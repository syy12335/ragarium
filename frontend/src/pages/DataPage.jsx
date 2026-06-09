import { useEffect, useMemo, useState } from 'react';
import { Database, FilePlus2, Link2, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api } from '../api.js';
import { Button, EmptyState, Field, HelpDot, IconButton, Panel, StatusPill } from '../components/ui.jsx';

const supportedText = '支持 .txt、.md、.html、.pdf、.docx 文件和单页 URL；同一批来源会一起切割并保存到当前 name-db。';

function newSourceRow(type = 'file') {
  return {
    id: `${Date.now()}-${Math.random()}`,
    type,
    file: null,
    url: '',
  };
}

export function DataPage({ remote, runTask }) {
  const [selectedDbId, setSelectedDbId] = useState('');
  const [newDbName, setNewDbName] = useState('');
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([newSourceRow('file')]);
  const [chunk, setChunk] = useState({ chunk_size: 900, chunk_overlap: 120 });

  useEffect(() => {
    api.getConfig().then((config) => setChunk(config.chunk || chunk)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedDbId && remote.knowledgeBases.length) {
      setSelectedDbId(String(remote.knowledgeBases[0].id));
    }
  }, [selectedDbId, remote.knowledgeBases]);

  useEffect(() => {
    if (!selectedDbId) {
      setDetail(null);
      return;
    }
    api.getKnowledgeBase(selectedDbId).then(setDetail).catch(() => setDetail(null));
  }, [selectedDbId, remote.knowledgeBases]);

  const selectedDb = useMemo(
    () => remote.knowledgeBases.find((item) => String(item.id) === String(selectedDbId)),
    [remote.knowledgeBases, selectedDbId],
  );

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

  return (
    <div className="data-layout">
      <Panel title="知识库 DB" className="db-sidebar">
        <div className="create-row">
          <Field label="新建 DB">
            <input
              value={newDbName}
              onChange={(event) => setNewDbName(event.target.value)}
              placeholder="support-docs-db"
            />
          </Field>
          <Button icon={FilePlus2} onClick={() => runTask('创建 DB 中', createDb)}>
            创建
          </Button>
        </div>

        <div className="db-list">
          {remote.knowledgeBases.map((db) => (
            <button
              key={db.id}
              className={String(db.id) === String(selectedDbId) ? 'db-item active' : 'db-item'}
              onClick={() => setSelectedDbId(String(db.id))}
            >
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
      </Panel>

      <div className="data-main">
        <Panel
          title={selectedDb ? selectedDb.name : '请选择 DB'}
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
            <EmptyState title="未选择 DB" body="请先创建一个 name-db，或从列表中选择已有 DB。" />
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
