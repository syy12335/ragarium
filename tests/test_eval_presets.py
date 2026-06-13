from __future__ import annotations

import pytest

from ragarium.eval_engine.metric_presets import (
    FULL,
    REFERENCE_FREE,
    MetricValidationError,
    infer_metric_preset,
    list_metric_specs,
    validate_metric_names,
)
from ragarium.eval_engine.rag_batch_runner import RagEvalRecord
from ragarium.eval_engine.ragas_eval import _build_ragas_dataset


def test_query_only_records_use_reference_free_preset():
    records = [
        RagEvalRecord(question="q1", answer="a1", contexts=["c1"]),
        RagEvalRecord(question="q2", answer="a2", contexts=["c2"], ground_truth=""),
    ]

    assert infer_metric_preset(records) == REFERENCE_FREE


def test_ground_truth_records_use_full_preset():
    records = [
        RagEvalRecord(question="q1", answer="a1", contexts=["c1"], ground_truth="reference"),
    ]

    assert infer_metric_preset(records) == FULL


def test_metric_registry_marks_reference_requirements():
    specs = {item["name"]: item for item in list_metric_specs()}

    assert specs["faithfulness"]["default_enabled"] is True
    assert specs["answer_relevancy"]["requires_reference"] is False
    assert specs["context_utilization"]["requires_reference"] is False
    assert specs["context_utilization"]["default_enabled"] is True
    assert specs["summary_score"]["requires_reference"] is False
    assert specs["summary_score"]["default_enabled"] is True
    assert specs["answer_correctness"]["requires_reference"] is True


def test_query_only_records_reject_reference_metrics():
    records = [RagEvalRecord(question="q1", answer="a1", contexts=["c1"])]

    assert validate_metric_names(["faithfulness", "context_utilization", "summary_score"], records) == [
        "faithfulness",
        "context_utilization",
        "summary_score",
    ]
    with pytest.raises(MetricValidationError, match="require reference answers"):
        validate_metric_names(["context_recall"], records)


def test_ragas_dataset_maps_answer_to_summary_for_summary_score():
    dataset = _build_ragas_dataset([
        RagEvalRecord(question="q1", answer="answer text", contexts=["context text"]),
    ])

    assert "summary" in dataset.column_names
    assert dataset[0]["summary"] == "answer text"
