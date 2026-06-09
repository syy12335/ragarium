from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rag_eval.app_config import AppConfigService
from rag_eval.eval_engine import EvalEngine
from rag_eval.ingestion import IngestionService
from rag_eval.query_generation import QueryGenerationService
from rag_eval.storage import ProductStore
from rag_eval.vector.vector_builder import VectorDatabaseBuilder
from rag_eval.workflow import DEFAULT_WORKFLOW_GRAPH, WorkflowEngine, WorkflowValidationError


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
    config_path: str = "config/application.yaml",
) -> FastAPI:
    state_root = _default_state_root()
    store = store or ProductStore(state_root / "state.sqlite")
    config_service = AppConfigService(config_path)
    ingestion_service = ingestion_service or IngestionService(
        store,
        state_root / "uploads",
        config_service=config_service,
    )
    workflow_engine = workflow_engine or WorkflowEngine()

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

    def runtime_top_k(graph: Dict[str, Any]) -> int:
        validation = workflow_engine.validate_graph(graph)
        retrieve_data = validation.nodes_by_type["retrieve"].get("data") or {}
        raw_top_k = retrieve_data.get("topK") or retrieve_data.get("k") or 3
        try:
            return int(raw_top_k)
        except (TypeError, ValueError):
            raise WorkflowValidationError("retrieve.topK must be an integer")

    def runtime_workflow_item(workflow: Dict[str, Any]) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "workflow_id": workflow["id"],
            "name": workflow["name"],
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
        workflows = [runtime_workflow_item(workflow) for workflow in store.list_workflows()]
        return _runtime_success(
            {"workflows": workflows},
            {"count": len(workflows)},
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

    @app.get("/api/workflows/default")
    def get_default_workflow() -> Dict[str, Any]:
        return {"name": "Default RAG workflow", "graph": DEFAULT_WORKFLOW_GRAPH}

    @app.get("/api/workflows")
    def list_workflows() -> List[Dict[str, Any]]:
        return store.list_workflows()

    @app.post("/api/workflows/validate")
    def validate_workflow(payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            workflow_engine.validate_graph(payload.graph)
            return {"ok": True}
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows")
    def save_workflow(payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            workflow_engine.validate_graph(payload.graph)
            return store.upsert_workflow(payload.name, payload.graph, payload.id)
        except Exception as exc:
            raise _http_error(exc)

    @app.post("/api/workflows/{workflow_id}/prepare")
    def prepare_workflow(workflow_id: int) -> Dict[str, Any]:
        source_kb_id: Optional[int] = None
        try:
            workflow = store.get_workflow(workflow_id)
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
            kb_id = _resolve_workflow_knowledge_base_id(
                workflow_engine,
                workflow,
                None,
            )
            kb = store.get_knowledge_base(kb_id)
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
            kb_id = _resolve_workflow_knowledge_base_id(
                workflow_engine,
                workflow,
                None,
            )
            kb = store.get_knowledge_base(kb_id)
            vector_manager = vector_builder_factory().manager
            runner = WorkflowRunner(
                workflow_engine=workflow_engine,
                graph=workflow["graph"],
                vector_manager=vector_manager,
                collection_name=kb["collection_name"],
                config_path=config_path,
            )
            samples = [{"question": query} for query in query_set["queries"]]
            if payload.limit:
                samples = samples[: payload.limit]
            result = eval_engine_factory().invoke(runner, samples)
            return store.create_eval_run(
                query_set_id=payload.query_set_id,
                workflow_id=payload.workflow_id,
                status="completed",
                metrics=result.overall,
                output_csv=result.csv_path,
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
