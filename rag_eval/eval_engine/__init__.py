# rag_eval/eval_engine/__init__.py

from .eval_result import EvalResult
from .rag_batch_runner import (
    RagEvalRecord,
    RagBatchRunner,
    RunnerProtocol,
    ProgressCallback,
)
from .ragas_eval import (
    run_ragas_evaluation,
    RagasEvaluator as _RagasBackendEvaluator,  # 仅作为内部使用
)
from .engine import EvalEngine
from .metric_presets import (
    FULL,
    REFERENCE_FREE,
    MetricValidationError,
    default_metric_names,
    infer_metric_preset,
    list_metric_specs,
    resolve_ragas_metric_names,
    resolve_ragas_metrics,
    validate_metric_names,
)

# 向后兼容别名：对外暴露的 RagasEvaluator = EvalEngine（runner + eval_samples 风格）
RagasEvaluator = EvalEngine

__all__ = [
    "EvalResult",
    "RagEvalRecord",
    "RagBatchRunner",
    "RunnerProtocol",
    "ProgressCallback",
    "run_ragas_evaluation",
    "EvalEngine",
    "RagasEvaluator",  # 注意：这里指向的是 EvalEngine，而不是 backend 级类
    "FULL",
    "REFERENCE_FREE",
    "MetricValidationError",
    "default_metric_names",
    "infer_metric_preset",
    "list_metric_specs",
    "resolve_ragas_metric_names",
    "resolve_ragas_metrics",
    "validate_metric_names",
]
