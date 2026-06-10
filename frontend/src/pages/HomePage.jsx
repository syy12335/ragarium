import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  PlugZap,
  Rocket,
} from 'lucide-react';
import { API_BASE, api } from '../api.js';
import { Button, Panel, StatusPill } from '../components/ui.jsx';

const workflowSteps = [
  {
    title: '配置模型与 Chunk',
    body: '先在配置里确认 Provider、默认 Embedding / Answer / Judge 模型，以及默认 Chunk 参数。',
    target: 'config',
  },
  {
    title: '准备数据',
    body: '在数据里新建知识库 DB，导入 File 或静态 URL，检查来源状态后构建索引。',
    target: 'data',
  },
  {
    title: '搭建 Workflow',
    body: '加载已有 Graph，或从空白/模板新建 Graph，再配置节点参数和连线。',
    target: 'workflow',
  },
  {
    title: '生成评测集',
    body: '用 3-5 个示例 Query 生成 query-only 评测集，后续作为评分输入。',
    target: 'queries',
  },
  {
    title: '运行评测',
    body: '在评测里选择 Query 集和可回答的 RAG Graph，运行 reference-free RAGAS 指标。',
    target: 'evaluation',
  },
  {
    title: '部署 API 调用',
    body: '一键检查并启动本地 Runtime API，然后查看其他语言可直接使用的 HTTP 调用方式。',
    action: 'deploy',
    icon: PlugZap,
  },
];

const fallbackGraphContract = {
  input: { question: '如何导入文档？' },
  batch_input: { questions: ['如何导入文档？', '如何运行评测？'] },
  output: {
    ok: true,
    output: {
      question: '如何导入文档？',
      answer: '模型生成的答案',
      contexts: ['检索命中的上下文片段'],
    },
    metadata: {
      workflow_id: 1,
      knowledge_base_id: 1,
      collection_name: 'kb_1_docs',
      top_k: 3,
      context_count: 1,
    },
  },
};

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

