from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


REFERENCE_FREE = "reference_free"
FULL = "full"

FAITHFULNESS = "faithfulness"
ANSWER_RELEVANCY = "answer_relevancy"
CONTEXT_PRECISION = "context_precision"
CONTEXT_RECALL = "context_recall"
CONTEXT_ENTITY_RECALL = "context_entity_recall"
CONTEXT_UTILIZATION = "context_utilization"
ANSWER_SIMILARITY = "answer_similarity"
ANSWER_CORRECTNESS = "answer_correctness"
SUMMARY_SCORE = "summary_score"


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    description: str
    requires_reference: bool
    default_enabled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "requires_reference": self.requires_reference,
            "default_enabled": self.default_enabled,
        }


class MetricValidationError(ValueError):
    pass


METRIC_REGISTRY: Dict[str, MetricSpec] = {
    FAITHFULNESS: MetricSpec(
        name=FAITHFULNESS,
        label="Faithfulness",
        description="回答是否被检索到的 contexts 支持，越低越可能幻觉。",
        requires_reference=False,
        default_enabled=True,
    ),
    ANSWER_RELEVANCY: MetricSpec(
        name=ANSWER_RELEVANCY,
        label="Answer relevancy",
        description="回答是否贴合 Query，冗余、跑题、不完整会扣分。",
        requires_reference=False,
        default_enabled=True,
    ),
    CONTEXT_PRECISION: MetricSpec(
        name=CONTEXT_PRECISION,
        label="Context precision",
        description="相关 context 是否排在更前，需要 reference。",
        requires_reference=True,
    ),
    CONTEXT_RECALL: MetricSpec(
        name=CONTEXT_RECALL,
        label="Context recall",
        description="contexts 是否覆盖 reference 所需信息，需要 reference。",
        requires_reference=True,
    ),
    CONTEXT_ENTITY_RECALL: MetricSpec(
        name=CONTEXT_ENTITY_RECALL,
        label="Context entity recall",
        description="contexts 是否覆盖 reference 中的实体，需要 reference。",
        requires_reference=True,
    ),
    CONTEXT_UTILIZATION: MetricSpec(
        name=CONTEXT_UTILIZATION,
        label="Context utilization",
        description="回答是否充分利用了检索到的 contexts，无需 reference；适合看召回内容有没有被答案真正用上。",
        requires_reference=False,
        default_enabled=True,
    ),
    ANSWER_SIMILARITY: MetricSpec(
        name=ANSWER_SIMILARITY,
        label="Answer similarity",
        description="答案与 reference 的语义相似度，需要 reference。",
        requires_reference=True,
    ),
    ANSWER_CORRECTNESS: MetricSpec(
        name=ANSWER_CORRECTNESS,
        label="Answer correctness",
        description="答案相对 reference 的事实正确性，需要 reference。",
        requires_reference=True,
    ),
    SUMMARY_SCORE: MetricSpec(
        name=SUMMARY_SCORE,
        label="Summary score",
        description="把回答当作 contexts 摘要来评估覆盖与简洁性，无需 reference；更适合摘要型回答，普通 RAG 仅作辅助参考。",
        requires_reference=False,
        default_enabled=True,
    ),
}


def list_metric_specs() -> List[Dict[str, Any]]:
    return [spec.to_dict() for spec in METRIC_REGISTRY.values()]


def default_metric_names() -> List[str]:
    return [name for name, spec in METRIC_REGISTRY.items() if spec.default_enabled]


def metric_names_for_preset(preset: str) -> List[str]:
    if preset == REFERENCE_FREE:
        return default_metric_names()
    if preset == FULL:
        return [FAITHFULNESS, ANSWER_RELEVANCY, CONTEXT_PRECISION, CONTEXT_RECALL]
    raise MetricValidationError(f"unknown metric preset: {preset}")


def normalize_metric_names(metric_names: Optional[Sequence[str]]) -> List[str]:
    if not metric_names:
        return default_metric_names()
    names: List[str] = []
    for raw_name in metric_names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        if name not in METRIC_REGISTRY:
            raise MetricValidationError(f"unknown RAGAS metric: {name}")
        if name not in names:
            names.append(name)
    if not names:
        raise MetricValidationError("at least one RAGAS metric must be selected")
    return names


def validate_metric_names(
    metric_names: Optional[Sequence[str]],
    records: Optional[Sequence[Any]] = None,
) -> List[str]:
    names = normalize_metric_names(metric_names)
    if records is not None:
        has_reference = any(bool(getattr(record, "ground_truth", None)) for record in records)
        if not has_reference:
            reference_metrics = [name for name in names if METRIC_REGISTRY[name].requires_reference]
            if reference_metrics:
                joined = ", ".join(reference_metrics)
                raise MetricValidationError(
                    f"RAGAS metrics require reference answers: {joined}. "
                    "当前评测集是 query-only，请只选择不依赖 reference 的指标。"
                )
    return names


def resolve_ragas_metric_names(metric_names: Sequence[str]) -> List[Any]:
    from ragas.metrics import (
        answer_correctness,
        answer_relevancy,
        answer_similarity,
        context_entity_recall,
        context_precision,
        context_recall,
        context_utilization,
        faithfulness,
        summarization_score,
    )

    metric_objects = {
        FAITHFULNESS: faithfulness,
        ANSWER_RELEVANCY: answer_relevancy,
        CONTEXT_PRECISION: context_precision,
        CONTEXT_RECALL: context_recall,
        CONTEXT_ENTITY_RECALL: context_entity_recall,
        CONTEXT_UTILIZATION: context_utilization,
        ANSWER_SIMILARITY: answer_similarity,
        ANSWER_CORRECTNESS: answer_correctness,
        SUMMARY_SCORE: summarization_score,
    }
    return [metric_objects[name] for name in normalize_metric_names(metric_names)]


def resolve_ragas_metrics(preset: str) -> List[Any]:
    return resolve_ragas_metric_names(metric_names_for_preset(preset))


def infer_metric_preset(records: list[Any]) -> str:
    has_reference = any(bool(getattr(record, "ground_truth", None)) for record in records)
    return FULL if has_reference else REFERENCE_FREE
