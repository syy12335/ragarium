from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ragarium.workflow import WorkflowValidationError


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, WorkflowValidationError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        converted = float(value)
        if not math.isfinite(converted):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return json_safe(value.tolist())
        except Exception:
            pass
    try:
        if value != value:
            return None
    except Exception:
        pass
    if str(value) in {"nan", "NaN", "<NA>", "NaT"}:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def runtime_success(
    output: Any, metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "ok": True,
        "output": output,
        "metadata": metadata or {},
    }


def runtime_error(
    code: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
        "metadata": metadata or {},
    }
