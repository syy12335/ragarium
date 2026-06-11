import { useEffect, useState } from 'react';
import { CheckCircle2, Plus, Save, Settings2, ShieldAlert, X } from 'lucide-react';
import { api } from '../api.js';
import { Button, Field, IconButton } from '../components/ui.jsx';

const providerPresets = [
  {
    id: 'qwen',
    title: 'qwen',
    description: '通义千问 DashScope 兼容接口',
    provider: {
      key: 'qwen',
      base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      api_key_env: 'API_KEY_QWEN',
      default_model_name: 'qwen3.7-plus',
    },
  },
  {
    id: 'openai',
    title: 'openai',
    description: 'OpenAI 官方兼容接口',
    provider: {
      key: 'openai',
      base_url: 'https://api.openai.com/v1',
      api_key_env: 'OPENAI_API_KEY',
      default_model_name: 'gpt-4.1-mini',
    },
  },
  {
    id: 'deepseek',
    title: 'deepseek',
    description: 'DeepSeek Chat 兼容接口',
    provider: {
      key: 'deepseek',
      base_url: 'https://api.deepseek.com/v1',
      api_key_env: 'DEEPSEEK_API_KEY',
      default_model_name: 'deepseek-chat',
    },
  },
  {
    id: 'siliconflow',
    title: 'siliconflow',
    description: 'SiliconFlow 聚合模型接口',
    provider: {
      key: 'siliconflow',
      base_url: 'https://api.siliconflow.cn/v1',
      api_key_env: 'SILICONFLOW_API_KEY',
      default_model_name: 'Qwen/Qwen3-32B',
    },
  },
  {
    id: 'custom',
    title: '自定义 Base URL',
    description: '填写任意 OpenAI 兼容网关',
    provider: null,
  },
];

const defaultRoles = {
  embedding: { provider: 'qwen', model_name: 'text-embedding-v4' },
  answer: { provider: 'qwen', model_name: 'qwen3.7-plus', temperature: 0.2, max_tokens: 1024 },
  judge: { provider: 'qwen', model_name: 'qwen3.7-plus', temperature: 0, max_tokens: 1024 },
};

const roleMeta = {
  embedding: {
    title: 'Embedding',
    subtitle: '把文本 Chunk 转成向量，决定后续检索质量。',
  },
  answer: {
    title: 'Answer',
    subtitle: 'RAG 回答模型，负责基于检索上下文生成答案。',
  },
  judge: {
    title: 'Judge',
    subtitle: 'RAGAS 评测模型，负责给答案和上下文打分。',
  },
};

function providerRow(key, value = {}, index = 0) {
  return {
    rowId: `provider_${index}_${key || 'new'}`,
    key,
    base_url: value.base_url || '',
    api_key_env: value.api_key_env || '',
    default_model_name: value.default_model_name || '',
    api_key: '',
  };
}

function uniqueProviderKey(baseKey, providers, editingRowId = null) {
  const existing = new Set(
    providers
      .filter((provider) => provider.rowId !== editingRowId)
      .map((provider) => provider.key.trim())
      .filter(Boolean),
  );
  if (!existing.has(baseKey)) {
    return baseKey;
  }
  let index = 2;
  while (existing.has(`${baseKey}_${index}`)) {
    index += 1;
  }
  return `${baseKey}_${index}`;
}

function newCustomProvider(index) {
  return {
    key: `provider_${index + 1}`,
    base_url: '',
    api_key_env: `PROVIDER_${index + 1}_API_KEY`,
    default_model_name: '',
  };
}

function ensureProviders(configProviders = {}) {
  const entries = Object.entries(configProviders);
  if (!entries.length) {
    return [providerRow('qwen', providerPresets[0].provider, 0)];
  }
  return entries.map(([key, value], index) => providerRow(key, value, index));
}

