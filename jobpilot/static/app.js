'use strict';
/* JobPilot Pro dashboard — professional multi-portal auto-apply */
const $ = s => document.querySelector(s);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(c));
  return el;
}

async function api(path, opt = {}) {
  if (opt.json !== undefined) { opt.method = opt.method || 'POST'; opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(opt.json); }
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}
let toastT;
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), 3400); }
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message || 'Something went wrong'); } };

/* ---------------- state ---------------- */
let S = null, jobs = [], jobsKey = '';
let view = (location.hash || '#jobs').slice(1);
let roles = [], cities = [], portalPick = [], modes = [], tiers = [], types = [];
let filter = 'all';
const sel = new Set();
let searching = false;
const MODES = [['remote', 'Remote'], ['hybrid', 'Hybrid'], ['wfo', 'On-site']];
const TIERS = [['tier1', 'Top / large'], ['tier2', 'Mid-size'], ['tier3', 'Startup / small']];
const TYPES = [['mnc', 'MNC'], ['product', 'Product'], ['startup', 'Startup'], ['service', 'IT services']];

const STATUS = {
  new: ['Ready to apply', ''], applying: ['Applying…', ''], ready: ['Form ready', 'Approve & submit'],
  needs_human: ['Needs you', ''], applied: ['Applied', ''], failed: ['Failed', ''], skipped: ['Skipped', ''], manual: ['You apply', ''],
};
const FILTERS = [['all', 'All'], ['new', 'To apply'], ['wait', 'Waiting'], ['applied', 'Applied'], ['skipped', 'Skipped']];
const inFilter = (j, f) => f === 'all' || (f === 'new' && ['new', 'applying'].includes(j.status)) ||
  (f === 'wait' && ['ready', 'needs_human', 'failed', 'manual'].includes(j.status)) || (f === 'applied' && j.status === 'applied') || (f === 'skipped' && j.status === 'skipped');

/* ---------------- theme ---------------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('jp-theme', t); } catch (e) {}
  $('#theme').setAttribute('aria-checked', t === 'dark');
}
$('#theme').onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
setTheme(document.documentElement.dataset.theme);

/* ---------------- header + nav ---------------- */
const TABS = [['jobs', 'Jobs'], ['resume', 'Resume'], ['portals', 'Portals'], ['settings', 'Settings']];
function renderNav() {
  const nav = $('#nav'); nav.replaceChildren(...TABS.map(([id, label]) =>
    h('button', { 'aria-current': view === id ? 'page' : null, onclick: () => go(id) }, label)));
  document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== 'v-' + view);
}
function go(v) { view = v; location.hash = v; renderNav(); renderView(); updateDock(); }
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== view && TABS.some(t => t[0] === v)) go(v); });

function renderLeds() {
  const on = (b, t) => h('span', {}, h('i', { class: 'dot' + (b ? ' on' : '') }), t);
  $('#leds').replaceChildren(on(S.ai_enabled, 'AI'), on(S.email_enabled, 'Email'), on(S.push_enabled, 'Alert'));
}
$('#log-btn').onclick = () => { const p = $('#logpane'); p.hidden = !p.hidden; renderLog(); };
$('#log-close').onclick = () => $('#logpane').hidden = true;
function renderLog() {
  if ($('#logpane').hidden) return;
  const pre = $('#logtext'), atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
  pre.textContent = S.log.join('\n') || 'No activity yet. Start a search to see steps here.';
  if (atEnd) pre.scrollTop = pre.scrollHeight;
}

/* ---------------- autopilot (progress + STOP) ---------------- */
function renderAutopilot() {
  const box = $('#auto'), r = S.run;
  if (!r.running) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  const pct = r.total ? Math.min(100, Math.round(100 * r.done / r.total)) : 0;
  const title = r.stopping ? 'Stopping…' : r.label || 'Working…';
  box.replaceChildren(h('div', { class: 'ap' },
    h('div', {}, h('b', {}, title), h('small', {}, r.current || '')),
    h('button', { class: 'stop', disabled: r.stopping, onclick: guard(stopAll) }, h('i'), 'Stop'),
    h('div', { class: 'track' }, h('div', { class: 'fill', style: `width:${pct}%` }))));
}
async function stopAll() { await api('/api/stop', { method: 'POST' }); toast('Stopping…'); await refresh(); }

