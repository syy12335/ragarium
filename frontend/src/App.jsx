import { useEffect, useState } from 'react';
import {
  Bot,
  Database,
  GitBranch,
  Home,
  ListChecks,
  RefreshCw,
  SlidersHorizontal,
  WandSparkles,
} from 'lucide-react';
import { api } from './api.js';
import { Button } from './components/ui.jsx';
import { ConfigPage } from './pages/ConfigPage.jsx';
import { DataPage } from './pages/DataPage.jsx';
import { EvaluationPage } from './pages/EvaluationPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { QueryPage } from './pages/QueryPage.jsx';
import { WorkflowPage } from './pages/WorkflowPage.jsx';

const tabs = [
  { id: 'home', label: '导航', subtitle: '产品入口与 Runtime API', icon: Home },
  { id: 'data', label: '数据', subtitle: 'name-db 导入、Chunk 和索引状态', icon: Database },
  { id: 'workflow', label: 'Workflow', subtitle: 'Dify-like RAG pipeline 画布', icon: GitBranch },
  { id: 'queries', label: 'Query 生成', subtitle: '生成 query-only 评测集', icon: WandSparkles },
  { id: 'evaluation', label: '评测', subtitle: '无参考答案 RAGAS 运行', icon: ListChecks },
  { id: 'config', label: '配置', subtitle: 'Provider、模型角色和默认 Chunk 参数', icon: SlidersHorizontal },
];

function useRemoteState() {
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [querySets, setQuerySets] = useState([]);
  const [evalRuns, setEvalRuns] = useState([]);

  async function refresh() {
    const [kb, wf, qs, er] = await Promise.all([
      api.listKnowledgeBases(),
      api.listWorkflows(),
      api.listQuerySets(),
      api.listEvalRuns(),
    ]);
    setKnowledgeBases(kb);
    setWorkflows(wf);
    setQuerySets(qs);
    setEvalRuns(er);
  }

  return {
    knowledgeBases,
    workflows,
    querySets,
    evalRuns,
    refresh,
  };
}

export default function App() {
  const remote = useRemoteState();
  const [activeTab, setActiveTab] = useState('home');
  const [status, setStatus] = useState('就绪');
  const active = tabs.find((tab) => tab.id === activeTab) || tabs[0];

  useEffect(() => {
    remote.refresh().catch((error) => setStatus(error.message));
  }, []);

  async function runTask(label, task) {
    setStatus(label);
    try {
      const result = await task();
      setStatus('完成');
      await remote.refresh();
      return result;
    } catch (error) {
      setStatus(error.message);
      return null;
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Bot size={22} />
          <div>
            <strong>RAG Eval</strong>
            <span>本地产品控制台</span>
          </div>
        </div>
        <nav>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                className={activeTab === tab.id ? 'nav-item active' : 'nav-item'}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={18} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="status-bar">
          <span>状态</span>
          <strong>{status}</strong>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{active.label}</h1>
            <p>{active.subtitle}</p>
          </div>
          <Button icon={RefreshCw} variant="secondary" onClick={() => runTask('刷新中', remote.refresh)}>
            刷新
          </Button>
        </header>

        {activeTab === 'home' ? <HomePage remote={remote} onNavigate={setActiveTab} /> : null}
        {activeTab === 'data' ? <DataPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'workflow' ? <WorkflowPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'queries' ? <QueryPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'evaluation' ? <EvaluationPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'config' ? <ConfigPage runTask={runTask} /> : null}
      </main>
    </div>
  );
}
