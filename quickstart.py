"""
quickstart.py

一行命令跑通完整链路：
    python quickstart.py

执行流程：
    1）构建 / 加载向量库（VectorDatabaseBuilder）
    2）用向量库做一次检索并打印检索到的文档
    3）构建 RagRunner，跑一条 normal_rag 链路生成回答
    4）用 EvalEngine 对整条 RAG 链路进行评估，并在控制台展示结果

评估样本数上限由 config/application.yaml 中的 evaluation.sample_limit 控制：
    0 或未配置 → 评估全部样本
"""

from __future__ import annotations

from typing import Any, Iterable

from ragarium import VectorDatabaseBuilder, RagRunner, EvalEngine


def pretty_print_docs(docs: Iterable[Any], max_docs: int = 3, max_chars: int = 400) -> None:
    """
    控制台友好打印检索结果，避免输出过长、过乱。

    约定：
      docs 为一个可迭代对象，元素通常为带有
        - page_content: str
        - metadata: dict (可选)
      属性的对象（例如 LangChain 的 Document）。
    """
    docs = list(docs)
    total = len(docs)
    print(f"\n[Retrieval] 共检索到 {total} 条文档")

    if total == 0:
        print("无检索结果。")
        return

    for idx, doc in enumerate(docs[:max_docs], start=1):
        print("\n" + "=" * 60)
        print(f"Document {idx}")

        # 尝试读取 source / id 等元信息
        meta = getattr(doc, "metadata", None)
        if isinstance(meta, dict):
            source = meta.get("source") or meta.get("id") or meta.get("doc_id")
            if source:
                print(f"[source] {source}")

        # 打印正文（或其前 max_chars 个字符）
        content = getattr(doc, "page_content", None)
        if not isinstance(content, str):
            content = str(doc)

        if len(content) > max_chars:
            print(content[:max_chars] + " ...")
        else:
            print(content)


def main() -> None:
    # 问题可以根据需要自行修改
    question = "《战国无双3》是由哪两个公司合作开发的？"

    print("[1] 构建 / 加载向量库（VectorDatabaseBuilder）...")
    vector_manager = VectorDatabaseBuilder().invoke()

    print(f"\n[2] 使用向量库检索问题：{question}")
    docs = vector_manager.invoke(question)
    pretty_print_docs(docs)

    print("\n[3] 构建 RagRunner 并运行 normal_rag 工作流...")
    runner = RagRunner(vector_manager, rag_type="normal_rag")
    result = runner.invoke(question)

    print("\n[RAG Answer]")
    # 如果 result 是 dict，优先打印 answer 字段
    if isinstance(result, dict) and "answer" in result:
        print(result["answer"])
    else:
        print(result)

    print("\n[4] 调用 EvalEngine 进行批量评估...")
    eval_engine = EvalEngine()
    eval_result = eval_engine.invoke(runner)  # limit 由 evaluation.sample_limit 控制
    eval_result.show_console(top_n=5)

    print("\n全部流程结束。")


if __name__ == "__main__":
    main()