/* ---------------- Jobs view ---------------- */
function chipToggle(list, key, label, onchange) {
  return h('button', { class: 'chip', 'aria-pressed': list.includes(key), onclick: e => {
    const i = list.indexOf(key); i < 0 ? list.push(key) : list.splice(i, 1);
    e.currentTarget.setAttribute('aria-pressed', list.includes(key)); onchange && onchange();
  } }, label);
}

function buildJobsView() {
  const v = $('#v-jobs');

  // Left filter panel
  const cityRow = h('div', { class: 'chips', id: 'city-row' });
  const portalRow = h('div', { class: 'chips', id: 'portal-row' });
  const panel = h('div', { class: 'panel' },
    h('div', { class: 'card' },
      h('div', { class: 'grp' }, h('h3', {}, 'Cities'), cityRow),
      h('div', { class: 'grp' }, h('h3', {}, 'Work style'), h('div', { class: 'chips' }, ...MODES.map(([k, l]) => chipToggle(modes, k, l)))),
      h('div', { class: 'grp' }, h('h3', {}, 'Company size'), h('div', { class: 'chips' }, ...TIERS.map(([k, l]) => chipToggle(tiers, k, l)))),
      h('div', { class: 'grp' }, h('h3', {}, 'Company type'), h('div', { class: 'chips' }, ...TYPES.map(([k, l]) => chipToggle(types, k, l)))),
      h('div', { class: 'grp' }, h('h3', {}, 'Search on'), portalRow),
    ));

  // Right content
  const input = h('input', { id: 'role-in', placeholder: roles.length ? 'Add another role…' : 'e.g. Backend Engineer, DevOps', 'aria-label': 'Job role', onkeydown: e => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addRole(input.value); input.value = ''; }
    if (e.key === 'Backspace' && !input.value && roles.length) { roles.pop(); renderRoleChips(); }
  } });
  const chips = h('div', { class: 'chips', id: 'role-chips' });
  const sugg = h('div', { class: 'suggest', id: 'sugg' });

  const hero = h('div', { class: 'hero-compact' },
    h('h1', {}, 'Find & auto-apply to jobs across India'),
    h('p', {}, 'Searches Naukri, foundit, Shine, Internshala + 120+ company career pages. Only matching roles are shown.'),
    h('div', { class: 'role-row' },
      h('label', { style: 'font-size:12px;font-weight:700;color:var(--mute);margin-right:4px' }, 'Roles'),
      chips, input,
      h('button', { class: 'go', id: 'go', onclick: guard(doSearch) }, 'Find jobs')),
    sugg);

  const right = h('div', {}, hero, h('div', { class: 'bar', id: 'bar' }), h('div', { id: 'list' }));
  v.replaceChildren(h('div', { class: 'jobs-layout' }, panel, right));
  renderRoleChips(); renderCities(); renderPortalPick(); renderJobs();
}

function renderRoleChips() {
  const el = $('#role-chips');
  if (!el) return;
  el.replaceChildren(...roles.map(r => h('span', { class: 'chip role' }, r,
    h('button', { 'aria-label': 'Remove ' + r, onclick: () => { roles = roles.filter(x => x !== r); renderRoleChips(); } }, '×'))));
  const have = new Set(roles.map(r => r.toLowerCase()));
  const ideas = (S.profile.target_roles || []).filter(r => !have.has(r.toLowerCase()));
  const s = $('#sugg'); if (!s) return;
  s.replaceChildren();
  if (ideas.length) s.append('From your resume: ', ...ideas.slice(0, 6).map(r => h('button', { onclick: () => addRole(r) }, '+ ' + r)));
  else if (!S.resume) s.append(h('span', {}, 'Upload your resume first for role suggestions. '), h('a', { href: '#resume' }, 'Go to Resume'));
}
function addRole(r) { r = r.trim().replace(/,$/, ''); if (r && !roles.some(x => x.toLowerCase() === r.toLowerCase())) roles.push(r); renderRoleChips(); }

