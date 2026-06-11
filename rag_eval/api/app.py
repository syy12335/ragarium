from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rag_eval.app_config import AppConfigService
from rag_eval.eval_engine import EvalEngine, RagEvalRecord
from rag_eval.ingestion import BrowserSessionManager, IngestionService
from rag_eval.query_generation import QueryGenerationService
from rag_eval.storage import ProductStore
from rag_eval.vector.vector_builder import VectorDatabaseBuilder
from rag_eval.workflow import (
    DEFAULT_TEMPLATE_ID,
    EVALUATION_TEMPLATE_ID,
    LEGACY_FULL_RAG_TEMPLATE_ID,
    RAG_TEMPLATE_ID,
    WorkflowEngine,
    WorkflowValidationError,
    get_default_workflow_graph,
    get_workflow_templates,
)


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1)


class UrlImportRequest(BaseModel):
    url: str = Field(min_length=1)
    chunk_size: Optional[int] = Field(default=None, gt=0)
    chunk_overlap: Optional[int] = Field(default=None, ge=0)


class AppConfigRequest(BaseModel):
    providers: Dict[str, Dict[str, Any]]
    roles: Dict[str, Dict[str, Any]]
    chunk: Dict[str, int]
    api_keys: Dict[str, str] = Field(default_factory=dict)


class IndexRequest(BaseModel):
    overwrite: bool = True


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=1)
    graph: Dict[str, Any]
    id: Optional[int] = None


class WorkflowRunRequest(BaseModel):
    knowledge_base_id: Optional[int] = None
    question: str = Field(min_length=1)
    k: int = 3


class WorkflowExecuteRequest(BaseModel):
    inputs: Dict[str, Any] = {}


class RuntimeInvokeRequest(BaseModel):
    question: str = ""


class RuntimeBatchRequest(BaseModel):
    questions: List[str] = []


class QueryGenerateRequest(BaseModel):
    knowledge_base_id: int
    examples: List[str]
    target_count: int = Field(gt=0, le=500)
    name: str = "Generated queries"


class EvalRunRequest(BaseModel):
    query_set_id: int
    workflow_id: int
    limit: Optional[int] = None


VectorBuilderFactory = Callable[[], VectorDatabaseBuilder]
QueryGeneratorFactory = Callable[[], QueryGenerationService]
EvalEngineFactory = Callable[[], Any]


def _default_state_root() -> Path:
    return Path(os.environ.get("RAG_EVAL_APP_HOME", "var/app"))


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, WorkflowValidationError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


class WorkflowRunner:
    def __init__(
        self,
        *,
        workflow_engine: WorkflowEngine,
        graph: Dict[str, Any],
        vector_manager: Any,
        collection_name: str,
        config_path: str,
        k: int = 3,
    ) -> None:
        self.workflow_engine = workflow_engine
        self.graph = graph
        self.vector_manager = vector_manager
        self.collection_name = collection_name
        self.config_path = config_path
        self.k = k

    def invoke(self, question: str) -> Dict[str, Any]:
        return self.workflow_engine.run_question(
            self.graph,
            question=question,
            vector_manager=self.vector_manager,
            collection_name=self.collection_name,
            config_path=self.config_path,
            k=self.k,
        )


def _resolve_workflow_knowledge_base_id(
    workflow_engine: WorkflowEngine,
    workflow: Dict[str, Any],
    fallback_id: Optional[int],
) -> int:
    return workflow_engine.resolve_knowledge_base_id(workflow["graph"])


def _runtime_success(output: Any, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "output": output,
        "metadata": metadata or {},
    }


def _runtime_error(
    code: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
        "metadata": metadata or {},
    }