export function HomePage({ remote, onNavigate, runTask }) {
  const [view, setView] = useState('landing');
  const [capabilities, setCapabilities] = useState(null);
  const [deployment, setDeployment] = useState(null);
  const [deployError, setDeployError] = useState('');

  useEffect(() => {
    api.runtimeCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  const callableWorkflows = useMemo(
    () => remote.workflows.filter((workflow) => {
      try {
        if (!workflow.runtime_capable) {
          return false;
        }
        const retrieveNode = workflow.graph.nodes.find((node) => node.type === 'retrieve');
        const sourceNode = workflow.graph.nodes.find((node) => node.type === 'source');
        const queryNode = workflow.graph.nodes.find((node) => node.type === 'query_generate');
        const kbId = retrieveNode?.data?.knowledgeBaseId || sourceNode?.data?.knowledgeBaseId || queryNode?.data?.knowledgeBaseId;
        const kb = remote.knowledgeBases.find((item) => String(item.id) === String(kbId));
        return kb?.index_status === 'ready';
      } catch {
        return false;
      }
    }),
    [remote.workflows, remote.knowledgeBases],
  );

  async function deployRuntime() {
    setDeployError('');
    const result = await runTask('部署 Runtime API', api.startLocalDeployment);
    if (result) {
      setDeployment(result);
      return;
    }
    setDeployError('部署失败，请查看左下角状态信息。');
  }

  if (view === 'deploy') {
    const output = deployment?.output;
    const metadata = deployment?.metadata || {};
    const examples = output?.examples || {};
    const graphContract = output?.graph_contract || fallbackGraphContract;
    const baseUrl = output?.base_url || API_BASE;
    const deployedWorkflows = output?.workflows || callableWorkflows;

    return (
      <div className="deployment-page">
        <div className="editor-header action-return-bar">
          <Button icon={ArrowLeft} variant="secondary" onClick={() => setView('landing')}>
            返回导航
          </Button>
          <div>
            <strong>部署 API 调用</strong>
            <span>先把本地 Runtime API 准备好，再给其他语言按 HTTP/JSON 调用。</span>
          </div>
        </div>

        <div className="deployment-layout">
          <Panel
            title="一键部署"
            actions={(
              <Button icon={Rocket} onClick={deployRuntime}>
                一键部署
              </Button>
            )}
          >
            <div className="deploy-summary">
              <div>
                <span>服务地址</span>
                <strong>{baseUrl}</strong>
              </div>
              <div>
                <span>Contract</span>
                <strong>{output?.contract_version || capabilities?.output?.contract_version || 'v1'}</strong>
              </div>
              <div>
                <span>可调用 Workflow</span>
                <strong>{metadata.ready_workflow_count ?? callableWorkflows.length}</strong>
              </div>
            </div>

            <div className="hint-box">
              <strong>{output?.message || '点击“一键部署”后会检查本地 Runtime API，并返回可调用的 Workflow 与调用示例。'}</strong>
              <span>如果没有可调用 Workflow，请先完成数据索引，并在 Workflow 中保存一个从 question 到 Answer 的 RAG Graph。</span>
            </div>
            {deployError ? <p className="error-text">{deployError}</p> : null}
          </Panel>

          {deployment ? (
            <Panel title="怎么用 API 调用">
              <div className="api-callout">
                <strong>调用顺序：先拿 Graph，再传输入，再读输出</strong>
                <span>先查询可调用 Workflow，选择某个 workflow_id，然后把 question 传给这个 Graph 的 invoke 或 batch endpoint。</span>
              </div>

              <div className="api-example-grid">
                <div>
                  <strong>1. 查看可调用 Workflow</strong>
                  <pre><code>{examples.list_workflows || `curl -s ${baseUrl}/api/runtime/workflows`}</code></pre>
                </div>
              </div>

              <div className="runtime-workflow-list">
                <strong>2. 调用某个 Graph</strong>
                {deployedWorkflows.length ? (
                  deployedWorkflows.map((workflow) => (
                    <div className="graph-contract-card" key={workflow.workflow_id || workflow.id}>
                      <div className="runtime-workflow-row">
                        <div>
                          <strong>{workflow.name}</strong>
                          <span>
                            workflow_id: {workflow.workflow_id || workflow.id}
                            {workflow.knowledge_base_name ? ` · DB: ${workflow.knowledge_base_name}` : ''}
                          </span>
                        </div>
                        <StatusPill status={workflow.can_run ? 'ready' : workflow.index_status || 'not_indexed'} />
                      </div>

                      <div className="graph-io-grid">
                        <div>
                          <strong>单条输入</strong>
                          <span>{workflow.invoke?.method || 'POST'} {workflow.invoke?.url || `${baseUrl}/api/runtime/workflows/${workflow.workflow_id || '{workflow_id}'}/invoke`}</span>
                          <pre><code>{formatJson(workflow.invoke?.request || graphContract.input)}</code></pre>
                        </div>
                        <div>
                          <strong>单条输出</strong>
                          <span>answer 是最终答案，contexts 是本次 RAG 检索到的上下文。</span>
                          <pre><code>{formatJson(workflow.invoke?.response || graphContract.output)}</code></pre>
                        </div>
                        <div>
                          <strong>单条 curl</strong>
                          <pre><code>{workflow.invoke?.curl || examples.invoke || `curl -X POST ${baseUrl}/api/runtime/workflows/${workflow.workflow_id || 1}/invoke -H 'Content-Type: application/json' -d '{"question":"如何导入文档？"}'`}</code></pre>
                        </div>
                        <div>
                          <strong>批量 curl</strong>
                          <pre><code>{workflow.batch?.curl || examples.batch || `curl -X POST ${baseUrl}/api/runtime/workflows/${workflow.workflow_id || 1}/batch -H 'Content-Type: application/json' -d '{"questions":["如何导入文档？","如何运行评测？"]}'`}</code></pre>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="graph-contract-card">
                    <div className="hint-box">
                      <strong>暂无可调用 Graph</strong>
                      <span>需要先准备一个已索引 DB，并保存可从 question 执行到 Answer 的 RAG Graph。下面是固定调用格式，等有 workflow_id 后替换即可。</span>
                    </div>
                    <div className="graph-io-grid">
                      <div>
                        <strong>单条输入</strong>
                        <span>POST {baseUrl}/api/runtime/workflows/{'{workflow_id}'}/invoke</span>
                        <pre><code>{formatJson(graphContract.input)}</code></pre>
                      </div>
                      <div>
                        <strong>单条输出</strong>
                        <span>所有语言都按这个 JSON 结构读取结果。</span>
                        <pre><code>{formatJson(graphContract.output)}</code></pre>
                      </div>
                      <div>
                        <strong>批量输入</strong>
                        <span>POST {baseUrl}/api/runtime/workflows/{'{workflow_id}'}/batch</span>
                        <pre><code>{formatJson(graphContract.batch_input)}</code></pre>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          ) : (
            <Panel title="部署后会展示">
              <div className="hint-box">
                <strong>API 调用示例会在这里展开。</strong>
                <span>包括 workflow 列表、单条 invoke、批量 batch，以及当前可调用 Graph 的状态。</span>
              </div>
            </Panel>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="home-dashboard">
      <Panel title="常见工作顺序" className="home-main-panel">
        <ol className="workflow-steps">
          {workflowSteps.map((step, index) => (
            <li key={step.title}>
              <button
                onClick={() => {
                  if (step.action === 'deploy') {
                    setView('deploy');
                    return;
                  }
                  onNavigate(step.target, { returnToHome: true, label: step.title });
                }}
              >
                <span>{index + 1}</span>
                <strong>{step.title}</strong>
                <small>{step.body}</small>
              </button>
            </li>
          ))}
        </ol>

        <div className="runtime-note">
          <PlugZap size={18} />
          <span>Runtime API：contract {capabilities?.output?.contract_version || 'v1'}，当前可调用 Workflow {callableWorkflows.length} 个。</span>
        </div>
      </Panel>

      <Panel title="运行概览" className="home-overview-panel">
        <div className="compact-overview">
          <div>
            <span>知识库 DB</span>
            <strong>{remote.knowledgeBases.length}</strong>
          </div>
          <div>
            <span>Workflow</span>
            <strong>{remote.workflows.length}</strong>
          </div>
          <div>
            <span>可调用 Workflow</span>
            <strong>{callableWorkflows.length}</strong>
          </div>
          <div>
            <span>评测记录</span>
            <strong>{remote.evalRuns.length}</strong>
          </div>
        </div>
      </Panel>

    </div>
  );
}