function renderCities() {
  const el = $('#city-row'); if (!el) return;
  el.replaceChildren(...S.city_presets.map(c => chipToggle(cities, c, c)),
    h('input', { class: 'chip', style: 'width:120px;cursor:text', placeholder: '+ city', 'aria-label': 'Add city', onkeydown: e => {
      if (e.key === 'Enter' && e.target.value.trim()) { cities.push(e.target.value.trim()); renderCities(); } } }));
}

function renderPortalPick() {
  const el = $('#portal-row'); if (!el) return;
  const auto = S.portals.filter(p => p.auto);
  el.replaceChildren(
    ...auto.map(p => h('button', { class: 'chip', 'aria-pressed': portalPick.includes(p.id), onclick: e => {
      const i = portalPick.indexOf(p.id); i < 0 ? portalPick.push(p.id) : portalPick.splice(i, 1);
      e.currentTarget.setAttribute('aria-pressed', portalPick.includes(p.id)); } },
      h('i', { class: 'dot' + (p.connected ? ' on' : '') }), p.name)),
    h('button', { class: 'chip', 'aria-pressed': true, title: 'Always included', style: 'opacity:.85' },
      h('i', { class: 'dot on' }), 'Company pages'),
    h('a', { href: '#portals', style: 'font-size:12px;font-weight:600;margin-left:4px' }, 'Connect →'));
}

async function doSearch() {
  if (!roles.length) { const v = $('#role-in')?.value; if (v?.trim()) addRole(v); }
  if (!roles.length) return toast('Add at least one role first');
  if (S.run.running) return toast('Already running. Stop it first.');
  searching = true;
  // Ensure at least the connected portals + company pages
  const portals = portalPick.length ? portalPick : S.portals.filter(p => p.auto).map(p => p.id);
  const r = await api('/api/search', { json: {
    roles, locations: cities, work_modes: modes.length ? modes : ['remote','hybrid','wfo'],
    company_tiers: tiers.length ? tiers : ['tier1','tier2','tier3'],
    company_types: types.length ? types : ['mnc','product','startup','service'],
    portals,
  }});
  toast(r.started ? 'Searching portals + company career pages…' : 'Busy. Try again shortly.');
  await refresh();
}

