from __future__ import annotations

import io

import pytest

from rag_eval.ingestion.chunking import chunk_document
from rag_eval.ingestion.loaders import ParsedDocument, parse_file, parse_url
from rag_eval.ingestion.service import IngestionService
from rag_eval.storage import ProductStore


def test_parse_text_and_chunk_metadata(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# Guide\n\nImport docs and run evaluation.", encoding="utf-8")

    parsed = parse_file(path)
    chunks = chunk_document(parsed, chunk_size=12, chunk_overlap=2)

    assert parsed.metadata["source"] == "guide.md"
    assert chunks
    assert chunks[0]["metadata"]["source"] == "guide.md"
    assert chunks[0]["metadata"]["chunk_index"] == 0


def test_parse_legacy_doc_is_rejected(tmp_path):
    path = tmp_path / "old.doc"
    path.write_bytes(b"not really a doc")

    with pytest.raises(ValueError, match="convert it to .docx"):
        parse_file(path)


def test_parse_url_with_mocked_response(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"<html><title>Demo</title><body><h1>Hello</h1><p>RAG docs</p></body></html>"

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=20: FakeResponse())

    parsed = parse_url("https://example.com/demo")

    assert parsed.metadata["url"] == "https://example.com/demo"
    assert parsed.metadata["title"] == "Demo"
    assert "RAG docs" in parsed.content


def test_ingestion_service_persists_chunks(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("alpha beta gamma " * 40, encoding="utf-8")

    service = IngestionService(store, tmp_path / "uploads", chunk_size=50, chunk_overlap=5)
    source = service.ingest_file_path(kb["id"], file_path)

    chunks = store.list_chunks(kb["id"])
    assert source["status"] == "ready"
    assert len(chunks) > 1
    assert chunks[0]["metadata_json"]["source"] == "doc.txt"


def test_ingestion_service_accepts_per_source_chunk_options(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("0123456789" * 20, encoding="utf-8")

    service = IngestionService(store, tmp_path / "uploads", chunk_size=100, chunk_overlap=0)
    service.ingest_file_path(kb["id"], file_path, chunk_size=30, chunk_overlap=5)

    chunks = store.list_chunks(kb["id"])
    assert len(chunks) >= 6
    assert len(chunks[0]["content"]) <= 30


def test_ingestion_service_reprocesses_existing_sources(tmp_path):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")
    file_path = tmp_path / "doc.txt"
    file_path.write_text("abcdefghij" * 30, encoding="utf-8")

    service = IngestionService(store, tmp_path / "uploads", chunk_size=120, chunk_overlap=0)
    service.ingest_file_path(kb["id"], file_path)
    initial_count = len(store.list_chunks(kb["id"]))

    result = service.reprocess_knowledge_base_sources(
        kb["id"],
        chunk_size=40,
        chunk_overlap=5,
    )

    chunks = store.list_chunks(kb["id"])
    assert result["chunk_size"] == 40
    assert result["chunk_overlap"] == 5
    assert len(chunks) > initial_count
    assert len(chunks[0]["content"]) <= 40
