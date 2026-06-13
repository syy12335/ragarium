import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Play, WandSparkles } from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, HelpDot, Panel, StatusPill } from '../components/ui.jsx';
import { FALLBACK_DEFAULT_METRICS, resolveDefaultMetricNames, resolveMetricSpecs } from '../evalMetrics.js';

export function EvaluationPage({ remote, runTask, onNavigate }) {
  const [querySetId, setQuerySetId] = useState('');
  const [workflowId, setWorkflowId] = useState('');
  const [limit, setLimit] = useState('');
  const [selectedMetricNames, setSelectedMetricNames] = useState(FALLBACK_DEFAULT_METRICS);
  const [activeRun, setActiveRun] = useState(null);
  const [isRunning, setIsRunning] = useState(false);

  const querySet = useMemo(
    () => remote.querySets.find((item) => String(item.id) === String(querySetId)),
    [remote.querySets, querySetId],
  );
  const runnableWorkflows = useMemo(
    () => remote.workflows.filter((workflow) => workflow.runtime_capable),
    [remote.workflows],
  );
  const selectedWorkflow = useMemo(
    () => remote.workflows.find((workflow) => String(workflow.id) === String(workflowId)),
    [remote.workflows, workflowId],
  );
  const hasQuerySets = remote.querySets.length > 0;
  const visibleRuns = activeRun ? [activeRun, ...remote.evalRuns] : remote.evalRuns;
  const metricSpecs = resolveMetricSpecs(remote);
  const defaultMetricNames = resolveDefaultMetricNames(remote);
  const defaultMetricKey = defaultMetricNames.join('|');
  const hasRemoteMetricDefaults = Boolean(remote.evalMetrics?.default_metric_names?.length);
  const metricsByName = useMemo(
    () => Object.fromEntries(metricSpecs.map((spec) => [spec.name, spec])),
    [metricSpecs],
  );
  const hasReference = Boolean(querySet?.has_reference || querySet?.reference_count);
  const selectedMetricSummary = selectedMetricNames
    .map((name) => metricsByName[name]?.label || name)
    .join(' / ');

  useEffect(() => {
    if (!hasRemoteMetricDefaults) {
      return;
    }
    setSelectedMetricNames((current) => {
      const stillUsingFallback =
        current.length === FALLBACK_DEFAULT_METRICS.length &&
        current.every((name, index) => name === FALLBACK_DEFAULT_METRICS[index]);
      return stillUsingFallback ? defaultMetricNames : current;
    });
  }, [defaultMetricKey, hasRemoteMetricDefaults]);

  function dbName(id) {
    return remote.knowledgeBases.find((db) => String(db.id) === String(id))?.name || `DB #${id}`;
  }

  function toggleMetric(name) {
    setSelectedMetricNames((current) => {
      if (current.includes(name)) {
        return current.length === 1 ? current : current.filter((item) => item !== name);
      }
      return [...current, name];
    });
  }

  async function runEvaluation() {
    return api.createEvalRun({
      query_set_id: Number(querySetId),
      workflow_id: Number(workflowId),
      limit: limit ? Number(limit) : undefined,
      metric_names: selectedMetricNames,
    });
  }

  async function handleRunEvaluation() {
    if (!querySetId || !workflowId || isRunning) {
      return;
    }
    const queryCount = estimateQueryCount(querySet, limit);
    setIsRunning(true);
    setActiveRun({
      id: 'pending',
      status: 'running',
      created_at: '刚刚',
      query_set_name: querySet?.name || '当前 Query 集',
      workflow_name: selectedWorkflow?.name || '当前 Workflow',
      query_count: queryCount,
      metrics: {},
      error: '',
    });
    const result = await runTask('运行评测中', async () => {
      const created = await runEvaluation();
      if (created?.status === 'failed') {
        await remote.refresh();
        setActiveRun(null);
        throw new Error(created.error || '评测失败');
      }
      return created;
    });
    setIsRunning(false);
    if (result) {
      setActiveRun(null);
    } else {
      setActiveRun((current) => current ? {
        ...current,
        status: 'failed',
        error: current.error || '评测没有完成。请查看顶部错误提示，或刷新运行记录确认是否已落库。',
      } : null);
    }
  }

  return (
    <div className="two-column">
      <Panel title="无参考答案评测">
        {!hasQuerySets ? (
          <div className="prerequisite-card">
            <div className="prerequisite-icon">
              <WandSparkles size={20} />
            </div>
            <div>
              <strong>先准备评测集</strong>
              <span>评测需要一组 Query 作为输入。先去数据页创建评测集，回来后再选择 Workflow 运行 RAGAS。</span>
            </div>
            <Button icon={WandSparkles} variant="secondary" onClick={() => onNavigate('queries')}>
              创建评测集
            </Button>
          </div>
        ) : (
          <>
            <Field label="Query 集" help="选择要评测的问题列表；系统会逐条运行 Workflow 生成答案，再交给 RAGAS 评分。">
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
            ) : (
              <div className="inline-action-hint">
                <span>需要新建或管理评测集？</span>
                <button type="button" onClick={() => onNavigate('queries')}>
                  <WandSparkles size={14} />
                  <span>去评测集</span>
                </button>
              </div>
            )}
            <Field label="Workflow" help="选择用于回答 Query 的 RAG Graph；评测指标会基于它生成的 answer 和 contexts。">
              <select value={workflowId} onChange={(event) => setWorkflowId(event.target.value)}>
                <option value="">选择 Workflow</option>
                {runnableWorkflows.map((workflow) => (
                  <option key={workflow.id} value={workflow.id}>{workflow.name}</option>
                ))}
              </select>
            </Field>
            <Field label="数量限制" help="限制本次评测使用多少条 Query；留空表示跑完整评测集，调试时可先填小数字。">
              <input value={limit} onChange={(event) => setLimit(event.target.value)} placeholder="全部" />
            </Field>
            <details className="advanced-section">
              <summary>
                <span>高级设置</span>
                <small>RAGAS 指标：{selectedMetricSummary}</small>
              </summary>
              <MetricSelector
                metrics={metricSpecs}
                selected={selectedMetricNames}
                defaultMetricNames={defaultMetricNames}
                hasReference={hasReference}
                onToggle={toggleMetric}
                onReset={() => setSelectedMetricNames(defaultMetricNames)}
              />
            </details>
            <Button
              icon={Play}
              loading={isRunning}
              loadingLabel="评测中"
              disabled={!querySetId || !workflowId || selectedMetricNames.length === 0}
              onClick={handleRunEvaluation}
            >
              运行评测
            </Button>
          </>
        )}
      </Panel>

      <Panel title="运行记录">
        {visibleRuns.length ? (
          <div className="card-list">
            {visibleRuns.map((run) => <EvalRunCard key={run.id} run={run} metricsByName={metricsByName} />)}
          </div>
        ) : (
          <EmptyState title="暂无评测记录" body="选择 Query 集和已保存的 Workflow 后运行评测。" />
        )}
      </Panel>
    </div>
  );
}

