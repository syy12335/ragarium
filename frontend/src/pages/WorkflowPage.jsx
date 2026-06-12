import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
} from '@xyflow/react';
import {
  ArrowLeft,
  ListChecks,
  Play,
  Plus,
  Save,
  Settings,
  Trash2,
  WandSparkles,
} from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, Panel, StatusPill } from '../components/ui.jsx';
import { buildNode, nodeCatalog, nodeMeta } from '../workflowNodes.js';

const DEFAULT_TEMPLATE_ID = 'blank';

function FlowNode({ data, type, selected }) {
  const meta = nodeMeta[type] || {};
  const runStatus = data?.runStatus || '';
  return (
    <div className={`flow-node flow-node-${type} ${selected ? 'selected' : ''} ${runStatus ? `run-${runStatus}` : ''}`}>
      {type !== 'start' ? <Handle type="target" position={Position.Left} /> : null}
      {runStatus === 'running' ? <span className="node-running-dot" /> : null}
      <strong>{data?.label || meta.label || type}</strong>
      <small>{meta.caption}</small>
      {type !== 'end' ? <Handle type="source" position={Position.Right} /> : null}
    </div>
  );
}

const nodeTypes = Object.fromEntries(nodeCatalog.map((item) => [item.type, FlowNode]));

function graphNameForTemplate(templateId, templates) {
  const template = templates.find((item) => item.id === templateId);
  if (!template || template.id === 'blank') {
    return '未命名 Graph';
  }
  return `${template.name} Graph`;
}

function cloneGraph(graph) {
  return {
    templateId: graph.templateId || DEFAULT_TEMPLATE_ID,
    nodes: graph.nodes || [],
    edges: graph.edges || [],
  };
}

