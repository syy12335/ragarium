# rag_eval/eval_engine/engine.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from rag_eval.eval_engine.rag_batch_runner import (
    RagBatchRunner,
    RunnerProtocol,
    RagEvalRecord,
    ProgressCallback,
)
from rag_eval.eval_engine.ragas_eval import RagasEvaluator
from rag_eval.eval_engine.eval_result import EvalResult
from utils import YamlConfigReader


class EvalEngine:
    """
    EvalEngine：评估层统一入口。

    职责：
      1. 基于给定 runner 和评估样本，调用 RagBatchRunner 生成 RagEvalRecord 列表；
      2. 调用 RagasEvaluator 执行 RAGAS 评估；
      3. 返回 EvalResult，供 CLI / Streamlit / NegativePoolBuilder 使用。

    不负责：
      1. 构建向量库；
      2. 具体 RAG 工作流逻辑（由 runner 决定）。
    """

    def __init__(
        self,
        config_path: str = "config/application.yaml",
        metrics: Optional[Sequence[Any]] = None,
        metric_preset: Optional[str] = None,
        limit: Optional[int] = None,
        show_progress: bool = True,
    ) -> None:
        """
        参数：
          config_path:
            application.yaml 路径，内部传给 RagasEvaluator 和样本加载逻辑。

          metrics:
            RAGAS 指标列表，传给 RagasEvaluator；
            若为 None，则使用 ragas_eval.py 中的默认指标集。

          limit:
            样本数上限。
              1）若在此处显式传入：
                    limit > 0  则只评估前 limit 条样本；
                    limit == 0 或 None 视为不限制，评估全部样本。
              2）若此处为 None，则从 config/application.yaml 中读取：
                    evaluation.sample_limit
                 规则同上：
                    sample_limit > 0  只评估前 sample_limit 条；
                    sample_limit == 0 或未配置  评估全部样本。

          show_progress:
            是否在命令行使用 tqdm 进度条；
            当提供 progress_callback 时，此参数会自动失效。
        """
        self.config_path = config_path
        self.metrics = metrics
        self.metric_preset = metric_preset
        self.show_progress = show_progress

        # 1）调用方显式传入 limit 的情况：0 表示不限制
        if limit is not None:
            self.limit = None if limit == 0 else limit
            return

        # 2）未显式传入 limit，则从配置中读取 evaluation.sample_limit
        try:
            cfg = YamlConfigReader(config_path)
            cfg_limit = cfg.get("evaluation.sample_limit")
            if cfg_limit is None:
                # 未配置时视为无限制
                self.limit = None
            else:
                value = int(cfg_limit)
                self.limit = None if value == 0 else value
        except Exception:
            # 配置异常时回退为无限制
            self.limit = None

    def _load_default_eval_samples(self) -> List[Dict[str, Any]]:
        """
        按 application.yaml 中的 dataset.samples_path 加载评估样本。

        约定：
          1）application.yaml 位于 project-root/config/；
          2）dataset.samples_path 为相对于 project-root 的 JSON 文件路径；
          3）JSON 顶层结构为列表，每个元素是一个 dict，至少包含 question 字段。
        """
        cfg = YamlConfigReader(self.config_path)
        project_root: Path = cfg.config_path.parent.parent

        samples_rel = cfg.get("dataset.samples_path")
        if not samples_rel:
            raise ValueError(
                "配置文件中未设置 dataset.samples_path，无法加载默认评估样本。"
            )

        samples_path = (project_root / samples_rel).resolve()
        if not samples_path.exists():
            raise FileNotFoundError(f"未找到评估样本文件：{samples_path}")

        with open(samples_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise TypeError("评估样本文件的顶层结构应为列表（list）。")

        return data

    def invoke(
        self,
        runner: RunnerProtocol,
        eval_samples: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> EvalResult:
        """
        执行一次完整评估流程。

        调用形式支持两种：
          1）EvalEngine().invoke(runner, eval_samples)
             由调用方显式提供样本列表。
          2）EvalEngine().invoke(runner)
             不提供样本时，自动从 application.yaml.dataset.samples_path 加载全部样本。
        """
        # 0. 如未显式传入 eval_samples，则按配置加载默认样本
        if eval_samples is None:
            eval_samples = self._load_default_eval_samples()

        if not eval_samples:
            raise ValueError("eval_samples 为空，无法执行评估。")

        # 1. 批量跑 RAG
        batch_runner = RagBatchRunner(runner, mode="eval")
        records: List[RagEvalRecord] = batch_runner.run_batch(
            eval_samples=eval_samples,
            limit=self.limit,  # None 表示评估全部样本
            show_progress=self.show_progress if progress_callback is None else False,
            progress_callback=progress_callback,
        )

        # 2. 调用 RAGAS 后端
        evaluator = RagasEvaluator(
            config_path=self.config_path,
            metrics=self.metrics,
            metric_preset=self.metric_preset,
        )
        result: EvalResult = evaluator.evaluate(records)

        return result
