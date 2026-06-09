from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from fastapi.testclient import TestClient

from rag_eval.api import create_app
from rag_eval.query_generation import QueryGenerationService
from rag_eval.storage import ProductStore
from rag_eval.workflow import DEFAULT_WORKFLOW_GRAPH, WorkflowEngine


def graph_with_source_db(kb_id: int):
    graph = deepcopy(DEFAULT_WORKFLOW_GRAPH)
    for node in graph["nodes"]:
        if node["type"] == "source":
            node["data"]["knowledgeBaseId"] = str(kb_id)
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