def create_app(
    *,
    store: Optional[ProductStore] = None,
    ingestion_service: Optional[IngestionService] = None,
    workflow_engine: Optional[WorkflowEngine] = None,
    vector_builder_factory: Optional[VectorBuilderFactory] = None,
    query_generator_factory: Optional[QueryGeneratorFactory] = None,
    eval_engine_factory: Optional[EvalEngineFactory] = None,
    browser_session_manager: Optional[Any] = None,
    config_path: str = "config/application.yaml",
) -> FastAPI:
    state_root = _default_state_root()
    store = store or ProductStore(state_root / "state.sqlite")
    config_service = AppConfigService(config_path, secrets_path=state_root / "provider_keys.yaml")
    ingestion_service = ingestion_service or IngestionService(
        store,
        state_root / "uploads",
        config_service=config_service,
    )
    workflow_engine = workflow_engine or WorkflowEngine()
    browser_session_manager = browser_session_manager or BrowserSessionManager(state_root / "browser_profile")

    def default_vector_builder_factory() -> VectorDatabaseBuilder:
        return VectorDatabaseBuilder(config_path)

    vector_builder_factory = vector_builder_factory or default_vector_builder_factory
    query_generator_factory = query_generator_factory or (
        lambda: QueryGenerationService(store, config_path=config_path)
    )
    eval_engine_factory = eval_engine_factory or (
        lambda: EvalEngine(
            config_path=config_path,
            metric_preset="reference_free",
            show_progress=False,
        )
    )

    app = FastAPI(title="RAG Eval Scaffold API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    def workflow_capabilities(workflow: Dict[str, Any]) -> Dict[str, Any]:
        graph = workflow["graph"]
        item = {
            "template_id": graph.get("templateId") or graph.get("template_id"),
            "executable": False,
            "runtime_capable": False,
            "prepare_capable": False,
            "evaluation_capable": False,
            "start_fields": [],
            "execution_error": None,
        }
        try:
            structure = workflow_engine.validate_graph_structure(graph)
            item["template_id"] = structure.template_id
            item["start_fields"] = workflow_engine.get_start_fields(graph)
        except Exception as exc:
            item["execution_error"] = str(exc)
            return item
        try:
            workflow_engine.validate_executable_graph(graph)
            item["executable"] = True
            item["runtime_capable"] = workflow_engine.is_runtime_graph(graph)
            item["prepare_capable"] = workflow_engine.is_prepare_graph(graph)
            item["evaluation_capable"] = workflow_engine.is_evaluation_graph(graph)
        except Exception as exc:
            item["execution_error"] = str(exc)
        return item

    def with_workflow_capabilities(workflow: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **workflow,
            **workflow_capabilities(workflow),
        }

    def runtime_top_k(graph: Dict[str, Any]) -> int:
        validation = workflow_engine.validate_graph_structure(graph)
        return workflow_engine.get_top_k_from_validation(validation)

    def runtime_workflow_item(workflow: Dict[str, Any]) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "workflow_id": workflow["id"],
            "name": workflow["name"],
            "template_id": None,
            "updated_at": workflow.get("updated_at"),
            "knowledge_base_id": None,
            "knowledge_base_name": None,
            "collection_name": None,
            "index_status": None,
            "top_k": None,
            "can_run": False,
            "error": None,
        }
        try:
            validation = workflow_engine.validate_executable_graph(workflow["graph"])
            item["template_id"] = validation.template_id
            if not workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("Workflow is not a runtime RAG graph")
            kb_id = workflow_engine.resolve_knowledge_base_id(workflow["graph"])
            kb = store.get_knowledge_base(kb_id)
            item.update(
                {
                    "knowledge_base_id": kb["id"],
                    "knowledge_base_name": kb["name"],
                    "collection_name": kb["collection_name"],
                    "index_status": kb["index_status"],
                    "top_k": runtime_top_k(workflow["graph"]),
                    "can_run": kb["index_status"] == "ready",
                }
            )
            if not item["can_run"]:
                item["error"] = {
                    "code": "index_not_ready",
                    "message": "Workflow 绑定的知识库索引未就绪",
                }
        except KeyError as exc:
            item["error"] = {"code": "knowledge_base_not_found", "message": str(exc)}
        except Exception as exc:
            item["error"] = {"code": "workflow_invalid", "message": str(exc)}
        return item

    def runtime_context(workflow_id: int) -> Dict[str, Any]:
        try:
            workflow = store.get_workflow(workflow_id)
        except KeyError as exc:
            return {
                "error": _runtime_error(
                    "workflow_not_found",
                    str(exc),
                    {"workflow_id": workflow_id},
                )
            }

        try:
            validation = workflow_engine.validate_executable_graph(workflow["graph"])
            if not workflow_engine.is_runtime_graph(workflow["graph"]):
                return {
                    "error": _runtime_error(
                        "workflow_not_callable",
                        "Runtime API 只支持可从 question 执行到 Answer 的 RAG graph",
                        {"workflow_id": workflow_id, "template_id": validation.template_id},
                    )
                }
            kb_id = workflow_engine.resolve_knowledge_base_id(workflow["graph"])
            kb = store.get_knowledge_base(kb_id)
            top_k = runtime_top_k(workflow["graph"])
        except KeyError as exc:
            return {
                "error": _runtime_error(
                    "knowledge_base_not_found",
                    str(exc),
                    {"workflow_id": workflow_id},
                )
            }
        except Exception as exc:
            return {
                "error": _runtime_error(
                    "workflow_invalid",
                    str(exc),
                    {"workflow_id": workflow_id},
                )
            }

        metadata = {
            "workflow_id": workflow_id,
            "knowledge_base_id": kb["id"],
            "collection_name": kb["collection_name"],
            "top_k": top_k,
        }
        if kb["index_status"] != "ready":
            return {
                "error": _runtime_error(
                    "index_not_ready",
                    "Workflow 绑定的知识库索引未就绪，请先在产品内准备索引",
                    {
                        **metadata,
                        "index_status": kb["index_status"],
                    },
                )
            }

        return {
            "workflow": workflow,
            "knowledge_base": kb,
            "metadata": metadata,
        }

    def runtime_invoke_question(
        workflow: Dict[str, Any],
        kb: Dict[str, Any],
        question: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = workflow_engine.run_question(
            workflow["graph"],
            question=question,
            vector_manager=vector_builder_factory().manager,
            collection_name=kb["collection_name"],
            config_path=config_path,
        )
        contexts = result.get("contexts") or []
        output = {
            "question": result.get("question") or question,
            "answer": result.get("answer") or result.get("generation") or "",
            "contexts": contexts,
        }
        return _runtime_success(
            output,
            {
                **metadata,
                "context_count": len(contexts),
            },
        )

    @app.get("/api/runtime/capabilities")
    def runtime_capabilities() -> Dict[str, Any]:
        return _runtime_success(
            {
                "contract_version": "v1",
                "transport": "http-json",
                "capabilities": {
                    "workflow_invoke": True,
                    "workflow_batch": True,
                    "node_invoke": False,
                    "prepare": False,
                },
                "endpoints": {
                    "list_workflows": "GET /api/runtime/workflows",
                    "invoke": "POST /api/runtime/workflows/{workflow_id}/invoke",
                    "batch": "POST /api/runtime/workflows/{workflow_id}/batch",
                },
                "schemas": {
                    "invoke_request": {"question": "string"},
                    "batch_request": {"questions": ["string"]},
                    "response": {
                        "ok": "boolean",
                        "output": "object | array",
                        "metadata": "object",
                        "error": {"code": "string", "message": "string"},
                    },
                },
                "examples": {
                    "curl": (
                        "curl -X POST http://127.0.0.1:8000/api/runtime/workflows/1/invoke "
                        "-H 'Content-Type: application/json' "
                        "-d '{\"question\":\"如何导入文档？\"}'"
                    )
                },
            },
            {"service": "rag-eval-runtime"},
        )

    @app.get("/api/runtime/workflows")
    def runtime_workflows() -> Dict[str, Any]:
        workflows = []
        for workflow in store.list_workflows():
            try:
                workflow_engine.validate_executable_graph(workflow["graph"])
            except Exception:
                continue
            if workflow_engine.is_runtime_graph(workflow["graph"]):
                workflows.append(runtime_workflow_item(workflow))
        return _runtime_success(
            {"workflows": workflows},
            {"count": len(workflows)},
        )

    @app.post("/api/deployment/local/start")
    def deploy_local_runtime() -> Dict[str, Any]:
        base_url = "http://127.0.0.1:8000"
        workflows = []
        for workflow in store.list_workflows():
            try:
                workflow_engine.validate_executable_graph(workflow["graph"])
            except Exception:
                continue
            if workflow_engine.is_runtime_graph(workflow["graph"]):
                workflows.append(runtime_workflow_item(workflow))

        workflow_contracts = []
        for workflow in workflows:
            workflow_id = workflow["workflow_id"]
            workflow_contracts.append(
                {
                    **workflow,
                    "invoke": {
                        "method": "POST",
                        "url": f"{base_url}/api/runtime/workflows/{workflow_id}/invoke",
                        "request": {"question": "如何导入文档？"},
                        "response": {
                            "ok": True,
                            "output": {
                                "question": "如何导入文档？",
                                "answer": "string",
                                "contexts": ["string"],
                            },
                            "metadata": {
                                "workflow_id": workflow_id,
                                "knowledge_base_id": workflow.get("knowledge_base_id"),
                                "collection_name": workflow.get("collection_name"),
                                "top_k": workflow.get("top_k"),
                                "context_count": "number",
                            },
                        },
                        "curl": (
                            f"curl -X POST {base_url}/api/runtime/workflows/{workflow_id}/invoke "
                            "-H 'Content-Type: application/json' "
                            "-d '{\"question\":\"如何导入文档？\"}'"
                        ),
                    },
                    "batch": {
                        "method": "POST",
                        "url": f"{base_url}/api/runtime/workflows/{workflow_id}/batch",
                        "request": {"questions": ["如何导入文档？", "如何运行评测？"]},
                        "response": {
                            "ok": True,
                            "output": {"items": ["Runtime response item"]},
                            "metadata": {
                                "workflow_id": workflow_id,
                                "count": "number",
                            },
                        },
                        "curl": (
                            f"curl -X POST {base_url}/api/runtime/workflows/{workflow_id}/batch "
                            "-H 'Content-Type: application/json' "
                            "-d '{\"questions\":[\"如何导入文档？\",\"如何运行评测？\"]}'"
                        ),
                    },
                }
            )

        ready_count = sum(1 for workflow in workflows if workflow.get("can_run"))
        return _runtime_success(
            {
                "status": "running",
                "message": "本地 Runtime API 已就绪，可通过 HTTP/JSON 从其他语言调用。",
                "contract_version": "v1",
                "base_url": base_url,
                "endpoints": {
                    "capabilities": "GET /api/runtime/capabilities",
                    "workflows": "GET /api/runtime/workflows",
                    "invoke": "POST /api/runtime/workflows/{workflow_id}/invoke",
                    "batch": "POST /api/runtime/workflows/{workflow_id}/batch",
                },
                "graph_contract": {
                    "input": {"question": "string"},
                    "batch_input": {"questions": ["string"]},
                    "output": {
                        "ok": True,
                        "output": {
                            "question": "string",
                            "answer": "string",
                            "contexts": ["string"],
                        },
                        "metadata": {
                            "workflow_id": "number",
                            "knowledge_base_id": "number",
                            "collection_name": "string",
                            "top_k": "number",
                            "context_count": "number",
                        },
                    },
                },
                "examples": {
                    "list_workflows": f"curl -s {base_url}/api/runtime/workflows",
                    "invoke": (
                        f"curl -X POST {base_url}/api/runtime/workflows/1/invoke "
                        "-H 'Content-Type: application/json' "
                        "-d '{\"question\":\"如何导入文档？\"}'"
                    ),
                    "batch": (
                        f"curl -X POST {base_url}/api/runtime/workflows/1/batch "
                        "-H 'Content-Type: application/json' "
                        "-d '{\"questions\":[\"如何导入文档？\",\"如何运行评测？\"]}'"
                    ),
                },
                "workflows": workflow_contracts,
            },
            {
                "service": "rag-eval-runtime",
                "workflow_count": len(workflows),
                "ready_workflow_count": ready_count,
            },
        )

    @app.post("/api/runtime/workflows/{workflow_id}/invoke")
    def runtime_invoke(workflow_id: int, payload: Optional[RuntimeInvokeRequest] = None) -> Dict[str, Any]:
        question = (payload.question if payload else "").strip()
        if not question:
            return _runtime_error(
                "invalid_question",
                "question 不能为空",
                {"workflow_id": workflow_id},
            )
        context = runtime_context(workflow_id)
        if "error" in context:
            return context["error"]
        try:
            return runtime_invoke_question(
                context["workflow"],
                context["knowledge_base"],
                question,
                context["metadata"],
            )
        except Exception as exc:
            return _runtime_error(
                "workflow_run_failed",
                str(exc),
                context["metadata"],
            )

    @app.post("/api/runtime/workflows/{workflow_id}/batch")
    def runtime_batch(workflow_id: int, payload: Optional[RuntimeBatchRequest] = None) -> Dict[str, Any]:
        if not payload or not payload.questions:
            return _runtime_error(
                "invalid_questions",
                "questions 不能为空",
                {"workflow_id": workflow_id},
            )
        context = runtime_context(workflow_id)
        if "error" in context:
            return context["error"]

        items = []
        for index, raw_question in enumerate(payload.questions):
            question = raw_question.strip()
            item_metadata = {
                **context["metadata"],
                "index": index,
            }
            if not question:
                items.append(
                    _runtime_error(
                        "invalid_question",
                        "question 不能为空",
                        item_metadata,
                    )
                )
                continue
            try:
                items.append(
                    runtime_invoke_question(
                        context["workflow"],
                        context["knowledge_base"],
                        question,
                        item_metadata,
                    )
                )
            except Exception as exc:
                items.append(
                    _runtime_error(
                        "workflow_run_failed",
                        str(exc),
                        item_metadata,
                    )
                )
        return _runtime_success(
            {"items": items},
            {
                **context["metadata"],
                "count": len(items),
            },
        )

    @app.get("/api/config")
    def get_config() -> Dict[str, Any]:
        try:
            return config_service.read()
        except Exception as exc:
            raise _http_error(exc)

    @app.put("/api/config")
    def update_config(payload: AppConfigRequest) -> Dict[str, Any]:
        try:
            return config_service.update(payload.model_dump())
        except Exception as exc:
            raise _http_error(exc)

    @app.get("/api/knowledge-bases")
    def list_knowledge_bases() -> List[Dict[str, Any]]:
        return store.list_knowledge_bases()

    @app.post("/api/knowledge-bases")
    def create_knowledge_base(payload: CreateKnowledgeBaseRequest) -> Dict[str, Any]:
        try:
            return store.create_knowledge_base(payload.name)
        except Exception as exc:
            raise _http_error(exc)

    @app.get("/api/knowledge-bases/{knowledge_base_id}")
    def get_knowledge_base(knowledge_base_id: int) -> Dict[str, Any]:
        try:
            kb = store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = store.list_sources(knowledge_base_id)
            kb["chunks"] = store.list_chunks(knowledge_base_id, limit=20)
            return kb
        except Exception as exc:
            raise _http_error(exc)

    def update_kb_status_after_ingestion_failure(knowledge_base_id: int, error: str) -> None:
        sources = store.list_sources(knowledge_base_id)
        chunks = store.list_chunks(knowledge_base_id)
        if chunks:
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="stale",
                error=None,
            )
            return
        if sources:
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="failed",
                error=error,
            )
            return
        store.update_knowledge_base_index_status(
            knowledge_base_id,
            status="not_indexed",
            error=None,
        )

    @app.post("/api/knowledge-bases/{knowledge_base_id}/files")
    async def upload_file(
        knowledge_base_id: int,
        file: UploadFile = File(...),
        chunk_size: Optional[int] = Form(default=None),
        chunk_overlap: Optional[int] = Form(default=None),
    ) -> Dict[str, Any]:
        try:
            data = await file.read()
            source = ingestion_service.ingest_bytes(
                knowledge_base_id,
                filename=file.filename or "upload.txt",
                data=data,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="stale",
                chunk_config={
                    "chunk_size": chunk_size,
                    "chunk_overlap": chunk_overlap,
                },
            )
            return source
        except Exception as exc:
            try:
                update_kb_status_after_ingestion_failure(knowledge_base_id, str(exc))
            except Exception:
                pass
            raise _http_error(exc)

    @app.post("/api/knowledge-bases/{knowledge_base_id}/urls")
    def import_url(knowledge_base_id: int, payload: UrlImportRequest) -> Dict[str, Any]:
        try:
            source = ingestion_service.ingest_url(
                knowledge_base_id,
                payload.url,
                chunk_size=payload.chunk_size,
                chunk_overlap=payload.chunk_overlap,
            )
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="stale",
                chunk_config={
                    "chunk_size": payload.chunk_size,
                    "chunk_overlap": payload.chunk_overlap,
                },
            )
            return source
        except Exception as exc:
            try:
                update_kb_status_after_ingestion_failure(knowledge_base_id, str(exc))
            except Exception:
                pass
            raise _http_error(exc)

    @app.delete("/api/knowledge-bases/{knowledge_base_id}/sources/{source_id}")
    def delete_source(knowledge_base_id: int, source_id: int) -> Dict[str, Any]:
        try:
            source = store.delete_source(knowledge_base_id, source_id)
            stored_path = source.get("stored_path")
            if stored_path:
                try:
                    file_path = Path(stored_path).resolve()
                    upload_root = ingestion_service.upload_root.resolve()
                    if file_path == upload_root or upload_root in file_path.parents:
                        file_path.unlink(missing_ok=True)
                except Exception:
                    pass

            remaining_sources = store.list_sources(knowledge_base_id)
            remaining_chunks = store.list_chunks(knowledge_base_id)
            if not remaining_sources:
                store.update_knowledge_base_index_status(
                    knowledge_base_id,
                    status="not_indexed",
                    error=None,
                )
            elif remaining_chunks:
                store.update_knowledge_base_index_status(
                    knowledge_base_id,
                    status="stale",
                    error=None,
                )
            else:
                store.update_knowledge_base_index_status(
                    knowledge_base_id,
                    status="failed",
                    error="当前知识库没有可索引 chunks，请先导入可解析的来源",
                )

            kb = store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = remaining_sources
            kb["chunks"] = store.list_chunks(knowledge_base_id, limit=20)
            return {"deleted_source": source, "knowledge_base": kb}
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/knowledge-bases/{knowledge_base_id}/sources/{source_id}/browser-session")
    def open_source_browser_session(knowledge_base_id: int, source_id: int) -> Dict[str, Any]:
        try:
            source = store.get_source(source_id)
            if int(source["knowledge_base_id"]) != int(knowledge_base_id) or source.get("source_type") != "url":
                raise KeyError(f"url source not found: {source_id}")
            return browser_session_manager.open_source(source)
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/browser-sessions/{session_id}/extract")
    def extract_browser_session(session_id: str) -> Dict[str, Any]:
        try:
            extracted = browser_session_manager.extract(session_id)
            knowledge_base_id = int(extracted["knowledge_base_id"])
            source_id = int(extracted["source_id"])
            source = ingestion_service.update_url_source_from_parsed(
                knowledge_base_id,
                source_id,
                extracted["parsed"],
            )
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="stale",
                error=None,
            )
            kb = store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = store.list_sources(knowledge_base_id)
            kb["chunks"] = store.list_chunks(knowledge_base_id, limit=20)
            try:
                browser_session_manager.close(session_id)
            except Exception:
                pass
            return {
                "session_id": session_id,
                "source": source,
                "chunk_count": source.get("chunk_count", 0),
                "knowledge_base": kb,
                "status": "ready",
            }
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/browser-sessions/{session_id}/close")
    def close_browser_session(session_id: str) -> Dict[str, Any]:
        try:
            return browser_session_manager.close(session_id)
        except Exception as exc:
            raise _http_error(exc)

    def build_knowledge_base_index(
        knowledge_base_id: int,
        *,
        overwrite: bool = True,
        chunk_config: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        store.update_knowledge_base_index_status(
            knowledge_base_id,
            status="indexing",
            error=None,
            chunk_config=chunk_config,
        )
        try:
            kb = store.get_knowledge_base(knowledge_base_id)
            chunks = store.list_chunks(knowledge_base_id)
            builder = vector_builder_factory()
            builder.build_from_chunks(
                chunks,
                collection_name=kb["collection_name"],
                overwrite=overwrite,
            )
            kb = store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="ready",
                error=None,
                chunk_config=chunk_config,
            )
            return {
                "knowledge_base_id": knowledge_base_id,
                "collection_name": kb["collection_name"],
                "chunk_count": len(chunks),
                "index_status": kb["index_status"],
                "indexed_at": kb["indexed_at"],
                "chunk_config": kb["chunk_config"],
            }
        except Exception as exc:
            store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="failed",
                error=str(exc),
                chunk_config=chunk_config,
            )
            raise

    @app.post("/api/knowledge-bases/{knowledge_base_id}/index")
    def build_index(knowledge_base_id: int, payload: IndexRequest) -> Dict[str, Any]:
        try:
            result = build_knowledge_base_index(knowledge_base_id, overwrite=payload.overwrite)
            result["status"] = result["index_status"]
            return result
        except Exception as exc:
            raise _http_error(exc)

    def run_query_generate_node_for_workflow(
        workflow: Dict[str, Any],
        *,
        node_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = workflow_engine.get_query_generate_config(workflow["graph"], node_id=node_id)
        generator = query_generator_factory()
        return generator.generate(
            knowledge_base_id=config["knowledge_base_id"],
            examples=config["examples"],
            target_count=config["target_count"],
            name=config["name"],
        )

    def normalize_context_texts(raw_contexts: Any) -> List[str]:
        if raw_contexts is None:
            return []
        if not isinstance(raw_contexts, list):
            raise ValueError("runner 返回的 contexts 字段必须是列表类型")
        contexts: List[str] = []
        for item in raw_contexts:
            if isinstance(item, str):
                contexts.append(item)
                continue
            if isinstance(item, dict):
                if "content" in item:
                    contexts.append(str(item["content"]))
                    continue
                if "page_content" in item:
                    contexts.append(str(item["page_content"]))
                    continue
            page_content = getattr(item, "page_content", None)
            if page_content is None:
                raise ValueError("contexts 元素必须是 str、包含 content/page_content 的 dict，或包含 page_content 属性")
            contexts.append(str(page_content))
        return contexts

    def evaluate_records_with_engine(records: List[RagEvalRecord]) -> Any:
        evaluator = eval_engine_factory()
        if hasattr(evaluator, "evaluate_records"):
            return evaluator.evaluate_records(records)
        if hasattr(evaluator, "evaluate"):
            return evaluator.evaluate(records)

        class AnswerRecordRunner:
            def __init__(self, items: List[RagEvalRecord]) -> None:
                self.records_by_question = {item.question: item for item in items}

            def invoke(self, question: str) -> Dict[str, Any]:
                record = self.records_by_question[question]
                return {
                    "question": record.question,
                    "answer": record.answer,
                    "contexts": record.contexts,
                }

        samples = [
            {
                "question": record.question,
                **({"ground_truth": record.ground_truth} if record.ground_truth else {}),
            }
            for record in records
        ]
        return evaluator.invoke(AnswerRecordRunner(records), samples)

    def generate_answer_records_for_query_set(
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        limit: Optional[int],
    ) -> Dict[str, Any]:
        validation = workflow_engine.validate_executable_graph(workflow["graph"])
        types = {
            node.get("type")
            for node in validation.ordered_nodes
        }
        if not {"retrieve", "prompt_llm", "answer"}.issubset(types):
            raise WorkflowValidationError("Eval run requires a graph with Retrieve, Prompt / LLM and Answer nodes")
        kb_id = workflow_engine.resolve_knowledge_base_id(workflow["graph"])
        kb = store.get_knowledge_base(kb_id)
        if kb["index_status"] != "ready":
            raise ValueError("knowledge base index is not ready")

        queries = list(query_set["queries"])
        if limit:
            queries = queries[:limit]

        vector_manager = vector_builder_factory().manager
        top_k = workflow_engine.get_top_k_from_validation(validation)
        rag_records: List[RagEvalRecord] = []
        answer_records: List[Dict[str, Any]] = []
        for index, query in enumerate(queries):
            result = workflow_engine.run_question(
                workflow["graph"],
                question=str(query),
                vector_manager=vector_manager,
                collection_name=kb["collection_name"],
                config_path=config_path,
                k=top_k,
            )
            contexts = normalize_context_texts(result.get("contexts") or [])
            question = str(result.get("question") or query)
            answer = str(result.get("answer") or result.get("generation") or "")
            meta = {
                "idx": index,
                "mode": "workflow_answer",
                "query_set_id": query_set["id"],
                "workflow_id": workflow["id"],
            }
            rag_records.append(
                RagEvalRecord(
                    question=question,
                    answer=answer,
                    contexts=contexts,
                    ground_truth=None,
                    meta=meta,
                )
            )
            answer_records.append(
                {
                    "question": question,
                    "answer": answer,
                    "contexts": contexts,
                    "meta": meta,
                }
            )

        return {
            "records": rag_records,
            "items": answer_records,
            "count": len(answer_records),
            "knowledge_base_id": kb_id,
            "collection_name": kb["collection_name"],
            "top_k": top_k,
        }

    def create_eval_run_from_answer_records(
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        records: List[RagEvalRecord],
    ) -> Dict[str, Any]:
        result = evaluate_records_with_engine(records)
        return store.create_eval_run(
            query_set_id=query_set["id"],
            workflow_id=workflow["id"],
            status="completed",
            metrics=result.overall,
            output_csv=result.csv_path,
        )

    def create_eval_run_from_query_set(
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        limit: Optional[int],
    ) -> Dict[str, Any]:
        answer_batch = generate_answer_records_for_query_set(
            query_set=query_set,
            workflow=workflow,
            limit=limit,
        )
        return create_eval_run_from_answer_records(
            query_set=query_set,
            workflow=workflow,
            records=answer_batch["records"],
        )

    def summarize_node_output(node_type: str, state: Dict[str, Any]) -> Dict[str, Any]:
        if node_type == "embed_index":
            result = state.get("index_result") or {}
            return {
                "knowledge_base_id": result.get("knowledge_base_id"),
                "chunk_count": result.get("chunk_count"),
                "index_status": result.get("index_status"),
            }
        if node_type == "query_generate":
            query_set = state.get("query_set") or {}
            return {
                "query_set_id": query_set.get("id"),
                "query_count": len(query_set.get("queries") or []),
            }
        if node_type == "answer":
            if state.get("answer_records") is not None:
                return {
                    "answer_count": state.get("answer_count", 0),
                    "query_set_id": (state.get("query_set") or {}).get("id"),
                    "context_count": sum(len(item.get("contexts") or []) for item in state.get("answer_records") or []),
                }
            return {
                "question": state.get("question"),
                "answer": state.get("answer"),
                "context_count": len(state.get("contexts") or []),
            }
        if node_type == "ragas_eval":
            eval_run = state.get("eval_run") or {}
            return {
                "eval_run_id": eval_run.get("id"),
                "status": eval_run.get("status"),
                "metrics": eval_run.get("metrics"),
            }
        return {"ok": True}

    def default_end_outputs(state: Dict[str, Any]) -> Dict[str, Any]:
        outputs: Dict[str, Any] = {}
        for key in [
            "knowledge_base_id",
            "index_result",
            "query_set",
            "question",
            "answer",
            "answer_count",
            "contexts",
            "eval_run",
        ]:
            if key in state:
                outputs[key] = state[key]
        return outputs

    def collect_end_outputs(node: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        outputs = (node.get("data") or {}).get("outputs") or []
        if not outputs:
            return default_end_outputs(state)
        collected: Dict[str, Any] = {}
        for output in outputs:
            if isinstance(output, str):
                name = output
                source = output
            else:
                name = str(output.get("name") or output.get("key") or "").strip()
                source = str(output.get("source") or output.get("key") or name).strip()
            if not name:
                continue
            collected[name] = state.get(source)
        return collected

    def execute_workflow(workflow: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        graph = workflow["graph"]
        validation = workflow_engine.validate_executable_graph(graph)
        if validation.is_legacy:
            question = (inputs or {}).get("question")
            if not question:
                raise WorkflowValidationError("legacy RAG workflow requires question input")
            kb_id = workflow_engine.resolve_knowledge_base_id(graph)
            kb = store.get_knowledge_base(kb_id)
            if kb["index_status"] != "ready":
                raise ValueError("knowledge base index is not ready")
            result = workflow_engine.run_question(
                graph,
                question=str(question),
                vector_manager=vector_builder_factory().manager,
                collection_name=kb["collection_name"],
                config_path=config_path,
            )
            return {
                "workflow_id": workflow["id"],
                "outputs": result,
                "trace": [{"node_id": "legacy_full_rag", "type": "legacy_full_rag", "status": "completed"}],
                "metadata": {"workflow_id": workflow["id"], "legacy": True},
            }

        state: Dict[str, Any] = {}
        trace = []
        for node in validation.ordered_nodes:
            node_id = node["id"]
            node_type = node["type"]
            data = node.get("data") or {}

            if node_type == "start":
                state.update(workflow_engine.resolve_start_inputs(graph, inputs or {}))
            elif node_type == "source":
                kb_id = workflow_engine.get_source_knowledge_base_id_from_validation(validation)
                kb = store.get_knowledge_base(kb_id)
                state["knowledge_base_id"] = kb_id
                state["collection_name"] = kb["collection_name"]
            elif node_type == "parse":
                state["parser"] = data.get("parser") or "auto"
            elif node_type == "chunk":
                state["chunk_config"] = workflow_engine.get_chunk_config_from_validation(validation)
            elif node_type == "embed_index":
                kb_id = state.get("knowledge_base_id")
                if not kb_id:
                    raise WorkflowValidationError("Embed / Index node requires upstream Source DB")
                chunk_config = state.get("chunk_config") or {"chunk_size": 900, "chunk_overlap": 120}
                store.update_knowledge_base_index_status(
                    kb_id,
                    status="processing",
                    error=None,
                    chunk_config=chunk_config,
                )
                ingestion_service.reprocess_knowledge_base_sources(
                    kb_id,
                    chunk_size=chunk_config["chunk_size"],
                    chunk_overlap=chunk_config["chunk_overlap"],
                )
                index_result = build_knowledge_base_index(
                    kb_id,
                    overwrite=data.get("overwrite", True) is not False,
                    chunk_config=chunk_config,
                )
                state["index_result"] = index_result
            elif node_type == "query_generate":
                query_set = run_query_generate_node_for_workflow(workflow, node_id=node_id)
                state["query_set"] = query_set
                state["queries"] = query_set["queries"]
                state["knowledge_base_id"] = query_set["knowledge_base_id"]
            elif node_type == "retrieve":
                kb_id = workflow_engine.get_retrieve_knowledge_base_id_from_validation(validation, required=False)
                if kb_id is not None:
                    state["knowledge_base_id"] = kb_id
                if "knowledge_base_id" not in state:
                    raise WorkflowValidationError("Retrieve node requires selected or upstream knowledge DB")
                state["top_k"] = workflow_engine.get_top_k_from_validation(validation)
            elif node_type == "prompt_llm":
                state["prompt"] = data.get("prompt") or ""
            elif node_type == "answer":
                if state.get("queries"):
                    query_set = state.get("query_set")
                    if not query_set:
                        raise WorkflowValidationError("Answer node requires upstream Query Generate for batch answers")
                    answer_batch = generate_answer_records_for_query_set(
                        query_set=query_set,
                        workflow=workflow,
                        limit=None,
                    )
                    state["answer_records"] = answer_batch["items"]
                    state["_rag_eval_records"] = answer_batch["records"]
                    state["answer_count"] = answer_batch["count"]
                    state["collection_name"] = answer_batch["collection_name"]
                    state["top_k"] = answer_batch["top_k"]
                else:
                    question = state.get("question")
                    if not question:
                        raise WorkflowValidationError("Answer node requires question input")
                    kb = store.get_knowledge_base(int(state["knowledge_base_id"]))
                    if kb["index_status"] != "ready":
                        raise ValueError("knowledge base index is not ready")
                    result = workflow_engine.run_question(
                        graph,
                        question=str(question),
                        vector_manager=vector_builder_factory().manager,
                        collection_name=kb["collection_name"],
                        config_path=config_path,
                        k=int(state.get("top_k") or 3),
                    )
                    state["question"] = result.get("question") or str(question)
                    state["answer"] = result.get("answer") or result.get("generation") or ""
                    state["contexts"] = result.get("contexts") or []
            elif node_type == "ragas_eval":
                query_set = state.get("query_set")
                if not query_set:
                    raise WorkflowValidationError("RAGAS Eval node requires upstream Query Generate")
                records = state.get("_rag_eval_records") or []
                if not records:
                    raise WorkflowValidationError("RAGAS Eval node requires upstream Answer records")
                eval_config = workflow_engine.get_eval_config_from_validation(validation)
                eval_records = records[: eval_config["limit"]] if eval_config["limit"] else records
                eval_run = create_eval_run_from_answer_records(
                    query_set=query_set,
                    workflow=workflow,
                    records=eval_records,
                )
                state["eval_run"] = eval_run
            elif node_type == "end":
                state["outputs"] = collect_end_outputs(node, state)
            else:
                raise WorkflowValidationError(f"unsupported executable node type: {node_type}")

            trace.append(
                {
                    "node_id": node_id,
                    "type": node_type,
                    "status": "completed",
                    "output": summarize_node_output(node_type, state),
                }
            )

        outputs = state.get("outputs") or default_end_outputs(state)
        return {
            "workflow_id": workflow["id"],
            "outputs": outputs,
            "trace": trace,
            "metadata": {
                "workflow_id": workflow["id"],
                "template_id": validation.template_id,
                "node_count": len(validation.ordered_nodes),
            },
        }

    @app.get("/api/workflows/templates")
    def list_workflow_templates() -> List[Dict[str, Any]]:
        return get_workflow_templates()

    @app.get("/api/workflows/default")
    def get_default_workflow(template_id: str = DEFAULT_TEMPLATE_ID) -> Dict[str, Any]:
        try:
            graph = get_default_workflow_graph(template_id)
            template = next(item for item in get_workflow_templates() if item["id"] == template_id)
            return {"name": template["name"], "graph": graph}
        except Exception as exc:
            raise _http_error(exc)

    @app.get("/api/workflows")
    def list_workflows() -> List[Dict[str, Any]]:
        return [with_workflow_capabilities(workflow) for workflow in store.list_workflows()]

    @app.post("/api/workflows/validate")
    def validate_workflow(payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            validation = workflow_engine.validate_executable_graph(payload.graph)
            return {
                "ok": True,
                "template_id": validation.template_id,
                "node_count": len(validation.ordered_nodes),
                "runtime_capable": workflow_engine.is_runtime_graph(payload.graph),
                "prepare_capable": workflow_engine.is_prepare_graph(payload.graph),
                "evaluation_capable": workflow_engine.is_evaluation_graph(payload.graph),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @app.post("/api/workflows")
    def save_workflow(payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            workflow_engine.validate_graph_structure(payload.graph)
            return with_workflow_capabilities(store.upsert_workflow(payload.name, payload.graph, payload.id))
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/execute")
    def execute_workflow_route(workflow_id: int, payload: Optional[WorkflowExecuteRequest] = None) -> Dict[str, Any]:
        try:
            workflow = store.get_workflow(workflow_id)
            return execute_workflow(workflow, inputs=(payload.inputs if payload else {}))
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/prepare")
    def prepare_workflow(workflow_id: int) -> Dict[str, Any]:
        source_kb_id: Optional[int] = None
        try:
            workflow = store.get_workflow(workflow_id)
            if workflow_engine.validate_graph_structure(workflow["graph"]).nodes_by_type.get("start"):
                result = execute_workflow(workflow, inputs={})
                index_result = result["outputs"].get("index_result") or {}
                return {
                    "workflow_id": workflow_id,
                    **index_result,
                }
            if not workflow_engine.is_prepare_graph(workflow["graph"]):
                raise WorkflowValidationError("prepare only supports offline DB workflows")
            source_kb_id = workflow_engine.get_source_knowledge_base_id(workflow["graph"])
            chunk_config = workflow_engine.get_chunk_config(workflow["graph"])
            store.update_knowledge_base_index_status(
                source_kb_id,
                status="processing",
                error=None,
                chunk_config=chunk_config,
            )
            ingestion_result = ingestion_service.reprocess_knowledge_base_sources(
                source_kb_id,
                chunk_size=chunk_config["chunk_size"],
                chunk_overlap=chunk_config["chunk_overlap"],
            )
            index_result = build_knowledge_base_index(
                source_kb_id,
                overwrite=True,
                chunk_config=chunk_config,
            )
            return {
                "workflow_id": workflow_id,
                "knowledge_base_id": source_kb_id,
                "source_count": len(ingestion_result["sources"]),
                "chunk_count": index_result["chunk_count"],
                "collection_name": index_result["collection_name"],
                "index_status": index_result["index_status"],
                "indexed_at": index_result["indexed_at"],
                "chunk_config": chunk_config,
            }
        except Exception as exc:
            if source_kb_id is not None:
                try:
                    store.update_knowledge_base_index_status(
                        source_kb_id,
                        status="failed",
                        error=str(exc),
                    )
                except Exception:
                    pass
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/run")
    def run_workflow(workflow_id: int, payload: WorkflowRunRequest) -> Dict[str, Any]:
        try:
            workflow = store.get_workflow(workflow_id)
            if workflow_engine.validate_graph_structure(workflow["graph"]).nodes_by_type.get("start"):
                result = execute_workflow(workflow, inputs={"question": payload.question})
                outputs = result["outputs"]
                return {
                    "question": outputs.get("question") or payload.question,
                    "answer": outputs.get("answer") or outputs.get("generation") or "",
                    "contexts": outputs.get("contexts") or [],
                }
            if not workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("run only supports RAG workflows")
            kb_id = _resolve_workflow_knowledge_base_id(
                workflow_engine,
                workflow,
                None,
            )
            kb = store.get_knowledge_base(kb_id)
            if kb["index_status"] != "ready":
                raise ValueError("knowledge base index is not ready")
            vector_manager = vector_builder_factory().manager
            return workflow_engine.run_question(
                workflow["graph"],
                question=payload.question,
                vector_manager=vector_manager,
                collection_name=kb["collection_name"],
                config_path=config_path,
                k=payload.k,
            )
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/nodes/{node_id}/run")
    def run_workflow_node(workflow_id: int, node_id: str) -> Dict[str, Any]:
        try:
            workflow = store.get_workflow(workflow_id)
            query_set = run_query_generate_node_for_workflow(workflow, node_id=node_id)
            return {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": "query_generate",
                "query_set": query_set,
            }
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/evaluate")
    def evaluate_workflow(workflow_id: int) -> Dict[str, Any]:
        query_set: Optional[Dict[str, Any]] = None
        try:
            workflow = store.get_workflow(workflow_id)
            if workflow_engine.validate_graph_structure(workflow["graph"]).nodes_by_type.get("start"):
                result = execute_workflow(workflow, inputs={})
                return {
                    "workflow_id": workflow_id,
                    "query_set": result["outputs"].get("query_set"),
                    "answer_count": result["outputs"].get("answer_count"),
                    "eval_run": result["outputs"].get("eval_run"),
                    "trace": result["trace"],
                    "metadata": result["metadata"],
                }
            if not workflow_engine.is_evaluation_graph(workflow["graph"]):
                raise WorkflowValidationError("evaluate only supports evaluation workflows")
            eval_config = workflow_engine.get_eval_config(workflow["graph"])
            query_set = run_query_generate_node_for_workflow(workflow)
            eval_run = create_eval_run_from_query_set(
                query_set=query_set,
                workflow=workflow,
                limit=eval_config["limit"],
            )
            return {
                "workflow_id": workflow_id,
                "query_set": query_set,
                "eval_run": eval_run,
            }
        except Exception as exc:
            if query_set is not None:
                try:
                    workflow = store.get_workflow(workflow_id)
                    failed_run = store.create_eval_run(
                        query_set_id=query_set["id"],
                        workflow_id=workflow["id"],
                        status="failed",
                        metrics={},
                        error=str(exc),
                    )
                    return {
                        "workflow_id": workflow_id,
                        "query_set": query_set,
                        "eval_run": failed_run,
                    }
                except Exception:
                    pass
            raise _http_error(exc)

    @app.get("/api/query-sets")
    def list_query_sets(knowledge_base_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return store.list_query_sets(knowledge_base_id)

    @app.post("/api/query-sets/generate")
    def generate_query_set(payload: QueryGenerateRequest) -> Dict[str, Any]:
        try:
            generator = query_generator_factory()
            return generator.generate(
                knowledge_base_id=payload.knowledge_base_id,
                examples=payload.examples,
                target_count=payload.target_count,
                name=payload.name,
            )
        except Exception as exc:
            raise _http_error(exc)

    @app.get("/api/eval-runs")
    def list_eval_runs() -> List[Dict[str, Any]]:
        return store.list_eval_runs()

    @app.post("/api/eval-runs")
    def create_eval_run(payload: EvalRunRequest) -> Dict[str, Any]:
        try:
            query_set = store.get_query_set(payload.query_set_id)
            workflow = store.get_workflow(payload.workflow_id)
            if not workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("Eval run requires a RAG workflow")
            return create_eval_run_from_query_set(
                query_set=query_set,
                workflow=workflow,
                limit=payload.limit,
            )
        except Exception as exc:
            # A failed run is still durable product state; return it so the UI
            # can show the exact model/API-key/index failure instead of losing it.
            failed_run = None
            try:
                failed_run = store.create_eval_run(
                    query_set_id=payload.query_set_id,
                    workflow_id=payload.workflow_id,
                    status="failed",
                    metrics={},
                    error=str(exc),
                )
            except Exception:
                pass
            if failed_run is not None:
                return failed_run
            raise _http_error(exc)

    return app


app = create_app()
