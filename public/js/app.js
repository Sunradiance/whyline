import { initSession, health, donation, decisions, ai, integrations, getApiKey, setApiKey } from './api.js';
import { renderMarkdown } from './markdown.js';
import { buildMemoryBrief } from './export.js';

const NAV = [
  { id: 'home', label: 'Ask Why', sub: 'Retrieval-backed answers with receipts' },
  { id: 'decisions', label: 'Decisions', sub: 'Search, filter, supersede' },
  { id: 'capture', label: 'Capture', sub: 'Email, transcripts, docs, threads' },
  { id: 'integrations', label: 'Integrations', sub: 'Slack /whyline, GitHub, Teams, MCP' },
  { id: 'brief', label: 'Memory Brief', sub: 'Export for leadership' },
];

const S = { view: 'home', list: [], search: '', statusFilter: '', lastAnswer: null, aiLoading: false, donation: null, intStatus: null };

const $ = (s) => document.querySelector(s);
const viewsEl = $('#views');

function toast(m) {
  const t = $('#toast');
  t.textContent = m;
  t.hidden = false;
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.hidden = true; }, 2800);
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

async function reload() {
  const { decisions: list } = await decisions.list(S.search, S.statusFilter);
  S.list = list;
  render();
}

async function go(id) {
  S.view = id;
  const n = NAV.find((x) => x.id === id);
  $('#view-title').textContent = n?.label || id;
  $('#view-subtitle').textContent = n?.sub || '';
  if (id === 'integrations' && !S.intStatus) {
    try { S.intStatus = await integrations.status(); } catch { /* ignore */ }
  }
  $('#nav').innerHTML = NAV.map((x) =>
    `<button class="nav-btn ${S.view === x.id ? 'active' : ''}" data-nav="${x.id}"><span class="dot"></span>${x.label}</button>`).join('');
  if (!viewsEl.childElementCount) {
    viewsEl.innerHTML = NAV.map((n) => `<section id="view-${n.id}" class="view"></section>`).join('');
  }
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${id}`));
  render();
}

function render() {
  ({ home: rHome, decisions: rDecisions, capture: rCapture, integrations: rIntegrations, brief: rBrief })[S.view]?.();
}

function decisionCard(d) {
  const srcs = (d.sources || []).map((s) =>
    s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.externalRef || s.sourceType)}</a>` : esc(s.externalRef || s.sourceType)
  ).join(' · ');
  const st = d.status === 'active' ? 'badge-active' : 'badge-superseded';
  return `<article class="card">
    <div class="card-head"><div class="card-title">${esc(d.title)}</div><span class="badge ${st}">${esc(d.status)}</span></div>
    <div class="card-meta"><span>${d.decidedAt || '—'}</span><span>${esc(d.decidedBy || '')}</span><span>conf ${d.confidence || '—'}/5</span></div>
    <div class="insight insight-accent">${esc(d.summary)}</div>
    ${d.reasoning ? `<div class="insight"><strong>Why:</strong> ${esc(d.reasoning)}</div>` : ''}
    ${srcs ? `<div class="card-meta" style="margin-top:0.5rem">📎 ${srcs}</div>` : ''}
    <div class="card-actions">
      ${d.status === 'active' ? `<button class="btn btn-sm btn-ghost" data-a="supersede" data-id="${d.id}">Supersede</button>` : ''}
      <button class="btn btn-sm btn-ghost" data-a="del" data-id="${d.id}">Delete</button>
    </div>
  </article>`;
}

