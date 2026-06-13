from __future__ import annotations

from fastapi import APIRouter

from ragarium.api.service import ApiService


def create_runtime_router(service: ApiService) -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/health", service.health, methods=["GET"])
    router.add_api_route(
        "/api/runtime/capabilities", service.runtime_capabilities, methods=["GET"]
    )
    router.add_api_route(
        "/api/runtime/workflows", service.runtime_workflows, methods=["GET"]
    )
    router.add_api_route(
        "/api/deployment/local/start", service.deploy_local_runtime, methods=["POST"]
    )
    router.add_api_route(
        "/api/runtime/workflows/{workflow_id}/invoke",
        service.runtime_invoke,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/runtime/workflows/{workflow_id}/batch",
        service.runtime_batch,
        methods=["POST"],
    )
    return router