function scoreColor(n) { return n >= 75 ? 'var(--green)' : n >= 55 ? 'var(--teal)' : 'var(--amber)'; }
function pass(j) {
  const [label] = STATUS[j.status] || [j.status];
  const portal = S.portals.find(p => p.id === j.source);
  const canSel = j.apply_mode === 'auto' && ['new', 'failed', 'needs_human'].includes(j.status);
  const srcName = portal ? portal.name : (j.source || '').startsWith('greenhouse') || (j.source || '').startsWith('lever') || (j.source || '').startsWith('ashby')
    ? 'Company site' : (j.source || '').split(':')[0];
  const tags = [
    j.location && h('span', { class: 'tag' }, j.location),
    j.work_mode && h('span', { class: 'tag ' + j.work_mode }, { remote: 'Remote', hybrid: 'Hybrid', wfo: 'On-site' }[j.work_mode] || j.work_mode),
    j.exp && h('span', { class: 'tag' }, j.exp),
    j.salary && h('span', { class: 'tag' }, j.salary),
    h('span', { class: 'tag src' }, srcName),
  ];
  const acts = [
    h('a', { class: 'btn', href: j.url, target: '_blank', rel: 'noopener' }, 'Open'),
    j.status === 'ready' && h('button', { class: 'btn pri', onclick: guard(() => act(`/api/jobs/${j.id}/approve`, 'Submitting…')) }, 'Approve & submit'),
    ['failed', 'needs_human'].includes(j.status) && j.apply_mode === 'auto' && h('button', { class: 'btn', onclick: guard(() => act(`/api/jobs/${j.id}/retry`, 'Retrying…')) }, 'Retry'),
    ['new', 'manual', 'needs_human', 'ready', 'failed'].includes(j.status) && h('button', { class: 'btn', onclick: guard(() => setStatus(j.id, 'applied')) }, 'I applied'),
    ['new', 'manual', 'needs_human', 'failed'].includes(j.status) && h('button', { class: 'btn ghost', onclick: guard(() => setStatus(j.id, 'skipped')) }, 'Skip'),
    j.status === 'skipped' && h('button', { class: 'btn', onclick: guard(() => setStatus(j.id, 'new')) }, 'Restore'),
    ['ready', 'applied', 'needs_human', 'failed'].includes(j.status) && j.apply_mode === 'auto' && h('a', { class: 'btn ghost', href: `/shots/job_${j.id}.png`, target: '_blank' }, 'Screenshot'),
  ];
  const note = j.note || (j.reason && j.status === 'new' ? j.reason : '');
  return h('article', { class: `pass s-${j.status}` + (sel.has(j.id) ? ' sel-on' : '') },
    h('div', { class: 'sel' }, canSel ? h('input', { type: 'checkbox', 'aria-label': 'Select ' + j.title, checked: sel.has(j.id), onchange: e => { e.target.checked ? sel.add(j.id) : sel.delete(j.id); renderJobs(); } }) : null),
    h('div', { class: 'main' }, h('h3', {}, j.title), h('p', { class: 'co' }, j.company), h('div', { class: 'tags' }, tags),
      j.matched && j.matched.length ? h('div', { class: 'kw' }, 'Matched skills: ', h('b', {}, j.matched.slice(0, 6).join(', '))) : null),
    h('div', { class: 'stub' },
      h('div', { class: 'score' }, h('div', { class: 'ring', style: `--p:${j.score};--c:${scoreColor(j.score)}`, title: 'Match score' }, h('span', {}, j.score)),
        h('div', {}, h('div', { class: 'state' }, label), h('span', { class: 'badge ' + j.apply_mode }, j.apply_mode === 'auto' ? 'Auto' : 'Manual'))),
      note ? h('div', { class: 'note' }, note) : null,
      j.applied_by ? h('div', { class: 'note' }, j.applied_by === 'ai' ? 'Applied by JobPilot' : 'Applied by you') : null,
      h('div', { class: 'acts' }, acts)));
}
async function act(path, msg) { const r = await api(path, { method: 'POST' }); toast(r.started ? msg : 'Busy. Try again.'); await refresh(); }
async function setStatus(id, s) { await api(`/api/jobs/${id}/status`, { json: { status: s } }); await refresh(); }

function renderJobs() {
  if (!$('#list')) return;
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, jobs.filter(j => inFilter(j, k)).length]));
  $('#bar').replaceChildren(
    h('h2', {}, jobs.length ? `${jobs.length} jobs` : 'Jobs'),
    ...FILTERS.map(([k, l]) => h('button', { class: 'pill', 'aria-pressed': filter === k, onclick: () => { filter = k; renderJobs(); } }, l, h('b', {}, counts[k]))),
    jobs.some(j => j.status !== 'applied') ? h('button', { class: 'btn danger', onclick: guard(clearJobs) }, 'Clear unapplied') : null);
  const list = jobs.filter(j => inFilter(j, filter));
  $('#list').replaceChildren(...(list.length ? list.map(pass) : [h('div', { class: 'empty' },
    h('h3', {}, jobs.length ? 'Nothing in this filter' : 'No jobs yet'),
    h('p', {}, jobs.length ? 'Try another tab above.' : 'Add roles, set filters on the left, then press Find jobs.'))]));
  updateDock();
}
async function clearJobs() {
  if (!confirm('Remove all jobs that are not applied yet? Applied jobs stay.')) return;
  const r = await api('/api/jobs/clear', { method: 'POST' });
  toast(`${r.removed} jobs cleared`); sel.clear(); await refresh();
}