function MetricSelector({ metrics, selected, defaultMetricNames, hasReference, onToggle, onReset }) {
  return (
    <div className="metric-selector">
      <div className="metric-selector-head">
        <strong>RAGAS 指标</strong>
        <button type="button" className="text-action-button" onClick={onReset}>
          恢复默认
        </button>
      </div>
      <div className="metric-option-list">
        {metrics.map((metric) => {
          const disabled = metric.requires_reference && !hasReference;
          return (
            <label key={metric.name} className={`metric-option ${disabled ? 'disabled' : ''}`}>
              <input
                type="checkbox"
                checked={selected.includes(metric.name)}
                disabled={disabled}
                onChange={() => onToggle(metric.name)}
              />
              <span>
                <strong>
                  {metric.label}
                  <HelpDot text={metric.description} />
                </strong>
                <small>
                  {metric.name}
                  {metric.requires_reference ? ' · 需要 reference' : ' · query-only 可用'}
                </small>
              </span>
            </label>
          );
        })}
      </div>
      {!hasReference ? (
        <p className="muted-copy">当前评测集没有 reference answer，因此依赖 reference 的指标会先禁用。</p>
      ) : null}
    </div>
  );
}

function estimateQueryCount(querySet, limit) {
  const total = querySet?.queries?.length || 0;
  const capped = Number(limit);
  if (!Number.isFinite(capped) || capped <= 0) {
    return total;
  }
  return Math.min(total, capped);
}

