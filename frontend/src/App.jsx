import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  Bot,
  Database,
  GitBranch,
  Home,
  ListChecks,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import { api } from './api.js';
import { Button } from './components/ui.jsx';
import { ConfigPage } from './pages/ConfigPage.jsx';
import { DataPage } from './pages/DataPage.jsx';
import { EvaluationPage } from './pages/EvaluationPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { WorkflowPage } from './pages/WorkflowPage.jsx';

const tabs = [
  { id: 'home', label: '导航', subtitle: '产品入口与 Runtime API', icon: Home },
  { id: 'data', label: '数据', subtitle: '知识库与评测集', icon: Database },
  { id: 'workflow', label: 'Workflow', subtitle: 'Dify-like RAG pipeline 画布', icon: GitBranch },
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
  const [dataIntent, setDataIntent] = useState({ section: 'landing', key: 0 });
  const [returnContext, setReturnContext] = useState(null);
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

  function navigate(tabId, options = {}) {
    const tab = tabs.find((item) => item.id === tabId) || tabs[0];
    if (options.returnToHome) {
      setReturnContext({
        label: options.label || tab.label,
      });
    } else {
      setReturnContext(null);
    }
    if (tabId === 'queries') {
      setDataIntent({ section: 'querySets', key: Date.now() });
      setActiveTab('data');
      return;
    }
    if (tabId === 'data') {
      setDataIntent({ section: 'landing', key: Date.now() });
    }
    setActiveTab(tabId);
  }

  function returnToHome() {
    setReturnContext(null);
    setActiveTab('home');
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
                onClick={() => navigate(tab.id)}
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

        {activeTab !== 'home' && returnContext ? (
          <div className="editor-header action-return-bar">
            <Button icon={ArrowLeft} variant="secondary" onClick={returnToHome}>
              返回导航
            </Button>
            <div>
              <strong>{returnContext.label}</strong>
              <span>从常见工作顺序进入，完成后可以回到导航继续下一步。</span>
            </div>
          </div>
        ) : null}

        {activeTab === 'home' ? <HomePage remote={remote} onNavigate={navigate} runTask={runTask} /> : null}
        {activeTab === 'data' ? <DataPage remote={remote} runTask={runTask} initialSection={dataIntent.section} navigationKey={dataIntent.key} /> : null}
        {activeTab === 'workflow' ? <WorkflowPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'evaluation' ? <EvaluationPage remote={remote} runTask={runTask} onNavigate={navigate} /> : null}
        {activeTab === 'config' ? <ConfigPage runTask={runTask} /> : null}
      </main>
    </div>
  );
}