/* ---------------- dock (Auto apply) ---------------- */
const eligible = () => jobs.filter(j => j.apply_mode === 'auto' && ['new', 'failed'].includes(j.status));
function updateDock() {
  const d = $('#dock'), run = S && S.run.running;
  if (!S || view !== 'jobs' || (!eligible().length && !sel.size && !run)) { d.hidden = true; return; }
  d.hidden = false;
  const review = !S.prefs.auto_submit;
  const strong = eligible().filter(j => j.score >= S.prefs.min_score);
  d.replaceChildren(...[
    h('div', { class: 'info' },
      h('b', {}, sel.size), ' selected',
      h('div', { class: 'muted', style: 'font-size:12px' }, `${strong.length} strong matches · ${S.applied_today}/${S.prefs.daily_cap} applied today`)),
    h('button', { class: 'btn', onclick: () => { strong.forEach(j => sel.add(j.id)); renderJobs(); } }, 'Select strong'),
    sel.size ? h('button', { class: 'btn', onclick: () => { sel.clear(); renderJobs(); } }, 'Clear') : null,
    h('label', { class: 'switch', title: 'ON = wait for your Approve. OFF = full auto submit.' },
      h('input', { type: 'checkbox', checked: review, onchange: guard(async e => {
        S.prefs.auto_submit = !e.target.checked;
        await api('/api/prefs', { method: 'PUT', json: { data: S.prefs } });
        toast(e.target.checked ? 'Will wait for your approval' : 'Full auto-submit enabled');
        updateDock();
      }) }), 'Review before submit'),
    run
      ? h('button', { class: 'stop', disabled: S.run.stopping, onclick: guard(stopAll) }, h('i'), 'Stop')
      : h('button', { class: 'go', disabled: !sel.size, onclick: guard(startApply) }, 'Auto apply selected'),
  ].filter(Boolean));
}
async function startApply() {
  const r = await api('/api/apply', { json: { ids: [...sel], submit: !!S.prefs.auto_submit } });
  toast(r.started ? 'Auto apply started. Press Stop anytime.' : 'Busy. Try again.');
  sel.clear(); await refresh();
}

/* ---------------- Resume view ---------------- */
const FIELDS = [
  ['first_name', 'First name'], ['last_name', 'Last name'], ['email', 'Email'], ['phone', 'Mobile (10 digits)'],
  ['location', 'City'], ['current_title', 'Current / last role'], ['current_company', 'Current / last company'],
  ['years_experience', 'Experience (years)'], ['notice_period', 'Notice period (e.g. 30 days)'],
  ['expected_ctc', 'Expected CTC'], ['current_ctc', 'Current CTC'], ['linkedin', 'LinkedIn URL'],
  ['github', 'GitHub URL'], ['education', 'Education'],
];
function buildResumeView() {
  const v = $('#v-resume'), r = S.resume;
  const fileIn = h('input', { type: 'file', accept: '.pdf,.docx,.txt', hidden: true, onchange: guard(() => upload(fileIn.files[0])) });
  const drop = h('div', { class: 'drop', tabindex: 0, role: 'button', onclick: () => fileIn.click(),
    onkeydown: e => e.key === 'Enter' && fileIn.click(),
    ondragover: e => { e.preventDefault(); drop.classList.add('over'); },
    ondragleave: () => drop.classList.remove('over'),
    ondrop: guard(e => { e.preventDefault(); drop.classList.remove('over'); return upload(e.dataTransfer.files[0]); }) },
    h('h3', {}, r ? 'Replace resume' : 'Drop your resume here'),
    h('p', { class: 'muted' }, 'PDF, DOCX or TXT · click or drag & drop'), fileIn);

  const left = h('div', { class: 'card' },
    h('h2', { class: 'section-title' }, 'Your resume'),
    h('p', { class: 'section-sub' }, 'JobPilot extracts skills, experience and contact details to fill application forms automatically.'),
    r ? h('div', { class: 'file' },
      h('div', { class: 'ext' }, r.ext),
      h('div', { style: 'min-width:0' },
        h('b', {}, r.name),
        h('div', { class: 'muted', style: 'font-size:12px' }, `${r.kb} KB · ${r.modified}`),
        h('div', { class: 'row', style: 'margin-top:8px' },
          h('a', { class: 'btn', href: '/api/resume/file' }, 'Download'),
          h('button', { class: 'btn', onclick: () => fileIn.click() }, 'Replace'))))
      : null,
    drop);

  const p = S.profile || {};
  const fields = h('div', { class: 'card' },
    h('h2', { class: 'section-title' }, 'Profile details'),
    h('p', { class: 'section-sub' }, 'Used to answer notice period, CTC and contact fields on company forms.'),
    h('div', { class: 'grid2' }, ...FIELDS.map(([k, lab]) =>
      h('div', { class: 'field' }, h('label', {}, lab),
        h('input', { value: p[k] || '', 'data-k': k, onchange: e => p[k] = e.target.value })))),
    h('div', { class: 'field', style: 'margin-top:12px' },
      h('label', {}, 'Skills (comma separated)'),
      h('textarea', { rows: 3, value: (p.skills || []).join(', '), onchange: e => p.skills = e.target.value.split(',').map(s => s.trim()).filter(Boolean) })),
    h('div', { class: 'field', style: 'margin-top:12px' },
      h('label', {}, 'Target roles (comma separated)'),
      h('textarea', { rows: 2, value: (p.target_roles || []).join(', '), onchange: e => p.target_roles = e.target.value.split(',').map(s => s.trim()).filter(Boolean) })),
    h('div', { class: 'row', style: 'margin-top:16px' },
      h('button', { class: 'go', onclick: guard(saveProfile) }, 'Save profile')));

  v.replaceChildren(h('div', { style: 'display:grid;grid-template-columns:1fr 1.4fr;gap:20px' }, left, fields));
}
async function upload(f) {
  if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/resume', { method: 'POST', body: fd }).then(x => x.json());
  if (r.error) throw new Error(r.error);
  toast('Resume uploaded & parsed'); await refresh();
}
async function saveProfile() {
  const p = S.profile || {};
  document.querySelectorAll('[data-k]').forEach(el => { p[el.dataset.k] = el.value; });
  await api('/api/profile', { method: 'PUT', json: { data: p } });
  toast('Profile saved'); await refresh();
}

