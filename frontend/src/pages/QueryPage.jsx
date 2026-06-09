import { useEffect, useMemo, useState } from 'react';
import { WandSparkles } from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, Panel } from '../components/ui.jsx';

export function QueryPage({ remote, runTask }) {
  const [dbId, setDbId] = useState('');
  const [examples, setExamples] = useState('如何配置这个产品？\n上传文档后怎么检索？\n评测结果怎么看？');
  const [targetCount, setTargetCount] = useState(10);
  const [name, setName] = useState('生成的 Query 集');

  useEffect(() => {
    if (!dbId && remote.knowledgeBases.length) {
      setDbId(String(remote.knowledgeBases[0].id));
    }
  }, [dbId, remote.knowledgeBases]);

  const relatedSets = useMemo(
    () => remote.querySets.filter((set) => String(set.knowledge_base_id) === String(dbId)),
    [remote.querySets, dbId],
  );

  async function generate() {
    if (!dbId) {
      throw new Error('请先选择 DB');
    }
    return api.generateQuerySet({
      knowledge_base_id: Number(dbId),
      examples: examples.split('\n').map((line) => line.trim()).filter(Boolean),
      target_count: Number(targetCount),
      name,
    });
  }

  return (
    <div className="two-column">
      <Panel title="生成 Query 集">
        <Field label="知识库 DB">
          <select value={dbId} onChange={(event) => setDbId(event.target.value)}>
            <option value="">选择 DB</option>
            {remote.knowledgeBases.map((db) => (
              <option key={db.id} value={db.id}>{db.name}</option>
            ))}
          </select>
        </Field>
        <Field label="名称">
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field label="示例 Query" help="3 到 5 行">
          <textarea value={examples} onChange={(event) => setExamples(event.target.value)} rows={8} />
        </Field>
        <Field label="目标数量">
          <input type="number" min="1" max="500" value={targetCount} onChange={(event) => setTargetCount(Number(event.target.value))} />
        </Field>
        <Button icon={WandSparkles} disabled={!dbId} onClick={() => runTask('生成 Query 中', generate)}>
          生成
        </Button>
      </Panel>

      <Panel title="Query 集">
        {relatedSets.length ? (
          <div className="card-list">
            {relatedSets.map((set) => (
              <article className="card-item" key={set.id}>
                <strong>{set.name}</strong>
                <span>{set.queries.length} 个 queries · 目标 {set.target_count}</span>
                <ol className="query-list">
                  {set.queries.slice(0, 6).map((query) => <li key={query}>{query}</li>)}
                </ol>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="暂无 Query 集" body="基于示例 Query 和 DB chunks 生成 query-only 数据。" />
        )}
      </Panel>
    </div>
  );
}
