from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

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
