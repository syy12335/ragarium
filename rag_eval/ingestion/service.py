from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from rag_eval.app_config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, AppConfigService
from rag_eval.storage import ProductStore

from .chunking import chunk_document
from .loaders import ParsedDocument, parse_file, parse_url

UNREADABLE_SOURCE_ERROR = "未解析到可切分文本；该页面可能需要浏览器渲染或登录态，当前静态抓取无法解析正文"
BLOCKED_PAGE_MARKERS = (
    "trouble accessing google search",
    "enablejs",
    "enable javascript",
    "javascript is disabled",
    "requires javascript",
    "需要启用 javascript",
    "login required",
    "please log in",
)
SHORT_SHELL_MARKERS = (
    *BLOCKED_PAGE_MARKERS,
    "没有被重定向",
    "请点击此处",
    "please click here",
    "send feedback",
)
SHELL_TEXT_MAX_LENGTH = 180


class IngestionService:
    def __init__(
        self,
        store: ProductStore,
        upload_root: str | Path = "var/app/uploads",
        *,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        config_service: Optional[AppConfigService] = None,
    ) -> None:
        self.store = store
        self.upload_root = Path(upload_root)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.config_service = config_service
        self.upload_root.mkdir(parents=True, exist_ok=True)

    def _kb_upload_dir(self, knowledge_base_id: int) -> Path:
        path = self.upload_root / f"kb_{knowledge_base_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ingest_file_path(
        self,
        knowledge_base_id: int,
        path: str | Path,
        *,
        original_name: Optional[str] = None,
        copy_into_store: bool = True,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> Dict[str, Any]:
        source_path = Path(path)
        name = original_name or source_path.name
        stored_path = source_path
        if copy_into_store:
            stored_path = self._kb_upload_dir(knowledge_base_id) / name
            if source_path.resolve() != stored_path.resolve():
                shutil.copyfile(source_path, stored_path)

        source = self.store.create_source(
            knowledge_base_id,
            source_type="file",
            name=name,
            stored_path=str(stored_path),
        )
        try:
            parsed = parse_file(stored_path, original_name=name)
            chunks = chunk_document(
                parsed,
                chunk_size=self._resolve_chunk_size(chunk_size),
                chunk_overlap=self._resolve_chunk_overlap(chunk_overlap),
            )
            self._ensure_parseable_text(parsed, chunks)
            self.store.replace_source_chunks(knowledge_base_id, source["id"], chunks)
            self.store.update_source_status(source["id"], status="ready", stored_path=str(stored_path))
            source = self.store.get_source(source["id"])
            source["chunk_count"] = len(chunks)
            return source
        except Exception as exc:
            self.store.replace_source_chunks(knowledge_base_id, source["id"], [])
            self.store.update_source_status(source["id"], status="failed", error=str(exc))
            raise

    def ingest_bytes(
        self,
        knowledge_base_id: int,
        *,
        filename: str,
        data: bytes,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> Dict[str, Any]:
        target = self._kb_upload_dir(knowledge_base_id) / filename
        target.write_bytes(data)
        return self.ingest_file_path(
            knowledge_base_id,
            target,
            original_name=filename,
            copy_into_store=False,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def ingest_url(
        self,
        knowledge_base_id: int,
        url: str,
        *,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> Dict[str, Any]:
        source = self.store.create_source(
            knowledge_base_id,
            source_type="url",
            name=url,
            uri=url,
        )
        try:
            parsed = parse_url(url)
            chunks = chunk_document(
                parsed,
                chunk_size=self._resolve_chunk_size(chunk_size),
                chunk_overlap=self._resolve_chunk_overlap(chunk_overlap),
            )
            self._ensure_parseable_text(parsed, chunks)
            self.store.replace_source_chunks(knowledge_base_id, source["id"], chunks)
            self.store.update_source_status(source["id"], status="ready")
            source = self.store.get_source(source["id"])
            source["chunk_count"] = len(chunks)
            return source
        except Exception as exc:
            self.store.replace_source_chunks(knowledge_base_id, source["id"], [])
            self.store.update_source_status(source["id"], status="failed", error=str(exc))
            raise

    def reprocess_knowledge_base_sources(
        self,
        knowledge_base_id: int,
        *,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> Dict[str, Any]:
        sources = self.store.list_sources(knowledge_base_id)
        if not sources:
            raise ValueError("knowledge DB has no sources to prepare")

        resolved_chunk_size = self._resolve_chunk_size(chunk_size)
        resolved_chunk_overlap = self._resolve_chunk_overlap(chunk_overlap)
        processed: List[Dict[str, Any]] = []
        errors: List[str] = []

        for source in sources:
            try:
                parsed = self._parse_existing_source(source)
                chunks = chunk_document(
                    parsed,
                    chunk_size=resolved_chunk_size,
                    chunk_overlap=resolved_chunk_overlap,
                )
                self._ensure_parseable_text(parsed, chunks)
                self.store.replace_source_chunks(
                    knowledge_base_id,
                    int(source["id"]),
                    chunks,
                )
                self.store.update_source_status(source["id"], status="ready")
                item = self.store.get_source(source["id"])
                item["chunk_count"] = len(chunks)
                processed.append(item)
            except Exception as exc:
                message = f"{source.get('name')}: {exc}"
                errors.append(message)
                self.store.replace_source_chunks(
                    knowledge_base_id,
                    int(source["id"]),
                    [],
                )
                self.store.update_source_status(
                    source["id"],
                    status="failed",
                    error=str(exc),
                )

        if errors:
            raise ValueError("; ".join(errors))

        return {
            "knowledge_base_id": knowledge_base_id,
            "sources": processed,
            "chunk_size": resolved_chunk_size,
            "chunk_overlap": resolved_chunk_overlap,
            "chunk_count": len(self.store.list_chunks(knowledge_base_id)),
        }

    def _parse_existing_source(self, source: Dict[str, Any]) -> ParsedDocument:
        source_type = source.get("source_type")
        if source_type == "file":
            stored_path = source.get("stored_path")
            if not stored_path:
                raise ValueError("file source is missing stored_path")
            return parse_file(stored_path, original_name=source.get("name"))
        if source_type == "url":
            uri = source.get("uri")
            if not uri:
                raise ValueError("url source is missing uri")
            return parse_url(uri)
        raise ValueError(f"unsupported source type: {source_type}")

    @staticmethod
    def _ensure_parseable_text(parsed: ParsedDocument, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            raise ValueError(UNREADABLE_SOURCE_ERROR)
        text = " ".join((parsed.content or "").split())
        normalized = text.lower()
        if any(marker in normalized for marker in BLOCKED_PAGE_MARKERS):
            raise ValueError(UNREADABLE_SOURCE_ERROR)
        if len(text) <= SHELL_TEXT_MAX_LENGTH and any(marker in normalized for marker in SHORT_SHELL_MARKERS):
            raise ValueError(UNREADABLE_SOURCE_ERROR)

    def _default_chunk_config(self) -> Dict[str, int]:
        if self.config_service is None:
            return {
                "chunk_size": self.chunk_size or DEFAULT_CHUNK_SIZE,
                "chunk_overlap": self.chunk_overlap if self.chunk_overlap is not None else DEFAULT_CHUNK_OVERLAP,
            }
        try:
            return self.config_service.read()["chunk"]
        except Exception:
            return {
                "chunk_size": self.chunk_size or DEFAULT_CHUNK_SIZE,
                "chunk_overlap": self.chunk_overlap if self.chunk_overlap is not None else DEFAULT_CHUNK_OVERLAP,
            }

    def _resolve_chunk_size(self, explicit: Optional[int]) -> int:
        if explicit is not None:
            return int(explicit)
        if self.chunk_size is not None:
            return int(self.chunk_size)
        return int(self._default_chunk_config()["chunk_size"])

    def _resolve_chunk_overlap(self, explicit: Optional[int]) -> int:
        if explicit is not None:
            return int(explicit)
        if self.chunk_overlap is not None:
            return int(self.chunk_overlap)
        return int(self._default_chunk_config()["chunk_overlap"])