/* ---------------- Portals view ---------------- */
function buildPortalsView() {
  const v = $('#v-portals');
  const auto = S.portals.filter(p => p.auto);
  const manual = S.portals.filter(p => !p.auto);
  v.replaceChildren(
    h('h2', { class: 'section-title' }, 'Job portals'),
    h('p', { class: 'section-sub' }, 'Connect portals so JobPilot can search and auto-apply with your login. Company career pages need no login.'),
    h('h3', { style: 'font-size:14px;margin:16px 0 10px;color:var(--mute)' }, 'Auto-apply portals'),
    h('div', { class: 'portal-grid' }, ...auto.map(p =>
      h('div', { class: 'portal-card' },
        h('h3', {}, h('i', { class: 'dot' + (p.connected ? ' on' : '') }), p.name),
        h('p', {}, p.blurb || ''),
        h('span', { class: 'status ' + (p.connected ? 'ok' : 'off') }, p.connected ? 'Connected' : 'Not connected'),
        h('div', { class: 'row', style: 'margin-top:12px' },
          h('button', { class: 'btn pri', onclick: guard(() => connectPortal(p.id)) }, p.connected ? 'Reconnect' : 'Connect'),
          p.connected && h('button', { class: 'btn', onclick: guard(() => disconnectPortal(p.id)) }, 'Disconnect'))))),
    h('h3', { style: 'font-size:14px;margin:24px 0 10px;color:var(--mute)' }, 'Manual search links (no auto-apply)'),
    h('div', { class: 'portal-grid' }, ...manual.map(p =>
      h('div', { class: 'portal-card' },
        h('h3', {}, p.name),
        h('p', {}, p.blurb || 'Opens a pre-filled search. You apply yourself.'),
        h('a', { class: 'btn', href: '#jobs', onclick: () => go('jobs') }, 'Use from Jobs page')))));
}
async function connectPortal(id) {
  toast('Opening login window… log in there, then click “I’m logged in”');
  const r = await api(`/api/portals/${id}/connect`, { method: 'POST' });
  toast(r.connected ? `${id} connected` : 'Login not completed');
  await refresh();
}
async function disconnectPortal(id) {
  await api(`/api/portals/${id}/disconnect`, { method: 'POST' });
  toast('Disconnected'); await refresh();
}

