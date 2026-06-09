from __future__ import annotations

from rag_eval.eval_engine.metric_presets import FULL, REFERENCE_FREE, infer_metric_preset
from rag_eval.eval_engine.rag_batch_runner import RagEvalRecord


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
