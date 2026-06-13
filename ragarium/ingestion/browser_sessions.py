from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from .loaders import ParsedDocument, URL_HEADERS, _load_playwright, normalize_text


@dataclass
class BrowserSession:
    session_id: str
    knowledge_base_id: int
    source_id: int
    url: str
    title: str
    playwright: Any
    context: Any
    page: Any


class BrowserSessionManager:
    def __init__(self, profile_root: str | Path) -> None:
        self.profile_root = Path(profile_root)
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, BrowserSession] = {}

    def open_source(self, source: Dict[str, Any], *, timeout: int = 20) -> Dict[str, Any]:
        if source.get("source_type") != "url" or not source.get("uri"):
            raise ValueError("only URL sources can be opened in browser")

        # Playwright persistent contexts lock their profile directory. V1 keeps one
        # product-owned browser session open at a time so cookies can be reused.
        self.close_all()

        sync_playwright, playwright_error, playwright_timeout_error = _load_playwright()
        timeout_ms = timeout * 1000
        playwright = None
        try:
            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_root),
                headless=False,
                user_agent=URL_HEADERS["User-Agent"],
                locale="zh-CN",
                extra_http_headers={
                    "Accept-Language": URL_HEADERS["Accept-Language"],
                },
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(source["uri"], wait_until="domcontentloaded", timeout=timeout_ms)
            except playwright_timeout_error:
                pass
            session_id = uuid4().hex
            session = BrowserSession(
                session_id=session_id,
                knowledge_base_id=int(source["knowledge_base_id"]),
                source_id=int(source["id"]),
                url=str(source["uri"]),
                title=page.title() or str(source["uri"]),
                playwright=playwright,
                context=context,
                page=page,
            )
            self._sessions[session_id] = session
            return {
                "session_id": session_id,
                "knowledge_base_id": session.knowledge_base_id,
                "source_id": session.source_id,
                "url": session.url,
                "title": session.title,
                "status": "open",
            }
        except RuntimeError:
            if playwright is not None:
                playwright.stop()
            raise
        except playwright_error as exc:
            if playwright is not None:
                playwright.stop()
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                raise RuntimeError("浏览器渲染依赖未就绪；请先执行 .venv/bin/python -m playwright install chromium") from exc
            raise RuntimeError(f"打开交互式浏览器失败：{message}") from exc

    def extract(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"browser session not found: {session_id}")
        title = session.page.title() or session.url
        text = session.page.evaluate("() => document.body ? document.body.innerText : ''")
        return {
            "session_id": session_id,
            "knowledge_base_id": session.knowledge_base_id,
            "source_id": session.source_id,
            "url": session.url,
            "parsed": ParsedDocument(
                content=normalize_text(text or ""),
                metadata={
                    "source": session.url,
                    "url": session.url,
                    "extension": ".html",
                    "title": title,
                },
            ),
        }

    def close(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            raise KeyError(f"browser session not found: {session_id}")
        self._close_session(session)
        return {"session_id": session_id, "status": "closed"}

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            session = self._sessions.pop(session_id)
            self._close_session(session)

    @staticmethod
    def _close_session(session: BrowserSession) -> None:
        try:
            session.context.close()
        finally:
            session.playwright.stop()