/* ---------------- Settings view ---------------- */
function buildSettingsView() {
  const v = $('#v-settings');
  const p = S.prefs || {};
  v.replaceChildren(
    h('h2', { class: 'section-title' }, 'Settings'),
    h('p', { class: 'section-sub' }, 'Tune match threshold, daily limit and auto-submit behaviour.'),
    h('div', { class: 'set-grid' },
      h('div', { class: 'card' },
        h('h3', { style: 'font-size:15px;margin-bottom:12px' }, 'Apply behaviour'),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Minimum match score (0–100)'),
          h('input', { type: 'number', min: 0, max: 100, value: p.min_score ?? 55, id: 'set-min' })),
        h('div', { class: 'field', style: 'margin-bottom:12px' },
          h('label', {}, 'Daily apply cap'),
          h('input', { type: 'number', min: 1, max: 100, value: p.daily_cap ?? 25, id: 'set-cap' })),
        h('label', { class: 'switch', style: 'margin-bottom:12px' },
          h('input', { type: 'checkbox', checked: !!p.auto_submit, id: 'set-auto' }),
          'Full auto-submit (no approval step)'),
        h('label', { class: 'switch' },
          h('input', { type: 'checkbox', checked: p.include_career_pages !== false, id: 'set-career' }),
          'Include company career pages'),
        h('div', { class: 'row', style: 'margin-top:16px' },
          h('button', { class: 'go', onclick: guard(saveSettings) }, 'Save settings'))),
      h('div', { class: 'card' },
        h('h3', { style: 'font-size:15px;margin-bottom:12px' }, 'Status'),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `AI scoring: ${S.ai_enabled ? 'Enabled' : 'Keyword-only (add ANTHROPIC_API_KEY for better scores)'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `Email alerts: ${S.email_enabled ? 'On' : 'Off'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0 0 8px' }, `Push alerts: ${S.push_enabled ? 'On' : 'Off'}`),
        h('p', { style: 'font-size:13px;color:var(--mute);margin:0' }, `Applied today: ${S.applied_today} / ${p.daily_cap || 25}`))));
}
async function saveSettings() {
  const data = {
    ...S.prefs,
    min_score: +$('#set-min').value,
    daily_cap: +$('#set-cap').value,
    auto_submit: $('#set-auto').checked,
    include_career_pages: $('#set-career').checked,
  };
  await api('/api/prefs', { method: 'PUT', json: { data } });
  toast('Settings saved'); await refresh();
}

/* ---------------- render + refresh ---------------- */
function renderView() {
  if (!S) return;
  if (view === 'jobs') buildJobsView();
  else if (view === 'resume') buildResumeView();
  else if (view === 'portals') buildPortalsView();
  else if (view === 'settings') buildSettingsView();
}

async function refresh() {
  S = await api('/api/state');
  // hydrate filters from saved prefs on first load
  if (!roles.length && S.prefs.roles?.length) roles = [...S.prefs.roles];
  if (!cities.length && S.prefs.locations?.length) cities = [...S.prefs.locations];
  if (!modes.length && S.prefs.work_modes?.length) modes = [...S.prefs.work_modes];
  if (!tiers.length && S.prefs.company_tiers?.length) tiers = [...S.prefs.company_tiers];
  if (!types.length && S.prefs.company_types?.length) types = [...S.prefs.company_types];
  if (!portalPick.length && S.prefs.portals?.length) portalPick = [...S.prefs.portals];
  else if (!portalPick.length) portalPick = S.portals.filter(p => p.auto).map(p => p.id);

  renderLeds(); renderAutopilot(); renderLog();
  const key = S.stats?.updated || '';
  if (key !== jobsKey || searching) {
    jobs = await api('/api/jobs').then(r => r.jobs || r || []).catch(() => []);
    jobsKey = key; searching = false;
  }
  renderView();
}

// poll while running
setInterval(() => { if (S?.run?.running) refresh(); }, 2000);
refresh().then(() => { renderNav(); renderView(); });