export function WorkflowPage({ remote, runTask }) {
  const [templates, setTemplates] = useState([]);
  const [viewMode, setViewMode] = useState('landing');
  const [debugBackView, setDebugBackView] = useState('debugList');
  const [starterTemplateId, setStarterTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [workflowName, setWorkflowName] = useState('未命名 Graph');
  const [workflowId, setWorkflowId] = useState('');
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [flowInstance, setFlowInstance] = useState(null);
  const [startInputs, setStartInputs] = useState({});
  const [validationResult, setValidationResult] = useState(null);
  const [queryNodeResult, setQueryNodeResult] = useState(null);
  const [testRun, setTestRun] = useState(null);
  const [isTestRunning, setIsTestRunning] = useState(false);
  const testPollRef = useRef(null);

  useEffect(() => {
    async function loadInitial() {
      const items = await api.listWorkflowTemplates();
      setTemplates(items);
    }
    loadInitial().catch(() => setTemplates([]));
  }, []);

  const graph = useMemo(
    () => ({ templateId: starterTemplateId, nodes, edges }),
    [starterTemplateId, nodes, edges],
  );
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const startNode = nodes.find((node) => node.type === 'start');
  const startFields = Array.isArray(startNode?.data?.fields) ? startNode.data.fields : [];
  const nodeRunStatus = useMemo(() => {
    const statuses = {};
    (testRun?.trace || []).forEach((item) => {
      if (item.node_id) {
        statuses[item.node_id] = item.status || 'pending';
      }
    });
    return statuses;
  }, [testRun]);
  const flowNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...(node.data || {}),
          runStatus: nodeRunStatus[node.id] || (testRun ? 'pending' : ''),
        },
      })),
    [nodes, nodeRunStatus, testRun],
  );

  function stopTestPolling() {
    if (testPollRef.current) {
      window.clearTimeout(testPollRef.current);
      testPollRef.current = null;
    }
  }

  function clearRunState() {
    stopTestPolling();
    setValidationResult(null);
    setQueryNodeResult(null);
    setTestRun(null);
    setIsTestRunning(false);
  }

  useEffect(() => () => stopTestPolling(), []);

  async function createNewGraph(templateId = DEFAULT_TEMPLATE_ID, knownTemplates = templates) {
    const payload = await api.getDefaultWorkflow(templateId);
    const nextGraph = cloneGraph(payload.graph);
    setWorkflowId('');
    setStarterTemplateId(nextGraph.templateId || templateId);
    setWorkflowName(graphNameForTemplate(templateId, knownTemplates));
    setNodes(nextGraph.nodes);
    setEdges(nextGraph.edges);
    setSelectedNodeId(nextGraph.nodes[0]?.id || '');
    setStartInputs({});
    clearRunState();
    setViewMode('editor');
  }

  async function loadWorkflow(id, targetView = 'editor', returnView = 'landing') {
    if (!id) {
      return;
    }
    const workflow = remote.workflows.find((item) => String(item.id) === String(id));
    if (!workflow) {
      return;
    }
    const nextGraph = cloneGraph(workflow.graph);
    setWorkflowId(String(workflow.id));
    setStarterTemplateId(nextGraph.templateId || 'custom');
    setWorkflowName(workflow.name);
    setNodes(nextGraph.nodes);
    setEdges(nextGraph.edges);
    setSelectedNodeId(nextGraph.nodes[0]?.id || '');
    setStartInputs({});
    clearRunState();
    setViewMode(targetView);
    if (targetView === 'debug') {
      setDebugBackView(returnView);
      const result = await api.validateWorkflow({ name: workflow.name || '未命名 Graph', graph: nextGraph });
      setValidationResult(result);
    }
    return { workflow, returnView };
  }

  async function debugCurrentWorkflow() {
    const saved = await saveCurrentWorkflow();
    clearRunState();
    const result = await api.validateWorkflow({ name: saved.name || workflowName || '未命名 Graph', graph: saved.graph || graph });
    setValidationResult(result);
    setDebugBackView('editor');
    setViewMode('debug');
    return saved;
  }

  function addNode(type, position = null) {
    if (['start', 'end'].includes(type)) {
      const existing = nodes.find((node) => node.type === type);
      if (existing) {
        setSelectedNodeId(existing.id);
        return;
      }
    }
    const next = buildNode(type, nodes.length, position);
    setNodes((current) => [...current, next]);
    setSelectedNodeId(next.id);
    clearRunState();
  }

  function deleteSelectedNode() {
    if (!selectedNodeId) {
      return;
    }
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId));
    setEdges((current) => current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId));
    setSelectedNodeId('');
    clearRunState();
  }

  function updateSelectedNodeData(key, value) {
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedNodeId
          ? { ...node, data: { ...(node.data || {}), [key]: value } }
          : node,
      ),
    );
    clearRunState();
  }

  function onDragStart(event, type) {
    event.dataTransfer.setData('application/rag-node-type', type);
    event.dataTransfer.effectAllowed = 'move';
  }

  function onDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }

  function onDrop(event) {
    event.preventDefault();
    const type = event.dataTransfer.getData('application/rag-node-type');
    if (!type) {
      return;
    }
    const position = flowInstance?.screenToFlowPosition
      ? flowInstance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
      : { x: event.clientX - 320, y: event.clientY - 160 };
    addNode(type, position);
  }

  function handleNodesChange(changes) {
    if (changes.some((change) => !['select', 'dimensions'].includes(change.type))) {
      clearRunState();
    }
    setNodes((current) => applyNodeChanges(changes, current));
  }

  function handleEdgesChange(changes) {
    if (changes.some((change) => change.type !== 'select')) {
      clearRunState();
    }
    setEdges((current) => applyEdgeChanges(changes, current));
  }

  async function saveCurrentWorkflow() {
    const saved = await api.saveWorkflow({
      id: workflowId || undefined,
      name: workflowName.trim() || '未命名 Graph',
      graph,
    });
    setWorkflowId(String(saved.id));
    await remote.refresh();
    return saved;
  }

  async function validateCurrentWorkflow() {
    const result = await api.validateWorkflow({ name: workflowName || '未命名 Graph', graph });
    setValidationResult(result);
    return result;
  }

  async function pollWorkflowTestRun(runId) {
    const snapshot = await api.getWorkflowTestRun(runId);
    setTestRun(snapshot);
    if (snapshot.status === 'running') {
      testPollRef.current = window.setTimeout(() => {
        pollWorkflowTestRun(runId).catch((error) => {
          setIsTestRunning(false);
          setTestRun((current) => ({
            ...(current || { run_id: runId, trace: [] }),
            status: 'failed',
            error: error.message,
          }));
        });
      }, 500);
    } else {
      setIsTestRunning(false);
      await remote.refresh();
    }
    return snapshot;
  }

  async function startGraphTest() {
    stopTestPolling();
    setQueryNodeResult(null);
    setValidationResult(null);
    setIsTestRunning(true);
    setTestRun({
      status: 'running',
      trace: nodes.map((node) => ({ node_id: node.id, type: node.type, status: 'pending' })),
      outputs: null,
      error: null,
    });
    try {
      const saved = await saveCurrentWorkflow();
      const initial = await api.startWorkflowTestRun(saved.id, { inputs: startInputs });
      setTestRun(initial);
      if (initial.status === 'running') {
        testPollRef.current = window.setTimeout(() => {
          pollWorkflowTestRun(initial.run_id).catch((error) => {
            setIsTestRunning(false);
            setTestRun((current) => ({
              ...(current || initial),
              status: 'failed',
              error: error.message,
            }));
          });
        }, 500);
      } else {
        setIsTestRunning(false);
        await remote.refresh();
      }
      return initial;
    } catch (error) {
      setIsTestRunning(false);
      setTestRun((current) => ({
        ...(current || { trace: [] }),
        status: 'failed',
        error: error.message,
      }));
      throw error;
    }
  }

  async function runSelectedNode() {
    if (!selectedNode || selectedNode.type !== 'query_generate') {
      throw new Error('第一版只支持运行 Query Generate 节点');
    }
    const saved = await saveCurrentWorkflow();
    const result = await api.runWorkflowNode(saved.id, selectedNode.id);
    setQueryNodeResult(result);
    await remote.refresh();
    return result;
  }

  function updateStartInput(name, value) {
    setStartInputs((current) => ({ ...current, [name]: value }));
  }

  function returnToLanding() {
    setViewMode('landing');
    setSelectedNodeId('');
    clearRunState();
  }

  if (viewMode === 'landing') {
    return (
      <WorkflowLanding
        onChooseLoad={() => setViewMode('load')}
        onChooseNew={() => setViewMode('new')}
        onChooseDebug={() => setViewMode('debugList')}
      />
    );
  }

  if (viewMode === 'load') {
    return (
      <WorkflowLoadEntry
        workflows={remote.workflows}
        onBack={() => setViewMode('landing')}
        onEdit={(id) => loadWorkflow(id, 'editor')}
      />
    );
  }

  if (viewMode === 'debugList') {
    return (
      <WorkflowDebugEntry
        workflows={remote.workflows}
        onBack={() => setViewMode('landing')}
        onDebug={(id) => runTask('打开 Graph 调试', () => loadWorkflow(id, 'debug', 'debugList'))}
      />
    );
  }

  if (viewMode === 'new') {
    return (
      <WorkflowNewEntry
        templates={templates}
        onBack={() => setViewMode('landing')}
        onCreate={(templateId) => runTask('新建 Graph 中', () => createNewGraph(templateId))}
      />
    );
  }

  if (viewMode === 'debug') {
    return (
      <WorkflowDebugPage
        workflowName={workflowName}
        workflowId={workflowId}
        nodes={nodes}
        fields={startFields}
        values={startInputs}
        onChange={updateStartInput}
        testRun={testRun}
        isRunning={isTestRunning}
        onRun={startGraphTest}
        selectedNodeId={selectedNodeId}
        onSelectNode={setSelectedNodeId}
        validationResult={validationResult}
        backLabel={debugBackView === 'editor' ? '返回编辑器' : '返回调试列表'}
        onBack={() => {
          clearRunState();
          setViewMode(debugBackView);
        }}
      />
    );
  }

  return (
    <div className="workflow-editor-shell">
      <div className="editor-header">
        <Button icon={ArrowLeft} variant="secondary" onClick={returnToLanding}>
          返回
        </Button>
        <div>
          <strong>{workflowName || '未命名 Graph'}</strong>
          <span>{workflowId ? `Graph #${workflowId}` : '未保存草稿'}</span>
        </div>
        <Button icon={Play} onClick={() => runTask('保存并打开调试', debugCurrentWorkflow)}>
          调试
        </Button>
      </div>

      <div className="workflow-layout graph-editor-layout">
        <Panel title="节点库" className="graph-sidebar">
        <div className="node-list">
          {nodeCatalog.map((item) => (
            <button
              key={item.type}
              className="node-card"
              draggable
              onDragStart={(event) => onDragStart(event, item.type)}
              onClick={() => addNode(item.type)}
              title="点击添加，或拖拽到画布"
            >
              <Plus size={15} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.caption}</small>
              </span>
            </button>
          ))}
        </div>
        </Panel>

        <div className="canvas-panel" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={flowNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onInit={setFlowInstance}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={(params) => {
              clearRunState();
              setEdges((current) =>
                addEdge(
                  {
                    ...params,
                    id: `${params.source}-${params.target}-${Date.now()}`,
                    animated: false,
                  },
                  current,
                ),
              );
            }}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId('')}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <Panel title="参数配置" className="inspector-panel" actions={<Settings size={17} />}>
          <Field label="Graph 名称" help="用于保存和加载这个工作流；Runtime API 和评测页也会显示这个名字。">
            <input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
          </Field>
          <div className="button-row">
            <Button icon={ListChecks} variant="secondary" onClick={() => runTask('校验 Graph 中', validateCurrentWorkflow)}>
              校验
            </Button>
            <Button icon={Save} onClick={() => runTask('保存 Graph 中', saveCurrentWorkflow)}>
              保存
            </Button>
          </div>

          {validationResult ? (
            <div className={validationResult.ok ? 'hint-box' : 'hint-box error-box'}>
              <strong>{validationResult.ok ? '可执行' : '暂不可执行'}</strong>
              <span>{validationResult.ok ? `${validationResult.node_count} 个节点已通过运行前校验` : validationResult.error}</span>
            </div>
          ) : null}

          <NodeInspector
            node={selectedNode}
            remote={remote}
            onChange={updateSelectedNodeData}
            onDelete={deleteSelectedNode}
            onRunNode={() => runTask('运行 Query Generate 节点中', runSelectedNode)}
          />

          {queryNodeResult ? <QuerySetResult result={queryNodeResult.query_set} title="节点生成结果" /> : null}
        </Panel>
      </div>
    </div>
  );
}

