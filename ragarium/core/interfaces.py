# ragarium/core/interfaces.py
from typing import Protocol
from .types import RagRecord


class RagInvokerProtocol(Protocol):
    """
    统一的 RAG 执行协议：
      输入：question 字符串
      输出：RagRecord（可转换为 dict）
    """

    def invoke(self, question: str) -> RagRecord:  # type: ignore[override]
        ...
