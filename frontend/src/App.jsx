import { useEffect, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Database,
  GitBranch,
  Home,
  ListChecks,
  Loader2,
  RefreshCw,
  SlidersHorizontal,
  Wifi,
  WifiOff,
  X,
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
  { id: 'workflow', label: 'Workflow', subtitle: 'RAG Graph 编辑与调试', icon: GitBranch },
  { id: 'evaluation', label: '评测', subtitle: '无参考答案 RAGAS 运行', icon: ListChecks },
  { id: 'config', label: '配置', subtitle: 'Provider、默认模型和高级参数', icon: SlidersHorizontal },
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
  const [configIntent, setConfigIntent] = useState(null);
  const [returnContext, setReturnContext] = useState(null);
  const [backendConnected, setBackendConnected] = useState(null);
  const [taskState, setTaskState] = useState({ kind: 'idle', message: '' });
  const active = tabs.find((tab) => tab.id === activeTab) || tabs[0];

  useEffect(() => {
    remote.refresh()
      .then(() => setBackendConnected(true))
      .catch((error) => {
        setBackendConnected(false);
        setTaskState({ kind: 'error', message: error.message });
      });
  }, []);

  async function runTask(label, task) {
    flushSync(() => {
      setTaskState({ kind: 'running', message: label });
    });
    await waitForPaint();
    try {
      const result = await task();
      await remote.refresh();
      setBackendConnected(true);
      setTaskState({ kind: 'success', message: doneLabel(label) });
      return result;
    } catch (error) {
      if (isConnectionError(error)) {
        setBackendConnected(false);
      }
      setTaskState({ kind: 'error', message: error.message });
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
    if (tabId === 'config') {
      setConfigIntent(options.intent ? { ...options.intent, key: Date.now() } : null);
    } else if (tabId !== 'data') {
      setConfigIntent(null);
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
        <div className={backendConnected === false ? 'service-status offline' : 'service-status online'}>
          {backendConnected === false ? <WifiOff size={15} /> : <Wifi size={15} />}
          <span>{backendConnected === false ? '连接失败' : '后端已连接'}</span>
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
        <TaskBanner state={taskState} onClose={() => setTaskState({ kind: 'idle', message: '' })} />

        {activeTab !== 'home' && activeTab !== 'data' && returnContext ? (
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
        {activeTab === 'data' ? (
          <DataPage
            remote={remote}
            runTask={runTask}
            initialSection={dataIntent.section}
            navigationKey={dataIntent.key}
            onNavigate={navigate}
          />
        ) : null}
        {activeTab === 'workflow' ? <WorkflowPage remote={remote} runTask={runTask} /> : null}
        {activeTab === 'evaluation' ? <EvaluationPage remote={remote} runTask={runTask} onNavigate={navigate} /> : null}
        {activeTab === 'config' ? <ConfigPage runTask={runTask} intent={configIntent} /> : null}
      </main>
    </div>
  );
}

function waitForPaint() {
  if (typeof window === 'undefined' || !window.requestAnimationFrame) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

function doneLabel(label) {
  if (label.endsWith('中')) {
    return `${label.slice(0, -1)}完成`;
  }
  return `${label} 完成`;
}

function isConnectionError(error) {
  return /failed to fetch|networkerror|load failed/i.test(error?.message || '');
}

function TaskBanner({ state, onClose }) {
  if (!state || state.kind === 'idle') {
    return null;
  }
  const Icon = state.kind === 'running' ? Loader2 : state.kind === 'success' ? CheckCircle2 : AlertCircle;
  return (
    <div className={`task-banner ${state.kind}`}>
      <Icon className={state.kind === 'running' ? 'spin' : ''} size={17} />
      <span>{state.message}</span>
      {state.kind !== 'running' ? (
        <button type="button" onClick={onClose} aria-label="关闭状态">
          <X size={14} />
        </button>
      ) : null}
    </div>
  );
}