function rHome() {
  const ans = S.lastAnswer;
  $(`#view-home`).innerHTML = `
    <div class="ask-hero">
      <h2>Ask why — retrieval-backed, with receipts</h2>
      <div class="ask-row">
        <input class="ask-input" id="ask-q" placeholder="Why don't we support annual billing in Germany?" />
        <button class="btn btn-primary" id="ask-btn" ${S.aiLoading ? 'disabled' : ''}>Ask</button>
      </div>
    </div>
    <div class="grid-3">
      <div class="stat"><div class="lbl">Decisions</div><div class="val">${S.list.filter((d) => d.status === 'active').length}</div></div>
      <div class="stat"><div class="lbl">Retrieved</div><div class="val" style="font-size:1.2rem">top ${8}</div><div class="sub">BM25 scoring</div></div>
      <div class="stat"><div class="lbl">Storage</div><div class="val" style="font-size:1.1rem">SQLite</div><div class="sub">shared server-side</div></div>
    </div>
    ${ans ? `
    <div class="answer-box">
      <h3>Answer · ${esc(ans.confidence)} · ${ans.retrieved || 0} decisions retrieved</h3>
      <div class="answer-body">${renderMarkdown(ans.answer)}</div>
      ${(ans.trail || []).length ? `<div class="section-h">Trail</div>${ans.trail.map((t, i) =>
        `<div class="trail-step"><span class="trail-num">${i + 1}</span><div><strong>${esc(t.step)}</strong><div class="insight">${esc(t.detail)}</div></div></div>`).join('')}` : ''}
      ${(ans.receipts || []).length ? `<div class="section-h">Receipts</div>${ans.receipts.map((r) =>
        `<div class="insight">${r.url ? `<a href="${esc(r.url)}" target="_blank">${esc(r.title || r.externalRef)}</a>` : esc(r.title)} <span class="badge badge-active">${esc(r.sourceType)}</span></div>`).join('')}` : ''}
      ${(ans.gaps || []).length ? `<div class="section-h">Gaps</div>${ans.gaps.map((g) => `<div class="insight">${esc(g)}</div>`).join('')}` : ''}
    </div>` : ''}`;
  $('#ask-btn')?.addEventListener('click', doAsk);
  $('#ask-q')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') doAsk(); });
}

async function doAsk() {
  const q = $('#ask-q')?.value?.trim();
  if (!q) return toast('Type a question');
  S.aiLoading = true;
  rHome();
  try {
    const { result, retrieved } = await ai.ask(q);
    S.lastAnswer = { ...result, retrieved };
    toast('Answer ready');
  } catch (e) {
    toast(e.message);
  } finally {
    S.aiLoading = false;
    rHome();
  }
}

function rDecisions() {
  $(`#view-decisions`).innerHTML = `
    <div class="filter-bar" style="display:flex;gap:0.5rem;margin-bottom:1rem">
      <input class="ask-input" id="dec-search" placeholder="Search decisions…" value="${esc(S.search)}" style="flex:1;padding:0.55rem 0.8rem;font-size:0.9rem" />
      <select id="dec-status" style="background:var(--card);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:0.4rem">
        <option value="">all</option><option value="active" ${S.statusFilter === 'active' ? 'selected' : ''}>active</option><option value="superseded" ${S.statusFilter === 'superseded' ? 'selected' : ''}>superseded</option>
      </select>
    </div>
    ${S.list.length ? S.list.map(decisionCard).join('') : '<div class="empty">No decisions match.</div>'}`;
  $('#dec-search')?.addEventListener('input', (e) => { S.search = e.target.value; reload(); });
  $('#dec-status')?.addEventListener('change', (e) => { S.statusFilter = e.target.value; reload(); });
}