function EvalRunCard({ run, metricsByName }) {
  const isPending = run.id === 'pending';
  const [expanded, setExpanded] = useState(false);
  const metrics = run.metrics || {};
  const metricEntries = Object.entries(metrics);
  const samples = Array.isArray(run.samples) ? run.samples : [];
  return (
    <article className={`card-item eval-run-card ${isPending ? 'active' : ''}`}>
      <div className="card-head">
        <strong>{isPending ? '本次评测' : `运行 #${run.id}`}</strong>
        <StatusPill status={run.status} />
      </div>
      <span>
        {isPending
          ? `${run.query_set_name} · ${run.workflow_name} · ${run.query_count} 个 queries`
          : run.created_at}
      </span>
      {isPending && run.status === 'running' ? <EvalProgress /> : null}
      {run.error ? <p className="error-text">{run.error}</p> : null}
      {metricEntries.length ? (
        <div className="eval-metric-list" aria-label="总体指标">
          {metricEntries.map(([name, value]) => (
            <div key={name} className="eval-metric-pill">
              <MetricLabel name={name} metricsByName={metricsByName} />
              <strong>{formatMetricValue(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {samples.length ? (
        <div className="eval-sample-section">
          <button type="button" className="text-action-button" onClick={() => setExpanded((value) => !value)}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
            <span>{expanded ? '收起单条明细' : `查看 ${samples.length} 条单条明细`}</span>
          </button>
          {expanded ? (
            <div className="eval-sample-list">
              {samples.map((sample, index) => (
                <EvalSampleCard key={`${run.id}-${sample.index || index}`} sample={sample} index={index} metricsByName={metricsByName} />
              ))}
            </div>
          ) : null}
        </div>
      ) : !isPending && run.status === 'completed' ? (
        <p className="muted-copy">这条历史记录没有保存单条明细；重新运行一次评测后会展示每条 Query 的答案和 contexts。</p>
      ) : null}
    </article>
  );
}

function EvalSampleCard({ sample, index, metricsByName }) {
  const contexts = Array.isArray(sample.contexts) ? sample.contexts : [];
  const metricEntries = Object.entries(sample.metrics || {});
  return (
    <article className="eval-sample-card">
      <div className="eval-sample-head">
        <strong>单条 #{sample.index || index + 1}</strong>
        {metricEntries.length ? (
          <div className="eval-sample-metrics">
            {metricEntries.map(([name, value]) => (
              <span key={name}>
                <MetricLabel name={name} metricsByName={metricsByName} />
                {formatMetricValue(value)}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="eval-sample-block">
        <span>Query</span>
        <p>{sample.question || '无 Query'}</p>
      </div>
      <div className="eval-sample-block">
        <span>Answer</span>
        <p>{sample.answer || '无 answer'}</p>
      </div>
      <details className="eval-contexts">
        <summary>Contexts（{contexts.length}）</summary>
        {contexts.length ? (
          <ol>
            {contexts.map((context, contextIndex) => (
              <li key={contextIndex}>{String(context)}</li>
            ))}
          </ol>
        ) : (
          <p>没有返回 contexts。</p>
        )}
      </details>
    </article>
  );
}

function MetricLabel({ name, metricsByName }) {
  const spec = metricsByName?.[name];
  return (
    <span className="metric-label">
      <span>{spec?.label || name}</span>
      {spec?.description ? <HelpDot text={spec.description} /> : null}
    </span>
  );
}

function formatMetricValue(value) {
  if (value === null || value === undefined) {
    return '无结果';
  }
  const number = Number(value);
  if (Number.isFinite(number)) {
    return number.toFixed(3);
  }
  return String(value);
}

function EvalProgress() {
  const steps = ['读取 Query 集', '运行 Workflow 生成答案', 'RAGAS 评分', '保存评测结果'];
  return (
    <div className="eval-progress">
      <strong>正在评测，请保持当前页面打开。</strong>
      <div className="eval-step-list">
        {steps.map((step, index) => (
          <span key={step} className={index === 1 ? 'active' : ''}>
            {step}
          </span>
        ))}
      </div>
    </div>
  );
}
