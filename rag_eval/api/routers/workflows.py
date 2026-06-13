from __future__ import annotations

from fastapi import APIRouter

from rag_eval.api.service import ApiService


def create_workflow_router(service: ApiService) -> APIRouter:
    router = APIRouter()
    router.add_api_route(
        "/api/workflows/templates", service.list_workflow_templates, methods=["GET"]
    )
    router.add_api_route(
        "/api/workflows/default", service.get_default_workflow, methods=["GET"]
    )
    router.add_api_route("/api/workflows", service.list_workflows, methods=["GET"])
    router.add_api_route(
        "/api/workflows/validate", service.validate_workflow, methods=["POST"]
    )
    router.add_api_route("/api/workflows", service.save_workflow, methods=["POST"])
    router.add_api_route(
        "/api/workflows/{workflow_id}/execute",
        service.execute_workflow_route,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/workflows/{workflow_id}/test-runs",
        service.create_workflow_test_run,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/workflow-test-runs/{run_id}",
        service.get_workflow_test_run,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/workflows/{workflow_id}/prepare",
        service.prepare_workflow,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/workflows/{workflow_id}/run", service.run_workflow, methods=["POST"]
    )
    router.add_api_route(
        "/api/workflows/{workflow_id}/nodes/{node_id}/run",
        service.run_workflow_node,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/workflows/{workflow_id}/evaluate",
        service.evaluate_workflow,
        methods=["POST"],
    )
    return router
