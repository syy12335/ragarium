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
} from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, Panel, StatusPill } from '../components/ui.jsx';
import { buildNode, nodeCatalog, nodeMeta } from '../workflowNodes.js';

function FlowNode({ data, type, selected }) {
  const meta = nodeMeta[type] || {};
  return (
    <div className={`flow-node flow-node-${type} ${selected ? 'selected' : ''}`}>
      {type !== 'source' ? <Handle type="target" position={Position.Left} /> : null}
      <strong>{data?.label || meta.label || type}</strong>
      <small>{meta.caption}</small>
      {type !== 'answer' ? <Handle type="source" position={Position.Right} /> : null}
    </div>
  );
}

const nodeTypes = {
  source: FlowNode,
  parse: FlowNode,
  chunk: FlowNode,
  embed_index: FlowNode,
  retrieve: FlowNode,
  prompt_llm: FlowNode,
  answer: FlowNode,
};

export function WorkflowPage({ remote, runTask }) {
  const [workflowName, setWorkflowName] = useState('默认 RAG Workflow');
  const [workflowId, setWorkflowId] = useState('');
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState(null);
  const [prepareResult, setPrepareResult] = useState(null);

  useEffect(() => {
    resetDefaultWorkflow();
  }, []);

  const graph = useMemo(() => ({ nodes, edges }), [nodes, edges]);
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const existingTypes = new Set(nodes.map((node) => node.type));

  async function resetDefaultWorkflow() {
    const payload = await api.getDefaultWorkflow();
    setWorkflowId('');
    setWorkflowName(payload.name === 'Default RAG workflow' ? '默认 RAG Workflow' : payload.name);
    setNodes(payload.graph.nodes);
    setEdges(payload.graph.edges);
    setSelectedNodeId(payload.graph.nodes[0]?.id || '');
    setAnswer(null);
    setPrepareResult(null);
  }

  function loadWorkflow(id) {
    setWorkflowId(id);
    const workflow = remote.workflows.find((item) => String(item.id) === String(id));
    if (!workflow) {
      return;
    }
    setWorkflowName(workflow.name);
    setNodes(workflow.graph.nodes);
    setEdges(workflow.graph.edges);
    setSelectedNodeId(workflow.graph.nodes[0]?.id || '');
    setAnswer(null);
    setPrepareResult(null);
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
      name: workflowName.trim() || 'RAG Workflow',
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

  return (
    <div className="workflow-layout">
      <Panel
        title="节点"
        className="node-library"
        actions={
          <Button icon={RotateCcw} variant="secondary" onClick={() => runTask('重置 Workflow 中', resetDefaultWorkflow)}>
            重置
          </Button>
        }
      >
        <div className="node-list">
          {nodeCatalog.map((item) => {
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
          remote={remote}
          onChange={updateSelectedNodeData}
          onDelete={deleteSelectedNode}
        />

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

          <Field label="问题">
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="输入要基于 Workflow DB 检索回答的问题" />
          </Field>
          <Button icon={Play} disabled={!question.trim()} onClick={() => runTask('运行 Workflow 中', runWorkflow)}>
            保存并运行
          </Button>
        </div>

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
      </Panel>
    </div>
  );
}

function NodeInspector({ node, remote, onChange, onDelete }) {
  if (!node) {
    return <EmptyState title="请选择节点" body="点击画布中的节点即可配置参数。" />;
  }

  const data = node.data || {};
  const numberValue = (key, fallback) => Number(data[key] ?? fallback);

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
          <Field label="知识库 DB" help="留空则继承 Source DB">
            <select value={data.knowledgeBaseId || ''} onChange={(event) => onChange('knowledgeBaseId', event.target.value)}>
              <option value="">继承 Source DB</option>
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
    </div>
  );
}
