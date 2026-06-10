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
      <Panel title="产品导航" className="home-main-panel">
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
