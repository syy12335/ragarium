# RAG Eval

本项目是一个本地运行的 RAG 评测产品。它把资料导入、知识库切分与索引、Workflow 编排、Query 评测集生成、RAGAS 评测和外部 HTTP 调用放在同一个控制台里，适合用来快速验证一个 RAG 系统是否“能检索、能回答、能评测、能被其他程序调用”。

默认语言是中文；默认模型服务商是千问。

## 你可以用它做什么

- 导入自己的资料包：支持 `.txt`、`.md`、`.html`、`.pdf`、`.docx` 和普通静态单页 URL。
- 管理本地知识库 DB：资料会解析、切分成 chunks，并写入本地 Chroma 向量库。
- 搭建 Workflow：用画布保存自己的 Graph，也可以从空白、离线建库、RAG、评测模板开始。
- 生成 query-only 评测集：输入 3-5 个示例 Query，模型会结合知识库内容生成更多 Query。
- 做无参考答案评测：默认使用不依赖标准答案的 RAGAS 指标。
- 对外提供 Runtime API：其他语言可以通过 HTTP/JSON 调用某个 RAG Graph 的输入输出。

## 快速开始

### 1. 安装依赖

建议使用 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

安装前端依赖：

```bash
cd frontend
npm install
cd ..
```

### 2. 配置千问 API Key

默认配置只需要一个千问 Key：

```bash
export API_KEY_QWEN="your-api-key"
```

Windows 当前会话：

```bat
set API_KEY_QWEN=your-api-key
```

默认模型角色：

- Embedding：`text-embedding-v4`
- Answer：`qwen3.7-plus`
- Judge：`qwen3.7-plus`

如需修改模型或 Provider，可以在产品里的「配置」页调整，也可以直接编辑：

- `config/application.yaml`
- `config/model_roles.yaml`

### 3. 启动后端

```bash
.venv/bin/python -m uvicorn rag_eval.api.app:app --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

### 4. 启动前端

另开一个终端：

```bash
cd frontend
npm run dev -- --port 5173
```

打开：

```text
http://127.0.0.1:5173/
```

## 推荐工作顺序

### 1. 配置模型

进入「配置」页，确认默认 Provider 和三个模型角色：

- Embedding：用于把 chunks 写入向量库。
- Answer：用于 RAG 回答。
- Judge：用于 RAGAS 评测。

第一版默认只保留千问，普通使用无需新增 Provider。

### 2. 准备数据

进入「数据」页：

1. 选择「知识库」。
2. 创建一个知识库。
3. 导入资料：选择本地文件，或粘贴一个 URL。
4. 导入完成后构建索引。

说明：

- `.doc` 暂不支持，请先转成 `.docx`。
- URL 默认做静态 HTML 抓取；动态页面、登录页或需要浏览器渲染的页面可能无法解析正文。
- Chunk size / overlap 放在「高级设置」里，默认值通常可以直接使用。

### 3. 搭建 Workflow

进入「Workflow」页后，先选择：

- 加载已有 Graph
- 新建 Graph

新建 Graph 可以选择：

- 空白
- 创建离线数据库
- 进行 RAG
- 评测

保存 Graph 不要求它立刻可运行；执行前才会做可执行性校验。一个可被 Runtime API 调用的 RAG Graph 通常需要从 `Start` 接收 `question`，经过 `Retrieve -> Prompt / LLM -> Answer`，最后到 `End`。

### 4. 生成评测集

进入「数据」页的「评测集」：

1. 选择一个知识库 DB。
2. 输入 3-5 个示例 Query。
3. 点击生成。

模型会结合知识库 chunks 和示例 Query 的风格生成 query-only 数据集，不生成 reference answer。

### 5. 运行评测

进入「评测」页：

1. 选择 Query 集。
2. 选择一个可回答 Query 的 RAG Graph。
3. 点击运行评测。

query-only 评测默认使用 reference-free 指标，例如：

- `faithfulness`
- `answer_relevancy`

只有样本包含 `ground_truth` / `reference` 时，才适合使用 context precision / recall 这类依赖参考答案的指标。

### 6. 部署 Runtime API

进入「导航」页的第 6 步「部署 API 调用」，点击「一键部署」后，会展示：

- Runtime API 服务地址
- Contract version
- 可调用 Graph 列表
- 某个 Graph 的输入 JSON
- 输出 JSON
- `invoke` / `batch` 的 curl 示例

Runtime API 只暴露可从 `question` 执行到 `Answer` 的 RAG Graph。离线建库和评测 Graph 不会作为外部 invoke 目标。

## Runtime API

### 查询能力

```bash
curl http://127.0.0.1:8000/api/runtime/capabilities
```

### 查询可调用 Graph

```bash
curl http://127.0.0.1:8000/api/runtime/workflows
```

### 单条调用

```bash
curl -X POST http://127.0.0.1:8000/api/runtime/workflows/1/invoke \
  -H 'Content-Type: application/json' \
  -d '{"question":"如何导入文档？"}'
```

成功响应结构：

```json
{
  "ok": true,
  "output": {
    "question": "如何导入文档？",
    "answer": "模型生成的答案",
    "contexts": ["检索命中的上下文"]
  },
  "metadata": {
    "workflow_id": 1,
    "knowledge_base_id": 1,
    "collection_name": "kb_1_docs",
    "top_k": 3,
    "context_count": 1
  }
}
```

### 批量调用

```bash
curl -X POST http://127.0.0.1:8000/api/runtime/workflows/1/batch \
  -H 'Content-Type: application/json' \
  -d '{"questions":["如何导入文档？","如何运行评测？"]}'
```

## 本地数据保存在哪里

第一版是单用户本地产品，没有登录、权限和多租户。

常见本地数据：

- SQLite 状态库：默认在 `var/app` 下。
- 上传原文件：保存到本地应用目录。
- Chroma 向量库：按配置或知识库 collection 落本地目录。
- 评测结果：保存在本地状态库，并可按旧脚手架配置输出 CSV。

这些目录通常属于本地运行产物，不应该提交到 Git。

## 旧脚手架入口

如果你只想跑旧的命令行 demo，仍可以使用：

```bash
python quickstart.py
```

旧 Streamlit 控制台仍保留：

```bash
streamlit run streamlit_app.py
```

但当前主产品入口是 React + FastAPI：

```text
http://127.0.0.1:5173/
```

## 目录结构

```text
frontend/                 # React + React Flow 产品前端
rag_eval/api/             # FastAPI HTTP API
rag_eval/ingestion/       # 文件 / URL 解析、chunk 生成
rag_eval/workflow/        # Graph 校验与执行
rag_eval/query_generation.py
rag_eval/vector/          # Chroma 向量库构建与管理
rag_eval/eval_engine/     # RAGAS 评测
rag_eval/storage.py       # SQLite 本地状态库
config/                   # 模型、Provider、chunk、评测配置
tests/                    # 后端单测与集成测试
```

## 测试与构建

后端测试：

```bash
.venv/bin/python -m pytest -q
```

前端构建：

```bash
cd frontend
npm run build
```

## 设计约束

- 第一版是单机本地产品。
- URL 只做单页导入，不做站点爬取。
- 默认不替用户把搜索页换成其他搜索服务；用户给什么 URL，就解析这个 URL 本身。
- 默认评测走 query-only / reference-free 路径，避免空 reference 造成误导性分数。
- Runtime API 只负责调用已准备好的 RAG Graph，不隐式触发导入、切分、索引或评测。
