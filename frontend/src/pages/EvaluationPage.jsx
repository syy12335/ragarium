import { useMemo, useState } from 'react';
import { Play } from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, Panel, StatusPill } from '../components/ui.jsx';

export function EvaluationPage({ remote, runTask }) {
  const [querySetId, setQuerySetId] = useState('');
  const [workflowId, setWorkflowId] = useState('');
  const [limit, setLimit] = useState('');

  const querySet = useMemo(
    () => remote.querySets.find((item) => String(item.id) === String(querySetId)),
    [remote.querySets, querySetId],
  );
  const runnableWorkflows = useMemo(
    () => remote.workflows.filter((workflow) => workflow.runtime_capable),
    [remote.workflows],
  );

  function dbName(id) {
    return remote.knowledgeBases.find((db) => String(db.id) === String(id))?.name || `DB #${id}`;
  }

  async function runEvaluation() {
    return api.createEvalRun({
      query_set_id: Number(querySetId),
      workflow_id: Number(workflowId),
      limit: limit ? Number(limit) : undefined,
    });
  }

  return (
    <div className="two-column">
      <Panel title="无参考答案评测">
        <Field label="Query 集">
          <select value={querySetId} onChange={(event) => setQuerySetId(event.target.value)}>
            <option value="">选择 Query 集</option>
            {remote.querySets.map((set) => (
              <option key={set.id} value={set.id}>
                {set.name} · {dbName(set.knowledge_base_id)}
              </option>
            ))}
          </select>
        </Field>
        {querySet ? (
          <div className="hint-box">
            <strong>{querySet.queries.length} 个 queries</strong>
            <span>来自 {dbName(querySet.knowledge_base_id)}</span>
          </div>
        ) : null}
        <Field label="Workflow">
          <select value={workflowId} onChange={(event) => setWorkflowId(event.target.value)}>
            <option value="">选择 Workflow</option>
            {runnableWorkflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
            ))}
          </select>
        </Field>
        <Field label="数量限制">
          <input value={limit} onChange={(event) => setLimit(event.target.value)} placeholder="全部" />
        </Field>
        <Button icon={Play} disabled={!querySetId || !workflowId} onClick={() => runTask('启动评测中', runEvaluation)}>
          运行评测
        </Button>
      </Panel>

      <Panel title="运行记录">
        {remote.evalRuns.length ? (
          <div className="card-list">
            {remote.evalRuns.map((run) => (
              <article className="card-item" key={run.id}>
                <div className="card-head">
                  <strong>运行 #{run.id}</strong>
                  <StatusPill status={run.status} />
                </div>
                <span>{run.created_at}</span>
                {run.error ? <p className="error-text">{run.error}</p> : null}
                {Object.keys(run.metrics || {}).length ? (
                  <pre>{JSON.stringify(run.metrics, null, 2)}</pre>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="暂无评测记录" body="选择 Query 集和已保存的 Workflow 后运行评测。" />
        )}
      </Panel>
    </div>
  );
}