function rCapture() {
  $(`#view-capture`).innerHTML = `
    <div class="grid-2">
      <div class="card"><div class="card-title">Meeting transcript</div><p class="insight">Fireflies/Otter/Zoom — speakers + timestamps.</p><button class="btn btn-magic" data-a="transcript">✦ Ingest transcript</button></div>
      <div class="card"><div class="card-title">Email / decisions@</div><p class="insight">Paste forwarded thread (or CC your alias).</p><button class="btn btn-magic" data-a="email-cap">✦ Capture email</button></div>
      <div class="card"><div class="card-title">Doc (Notion / Confluence / GDocs)</div><button class="btn btn-magic" data-a="doc-cap">✦ Ingest doc</button></div>
      <div class="card"><div class="card-title">Extract from text</div><button class="btn btn-magic" data-a="extract">✦ Extract decision</button></div>
      <div class="card"><div class="card-title">Synthesize fragments</div><button class="btn btn-magic" data-a="synth">✦ Synthesize</button></div>
      <div class="card"><div class="card-title">Slack / Teams JSON</div><button class="btn btn-magic" data-a="slack-json">✦ Slack thread</button> <button class="btn btn-ghost btn-sm" data-a="teams-json">Teams</button></div>
      <div class="card"><div class="card-title">Manual log</div><button class="btn btn-primary" data-a="log">+ Log decision</button></div>
    </div>`;
}

function intCard(logo, title, lines, ok) {
  const st = ok ? 'badge-active' : 'badge-superseded';
  return `<div class="card int-card"><div class="int-logo">${logo}</div><div style="flex:1">
    <div class="card-head"><div class="card-title">${title}</div><span class="badge ${st}">${ok ? 'live' : 'needs config'}</span></div>
    ${lines.map((l) => `<div class="insight">${l}</div>`).join('')}
  </div></div>`;
}

function rIntegrations() {
  const s = S.intStatus || {};
  $(`#view-integrations`).innerHTML = [
    intCard('EMAIL', 'decisions@ capture', [
      'POST <code>/api/integrations/email/ingest</code> · <code>EMAIL_WEBHOOK_SECRET</code>',
      'CC any thread → extracted + persisted. See <code>integrations/email/README.md</code>',
    ], s.email?.configured),
    intCard('SLACK', '/whyline + 📌 reaction', [
      'Slash: <code>/whyline &lt;text or thread URL&gt;</code> · React 📌 on threads',
      'Events: <code>/api/integrations/slack/events</code> · Commands: <code>/api/integrations/slack/commands</code>',
    ], s.slack?.configured),
    intCard('MCP', 'Claude / Cursor / Copilot', [
      'Tools: <code>whyline_ask</code> <code>whyline_extract</code> <code>whyline_search</code>',
      'Run: <code>npm run mcp</code> · See <code>integrations/mcp/README.md</code>',
    ], true),
    intCard('TRANSCRIPT', 'Meeting notes', ['POST <code>/api/integrations/transcript/ingest</code>'], s.transcript?.configured),
    intCard('DOCS', 'Notion / Confluence / GDocs', ['POST <code>/api/integrations/doc/ingest</code>'], s.doc?.configured),
    intCard('GITHUB', 'PR + issue discussions', ['POST <code>/api/integrations/github/webhook</code> · <code>GITHUB_WEBHOOK_SECRET</code>'], s.github?.configured),
    intCard('TEAMS', 'MS Teams threads', ['POST <code>/api/integrations/teams/ingest</code> · <code>TEAMS_WEBHOOK_SECRET</code>'], s.teams?.configured),
    intCard('LINEAR', 'Issue discussions', ['POST <code>/api/integrations/linear/webhook</code>'], s.linear?.configured),
    intCard('JIRA', 'Atlassian webhook', ['POST <code>/api/integrations/atlassian/jira</code>'], s.atlassian?.configured),
    intCard('SFDC', 'Salesforce (scoped)', ['POST <code>/api/integrations/salesforce/webhook</code>'], s.salesforce?.configured),
  ].join('');
}

function rBrief() {
  const brief = buildMemoryBrief(S.list);
  $(`#view-brief`)._b = brief;
  $(`#view-brief`).innerHTML = `
    <div style="display:flex;gap:0.5rem;margin-bottom:1rem">
      <button class="btn btn-magic" data-a="enhance">✦ AI enhance</button>
      <button class="btn btn-ghost" data-a="copy">Copy</button>
      <button class="btn btn-ghost" data-a="dl">Download</button>
      <button class="btn btn-ghost" data-a="export-json">Export JSON</button>
      <button class="btn btn-ghost" data-a="import-json">Import JSON</button>
    </div><div class="pre" id="brief-pre">${esc(brief)}</div>`;
}