export function ConfigPage({ runTask, intent = null }) {
  const [providers, setProviders] = useState([]);
  const [roles, setRoles] = useState(defaultRoles);
  const [chunk, setChunk] = useState({ chunk_size: 900, chunk_overlap: 120 });
  const [envStatus, setEnvStatus] = useState({});
  const [showPresetModal, setShowPresetModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState(null);
  const [editingRole, setEditingRole] = useState(null);
  const [editingChunk, setEditingChunk] = useState(null);
  const [handledIntentKey, setHandledIntentKey] = useState('');

  useEffect(() => {
    loadConfig().catch(() => {});
  }, []);

  useEffect(() => {
    if (!intent || intent.type !== 'openProvider' || !providers.length) {
      return;
    }
    const key = `${intent.key || ''}:${intent.type}:${intent.providerKey || ''}`;
    if (handledIntentKey === key) {
      return;
    }
    const provider = providers.find((item) => item.key === intent.providerKey) || providers[0];
    editProvider(provider);
    setHandledIntentKey(key);
  }, [intent, providers, handledIntentKey]);

  async function loadConfig() {
    const config = await api.getConfig();
    setProviders(ensureProviders(config.providers || {}));
    setRoles(config.roles || defaultRoles);
    setChunk(config.chunk || chunk);
    setEnvStatus(config.env_status || {});
    setShowPresetModal(false);
    setEditingProvider(null);
    setEditingRole(null);
    setEditingChunk(null);
  }

  function openAddProvider() {
    setShowPresetModal(true);
  }

  function selectPreset(preset) {
    const draft = preset.provider ? { ...preset.provider } : newCustomProvider(providers.length);
    draft.key = uniqueProviderKey(draft.key, providers);
    setShowPresetModal(false);
    setEditingProvider({
      mode: 'create',
      rowId: `provider_new_${Date.now()}`,
      draft,
    });
  }

  function editProvider(provider) {
    setEditingProvider({
      mode: 'edit',
      rowId: provider.rowId,
      draft: {
        key: provider.key,
        base_url: provider.base_url,
        api_key_env: provider.api_key_env,
        default_model_name: provider.default_model_name,
        api_key: provider.api_key || '',
      },
    });
  }

  function updateEditingProvider(patch) {
    setEditingProvider((current) => current ? { ...current, draft: { ...current.draft, ...patch } } : current);
  }

  function buildProviderMap(providerRows) {
    return Object.fromEntries(
      providerRows
        .filter((provider) => provider.key.trim())
        .map((provider) => [
          provider.key.trim(),
          {
            base_url: provider.base_url,
            api_key_env: provider.api_key_env,
            default_model_name: provider.default_model_name,
          },
        ]),
    );
  }

  async function persistConfig({ providerRows = providers, roleConfig = roles, chunkConfig = chunk, apiKeys = {} } = {}) {
    const providerMap = buildProviderMap(providerRows);
    if (!Object.keys(providerMap).length) {
      throw new Error('至少需要保留一个 Provider');
    }
    await api.updateConfig({
      providers: providerMap,
      roles: roleConfig,
      chunk: {
        chunk_size: Number(chunkConfig.chunk_size),
        chunk_overlap: Number(chunkConfig.chunk_overlap),
      },
      api_keys: apiKeys,
    });
    await loadConfig();
  }

  async function saveEditingProvider() {
    if (!editingProvider) {
      return;
    }
    const row = {
      rowId: editingProvider.rowId,
      key: editingProvider.draft.key.trim(),
      base_url: editingProvider.draft.base_url,
      api_key_env: editingProvider.draft.api_key_env,
      default_model_name: editingProvider.draft.default_model_name,
      api_key: editingProvider.draft.api_key || '',
    };
    if (!row.key) {
      throw new Error('请填写 Provider 名称');
    }
    const duplicated = providers.some((provider) => provider.rowId !== row.rowId && provider.key.trim() === row.key);
    if (duplicated) {
      throw new Error('Provider 名称已存在');
    }
    const nextProviders = editingProvider.mode === 'create'
      ? [...providers, row]
      : providers.map((provider) => (provider.rowId === editingProvider.rowId ? row : provider));
    const apiKeys = row.api_key.trim() ? { [row.key]: row.api_key.trim() } : {};
    await persistConfig({ providerRows: nextProviders, apiKeys });
  }

  async function removeProvider(index) {
    if (providers.length <= 1) {
      return;
    }
    const removedProvider = providers[index];
    const nextProviders = providers.filter((_, idx) => idx !== index);
    const fallbackProvider = nextProviders[0]?.key || '';
    const nextRoles = Object.fromEntries(
      Object.entries(roles).map(([roleKey, roleValue]) => [
        roleKey,
        {
          ...roleValue,
          provider: roleValue?.provider === removedProvider.key ? fallbackProvider : roleValue?.provider,
        },
      ]),
    );
    await persistConfig({ providerRows: nextProviders, roleConfig: nextRoles });
  }

  function openRoleModal(kind) {
    setEditingRole({
      kind,
      draft: { ...defaultRoles[kind], ...(roles[kind] || {}) },
    });
  }

  function updateEditingRole(patch) {
    setEditingRole((current) => current ? ({
      ...current,
      draft: {
        ...(current.draft || {}),
        ...patch,
      },
    }) : current);
  }

  async function saveEditingRole() {
    if (!editingRole) {
      return;
    }
    await persistConfig({
      roleConfig: {
        ...roles,
        [editingRole.kind]: editingRole.draft,
      },
    });
  }

  function openChunkModal() {
    setEditingChunk({ ...chunk });
  }

  function updateEditingChunk(patch) {
    setEditingChunk((current) => ({ ...(current || chunk), ...patch }));
  }

  async function saveEditingChunk() {
    if (!editingChunk) {
      return;
    }
    await persistConfig({ chunkConfig: editingChunk });
  }

  const providerOptions = providers.map((provider) => provider.key.trim()).filter(Boolean);

  return (
    <div className="config-simple-layout">
      <section className="settings-section">
        <div className="settings-section-head">
          <div>
            <strong>Provider 配置</strong>
            <span>管理模型服务地址和 API Key。</span>
          </div>
          <Button icon={Plus} variant="secondary" onClick={openAddProvider}>新增配置</Button>
        </div>
        <div className="provider-config-list">
          {providers.map((provider, index) => (
            <ProviderConfigCard
              key={provider.rowId}
              provider={provider}
              envStatus={envStatus[provider.key]}
              canDelete={providers.length > 1}
              onEdit={() => editProvider(provider)}
              onRemove={() => runTask('删除 Provider 中', () => removeProvider(index))}
            />
          ))}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-head">
          <div>
            <strong>默认模型</strong>
            <span>每个模型右侧都有独立配置入口。</span>
          </div>
        </div>
        <div className="model-summary-list">
          {Object.keys(roleMeta).map((kind) => (
            <ModelRoleSummary
              key={kind}
              kind={kind}
              role={roles[kind] || {}}
              onEdit={() => openRoleModal(kind)}
            />
          ))}
        </div>
      </section>

      <section className="advanced-params-row">
        <div className="advanced-params-copy">
          <strong>高级参数</strong>
          <span>默认 Chunk 参数用于新导入资料的切片规则。</span>
        </div>
        <div className="advanced-params-values">
          <span>
            <small>Chunk size</small>
            <strong>{chunk.chunk_size}</strong>
          </span>
          <span>
            <small>Overlap</small>
            <strong>{chunk.chunk_overlap}</strong>
          </span>
        </div>
        <IconButton label="配置高级参数" icon={Settings2} onClick={openChunkModal} />
      </section>

      {showPresetModal ? (
        <ProviderPresetModal onClose={() => setShowPresetModal(false)} onSelect={selectPreset} />
      ) : null}
      {editingProvider ? (
        <ProviderEditModal
          provider={editingProvider.draft}
          envStatus={editingProvider.mode === 'edit' ? envStatus[editingProvider.draft.key] : null}
          mode={editingProvider.mode}
          onChange={updateEditingProvider}
          onSave={() => runTask('保存 Provider 中', saveEditingProvider)}
          onClose={() => setEditingProvider(null)}
        />
      ) : null}
      {editingRole ? (
        <RoleConfigModal
          kind={editingRole.kind}
          role={editingRole.draft}
          providerOptions={providerOptions}
          onChange={updateEditingRole}
          onSave={() => runTask('保存默认模型中', saveEditingRole)}
          onClose={() => setEditingRole(null)}
        />
      ) : null}
      {editingChunk ? (
        <ChunkConfigModal
          chunk={editingChunk}
          onChange={updateEditingChunk}
          onSave={() => runTask('保存 Chunk 参数中', saveEditingChunk)}
          onClose={() => setEditingChunk(null)}
        />
      ) : null}
    </div>
  );
}

function ModelRoleSummary({ kind, role, onEdit }) {
  const meta = roleMeta[kind];
  return (
    <div className="model-summary-row">
      <div className="model-summary-main">
        <strong>{meta.title}</strong>
        <span>{meta.subtitle}</span>
      </div>
      <div className="model-summary-meta">
        <small>{role.provider || '未选择 Provider'}</small>
        <strong>{role.model_name || role.model || '未配置模型'}</strong>
      </div>
      <IconButton label={`配置 ${meta.title}`} icon={Settings2} onClick={onEdit} />
    </div>
  );
}

function ProviderConfigCard({ provider, envStatus, canDelete, onEdit, onRemove }) {
  const configured = Boolean(envStatus?.configured);
  const pendingKey = Boolean(provider.api_key?.trim());
  return (
    <div className="provider-config-card">
      <div className="provider-summary">
        <div className="provider-title-block">
          <strong>{provider.key || '未命名 Provider'}</strong>
          <small>{provider.base_url || '还没有配置 Base URL'}</small>
        </div>
        <div className={configured || pendingKey ? 'provider-key-pill ready' : 'provider-key-pill missing'}>
          {configured || pendingKey ? <CheckCircle2 size={15} /> : <ShieldAlert size={15} />}
          <span>{configured ? 'Key 已保存' : pendingKey ? 'Key 待保存' : '未填写 Key'}</span>
        </div>
        <IconButton label="配置 Provider" icon={Settings2} onClick={onEdit} />
        {canDelete ? <IconButton className="danger" label="删除 Provider" icon={X} onClick={onRemove} /> : null}
      </div>
    </div>
  );
}

function ProviderPresetModal({ onClose, onSelect }) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal-panel provider-preset-modal" role="dialog" aria-modal="true" aria-label="新增 Provider">
        <div className="modal-head">
          <div>
            <h3>新增 Provider</h3>
            <p>选择常见厂商，或从自定义 Base URL 开始。</p>
          </div>
          <IconButton label="关闭" icon={X} onClick={onClose} />
        </div>
        <div className="preset-grid">
          {providerPresets.map((preset) => (
            <button className="preset-card" key={preset.id} type="button" onClick={() => onSelect(preset)}>
              <strong>{preset.title}</strong>
              <span>{preset.description}</span>
              <small>{preset.provider?.base_url || '手动填写 Base URL'}</small>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ProviderEditModal({ provider, envStatus, mode, onChange, onSave, onClose }) {
  const configured = Boolean(envStatus?.configured);
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal-panel provider-edit-modal" role="dialog" aria-modal="true" aria-label="Provider 配置">
        <div className="modal-head">
          <div>
            <h3>{mode === 'create' ? '配置新 Provider' : `配置 ${provider.key || 'Provider'}`}</h3>
            <p>填写模型服务地址和 API Key，保存后即可用于检索、回答和评测。</p>
          </div>
          <IconButton label="关闭" icon={X} onClick={onClose} />
        </div>
        <div className={configured ? 'api-key-status ready' : 'api-key-status missing'}>
          {configured ? <CheckCircle2 size={22} /> : <ShieldAlert size={22} />}
          <div>
            <strong>{configured ? 'API Key 已保存' : '还没有填写 API Key'}</strong>
            <p>{configured ? '如需更换 Key，请在下面重新填写；留空则保持不变。' : '请输入当前 Provider 的 API Key。'}</p>
          </div>
        </div>
        <div className="provider-edit-form">
          <Field label="Provider 名称" help="用于在默认模型里选择这组模型服务。">
            <input value={provider.key} onChange={(event) => onChange({ key: event.target.value })} />
          </Field>
          <Field label="Base URL" help="OpenAI 兼容接口地址；请求模型时会发到这个网关。">
            <input value={provider.base_url} onChange={(event) => onChange({ base_url: event.target.value })} />
          </Field>
          <Field label="API Key" help={configured ? '留空表示继续使用已保存的 Key。' : '粘贴该模型服务的 API Key。'}>
            <input
              type="password"
              autoComplete="off"
              placeholder={configured ? '已保存，留空不修改' : '粘贴 API Key'}
              value={provider.api_key || ''}
              onChange={(event) => onChange({ api_key: event.target.value })}
            />
          </Field>
          <Field label="默认模型" help="当某个角色没有单独指定模型时，会回退使用这里的模型。">
            <input value={provider.default_model_name} onChange={(event) => onChange({ default_model_name: event.target.value })} />
          </Field>
        </div>
        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button icon={Save} onClick={onSave}>保存</Button>
        </div>
      </div>
    </div>
  );
}

function RoleConfigModal({ kind, role, providerOptions, onChange, onSave, onClose }) {
  const meta = roleMeta[kind];
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal-panel model-config-modal" role="dialog" aria-modal="true" aria-label={`${meta.title} 配置`}>
        <div className="modal-head">
          <div>
            <h3>{meta.title} 配置</h3>
            <p>{meta.subtitle}</p>
          </div>
          <IconButton label="关闭" icon={X} onClick={onClose} />
        </div>
        <RoleEditorCard
          kind={kind}
          role={role || {}}
          providerOptions={providerOptions}
          onChange={onChange}
          showGenerationParams={kind === 'answer' || kind === 'judge'}
        />
        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button icon={Save} onClick={onSave}>保存</Button>
        </div>
      </div>
    </div>
  );
}

function RoleEditorCard({ kind, role, providerOptions, onChange, showGenerationParams = false }) {
  const meta = roleMeta[kind];
  return (
    <div className="model-edit-card">
      <div className="model-role-head">
        <div>
          <strong>{meta.title}</strong>
          <p>{meta.subtitle}</p>
        </div>
        <span>{role.provider || '未选择'}</span>
      </div>
      <Field label="Provider" help="前置配置：先选择这个角色调用哪个模型服务。">
        <select value={role.provider || ''} onChange={(event) => onChange({ provider: event.target.value })}>
          <option value="">选择 Provider</option>
          {providerOptions.map((provider) => (
            <option key={provider} value={provider}>{provider}</option>
          ))}
        </select>
      </Field>
      <Field label="Model" help="这个角色实际使用的模型名。">
        <input value={role.model_name || role.model || ''} onChange={(event) => onChange({ model_name: event.target.value })} />
      </Field>
      {showGenerationParams ? (
        <details className="role-advanced">
          <summary>高级参数</summary>
          <div className="field-grid">
            <Field label="Temperature" help="控制输出随机性；回答可略高，评测建议接近 0 保持稳定。">
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={role.temperature ?? 0}
                onChange={(event) => onChange({ temperature: Number(event.target.value) })}
              />
            </Field>
            <Field label="Max tokens" help="限制单次输出长度；太小可能截断答案或评分解释，太大成本更高。">
              <input
                type="number"
                min="1"
                value={role.max_tokens ?? 1024}
                onChange={(event) => onChange({ max_tokens: Number(event.target.value) })}
              />
            </Field>
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ChunkConfigModal({ chunk, onChange, onSave, onClose }) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal-panel chunk-config-modal" role="dialog" aria-modal="true" aria-label="Chunk 参数配置">
        <div className="modal-head">
          <div>
            <h3>默认 Chunk 参数</h3>
            <p>这些参数会作为新导入资料的默认切片规则。</p>
          </div>
          <IconButton label="关闭" icon={X} onClick={onClose} />
        </div>
        <div className="chunk-simple-grid">
          <Field label="Chunk size" help="每个 Chunk 的目标长度；越大上下文越完整，但检索成本更高。">
            <input
              type="number"
              min="100"
              value={chunk.chunk_size}
              onChange={(event) => onChange({ chunk_size: Number(event.target.value) })}
            />
          </Field>
          <Field label="Overlap" help="相邻 Chunk 重叠的长度；适当重叠可以减少边界信息丢失。">
            <input
              type="number"
              min="0"
              value={chunk.chunk_overlap}
              onChange={(event) => onChange({ chunk_overlap: Number(event.target.value) })}
            />
          </Field>
        </div>
        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button icon={Save} onClick={onSave}>保存</Button>
        </div>
      </div>
    </div>
  );
}
