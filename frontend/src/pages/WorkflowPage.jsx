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
  return (
    <div className={`flow-node flow-node-${type} ${selected ? 'selected' : ''}`}>
      {type !== 'start' ? <Handle type="target" position={Position.Left} /> : null}
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
  const [starterTemplateId, setStarterTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [workflowName, setWorkflowName] = useState('未命名 Graph');
  const [workflowId, setWorkflowId] = useState('');
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [flowInstance, setFlowInstance] = useState(null);
  const [startInputs, setStartInputs] = useState({});
  const [validationResult, setValidationResult] = useState(null);
  const [executeResult, setExecuteResult] = useState(null);
  const [queryNodeResult, setQueryNodeResult] = useState(null);

  useEffect(() => {
    async function loadInitial() {
      const items = await api.listWorkflowTemplates();
      setTemplates(items);
      await createNewGraph(DEFAULT_TEMPLATE_ID, items);
    }
    loadInitial().catch(() => createNewGraph(DEFAULT_TEMPLATE_ID, []));
  }, []);

  const graph = useMemo(
    () => ({ templateId: starterTemplateId, nodes, edges }),
    [starterTemplateId, nodes, edges],
  );
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const startNode = nodes.find((node) => node.type === 'start');
  const startFields = Array.isArray(startNode?.data?.fields) ? startNode.data.fields : [];

  function clearRunState() {
    setValidationResult(null);
    setExecuteResult(null);
    setQueryNodeResult(null);
  }

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
  }

  function loadWorkflow(id) {
    if (!id) {
      createNewGraph(starterTemplateId).catch(() => {});
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

  async function executeCurrentWorkflow() {
    const saved = await saveCurrentWorkflow();
    const result = await api.executeWorkflow(saved.id, { inputs: startInputs });
    setExecuteResult(result);
    await remote.refresh();
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

  function updateStartInput(name, value) {
    setStartInputs((current) => ({ ...current, [name]: value }));
  }

  return (
    <div className="workflow-layout graph-editor-layout">
      <Panel title="Graph" className="graph-sidebar">
        <Field label="已保存 Graph">
          <select value={workflowId} onChange={(event) => loadWorkflow(event.target.value)}>
            <option value="">未保存草稿</option>
            {remote.workflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
            ))}
          </select>
        </Field>

        <div className="new-graph-list">
          <span>新建 Graph</span>
          {templates.map((template) => (
            <button
              key={template.id}
              className="new-graph-card"
              onClick={() => runTask('新建 Graph 中', () => createNewGraph(template.id))}
            >
              <strong>{template.name}</strong>
              <small>{template.description}</small>
            </button>
          ))}
        </div>

        <div className="node-list">
          <span className="section-label">节点库</span>
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
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onInit={setFlowInstance}
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
        <Field label="Graph 名称">
          <input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
        </Field>
        <div className="button-row">
          <Button icon={ListChecks} variant="secondary" onClick={() => runTask('校验 Graph 中', validateCurrentWorkflow)}>
            校验
          </Button>
          <Button icon={Save} onClick={() => runTask('保存 Graph 中', saveCurrentWorkflow)}>
            保存
          </Button>
          <Button icon={Play} onClick={() => runTask('执行 Graph 中', executeCurrentWorkflow)}>
            执行
          </Button>
        </div>

        {validationResult ? (
          <div className={validationResult.ok ? 'hint-box' : 'hint-box error-box'}>
            <strong>{validationResult.ok ? '可执行' : '暂不可执行'}</strong>
            <span>{validationResult.ok ? `${validationResult.node_count} 个节点已通过运行前校验` : validationResult.error}</span>
          </div>
        ) : null}

        <StartInputForm fields={startFields} values={startInputs} onChange={updateStartInput} />

        <NodeInspector
          node={selectedNode}
          remote={remote}
          onChange={updateSelectedNodeData}
          onDelete={deleteSelectedNode}
          onRunNode={() => runTask('运行 Query Generate 节点中', runSelectedNode)}
        />

        {queryNodeResult ? <QuerySetResult result={queryNodeResult.query_set} title="节点生成结果" /> : null}
        {executeResult ? <ExecutionResult result={executeResult} /> : null}
      </Panel>
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
          <Field key={field.name} label={`${field.name}${field.required ? ' *' : ''}`} help={field.type}>
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
  return (
    <div className="result">
      <h3>执行结果</h3>
      <pre>{JSON.stringify(result.outputs || {}, null, 2)}</pre>
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

      <Field label="标签">
        <input value={data.label || ''} onChange={(event) => onChange('label', event.target.value)} />
      </Field>

      {node.type === 'start' ? (
        <StartFieldEditor fields={Array.isArray(data.fields) ? data.fields : []} onChange={(fields) => onChange('fields', fields)} />
      ) : null}

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
          <Field label="知识库 DB" help="留空则继承上游 DB">
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