function modal(title, html, onSave) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = html;
  const m = $('#modal'), f = $('#modal-form');
  m.showModal();
  const h = async (e) => { e.preventDefault(); if (await onSave() !== false) m.close(); f.removeEventListener('submit', h); };
  f.addEventListener('submit', h);
}

function showDonation() {
  const d = S.donation;
  if (!d?.enabled || !d?.address) {
    $('#donation-body').innerHTML = '<p class="insight">Donations not configured for this deployment.</p>';
    $('#donation-modal').showModal();
    return;
  }
  $('#donation-body').innerHTML = d?.address ? `
    <p style="color:var(--muted)">Voluntary <strong style="color:var(--sol)">SOL</strong> on Solana chain only.</p>
    <div class="sol-warning">◎ No other tokens or chains accepted</div>
    <div class="sol-address">${esc(d.address)}</div>
    <button class="btn btn-primary" data-a="copy-sol" style="width:100%">Copy address</button>` : '';
  $('#donation-modal').showModal();
}

document.body.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-a], [data-nav]');
  if (!b) return;
  if (b.dataset.nav) { go(b.dataset.nav); return; }
  const a = b.dataset.a, id = b.dataset.id;

  if (a === 'copy-sol') { await navigator.clipboard.writeText(S.donation?.address || ''); toast('Copied'); }
  if (a === 'del' && confirm('Delete?')) { await decisions.delete(id); await reload(); toast('Deleted'); }
  if (a === 'supersede') {
    modal('Supersede — new decision', '<div class="field"><label>New title</label><input name="title" required></div><div class="field"><label>Summary</label><textarea name="summary" rows="3"></textarea></div><div class="field"><label>What changed?</label><textarea name="reasoning" rows="5" required></textarea></div>', async () => {
      const fd = new FormData($('#modal-form'));
      await decisions.supersede(id, { title: fd.get('title'), reasoning: fd.get('reasoning'), summary: fd.get('summary') || fd.get('reasoning'), sourceType: 'supersede' });
      await reload(); toast('Superseded');
    });
  }
  if (a === 'extract') modal('Extract', '<div class="field"><textarea name="text" rows="10" required></textarea></div>', async () => {
    const text = new FormData($('#modal-form')).get('text');
    await ai.extract(text, 'manual'); await reload(); toast('Saved to SQLite');
  });
  if (a === 'synth') modal('Synthesize', '<div class="field"><textarea name="frags" rows="8" placeholder="one fragment per line"></textarea></div>', async () => {
    const frags = new FormData($('#modal-form')).get('frags').split('\n').filter(Boolean);
    await ai.synthesize(frags); await reload(); toast('Synthesized');
  });
  if (a === 'transcript') modal('Meeting transcript', '<div class="field"><label>Title</label><input name="title"></div><div class="field"><label>URL (optional)</label><input name="url"></div><div class="field"><label>Transcript (Speaker (00:12): text…)</label><textarea name="text" rows="12" required></textarea></div>', async () => {
    const fd = new FormData($('#modal-form'));
    await integrations.transcript({ title: fd.get('title'), url: fd.get('url'), text: fd.get('text'), provider: 'manual' });
    await reload(); toast('Transcript captured');
  });
  if (a === 'email-cap') modal('Email capture', '<div class="field"><label>Subject</label><input name="subject"></div><div class="field"><label>From</label><input name="from"></div><div class="field"><label>Body</label><textarea name="body" rows="10" required></textarea></div>', async () => {
    const fd = new FormData($('#modal-form'));
    await integrations.emailCapture({ subject: fd.get('subject'), body: fd.get('body'), from: fd.get('from') });
    await reload(); toast('Email captured');
  });
  if (a === 'doc-cap') modal('Doc ingest', '<div class="field"><label>Title</label><input name="title" required></div><div class="field"><label>Source</label><select name="sourceType"><option value="notion">Notion</option><option value="confluence">Confluence</option><option value="gdocs">Google Docs</option></select></div><div class="field"><label>URL</label><input name="url"></div><div class="field"><label>Text</label><textarea name="text" rows="10" required></textarea></div>', async () => {
    const fd = new FormData($('#modal-form'));
    await integrations.doc({ title: fd.get('title'), sourceType: fd.get('sourceType'), url: fd.get('url'), text: fd.get('text') });
    await reload(); toast('Doc captured');
  });
  if (a === 'slack-json') modal('Slack messages JSON', '<div class="field"><textarea name="json" rows="8"></textarea></div>', async () => {
    await integrations.slackIngest(JSON.parse(new FormData($('#modal-form')).get('json')));
    await reload(); toast('Ingested');
  });
  if (a === 'teams-json') modal('Teams messages JSON', '<div class="field"><textarea name="json" rows="8" placeholder=\'[{"text":"..."}]\'></textarea></div>', async () => {
    const msgs = JSON.parse(new FormData($('#modal-form')).get('json'));
    await integrations.teams({ messages: msgs });
    await reload(); toast('Teams captured');
  });
  if (a === 'log') modal('Log decision', '<div class="field"><label>Title</label><input name="title" required></div><div class="field"><label>Summary</label><textarea name="summary"></textarea></div><div class="field"><label>Reasoning</label><textarea name="reasoning"></textarea></div>', async () => {
    const fd = new FormData($('#modal-form'));
    await decisions.create({ title: fd.get('title'), summary: fd.get('summary'), reasoning: fd.get('reasoning'), sourceType: 'manual', status: 'active' });
    await reload(); toast('Logged');
  });
  if (a === 'copy') { await navigator.clipboard.writeText($(`#view-brief`)._b); toast('Copied'); }
  if (a === 'dl') { const l = document.createElement('a'); l.href = URL.createObjectURL(new Blob([$(`#view-brief`)._b])); l.download = 'memory-brief.md'; l.click(); }
  if (a === 'export-json') {
    const data = await decisions.exportAll();
    const l = document.createElement('a');
    l.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)]));
    l.download = 'whyline-export.json';
    l.click();
    toast('Exported');
  }
  if (a === 'import-json') modal('Import JSON backup', '<div class="field"><textarea name="json" rows="12" placeholder=\'{"decisions":[...]}\'></textarea></div>', async () => {
    const { imported } = await decisions.importAll(JSON.parse(new FormData($('#modal-form')).get('json')));
    await reload();
    toast(`Imported ${imported} decision(s)`);
  });
  if (a === 'enhance') { const { brief } = await ai.enhanceBrief($(`#view-brief`)._b); $(`#view-brief`)._b = brief; $('#brief-pre').textContent = brief; toast('Enhanced'); }
});

$('#btn-log-decision').onclick = () => document.querySelector('[data-a="log"]')?.click();
$('#btn-support').onclick = showDonation;
$('#donation-close').onclick = () => $('#donation-modal').close();
$('#donation-done').onclick = () => $('#donation-modal').close();
$('#modal-close').onclick = () => $('#modal').close();
$('#modal-cancel').onclick = () => $('#modal').close();

$('#api-key').addEventListener('change', (e) => { setApiKey(e.target.value); toast('API key set (session memory only)'); });

(async () => {
  const ok = await initSession();
  if (!ok && !getApiKey()) toast('Remote? Ask admin for WHYLINE_API_KEY');
  const h = await health();
  $('#db-status').textContent = h.apis?.db ? 'sqlite · local' : '—';
  S.donation = await donation();
  await reload();
  go('home');
})();