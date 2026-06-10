# rag-eval-scaffold

一个轻量级的 RAG 评测脚手架，用一条命令跑通「数据集 → 向量库 → RAG 工作流 → 评估」，内置基于 Streamlit 的轻量可视化控制台，并提供解耦的向量库管理层（VectorManager）、RAG Runner 层与评估层，统一通过 invoke 接口衔接。

当前默认示例仍提供中文问答数据集和一条基础 RAG 工作流，并内置模型服务的配置示例（默认 Qwen），整体设计不绑定任何单一厂商，可通过配置接入其他兼容的对话与 embedding 服务。

## 1. 项目定位与目标人群

1. 作为 RAG / LLM 工程脚手架  
   用于有实验需求或工程需求的用户，在统一协议下完成：  
   1）构建和管理向量库；  
   2）编排一条或多条 RAG 工作流并输出统一结构；  
   3）调用评估引擎，对不同工作流、数据集和指标进行对比。

2. 作为从 0 到 1 的 RAG 学习项目  
   面向缺乏完整工程经验的用户，本项目已经把「数据集 → 向量库 → 检索 → 生成 → 评估」整条链路的接口穿在一起：  
   从默认实现开始，可以按模块逐步替换或扩展，而不必反复查阅各组件文档。

## 2. 核心特点（当前版本）

1. 一行构建向量库并获取 VectorManager  
   通过统一入口可以在一行代码内完成：  
   1）按配置加载基准数据集；  
   2）构建或更新向量库；  
   3）返回一个向量库管理工具 VectorManager，用于检索、增删文档以及构造 retriever。  
   配置集中在 `config/application.yaml` 中，包含数据路径、切分策略、向量库持久化位置等。

2. 数据集 / 向量库层、RAG 层与评估层彻底解耦  
   1）数据集 / 向量库层只负责「样本 → chunks → 向量库」，对上暴露 VectorManager。  
   2）RAG 层只关心「如何利用 VectorManager 检索加调用 LLM 组成工作流」，统一通过 Runner 的 `invoke` 暴露结果。  
   3）评估层只依赖 Runner 协议与样本格式，不感知底层向量库和具体工作流实现，便于切换数据集、模型与流水线。

3. 统一的 `invoke` 协议  
   1）向量库管理工具通过统一的接口对外提供检索能力（例如 `VectorManager().invoke(query: str, k: int = 5) -> List[Document]`），只关心“给定 query 返回哪些文档”；  
   2）所有 Runner 实现统一的 `Runner().invoke(question: str) -> dict` 接口，返回约定结构（question、generation、contexts 等）；  
   3）评估引擎统一通过 `EvalEngine().invoke(runner)` 触发评估流程，内部再调用批量执行与具体评估方法。

4. 低门槛可修改性 与 高阶可扩展性  
   默认 chunking 逻辑和 workflow 结构尽量保持直观，便于初学者直接阅读和修改：  
   1）初学者可以从默认 chunking 和 workflow 入手，直接改 prompt、改检索策略、增减简单节点；  
   2）高阶用户则可以完全忽略默认实现，只需通过 VectorManager 取到 retriever，并实现符合协议的 Runner（保留 `invoke` 签名和输出结构），即可直接接入评估层对比不同 RAG 方案。

## 3. 安装与环境配置

1. Python 版本要求  
   建议使用 Python 3.10 及以上版本。

2. 安装依赖  

   在项目根目录执行：

   ```bash
   pip install -r requirements.txt
   ```

3. 配置模型与 API Key

   默认配置只使用千问：`text-embedding-v4` 负责 Embedding，`qwen3.7-plus` 负责回答和评测。先设置一个千问 API Key 即可：

   Windows 当前会话示例：

   ```bat
   set API_KEY_QWEN=your-api-key # 千问
   ```

   如果确实需要接入其他 Provider，再到「配置」页或 `config/application.yaml` 里手动新增。

## 4. Quick Start：一条命令跑通

在项目根目录执行：

```bash
python quickstart.py
```

带前端版本：

```bash
streamlit run streamlit_app.py
```

默认流程包括以下步骤：

1. 构建基准数据集与向量库  
   1）从原始数据构建评估样本（samples）；  
   2）根据配置对样本中的上下文字段进行切分，生成 chunks；  
   3）构建或更新本地向量库，并持久化到指定目录。

2. 加载评估样本  
   从 `dataset.samples_path` 读取规范化样本.

3. 使用默认 Runner 批量运行 RAG  
   默认 Runner 内部使用 VectorManager 来检索上下文，并通过配置的模型生成回答，  
   按约定输出 `question`、`generation`、`contexts` 等字段。

4. 调用评估引擎进行评估  
   1）将 Runner 的输出规整为标准记录结构；  
   2）调用 RAGAS 等评估方法，计算整体指标与逐样本指标；  
   3）将结果输出到控制台，并根据配置写出 CSV 等文件。

只要依赖、配置与 API Key 正常，这一条命令即可完成从数据到评估报告的完整闭环。

## 5. 高级用法概览

本节只描述思路与接口约定，具体示例以仓库中的示例脚本为准。

### 5.1 使用 VectorManager 进行自定义检索与管理

典型流程为：

1. 通过统一入口构建向量库接口 `VectorDatabaseBuilder().invoke()` 并获取 VectorManager（内部按约定从 `config/application.yaml` 加载配置）；  

2. 使用 VectorManager 提供的接口执行以下操作：  
   1）按条件追加新文档（`add_documents(...)`）；  
   2）删除或重建集合（`delete_collection(...)`）；  
   3）获取 retriever 或直接检索若干条文档（`get_retriever(...)` 或 `invoke(...)`）；  
   4）配合自定义模型进行问答或分析。

