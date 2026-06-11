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
    monkeypatch.setattr(
        "rag_eval.ingestion.loaders._render_url_text",
        lambda url, timeout=20: ("Demo", "Hello\nRAG docs"),
    )

    parsed = parse_url("https://example.com/demo")

    assert parsed.metadata["url"] == "https://example.com/demo"
    assert parsed.metadata["title"] == "Demo"
    assert "RAG docs" in parsed.content


def test_google_search_url_renders_original_url(monkeypatch):
    seen = {}

    def fake_render(url, timeout=20):
        seen["url"] = url
        return "Google Search", "Google Search\nRAG Eval result"

    monkeypatch.setattr("rag_eval.ingestion.loaders._render_url_text", fake_render)

    parsed = parse_url("https://www.google.com/search?q=rag%20eval")

    assert seen["url"] == "https://www.google.com/search?q=rag%20eval"
    assert "duckduckgo" not in seen["url"]
    assert parsed.metadata["url"] == "https://www.google.com/search?q=rag%20eval"
    assert parsed.metadata["extension"] == ".html"
    assert parsed.metadata["title"] == "Google Search"
    assert "Google Search" in parsed.content
    assert "search_query" not in parsed.metadata


def test_google_search_url_retries_google_lightweight_page_on_challenge(monkeypatch):
    seen = []

    def fake_render(url, timeout=20):
        seen.append(url)
        if len(seen) == 1:
            return "关于此网页", "关于此网页 我们的系统检测到您的计算机网络中存在异常流量。"
        return "1 - Google 搜索", "1 - 維基百科，自由的百科全書\n数学中的数字 1。"

    monkeypatch.setattr("rag_eval.ingestion.loaders._render_url_text", fake_render)

    original_url = "https://www.google.com/search?q=1&sourceid=chrome&ie=UTF-8"
    parsed = parse_url(original_url)

    assert seen[0] == original_url
    assert seen[1].startswith("https://www.google.com/search?")
    assert "q=1" in seen[1]
    assert "gbv=1" in seen[1]
    assert "pws=0" in seen[1]
    assert "duckduckgo" not in "\n".join(seen)
    assert parsed.metadata["url"] == original_url
    assert parsed.metadata["source"] == original_url
    assert parsed.metadata["rendered_url"] == seen[1]
    assert parsed.metadata["title"] == "1 - Google 搜索"
    assert "維基百科" in parsed.content
    assert "search_query" not in parsed.metadata


def test_parse_url_reports_missing_browser(monkeypatch):
    def fail_load_playwright():
        raise RuntimeError("浏览器渲染依赖未就绪；请先执行 .venv/bin/python -m playwright install chromium")

    monkeypatch.setattr("rag_eval.ingestion.loaders._load_playwright", fail_load_playwright)

    with pytest.raises(RuntimeError, match="playwright install chromium"):
        parse_url("https://example.com/demo")


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


def test_ingestion_service_rejects_url_without_text_chunks(tmp_path, monkeypatch):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")

    monkeypatch.setattr(
        "rag_eval.ingestion.service.parse_url",
        lambda url: ParsedDocument(content="", metadata={"source": url, "url": url}),
    )

    service = IngestionService(store, tmp_path / "uploads", chunk_size=100, chunk_overlap=0)

    with pytest.raises(ValueError, match="未获得可切分正文"):
        service.ingest_url(kb["id"], "https://example.com/app")

    sources = store.list_sources(kb["id"])
    assert sources[0]["status"] == "failed"
    assert sources[0]["error_code"] == "browser_challenge"
    assert "未获得可切分正文" in sources[0]["error"]
    assert store.list_chunks(kb["id"]) == []


def test_ingestion_service_rejects_js_redirect_shell(tmp_path, monkeypatch):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")

    monkeypatch.setattr(
        "rag_eval.ingestion.service.parse_url",
        lambda url: ParsedDocument(
            content="如果您在几秒钟内没有被重定向，请点击此处。",
            metadata={"source": url, "url": url, "extension": ".html"},
        ),
    )

    service = IngestionService(store, tmp_path / "uploads", chunk_size=100, chunk_overlap=0)

    with pytest.raises(ValueError, match="未获得可切分正文"):
        service.ingest_url(kb["id"], "https://example.com/app")

    sources = store.list_sources(kb["id"])
    assert sources[0]["status"] == "failed"
    assert sources[0]["error_code"] == "browser_challenge"
    assert "未获得可切分正文" in sources[0]["error"]
    assert store.list_chunks(kb["id"]) == []


def test_ingestion_service_rejects_browser_challenge_page(tmp_path, monkeypatch):
    store = ProductStore(tmp_path / "state.sqlite")
    kb = store.create_knowledge_base("Docs")

    monkeypatch.setattr(
        "rag_eval.ingestion.service.parse_url",
        lambda url: ParsedDocument(
            content="关于此网页 我们的系统检测到您的计算机网络中存在异常流量。此网页用于确认这些请求是由您而不是自动程序发出的。",
            metadata={"source": url, "url": url, "extension": ".html"},
        ),
    )

    service = IngestionService(store, tmp_path / "uploads", chunk_size=200, chunk_overlap=0)

    with pytest.raises(ValueError, match="未获得可切分正文"):
        service.ingest_url(kb["id"], "https://www.google.com/search?q=good")

    source = store.list_sources(kb["id"])[0]
    assert source["status"] == "failed"
    assert source["error_code"] == "browser_challenge"
    assert store.list_chunks(kb["id"]) == []


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
