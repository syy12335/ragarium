from __future__ import annotations

from fastapi import APIRouter

from ragarium.api.service import ApiService


def create_evaluation_router(service: ApiService) -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/query-sets", service.list_query_sets, methods=["GET"])
    router.add_api_route(
        "/api/query-sets/generate", service.generate_query_set, methods=["POST"]
    )
    router.add_api_route("/api/eval-runs", service.list_eval_runs, methods=["GET"])
    router.add_api_route(
        "/api/eval-metrics", service.list_eval_metrics, methods=["GET"]
    )
    router.add_api_route("/api/eval-runs", service.create_eval_run, methods=["POST"])
    return router
