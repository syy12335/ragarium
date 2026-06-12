from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import math
import os

from datasets import Dataset, Features, Sequence as HFSequence, Value

from ragas import evaluate as ragas_evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_openai import ChatOpenAI

import pandas as pd

from utils import YamlConfigReader
from rag_eval.eval_engine.rag_batch_runner import RagEvalRecord
from rag_eval.eval_engine.eval_result import EvalResult
from rag_eval.eval_engine.metric_presets import infer_metric_preset, resolve_ragas_metrics


def _build_ragas_dataset(records: List[RagEvalRecord]) -> Dataset:
    """
    将 RagEvalRecord 列表转换为 RAGAS 期望的 Dataset 结构。

    字段约定（对应 RAGAS 传统接口）：
      question:      str                    # 问题文本
      answer:        str                    # RAG 生成的回答
      contexts:      List[str]              # 上下文文本列表
      ground_truth:  str                    # 标准答案（可以为空字符串）
    """
    if not records:
        raise ValueError("records 为空，无法构建 RAGAS 数据集。")

    questions: List[str] = []
    answers: List[str] = []
    contexts_list: List[List[str]] = []
    ground_truths: List[str] = []

    for r in records:
        questions.append(str(r.question) if r.question is not None else "")
        answers.append(str(r.answer) if r.answer is not None else "")

        ctx_texts: List[str] = []
        for c in r.contexts or []:
            text = getattr(c, "page_content", c)
            ctx_texts.append(str(text))
        contexts_list.append(ctx_texts)

        gt = r.ground_truth if r.ground_truth is not None else ""
        ground_truths.append(str(gt))

    raw_data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths,
    }

    features = Features(
        {
            "question": Value("string"),
            "answer": Value("string"),
            "contexts": HFSequence(Value("string")),
            "ground_truth": Value("string"),
        }
    )

    ds = Dataset.from_dict(raw_data)
    ds = ds.cast(features)

    # 调试输出（稳定后可视情况删除）
    print("[debug] RAGAS Dataset:", ds)
    print("[debug] features:", ds.features)
    ctx_feat = ds.features["contexts"]
    print(
        "[debug] contexts feature -> type:",
        type(ctx_feat),
        "inner dtype:",
        getattr(ctx_feat, "feature", None).dtype if getattr(ctx_feat, "feature", None) else None,
    )

    return ds


def _load_model_roles(config: YamlConfigReader) -> YamlConfigReader:
    """
    加载与 application.yaml 同级目录下的 model_roles.yaml。

    约定：
      application.yaml 位于 project-root/config/
      model_roles.yaml 也位于 project-root/config/
    """
    roles_path = config.config_path.parent / "model_roles.yaml"
    if not roles_path.exists():
        raise FileNotFoundError(
            f"未在 {roles_path} 找到 model_roles.yaml，"
            "评估层需要通过该文件获取 provider / model_name 等角色配置。"
        )
    return YamlConfigReader(str(roles_path))


def _build_ragas_components(config: YamlConfigReader):
    """
    构造 RAGAS 评估使用的 LLM 与 Embedding 封装。

    规则：

      1）从 model_roles.yaml 中读取：
           embedding.provider / embedding.model_name
           evaluation.provider / evaluation.model_name （新增）
         若 evaluation 未配置，则回退到 generation，再回退到 embedding。

      2）根据 provider 找到 application.yaml.llm.<provider> 段，
         使用其中的 api_key_env 从环境变量获取 API Key。

      3）embedding 与向量库保持完全一致：
         评估所用 embedding 模型 = embedding.model_name。
    """
    roles_cfg = _load_model_roles(config)

    # 1. embedding 角色：用于向量库和 RAGAS 的 embedding 计算
    emb_provider = roles_cfg.get("embedding.provider") or "qwen"
    emb_model_name = (
        roles_cfg.get("embedding.model_name")
        or roles_cfg.get("embedding.model")
        or "text-embedding-v4"
    )

    # 2. evaluation 角色：用于 RAGAS 的判分 LLM
    #    优先 evaluation.*，其次 fallback 到 generation.*，最后 fallback 到 embedding.*
    eval_provider = (
        roles_cfg.get("evaluation.provider")
        or roles_cfg.get("generation.provider")
        or emb_provider
    )

    eval_model_name = (
        roles_cfg.get("evaluation.model")
        or roles_cfg.get("evaluation.model_name")
        or roles_cfg.get("generation.model")
        or roles_cfg.get("generation.model_name")
        or config.get(f"llm.{eval_provider}.default_eval_model_name")
        or config.get(f"llm.{eval_provider}.default_model_name")
        or "qwen3.7-plus"
    )

    eval_temperature = roles_cfg.get("evaluation.temperature", 0)
    eval_max_tokens = roles_cfg.get("evaluation.max_tokens", 1024)

    # 3. RAGAS embedding 继续使用 DashScope；Judge LLM 则走统一 OpenAI 兼容接口，
    #    与 Answer 节点保持一致，避免同一个模型在不同 SDK 下表现不一致。
    if emb_provider != "qwen":
        raise NotImplementedError(
            "当前 RAGAS embedding backend 仅支持 provider='qwen'，"
            f"检测到 embedding.provider={emb_provider}。"
        )

    # 4. 从 application.yaml.llm.<provider> 读取 API Key 环境变量名
    llm_section_key = f"llm.{eval_provider}"
    api_key_env = config.get(f"{llm_section_key}.api_key_env") or "API_KEY_QWEN"
    base_url = config.get(f"{llm_section_key}.base_url")
    api_key = os.environ.get(api_key_env)
    if not base_url:
        raise ValueError(
            f"未在 application.yaml 中找到 {llm_section_key}.base_url，"
            "请先配置该 Provider 的 Base URL。"
        )
    if not api_key:
        raise ValueError(
            f"未在环境变量 {api_key_env} 中找到 API Key，"
            "请先设置该环境变量。"
        )

    # 5. 构造 RAGAS 用的 LLM 与 Embedding 封装
    llm = LangchainLLMWrapper(
        ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=eval_model_name,
            temperature=eval_temperature,
            max_tokens=eval_max_tokens,
            extra_body={"enable_thinking": False} if eval_provider == "qwen" else None,
        )
    )

    embeddings = LangchainEmbeddingsWrapper(
        DashScopeEmbeddings(
            model=emb_model_name,
            dashscope_api_key=api_key,
        )
    )

    return llm, embeddings


