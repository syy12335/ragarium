# ragarium/eval_engine/rag_batch_runner.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable, Callable

from tqdm import tqdm


@runtime_checkable
class RunnerProtocol(Protocol):
    """
    Runner 协议约定：

      invoke(question: str) -> dict

    返回的 dict 至少包含：
      - question: str
      - generation: str
      - contexts: List[
            str
          | 具有 page_content 属性的对象
          | 形如 {"content": str, ...} / {"page_content": str, ...} 的 dict
        ]
    """

    def invoke(self, question: str) -> Dict[str, Any]:
        ...


@dataclass
class RagEvalRecord:
    """
    评估阶段使用的统一样本结构。
    由 RagBatchRunner 负责构造，后续传给 RAGAS 等评估工具。

    字段含义：
      question:      原始问题
      answer:        RAG 生成的最终回答
      contexts:      与该回答相关的上下文文本列表（已经规整为纯字符串）
      ground_truth:  标准答案（可选，如基准数据集提供的参考答案）
      meta:          额外元信息（模式、索引、runner 名称等）
    """

    question: str
    answer: str
    contexts: List[str]
    ground_truth: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


# 进度回调类型：current, total
ProgressCallback = Callable[[int, int], None]


class RagBatchRunner:
    """
    RagBatchRunner：批量执行 RAG runner 并产出 RagEvalRecord 列表。

    职责：
      1. 遍历评估样本列表，逐条调用 runner.invoke(question)。
      2. 适配 runner 的输出结构，将结果规整为 RagEvalRecord。
      3. 将上下文统一转换为 List[str]，便于后续 RAGAS 处理。

    不负责：
      1. 构建向量库或加载数据集。
      2. 执行任何评估逻辑（打分由 RAGAS 等模块负责）。
    """

    def __init__(self, runner: RunnerProtocol, mode: str = "default"):
        """
        参数：
          runner: 满足 RunnerProtocol 的任意对象（DefaultRunner 或自定义 Runner）。
          mode:   可选的模式标签，用于写入 meta 便于区分实验。
        """
        if not isinstance(runner, RunnerProtocol):
            raise TypeError(
                "runner 未实现 RunnerProtocol 协议："
                "需要提供 invoke(question: str) -> dict 方法。"
            )

        self.runner = runner
        self.mode = mode

    def _normalize_contexts(self, raw_contexts: Any) -> List[str]:
        """
        将 runner 返回的 contexts 统一规整为 List[str]。

        支持的输入形式：
          1. List[str]
          2. List[Obj]，其中 Obj 具有 page_content 属性（如 LangChain Document）
          3. List[dict]，其中 dict 至少包含：
               - "content": str           或
               - "page_content": str

        其他形式将抛出异常，提示用户调整 runner 的输出结构。
        """
        if raw_contexts is None:
            return []

        if not isinstance(raw_contexts, list):
            raise ValueError(
                "runner 返回的 `contexts` 字段必须是列表类型，"
                f"当前类型为：{type(raw_contexts)}"
            )

        texts: List[str] = []
        for c in raw_contexts:
            # 1）已经是字符串
            if isinstance(c, str):
                texts.append(c)
                continue

            # 2）dict 形式：优先取 content / page_content 字段
            if isinstance(c, dict):
                if "content" in c:
                    texts.append(str(c["content"]))
                    continue
                if "page_content" in c:
                    texts.append(str(c["page_content"]))
                    continue
                # 其他字段一律视为不符合约定，继续走后面的通用分支报错

            # 3）通用对象：尝试读取 page_content 属性
            text = getattr(c, "page_content", None)
            if text is None:
                raise ValueError(
                    "contexts 列表中的元素既不是 str，"
                    "也不是包含 content/page_content 字段的 dict，"
                    "也不包含 page_content 属性，"
                    "请调整 runner.invoke 的返回结构。"
                )
            texts.append(str(text))

        return texts

    def run_batch(
        self,
        eval_samples: List[Dict[str, Any]],
        limit: Optional[int] = None,
        show_progress: bool = True,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> List[RagEvalRecord]:
        """
        批量执行 RAG。

        参数：
          eval_samples:
            样本列表，元素形如：
              {
                "question": "...",
                "ground_truth": "...",   # 可选
                "id": "...",             # 可选
                ...
              }

          limit:
            若设置，只处理前 limit 条样本。

          show_progress:
            是否使用 tqdm 显示进度条（仅在 progress_callback 为空时生效）。

          progress_callback:
            若提供，则每处理一条样本调用一次 progress_callback(current, total)，
            方便在外部（如 Streamlit）更新进度条。

        返回：
          RagEvalRecord 列表，可直接传给 RAGAS 评估模块。
        """
        if not eval_samples:
            return []

        samples = eval_samples
        if limit is not None:
            samples = samples[:limit]

        total = len(samples)
        records: List[RagEvalRecord] = []

        iterator = enumerate(samples)
        if show_progress and progress_callback is None:
            iterator = tqdm(
                iterator,
                total=total,
                desc=f"RAG [{self.mode}] Running",
                ncols=90,
            )

        for idx, sample in iterator:
            if "question" not in sample:
                raise KeyError(
                    "eval_samples 中的样本缺少 `question` 字段，"
                    f"样本索引：{idx}"
                )

            question = sample["question"]
            ground_truth = sample.get("ground_truth")

            # 1. 调用 runner 执行单条 RAG
            out = self.runner.invoke(question)

            if not isinstance(out, dict):
                raise TypeError(
                    "runner.invoke(question) 必须返回 dict，"
                    f"当前返回类型为：{type(out)}"
                )

            # 2. 解析回答
            answer = out.get("generation") or out.get("answer")
            if answer is None:
                raise KeyError(
                    "runner 返回结果中缺少 `generation` 字段，"
                    "请确保 invoke(question) 至少包含 "
                    "`generation` / `answer` 之一。"
                )
            answer = str(answer)

            # 3. 解析上下文并规整为 List[str]
            raw_contexts = out.get("contexts", [])
            contexts_text = self._normalize_contexts(raw_contexts)

            # 4. question 以 runner 返回为准，如无则回退到样本
            out_question = out.get("question", question)

            # 5. 组装 RagEvalRecord
            meta: Dict[str, Any] = {
                "idx": idx,
                "mode": self.mode,
                "sample_id": sample.get("id"),
                "runner_class": type(self.runner).__name__,
            }

            record = RagEvalRecord(
                question=out_question,
                answer=answer,
                contexts=contexts_text,
                ground_truth=ground_truth,
                meta=meta,
            )
            records.append(record)

            # 6. 进度回调（current 用 1 开始更直观）
            if progress_callback is not None:
                current = idx + 1
                progress_callback(current, total)

        return records