VectorManager 会隐藏底层向量库的具体实现细节，使 RAG 工作流的代码只依赖一个统一的检索接口。

示例用法：

```python
from rag_eval import VectorDatabaseBuilder

# 根据配置信息构建向量数据库，返回该数据库的管理器 VectorManager
vector_manager = VectorDatabaseBuilder().invoke()

# 直接用 invoke 做相似度检索，返回若干条文档
docs = vector_manager.invoke("《战国无双3》是由哪两个公司合作开发的？", k=5)
```

如果需要使用自定义数据集，请阅读`rag_eval\dataset_tools\__init__.py`

### 5.2 自定义 Runner 并接入评估层

Runner 协议约定如下（简化示意）：

```python
class MyRunner:
    def __init__(self, vector_manager, ...):
        self.vector_manager = vector_manager
        # 其他模型、prompt、workflow 配置

    def invoke(self, question: str) -> dict:
        """
        按约定返回结构，供评估层理解：
          question: 原始问题
          generation: 模型最终回答（字符串）
          contexts: 用于回答该问题的检索上下文列表
        """
        ...
        return {
            "question": question,
            "generation": answer_text,
            "contexts": context_list,
        }
```

评估层只依赖 `invoke` 的输入输出协议，因此：  
1）只要返回结构满足约定，即可直接接入评估引擎；  
2）内部使用哪个模型、如何拼接 prompt、是否使用多轮链路，评估层均不关心。

### 5.3 使用统一评估引擎进行评估

评估入口形式类似（示意）：

```python
from rag_eval import EvalEngine

runner = MyRunner(...)
eval_result = EvalEngine().invoke(runner)
eval_result.show_console(top_n=5)
```

EvalEngine 内部负责：

1. 加载评估样本（可由配置控制样本数量等）；  
2. 批量调用 Runner 的 `invoke`；  
3. 调用 RAGAS 等评估方法；  
4. 汇总整体指标与逐样本结果，并提供控制台展示与前端展示接口。

### 5.4 使用 Streamlit 前端进行调试与展示（可选）

如果希望使用图形界面进行调试或展示，可以运行项目内的 Streamlit 应用。典型用法如下：

1. 在项目根目录执行：

   ```bash
   streamlit run streamlit_app.py
   ```

2. 前端通常包含两类模式：  
   1）评估模式  
      1）基于当前配置执行评估流程，展示整体指标与逐样本评分表；  
      2）可以选择样本数量、触发评估，并在页面上看到进度与预估耗时；  
      3）支持查看单条样本的 question、ground_truth、generation 与 contexts 等细节。  
   2）Chat 模式  
      1）复用当前配置下的 Runner 进行交互式 RAG 问答；  
      2）用于直观感受检索质量与回答质量，配合评估结果进行调试。

前端的存在并不改变底层接口约定，只是将已有的 Runner、评估引擎和结果展示封装成一个易于交互的控制台界面。

## 6. 配置与目录结构（简要）

具体结构可能随版本演进略有调整，以仓库实际为准。典型布局如下：

```text
config/
  application.yaml          # 全局配置：数据集、向量库、模型与评估等
  agents.yaml               # 模型角色、prompt、agent 配置等

datasets/
  raw/                      # 原始数据集
  processed/                # 处理后的 samples / chunks 等

rag_eval/
  __init__.py
  core/                     # 核心类型与接口定义
    __init__.py
    interfaces.py
    types.py
  dataset_tools/            # 从 raw 到 samples 与 chunks 的相关工具
    __init__.py
    cmrc2018/
      ...                   # CMRC2018 相关脚本
  embeddings/
    __init__.py
    factory.py              # embedding 工厂与封装
  eval_engine/              # 批量执行与评估引擎（EvalEngine 等）
    __init__.py
    engine.py
    eval_result.py
    rag_batch_runner.py
    ragas_eval.py
  rag/                      # 默认 RAG workflow 与 Runner
    __init__.py
    normal_rag.py
    runner.py
  vector/                   # 向量库构建与 VectorManager 实现
    __init__.py
    vector_builder.py
    vector_store_manager.py

utils/
  ...                       # 通用工具

quickstart.py               # 一键跑通示例脚本
quickstart.ipynb            # 对应的 Notebook 示例（可选）
streamlit_app.py            # 可视化控制台入口
```

主要配置集中在 `config/application.yaml` 中，通常包括：

1. 数据相关路径与样本数量限制；  
   2. 向量库后端配置（持久化目录、集合名、embedding 模型等）；  
   3. 检索参数（例如 top_k 等）；  
   4. 模型与 API 设置；  
   5. 评估输出路径与评估参数。

## 7. 当前状态与后续规划（概述）

1. 当前版本已经完成：  
   1）数据集 / 向量库层、RAG 层与评估层的彻底解耦；  
   2）面向向量库的一行构建与 VectorManager 管理接口；  
   3）统一 `invoke` 协议下的 Runner 与评估引擎；  
   4）在一键运行基础上增加高级定制入口，并优化前端逻辑与进度提示；  
   5）提供用于调试与展示的 Streamlit 控制台。

2. 计划中的扩展方向包括：  
   1）增加更多基准数据集与示例 Runner；  
   2）扩充评估方法和指标，并支持更灵活的评估配置；  
   3）为不同模型服务提供更完善的配置模板与示例。

如果只想先跑通一个端到端的 RAG 加评估链路，可以直接从 `quickstart.py` 开始；  
如果对工程化与扩展性有更高要求，可以从 VectorManager、Runner 协议和 Streamlit 前端入手，逐步替换和扩展各个模块。
