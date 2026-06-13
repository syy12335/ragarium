from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ragarium.app_config import AppConfigService
from ragarium.ingestion import BrowserSessionManager, IngestionService
from ragarium.query_generation import QueryGenerationService
from ragarium.storage import ProductStore
from ragarium.vector.vector_builder import VectorDatabaseBuilder
from ragarium.workflow import WorkflowEngine


VectorBuilderFactory = Callable[[], VectorDatabaseBuilder]
QueryGeneratorFactory = Callable[[], QueryGenerationService]
EvalEngineFactory = Callable[[], Any]


@dataclass
class ApiContext:
    store: ProductStore
    config_service: AppConfigService
    ingestion_service: IngestionService
    workflow_engine: WorkflowEngine
    vector_builder_factory: VectorBuilderFactory
    query_generator_factory: QueryGeneratorFactory
    eval_engine_factory: Optional[EvalEngineFactory]
    browser_session_manager: Any
    config_path: str
    state_root: Path


def default_state_root() -> Path:
    return Path(os.environ.get("RAGARIUM_APP_HOME", "var/app"))


def create_api_context(
    *,
    store: Optional[ProductStore] = None,
    ingestion_service: Optional[IngestionService] = None,
    workflow_engine: Optional[WorkflowEngine] = None,
    vector_builder_factory: Optional[VectorBuilderFactory] = None,
    query_generator_factory: Optional[QueryGeneratorFactory] = None,
    eval_engine_factory: Optional[EvalEngineFactory] = None,
    browser_session_manager: Optional[Any] = None,
    config_path: str = "config/application.yaml",
) -> ApiContext:
    state_root = default_state_root()
    store = store or ProductStore(state_root / "state.sqlite")
    config_service = AppConfigService(
        config_path, secrets_path=state_root / "provider_keys.yaml"
    )
    config_service.read()
    ingestion_service = ingestion_service or IngestionService(
        store,
        state_root / "uploads",
        config_service=config_service,
    )
    workflow_engine = workflow_engine or WorkflowEngine()
    browser_session_manager = browser_session_manager or BrowserSessionManager(
        state_root / "browser_profile"
    )

    def default_vector_builder_factory() -> VectorDatabaseBuilder:
        return VectorDatabaseBuilder(config_path)

    vector_builder_factory = vector_builder_factory or default_vector_builder_factory
    query_generator_factory = query_generator_factory or (
        lambda: QueryGenerationService(store, config_path=config_path)
    )

    return ApiContext(
        store=store,
        config_service=config_service,
        ingestion_service=ingestion_service,
        workflow_engine=workflow_engine,
        vector_builder_factory=vector_builder_factory,
        query_generator_factory=query_generator_factory,
        eval_engine_factory=eval_engine_factory,
        browser_session_manager=browser_session_manager,
        config_path=config_path,
        state_root=state_root,
    )
