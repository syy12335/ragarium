from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rag_eval.api.context import (
    EvalEngineFactory,
    QueryGeneratorFactory,
    VectorBuilderFactory,
    create_api_context,
)
from rag_eval.api.routers import (
    create_evaluation_router,
    create_knowledge_router,
    create_runtime_router,
    create_workflow_router,
)
from rag_eval.api.service import ApiService
from rag_eval.ingestion import IngestionService
from rag_eval.storage import ProductStore
from rag_eval.workflow import WorkflowEngine


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
    context = create_api_context(
        store=store,
        ingestion_service=ingestion_service,
        workflow_engine=workflow_engine,
        vector_builder_factory=vector_builder_factory,
        query_generator_factory=query_generator_factory,
        eval_engine_factory=eval_engine_factory,
        browser_session_manager=browser_session_manager,
        config_path=config_path,
    )
    service = ApiService(context)

    app = FastAPI(title="RAG Eval Scaffold API")
    app.state.api_context = context
    app.state.api_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(create_runtime_router(service))
    app.include_router(create_knowledge_router(service))
    app.include_router(create_workflow_router(service))
    app.include_router(create_evaluation_router(service))
    return app


app = create_app()
