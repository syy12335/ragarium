from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional

from ragarium.api.errors import utc_now


WorkflowProgressCallback = Callable[[Dict[str, Any]], None]
WorkflowExecutor = Callable[..., Dict[str, Any]]


class WorkflowTestRunManager:
    def __init__(
        self, *, workflow_engine: Any, execute_workflow: WorkflowExecutor
    ) -> None:
        self.workflow_engine = workflow_engine
        self.execute_workflow = execute_workflow
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def snapshot(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"workflow test run not found: {run_id}")
            snapshot = deepcopy(self._runs[run_id])
        for item in snapshot.get("trace") or []:
            item.pop("_started_monotonic", None)
        return snapshot

    def create_run(
        self,
        *,
        workflow_id: int,
        workflow: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        run_id = uuid.uuid4().hex
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "status": "running",
                "current_node_id": None,
                "current_node_type": None,
                "trace": self._trace_items(workflow["graph"]),
                "outputs": None,
                "error": None,
                "metadata": {"workflow_id": workflow_id},
                "started_at": utc_now(),
                "finished_at": None,
            }
        self._prune()
        thread = threading.Thread(
            target=self._run_in_background,
            args=(run_id, workflow, inputs),
            daemon=True,
        )
        thread.start()
        return self.snapshot(run_id)

    def _prune(self) -> None:
        with self._lock:
            if len(self._runs) <= 50:
                return
            removable = sorted(
                self._runs.items(),
                key=lambda item: item[1].get("started_at") or "",
            )[: len(self._runs) - 50]
            for run_id, _ in removable:
                self._runs.pop(run_id, None)

    def _trace_items(self, graph: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            validation = self.workflow_engine.validate_executable_graph(graph)
            if validation.is_legacy:
                return [
                    {
                        "node_id": "legacy_full_rag",
                        "type": "legacy_full_rag",
                        "status": "pending",
                    }
                ]
            return [
                {
                    "node_id": node["id"],
                    "type": node["type"],
                    "status": "pending",
                }
                for node in validation.ordered_nodes
            ]
        except Exception:
            return [
                {
                    "node_id": str(node.get("id") or ""),
                    "type": str(node.get("type") or "unknown"),
                    "status": "pending",
                }
                for node in graph.get("nodes") or []
                if node.get("id")
            ]

    def _update_run(self, run_id: str, patch: Dict[str, Any]) -> None:
        with self._lock:
            if run_id not in self._runs:
                return
            self._runs[run_id].update(patch)

    def _update_node(
        self,
        run_id: str,
        *,
        node_id: str,
        node_type: str,
        status: str,
        node_input: Optional[Dict[str, Any]] = None,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        now = utc_now()
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            trace = run.setdefault("trace", [])
            item = next(
                (entry for entry in trace if entry.get("node_id") == node_id), None
            )
            if item is None:
                item = {"node_id": node_id, "type": node_type, "status": "pending"}
                trace.append(item)
            item["type"] = node_type
            item["status"] = status
            if status == "running":
                item["started_at"] = now
                item["_started_monotonic"] = time.monotonic()
                run["current_node_id"] = node_id
                run["current_node_type"] = node_type
            else:
                item["finished_at"] = now
                started = item.pop("_started_monotonic", None)
                if started is not None:
                    item["duration_ms"] = int(
                        (time.monotonic() - float(started)) * 1000
                    )
            if node_input is not None:
                item["input"] = node_input
            if output is not None:
                item["output"] = output
            if error is not None:
                item["error"] = error
            if status == "failed":
                run["current_node_id"] = node_id
                run["current_node_type"] = node_type

    def _progress_callback(self, run_id: str) -> WorkflowProgressCallback:
        def callback(event: Dict[str, Any]) -> None:
            event_type = event.get("event")
            node_id = str(event.get("node_id") or "")
            node_type = str(event.get("type") or "unknown")
            if not node_id:
                return
            if event_type == "node_started":
                self._update_node(
                    run_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="running",
                    node_input=event.get("input") or {},
                )
            elif event_type == "node_completed":
                self._update_node(
                    run_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="completed",
                    output=event.get("output") or {},
                )
            elif event_type == "node_failed":
                self._update_node(
                    run_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="failed",
                    error=str(event.get("error") or "failed"),
                )

        return callback

    def _run_in_background(
        self,
        run_id: str,
        workflow: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> None:
        try:
            result = self.execute_workflow(
                workflow,
                inputs=inputs,
                progress_callback=self._progress_callback(run_id),
            )
            self._update_run(
                run_id,
                {
                    "status": "completed",
                    "current_node_id": None,
                    "current_node_type": None,
                    "outputs": result.get("outputs") or {},
                    "metadata": result.get("metadata")
                    or {"workflow_id": workflow["id"]},
                    "finished_at": utc_now(),
                },
            )
        except Exception as exc:
            self._update_run(
                run_id,
                {
                    "status": "failed",
                    "error": str(exc),
                    "finished_at": utc_now(),
                    "metadata": {"workflow_id": workflow["id"]},
                },
            )
