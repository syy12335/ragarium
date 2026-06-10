import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Database,
  FilePlus2,
  Link2,
  ListChecks,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  WandSparkles,
} from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, HelpDot, IconButton, Panel, StatusPill } from '../components/ui.jsx';

const supportedText = '支持 .txt、.md、.html、.pdf、.docx 文件和单页 URL；同一批来源会一起切割并保存到当前 name-db。';
const defaultExamples = '如何配置这个产品？\n上传文档后怎么检索？\n评测结果怎么看？';

function newSourceRow(type = 'file') {
  return {
    id: `${Date.now()}-${Math.random()}`,
    type,
    file: null,
    url: '',
  };
}

export function DataPage({ remote, runTask, initialSection = 'landing', navigationKey = 0 }) {
  const [viewMode, setViewMode] = useState('landing');
  const [selectedDbId, setSelectedDbId] = useState('');
  const [newDbName, setNewDbName] = useState('');
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([newSourceRow('file')]);
  const [chunk, setChunk] = useState({ chunk_size: 900, chunk_overlap: 120 });
  const [queryDbId, setQueryDbId] = useState('');
  const [queryExamples, setQueryExamples] = useState(defaultExamples);
  const [queryTargetCount, setQueryTargetCount] = useState(10);
  const [queryName, setQueryName] = useState('生成的 Query 集');
  const [selectedQuerySetId, setSelectedQuerySetId] = useState('');

  useEffect(() => {
    api.getConfig().then((config) => setChunk(config.chunk || chunk)).catch(() => {});
  }, []);

  useEffect(() => {
    if (initialSection === 'querySets') {
      setViewMode('query-entry');
      return;
    }
    setViewMode('landing');
  }, [initialSection, navigationKey]);

  useEffect(() => {
    if (!selectedDbId || viewMode !== 'kb-detail') {
      if (!selectedDbId) {
        setDetail(null);
      }
      return;
    }
    api.getKnowledgeBase(selectedDbId).then(setDetail).catch(() => setDetail(null));
  }, [selectedDbId, remote.knowledgeBases, viewMode]);

  useEffect(() => {
    if (!queryDbId && remote.knowledgeBases.length) {
      setQueryDbId(String(remote.knowledgeBases[0].id));
    }
  }, [queryDbId, remote.knowledgeBases]);

  const selectedDb = useMemo(
    () => remote.knowledgeBases.find((item) => String(item.id) === String(selectedDbId)),
    [remote.knowledgeBases, selectedDbId],
  );

  const selectedQuerySet = useMemo(
    () => remote.querySets.find((item) => String(item.id) === String(selectedQuerySetId)),
    [remote.querySets, selectedQuerySetId],
  );

  const querySetsForDb = useMemo(
    () => remote.querySets.filter((set) => String(set.knowledge_base_id) === String(queryDbId)),
    [remote.querySets, queryDbId],
  );

  function dbName(id) {
    return remote.knowledgeBases.find((db) => String(db.id) === String(id))?.name || `DB #${id}`;
  }

  function backToLanding() {
    setViewMode('landing');
    setSelectedDbId('');
    setSelectedQuerySetId('');
    setDetail(null);
  }

  function openKnowledgeBase(id) {
    setSelectedDbId(String(id));
    setViewMode('kb-detail');
  }

  function updateRow(id, patch) {
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeRow(id) {
    setRows((current) => (current.length === 1 ? current : current.filter((row) => row.id !== id)));
  }

  async function refreshDetail() {
    await remote.refresh();
    if (selectedDbId) {
      setDetail(await api.getKnowledgeBase(selectedDbId));
    }
  }

  async function createDb() {
    const created = await api.createKnowledgeBase(newDbName.trim() || 'knowledge-db');
    setNewDbName('');
    setSelectedDbId(String(created.id));
    setDetail(await api.getKnowledgeBase(created.id));
    setViewMode('kb-detail');
    return created;
  }

  async function importSources() {
    if (!selectedDbId) {
      throw new Error('请先选择或创建 DB');
    }
    const readyRows = rows.filter((row) => (row.type === 'file' ? row.file : row.url.trim()));
    if (!readyRows.length) {
      throw new Error('请至少添加一个 File 或 URL');
    }
    const options = {
      chunk_size: Number(chunk.chunk_size),
      chunk_overlap: Number(chunk.chunk_overlap),
    };
    for (const row of readyRows) {
      if (row.type === 'file') {
        await api.uploadFile(selectedDbId, row.file, options);
      } else {
        await api.importUrl(selectedDbId, row.url.trim(), options);
      }
    }
    setRows([newSourceRow('file')]);
    await refreshDetail();
  }

  async function buildIndex() {
    if (!selectedDbId) {
      throw new Error('请先选择或创建 DB');
    }
    const result = await api.buildIndex(selectedDbId, true);
    await refreshDetail();
    return result;
  }

  function startNewQuerySet() {
    setQueryDbId(remote.knowledgeBases[0] ? String(remote.knowledgeBases[0].id) : '');
    setQueryExamples(defaultExamples);
    setQueryTargetCount(10);
    setQueryName('生成的 Query 集');
    setSelectedQuerySetId('');
    setViewMode('query-create');
  }

  function openQuerySet(id) {
    setSelectedQuerySetId(String(id));
    setViewMode('query-detail');
  }

  async function generateQuerySet() {
    if (!queryDbId) {
      throw new Error('请先选择知识库 DB');
    }
    const result = await api.generateQuerySet({
      knowledge_base_id: Number(queryDbId),
      examples: queryExamples.split('\n').map((line) => line.trim()).filter(Boolean),
      target_count: Number(queryTargetCount),
      name: queryName.trim() || '生成的 Query 集',
    });
    setSelectedQuerySetId(String(result.id));
    setViewMode('query-detail');
    return result;
  }

  if (viewMode === 'landing') {
    return (
      <div className="data-entry-grid">
        <button className="data-entry-card large" onClick={() => setViewMode('kb-entry')}>
          <Database size={42} />
          <span>
            <strong>知识库</strong>
            <small>导入 File / URL，切分 Chunk，并构建索引。</small>
          </span>
        </button>
        <button className="data-entry-card large" onClick={() => setViewMode('query-entry')}>
          <ListChecks size={42} />
          <span>
            <strong>评测集</strong>
            <small>管理 query-only 数据集，用于后续 RAGAS 评测。</small>
          </span>
        </button>
      </div>
    );
  }

  if (viewMode === 'kb-entry') {
    return (
      <div className="data-section-shell">
        <DataBackHeader title="知识库" subtitle="选择加载已有 DB，或新建一个知识库。" onBack={backToLanding} />
        <div className="data-entry-layout">
          <Panel title="加载已有知识库">
            {remote.knowledgeBases.length ? (
              <div className="db-list relaxed">
                {remote.knowledgeBases.map((db) => (
                  <button key={db.id} className="db-item" onClick={() => openKnowledgeBase(db.id)}>
                    <span>
                      <strong>{db.name}</strong>
                      <small>{db.collection_name}</small>
                    </span>
                    <span className="db-meta">
                      <StatusPill status={db.index_status} />
                      <small>{db.source_count || 0} 个来源 · {db.chunk_count || 0} 个 chunks</small>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无知识库" body="从右侧新建一个 DB 后再导入来源。" />
            )}
          </Panel>

          <Panel title="新建知识库">
            <Field label="名称">
              <input
                value={newDbName}
                onChange={(event) => setNewDbName(event.target.value)}
                placeholder="support-docs-db"
              />
            </Field>
            <Button icon={FilePlus2} onClick={() => runTask('创建 DB 中', createDb)}>
              创建并进入
            </Button>
          </Panel>
        </div>
      </div>
    );
  }

  if (viewMode === 'kb-detail') {
    return (
      <div className="data-section-shell">
        <DataBackHeader title={selectedDb ? selectedDb.name : '知识库详情'} subtitle={selectedDb ? selectedDb.collection_name : '未选择 DB'} onBack={() => setViewMode('kb-entry')} />
        <div className="data-main">
          <Panel
            title="知识库概览"
            actions={
              <>
                <Button icon={RefreshCw} variant="secondary" onClick={() => runTask('刷新 DB 中', refreshDetail)}>
                  刷新
                </Button>
                <Button icon={Database} variant="secondary" disabled={!selectedDbId} onClick={() => runTask('构建索引中', buildIndex)}>
                  构建索引
                </Button>
              </>
            }
          >
            {selectedDb ? (
              <div className="db-summary">
                <div>
                  <span>Collection</span>
                  <strong>{selectedDb.collection_name}</strong>
                </div>
                <div>
                  <span>索引</span>
                  <StatusPill status={detail?.index_status || selectedDb.index_status} />
                </div>
                <div>
                  <span>来源</span>
                  <strong>{detail?.sources?.length || selectedDb.source_count || 0}</strong>
                </div>
                <div>
                  <span>Chunks</span>
                  <strong>{selectedDb.chunk_count || detail?.chunks?.length || 0}</strong>
                </div>
              </div>
            ) : (
              <EmptyState title="未选择 DB" body="请返回选择已有知识库，或新建一个 DB。" />
            )}
            {detail?.index_error ? <p className="error-text">{detail.index_error}</p> : null}
          </Panel>

          <Panel
            title={
              <span className="title-with-help">
                添加来源
                <HelpDot text={supportedText} />
              </span>
            }
            actions={
              <>
                <Button icon={Plus} variant="secondary" onClick={() => setRows((current) => [...current, newSourceRow('file')])}>
                  File
                </Button>
                <Button icon={Plus} variant="secondary" onClick={() => setRows((current) => [...current, newSourceRow('url')])}>
                  URL
                </Button>
              </>
            }
          >
            <div className="chunk-bar">
              <Field label="Chunk size">
                <input
                  type="number"
                  min="100"
                  value={chunk.chunk_size}
                  onChange={(event) => setChunk((current) => ({ ...current, chunk_size: Number(event.target.value) }))}
                />
              </Field>
              <Field label="Overlap">
                <input
                  type="number"
                  min="0"
                  value={chunk.chunk_overlap}
                  onChange={(event) => setChunk((current) => ({ ...current, chunk_overlap: Number(event.target.value) }))}
                />
              </Field>
            </div>

            <div className="source-list">
              {rows.map((row) => (
                <div className="source-row" key={row.id}>
                  <div className="source-row-head">
                    <div className="segmented compact">
                      <button className={row.type === 'file' ? 'active' : ''} onClick={() => updateRow(row.id, { type: 'file', url: '' })}>
                        File
                      </button>
                      <button className={row.type === 'url' ? 'active' : ''} onClick={() => updateRow(row.id, { type: 'url', file: null })}>
                        URL
                      </button>
                    </div>
                    <IconButton label="移除来源" icon={Trash2} onClick={() => removeRow(row.id)} />
                  </div>
                  {row.type === 'file' ? (
                    <Field label="File">
                      <input type="file" onChange={(event) => updateRow(row.id, { file: event.target.files?.[0] || null })} />
                    </Field>
                  ) : (
                    <Field label="URL">
                      <div className="input-with-icon">
                        <Link2 size={16} />
                        <input
                          value={row.url}
                          onChange={(event) => updateRow(row.id, { url: event.target.value })}
                          placeholder="https://example.com/doc"
                        />
                      </div>
                    </Field>
                  )}
                </div>
              ))}
            </div>

            <Button
              icon={Upload}
              disabled={!selectedDbId || rows.every((row) => (row.type === 'file' ? !row.file : !row.url.trim()))}
              onClick={() => runTask('导入来源中', importSources)}
            >
              导入到当前 DB
            </Button>
          </Panel>

          <div className="detail-grid">
            <Panel title="来源">
              {detail?.sources?.length ? (
                <div className="table-list">
                  {detail.sources.map((source) => (
                    <div className="table-row" key={source.id}>
                      <span>
                        <strong>{source.name}</strong>
                        <small>{source.source_type}</small>
                      </span>
                      <StatusPill status={source.status} />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="暂无来源" body="向当前 DB 添加一个 File 或 URL。" />
              )}
            </Panel>

            <Panel title="Chunk 预览">
              {detail?.chunks?.length ? (
                <div className="chunk-list">
                  {detail.chunks.slice(0, 8).map((item) => (
                    <p className="chunk-preview" key={item.id}>{item.content}</p>
                  ))}
                </div>
              ) : (
                <EmptyState title="暂无 chunks" body="导入来源后会生成 chunks。" />
              )}
            </Panel>
          </div>
        </div>
      </div>
    );
  }

  if (viewMode === 'query-entry') {
    return (
      <div className="data-section-shell">
        <DataBackHeader title="评测集" subtitle="选择已有 query-only 评测集，或基于知识库生成新的 Query 集。" onBack={backToLanding} />
        <div className="data-entry-layout">
          <Panel title="加载已有评测集">
            {remote.querySets.length ? (
              <div className="card-list">
                {remote.querySets.map((set) => (
                  <button className="graph-entry-card" key={set.id} onClick={() => openQuerySet(set.id)}>
                    <span>
                      <strong>{set.name}</strong>
                      <small>{dbName(set.knowledge_base_id)} · {set.queries.length} 个 queries</small>
                    </span>
                    <StatusPill status="ready" />
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无评测集" body="从右侧新建一个 Query 集。" />
            )}
          </Panel>

          <Panel title="新建评测集">
            <p className="muted-copy">选择知识库 DB，输入 3-5 个示例 Query，模型会按当前知识库内容和风格生成 query-only 评测集。</p>
            <Button icon={WandSparkles} disabled={!remote.knowledgeBases.length} onClick={startNewQuerySet}>
              新建 Query 集
            </Button>
            {!remote.knowledgeBases.length ? (
              <p className="error-text">请先创建知识库并导入来源。</p>
            ) : null}
          </Panel>
        </div>
      </div>
    );
  }

  if (viewMode === 'query-create') {
    return (
      <div className="data-section-shell">
        <DataBackHeader title="新建评测集" subtitle="基于知识库内容和示例 Query 风格生成。" onBack={() => setViewMode('query-entry')} />
        <div className="two-column">
          <Panel title="生成 Query 集">
            <Field label="知识库 DB">
              <select value={queryDbId} onChange={(event) => setQueryDbId(event.target.value)}>
                <option value="">选择 DB</option>
                {remote.knowledgeBases.map((db) => (
                  <option key={db.id} value={db.id}>{db.name}</option>
                ))}
              </select>
            </Field>
            <Field label="名称">
              <input value={queryName} onChange={(event) => setQueryName(event.target.value)} />
            </Field>
            <Field label="示例 Query" help="3 到 5 行">
              <textarea value={queryExamples} onChange={(event) => setQueryExamples(event.target.value)} rows={8} />
            </Field>
            <Field label="目标数量">
              <input type="number" min="1" max="500" value={queryTargetCount} onChange={(event) => setQueryTargetCount(Number(event.target.value))} />
            </Field>
            <Button icon={WandSparkles} disabled={!queryDbId} onClick={() => runTask('生成 Query 中', generateQuerySet)}>
              生成
            </Button>
          </Panel>

          <Panel title="当前 DB 的评测集">
            {querySetsForDb.length ? (
              <div className="card-list">
                {querySetsForDb.map((set) => (
                  <article className="card-item" key={set.id}>
                    <strong>{set.name}</strong>
                    <span>{set.queries.length} 个 queries · 目标 {set.target_count}</span>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无评测集" body="生成后会出现在这里。" />
            )}
          </Panel>
        </div>
      </div>
    );
  }

  return (
    <div className="data-section-shell">
      <DataBackHeader title={selectedQuerySet?.name || '评测集详情'} subtitle={selectedQuerySet ? `${dbName(selectedQuerySet.knowledge_base_id)} · ${selectedQuerySet.queries.length} 个 queries` : '未选择评测集'} onBack={() => setViewMode('query-entry')} />
      <div className="two-column">
        <Panel title="评测集概览">
          {selectedQuerySet ? (
            <div className="db-summary">
              <div>
                <span>知识库 DB</span>
                <strong>{dbName(selectedQuerySet.knowledge_base_id)}</strong>
              </div>
              <div>
                <span>Queries</span>
                <strong>{selectedQuerySet.queries.length}</strong>
              </div>
              <div>
                <span>目标数量</span>
                <strong>{selectedQuerySet.target_count}</strong>
              </div>
              <div>
                <span>创建时间</span>
                <strong>{selectedQuerySet.created_at}</strong>
              </div>
            </div>
          ) : (
            <EmptyState title="未选择评测集" body="请返回列表选择已有评测集。" />
          )}
        </Panel>

        <Panel title="Query 预览">
          {selectedQuerySet?.queries?.length ? (
            <ol className="query-list roomy">
              {selectedQuerySet.queries.map((query) => <li key={query}>{query}</li>)}
            </ol>
          ) : (
            <EmptyState title="暂无 Query" body="这个评测集没有 query 数据。" />
          )}
        </Panel>
      </div>
    </div>
  );
}

function DataBackHeader({ title, subtitle, onBack }) {
  return (
    <div className="editor-header">
      <Button icon={ArrowLeft} variant="secondary" onClick={onBack}>
        返回
      </Button>
      <div>
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
    </div>
  );
}
