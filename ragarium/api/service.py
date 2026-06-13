from __future__ import annotations
from inspect import signature
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import File, Form, UploadFile
from ragarium.api.context import ApiContext
from ragarium.api.errors import (
    http_error,
    json_safe,
    runtime_error,
    runtime_success,
    utc_now,
)
from ragarium.api.schemas import (
    AppConfigRequest,
    CreateKnowledgeBaseRequest,
    EvalRunRequest,
    IndexRequest,
    QueryGenerateRequest,
    RetrievalTestRequest,
    RuntimeBatchRequest,
    RuntimeInvokeRequest,
    UrlImportRequest,
    WorkflowExecuteRequest,
    WorkflowRequest,
    WorkflowRunRequest,
)
from ragarium.api.task_runs import WorkflowProgressCallback, WorkflowTestRunManager
from ragarium.eval_engine import (
    EvalEngine,
    MetricValidationError,
    RagEvalRecord,
    list_metric_specs,
    resolve_ragas_metric_names,
    validate_metric_names,
)
from ragarium.workflow import (
    DEFAULT_TEMPLATE_ID,
    WorkflowEngine,
    WorkflowValidationError,
    get_default_workflow_graph,
    get_workflow_templates,
)


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


class ApiService:

    def __init__(self, context: ApiContext) -> None:
        self.context = context
        self.store = context.store
        self.config_service = context.config_service
        self.ingestion_service = context.ingestion_service
        self.workflow_engine = context.workflow_engine
        self.vector_builder_factory = context.vector_builder_factory
        self.query_generator_factory = context.query_generator_factory
        self.eval_engine_factory = context.eval_engine_factory
        self.browser_session_manager = context.browser_session_manager
        self.config_path = context.config_path
        self.test_runs = WorkflowTestRunManager(
            workflow_engine=self.workflow_engine, execute_workflow=self.execute_workflow
        )

    def build_eval_engine(self, metric_names: Optional[List[str]] = None) -> Any:
        if self.eval_engine_factory is None:
            metrics = resolve_ragas_metric_names(metric_names) if metric_names else None
            return EvalEngine(
                config_path=self.config_path,
                metrics=metrics,
                metric_preset=None if metrics else "reference_free",
                show_progress=False,
            )
        try:
            params = signature(self.eval_engine_factory).parameters
            if "metric_names" in params:
                return self.eval_engine_factory(metric_names=metric_names)
        except (TypeError, ValueError):
            pass
        return self.eval_engine_factory()

    def health(self) -> Dict[str, str]:
        return {"status": "ok"}

    def workflow_capabilities(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
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
            structure = self.workflow_engine.validate_graph_structure(graph)
            item["template_id"] = structure.template_id
            item["start_fields"] = self.workflow_engine.get_start_fields(graph)
        except Exception as exc:
            item["execution_error"] = str(exc)
            return item
        try:
            self.workflow_engine.validate_executable_graph(graph)
            item["executable"] = True
            item["runtime_capable"] = self.workflow_engine.is_runtime_graph(graph)
            item["prepare_capable"] = self.workflow_engine.is_prepare_graph(graph)
            item["evaluation_capable"] = self.workflow_engine.is_evaluation_graph(graph)
        except Exception as exc:
            item["execution_error"] = str(exc)
        return item

    def with_workflow_capabilities(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        return {**workflow, **self.workflow_capabilities(workflow)}

    def runtime_top_k(self, graph: Dict[str, Any]) -> int:
        validation = self.workflow_engine.validate_graph_structure(graph)
        return self.workflow_engine.get_top_k_from_validation(validation)

    def runtime_workflow_item(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
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
            validation = self.workflow_engine.validate_executable_graph(
                workflow["graph"]
            )
            item["template_id"] = validation.template_id
            if not self.workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("Workflow is not a runtime RAG graph")
            kb_id = self.workflow_engine.resolve_knowledge_base_id(workflow["graph"])
            kb = self.store.get_knowledge_base(kb_id)
            item.update(
                {
                    "knowledge_base_id": kb["id"],
                    "knowledge_base_name": kb["name"],
                    "collection_name": kb["collection_name"],
                    "index_status": kb["index_status"],
                    "top_k": self.runtime_top_k(workflow["graph"]),
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

    def runtime_context(self, workflow_id: int) -> Dict[str, Any]:
        try:
            workflow = self.store.get_workflow(workflow_id)
        except KeyError as exc:
            return {
                "error": runtime_error(
                    "workflow_not_found", str(exc), {"workflow_id": workflow_id}
                )
            }
        try:
            validation = self.workflow_engine.validate_executable_graph(
                workflow["graph"]
            )
            if not self.workflow_engine.is_runtime_graph(workflow["graph"]):
                return {
                    "error": runtime_error(
                        "workflow_not_callable",
                        "Runtime API 只支持可从 question 执行到 Answer 的 RAG graph",
                        {
                            "workflow_id": workflow_id,
                            "template_id": validation.template_id,
                        },
                    )
                }
            kb_id = self.workflow_engine.resolve_knowledge_base_id(workflow["graph"])
            kb = self.store.get_knowledge_base(kb_id)
            top_k = self.runtime_top_k(workflow["graph"])
        except KeyError as exc:
            return {
                "error": runtime_error(
                    "knowledge_base_not_found", str(exc), {"workflow_id": workflow_id}
                )
            }
        except Exception as exc:
            return {
                "error": runtime_error(
                    "workflow_invalid", str(exc), {"workflow_id": workflow_id}
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
                "error": runtime_error(
                    "index_not_ready",
                    "Workflow 绑定的知识库索引未就绪，请先在产品内准备索引",
                    {**metadata, "index_status": kb["index_status"]},
                )
            }
        return {"workflow": workflow, "knowledge_base": kb, "metadata": metadata}

    def runtime_invoke_question(
        self,
        workflow: Dict[str, Any],
        kb: Dict[str, Any],
        question: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = self.workflow_engine.run_question(
            workflow["graph"],
            question=question,
            vector_manager=self.vector_builder_factory().manager,
            collection_name=kb["collection_name"],
            config_path=self.config_path,
        )
        contexts = result.get("contexts") or []
        output = {
            "question": result.get("question") or question,
            "answer": result.get("answer") or result.get("generation") or "",
            "contexts": contexts,
        }
        return runtime_success(output, {**metadata, "context_count": len(contexts)})

    def runtime_capabilities(self) -> Dict[str, Any]:
        return runtime_success(
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
                    "curl": "curl -X POST http://127.0.0.1:8000/api/runtime/workflows/1/invoke -H 'Content-Type: application/json' -d '{\"question\":\"如何导入文档？\"}'"
                },
            },
            {"service": "ragarium-runtime"},
        )

    def runtime_workflows(self) -> Dict[str, Any]:
        workflows = []
        for workflow in self.store.list_workflows():
            try:
                self.workflow_engine.validate_executable_graph(workflow["graph"])
            except Exception:
                continue
            if self.workflow_engine.is_runtime_graph(workflow["graph"]):
                workflows.append(self.runtime_workflow_item(workflow))
        return runtime_success({"workflows": workflows}, {"count": len(workflows)})

    def deploy_local_runtime(self) -> Dict[str, Any]:
        base_url = "http://127.0.0.1:8000"
        workflows = []
        for workflow in self.store.list_workflows():
            try:
                self.workflow_engine.validate_executable_graph(workflow["graph"])
            except Exception:
                continue
            if self.workflow_engine.is_runtime_graph(workflow["graph"]):
                workflows.append(self.runtime_workflow_item(workflow))
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
                        "curl": f"""curl -X POST {base_url}/api/runtime/workflows/{workflow_id}/invoke -H 'Content-Type: application/json' -d '{{"question":"如何导入文档？"}}'""",
                    },
                    "batch": {
                        "method": "POST",
                        "url": f"{base_url}/api/runtime/workflows/{workflow_id}/batch",
                        "request": {"questions": ["如何导入文档？", "如何运行评测？"]},
                        "response": {
                            "ok": True,
                            "output": {"items": ["Runtime response item"]},
                            "metadata": {"workflow_id": workflow_id, "count": "number"},
                        },
                        "curl": f"""curl -X POST {base_url}/api/runtime/workflows/{workflow_id}/batch -H 'Content-Type: application/json' -d '{{"questions":["如何导入文档？","如何运行评测？"]}}'""",
                    },
                }
            )
        ready_count = sum((1 for workflow in workflows if workflow.get("can_run")))
        return runtime_success(
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
                    "invoke": f"""curl -X POST {base_url}/api/runtime/workflows/1/invoke -H 'Content-Type: application/json' -d '{{"question":"如何导入文档？"}}'""",
                    "batch": f"""curl -X POST {base_url}/api/runtime/workflows/1/batch -H 'Content-Type: application/json' -d '{{"questions":["如何导入文档？","如何运行评测？"]}}'""",
                },
                "workflows": workflow_contracts,
            },
            {
                "service": "ragarium-runtime",
                "workflow_count": len(workflows),
                "ready_workflow_count": ready_count,
            },
        )

    def runtime_invoke(
        self, workflow_id: int, payload: Optional[RuntimeInvokeRequest] = None
    ) -> Dict[str, Any]:
        question = (payload.question if payload else "").strip()
        if not question:
            return runtime_error(
                "invalid_question", "question 不能为空", {"workflow_id": workflow_id}
            )
        context = self.runtime_context(workflow_id)
        if "error" in context:
            return context["error"]
        try:
            return self.runtime_invoke_question(
                context["workflow"],
                context["knowledge_base"],
                question,
                context["metadata"],
            )
        except Exception as exc:
            return runtime_error("workflow_run_failed", str(exc), context["metadata"])

    def runtime_batch(
        self, workflow_id: int, payload: Optional[RuntimeBatchRequest] = None
    ) -> Dict[str, Any]:
        if not payload or not payload.questions:
            return runtime_error(
                "invalid_questions", "questions 不能为空", {"workflow_id": workflow_id}
            )
        context = self.runtime_context(workflow_id)
        if "error" in context:
            return context["error"]
        items = []
        for index, raw_question in enumerate(payload.questions):
            question = raw_question.strip()
            item_metadata = {**context["metadata"], "index": index}
            if not question:
                items.append(
                    runtime_error(
                        "invalid_question", "question 不能为空", item_metadata
                    )
                )
                continue
            try:
                items.append(
                    self.runtime_invoke_question(
                        context["workflow"],
                        context["knowledge_base"],
                        question,
                        item_metadata,
                    )
                )
            except Exception as exc:
                items.append(
                    runtime_error("workflow_run_failed", str(exc), item_metadata)
                )
        return runtime_success(
            {"items": items}, {**context["metadata"], "count": len(items)}
        )

    def get_config(self) -> Dict[str, Any]:
        try:
            return self.config_service.read()
        except Exception as exc:
            raise http_error(exc)

    def update_config(self, payload: AppConfigRequest) -> Dict[str, Any]:
        try:
            return self.config_service.update(payload.model_dump())
        except Exception as exc:
            raise http_error(exc)

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        return self.store.list_knowledge_bases()

    def create_knowledge_base(
        self, payload: CreateKnowledgeBaseRequest
    ) -> Dict[str, Any]:
        try:
            return self.store.create_knowledge_base(payload.name)
        except Exception as exc:
            raise http_error(exc)

    def get_knowledge_base(self, knowledge_base_id: int) -> Dict[str, Any]:
        try:
            kb = self.store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = self.store.list_sources(knowledge_base_id)
            kb["chunks"] = self.store.list_chunks(knowledge_base_id, limit=20)
            return kb
        except Exception as exc:
            raise http_error(exc)

    def update_kb_status_after_ingestion_failure(
        self, knowledge_base_id: int, error: str
    ) -> None:
        sources = self.store.list_sources(knowledge_base_id)
        chunks = self.store.list_chunks(knowledge_base_id)
        if chunks:
            self.store.update_knowledge_base_index_status(
                knowledge_base_id, status="stale", error=None
            )
            return
        if sources:
            self.store.update_knowledge_base_index_status(
                knowledge_base_id, status="failed", error=error
            )
            return
        self.store.update_knowledge_base_index_status(
            knowledge_base_id, status="not_indexed", error=None
        )

    async def upload_file(
        self,
        knowledge_base_id: int,
        file: UploadFile = File(...),
        chunk_size: Optional[int] = Form(default=None),
        chunk_overlap: Optional[int] = Form(default=None),
    ) -> Dict[str, Any]:
        try:
            data = await file.read()
            source = self.ingestion_service.ingest_bytes(
                knowledge_base_id,
                filename=file.filename or "upload.txt",
                data=data,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            self.store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="stale",
                chunk_config={"chunk_size": chunk_size, "chunk_overlap": chunk_overlap},
            )
            return source
        except Exception as exc:
            try:
                self.update_kb_status_after_ingestion_failure(
                    knowledge_base_id, str(exc)
                )
            except Exception:
                pass
            raise http_error(exc)

    def import_url(
        self, knowledge_base_id: int, payload: UrlImportRequest
    ) -> Dict[str, Any]:
        try:
            source = self.ingestion_service.ingest_url(
                knowledge_base_id,
                payload.url,
                chunk_size=payload.chunk_size,
                chunk_overlap=payload.chunk_overlap,
            )
            self.store.update_knowledge_base_index_status(
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
                self.update_kb_status_after_ingestion_failure(
                    knowledge_base_id, str(exc)
                )
            except Exception:
                pass
            raise http_error(exc)

    def delete_source(self, knowledge_base_id: int, source_id: int) -> Dict[str, Any]:
        try:
            source = self.store.delete_source(knowledge_base_id, source_id)
            stored_path = source.get("stored_path")
            if stored_path:
                try:
                    file_path = Path(stored_path).resolve()
                    upload_root = self.ingestion_service.upload_root.resolve()
                    if file_path == upload_root or upload_root in file_path.parents:
                        file_path.unlink(missing_ok=True)
                except Exception:
                    pass
            remaining_sources = self.store.list_sources(knowledge_base_id)
            remaining_chunks = self.store.list_chunks(knowledge_base_id)
            if not remaining_sources:
                self.store.update_knowledge_base_index_status(
                    knowledge_base_id, status="not_indexed", error=None
                )
            elif remaining_chunks:
                self.store.update_knowledge_base_index_status(
                    knowledge_base_id, status="stale", error=None
                )
            else:
                self.store.update_knowledge_base_index_status(
                    knowledge_base_id,
                    status="failed",
                    error="当前知识库没有可索引 chunks，请先导入可解析的来源",
                )
            kb = self.store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = remaining_sources
            kb["chunks"] = self.store.list_chunks(knowledge_base_id, limit=20)
            return {"deleted_source": source, "knowledge_base": kb}
        except Exception as exc:
            raise http_error(exc)

    def open_source_browser_session(
        self, knowledge_base_id: int, source_id: int
    ) -> Dict[str, Any]:
        try:
            source = self.store.get_source(source_id)
            if (
                int(source["knowledge_base_id"]) != int(knowledge_base_id)
                or source.get("source_type") != "url"
            ):
                raise KeyError(f"url source not found: {source_id}")
            return self.browser_session_manager.open_source(source)
        except Exception as exc:
            raise http_error(exc)

    def extract_browser_session(self, session_id: str) -> Dict[str, Any]:
        try:
            extracted = self.browser_session_manager.extract(session_id)
            knowledge_base_id = int(extracted["knowledge_base_id"])
            source_id = int(extracted["source_id"])
            source = self.ingestion_service.update_url_source_from_parsed(
                knowledge_base_id, source_id, extracted["parsed"]
            )
            self.store.update_knowledge_base_index_status(
                knowledge_base_id, status="stale", error=None
            )
            kb = self.store.get_knowledge_base(knowledge_base_id)
            kb["sources"] = self.store.list_sources(knowledge_base_id)
            kb["chunks"] = self.store.list_chunks(knowledge_base_id, limit=20)
            try:
                self.browser_session_manager.close(session_id)
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
            raise http_error(exc)

    def close_browser_session(self, session_id: str) -> Dict[str, Any]:
        try:
            return self.browser_session_manager.close(session_id)
        except Exception as exc:
            raise http_error(exc)

    def build_knowledge_base_index(
        self,
        knowledge_base_id: int,
        *,
        overwrite: bool = True,
        chunk_config: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        self.store.update_knowledge_base_index_status(
            knowledge_base_id, status="indexing", error=None, chunk_config=chunk_config
        )
        try:
            self.config_service.read()
            kb = self.store.get_knowledge_base(knowledge_base_id)
            chunks = self.store.list_chunks(knowledge_base_id)
            builder = self.vector_builder_factory()
            builder.build_from_chunks(
                chunks, collection_name=kb["collection_name"], overwrite=overwrite
            )
            kb = self.store.update_knowledge_base_index_status(
                knowledge_base_id, status="ready", error=None, chunk_config=chunk_config
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
            self.store.update_knowledge_base_index_status(
                knowledge_base_id,
                status="failed",
                error=str(exc),
                chunk_config=chunk_config,
            )
            raise

    def build_index(
        self, knowledge_base_id: int, payload: IndexRequest
    ) -> Dict[str, Any]:
        try:
            result = self.build_knowledge_base_index(
                knowledge_base_id, overwrite=payload.overwrite
            )
            result["status"] = result["index_status"]
            return result
        except Exception as exc:
            raise http_error(exc)

    def test_knowledge_base_retrieval(
        self, knowledge_base_id: int, payload: RetrievalTestRequest
    ) -> Dict[str, Any]:
        try:
            query = payload.query.strip()
            if not query:
                raise ValueError("query is required")
            kb = self.store.get_knowledge_base(knowledge_base_id)
            if kb["index_status"] != "ready":
                raise ValueError("知识库索引未就绪，请先构建索引")
            self.config_service.read()
            documents = self.vector_builder_factory().manager.invoke(
                query, k=payload.top_k, collection_name=kb["collection_name"]
            )
            results = []
            for index, document in enumerate(documents, start=1):
                metadata = dict(getattr(document, "metadata", None) or {})
                content = getattr(document, "page_content", None)
                if content is None and isinstance(document, dict):
                    metadata = dict(document.get("metadata") or {})
                    content = (
                        document.get("content") or document.get("page_content") or ""
                    )
                title_or_path = (
                    metadata.get("title")
                    or metadata.get("path")
                    or metadata.get("file_name")
                    or metadata.get("source")
                    or metadata.get("url")
                    or ""
                )
                results.append(
                    {
                        "rank": index,
                        "content": str(content or ""),
                        "source": metadata.get("source") or "",
                        "title_or_path": title_or_path,
                        "url": metadata.get("url") or "",
                        "chunk_index": metadata.get("chunk_index"),
                        "metadata": metadata,
                    }
                )
            return {
                "query": query,
                "top_k": payload.top_k,
                "knowledge_base_id": knowledge_base_id,
                "collection_name": kb["collection_name"],
                "results": results,
            }
        except Exception as exc:
            raise http_error(exc)

    def run_query_generate_node_for_workflow(
        self, workflow: Dict[str, Any], *, node_id: Optional[str] = None
    ) -> Dict[str, Any]:
        config = self.workflow_engine.get_query_generate_config(
            workflow["graph"], node_id=node_id
        )
        generator = self.query_generator_factory()
        return generator.generate(
            knowledge_base_id=config["knowledge_base_id"],
            examples=config["examples"],
            target_count=config["target_count"],
            name=config["name"],
        )

    def normalize_context_texts(self, raw_contexts: Any) -> List[str]:
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
                raise ValueError(
                    "contexts 元素必须是 str、包含 content/page_content 的 dict，或包含 page_content 属性"
                )
            contexts.append(str(page_content))
        return contexts

    def filter_eval_result_metrics(
        self, result: Any, metric_names: Optional[List[str]]
    ) -> Any:
        if not metric_names:
            return result
        selected = set(metric_names)
        if hasattr(result, "overall") and isinstance(result.overall, dict):
            result.overall = {
                name: value
                for name, value in result.overall.items()
                if name in selected
            }
        per_sample = getattr(result, "per_sample", None)
        if per_sample is not None and hasattr(per_sample, "columns"):
            keep_columns = [
                column
                for column in per_sample.columns
                if column in selected
                or column in {"question", "answer", "contexts", "ground_truth"}
            ]
            result.per_sample = per_sample[keep_columns]
        return result

    def evaluate_records_with_engine(
        self, records: List[RagEvalRecord], metric_names: Optional[List[str]] = None
    ) -> Any:
        selected_metric_names = validate_metric_names(metric_names, records)
        evaluator = self.build_eval_engine(
            selected_metric_names if metric_names else None
        )
        if hasattr(evaluator, "evaluate_records"):
            return self.filter_eval_result_metrics(
                evaluator.evaluate_records(records), selected_metric_names
            )
        if hasattr(evaluator, "evaluate"):
            return self.filter_eval_result_metrics(
                evaluator.evaluate(records), selected_metric_names
            )

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
                **(
                    {"ground_truth": record.ground_truth} if record.ground_truth else {}
                ),
            }
            for record in records
        ]
        return self.filter_eval_result_metrics(
            evaluator.invoke(AnswerRecordRunner(records), samples),
            selected_metric_names,
        )

    def generate_answer_records_for_query_set(
        self,
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        limit: Optional[int],
    ) -> Dict[str, Any]:
        validation = self.workflow_engine.validate_executable_graph(workflow["graph"])
        types = {node.get("type") for node in validation.ordered_nodes}
        if not {"retrieve", "prompt_llm", "answer"}.issubset(types):
            raise WorkflowValidationError(
                "Eval run requires a graph with Retrieve, Prompt / LLM and Answer nodes"
            )
        kb_id = self.workflow_engine.resolve_knowledge_base_id(workflow["graph"])
        kb = self.store.get_knowledge_base(kb_id)
        if kb["index_status"] != "ready":
            raise ValueError("knowledge base index is not ready")
        queries = list(query_set["queries"])
        if limit:
            queries = queries[:limit]
        vector_manager = self.vector_builder_factory().manager
        top_k = self.workflow_engine.get_top_k_from_validation(validation)
        rag_records: List[RagEvalRecord] = []
        answer_records: List[Dict[str, Any]] = []
        for index, query in enumerate(queries):
            result = self.workflow_engine.run_question(
                workflow["graph"],
                question=str(query),
                vector_manager=vector_manager,
                collection_name=kb["collection_name"],
                config_path=self.config_path,
                k=top_k,
            )
            contexts = self.normalize_context_texts(result.get("contexts") or [])
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

    def build_eval_run_samples(
        self, result: Any, records: List[RagEvalRecord]
    ) -> List[Dict[str, Any]]:
        metric_names = sorted((getattr(result, "overall", {}) or {}).keys())
        rows: List[Dict[str, Any]] = []
        per_sample = getattr(result, "per_sample", None)
        if per_sample is not None and hasattr(per_sample, "to_dict"):
            rows = per_sample.to_dict(orient="records")
        samples = []
        for index, record in enumerate(records):
            row = rows[index] if index < len(rows) else {}
            contexts = row.get("contexts", record.contexts)
            if contexts is None:
                contexts = []
            elif isinstance(contexts, str):
                contexts = [contexts]
            metrics = {
                name: json_safe(row.get(name)) for name in metric_names if name in row
            }
            samples.append(
                {
                    "index": index + 1,
                    "question": json_safe(row.get("question", record.question)),
                    "answer": json_safe(row.get("answer", record.answer)),
                    "contexts": json_safe(contexts),
                    "ground_truth": json_safe(
                        row.get("ground_truth", record.ground_truth)
                    ),
                    "metrics": metrics,
                    "meta": json_safe(record.meta),
                }
            )
        return samples

    def create_eval_run_from_answer_records(
        self,
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        records: List[RagEvalRecord],
        metric_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        result = self.evaluate_records_with_engine(records, metric_names=metric_names)
        samples = self.build_eval_run_samples(result, records)
        return self.store.create_eval_run(
            query_set_id=query_set["id"],
            workflow_id=workflow["id"],
            status="completed",
            metrics=result.overall,
            samples=samples,
            output_csv=result.csv_path,
        )

    def create_eval_run_from_query_set(
        self,
        *,
        query_set: Dict[str, Any],
        workflow: Dict[str, Any],
        limit: Optional[int],
        metric_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        answer_batch = self.generate_answer_records_for_query_set(
            query_set=query_set, workflow=workflow, limit=limit
        )
        return self.create_eval_run_from_answer_records(
            query_set=query_set,
            workflow=workflow,
            records=answer_batch["records"],
            metric_names=metric_names,
        )

    def summarize_node_output(
        self, node_type: str, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        if node_type == "start":
            return {"keys": sorted(state.keys()), "question": state.get("question")}
        if node_type == "source":
            return {
                "knowledge_base_id": state.get("knowledge_base_id"),
                "collection_name": state.get("collection_name"),
            }
        if node_type == "parse":
            return {"parser": state.get("parser")}
        if node_type == "chunk":
            return {"chunk_config": state.get("chunk_config")}
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
                    "context_count": sum(
                        (
                            len(item.get("contexts") or [])
                            for item in state.get("answer_records") or []
                        )
                    ),
                }
            return {
                "question": state.get("question"),
                "answer": state.get("answer"),
                "context_count": len(state.get("contexts") or []),
            }
        if node_type == "retrieve":
            return {
                "knowledge_base_id": state.get("knowledge_base_id"),
                "top_k": state.get("top_k"),
                "question": state.get("question"),
                "query_count": len(state.get("queries") or []),
            }
        if node_type == "prompt_llm":
            prompt = state.get("prompt") or ""
            return {"prompt_length": len(prompt), "has_custom_prompt": bool(prompt)}
        if node_type == "ragas_eval":
            eval_run = state.get("eval_run") or {}
            return {
                "eval_run_id": eval_run.get("id"),
                "status": eval_run.get("status"),
                "metrics": eval_run.get("metrics"),
            }
        if node_type == "end":
            outputs = state.get("outputs") or {}
            return {"output_keys": sorted(outputs.keys())}
        return {"ok": True}

    def summarize_node_input(
        self,
        node_type: str,
        node: Dict[str, Any],
        state: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        data = node.get("data") or {}
        if node_type == "start":
            return {"inputs": inputs}
        if node_type == "source":
            return {"knowledge_base_id": data.get("knowledgeBaseId")}
        if node_type == "parse":
            return {
                "knowledge_base_id": state.get("knowledge_base_id"),
                "collection_name": state.get("collection_name"),
            }
        if node_type == "chunk":
            return {
                "configured_chunk_size": data.get("chunkSize"),
                "configured_chunk_overlap": data.get("chunkOverlap"),
            }
        if node_type == "embed_index":
            return {
                "knowledge_base_id": state.get("knowledge_base_id"),
                "chunk_config": state.get("chunk_config"),
                "overwrite": data.get("overwrite", True) is not False,
            }
        if node_type == "query_generate":
            return {
                "knowledge_base_id": data.get("knowledgeBaseId"),
                "example_count": len(data.get("examples") or []),
                "target_count": data.get("targetCount"),
                "name": data.get("name"),
            }
        if node_type == "retrieve":
            return {
                "knowledge_base_id": data.get("knowledgeBaseId")
                or state.get("knowledge_base_id"),
                "question": state.get("question"),
                "query_count": len(state.get("queries") or []),
                "top_k": data.get("topK") or state.get("top_k"),
            }
        if node_type == "prompt_llm":
            return {
                "question": state.get("question"),
                "query_count": len(state.get("queries") or []),
                "prompt_preview": (data.get("prompt") or "")[:240],
            }
        if node_type == "answer":
            return {
                "question": state.get("question"),
                "query_count": len(state.get("queries") or []),
                "knowledge_base_id": state.get("knowledge_base_id"),
                "top_k": state.get("top_k"),
            }
        if node_type == "ragas_eval":
            return {
                "query_set_id": (state.get("query_set") or {}).get("id"),
                "answer_count": state.get("answer_count"),
            }
        if node_type == "end":
            return {
                "state_keys": sorted(
                    (key for key in state.keys() if not key.startswith("_"))
                ),
                "configured_outputs": (node.get("data") or {}).get("outputs") or [],
            }
        return {
            "state_keys": sorted(
                (key for key in state.keys() if not key.startswith("_"))
            )
        }

    def default_end_outputs(self, state: Dict[str, Any]) -> Dict[str, Any]:
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

    def collect_end_outputs(
        self, node: Dict[str, Any], state: Dict[str, Any]
    ) -> Dict[str, Any]:
        outputs = (node.get("data") or {}).get("outputs") or []
        if not outputs:
            return self.default_end_outputs(state)
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

    def execute_workflow(
        self,
        workflow: Dict[str, Any],
        inputs: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[WorkflowProgressCallback] = None,
    ) -> Dict[str, Any]:
        graph = workflow["graph"]
        validation = self.workflow_engine.validate_executable_graph(graph)
        if validation.is_legacy:
            question = (inputs or {}).get("question")
            if not question:
                raise WorkflowValidationError(
                    "legacy RAG workflow requires question input"
                )
            kb_id = self.workflow_engine.resolve_knowledge_base_id(graph)
            kb = self.store.get_knowledge_base(kb_id)
            if kb["index_status"] != "ready":
                raise ValueError("knowledge base index is not ready")
            if progress_callback:
                progress_callback(
                    {
                        "event": "node_started",
                        "node_id": "legacy_full_rag",
                        "type": "legacy_full_rag",
                        "input": {
                            "question": str(question),
                            "knowledge_base_id": kb_id,
                        },
                    }
                )
            try:
                result = self.workflow_engine.run_question(
                    graph,
                    question=str(question),
                    vector_manager=self.vector_builder_factory().manager,
                    collection_name=kb["collection_name"],
                    config_path=self.config_path,
                )
            except Exception as exc:
                if progress_callback:
                    progress_callback(
                        {
                            "event": "node_failed",
                            "node_id": "legacy_full_rag",
                            "type": "legacy_full_rag",
                            "error": str(exc),
                        }
                    )
                raise
            if progress_callback:
                progress_callback(
                    {
                        "event": "node_completed",
                        "node_id": "legacy_full_rag",
                        "type": "legacy_full_rag",
                        "output": {
                            "question": result.get("question"),
                            "answer": result.get("answer") or result.get("generation"),
                            "context_count": len(result.get("contexts") or []),
                        },
                    }
                )
            return {
                "workflow_id": workflow["id"],
                "outputs": result,
                "trace": [
                    {
                        "node_id": "legacy_full_rag",
                        "type": "legacy_full_rag",
                        "status": "completed",
                    }
                ],
                "metadata": {"workflow_id": workflow["id"], "legacy": True},
            }
        state: Dict[str, Any] = {}
        trace = []
        for node in validation.ordered_nodes:
            node_id = node["id"]
            node_type = node["type"]
            data = node.get("data") or {}
            if progress_callback:
                progress_callback(
                    {
                        "event": "node_started",
                        "node_id": node_id,
                        "type": node_type,
                        "input": self.summarize_node_input(
                            node_type, node, state, inputs or {}
                        ),
                    }
                )
            try:
                if node_type == "start":
                    state.update(
                        self.workflow_engine.resolve_start_inputs(graph, inputs or {})
                    )
                elif node_type == "source":
                    kb_id = self.workflow_engine.get_source_knowledge_base_id_from_validation(
                        validation
                    )
                    kb = self.store.get_knowledge_base(kb_id)
                    state["knowledge_base_id"] = kb_id
                    state["collection_name"] = kb["collection_name"]
                elif node_type == "parse":
                    state["parser"] = data.get("parser") or "auto"
                elif node_type == "chunk":
                    state["chunk_config"] = (
                        self.workflow_engine.get_chunk_config_from_validation(
                            validation
                        )
                    )
                elif node_type == "embed_index":
                    kb_id = state.get("knowledge_base_id")
                    if not kb_id:
                        raise WorkflowValidationError(
                            "Embed / Index node requires upstream Source DB"
                        )
                    chunk_config = state.get("chunk_config") or {
                        "chunk_size": 900,
                        "chunk_overlap": 120,
                    }
                    self.store.update_knowledge_base_index_status(
                        kb_id,
                        status="processing",
                        error=None,
                        chunk_config=chunk_config,
                    )
                    self.ingestion_service.reprocess_knowledge_base_sources(
                        kb_id,
                        chunk_size=chunk_config["chunk_size"],
                        chunk_overlap=chunk_config["chunk_overlap"],
                    )
                    index_result = self.build_knowledge_base_index(
                        kb_id,
                        overwrite=data.get("overwrite", True) is not False,
                        chunk_config=chunk_config,
                    )
                    state["index_result"] = index_result
                elif node_type == "query_generate":
                    query_set = self.run_query_generate_node_for_workflow(
                        workflow, node_id=node_id
                    )
                    state["query_set"] = query_set
                    state["queries"] = query_set["queries"]
                    state["knowledge_base_id"] = query_set["knowledge_base_id"]
                elif node_type == "retrieve":
                    kb_id = self.workflow_engine.get_retrieve_knowledge_base_id_from_validation(
                        validation, required=False
                    )
                    if kb_id is not None:
                        state["knowledge_base_id"] = kb_id
                    if "knowledge_base_id" not in state:
                        raise WorkflowValidationError(
                            "Retrieve node requires selected or upstream knowledge DB"
                        )
                    state["top_k"] = self.workflow_engine.get_top_k_from_validation(
                        validation
                    )
                elif node_type == "prompt_llm":
                    state["prompt"] = data.get("prompt") or ""
                elif node_type == "answer":
                    if state.get("queries"):
                        query_set = state.get("query_set")
                        if not query_set:
                            raise WorkflowValidationError(
                                "Answer node requires upstream Query Generate for batch answers"
                            )
                        answer_batch = self.generate_answer_records_for_query_set(
                            query_set=query_set, workflow=workflow, limit=None
                        )
                        state["answer_records"] = answer_batch["items"]
                        state["_ragarium_records"] = answer_batch["records"]
                        state["answer_count"] = answer_batch["count"]
                        state["collection_name"] = answer_batch["collection_name"]
                        state["top_k"] = answer_batch["top_k"]
                    else:
                        question = state.get("question")
                        if not question:
                            raise WorkflowValidationError(
                                "Answer node requires question input"
                            )
                        kb = self.store.get_knowledge_base(
                            int(state["knowledge_base_id"])
                        )
                        if kb["index_status"] != "ready":
                            raise ValueError("knowledge base index is not ready")
                        result = self.workflow_engine.run_question(
                            graph,
                            question=str(question),
                            vector_manager=self.vector_builder_factory().manager,
                            collection_name=kb["collection_name"],
                            config_path=self.config_path,
                            k=int(state.get("top_k") or 3),
                        )
                        state["question"] = result.get("question") or str(question)
                        state["answer"] = (
                            result.get("answer") or result.get("generation") or ""
                        )
                        state["contexts"] = result.get("contexts") or []
                elif node_type == "ragas_eval":
                    query_set = state.get("query_set")
                    if not query_set:
                        raise WorkflowValidationError(
                            "RAGAS Eval node requires upstream Query Generate"
                        )
                    records = state.get("_ragarium_records") or []
                    if not records:
                        raise WorkflowValidationError(
                            "RAGAS Eval node requires upstream Answer records"
                        )
                    eval_config = self.workflow_engine.get_eval_config_from_validation(
                        validation
                    )
                    eval_records = (
                        records[: eval_config["limit"]]
                        if eval_config["limit"]
                        else records
                    )
                    eval_run = self.create_eval_run_from_answer_records(
                        query_set=query_set,
                        workflow=workflow,
                        records=eval_records,
                        metric_names=eval_config.get("metric_names"),
                    )
                    state["eval_run"] = eval_run
                elif node_type == "end":
                    state["outputs"] = self.collect_end_outputs(node, state)
                else:
                    raise WorkflowValidationError(
                        f"unsupported executable node type: {node_type}"
                    )
            except Exception as exc:
                if progress_callback:
                    progress_callback(
                        {
                            "event": "node_failed",
                            "node_id": node_id,
                            "type": node_type,
                            "error": str(exc),
                        }
                    )
                raise
            node_output = self.summarize_node_output(node_type, state)
            trace.append(
                {
                    "node_id": node_id,
                    "type": node_type,
                    "status": "completed",
                    "output": node_output,
                }
            )
            if progress_callback:
                progress_callback(
                    {
                        "event": "node_completed",
                        "node_id": node_id,
                        "type": node_type,
                        "output": node_output,
                    }
                )
        outputs = state.get("outputs") or self.default_end_outputs(state)
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

    def list_workflow_templates(self) -> List[Dict[str, Any]]:
        return get_workflow_templates()

    def get_default_workflow(
        self, template_id: str = DEFAULT_TEMPLATE_ID
    ) -> Dict[str, Any]:
        try:
            graph = get_default_workflow_graph(template_id)
            template = next(
                (item for item in get_workflow_templates() if item["id"] == template_id)
            )
            return {"name": template["name"], "graph": graph}
        except Exception as exc:
            raise http_error(exc)

    def list_workflows(self) -> List[Dict[str, Any]]:
        return [
            self.with_workflow_capabilities(workflow)
            for workflow in self.store.list_workflows()
        ]

    def validate_workflow(self, payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            validation = self.workflow_engine.validate_executable_graph(payload.graph)
            return {
                "ok": True,
                "template_id": validation.template_id,
                "node_count": len(validation.ordered_nodes),
                "runtime_capable": self.workflow_engine.is_runtime_graph(payload.graph),
                "prepare_capable": self.workflow_engine.is_prepare_graph(payload.graph),
                "evaluation_capable": self.workflow_engine.is_evaluation_graph(
                    payload.graph
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_workflow(self, payload: WorkflowRequest) -> Dict[str, Any]:
        try:
            self.workflow_engine.validate_graph_structure(payload.graph)
            return self.with_workflow_capabilities(
                self.store.upsert_workflow(payload.name, payload.graph, payload.id)
            )
        except Exception as exc:
            raise http_error(exc)

    def execute_workflow_route(
        self, workflow_id: int, payload: Optional[WorkflowExecuteRequest] = None
    ) -> Dict[str, Any]:
        try:
            workflow = self.store.get_workflow(workflow_id)
            return self.execute_workflow(
                workflow, inputs=payload.inputs if payload else {}
            )
        except Exception as exc:
            raise http_error(exc)

    def create_workflow_test_run(
        self, workflow_id: int, payload: Optional[WorkflowExecuteRequest] = None
    ) -> Dict[str, Any]:
        try:
            workflow = self.store.get_workflow(workflow_id)
            inputs = payload.inputs if payload else {}
            return self.test_runs.create_run(
                workflow_id=workflow_id, workflow=workflow, inputs=inputs
            )
        except Exception as exc:
            raise http_error(exc)

    def get_workflow_test_run(self, run_id: str) -> Dict[str, Any]:
        try:
            return self.test_runs.snapshot(run_id)
        except Exception as exc:
            raise http_error(exc)

    def prepare_workflow(self, workflow_id: int) -> Dict[str, Any]:
        source_kb_id: Optional[int] = None
        try:
            workflow = self.store.get_workflow(workflow_id)
            if self.workflow_engine.validate_graph_structure(
                workflow["graph"]
            ).nodes_by_type.get("start"):
                result = self.execute_workflow(workflow, inputs={})
                index_result = result["outputs"].get("index_result") or {}
                return {"workflow_id": workflow_id, **index_result}
            if not self.workflow_engine.is_prepare_graph(workflow["graph"]):
                raise WorkflowValidationError(
                    "prepare only supports offline DB workflows"
                )
            source_kb_id = self.workflow_engine.get_source_knowledge_base_id(
                workflow["graph"]
            )
            chunk_config = self.workflow_engine.get_chunk_config(workflow["graph"])
            self.store.update_knowledge_base_index_status(
                source_kb_id, status="processing", error=None, chunk_config=chunk_config
            )
            ingestion_result = self.ingestion_service.reprocess_knowledge_base_sources(
                source_kb_id,
                chunk_size=chunk_config["chunk_size"],
                chunk_overlap=chunk_config["chunk_overlap"],
            )
            index_result = self.build_knowledge_base_index(
                source_kb_id, overwrite=True, chunk_config=chunk_config
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
                    self.store.update_knowledge_base_index_status(
                        source_kb_id, status="failed", error=str(exc)
                    )
                except Exception:
                    pass
            raise http_error(exc)

    def run_workflow(
        self, workflow_id: int, payload: WorkflowRunRequest
    ) -> Dict[str, Any]:
        try:
            workflow = self.store.get_workflow(workflow_id)
            if self.workflow_engine.validate_graph_structure(
                workflow["graph"]
            ).nodes_by_type.get("start"):
                result = self.execute_workflow(
                    workflow, inputs={"question": payload.question}
                )
                outputs = result["outputs"]
                return {
                    "question": outputs.get("question") or payload.question,
                    "answer": outputs.get("answer") or outputs.get("generation") or "",
                    "contexts": outputs.get("contexts") or [],
                }
            if not self.workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("run only supports RAG workflows")
            kb_id = _resolve_workflow_knowledge_base_id(
                self.workflow_engine, workflow, None
            )
            kb = self.store.get_knowledge_base(kb_id)
            if kb["index_status"] != "ready":
                raise ValueError("knowledge base index is not ready")
            vector_manager = self.vector_builder_factory().manager
            return self.workflow_engine.run_question(
                workflow["graph"],
                question=payload.question,
                vector_manager=vector_manager,
                collection_name=kb["collection_name"],
                config_path=self.config_path,
                k=payload.k,
            )
        except Exception as exc:
            raise http_error(exc)

    def run_workflow_node(self, workflow_id: int, node_id: str) -> Dict[str, Any]:
        try:
            workflow = self.store.get_workflow(workflow_id)
            query_set = self.run_query_generate_node_for_workflow(
                workflow, node_id=node_id
            )
            return {
                "workflow_id": workflow_id,
                "node_id": node_id,
                "node_type": "query_generate",
                "query_set": query_set,
            }
        except Exception as exc:
            raise http_error(exc)

    def evaluate_workflow(self, workflow_id: int) -> Dict[str, Any]:
        query_set: Optional[Dict[str, Any]] = None
        try:
            workflow = self.store.get_workflow(workflow_id)
            if self.workflow_engine.validate_graph_structure(
                workflow["graph"]
            ).nodes_by_type.get("start"):
                result = self.execute_workflow(workflow, inputs={})
                return {
                    "workflow_id": workflow_id,
                    "query_set": result["outputs"].get("query_set"),
                    "answer_count": result["outputs"].get("answer_count"),
                    "eval_run": result["outputs"].get("eval_run"),
                    "trace": result["trace"],
                    "metadata": result["metadata"],
                }
            if not self.workflow_engine.is_evaluation_graph(workflow["graph"]):
                raise WorkflowValidationError(
                    "evaluate only supports evaluation workflows"
                )
            eval_config = self.workflow_engine.get_eval_config(workflow["graph"])
            query_set = self.run_query_generate_node_for_workflow(workflow)
            eval_run = self.create_eval_run_from_query_set(
                query_set=query_set,
                workflow=workflow,
                limit=eval_config["limit"],
                metric_names=eval_config.get("metric_names"),
            )
            return {
                "workflow_id": workflow_id,
                "query_set": query_set,
                "eval_run": eval_run,
            }
        except Exception as exc:
            if query_set is not None:
                try:
                    workflow = self.store.get_workflow(workflow_id)
                    failed_run = self.store.create_eval_run(
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
            raise http_error(exc)

    def list_query_sets(
        self, knowledge_base_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return self.store.list_query_sets(knowledge_base_id)

    def generate_query_set(self, payload: QueryGenerateRequest) -> Dict[str, Any]:
        try:
            generator = self.query_generator_factory()
            return generator.generate(
                knowledge_base_id=payload.knowledge_base_id,
                examples=payload.examples,
                target_count=payload.target_count,
                name=payload.name,
            )
        except Exception as exc:
            raise http_error(exc)

    def list_eval_runs(self) -> List[Dict[str, Any]]:
        return self.store.list_eval_runs()

    def list_eval_metrics(self) -> Dict[str, Any]:
        return {
            "metrics": list_metric_specs(),
            "default_metric_names": validate_metric_names(None),
        }

    def create_eval_run(self, payload: EvalRunRequest) -> Dict[str, Any]:
        try:
            query_set = self.store.get_query_set(payload.query_set_id)
            workflow = self.store.get_workflow(payload.workflow_id)
            if not self.workflow_engine.is_runtime_graph(workflow["graph"]):
                raise WorkflowValidationError("Eval run requires a RAG workflow")
            return self.create_eval_run_from_query_set(
                query_set=query_set,
                workflow=workflow,
                limit=payload.limit,
                metric_names=payload.metric_names,
            )
        except Exception as exc:
            if isinstance(exc, MetricValidationError):
                raise http_error(exc)
            failed_run = None
            try:
                failed_run = self.store.create_eval_run(
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
            raise http_error(exc)
