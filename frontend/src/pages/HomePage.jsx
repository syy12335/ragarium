import { useEffect, useMemo, useState } from 'react';
import {
  Database,
  GitBranch,
  ListChecks,
  PlugZap,
  SlidersHorizontal,
  WandSparkles,
} from 'lucide-react';
import { API_BASE, api } from '../api.js';
import { Panel, StatusPill } from '../components/ui.jsx';

const moduleCards = [
  {
    id: 'data',
    title: '数据',
    body: '管理知识库与 query-only 评测集',
    icon: Database,
  },
  {
    id: 'workflow',
    title: 'Workflow',
    body: '三个可执行模板：离线 DB、RAG、评测',
    icon: GitBranch,
  },
  {
    id: 'queries',
    title: 'Query 生成',
    body: '快捷进入数据页的评测集入口',
    icon: WandSparkles,
  },
  {
    id: 'evaluation',
    title: '评测',
    body: '运行无参考答案 RAGAS 评测',
    icon: ListChecks,
  },
  {
    id: 'config',
    title: '配置',
    body: '管理 Provider、默认模型和 Chunk 参数',
    icon: SlidersHorizontal,
  },
];

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
    title: '评测或外部调用',
    body: '在评测里跑 RAGAS；当 RAG Graph 可调用后，也可以用 Runtime API 从其他语言接入。',
    target: 'evaluation',
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

        <div className="section-subtitle">
          <strong>模块入口</strong>
          <span>也可以直接进入某个模块处理当前任务。</span>
        </div>
        <div className="launch-grid">
          {moduleCards.map((card) => {
            const Icon = card.icon;
            return (
              <button className="launch-card" key={card.id} onClick={() => onNavigate(card.id)}>
                <Icon size={20} />
                <span>
                  <strong>{card.title}</strong>
                  <small>{card.body}</small>
                </span>
              </button>
            );
          })}
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

      <Panel title="Runtime API" className="home-runtime-panel">
        <div className="runtime-compact-card">
          <PlugZap size={20} />
          <div>
            <strong>外部 HTTP 调用</strong>
            <span>{API_BASE} · contract {capabilities?.output?.contract_version || 'v1'}</span>
          </div>
          <StatusPill status={capabilities?.output?.capabilities?.workflow_invoke ? 'ready' : 'failed'} />
        </div>
      </Panel>
    </div>
  );
}
