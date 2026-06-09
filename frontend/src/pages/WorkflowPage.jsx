import { useEffect, useMemo, useState } from 'react';
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
  Database,
  ListChecks,
  Play,
  Plus,
  RotateCcw,
  Save,
  Settings,
  Trash2,
  WandSparkles,
} from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, Panel, StatusPill } from '../components/ui.jsx';
import { buildNode, nodeCatalog, nodeMeta } from '../workflowNodes.js';

const DEFAULT_TEMPLATE_ID = 'rag';
const LEGACY_TEMPLATE_ID = 'legacy_full_rag';

function FlowNode({ data, type, selected }) {
  const meta = nodeMeta[type] || {};
  const isSourceLike = type === 'source' || type === 'query_generate';
  const isTerminal = type === 'answer' || type === 'ragas_eval';
  return (
    <div className={`flow-node flow-node-${type} ${selected ? 'selected' : ''}`}>
      {!isSourceLike ? <Handle type="target" position={Position.Left} /> : null}
      <strong>{data?.label || meta.label || type}</strong>
      <small>{meta.caption}</small>
      {!isTerminal ? <Handle type="source" position={Position.Right} /> : null}
    </div>
  );
}

const nodeTypes = Object.fromEntries(nodeCatalog.map((item) => [item.type, FlowNode]));

function inferTemplateId(graph) {
  if (graph?.templateId) {
    return graph.templateId;
  }
  const types = new Set((graph?.nodes || []).map((node) => node.type));
  if (types.has('query_generate') || types.has('ragas_eval')) {
    return 'evaluation';
  }
  if (types.has('source') && types.has('parse') && types.has('chunk') && types.has('embed_index') && types.has('retrieve')) {
    return LEGACY_TEMPLATE_ID;
  }
  if (types.has('source') && types.has('parse') && types.has('chunk') && types.has('embed_index')) {
    return 'offline_db';
  }
  return DEFAULT_TEMPLATE_ID;
}

function workflowNameFallback(templateId, templates) {
  if (templateId === LEGACY_TEMPLATE_ID) {
    return 'Legacy Full RAG Workflow';
  }
  return templates.find((item) => item.id === templateId)?.name || 'RAG Workflow';
}

