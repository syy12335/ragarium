from __future__ import annotations

import os
import time
from copy import deepcopy
from dataclasses import dataclass

import yaml
from fastapi.testclient import TestClient

from rag_eval.api import create_app
from rag_eval.ingestion.loaders import ParsedDocument
from rag_eval.query_generation import QueryGenerationService
from rag_eval.storage import ProductStore
from rag_eval.workflow import DEFAULT_WORKFLOW_GRAPH, WorkflowEngine, get_default_workflow_graph


def graph_with_source_db(kb_id: int):
    graph = deepcopy(DEFAULT_WORKFLOW_GRAPH)
    for node in graph["nodes"]:
        if node["type"] == "source":
            node["data"]["knowledgeBaseId"] = str(kb_id)
    return graph


def template_graph(template_id: str, kb_id: int):
    graph = get_default_workflow_graph(template_id)
    for node in graph["nodes"]:
        if node["type"] == "source":
            node["data"]["knowledgeBaseId"] = str(kb_id)
        if node["type"] == "retrieve" and template_id == "rag":
            node["data"]["knowledgeBaseId"] = str(kb_id)
        if node["type"] == "query_generate":
            node["data"]["knowledgeBaseId"] = str(kb_id)
            node["data"]["targetCount"] = 3
    return graph


class FakeVectorBuilder:
    def __init__(self):
        self.manager = object()

    def build_from_chunks(self, chunks, *, collection_name, overwrite=True):
        self.chunks = chunks
        self.collection_name = collection_name


@dataclass
class FakeRetrievedDocument:
    page_content: str
    metadata: dict


class FakeRetrievalManager:
    def __init__(self, env_name: str | None = None, expected_value: str | None = None):
        self.calls = []
        self.env_name = env_name
        self.expected_value = expected_value

    def invoke(self, query, *, k=3, collection_name=None):
        if self.env_name:
            assert os.environ.get(self.env_name) == self.expected_value
        self.calls.append({"query": query, "k": k, "collection_name": collection_name})
        return [
            FakeRetrievedDocument(
                page_content="Upload files, build an index, then test retrieval.",
                metadata={
                    "source": "guide.md",
                    "title": "Guide",
                    "url": "https://example.com/guide",
                    "chunk_index": 2,
                },
            ),
            FakeRetrievedDocument(
                page_content="RAG evaluation can use query-only datasets.",
                metadata={
                    "source": "eval.md",
                    "path": "docs/eval.md",
                    "chunk_index": 4,
                },
            ),
        ][:k]


class FakeRetrievalVectorBuilder(FakeVectorBuilder):
    def __init__(self, manager):
        self.manager = manager


class EnvAssertingVectorBuilder(FakeVectorBuilder):
    def __init__(self, env_name: str, expected_value: str):
        super().__init__()
        self.env_name = env_name
        self.expected_value = expected_value

    def build_from_chunks(self, chunks, *, collection_name, overwrite=True):
        assert os.environ.get(self.env_name) == self.expected_value
        super().build_from_chunks(chunks, collection_name=collection_name, overwrite=overwrite)


class FakeWorkflowEngine(WorkflowEngine):
    def run_question(self, graph, *, question, vector_manager=None, collection_name=None, **kwargs):
        self.validate_graph(graph)
        return {
            "question": question,
            "answer": f"fake answer from {collection_name}",
            "contexts": ["fake context"],
        }


@dataclass
class FakeEvalResult:
    overall: dict
    csv_path: str


class FakeEvalEngine:
    def invoke(self, runner, samples):
        assert samples
        return FakeEvalResult(overall={"faithfulness": 1.0, "answer_relevancy": 0.9}, csv_path="fake.csv")


