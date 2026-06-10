import { useEffect, useState } from 'react';
import { Plus, RefreshCw, Save, X } from 'lucide-react';
import { api } from '../api.js';
import { Button, Field, IconButton, Panel } from '../components/ui.jsx';

const defaultRoles = {
  embedding: { provider: 'qwen', model_name: 'text-embedding-v4' },
  answer: { provider: 'qwen', model_name: 'qwen3.7-plus', temperature: 0.2, max_tokens: 1024 },
  judge: { provider: 'qwen', model_name: 'qwen3.7-plus', temperature: 0, max_tokens: 1024 },
};

export function ConfigPage({ runTask }) {
  const [providers, setProviders] = useState([]);
  const [roles, setRoles] = useState(defaultRoles);
  const [chunk, setChunk] = useState({ chunk_size: 900, chunk_overlap: 120 });

  useEffect(() => {
    loadConfig().catch(() => {});
  }, []);

  async function loadConfig() {
    const config = await api.getConfig();
    setProviders(
      Object.entries(config.providers || {}).map(([key, value]) => ({
        key,
        base_url: value.base_url || '',
        api_key_env: value.api_key_env || '',
        default_model_name: value.default_model_name || '',
      })),
    );
    setRoles(config.roles || defaultRoles);
    setChunk(config.chunk || chunk);
  }

  function updateProvider(index, patch) {
    setProviders((rows) => rows.map((row, idx) => (idx === index ? { ...row, ...patch } : row)));
  }

  function addProvider() {
    setProviders((rows) => [
      ...rows,
      {
        key: `provider_${rows.length + 1}`,
        base_url: '',
        api_key_env: '',
        default_model_name: '',
      },
    ]);
  }

  function removeProvider(index) {
    setProviders((rows) => rows.filter((_, idx) => idx !== index));
  }

  function updateRole(role, patch) {
    setRoles((current) => ({ ...current, [role]: { ...(current[role] || {}), ...patch } }));
  }

  async function saveConfig() {
    const providerMap = Object.fromEntries(
      providers
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
    await api.updateConfig({
      providers: providerMap,
      roles,
      chunk: {
        chunk_size: Number(chunk.chunk_size),
        chunk_overlap: Number(chunk.chunk_overlap),
      },
    });
    await loadConfig();
  }

  const providerOptions = providers.map((provider) => provider.key).filter(Boolean);

  return (
    <div className="config-layout">
      <Panel title="Provider 配置" actions={<Button icon={Plus} variant="secondary" onClick={addProvider}>新增 Provider</Button>}>
        <div className="provider-list">
          {providers.map((provider, index) => (
            <div className="provider-row" key={`${provider.key}-${index}`}>
              <div className="provider-row-head">
                <strong>{provider.key || 'provider'}</strong>
                <IconButton label="删除 Provider" icon={X} onClick={() => removeProvider(index)} />
              </div>
              <div className="provider-grid">
                <Field label="Key">
                  <input value={provider.key} onChange={(event) => updateProvider(index, { key: event.target.value })} />
                </Field>
                <Field label="Base URL">
                  <input value={provider.base_url} onChange={(event) => updateProvider(index, { base_url: event.target.value })} />
                </Field>
                <Field label="API key env">
                  <input value={provider.api_key_env} onChange={(event) => updateProvider(index, { api_key_env: event.target.value })} />
                </Field>
                <Field label="默认模型">
                  <input value={provider.default_model_name} onChange={(event) => updateProvider(index, { default_model_name: event.target.value })} />
                </Field>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="默认模型">
        <RoleEditor
          title="Embedding 模型"
          role={roles.embedding || {}}
          providerOptions={providerOptions}
          onChange={(patch) => updateRole('embedding', patch)}
        />
        <RoleEditor
          title="Answer 模型"
          role={roles.answer || {}}
          providerOptions={providerOptions}
          onChange={(patch) => updateRole('answer', patch)}
          showGenerationParams
        />
        <RoleEditor
          title="Judge 模型"
          role={roles.judge || {}}
          providerOptions={providerOptions}
          onChange={(patch) => updateRole('judge', patch)}
          showGenerationParams
        />
      </Panel>

      <Panel
        title="默认 Chunk 参数"
        actions={
          <>
            <Button icon={RefreshCw} variant="secondary" onClick={() => runTask('加载配置中', loadConfig)}>
              重新加载
            </Button>
            <Button icon={Save} onClick={() => runTask('保存配置中', saveConfig)}>
              保存配置
            </Button>
          </>
        }
      >
        <div className="field-grid">
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
      </Panel>
    </div>
  );
}

function RoleEditor({ title, role, providerOptions, onChange, showGenerationParams = false }) {
  return (
    <div className="role-editor">
      <h3>{title}</h3>
      <div className="field-grid">
        <Field label="Provider">
          <select value={role.provider || ''} onChange={(event) => onChange({ provider: event.target.value })}>
            <option value="">选择 Provider</option>
            {providerOptions.map((provider) => (
              <option key={provider} value={provider}>{provider}</option>
            ))}
          </select>
        </Field>
        <Field label="Model">
          <input value={role.model_name || role.model || ''} onChange={(event) => onChange({ model_name: event.target.value })} />
        </Field>
      </div>
      {showGenerationParams ? (
        <div className="field-grid">
          <Field label="Temperature">
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={role.temperature ?? 0}
              onChange={(event) => onChange({ temperature: Number(event.target.value) })}
            />
          </Field>
          <Field label="Max tokens">
            <input
              type="number"
              min="1"
              value={role.max_tokens ?? 1024}
              onChange={(event) => onChange({ max_tokens: Number(event.target.value) })}
            />
          </Field>
        </div>
      ) : null}
    </div>
  );
}
