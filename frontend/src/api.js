export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return payload;
}

export const api = {
  health: () => request('/api/health'),
  listKnowledgeBases: () => request('/api/knowledge-bases'),
  getKnowledgeBase: (id) => request(`/api/knowledge-bases/${id}`),
  createKnowledgeBase: (name) =>
    request('/api/knowledge-bases', { method: 'POST', body: JSON.stringify({ name }) }),
  getConfig: () => request('/api/config'),
  updateConfig: (payload) =>
    request('/api/config', { method: 'PUT', body: JSON.stringify(payload) }),
  uploadFile: (knowledgeBaseId, file, options = {}) => {
    const body = new FormData();
    body.append('file', file);
    if (options.chunk_size) {
      body.append('chunk_size', String(options.chunk_size));
    }
    if (options.chunk_overlap || options.chunk_overlap === 0) {
      body.append('chunk_overlap', String(options.chunk_overlap));
    }
    return request(`/api/knowledge-bases/${knowledgeBaseId}/files`, { method: 'POST', body });
  },
  importUrl: (knowledgeBaseId, url, options = {}) =>
    request(`/api/knowledge-bases/${knowledgeBaseId}/urls`, {
      method: 'POST',
      body: JSON.stringify({
        url,
        chunk_size: options.chunk_size,
        chunk_overlap: options.chunk_overlap,
      }),
    }),
  deleteSource: (knowledgeBaseId, sourceId) =>
    request(`/api/knowledge-bases/${knowledgeBaseId}/sources/${sourceId}`, { method: 'DELETE' }),
  openSourceBrowserSession: (knowledgeBaseId, sourceId) =>
    request(`/api/knowledge-bases/${knowledgeBaseId}/sources/${sourceId}/browser-session`, { method: 'POST' }),
  extractBrowserSession: (sessionId) =>
    request(`/api/browser-sessions/${sessionId}/extract`, { method: 'POST' }),
  closeBrowserSession: (sessionId) =>
    request(`/api/browser-sessions/${sessionId}/close`, { method: 'POST' }),
  buildIndex: (knowledgeBaseId, overwrite = true) =>
    request(`/api/knowledge-bases/${knowledgeBaseId}/index`, {
      method: 'POST',
      body: JSON.stringify({ overwrite }),
    }),
  testRetrieval: (knowledgeBaseId, payload) =>
    request(`/api/knowledge-bases/${knowledgeBaseId}/retrieval-test`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listWorkflowTemplates: () => request('/api/workflows/templates'),
  getDefaultWorkflow: (templateId = 'blank') => request(`/api/workflows/default?template_id=${encodeURIComponent(templateId)}`),
  listWorkflows: () => request('/api/workflows'),
  saveWorkflow: (payload) =>
    request('/api/workflows', { method: 'POST', body: JSON.stringify(payload) }),
  validateWorkflow: (payload) =>
    request('/api/workflows/validate', { method: 'POST', body: JSON.stringify(payload) }),
  prepareWorkflow: (workflowId) =>
    request(`/api/workflows/${workflowId}/prepare`, { method: 'POST' }),
  runWorkflow: (workflowId, payload) =>
    request(`/api/workflows/${workflowId}/run`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  executeWorkflow: (workflowId, payload) =>
    request(`/api/workflows/${workflowId}/execute`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startWorkflowTestRun: (workflowId, payload) =>
    request(`/api/workflows/${workflowId}/test-runs`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getWorkflowTestRun: (runId) => request(`/api/workflow-test-runs/${runId}`),
  runWorkflowNode: (workflowId, nodeId) =>
    request(`/api/workflows/${workflowId}/nodes/${nodeId}/run`, { method: 'POST' }),
  evaluateWorkflow: (workflowId) =>
    request(`/api/workflows/${workflowId}/evaluate`, { method: 'POST' }),
  listQuerySets: (knowledgeBaseId) => {
    const query = knowledgeBaseId ? `?knowledge_base_id=${knowledgeBaseId}` : '';
    return request(`/api/query-sets${query}`);
  },
  generateQuerySet: (payload) =>
    request('/api/query-sets/generate', { method: 'POST', body: JSON.stringify(payload) }),
  listEvalRuns: () => request('/api/eval-runs'),
  listEvalMetrics: () => request('/api/eval-metrics'),
  createEvalRun: (payload) =>
    request('/api/eval-runs', { method: 'POST', body: JSON.stringify(payload) }),
  startLocalDeployment: () => request('/api/deployment/local/start', { method: 'POST' }),
  runtimeCapabilities: () => request('/api/runtime/capabilities'),
  runtimeWorkflows: () => request('/api/runtime/workflows'),
};
