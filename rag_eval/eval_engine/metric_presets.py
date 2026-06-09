from __future__ import annotations

from typing import Any, List


REFERENCE_FREE = "reference_free"
FULL = "full"


def resolve_ragas_metrics(preset: str) -> List[Any]:
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    if preset == REFERENCE_FREE:
        return [faithfulness, answer_relevancy]
    if preset == FULL:
        return [faithfulness, answer_relevancy, context_precision, context_recall]
    raise ValueError(f"unknown metric preset: {preset}")


def infer_metric_preset(records: list[Any]) -> str:
    has_reference = any(bool(getattr(record, "ground_truth", None)) for record in records)
    return FULL if has_reference else REFERENCE_FREE