export function WorkflowPage({ remote, runTask }) {
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [workflowName, setWorkflowName] = useState('进行 RAG');
  const [workflowId, setWorkflowId] = useState('');
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState(null);
  const [prepareResult, setPrepareResult] = useState(null);
  const [queryNodeResult, setQueryNodeResult] = useState(null);
  const [evaluationResult, setEvaluationResult] = useState(null);

  useEffect(() => {
    async function loadInitial() {
      const items = await api.listWorkflowTemplates();
      setTemplates(items);
      await resetDefaultWorkflow(DEFAULT_TEMPLATE_ID, items);
    }
    loadInitial().catch(() => resetDefaultWorkflow(DEFAULT_TEMPLATE_ID, []));
  }, []);

  const graph = useMemo(() => ({ templateId, nodes, edges }), [templateId, nodes, edges]);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const existingTypes = new Set(nodes.map((node) => node.type));
  const currentTemplate = templates.find((item) => item.id === templateId);
  const allowedTypes = currentTemplate?.node_types || (
    templateId === LEGACY_TEMPLATE_ID
      ? ['source', 'parse', 'chunk', 'embed_index', 'retrieve', 'prompt_llm', 'answer']
      : []
  );
  const availableNodes = nodeCatalog.filter((item) => allowedTypes.includes(item.type));

  function clearOutputs() {
    setAnswer(null);
    setPrepareResult(null);
    setQueryNodeResult(null);
    setEvaluationResult(null);
  }

  async function resetDefaultWorkflow(nextTemplateId = templateId, knownTemplates = templates) {
    const normalizedTemplateId = nextTemplateId === LEGACY_TEMPLATE_ID ? DEFAULT_TEMPLATE_ID : nextTemplateId;
    const payload = await api.getDefaultWorkflow(normalizedTemplateId || DEFAULT_TEMPLATE_ID);
    setWorkflowId('');
    setTemplateId(payload.graph.templateId || normalizedTemplateId || DEFAULT_TEMPLATE_ID);
    setWorkflowName(payload.name || workflowNameFallback(normalizedTemplateId, knownTemplates));
    setNodes(payload.graph.nodes);
    setEdges(payload.graph.edges);
    setSelectedNodeId(payload.graph.nodes[0]?.id || '');
    clearOutputs();
  }

  function loadWorkflow(id) {
    if (!id) {
      resetDefaultWorkflow(templateId).catch(() => {});
      return;
    }
    setWorkflowId(id);
    const workflow = remote.workflows.find((item) => String(item.id) === String(id));
    if (!workflow) {
      return;
    }
    const loadedTemplateId = inferTemplateId(workflow.graph);
    setTemplateId(loadedTemplateId);
    setWorkflowName(workflow.name);
    setNodes(workflow.graph.nodes);
    setEdges(workflow.graph.edges);
    setSelectedNodeId(workflow.graph.nodes[0]?.id || '');
    clearOutputs();
  }

  function addNode(type) {
    const existing = nodes.find((node) => node.type === type);
    if (existing) {
      setSelectedNodeId(existing.id);
      return;
    }
    const next = buildNode(type, nodes.length);
    setNodes((current) => [...current, next]);
    setSelectedNodeId(next.id);
  }

  function deleteSelectedNode() {
    if (!selectedNodeId) {
      return;
    }
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId));
    setEdges((current) => current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId));
    setSelectedNodeId('');
  }

  function updateSelectedNodeData(key, value) {
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedNodeId
          ? { ...node, data: { ...(node.data || {}), [key]: value } }
          : node,
      ),
    );
  }

  async function saveCurrentWorkflow() {
    const saved = await api.saveWorkflow({
      id: workflowId || undefined,
      name: workflowName.trim() || workflowNameFallback(templateId, templates),
      graph,
    });
    setWorkflowId(String(saved.id));
    await remote.refresh();
    return saved;
  }

  async function prepareWorkflow() {
    const saved = await saveCurrentWorkflow();
    const result = await api.prepareWorkflow(saved.id);
    setPrepareResult(result);
    await remote.refresh();
    return result;
  }

  async function runWorkflow() {
    if (!question.trim()) {
      throw new Error('请先输入问题');
    }
    const saved = await saveCurrentWorkflow();
    const result = await api.runWorkflow(saved.id, { question: question.trim() });
    setAnswer(result);
    return result;
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

  async function runEvaluationWorkflow() {
    const saved = await saveCurrentWorkflow();
    const result = await api.evaluateWorkflow(saved.id);
    setEvaluationResult(result);
    await remote.refresh();
    return result;
  }

  function renderRunBox() {
    if (templateId === 'offline_db') {
      return (
        <div className="run-box">
          <Button icon={Database} variant="secondary" onClick={() => runTask('准备 Workflow 中', prepareWorkflow)}>
            保存并准备索引
          </Button>
          {prepareResult ? (
            <div className="mini-result">
              <span>已准备 DB #{prepareResult.knowledge_base_id}</span>
              <StatusPill status={prepareResult.index_status} />
              <small>{prepareResult.chunk_count} 个 chunks · {prepareResult.collection_name}</small>
            </div>
          ) : null}
        </div>
      );
    }

    if (templateId === 'evaluation') {
      return (
        <div className="run-box">
          <Button icon={ListChecks} onClick={() => runTask('运行评测 Workflow 中', runEvaluationWorkflow)}>
            保存并运行评测
          </Button>
          {queryNodeResult ? <QuerySetResult result={queryNodeResult.query_set} title="节点生成结果" /> : null}
          {evaluationResult ? (
            <div className="result">
              <h3>评测结果</h3>
              <QuerySetResult result={evaluationResult.query_set} title="生成的 Query Set" />
              <div className="mini-result">
                <span>Eval run #{evaluationResult.eval_run?.id}</span>
                <StatusPill status={evaluationResult.eval_run?.status} />
              </div>
              {Object.keys(evaluationResult.eval_run?.metrics || {}).length ? (
                <pre>{JSON.stringify(evaluationResult.eval_run.metrics, null, 2)}</pre>
              ) : null}
              {evaluationResult.eval_run?.error ? <p className="error-text">{evaluationResult.eval_run.error}</p> : null}
            </div>
          ) : null}
        </div>
      );
    }

    return (
      <div className="run-box">
        {templateId === LEGACY_TEMPLATE_ID ? (
          <>
            <Button icon={Database} variant="secondary" onClick={() => runTask('准备 Workflow 中', prepareWorkflow)}>
              保存并准备索引
            </Button>
            {prepareResult ? (
              <div className="mini-result">
                <span>已准备 DB #{prepareResult.knowledge_base_id}</span>
                <StatusPill status={prepareResult.index_status} />
                <small>{prepareResult.chunk_count} 个 chunks · {prepareResult.collection_name}</small>
              </div>
            ) : null}
          </>
        ) : null}
        <Field label="问题">
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入要基于 Workflow DB 检索回答的问题" />
        </Field>
        <Button icon={Play} disabled={!question.trim()} onClick={() => runTask('运行 Workflow 中', runWorkflow)}>
          保存并运行
        </Button>
        {answer ? (
          <div className="result">
            <h3>回答</h3>
            <p>{answer.answer || answer.generation}</p>
            <h3>上下文</h3>
            {(answer.contexts || []).slice(0, 4).map((context, index) => (
              <p className="chunk-preview" key={index}>{typeof context === 'string' ? context : context.content}</p>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="workflow-page">
      <Panel title="Workflow 模板" className="template-panel">
        <div className="template-grid">
          {templates.map((template) => (
            <button
              key={template.id}
              className={templateId === template.id ? 'template-card active' : 'template-card'}
              onClick={() => runTask('加载 Workflow 模板中', () => resetDefaultWorkflow(template.id))}
            >
              <strong>{template.name}</strong>
              <span>{template.description}</span>
              <small>{template.node_types.join(' -> ')}</small>
            </button>
          ))}
        </div>
      </Panel>

      <div className="workflow-layout">
        <Panel
          title="节点"
          className="node-library"
          actions={
            <Button icon={RotateCcw} variant="secondary" onClick={() => runTask('重置 Workflow 中', () => resetDefaultWorkflow(templateId))}>
              重置
            </Button>
          }
        >
          <div className="node-list">
            {availableNodes.map((item) => {
              const exists = existingTypes.has(item.type);
              return (
                <button
                  key={item.type}
                  className={exists ? 'node-card active' : 'node-card'}
                  onClick={() => addNode(item.type)}
                  title={exists ? '已在画布中，点击可选中。' : '添加节点到画布'}
                >
                  <Plus size={15} />
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.caption}</small>
                  </span>
                </button>
              );
            })}
          </div>
        </Panel>

        <div className="canvas-panel">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={(changes) => setNodes((current) => applyNodeChanges(changes, current))}
            onEdgesChange={(changes) => setEdges((current) => applyEdgeChanges(changes, current))}
            onConnect={(params) =>
              setEdges((current) =>
                addEdge(
                  {
                    ...params,
                    id: `${params.source}-${params.target}-${Date.now()}`,
                    animated: false,
                  },
                  current,
                ),
              )
            }
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId('')}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <Panel title="参数配置" className="inspector-panel" actions={<Settings size={17} />}>
          <Field label="已保存 Workflow">
            <select value={workflowId} onChange={(event) => loadWorkflow(event.target.value)}>
              <option value="">未保存的默认配置</option>
              {remote.workflows.map((workflow) => (
                <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
              ))}
            </select>
          </Field>
          <Field label="名称">
            <input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
          </Field>
          <div className="button-row">
            <Button icon={ListChecks} variant="secondary" onClick={() => runTask('校验 Workflow 中', () => api.validateWorkflow({ name: workflowName, graph }))}>
              校验
            </Button>
            <Button icon={Save} onClick={() => runTask('保存 Workflow 中', saveCurrentWorkflow)}>
              保存
            </Button>
          </div>

          <NodeInspector
            node={selectedNode}
            templateId={templateId}
            remote={remote}
            onChange={updateSelectedNodeData}
            onDelete={deleteSelectedNode}
            onRunNode={() => runTask('运行 Query Generate 节点中', runSelectedNode)}
          />

          {renderRunBox()}
        </Panel>
      </div>
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

function NodeInspector({ node, templateId, remote, onChange, onDelete, onRunNode }) {
  if (!node) {
    return <EmptyState title="请选择节点" body="点击画布中的节点即可配置参数。" />;
  }

  const data = node.data || {};
  const numberValue = (key, fallback) => Number(data[key] ?? fallback);
  const examplesValue = Array.isArray(data.examples) ? data.examples.join('\n') : (data.examples || '');
  const retrieveHelp = templateId === 'evaluation'
    ? '留空则继承 Query Generate DB'
    : templateId === LEGACY_TEMPLATE_ID
      ? '留空则继承 Source DB'
      : 'RAG 模板需要选择已索引 DB';

  return (
    <div className="node-inspector">
      <div className="panel-title-row">
        <h3>{nodeMeta[node.type]?.label || node.type}</h3>
        <Button icon={Trash2} variant="secondary" onClick={onDelete}>
          删除
        </Button>
      </div>

      <Field label="标签">
        <input value={data.label || ''} onChange={(event) => onChange('label', event.target.value)} />
      </Field>

      {node.type === 'source' ? (
        <Field label="知识库 DB">
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
          <Field label="知识库 DB">
            <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
              <option value="">选择 DB</option>
              {remote.knowledgeBases.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Query Set 名称">
            <input value={data.name || ''} onChange={(event) => onChange('name', event.target.value)} />
          </Field>
          <Field label="示例 Query" help="3 到 5 行">
            <textarea
              rows={6}
              value={examplesValue}
              onChange={(event) => onChange('examples', event.target.value.split('\n').map((line) => line.trim()).filter(Boolean))}
            />
          </Field>
          <Field label="目标数量">
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
        <Field label="Parser">
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
          <Field label="Chunk size">
            <input
              type="number"
              min="100"
              value={numberValue('chunkSize', 900)}
              onChange={(event) => onChange('chunkSize', Number(event.target.value))}
            />
          </Field>
          <Field label="Overlap">
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
          <Field label="知识库 DB" help={retrieveHelp}>
            <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
              <option value="">{templateId === 'rag' ? '选择 DB' : '继承上游 DB'}</option>
              {remote.knowledgeBases.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="field-grid">
            <Field label="Top K">
              <input
                type="number"
                min="1"
                max="20"
                value={numberValue('topK', 3)}
                onChange={(event) => onChange('topK', Number(event.target.value))}
              />
            </Field>
            <Field label="检索方式">
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
            <Field label="Model">
              <input value={data.model || ''} placeholder="使用配置默认值" onChange={(event) => onChange('model', event.target.value)} />
            </Field>
            <Field label="Temperature">
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
          <Field label="Prompt 模板">
            <textarea rows={8} value={data.prompt || ''} onChange={(event) => onChange('prompt', event.target.value)} />
          </Field>
        </>
      ) : null}

      {node.type === 'answer' ? (
        <>
          <Field label="输出 key">
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
          <Field label="Metric preset">
            <select value={data.metricPreset || 'reference_free'} onChange={(event) => onChange('metricPreset', event.target.value)}>
              <option value="reference_free">reference_free</option>
            </select>
          </Field>
          <Field label="数量限制">
            <input value={data.limit || ''} onChange={(event) => onChange('limit', event.target.value)} placeholder="全部" />
          </Field>
        </>
      ) : null}
    </div>
  );
}
