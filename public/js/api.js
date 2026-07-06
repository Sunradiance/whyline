/** API key kept in memory only — not sessionStorage (XSS exfil risk). */
let _apiKey = '';

export function getApiKey() {
  return _apiKey;
}

export function setApiKey(key) {
  _apiKey = (key || '').trim();
}

async function api(path, { method = 'GET', body } = {}) {
  const opts = { method, credentials: 'include', headers: {} };
  if (_apiKey) opts.headers['X-Whyline-Key'] = _apiKey;
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`/api${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

export async function initSession() {
  try {
    await api('/session', { method: 'POST' });
    return true;
  } catch {
    return false;
  }
}

export const health = () => api('/health');
export const donation = () => api('/donation');
export const decisions = {
  list: (search = '', status = '') => api(`/decisions?search=${encodeURIComponent(search)}&status=${encodeURIComponent(status)}`),
  create: (d) => api('/decisions', { method: 'POST', body: d }),
  patch: (id, d) => api(`/decisions/${id}`, { method: 'PATCH', body: d }),
  delete: (id) => api(`/decisions/${id}`, { method: 'DELETE' }),
  supersede: (id, d) => api(`/decisions/${id}/supersede`, { method: 'POST', body: d }),
  exportAll: () => api('/decisions/export'),
  importAll: (data) => api('/decisions/import', { method: 'POST', body: data }),
};
export const ai = {
  ask: (question) => api('/ai/ask', { method: 'POST', body: { question } }),
  search: (query, top_k) => api('/ai/search', { method: 'POST', body: { query, top_k } }),
  extract: (text, source, sources) => api('/ai/extract', { method: 'POST', body: { text, source, sources } }),
  synthesize: (fragments) => api('/ai/synthesize', { method: 'POST', body: { fragments } }),
  enhanceBrief: (brief) => api('/ai/enhance-brief', { method: 'POST', body: { brief } }),
};
export const integrations = {
  status: () => api('/integrations/status'),
  slackIngest: (messages) => api('/integrations/slack/ingest', { method: 'POST', body: { messages } }),
  slackCapture: (channel, thread_ts) => api('/integrations/slack/capture', { method: 'POST', body: { channel, thread_ts } }),
  emailCapture: (payload) => api('/integrations/email/capture', { method: 'POST', body: payload }),
  transcript: (payload) => api('/integrations/transcript/ingest', { method: 'POST', body: payload }),
  doc: (payload) => api('/integrations/doc/ingest', { method: 'POST', body: payload }),
  teams: (payload) => api('/integrations/teams/capture', { method: 'POST', body: payload }),
};