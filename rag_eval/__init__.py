"""
rag_eval 顶层包的公共 API。

当前稳定暴露的核心组件包括：

1. VectorDatabaseBuilder
   用途：
       从评估样本（samples）与 chunk 文件构建向量库。

   典型用法：
       from rag_eval import VectorDatabaseBuilder
       builder = VectorDatabaseBuilder("config/application.yaml")
       manager = builder.invoke(overwrite=True)

2. dataset_tools
   用途：
       数据集适配层，目前内置 cmrc2018 子模块。

   典型用法：
       from rag_eval.dataset_tools import cmrc2018
       samples_path = cmrc2018.build_eval_samples(config)

3. RagRunner
   用途：
       基于已有向量库运行一条默认的 RAG 工作流（检索 + 生成），
       内部会根据 config/application.yaml 与 config/model_roles.yaml 的 generation 段构造 LLM 和提示词。

   典型用法：
       from rag_eval import VectorDatabaseBuilder, RagRunner

       builder = VectorDatabaseBuilder("config/application.yaml")
       vector_manager = builder.invoke(overwrite=False)

       runner = RagRunner.from_vector_store(
           vector_manager,
           config_path="config/application.yaml",
       )

       result = runner.invoke("这里写你的问题")

4. EvalEngine
   用途：
       基于给定的 runner 和评估样本，批量执行 RAG 并通过 RAGAS 自动评估。

   典型用法：
       from rag_eval import EvalEngine

       engine = EvalEngine()  # 默认读取 config/application.yaml 和 model_roles.yaml
       eval_result = engine.invoke(runner, eval_samples)
       eval_result.show_console(top_n=5)
"""

__all__ = [
    "VectorDatabaseBuilder",
    "dataset_tools",
    "RagRunner",
    "EvalEngine",
]


def __getattr__(name: str):
    if name == "VectorDatabaseBuilder":
        from .vector.vector_builder import VectorDatabaseBuilder

        return VectorDatabaseBuilder
    if name == "dataset_tools":
        from . import dataset_tools

        return dataset_tools
    if name == "RagRunner":
        from .rag import RagRunner

        return RagRunner
    if name == "EvalEngine":
        from .eval_engine import EvalEngine

        return EvalEngine
    raise AttributeError(f"module 'rag_eval' has no attribute {name!r}")
