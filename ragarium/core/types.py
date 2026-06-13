# ragarium/core/types.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContextItem:
    """
    检索得到的单条上下文。
    """
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None  # 可选：相似度 / 距离等


@dataclass
class RagRecord:
    """
    RAG 调用的一条标准记录，用于后续评估与负例池。

    对 NormalRag：
      negative_contexts 为 None。

    对 NegativeRAG：
      negative_contexts 为负记忆检索得到的上下文。
    """
    question: str
    answer: str
    contexts: List[ContextItem]
    negative_contexts: Optional[List[ContextItem]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        def _ctx_to_dict(c: ContextItem) -> Dict[str, Any]:
            return {
                "content": c.content,
                "metadata": c.metadata,
                "score": c.score,
            }

        data = {
            "question": self.question,
            "answer": self.answer,
            "contexts": [_ctx_to_dict(c) for c in self.contexts],
            "extra": self.extra,
        }
        if self.negative_contexts is not None:
            data["negative_contexts"] = [_ctx_to_dict(c) for c in self.negative_contexts]
        return data
