import { useEffect, useMemo, useState } from 'react';
import {
  PlugZap,
} from 'lucide-react';
import { api } from '../api.js';
import { Panel } from '../components/ui.jsx';

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
    body: '当 RAG Graph 可调用后，用 Runtime API 从其他语言通过 HTTP 接入 question -> answer。',
    target: 'workflow',
    icon: PlugZap,
  },
];

export function HomePage({ remote, onNavigate }) {
  const [capabilities, setCapabilities] = useState(null);

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

  return (
    <div className="home-dashboard">
      <Panel title="常见工作顺序" className="home-main-panel">
        <ol className="workflow-steps">
          {workflowSteps.map((step, index) => (
            <li key={step.title}>
              <button onClick={() => onNavigate(step.target)}>
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