def run_ragas_evaluation(
    records: List[RagEvalRecord],
    config_path: str = "config/application.yaml",
    metrics: Optional[Sequence[Any]] = None,
    metric_preset: Optional[str] = None,
) -> EvalResult:
    """
    以函数方式执行一次完整的 RAGAS 评估流程。

    参数：
      records:
        来自 RagBatchRunner 的 RagEvalRecord 列表。

      config_path:
        application.yaml 路径，默认 "config/application.yaml"。

      metrics:
        要使用的 RAGAS 指标列表。
        若为 None，则根据 metric_preset 或样本是否含 ground_truth 自动选择。

      metric_preset:
        "reference_free" 只跑 faithfulness / answer_relevancy，适合 query-only 数据集。
        "full" 跑 faithfulness / answer_relevancy / context_precision / context_recall。

    返回：
      EvalResult 对象，封装整体指标、逐样本结果、Dataset、CSV 路径等信息。
    """
    if not records:
        raise ValueError("records 为空，无法执行 RAGAS 评估。")

    config = YamlConfigReader(config_path)

    project_root = config.config_path.parent.parent

    csv_rel_path = config.get("evaluation.output_csv")
    if not csv_rel_path:
        raise ValueError(
            "未在 application.yaml 中配置 evaluation.output_csv，"
            "请在 config/application.yaml 的 evaluation 段中设置默认写入路径，例如：\n"
            "evaluation:\n"
            "  output_csv: \"data/evaluation/ragas_result.csv\""
        )

    csv_path = (project_root / csv_rel_path).resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = _build_ragas_dataset(records)

    eval_llm, eval_embeddings = _build_ragas_components(config)

    if metrics is None:
        preset = metric_preset or infer_metric_preset(records)
        metrics = resolve_ragas_metrics(preset)

    for m in metrics:
        if hasattr(m, "embeddings"):
            setattr(m, "embeddings", eval_embeddings)

    result = ragas_evaluate(
        dataset=dataset,
        metrics=list(metrics),
        llm=eval_llm,
        embeddings=eval_embeddings,
    )

    df: pd.DataFrame = result.to_pandas()

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[ragas_eval] 已将评估结果写入：{csv_path}")

    overall: Dict[str, Optional[float]] = {}
    for m in metrics:
        name = getattr(m, "name", None)
        if name is None:
            continue
        raw_value = None
        try:
            raw_value = result[name]
        except Exception:
            raw_value = result.get(name)
        if raw_value is None:
            overall[name] = None
            continue
        try:
            value = float(raw_value)
            overall[name] = value if math.isfinite(value) else None
        except Exception:
            overall[name] = None

    eval_result = EvalResult(
        overall=overall,
        per_sample=df,
        dataset=dataset,
        csv_path=str(csv_path),
        raw_result=result,
    )
    return eval_result


class RagasEvaluator:
    """
    RagasEvaluator：面向对象的评估封装。

    用法示例：

      from rag_eval.eval_engine import RagBatchRunner, RagasEvaluator

      runner = DefaultRunner()
      batch = RagBatchRunner(runner)

      records = batch.run_batch(eval_samples, limit=200)
      evaluator = RagasEvaluator()
      eval_result = evaluator.evaluate(records)

      eval_result.show_console()
    """

    def __init__(
        self,
        config_path: str = "config/application.yaml",
        metrics: Optional[Sequence[Any]] = None,
        metric_preset: Optional[str] = None,
    ):
        self.config_path = config_path
        self.metrics = metrics
        self.metric_preset = metric_preset

    def evaluate(self, records: List[RagEvalRecord]) -> EvalResult:
        """
        执行 RAGAS 评估。
        """
        return run_ragas_evaluation(
            records=records,
            config_path=self.config_path,
            metrics=self.metrics,
            metric_preset=self.metric_preset,
        )