class FakeBrowserSessionManager:
    def __init__(self):
        self.source = None
        self.closed = []

    def open_source(self, source):
        self.source = source
        return {
            "session_id": "session-1",
            "knowledge_base_id": source["knowledge_base_id"],
            "source_id": source["id"],
            "url": source["uri"],
            "status": "open",
        }

    def extract(self, session_id):
        assert session_id == "session-1"
        return {
            "session_id": session_id,
            "knowledge_base_id": self.source["knowledge_base_id"],
            "source_id": self.source["id"],
            "url": self.source["uri"],
            "parsed": ParsedDocument(
                content="Chrome browser download page. Install Chrome and manage browser settings.",
                metadata={
                    "source": self.source["uri"],
                    "url": self.source["uri"],
                    "extension": ".html",
                    "title": "Chrome",
                },
            ),
        }

    def close(self, session_id):
        self.closed.append(session_id)
        return {"session_id": session_id, "status": "closed"}


def test_api_config_reports_env_status(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "API_KEY_QWEN",
                        "default_model_name": "qwen3.7-plus",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("API_KEY_QWEN", "test-key")

    client = TestClient(create_app(store=ProductStore(tmp_path / "state.sqlite"), config_path=str(app_path)))
    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["env_status"]["qwen"] == {
        "api_key_env": "API_KEY_QWEN",
        "configured": True,
    }


def test_api_config_rejects_empty_providers(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "api_key_env": "API_KEY_QWEN",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    client = TestClient(create_app(store=ProductStore(tmp_path / "state.sqlite"), config_path=str(app_path)))
    response = client.put(
        "/api/config",
        json={
            "providers": {},
            "roles": {},
            "chunk": {"chunk_size": 900, "chunk_overlap": 120},
        },
    )

    assert response.status_code == 400
    assert "at least one provider" in response.json()["detail"]


def test_api_config_accepts_managed_api_key_without_returning_secret(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "API_KEY_QWEN",
                        "default_model_name": "qwen3.7-plus",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_EVAL_APP_HOME", str(tmp_path / "app_state"))
    monkeypatch.delenv("API_KEY_QWEN", raising=False)

    client = TestClient(create_app(store=ProductStore(tmp_path / "state.sqlite"), config_path=str(app_path)))
    response = client.put(
        "/api/config",
        json={
            "providers": {
                "qwen": {
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key_env": "API_KEY_QWEN",
                    "default_model_name": "qwen3.7-plus",
                }
            },
            "roles": {},
            "chunk": {"chunk_size": 900, "chunk_overlap": 120},
            "api_keys": {"qwen": "secret-key"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["env_status"]["qwen"]["configured"] is True
    assert "api_key" not in data["providers"]["qwen"]
    assert "secret-key" not in response.text


def test_api_delete_source_removes_chunks_and_updates_kb_status(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    source = store.create_source(
        kb["id"],
        source_type="url",
        name="https://example.com/doc",
        uri="https://example.com/doc",
        status="ready",
    )
    store.replace_source_chunks(
        kb["id"],
        source["id"],
        [
            {
                "chunk_index": 0,
                "content": "example chunk",
                "metadata": {"source": "https://example.com/doc", "chunk_index": 0},
            }
        ],
    )
    store.update_knowledge_base_index_status(kb["id"], status="ready")

    client = TestClient(create_app(store=store))
    response = client.delete(f"/api/knowledge-bases/{kb['id']}/sources/{source['id']}")

    assert response.status_code == 200
    assert response.json()["deleted_source"]["id"] == source["id"]
    assert store.list_sources(kb["id"]) == []
    assert store.list_chunks(kb["id"]) == []
    assert store.get_knowledge_base(kb["id"])["index_status"] == "not_indexed"


def test_api_failed_url_import_updates_source_and_kb_status(tmp_path, monkeypatch):
    store = ProductStore(tmp_path / "state.sqlite")
    client = TestClient(create_app(store=store))
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()

    monkeypatch.setattr(
        "rag_eval.ingestion.service.parse_url",
        lambda url: ParsedDocument(
            content="如果您在几秒钟内没有被重定向，请点击此处。",
            metadata={"source": url, "url": url, "extension": ".html"},
        ),
    )

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/urls",
        json={"url": "https://example.com/app"},
    )

    assert response.status_code == 400
    assert "未获得可切分正文" in response.json()["detail"]
    detail = client.get(f"/api/knowledge-bases/{kb['id']}").json()
    assert detail["index_status"] == "failed"
    assert "未获得可切分正文" in detail["index_error"]
    assert detail["chunks"] == []
    assert detail["sources"][0]["status"] == "failed"
    assert detail["sources"][0]["error_code"] == "browser_challenge"


def test_api_browser_session_extracts_failed_url_source(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    source = store.create_source(
        kb["id"],
        source_type="url",
        name="https://www.google.com/search?q=chrome",
        uri="https://www.google.com/search?q=chrome",
        status="failed",
        error="浏览器已打开原页面，但未获得可切分正文",
    )
    store.update_source_status(
        source["id"],
        status="failed",
        error=source["error"],
        error_code="browser_challenge",
    )
    manager = FakeBrowserSessionManager()
    client = TestClient(create_app(store=store, browser_session_manager=manager))

    open_response = client.post(f"/api/knowledge-bases/{kb['id']}/sources/{source['id']}/browser-session")
    assert open_response.status_code == 200
    assert open_response.json()["session_id"] == "session-1"

    extract_response = client.post("/api/browser-sessions/session-1/extract")
    assert extract_response.status_code == 200
    payload = extract_response.json()
    assert payload["source"]["status"] == "ready"
    assert payload["source"]["error"] is None
    assert payload["source"]["error_code"] is None
    assert payload["chunk_count"] >= 1
    assert payload["knowledge_base"]["index_status"] == "stale"
    assert store.list_chunks(kb["id"])[0]["content"].startswith("Chrome browser")
    assert manager.closed == ["session-1"]


def test_api_browser_session_rejects_invalid_source_and_session(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    source = store.create_source(
        kb["id"],
        source_type="file",
        name="doc.txt",
        stored_path="/tmp/doc.txt",
        status="failed",
    )
    client = TestClient(create_app(store=store))

    open_response = client.post(f"/api/knowledge-bases/{kb['id']}/sources/{source['id']}/browser-session")
    assert open_response.status_code == 404

    close_response = client.post("/api/browser-sessions/missing/close")
    assert close_response.status_code == 404


def test_api_index_loads_managed_provider_key_before_build(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    roles_path = config_dir / "model_roles.yaml"
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "TEST_INDEX_QWEN_KEY",
                        "default_model_name": "qwen3.7-plus",
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    roles_path.write_text(
        yaml.safe_dump(
            {
                "embedding": {"provider": "qwen", "model_name": "text-embedding-v4"},
                "generation": {"provider": "qwen", "model_name": "qwen3.7-plus"},
                "evaluation": {"provider": "qwen", "model_name": "qwen3.7-plus"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    app_home = tmp_path / "var" / "app"
    app_home.mkdir(parents=True)
    (app_home / "provider_keys.yaml").write_text(
        yaml.safe_dump({"api_keys": {"qwen": "managed-secret"}}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_EVAL_APP_HOME", str(app_home))
    monkeypatch.delenv("TEST_INDEX_QWEN_KEY", raising=False)

    store = ProductStore(tmp_path / "state.sqlite")
    app = create_app(
        store=store,
        config_path=str(app_path),
        vector_builder_factory=lambda: EnvAssertingVectorBuilder("TEST_INDEX_QWEN_KEY", "managed-secret"),
    )
    client = TestClient(app)
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()
    upload_response = client.post(
        f"/api/knowledge-bases/{kb['id']}/files",
        files={"file": ("doc.txt", b"Import files, chunk text, and evaluate RAG.", "text/plain")},
    )
    assert upload_response.status_code == 200

    index_response = client.post(f"/api/knowledge-bases/{kb['id']}/index", json={"overwrite": True})

    assert index_response.status_code == 200
    assert index_response.json()["status"] == "ready"


def test_api_retrieval_test_returns_ranked_chunks_from_current_collection(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    manager = FakeRetrievalManager()
    app = create_app(
        store=store,
        vector_builder_factory=lambda: FakeRetrievalVectorBuilder(manager),
    )
    client = TestClient(app)
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()
    store.update_knowledge_base_index_status(kb["id"], status="ready")

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/retrieval-test",
        json={"query": "怎么测试召回？", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "怎么测试召回？"
    assert payload["top_k"] == 2
    assert payload["collection_name"] == kb["collection_name"]
    assert manager.calls == [
        {
            "query": "怎么测试召回？",
            "k": 2,
            "collection_name": kb["collection_name"],
        }
    ]
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][0]["content"].startswith("Upload files")
    assert payload["results"][0]["source"] == "guide.md"
    assert payload["results"][0]["title_or_path"] == "Guide"
    assert payload["results"][0]["url"] == "https://example.com/guide"
    assert payload["results"][0]["chunk_index"] == 2
    assert payload["results"][1]["title_or_path"] == "docs/eval.md"


def test_api_retrieval_test_requires_ready_index(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    manager = FakeRetrievalManager()
    app = create_app(
        store=store,
        vector_builder_factory=lambda: FakeRetrievalVectorBuilder(manager),
    )
    client = TestClient(app)
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/retrieval-test",
        json={"query": "怎么测试召回？", "top_k": 3},
    )

    assert response.status_code == 400
    assert "索引未就绪" in response.json()["detail"]
    assert manager.calls == []


def test_api_retrieval_test_validates_query_and_top_k(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    app = create_app(
        store=store,
        vector_builder_factory=lambda: FakeRetrievalVectorBuilder(FakeRetrievalManager()),
    )
    client = TestClient(app)
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()
    store.update_knowledge_base_index_status(kb["id"], status="ready")

    empty_response = client.post(
        f"/api/knowledge-bases/{kb['id']}/retrieval-test",
        json={"query": " ", "top_k": 3},
    )
    invalid_top_k_response = client.post(
        f"/api/knowledge-bases/{kb['id']}/retrieval-test",
        json={"query": "怎么测试召回？", "top_k": 99},
    )

    assert empty_response.status_code == 400
    assert empty_response.json()["detail"] == "query is required"
    assert invalid_top_k_response.status_code == 422


def test_api_retrieval_test_loads_managed_provider_key_before_query(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    app_path = config_dir / "application.yaml"
    (config_dir / "model_roles.yaml").write_text("{}", encoding="utf-8")
    app_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "qwen": {
                        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                        "api_key_env": "TEST_RETRIEVAL_QWEN_KEY",
                        "default_model_name": "qwen3.7-plus",
                    }
                },
                "ingestion": {"chunk_size": 900, "chunk_overlap": 120},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    app_home = tmp_path / "var" / "app"
    app_home.mkdir(parents=True)
    (app_home / "provider_keys.yaml").write_text(
        yaml.safe_dump({"api_keys": {"qwen": "managed-retrieval-secret"}}, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_EVAL_APP_HOME", str(app_home))
    monkeypatch.delenv("TEST_RETRIEVAL_QWEN_KEY", raising=False)

    store = ProductStore(tmp_path / "state.sqlite")
    manager = FakeRetrievalManager("TEST_RETRIEVAL_QWEN_KEY", "managed-retrieval-secret")
    app = create_app(
        store=store,
        config_path=str(app_path),
        vector_builder_factory=lambda: FakeRetrievalVectorBuilder(manager),
    )
    client = TestClient(app)
    kb = client.post("/api/knowledge-bases", json={"name": "Docs"}).json()
    store.update_knowledge_base_index_status(kb["id"], status="ready")

    response = client.post(
        f"/api/knowledge-bases/{kb['id']}/retrieval-test",
        json={"query": "怎么测试召回？", "top_k": 1},
    )

    assert response.status_code == 200
    assert manager.calls[0]["collection_name"] == kb["collection_name"]


def test_api_import_index_generate_and_eval(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")

    app = create_app(
        store=store,
        workflow_engine=FakeWorkflowEngine(),
        vector_builder_factory=lambda: FakeVectorBuilder(),
        query_generator_factory=lambda: QueryGenerationService(
            store,
            model_client=lambda prompt: '["怎么导入资料？", "如何切分文本？", "怎么评分？"]',
        ),
        eval_engine_factory=lambda: FakeEvalEngine(),
    )
    client = TestClient(app)

    kb_response = client.post("/api/knowledge-bases", json={"name": "Docs"})
    assert kb_response.status_code == 200
    kb_id = kb_response.json()["id"]

    upload_response = client.post(
        f"/api/knowledge-bases/{kb_id}/files",
        files={"file": ("doc.txt", b"Import files, chunk text, and evaluate RAG.", "text/plain")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["status"] == "ready"

    index_response = client.post(f"/api/knowledge-bases/{kb_id}/index", json={"overwrite": True})
    assert index_response.status_code == 200
    assert index_response.json()["chunk_count"] >= 1

    workflow_response = client.post(
        "/api/workflows",
        json={"name": "Default", "graph": graph_with_source_db(kb_id)},
    )
    assert workflow_response.status_code == 200
    workflow_id = workflow_response.json()["id"]

    prepare_response = client.post(f"/api/workflows/{workflow_id}/prepare")
    assert prepare_response.status_code == 200
    assert prepare_response.json()["knowledge_base_id"] == kb_id
    assert prepare_response.json()["index_status"] == "ready"
    assert prepare_response.json()["chunk_count"] >= 1

    run_response = client.post(
        f"/api/workflows/{workflow_id}/run",
        json={"question": "How does this work?"},
    )
    assert run_response.status_code == 200
    assert "fake answer" in run_response.json()["answer"]

    capabilities_response = client.get("/api/runtime/capabilities")
    assert capabilities_response.status_code == 200
    assert capabilities_response.json()["ok"] is True
    assert capabilities_response.json()["output"]["contract_version"] == "v1"
    assert capabilities_response.json()["output"]["capabilities"]["workflow_invoke"] is True

    runtime_workflows_response = client.get("/api/runtime/workflows")
    assert runtime_workflows_response.status_code == 200
    runtime_workflows = runtime_workflows_response.json()["output"]["workflows"]
    assert runtime_workflows[0]["workflow_id"] == workflow_id
    assert runtime_workflows[0]["can_run"] is True

    deployment_response = client.post("/api/deployment/local/start")
    assert deployment_response.status_code == 200
    deployment = deployment_response.json()
    assert deployment["ok"] is True
    assert deployment["output"]["status"] == "running"
    assert deployment["output"]["contract_version"] == "v1"
    assert deployment["output"]["graph_contract"]["input"] == {"question": "string"}
    assert deployment["output"]["examples"]["invoke"].startswith("curl -X POST")
    assert deployment["metadata"]["ready_workflow_count"] >= 1
    assert deployment["output"]["workflows"][0]["workflow_id"] == workflow_id
    assert deployment["output"]["workflows"][0]["invoke"]["request"] == {"question": "如何导入文档？"}
    assert f"/api/runtime/workflows/{workflow_id}/invoke" in deployment["output"]["workflows"][0]["invoke"]["url"]

    runtime_invoke_response = client.post(
        f"/api/runtime/workflows/{workflow_id}/invoke",
        json={"question": "How does runtime work?"},
    )
    assert runtime_invoke_response.status_code == 200
    runtime_invoke = runtime_invoke_response.json()
    assert runtime_invoke["ok"] is True
    assert runtime_invoke["output"]["question"] == "How does runtime work?"
    assert "fake answer" in runtime_invoke["output"]["answer"]
    assert runtime_invoke["metadata"]["workflow_id"] == workflow_id
    assert runtime_invoke["metadata"]["knowledge_base_id"] == kb_id
    assert runtime_invoke["metadata"]["context_count"] == 1

    runtime_batch_response = client.post(
        f"/api/runtime/workflows/{workflow_id}/batch",
        json={"questions": ["one", "two"]},
    )
    assert runtime_batch_response.status_code == 200
    runtime_batch = runtime_batch_response.json()
    assert runtime_batch["ok"] is True
    assert len(runtime_batch["output"]["items"]) == 2
    assert runtime_batch["output"]["items"][0]["ok"] is True

    empty_question_response = client.post(
        f"/api/runtime/workflows/{workflow_id}/invoke",
        json={"question": "   "},
    )
    assert empty_question_response.status_code == 200
    assert empty_question_response.json()["ok"] is False
    assert empty_question_response.json()["error"]["code"] == "invalid_question"

    missing_body_response = client.post(f"/api/runtime/workflows/{workflow_id}/invoke")
    assert missing_body_response.status_code == 200
    assert missing_body_response.json()["ok"] is False
    assert missing_body_response.json()["error"]["code"] == "invalid_question"

    missing_workflow_response = client.post(
        "/api/runtime/workflows/999/invoke",
        json={"question": "hello"},
    )
    assert missing_workflow_response.status_code == 200
    assert missing_workflow_response.json()["ok"] is False
    assert missing_workflow_response.json()["error"]["code"] == "workflow_not_found"

    stale_kb = client.post("/api/knowledge-bases", json={"name": "Stale Docs"}).json()
    stale_workflow_response = client.post(
        "/api/workflows",
        json={"name": "Stale", "graph": graph_with_source_db(stale_kb["id"])},
    )
    stale_workflow_id = stale_workflow_response.json()["id"]
    stale_invoke_response = client.post(
        f"/api/runtime/workflows/{stale_workflow_id}/invoke",
        json={"question": "hello"},
    )
    assert stale_invoke_response.status_code == 200
    assert stale_invoke_response.json()["ok"] is False
    assert stale_invoke_response.json()["error"]["code"] == "index_not_ready"

    query_response = client.post(
        "/api/query-sets/generate",
        json={
            "knowledge_base_id": kb_id,
            "examples": ["如何上传文档？", "如何构建索引？", "如何运行评测？"],
            "target_count": 3,
            "name": "Smoke queries",
        },
    )
    assert query_response.status_code == 200
    query_set_id = query_response.json()["id"]

    eval_response = client.post(
        "/api/eval-runs",
        json={"query_set_id": query_set_id, "workflow_id": workflow_id},
    )
    assert eval_response.status_code == 200
    assert eval_response.json()["status"] == "completed"

    templates_response = client.get("/api/workflows/templates")
    assert templates_response.status_code == 200
    assert [item["id"] for item in templates_response.json()] == ["blank", "offline_db", "rag", "evaluation"]

    blank_response = client.get("/api/workflows/default?template_id=blank")
    assert blank_response.status_code == 200
    assert blank_response.json()["graph"]["templateId"] == "blank"

    blank_workflow_response = client.post(
        "/api/workflows",
        json={"name": "Blank draft", "graph": blank_response.json()["graph"]},
    )
    assert blank_workflow_response.status_code == 200
    blank_workflow_id = blank_workflow_response.json()["id"]
    blank_validate_response = client.post(
        "/api/workflows/validate",
        json={"name": "Blank draft", "graph": blank_response.json()["graph"]},
    )
    assert blank_validate_response.status_code == 200
    assert blank_validate_response.json()["ok"] is False
    blank_execute_response = client.post(f"/api/workflows/{blank_workflow_id}/execute", json={"inputs": {}})
    assert blank_execute_response.status_code == 400

    default_rag_response = client.get("/api/workflows/default?template_id=rag")
    assert default_rag_response.status_code == 200
    assert default_rag_response.json()["graph"]["templateId"] == "rag"

    offline_workflow_response = client.post(
        "/api/workflows",
        json={"name": "Offline DB", "graph": template_graph("offline_db", kb_id)},
    )
    assert offline_workflow_response.status_code == 200
    offline_workflow_id = offline_workflow_response.json()["id"]
    offline_prepare_response = client.post(f"/api/workflows/{offline_workflow_id}/prepare")
    assert offline_prepare_response.status_code == 200
    assert offline_prepare_response.json()["knowledge_base_id"] == kb_id

    rag_workflow_response = client.post(
        "/api/workflows",
        json={"name": "Runtime RAG", "graph": template_graph("rag", kb_id)},
    )
    assert rag_workflow_response.status_code == 200
    rag_workflow_id = rag_workflow_response.json()["id"]
    rag_run_response = client.post(
        f"/api/workflows/{rag_workflow_id}/run",
        json={"question": "How does RAG work?"},
    )
    assert rag_run_response.status_code == 200
    assert "fake answer" in rag_run_response.json()["answer"]
    rag_execute_response = client.post(
        f"/api/workflows/{rag_workflow_id}/execute",
        json={"inputs": {"question": "How does execute work?"}},
    )
    assert rag_execute_response.status_code == 200
    assert "fake answer" in rag_execute_response.json()["outputs"]["answer"]

    test_run_response = client.post(
        f"/api/workflows/{rag_workflow_id}/test-runs",
        json={"inputs": {"question": "How does test run work?"}},
    )
    assert test_run_response.status_code == 200
    test_run = test_run_response.json()
    assert test_run["run_id"]
    assert test_run["workflow_id"] == rag_workflow_id
    assert test_run["status"] in {"running", "completed"}
    for _ in range(50):
        test_run = client.get(f"/api/workflow-test-runs/{test_run['run_id']}").json()
        if test_run["status"] != "running":
            break
        time.sleep(0.02)
    assert test_run["status"] == "completed"
    assert "fake answer" in test_run["outputs"]["answer"]
    assert test_run["current_node_id"] is None
    assert [item["status"] for item in test_run["trace"]] == ["completed"] * len(test_run["trace"])
    assert any(item["type"] == "answer" and item["output"]["context_count"] == 1 for item in test_run["trace"])
    answer_test_trace = next(item for item in test_run["trace"] if item["type"] == "answer")
    assert answer_test_trace["input"]["question"] == "How does test run work?"
    assert answer_test_trace["output"]["answer"] == f"fake answer from {store.get_knowledge_base(kb_id)['collection_name']}"

    evaluation_workflow_response = client.post(
        "/api/workflows",
        json={"name": "Evaluation Workflow", "graph": template_graph("evaluation", kb_id)},
    )
    assert evaluation_workflow_response.status_code == 200
    evaluation_workflow = evaluation_workflow_response.json()
    node_run_response = client.post(
        f"/api/workflows/{evaluation_workflow['id']}/nodes/query_generate/run",
    )
    assert node_run_response.status_code == 200
    assert node_run_response.json()["query_set"]["target_count"] == 3

    workflow_eval_response = client.post(f"/api/workflows/{evaluation_workflow['id']}/evaluate")
    assert workflow_eval_response.status_code == 200
    workflow_eval = workflow_eval_response.json()
    assert workflow_eval["query_set"]["target_count"] == 3
    assert workflow_eval["answer_count"] == 3
    assert workflow_eval["eval_run"]["status"] == "completed"
    answer_trace = next(item for item in workflow_eval["trace"] if item["type"] == "answer")
    assert answer_trace["output"]["answer_count"] == 3
    assert answer_trace["output"]["context_count"] == 3

    runtime_workflows_after_templates = client.get("/api/runtime/workflows").json()["output"]["workflows"]
    runtime_ids = {item["workflow_id"] for item in runtime_workflows_after_templates}
    assert rag_workflow_id in runtime_ids
    assert offline_workflow_id not in runtime_ids
    assert evaluation_workflow["id"] not in runtime_ids
    assert blank_workflow_id not in runtime_ids
