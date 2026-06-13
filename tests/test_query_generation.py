from __future__ import annotations

import pytest

from ragarium.query_generation import QueryGenerationService
from ragarium.storage import ProductStore


def test_query_generation_validates_example_count(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    service = QueryGenerationService(store, model_client=lambda prompt: "[]")

    with pytest.raises(ValueError, match="3 to 5"):
        service.generate(knowledge_base_id=1, examples=["one"], target_count=2)


def test_query_generation_rejects_invalid_json(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    service = QueryGenerationService(store, model_client=lambda prompt: "not json")

    with pytest.raises(ValueError, match="JSON array"):
        service.parse_queries("not json")


def test_query_generation_persists_query_only_set(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    source = store.create_source(kb["id"], source_type="file", name="doc.txt", status="ready")
    store.replace_source_chunks(
        kb["id"],
        source["id"],
        [
            {
                "chunk_index": 0,
                "content": "Users can import files, build chunks, and run RAG evaluation.",
                "metadata": {"source": "doc.txt", "chunk_index": 0},
            }
        ],
    )
    service = QueryGenerationService(
        store,
        model_client=lambda prompt: '["怎么导入文档？", "如何构建向量库？", "怎么运行评测？"]',
    )

    query_set = service.generate(
        knowledge_base_id=kb["id"],
        examples=["上传文档怎么做？", "如何运行 RAG？", "评测指标有哪些？"],
        target_count=3,
    )

    assert query_set["queries"] == ["怎么导入文档？", "如何构建向量库？", "怎么运行评测？"]
    assert "queries_json" not in query_set
