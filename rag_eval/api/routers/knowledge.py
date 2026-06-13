from __future__ import annotations

from fastapi import APIRouter

from rag_eval.api.service import ApiService


def create_knowledge_router(service: ApiService) -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/config", service.get_config, methods=["GET"])
    router.add_api_route("/api/config", service.update_config, methods=["PUT"])
    router.add_api_route(
        "/api/knowledge-bases", service.list_knowledge_bases, methods=["GET"]
    )
    router.add_api_route(
        "/api/knowledge-bases", service.create_knowledge_base, methods=["POST"]
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}",
        service.get_knowledge_base,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/files",
        service.upload_file,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/urls",
        service.import_url,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/sources/{source_id}",
        service.delete_source,
        methods=["DELETE"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/sources/{source_id}/browser-session",
        service.open_source_browser_session,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/browser-sessions/{session_id}/extract",
        service.extract_browser_session,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/browser-sessions/{session_id}/close",
        service.close_browser_session,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/index",
        service.build_index,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/knowledge-bases/{knowledge_base_id}/retrieval-test",
        service.test_knowledge_base_retrieval,
        methods=["POST"],
    )
    return router
