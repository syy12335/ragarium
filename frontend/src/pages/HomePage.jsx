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
import { Button, EmptyState, Panel, StatusPill } from '../components/ui.jsx';

const moduleCards = [
  {
    id: 'data',
    title: '数据',
    body: '管理 name-db、来源、Chunk 和索引状态',
    icon: Database,
  },
  {
    id: 'workflow',
    title: 'Workflow',
    body: '配置 RAG pipeline 画布并运行问答',
    icon: GitBranch,
  },
  {
    id: 'queries',
    title: 'Query 生成',
    body: '基于示例 Query 生成评测集',
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
        const sourceNode = workflow.graph.nodes.find((node) => node.type === 'source');
        const kbId = sourceNode?.data?.knowledgeBaseId;
        const kb = remote.knowledgeBases.find((item) => String(item.id) === String(kbId));
        return kb?.index_status === 'ready';
      } catch {
        return false;
      }
    }),
    [remote.workflows, remote.knowledgeBases],
  );

  const curlExample =
    capabilities?.output?.examples?.curl ||
    `curl -X POST ${API_BASE}/api/runtime/workflows/1/invoke -H 'Content-Type: application/json' -d '{"question":"如何导入文档？"}'`;

  return (
    <div className="home-layout">
      <Panel title="产品导航">
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

      <Panel title="运行概览">
        <div className="db-summary">
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

      <Panel
        title="Runtime API"
        className="runtime-panel"
        actions={
          <Button icon={PlugZap} variant="secondary" onClick={() => onNavigate('workflow')}>
            进入 Workflow
          </Button>
        }
      >
        <div className="runtime-card">
          <div>
            <span>服务地址</span>
            <strong>{API_BASE}</strong>
          </div>
          <div>
            <span>Contract</span>
            <strong>{capabilities?.output?.contract_version || 'v1'}</strong>
          </div>
          <div>
            <span>Workflow 调用</span>
            <StatusPill status={capabilities?.output?.capabilities?.workflow_invoke ? 'ready' : 'failed'} />
          </div>
        </div>

        <div className="endpoint-list">
          <code>GET /api/runtime/capabilities</code>
          <code>GET /api/runtime/workflows</code>
          <code>POST /api/runtime/workflows/&#123;workflow_id&#125;/invoke</code>
          <code>POST /api/runtime/workflows/&#123;workflow_id&#125;/batch</code>
        </div>

        <pre>{curlExample}</pre>
      </Panel>

      <Panel title="可调用 Workflow">
        {callableWorkflows.length ? (
          <div className="card-list">
            {callableWorkflows.slice(0, 6).map((workflow) => (
              <article className="card-item" key={workflow.id}>
                <strong>{workflow.name}</strong>
                <span>Workflow #{workflow.id}</span>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="暂无可调用 Workflow" body="准备索引后，Workflow 会出现在这里。" />
        )}
      </Panel>
    </div>
  );
}