function WorkflowLanding({ onChooseLoad, onChooseNew, onChooseDebug }) {
  return (
    <div className="workflow-home-grid">
      <section className="workflow-home-card">
        <div className="workflow-home-card-head">
          <ListChecks size={42} />
          <span>
            <strong>编辑 Graph</strong>
            <small>创建或加载 Graph，在画布里调整节点、连线和参数。</small>
          </span>
        </div>
        <div className="workflow-home-actions">
          <button className="workflow-home-action" onClick={onChooseLoad}>
            <ListChecks size={22} />
            <span>
              <strong>加载 Graph</strong>
              <small>打开已保存 Graph 继续编辑。</small>
            </span>
          </button>
          <button className="workflow-home-action" onClick={onChooseNew}>
            <Plus size={22} />
            <span>
              <strong>新建 Graph</strong>
              <small>从空白或模板开始创建。</small>
            </span>
          </button>
        </div>
      </section>
      <button className="workflow-home-card workflow-home-card-button" onClick={onChooseDebug}>
        <Play size={42} />
        <span>
          <strong>调试 Graph</strong>
          <small>选择已保存 Graph，端到端测试输入、输出和节点流转。</small>
        </span>
      </button>
    </div>
  );
}

function WorkflowLoadEntry({ workflows, onBack, onEdit }) {
  return (
    <div className="workflow-entry-page">
      <div className="editor-header">
        <Button icon={ArrowLeft} variant="secondary" onClick={onBack}>
          返回
        </Button>
        <div>
          <strong>加载 Graph</strong>
          <span>选择一个已保存 graph 进入画布编辑。</span>
        </div>
      </div>
      <Panel title="加载 Graph">
        {workflows.length ? (
          <div className="graph-entry-list">
            {workflows.map((workflow) => (
              <button className="graph-entry-card" key={workflow.id} onClick={() => onEdit(String(workflow.id))}>
                <span>
                  <strong>{workflow.name}</strong>
                  <small>Graph #{workflow.id} · {workflow.executable ? '可执行' : '草稿'}</small>
                </span>
                {workflow.runtime_capable ? <StatusPill status="ready" /> : null}
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title="暂无 Graph" body="返回后选择新建 Graph。" />
        )}
      </Panel>
    </div>
  );
}

function WorkflowDebugEntry({ workflows, onBack, onDebug }) {
  return (
    <div className="workflow-entry-page">
      <div className="editor-header">
        <Button icon={ArrowLeft} variant="secondary" onClick={onBack}>
          返回
        </Button>
        <div>
          <strong>调试 Graph</strong>
          <span>选择一个已保存 graph，进入端到端测试。</span>
        </div>
      </div>
      <Panel title="调试 Graph">
        {workflows.length ? (
          <div className="graph-entry-list">
            {workflows.map((workflow) => (
              <button className="graph-entry-card" key={workflow.id} onClick={() => onDebug(String(workflow.id))}>
                <span>
                  <strong>{workflow.name}</strong>
                  <small>Graph #{workflow.id} · {workflow.executable ? '可执行' : '草稿'}</small>
                </span>
                {workflow.executable ? <StatusPill status="ready" /> : <StatusPill status="failed" />}
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title="暂无 Graph" body="返回后先新建或保存一个 Graph。" />
        )}
      </Panel>
    </div>
  );
}

function WorkflowNewEntry({ templates, onBack, onCreate }) {
  return (
    <div className="workflow-entry-page">
      <div className="editor-header">
        <Button icon={ArrowLeft} variant="secondary" onClick={onBack}>
          返回
        </Button>
        <div>
          <strong>新建 Graph</strong>
          <span>选择空白或一个 starter 模板。</span>
        </div>
      </div>
      <Panel title="新建 Graph">
        {templates.length ? (
          <div className="graph-template-grid">
            {templates.map((template) => (
              <button className="graph-template-card" key={template.id} onClick={() => onCreate(template.id)}>
                <strong>{template.name}</strong>
                <span>{template.description}</span>
                <small>{template.node_types.join(' -> ')}</small>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState title="模板加载中" body="请稍后刷新，或先检查后端服务。" />
        )}
      </Panel>
    </div>
  );
}

function WorkflowDebugPage({
  workflowName,
  workflowId,
  nodes,
  fields,
  values,
  onChange,
  testRun,
  isRunning,
  onRun,
  selectedNodeId,
  onSelectNode,
  validationResult,
  backLabel,
  onBack,
}) {
  const canRun = validationResult?.ok !== false;
  return (
    <div className="workflow-debug-page">
      <div className="editor-header">
        <Button icon={ArrowLeft} variant="secondary" onClick={onBack}>
          {backLabel}
        </Button>
        <div>
          <strong>{workflowName || '未命名 Graph'}</strong>
          <span>{workflowId ? `Graph #${workflowId} · 端到端调试` : '端到端调试'}</span>
        </div>
      </div>
      {validationResult?.ok === false ? (
        <div className="hint-box error-box">
          <strong>当前 Graph 暂不可调试</strong>
          <span>{validationResult.error}</span>
        </div>
      ) : null}
      <GraphDebugWorkspace
        nodes={nodes}
        fields={fields}
        values={values}
        onChange={onChange}
        testRun={testRun}
        isRunning={isRunning}
        onRun={onRun}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
        disabled={!canRun}
      />
    </div>
  );
}

function StartInputForm({ fields, values, onChange }) {
  return (
    <div className="run-box">
      <h3>Start 输入</h3>
      {fields.length ? fields.map((field) => {
        const value = values[field.name] ?? field.default ?? '';
        if (field.type === 'boolean') {
          return (
            <label className="checkbox-row" key={field.name}>
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => onChange(field.name, event.target.checked)}
              />
              <span>{field.name}{field.required ? ' *' : ''}</span>
            </label>
          );
        }
        return (
          <Field key={field.name} label={`${field.name}${field.required ? ' *' : ''}`} help={`${field.type}；执行 Graph 时传入，后续节点可读取这个变量。`}>
            <input
              type={field.type === 'number' ? 'number' : 'text'}
              value={value}
              onChange={(event) => onChange(field.name, event.target.value)}
            />
          </Field>
        );
      }) : (
        <EmptyState title="无需输入" body="Start 节点没有定义输入参数。" />
      )}
    </div>
  );
}

function traceStatusLabel(status) {
  const labels = {
    pending: '等待中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
  };
  return labels[status] || status || '等待中';
}

function nodeLabel(type) {
  return nodeMeta[type]?.label || type || 'Unknown';
}

function formatContext(context) {
  if (typeof context === 'string') {
    return context;
  }
  if (context && typeof context === 'object') {
    return context.content || context.page_content || context.text || JSON.stringify(context);
  }
  return String(context ?? '');
}

function GraphDebugWorkspace({
  nodes,
  fields,
  values,
  onChange,
  testRun,
  isRunning,
  onRun,
  selectedNodeId,
  onSelectNode,
  disabled = false,
}) {
  const trace = testRun?.trace || [];
  const currentNode = testRun?.current_node_type ? nodeLabel(testRun.current_node_type) : '';
  const buttonLabel = isRunning ? '测试中' : testRun ? '重新测试' : '开始端到端测试';
  const missingRequired = fields.some((field) => field.required && !String(values[field.name] ?? field.default ?? '').trim());
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const selectedTrace = trace.find((item) => item.node_id === selectedNodeId);
  async function handleRun() {
    try {
      await onRun();
    } catch {
      // The panel state is updated by startGraphTest; keep the click quiet here.
    }
  }
  return (
    <div className="graph-debug-workspace">
      <section className="graph-debug-runner">
        <div>
          <h2>端到端调试</h2>
          <p>输入一次真实问题，跑完整个 Graph。运行时会显示当前节点；点击节点可查看该节点输入和输出。</p>
        </div>
        <StartInputForm fields={fields} values={values} onChange={onChange} />
        <Button
          icon={Play}
          className="full-width test-run-button"
          loading={isRunning}
          loadingLabel="测试中"
          disabled={disabled || missingRequired}
          onClick={handleRun}
        >
          {buttonLabel}
        </Button>
        {disabled ? <p className="test-run-hint">当前 Graph 未通过运行前校验，修复后再调试。</p> : null}
        {!disabled && missingRequired ? <p className="test-run-hint">先补齐 Start 节点必填输入，再开始测试。</p> : null}
        {testRun ? (
          <div className={`test-run-card test-run-${testRun.status || 'pending'}`}>
            <div className="test-run-head">
              <span>{isRunning && currentNode ? `当前：${currentNode}` : `状态：${traceStatusLabel(testRun.status)}`}</span>
              {testRun.run_id ? <small>Run {testRun.run_id.slice(0, 8)}</small> : null}
            </div>
            {testRun.error ? <div className="inline-error">{testRun.error}</div> : null}
            {trace.length ? (
              <div className="node-progress-list">
                {trace.map((item) => (
                  <button
                    type="button"
                    className={`node-progress-item status-${item.status || 'pending'} ${selectedNodeId === item.node_id ? 'selected' : ''}`}
                    key={item.node_id}
                    onClick={() => onSelectNode(item.node_id)}
                  >
                    <span className="progress-dot" />
                    <span>
                      <strong>{nodeLabel(item.type)}</strong>
                      <small>{item.duration_ms || item.duration_ms === 0 ? `${item.duration_ms}ms` : item.node_id}</small>
                    </span>
                    <em>{traceStatusLabel(item.status)}</em>
                  </button>
                ))}
              </div>
            ) : null}
            {testRun.outputs ? <TestRunOutput outputs={testRun.outputs} /> : null}
          </div>
        ) : null}
      </section>
      <NodeDebugPanel node={selectedNode} traceItem={selectedTrace} />
    </div>
  );
}

function NodeDebugPanel({ node, traceItem }) {
  if (!node) {
    return (
      <section className="node-debug-panel">
        <EmptyState title="选择一个节点" body="在左侧进度列表或画布中点击节点，查看这次运行的输入和输出。" />
      </section>
    );
  }
  const status = traceItem?.status || 'pending';
  return (
    <section className="node-debug-panel">
      <div className="node-debug-title">
        <span>
          <strong>{node.data?.label || nodeLabel(node.type)}</strong>
          <small>{node.id}</small>
        </span>
        <StatusPill status={status} />
      </div>
      {traceItem?.error ? <div className="inline-error">{traceItem.error}</div> : null}
      <DebugJsonBlock title="输入" value={traceItem?.input} emptyText="这次运行还没有进入该节点。" />
      <DebugJsonBlock title="输出" value={traceItem?.output} emptyText={status === 'running' ? '节点正在运行，输出尚未产生。' : '暂无输出。'} />
    </section>
  );
}

function DebugJsonBlock({ title, value, emptyText }) {
  const hasValue = value !== undefined && value !== null;
  return (
    <div className="debug-json-block">
      <h3>{title}</h3>
      {hasValue ? <pre>{JSON.stringify(value, null, 2)}</pre> : <p>{emptyText}</p>}
    </div>
  );
}

function TestRunOutput({ outputs }) {
  const contexts = outputs.contexts || [];
  const evalRun = outputs.eval_run;
  const querySet = outputs.query_set;
  const hasRagOutput = outputs.question || outputs.answer || contexts.length;
  return (
    <div className="test-output">
      <h3>测试结果</h3>
      {hasRagOutput ? (
        <>
          {outputs.question ? (
            <div className="answer-block">
              <span>Question</span>
              <strong>{outputs.question}</strong>
            </div>
          ) : null}
          <div className="answer-block">
            <span>Answer</span>
            <p>{outputs.answer || '暂无回答内容'}</p>
          </div>
          <div className="answer-block">
            <span>Contexts</span>
            {contexts.length ? (
              <ol className="context-list">
                {contexts.slice(0, 5).map((context, index) => (
                  <li key={`${index}-${formatContext(context).slice(0, 24)}`}>{formatContext(context)}</li>
                ))}
              </ol>
            ) : (
              <p>没有返回 contexts。</p>
            )}
          </div>
        </>
      ) : querySet || evalRun || outputs.answer_count ? (
        <div className="result-summary">
          {querySet ? (
            <div>
              <span>Query Set</span>
              <strong>#{querySet.id}</strong>
            </div>
          ) : null}
          {outputs.answer_count ? (
            <div>
              <span>Answers</span>
              <strong>{outputs.answer_count}</strong>
            </div>
          ) : null}
          {evalRun ? (
            <div>
              <span>Eval Run</span>
              <strong>#{evalRun.id}</strong>
            </div>
          ) : null}
        </div>
      ) : (
        <pre>{JSON.stringify(outputs, null, 2)}</pre>
      )}
      {evalRun?.metrics && Object.keys(evalRun.metrics).length ? (
        <pre>{JSON.stringify(evalRun.metrics, null, 2)}</pre>
      ) : null}
    </div>
  );
}

function QuerySetResult({ result, title }) {
  if (!result) {
    return null;
  }
  return (
    <div className="mini-result query-result">
      <span>{title} #{result.id}</span>
      <strong>{result.name}</strong>
      <small>{result.queries?.length || 0} 个 queries</small>
      <ol className="query-list">
        {(result.queries || []).slice(0, 5).map((query) => <li key={query}>{query}</li>)}
      </ol>
    </div>
  );
}

function ExecutionResult({ result }) {
  const outputs = result.outputs || {};
  const querySet = outputs.query_set;
  const evalRun = outputs.eval_run;
  return (
    <div className="result">
      <h3>执行结果</h3>
      {querySet || evalRun || outputs.answer_count ? (
        <div className="result-summary">
          {querySet ? (
            <div>
              <span>Query Set</span>
              <strong>#{querySet.id}</strong>
            </div>
          ) : null}
          {outputs.answer_count ? (
            <div>
              <span>Answers</span>
              <strong>{outputs.answer_count}</strong>
            </div>
          ) : null}
          {evalRun ? (
            <div>
              <span>Eval Run</span>
              <strong>#{evalRun.id}</strong>
            </div>
          ) : null}
        </div>
      ) : null}
      {evalRun?.metrics && Object.keys(evalRun.metrics).length ? (
        <pre>{JSON.stringify(evalRun.metrics, null, 2)}</pre>
      ) : (
        <pre>{JSON.stringify(outputs, null, 2)}</pre>
      )}
      <h3>Trace</h3>
      <div className="trace-list">
        {(result.trace || []).map((item) => (
          <div className="trace-item" key={item.node_id}>
            <strong>{item.type}</strong>
            <StatusPill status={item.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

function NodeInspector({ node, remote, onChange, onDelete, onRunNode }) {
  if (!node) {
    return <EmptyState title="请选择节点" body="点击画布中的节点即可配置参数。" />;
  }

  const data = node.data || {};
  const numberValue = (key, fallback) => Number(data[key] ?? fallback);
  const examplesValue = Array.isArray(data.examples) ? data.examples.join('\n') : (data.examples || '');

  return (
    <div className="node-inspector">
      <div className="panel-title-row">
        <h3>{nodeMeta[node.type]?.label || node.type}</h3>
        <Button icon={Trash2} variant="secondary" onClick={onDelete}>
          删除
        </Button>
      </div>

      <Field label="标签" help="节点在画布上的显示名称；只影响可读性，不改变节点类型。">
        <input value={data.label || ''} onChange={(event) => onChange('label', event.target.value)} />
      </Field>

      {node.type === 'start' ? (
        <StartFieldEditor fields={Array.isArray(data.fields) ? data.fields : []} onChange={(fields) => onChange('fields', fields)} />
      ) : null}

      {node.type === 'source' ? (
        <Field label="知识库 DB" help="指定离线处理链路读取哪个知识库；Parse、Chunk 和索引都会基于这个 DB 的来源。">
          <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
            <option value="">选择 DB</option>
            {remote.knowledgeBases.map((db) => (
              <option key={db.id} value={db.id}>
                {db.name}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      {node.type === 'query_generate' ? (
        <>
          <Field label="知识库 DB" help="指定 Query 生成参考哪个知识库内容，避免生成和数据无关的问题。">
            <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
              <option value="">选择 DB</option>
              {remote.knowledgeBases.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Query Set 名称" help="生成后保存成这个评测集名称，方便在评测页或后续 Workflow 中选择。">
            <input value={data.name || ''} onChange={(event) => onChange('name', event.target.value)} />
          </Field>
          <Field label="示例 Query" help="每行一个，3 到 5 行；模型会学习问题风格，并结合 DB 内容扩写 Query。">
            <textarea
              rows={6}
              value={examplesValue}
              onChange={(event) => onChange('examples', event.target.value.split('\n').map((line) => line.trim()).filter(Boolean))}
            />
          </Field>
          <Field label="目标数量" help="需要生成多少条 Query；数量越多覆盖面更广，后续评测耗时也更长。">
            <input
              type="number"
              min="1"
              max="500"
              value={numberValue('targetCount', 10)}
              onChange={(event) => onChange('targetCount', Number(event.target.value))}
            />
          </Field>
          <Button icon={WandSparkles} variant="secondary" onClick={onRunNode}>
            运行当前节点
          </Button>
        </>
      ) : null}

      {node.type === 'parse' ? (
        <Field label="Parser" help="决定如何从来源中抽取正文；通常保持自动识别即可。">
          <select value={data.parser || 'auto'} onChange={(event) => onChange('parser', event.target.value)}>
            <option value="auto">按来源自动识别</option>
            <option value="plain_text">Plain text</option>
            <option value="html">HTML</option>
            <option value="pdf">PDF</option>
            <option value="docx">DOCX</option>
          </select>
        </Field>
      ) : null}

      {node.type === 'chunk' ? (
        <div className="field-grid">
          <Field label="Chunk size" help="控制重新切片的长度；影响检索粒度、上下文完整度和索引大小。">
            <input
              type="number"
              min="100"
              value={numberValue('chunkSize', 900)}
              onChange={(event) => onChange('chunkSize', Number(event.target.value))}
            />
          </Field>
          <Field label="Overlap" help="控制相邻 Chunk 重叠文本量；用于减少句子被截断导致的检索丢失。">
            <input
              type="number"
              min="0"
              value={numberValue('chunkOverlap', 120)}
              onChange={(event) => onChange('chunkOverlap', Number(event.target.value))}
            />
          </Field>
        </div>
      ) : null}

      {node.type === 'embed_index' ? (
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={data.overwrite !== false}
            onChange={(event) => onChange('overwrite', event.target.checked)}
          />
          <span>准备索引时覆盖 vector index</span>
        </label>
      ) : null}

      {node.type === 'retrieve' ? (
        <>
          <Field label="知识库 DB" help="决定从哪个 DB 检索上下文；留空则继承上游 DB，适合模板链路。">
            <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
              <option value="">继承上游 DB</option>
              {remote.knowledgeBases.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="field-grid">
            <Field label="Top K" help="每个问题取回多少个相关 Chunk；更大可能召回更多信息，也会增加噪声和成本。">
              <input
                type="number"
                min="1"
                max="20"
                value={numberValue('topK', 3)}
                onChange={(event) => onChange('topK', Number(event.target.value))}
              />
            </Field>
            <Field label="检索方式" help="决定向量库怎么排序候选上下文；当前第一版只开放相似度检索。">
              <select value={data.searchType || 'similarity'} onChange={(event) => onChange('searchType', event.target.value)}>
                <option value="similarity">Similarity</option>
              </select>
            </Field>
          </div>
        </>
      ) : null}

      {node.type === 'prompt_llm' ? (
        <>
          <div className="field-grid">
            <Field label="Model" help="可覆盖配置页的默认 Answer 模型；留空时使用全局默认模型。">
              <input value={data.model || ''} placeholder="使用配置默认值" onChange={(event) => onChange('model', event.target.value)} />
            </Field>
            <Field label="Temperature" help="控制回答随机性；RAG 和评测建议偏低，输出更稳定。">
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={numberValue('temperature', 0.2)}
                onChange={(event) => onChange('temperature', Number(event.target.value))}
              />
            </Field>
          </div>
          <Field label="Prompt 模板" help="定义模型如何使用 question 和 contexts 生成回答；会直接影响答案风格和忠实度。">
            <textarea rows={8} value={data.prompt || ''} onChange={(event) => onChange('prompt', event.target.value)} />
          </Field>
        </>
      ) : null}

      {node.type === 'answer' ? (
        <>
          <Field label="输出 key" help="指定答案写入执行状态的字段名；End 节点和评测节点会从这里取结果。">
            <input value={data.outputKey || 'answer'} onChange={(event) => onChange('outputKey', event.target.value)} />
          </Field>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={data.includeContexts !== false}
              onChange={(event) => onChange('includeContexts', event.target.checked)}
            />
            <span>包含检索到的 contexts</span>
          </label>
        </>
      ) : null}

      {node.type === 'ragas_eval' ? (
        <>
          <Field label="Metric preset" help="决定使用哪组 RAGAS 指标；query-only 数据默认使用不依赖标准答案的 reference_free。">
            <select value={data.metricPreset || 'reference_free'} onChange={(event) => onChange('metricPreset', event.target.value)}>
              <option value="reference_free">reference_free</option>
            </select>
          </Field>
          <Field label="数量限制" help="限制本次评测使用多少条 Query；调试时可先少量跑，正式评测留空跑全部。">
            <input value={data.limit || ''} onChange={(event) => onChange('limit', event.target.value)} placeholder="全部" />
          </Field>
        </>
      ) : null}

      {node.type === 'end' ? (
        <EndOutputEditor outputs={Array.isArray(data.outputs) ? data.outputs : []} onChange={(outputs) => onChange('outputs', outputs)} />
      ) : null}
    </div>
  );
}

function StartFieldEditor({ fields, onChange }) {
  function updateField(index, key, value) {
    const next = fields.map((field, idx) => idx === index ? { ...field, [key]: value } : field);
    onChange(next);
  }

  function addField() {
    onChange([...fields, { name: `input_${fields.length + 1}`, type: 'string', required: false, default: '' }]);
  }

  function removeField(index) {
    onChange(fields.filter((_, idx) => idx !== index));
  }

  return (
    <div className="sub-editor">
      <div className="panel-title-row">
        <h3>输入参数</h3>
        <Button icon={Plus} variant="secondary" onClick={addField}>添加</Button>
      </div>
      <p className="muted-copy">定义执行 Graph 时需要用户填写的变量；后续节点可以读取这些值，例如 question、limit 或调试开关。</p>
      {fields.length ? fields.map((field, index) => (
        <div className="field-row" key={`${field.name}_${index}`}>
          <input value={field.name || ''} onChange={(event) => updateField(index, 'name', event.target.value)} placeholder="变量名" />
          <select value={field.type || 'string'} onChange={(event) => updateField(index, 'type', event.target.value)}>
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="boolean">boolean</option>
            <option value="json">json</option>
          </select>
          <input value={field.default ?? ''} onChange={(event) => updateField(index, 'default', event.target.value)} placeholder="默认值" />
          <label className="mini-checkbox">
            <input type="checkbox" checked={Boolean(field.required)} onChange={(event) => updateField(index, 'required', event.target.checked)} />
            必填
          </label>
          <button className="icon-button" onClick={() => removeField(index)} title="删除" type="button">
            <Trash2 size={15} />
          </button>
        </div>
      )) : <EmptyState title="暂无输入参数" body="执行时不会展示输入表单。" />}
    </div>
  );
}

function EndOutputEditor({ outputs, onChange }) {
  function updateOutput(index, value) {
    onChange(outputs.map((item, idx) => idx === index ? value : item));
  }

  return (
    <div className="sub-editor">
      <div className="panel-title-row">
        <h3>输出字段</h3>
        <Button icon={Plus} variant="secondary" onClick={() => onChange([...outputs, 'answer'])}>添加</Button>
      </div>
      <p className="muted-copy">定义 End 节点最终返回哪些 state 字段；外部调用和执行结果会优先展示这些字段。</p>
      {outputs.length ? outputs.map((output, index) => (
        <div className="output-row" key={`${output}_${index}`}>
          <input value={output || ''} onChange={(event) => updateOutput(index, event.target.value)} placeholder="state key，如 answer" />
          <button className="icon-button" onClick={() => onChange(outputs.filter((_, idx) => idx !== index))} title="删除" type="button">
            <Trash2 size={15} />
          </button>
        </div>
      )) : <EmptyState title="默认输出" body="未配置时返回当前执行结果摘要。" />}
    </div>
  );
}
