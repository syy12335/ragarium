import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Database,
  FilePlus2,
  Link2,
  ListChecks,
  Plus,
  Trash2,
  Upload,
  WandSparkles,
} from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, HelpDot, IconButton, Panel, StatusPill } from '../components/ui.jsx';

const supportedText = '支持 .txt、.md、.html、.pdf、.docx 文件和单页 URL；URL 会用独立浏览器打开原页面并提取可见正文，登录页、验证码页可能失败。同一批来源会一起切割并保存到当前知识库 DB。';
const defaultExamples = '如何配置这个产品？\n上传文档后怎么检索？\n评测结果怎么看？';

function newSourceRow() {
  return {
    id: `${Date.now()}-${Math.random()}`,
    file: null,
    url: '',
  };
}

export function DataPage({ remote, runTask, initialSection = 'landing', navigationKey = 0 }) {
  const [viewMode, setViewMode] = useState('landing');
  const [selectedDbId, setSelectedDbId] = useState('');
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([newSourceRow()]);
  const [chunk, setChunk] = useState({ chunk_size: 900, chunk_overlap: 120 });
  const [queryDbId, setQueryDbId] = useState('');
  const [queryExamples, setQueryExamples] = useState(defaultExamples);
  const [queryTargetCount, setQueryTargetCount] = useState(10);
  const [queryName, setQueryName] = useState('生成的 Query 集');
  const [selectedQuerySetId, setSelectedQuerySetId] = useState('');
  const [browserSessions, setBrowserSessions] = useState({});

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

  function nextName(prefix, items) {
    const names = new Set(items.map((item) => item.name));
    let index = items.length + 1;
    let name = `${prefix} ${index}`;
    while (names.has(name)) {
      index += 1;
      name = `${prefix} ${index}`;
    }
    return name;
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
    const created = await api.createKnowledgeBase(nextName('知识库', remote.knowledgeBases));
    setSelectedDbId(String(created.id));
    setDetail(await api.getKnowledgeBase(created.id));
    setViewMode('kb-detail');
    return created;
  }

  async function importSources() {
    if (!selectedDbId) {
      throw new Error('请先选择或创建 DB');
    }
    const readyRows = rows.filter((row) => row.file || row.url.trim());
    if (!readyRows.length) {
      throw new Error('请至少选择一个文件或粘贴一个 URL');
    }
    const options = {
      chunk_size: Number(chunk.chunk_size),
      chunk_overlap: Number(chunk.chunk_overlap),
    };
    let firstError = null;
    for (const row of readyRows) {
      try {
        if (row.file) {
          await api.uploadFile(selectedDbId, row.file, options);
        }
        if (row.url.trim()) {
          await api.importUrl(selectedDbId, row.url.trim(), options);
        }
      } catch (error) {
        firstError = firstError || error;
      }
    }
    setRows([newSourceRow()]);
    await refreshDetail();
    if (firstError) {
      throw firstError;
    }
  }

  async function buildIndex() {
    if (!selectedDbId) {
      throw new Error('请先选择或创建 DB');
    }
    const result = await api.buildIndex(selectedDbId, true);
    await refreshDetail();
    return result;
  }

  async function deleteSource(source) {
    if (!selectedDbId) {
      throw new Error('请先选择 DB');
    }
    const ok = window.confirm(`删除来源「${source.name}」？对应 chunks 也会一起删除。`);
    if (!ok) {
      return null;
    }
    const result = await api.deleteSource(selectedDbId, source.id);
    await refreshDetail();
    return result;
  }

  async function openBrowserForSource(source) {
    if (!selectedDbId) {
      throw new Error('请先选择 DB');
    }
    const result = await api.openSourceBrowserSession(selectedDbId, source.id);
    setBrowserSessions((current) => ({ ...current, [source.id]: result.session_id }));
    return result;
  }

  async function extractBrowserForSource(source) {
    const sessionId = browserSessions[source.id];
    if (!sessionId) {
      throw new Error('请先打开浏览器处理这个 URL');
    }
    const result = await api.extractBrowserSession(sessionId);
    setBrowserSessions((current) => {
      const next = { ...current };
      delete next[source.id];
      return next;
    });
    await refreshDetail();
    return result;
  }

  async function closeBrowserForSource(source) {
    const sessionId = browserSessions[source.id];
    if (!sessionId) {
      return null;
    }
    const result = await api.closeBrowserSession(sessionId);
    setBrowserSessions((current) => {
      const next = { ...current };
      delete next[source.id];
      return next;
    });
    return result;
  }

  function startNewQuerySet() {
    setQueryDbId(remote.knowledgeBases[0] ? String(remote.knowledgeBases[0].id) : '');
    setQueryExamples(defaultExamples);
    setQueryTargetCount(10);
    setQueryName(nextName('评测集', remote.querySets));
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
      name: queryName.trim() || nextName('评测集', remote.querySets),
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
            <div className="quick-create-card">
              <Database size={24} />
              <div>
                <strong>直接创建一个空知识库</strong>
                <span>系统会自动命名；进入后再导入 File 或 URL。后续在 Workflow、Query 生成和评测里按这个 DB 选择数据来源。</span>
              </div>
            </div>
            <Button icon={FilePlus2} onClick={() => runTask('创建 DB 中', createDb)}>
              创建知识库
            </Button>
          </Panel>
        </div>
      </div>
    );
  }

  if (viewMode === 'kb-detail') {
    return (
      <div className="data-section-shell">
        <div className="minimal-back-row">
          <Button icon={ArrowLeft} variant="secondary" onClick={() => setViewMode('kb-entry')}>
            返回知识库
          </Button>
        </div>
        <div className="data-main">
          <Panel
            title={
              <span className="title-with-help">
                导入资料到 {selectedDb?.name || '当前知识库'}
                <HelpDot text={supportedText} />
              </span>
            }
            actions={
              detail?.sources?.length ? (
                <Button icon={Database} variant="secondary" disabled={!selectedDbId} onClick={() => runTask('构建索引中', buildIndex)}>
                  构建索引
                </Button>
              ) : null
            }
          >
            {detail?.index_error ? <p className="error-text">{detail.index_error}</p> : null}

            <div className="source-list">
              {rows.map((row, index) => (
                <div className="source-input-group" key={row.id}>
                  {rows.length > 1 ? (
                    <div className="source-row-head compact-head">
                      <strong>来源 {index + 1}</strong>
                      <IconButton className="danger" label="移除来源" icon={Trash2} onClick={() => removeRow(row.id)} />
                    </div>
                  ) : null}
                  <Field label="资料来源" help="选择本地文件，或者粘贴网页 URL；填一个即可。多个来源请点“添加来源”。">
                    <div className="source-composer">
                      <label className={row.file ? 'file-picker has-file' : 'file-picker'}>
                        <FilePlus2 size={18} />
                        <span>
                          <strong>{row.file ? row.file.name : '选择文件'}</strong>
                          <small>PDF / Word / Markdown / HTML / TXT</small>
                        </span>
                        <input type="file" onChange={(event) => updateRow(row.id, { file: event.target.files?.[0] || null })} />
                      </label>
                      <div className="source-divider"><span>或</span></div>
                      <div className="input-with-icon source-url-input">
                        <Link2 size={16} />
                        <input
                          value={row.url}
                          onChange={(event) => updateRow(row.id, { url: event.target.value })}
                          placeholder="https://example.com/doc"
                        />
                      </div>
                    </div>
                  </Field>
                </div>
              ))}
            </div>

            <div className="source-add-row">
              <Button icon={Plus} variant="secondary" onClick={() => setRows((current) => [...current, newSourceRow()])}>
                添加来源
              </Button>
            </div>

            <details className="advanced-settings">
              <summary>高级设置</summary>
              <div className="chunk-bar">
                <Field label="Chunk size" help="控制每个切片的大致长度；切片越大，上下文更完整，但检索和评测成本更高。">
                  <input
                    type="number"
                    min="100"
                    value={chunk.chunk_size}
                    onChange={(event) => setChunk((current) => ({ ...current, chunk_size: Number(event.target.value) }))}
                  />
                </Field>
                <Field label="Overlap" help="控制相邻切片重复多少内容；适当重叠能减少句子被切断导致的检索丢失。">
                  <input
                    type="number"
                    min="0"
                    value={chunk.chunk_overlap}
                    onChange={(event) => setChunk((current) => ({ ...current, chunk_overlap: Number(event.target.value) }))}
                  />
                </Field>
              </div>
            </details>

            <Button
              icon={Upload}
              disabled={!selectedDbId || rows.every((row) => !row.file && !row.url.trim())}
              onClick={() => runTask('导入来源中', importSources)}
            >
              开始导入
            </Button>
          </Panel>

          {(detail?.sources?.length || detail?.chunks?.length) ? (
            <div className="detail-grid">
            <Panel title="来源">
              {detail?.sources?.length ? (
                <div className="table-list">
                  {detail.sources.map((source) => {
                    const sessionId = browserSessions[source.id];
                    const needsBrowser = source.error_code === 'browser_challenge';
                    return (
                      <div className="table-row" key={source.id}>
                        <span>
                          <strong>{source.name}</strong>
                          <small>{source.source_type}</small>
                          {source.error ? <small className="source-error">{source.error}</small> : null}
                          {needsBrowser && !sessionId ? (
                            <small className="source-recovery-hint">
                              页面需要验证码、登录或人工确认，可以打开独立浏览器处理。
                            </small>
                          ) : null}
                          {sessionId ? (
                            <small className="source-recovery-hint">
                              等待你在浏览器中完成页面访问，完成后点击“提取正文”。
                            </small>
                          ) : null}
                        </span>
                        <div className="row-actions">
                          {needsBrowser ? <span className="status-pill status-stale">需要浏览器处理</span> : <StatusPill status={source.status} />}
                          {needsBrowser && !sessionId ? (
                            <Button variant="secondary" onClick={() => runTask('打开浏览器中', () => openBrowserForSource(source))}>
                              打开浏览器处理
                            </Button>
                          ) : null}
                          {sessionId ? (
                            <>
                              <Button onClick={() => runTask('提取正文中', () => extractBrowserForSource(source))}>
                                提取正文
                              </Button>
                              <Button variant="secondary" onClick={() => runTask('关闭浏览器中', () => closeBrowserForSource(source))}>
                                关闭浏览器
                              </Button>
                            </>
                          ) : null}
                          <IconButton className="danger" label="删除来源" icon={Trash2} onClick={() => runTask('删除来源中', () => deleteSource(source))} />
                        </div>
                      </div>
                    );
                  })}
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
          ) : null}
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
            <Field label="知识库 DB" help="决定模型从哪个知识库抽样内容；生成的 Query 会围绕这个 DB 的 chunks。">
              <select value={queryDbId} onChange={(event) => setQueryDbId(event.target.value)}>
                <option value="">选择 DB</option>
                {remote.knowledgeBases.map((db) => (
                  <option key={db.id} value={db.id}>{db.name}</option>
                ))}
              </select>
            </Field>
            <Field label="示例 Query" help="每行一个，3 到 5 行；模型会学习这些问题的语气、长短和关注点来扩写更多 Query。">
              <textarea value={queryExamples} onChange={(event) => setQueryExamples(event.target.value)} rows={8} />
            </Field>
            <details className="advanced-settings">
              <summary>高级设置</summary>
              <Field label="名称" help="用于在评测页和 Workflow 里识别这批 Query；不填也会自动命名。">
                <input value={queryName} onChange={(event) => setQueryName(event.target.value)} />
              </Field>
              <Field label="目标数量" help="要生成多少条 Query；数量越多覆盖面越广，但后续生成答案和评测会更慢。">
                <input type="number" min="1" max="500" value={queryTargetCount} onChange={(event) => setQueryTargetCount(Number(event.target.value))} />
              </Field>
            </details>
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
