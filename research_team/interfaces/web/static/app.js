/* research-team web console.
 *
 * The event log is the spine: selecting an event folds the workspace and the
 * conversation to that moment via /api/sessions/{id}/at/{n}. Everything else
 * (files, diffs, messages) is a projection of the currently selected point.
 *
 * No build step, no dependencies, no external requests.
 */
'use strict';

(function () {

/* ===================================================================== */
/* tiny dom helpers                                                      */
/* ===================================================================== */

function h(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const key in attrs) {
      const val = attrs[key];
      if (val === null || val === undefined || val === false) continue;
      if (key === 'class') node.className = val;
      else if (key === 'text') node.textContent = val;
      else if (key === 'style') node.setAttribute('style', val);
      else if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), val);
      else if (key === 'dataset') { for (const d in val) node.dataset[d] = val[d]; }
      else node.setAttribute(key, val === true ? '' : String(val));
    }
  }
  appendKids(node, children);
  return node;
}

function appendKids(node, kids) {
  if (kids === null || kids === undefined || kids === false) return;
  if (Array.isArray(kids)) { kids.forEach(function (k) { appendKids(node, k); }); return; }
  node.appendChild(kids instanceof Node ? kids : document.createTextNode(String(kids)));
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function slot(root, name) { return root.querySelector('[data-slot="' + name + '"]'); }

function tpl(id) {
  const t = document.getElementById(id);
  return t.content.firstElementChild.cloneNode(true);
}

/* ===================================================================== */
/* formatting                                                            */
/* ===================================================================== */

function shortId(id) { return typeof id === 'string' ? id.slice(0, 8) : '????????'; }

function parseTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function clockTime(iso) {
  const d = parseTime(iso);
  if (!d) return '--:--:--';
  return String(d.getHours()).padStart(2, '0') + ':' +
         String(d.getMinutes()).padStart(2, '0') + ':' +
         String(d.getSeconds()).padStart(2, '0');
}

function fullTime(iso) {
  const d = parseTime(iso);
  return d ? d.toLocaleString() : String(iso || 'unknown time');
}

function relTime(iso) {
  const d = parseTime(iso);
  if (!d) return 'unknown';
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 45) return 'just now';
  if (secs < 5400) return Math.round(secs / 60) + 'm ago';
  if (secs < 172800) return Math.round(secs / 3600) + 'h ago';
  return Math.round(secs / 86400) + 'd ago';
}

function bytes(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '-';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}

function plural(n, one, many) {
  const v = typeof n === 'number' ? n : 0;
  return v + ' ' + (v === 1 ? one : (many || one + 's'));
}

/* The backend names events in PascalCase (FileEdited, ToolResultRecorded...).
 * We never hard-code the full set — we bucket by substring so an event type
 * added later still gets a sane colour instead of vanishing. */
function eventKind(type) {
  const t = String(type || '').toLowerCase();
  if (t.indexOf('fail') >= 0 || t.indexOf('error') >= 0) return 'failure';
  if (t.indexOf('fork') >= 0 || t.indexOf('session') >= 0) return 'session';
  if (t.indexOf('tool') >= 0) return 'tool';
  if (t.indexOf('file') >= 0) return 'file';
  if (t.indexOf('message') >= 0) return 'message';
  if (t.indexOf('turn') >= 0) return 'turn';
  return 'other';
}

function humanType(type) {
  return String(type || 'Event').replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
}

function truncate(str, n) {
  const s = String(str === null || str === undefined ? '' : str);
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

/* Message content may be a plain string or langchain's block list. */
function contentText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map(function (block) {
      if (typeof block === 'string') return block;
      if (block && typeof block === 'object') return block.text || block.content || '';
      return '';
    }).filter(Boolean).join('\n');
  }
  if (content === null || content === undefined) return '';
  try { return JSON.stringify(content, null, 2); } catch (e) { return String(content); }
}

function firstArg(args) {
  if (!args || typeof args !== 'object') {
    return args === undefined || args === null ? '' : truncate(String(args), 70);
  }
  const keys = Object.keys(args);
  if (!keys.length) return '';
  const preferred = ['path', 'file_path', 'filename', 'pattern', 'command', 'query'];
  let key = keys[0];
  for (let i = 0; i < preferred.length; i++) {
    if (keys.indexOf(preferred[i]) >= 0) { key = preferred[i]; break; }
  }
  const val = args[key];
  const shown = typeof val === 'string' ? val : (function () {
    try { return JSON.stringify(val); } catch (e) { return String(val); }
  })();
  const extra = keys.length > 1 ? '  +' + (keys.length - 1) : '';
  return key + '=' + truncate(shown, 60) + extra;
}

/* ===================================================================== */
/* diff (line-based LCS)                                                 */
/* ===================================================================== */

function splitLines(s) {
  const str = String(s === null || s === undefined ? '' : s);
  const lines = str.split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

function diffLines(oldLines, newLines) {
  const n = oldLines.length, m = newLines.length;
  // Bail out to a whole-block replace on inputs large enough to make the
  // quadratic table unpleasant; the rendering stays correct, just coarser.
  if (n * m > 1500000) {
    const coarse = [];
    for (let i = 0; i < n; i++) coarse.push({ op: 'del', text: oldLines[i] });
    for (let j = 0; j < m; j++) coarse.push({ op: 'add', text: newLines[j] });
    return coarse;
  }
  const w = m + 1;
  const dp = new Int32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] = oldLines[i] === newLines[j]
        ? dp[(i + 1) * w + (j + 1)] + 1
        : Math.max(dp[(i + 1) * w + j], dp[i * w + (j + 1)]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (oldLines[i] === newLines[j]) { out.push({ op: 'ctx', text: oldLines[i] }); i++; j++; }
    else if (dp[(i + 1) * w + j] >= dp[i * w + (j + 1)]) { out.push({ op: 'del', text: oldLines[i] }); i++; }
    else { out.push({ op: 'add', text: newLines[j] }); j++; }
  }
  while (i < n) { out.push({ op: 'del', text: oldLines[i] }); i++; }
  while (j < m) { out.push({ op: 'add', text: newLines[j] }); j++; }
  return out;
}

const DIFF_CONTEXT = 3;

function renderDiff(oldText, newText) {
  const rows = diffLines(splitLines(oldText), splitLines(newText));
  const pre = h('pre', { class: 'diff' });
  const keep = new Array(rows.length);
  let anyChange = false;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].op === 'ctx') continue;
    anyChange = true;
    for (let k = Math.max(0, i - DIFF_CONTEXT); k <= Math.min(rows.length - 1, i + DIFF_CONTEXT); k++) {
      keep[k] = true;
    }
  }
  if (!anyChange) {
    pre.appendChild(h('span', { class: 'dl skip', text: '  (no textual change)' }));
    return pre;
  }
  let hidden = 0;
  for (let i = 0; i < rows.length; i++) {
    if (!keep[i]) { hidden++; continue; }
    if (hidden) {
      pre.appendChild(h('span', { class: 'dl skip', text: '  ⋯ ' + hidden + ' unchanged line' + (hidden === 1 ? '' : 's') }));
      hidden = 0;
    }
    const row = rows[i];
    const sign = row.op === 'add' ? '+' : row.op === 'del' ? '-' : ' ';
    pre.appendChild(h('span', { class: 'dl ' + row.op }, [
      h('span', { class: 'sig', text: sign }),
      row.text
    ]));
  }
  if (hidden) {
    pre.appendChild(h('span', { class: 'dl skip', text: '  ⋯ ' + hidden + ' unchanged line' + (hidden === 1 ? '' : 's') }));
  }
  return pre;
}

function renderCode(text) {
  const pre = h('pre', { class: 'code' });
  const lines = splitLines(text);
  if (!lines.length) {
    pre.appendChild(h('span', { class: 'dl skip', text: '  (empty file)' }));
    return pre;
  }
  lines.forEach(function (line, i) {
    pre.appendChild(h('span', {}, [
      h('span', { class: 'ln', text: String(i + 1) }),
      line + '\n'
    ]));
  });
  return pre;
}

/* ===================================================================== */
/* api                                                                   */
/* ===================================================================== */

const api = {
  get: function (path) { return request('GET', path, null); },
  post: function (path, body) { return request('POST', path, body === undefined ? {} : body); }
};

function request(method, path, body) {
  const init = { method: method, headers: { 'Accept': 'application/json' } };
  if (body !== null) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  return fetch(path, init).then(function (res) {
    return res.text().then(function (raw) {
      let parsed = null;
      if (raw) { try { parsed = JSON.parse(raw); } catch (e) { parsed = null; } }
      if (!res.ok) {
        const detail = (parsed && (parsed.detail || parsed.error)) || truncate(raw, 200) ||
                       (res.status + ' ' + res.statusText);
        const err = new Error(String(detail));
        err.status = res.status;
        throw err;
      }
      return parsed;
    });
  });
}

function encodePath(p) { return encodeURIComponent(String(p === null || p === undefined ? '' : p)); }

/* ===================================================================== */
/* state                                                                 */
/* ===================================================================== */

const state = {
  route: { name: 'tree', id: null },
  // tree view
  tree: null,
  sessionMeta: {},          // id -> row from /api/sessions
  treeError: null,
  // session view
  sessionId: null,
  head: null,               // /api/sessions/{id}
  events: [],
  at: null,                 // null === HEAD, else 1-based event index
  snapshot: null,           // /api/sessions/{id}/at/{n} (null when at HEAD)
  openPath: null,
  fileTab: 'content',       // 'content' | 'history'
  fileContent: null,
  fileContentAt: undefined, // the scrub point fileContent was fetched for
  fileHistory: null,
  fileError: null,
  fileMissing: false,       // 404: the path does not exist at this point
  openRevisions: {},        // history index -> bool
  sending: false,
  liveNote: '',
  sessionError: null,
  loadingSnapshot: false,
  freshIndices: {}
};

let root = null;            // current view element
let sessionEls = null;      // cached slots for the session view

/* ===================================================================== */
/* toasts                                                               */
/* ===================================================================== */

function toast(message, kind) {
  const box = document.getElementById('toasts');
  const node = h('div', { class: 'toast' + (kind ? ' ' + kind : ''), text: String(message) });
  box.appendChild(node);
  setTimeout(function () {
    node.style.transition = 'opacity .3s';
    node.style.opacity = '0';
    setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 320);
  }, kind === 'bad' ? 7000 : 3800);
}

function errorBox(title, message, retry) {
  return h('div', { class: 'error-box' }, [
    h('strong', { text: title }),
    String(message),
    retry ? h('div', {}, h('button', { class: 'btn btn-sm', onclick: retry }, 'Retry')) : null
  ]);
}

function emptyState(title, detail) {
  return h('div', { class: 'empty' }, [h('strong', { text: title }), detail || null]);
}

/* ===================================================================== */
/* routing                                                               */
/* ===================================================================== */

function parseHash() {
  const raw = String(location.hash || '').replace(/^#\/?/, '');
  const parts = raw.split('/').filter(Boolean);
  if (parts[0] === 's' && parts[1]) {
    const at = parts[2] === 'at' && parts[3] ? parseInt(parts[3], 10) : null;
    return { name: 'session', id: decodeURIComponent(parts[1]), at: isNaN(at) ? null : at };
  }
  return { name: 'tree', id: null, at: null };
}

function go(hash) {
  if (location.hash === hash) onRoute();
  else location.hash = hash;
}

function onRoute() {
  const next = parseHash();
  const changedSession = next.name !== state.route.name || next.id !== state.route.id;
  state.route = next;
  // Nothing scheduled against the previous view should fire against this one.
  clearTimeout(treeRefreshTimer); treeRefreshTimer = null;
  clearTimeout(freshSweepTimer); freshSweepTimer = null;
  if (next.name === 'session') {
    if (changedSession) {
      state.sessionId = next.id;
      state.head = null;
      state.events = [];
      state.at = next.at;
      state.snapshot = null;
      state.openPath = null;
      state.fileContent = null;
      state.fileContentAt = undefined;
      state.fileHistory = null;
      state.fileError = null;
      state.fileMissing = false;
      state.openRevisions = {};
      state.sessionError = null;
      state.liveNote = '';
      state.freshIndices = {};
      // A turn in flight belongs to the session we just left; the composer we
      // are about to mount is a different one and must start enabled.
      state.sending = false;
      state.loadingSnapshot = false;
      sessionEls = null;
      mountSessionView();
      loadSession();
    } else if (next.at !== state.at) {
      // Browser back/forward or a hand-edited hash: the timeline's selection,
      // dimming and HEAD marker are all derived from state.at, so re-render it.
      state.at = next.at;
      renderTimeline();
      renderScrubBar();
      loadSnapshot();
    }
  } else {
    state.sessionId = null;
    sessionEls = null;
    mountTreeView();
    loadTree();
  }
  renderCrumbs();
}

function renderCrumbs() {
  const box = document.getElementById('crumbs');
  clear(box);
  if (state.route.name !== 'session') {
    box.appendChild(h('span', { class: 'sep', text: 'fork tree' }));
    return;
  }
  box.appendChild(h('a', { href: '#/', text: 'sessions' }));
  box.appendChild(h('span', { class: 'sep', text: '/' }));
  box.appendChild(h('span', { class: 'sid', text: shortId(state.sessionId) }));
  const forked = state.head && state.head.forked_from;
  if (forked) {
    box.appendChild(h('span', { class: 'sep', text: '← forked from' }));
    box.appendChild(h('a', {
      href: '#/s/' + encodeURIComponent(forked),
      text: shortId(forked) + (state.head.forked_at ? ' @' + state.head.forked_at : '')
    }));
  }
}

/* ===================================================================== */
/* tree view                                                             */
/* ===================================================================== */

function mountTreeView() {
  root = tpl('tpl-tree-view');
  const app = document.getElementById('app');
  clear(app);
  app.appendChild(root);
  root.querySelector('[data-act="new-session"]').addEventListener('click', newSession);
  clear(slot(root, 'tree'));
  slot(root, 'tree').appendChild(h('div', { class: 'empty', text: 'loading sessions…' }));
}

function loadTree() {
  return Promise.all([
    api.get('/api/tree').catch(function (e) { return { __err: e }; }),
    api.get('/api/sessions').catch(function () { return []; })
  ]).then(function (res) {
    const tree = res[0], sessions = res[1];
    state.sessionMeta = {};
    if (Array.isArray(sessions)) {
      sessions.forEach(function (s) { if (s && s.id) state.sessionMeta[s.id] = s; });
    }
    if (tree && tree.__err) {
      state.tree = null;
      state.treeError = tree.__err.message;
    } else {
      state.tree = Array.isArray(tree) ? tree : [];
      state.treeError = null;
      // If /api/tree came back empty but sessions exist, fall back to the flat
      // list rather than showing a misleading "no sessions" state.
      if (!state.tree.length && Array.isArray(sessions) && sessions.length) {
        state.tree = sessions.map(function (s) {
          return Object.assign({}, s, { children: [] });
        });
      }
    }
    if (state.route.name === 'tree') renderTree();
  });
}

function renderTree() {
  if (!root) return;
  const box = slot(root, 'tree');
  if (!box) return;
  clear(box);

  if (state.treeError) {
    box.appendChild(errorBox('Could not load the session tree', state.treeError, function () {
      clear(box);
      box.appendChild(h('div', { class: 'empty', text: 'retrying…' }));
      loadTree();
    }));
    return;
  }
  if (!state.tree || !state.tree.length) {
    box.appendChild(emptyState('No sessions yet.',
      'Create one to start an event log, or run the CLI (uv run main.py) — sessions are shared.'));
    return;
  }
  box.appendChild(buildTreeList(state.tree, 0));
}

function buildTreeList(nodes, depth) {
  const ul = h('ul', { class: depth === 0 ? 'tree' : null });
  nodes.forEach(function (node) {
    if (!node || !node.id) return;
    const li = h('li');
    li.appendChild(treeNode(node));
    const kids = Array.isArray(node.children) ? node.children : [];
    if (kids.length) li.appendChild(buildTreeList(kids, depth + 1));
    ul.appendChild(li);
  });
  return ul;
}

function treeNode(node) {
  const meta = state.sessionMeta[node.id] || {};
  const failed = num(node.failed_turns, meta.failed_turns);
  const forkedAt = node.forked_at !== undefined && node.forked_at !== null
    ? node.forked_at : meta.forked_at;
  const first = node.first_message || meta.first_message;

  return h('button', {
    class: 'node',
    onclick: function () { go('#/s/' + encodeURIComponent(node.id)); }
  }, [
    h('div', { class: 'node-top' }, [
      h('span', { class: 'node-id', text: shortId(node.id) }),
      h('span', {
        class: 'node-msg' + (first ? '' : ' empty'),
        text: first ? truncate(first, 120) : 'no messages yet'
      }),
      forkedAt !== null && forkedAt !== undefined
        ? h('span', { class: 'chip chip-fork', text: 'forked @ event ' + forkedAt })
        : null,
      failed ? h('span', { class: 'chip chip-fail', text: plural(failed, 'failed turn') }) : null
    ]),
    h('div', { class: 'node-stats' }, [
      h('span', {}, [h('b', { text: String(num(node.turns, meta.turns) || 0) }), ' turns']),
      h('span', {}, [h('b', { text: String(num(node.files, meta.files) || 0) }), ' files']),
      h('span', { title: fullTime(node.started_at || meta.started_at),
                  text: relTime(node.started_at || meta.started_at) })
    ])
  ]);
}

function num(a, b) {
  if (typeof a === 'number') return a;
  if (typeof b === 'number') return b;
  return null;
}

let creatingSession = false;

function newSession(ev) {
  if (creatingSession) return;
  creatingSession = true;
  const button = ev && ev.currentTarget;
  if (button) button.disabled = true;
  api.post('/api/sessions', {}).then(function (res) {
    if (res && res.id) go('#/s/' + encodeURIComponent(res.id));
    else toast('Session created but no id was returned.', 'bad');
  }).catch(function (e) {
    toast('Could not create session: ' + e.message, 'bad');
  }).then(function () {
    creatingSession = false;
    if (button && button.isConnected) button.disabled = false;
  });
}

/* ===================================================================== */
/* session view                                                          */
/* ===================================================================== */

function mountSessionView() {
  root = tpl('tpl-session-view');
  const app = document.getElementById('app');
  clear(app);
  app.appendChild(root);
  sessionEls = {
    scrubbar: slot(root, 'scrubbar'),
    timeline: slot(root, 'timeline'),
    timelineMeta: slot(root, 'timeline-meta'),
    files: slot(root, 'files'),
    fileview: slot(root, 'fileview'),
    workspaceMeta: slot(root, 'workspace-meta'),
    conversation: slot(root, 'conversation'),
    convMeta: slot(root, 'conv-meta'),
    composer: slot(root, 'composer'),
    input: slot(root, 'input'),
    send: slot(root, 'send'),
    hint: slot(root, 'composer-hint')
  };
  sessionEls.composer.addEventListener('submit', onSend);
  sessionEls.input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); onSend(ev); }
  });
  sessionEls.timeline.appendChild(h('div', { class: 'empty', text: 'loading event log…' }));
  renderComposer();
}

function loadSession() {
  const id = state.sessionId;
  return Promise.all([
    api.get('/api/sessions/' + encodeURIComponent(id)),
    api.get('/api/sessions/' + encodeURIComponent(id) + '/events')
  ]).then(function (res) {
    if (state.sessionId !== id) return;
    state.head = res[0] || {};
    state.events = Array.isArray(res[1]) ? res[1] : [];
    state.sessionError = null;
    renderCrumbs();
    renderTimeline();
    if (state.at !== null) loadSnapshot();
    else { state.snapshot = null; renderWorkspace(); renderConversation(); renderScrubBar(); }
  }).catch(function (e) {
    if (state.sessionId !== id) return;
    state.sessionError = e.message;
    renderSessionError();
  });
}

function renderSessionError() {
  if (!sessionEls) return;
  [sessionEls.timeline, sessionEls.conversation].forEach(function (el) { clear(el); });
  clear(sessionEls.files); clear(sessionEls.fileview);
  sessionEls.timeline.appendChild(errorBox('Session unavailable', state.sessionError, function () {
    clear(sessionEls.timeline);
    sessionEls.timeline.appendChild(h('div', { class: 'empty', text: 'retrying…' }));
    loadSession();
  }));
}

/* --- scrubbing --------------------------------------------------------- */

function selectEvent(index) {
  // index === null means HEAD (live)
  const target = index === null ? null : index;
  state.at = target;
  const base = '#/s/' + encodeURIComponent(state.sessionId);
  const hash = target === null ? base : base + '/at/' + target;
  if (location.hash !== hash) {
    state.route.at = target;
    history.replaceState(null, '', hash);
  }
  renderTimeline();
  renderScrubBar();
  loadSnapshot();
}

function loadSnapshot() {
  if (state.at === null) {
    state.snapshot = null;
    state.loadingSnapshot = false;
    renderWorkspace();
    renderConversation();
    renderScrubBar();
    renderComposer();
    refreshOpenFile();
    return Promise.resolve();
  }
  const id = state.sessionId, at = state.at;
  state.loadingSnapshot = true;
  renderScrubBar();
  renderComposer();
  return api.get('/api/sessions/' + encodeURIComponent(id) + '/at/' + at)
    .then(function (snap) {
      if (state.sessionId !== id || state.at !== at) return;
      state.snapshot = snap || {};
      state.loadingSnapshot = false;
      renderWorkspace();
      renderConversation();
      renderScrubBar();
      renderComposer();
      refreshOpenFile();
    })
    .catch(function (e) {
      if (state.sessionId !== id || state.at !== at) return;
      state.loadingSnapshot = false;
      state.snapshot = { __error: e.message, files: [], messages: [] };
      renderWorkspace();
      renderConversation();
      renderScrubBar();
      renderComposer();
    });
}

/* The object the workspace/conversation panels read from. */
function view() {
  return state.at === null ? (state.head || {}) : (state.snapshot || {});
}

function isHistorical() { return state.at !== null; }

/* Total events at HEAD. The backend reports `event_count`; the fetched log
 * length is the fallback (and the two can disagree briefly mid-turn). */
function totalEvents() {
  const declared = state.head && state.head.event_count;
  return typeof declared === 'number'
    ? Math.max(declared, state.events.length)
    : state.events.length;
}

function renderScrubBar() {
  if (!sessionEls) return;
  const bar = sessionEls.scrubbar;
  clear(bar);
  bar.className = 'scrub-bar' + (isHistorical() ? ' historical' : '');

  if (!isHistorical()) {
    bar.appendChild(h('span', { class: 'scrub-state live' }, [
      h('span', { class: 'conn-dot', style: 'background:var(--k-file)' }), 'live · head'
    ]));
    const head = state.head || {};
    bar.appendChild(h('span', { class: 'scrub-detail' }, [
      plural(totalEvents(), 'event') + ' · ' +
      plural(head.turn_index || 0, 'turn') + ' · ' +
      plural((head.files || []).length, 'file') +
      (head.model_name ? ' · ' + head.model_name : '') +
      (head.failed_turns ? ' · ' + plural(head.failed_turns, 'failed turn') : '')
    ]));
  } else {
    const ev = eventAt(state.at);
    bar.appendChild(h('span', { class: 'scrub-state hist' }, [
      h('span', { class: 'conn-dot', style: 'background:var(--accent)' }), 'time travel'
    ]));
    bar.appendChild(h('span', { class: 'scrub-detail' },
      'viewing the workspace as of event ' + state.at + ' of ' + totalEvents() +
      (ev ? ' — ' + humanType(ev.type) + (ev.summary ? ': ' + truncate(ev.summary, 90) : '') : '') +
      (state.loadingSnapshot ? '  …folding' : '')));
  }

  const actions = h('div', { class: 'scrub-actions' });
  if (isHistorical()) {
    actions.appendChild(h('button', {
      class: 'btn btn-sm',
      onclick: function (e) { forkAt(state.at, e.currentTarget); }
    }, 'Fork here'));
    actions.appendChild(h('button', {
      class: 'btn btn-sm btn-accent',
      onclick: function () { selectEvent(null); }
    }, 'Back to live'));
  }
  bar.appendChild(actions);
}

function eventAt(index) {
  for (let i = 0; i < state.events.length; i++) {
    if (state.events[i] && state.events[i].index === index) return state.events[i];
  }
  return state.events[index - 1] || null;
}

/* --- timeline ---------------------------------------------------------- */

function renderTimeline() {
  if (!sessionEls) return;
  const box = sessionEls.timeline;
  clear(box);
  sessionEls.timelineMeta.textContent = state.events.length
    ? plural(state.events.length, 'event') : '';

  if (!state.events.length) {
    box.appendChild(emptyState('The log is empty.',
      'Send a turn below — every message, tool call and file write lands here in order.'));
    return;
  }

  const list = h('div', { class: 'timeline', tabindex: '0', role: 'listbox',
                          id: 'timeline-listbox',
                          'aria-label': 'event timeline' });
  list.addEventListener('keydown', onTimelineKey);

  state.events.forEach(function (ev, i) {
    const index = typeof ev.index === 'number' ? ev.index : i + 1;
    const kind = eventKind(ev.type);
    const selected = state.at === index;
    const future = isHistorical() && index > state.at;
    const summary = ev.summary === null || ev.summary === undefined ? '' : String(ev.summary);
    const row = h('div', {
      class: 'ev k-' + kind + (selected ? ' selected' : '') + (future ? ' future' : '') +
             (ev.is_error ? ' is-error' : '') + (state.freshIndices[index] ? ' fresh' : ''),
      role: 'option',
      id: 'ev-' + index,
      'aria-selected': selected ? 'true' : 'false',
      dataset: { index: String(index) },
      title: humanType(ev.type) + '\n' + fullTime(ev.occurred_at) +
             (summary ? '\n' + summary : ''),
      onclick: function () { selectEvent(index); }
    }, [
      h('span', { class: 'ev-idx', text: String(index) }),
      h('span', { class: 'ev-rail' }),
      h('span', { class: 'ev-main' }, [
        h('span', { class: 'ev-type' }, [
          humanType(ev.type),
          typeof ev.turn_index === 'number' ? h('span', { class: 'ev-path' }, ' · turn ' + ev.turn_index) : null
        ]),
        h('span', { class: 'ev-summary' }, [
          // The summary stands alone (it has to, for the live feed), so for a
          // file event it already opens with the path -- don't print it twice.
          ev.path && summary.indexOf(ev.path) !== 0
            ? h('span', { class: 'ev-path', text: ev.path + '  ' }) : null,
          summary ? truncate(summary, 160) : (ev.path ? '' : '—')
        ])
      ]),
      h('span', { class: 'ev-time', text: clockTime(ev.occurred_at) }),
      // Out of the tab order and hidden from AT: it duplicates the scrub bar's
      // "Fork here", and a focusable control inside a role="option" is invalid.
      h('button', {
        class: 'btn btn-ghost ev-fork',
        tabindex: '-1',
        'aria-hidden': 'true',
        title: 'fork a new session at event ' + index,
        onclick: function (e) { e.stopPropagation(); forkAt(index, e.currentTarget); }
      }, 'fork here')
    ]);
    list.appendChild(row);
  });

  list.appendChild(h('div', {
    class: 'head-marker' + (state.at === null ? ' selected' : ''),
    role: 'option',
    id: 'ev-head',
    'aria-selected': state.at === null ? 'true' : 'false',
    onclick: function () { selectEvent(null); }
  }, state.at === null ? '● HEAD — live' : '○ HEAD — click to return to live'));

  // Focus stays on the listbox; this is what announces the moving selection.
  list.setAttribute('aria-activedescendant', state.at === null ? 'ev-head' : 'ev-' + state.at);

  box.appendChild(list);
  scrollSelectedIntoView();
}

function scrollSelectedIntoView() {
  if (!sessionEls) return;
  const el = sessionEls.timeline.querySelector('.ev.selected, .head-marker.selected');
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
}

function onTimelineKey(ev) {
  const total = state.events.length;
  if (!total) return;
  const cur = state.at === null ? total + 1 : state.at;
  let next = null;
  if (ev.key === 'ArrowDown' || ev.key === 'j') next = Math.min(cur + 1, total + 1);
  else if (ev.key === 'ArrowUp' || ev.key === 'k') next = Math.max(cur - 1, 1);
  else if (ev.key === 'Home') next = 1;
  else if (ev.key === 'End') next = total + 1;
  else if (ev.key === 'Escape') next = total + 1;
  else return;
  ev.preventDefault();
  // The document-level Escape handler is on the bubble phase too; without this
  // one keypress would fold twice.
  ev.stopPropagation();
  const target = next > total ? null : next;
  if (target !== state.at) selectEvent(target);
  const list = sessionEls && sessionEls.timeline.querySelector('.timeline');
  if (list) list.focus();
}

/* --- workspace --------------------------------------------------------- */

function renderWorkspace() {
  if (!sessionEls) return;
  const v = view();
  const files = Array.isArray(v.files) ? v.files : [];
  const box = sessionEls.files;
  clear(box);

  sessionEls.workspaceMeta.textContent = isHistorical()
    ? '@ event ' + state.at
    : 'head';

  if (v.__error) {
    box.appendChild(errorBox('Could not fold to event ' + state.at, v.__error, function () {
      loadSnapshot();
    }));
    clear(sessionEls.fileview);
    return;
  }

  if (!files.length) {
    box.appendChild(emptyState('No files.', isHistorical()
      ? 'The workspace was empty at event ' + state.at + '.'
      : 'The agent has not written anything yet.'));
  } else {
    const list = h('div', { tabindex: '0', role: 'listbox', id: 'files-listbox',
                            'aria-label': 'files' });
    list.addEventListener('keydown', onFilesKey);
    files.forEach(function (f, i) {
      const path = f && f.path ? f.path : String(f);
      const selected = state.openPath === path;
      if (selected) list.setAttribute('aria-activedescendant', 'file-' + i);
      list.appendChild(h('div', {
        class: 'file-row' + (selected ? ' selected' : ''),
        role: 'option',
        id: 'file-' + i,
        'aria-selected': selected ? 'true' : 'false',
        dataset: { path: path },
        onclick: function () { openFile(path); }
      }, [
        h('span', { class: 'file-path', text: path, title: path }),
        h('span', { class: 'file-meta', text:
          (typeof f.revisions === 'number' ? 'r' + f.revisions + '  ' : '') + bytes(f.size) })
      ]));
    });
    box.appendChild(list);
    // Keep the open file honest: if it does not exist at this point, drop it.
    if (state.openPath && !files.some(function (f) { return (f && f.path) === state.openPath; })) {
      const gone = state.openPath;
      clear(sessionEls.fileview);
      sessionEls.fileview.appendChild(emptyState('Not in the workspace here.',
        gone + ' does not exist as of event ' + state.at + '.'));
      return;
    }
  }
  renderFileView();
}

function onFilesKey(ev) {
  const rows = Array.prototype.slice.call(ev.currentTarget.querySelectorAll('.file-row'));
  if (!rows.length) return;
  let idx = rows.findIndex(function (r) { return r.classList.contains('selected'); });
  if (ev.key === 'ArrowDown') idx = Math.min(idx + 1, rows.length - 1);
  else if (ev.key === 'ArrowUp') idx = Math.max(idx - 1, 0);
  else if (ev.key === 'Enter') { if (idx < 0) idx = 0; }
  else return;
  ev.preventDefault();
  ev.stopPropagation();
  const path = rows[idx].dataset.path;
  // Enter on the already-open file re-reads it; arrows only move the selection.
  if (path !== state.openPath) openFile(path);
  else if (ev.key === 'Enter') loadFile();
  // openFile re-renders the pane, so the list we were called on is now
  // detached -- re-query from sessionEls.files, which is stable.
  const list = sessionEls && sessionEls.files.querySelector('[role="listbox"]');
  if (!list) return;
  const selected = list.querySelector('.file-row.selected');
  if (selected && selected.scrollIntoView) selected.scrollIntoView({ block: 'nearest' });
  list.focus();
}

function openFile(path) {
  const changed = state.openPath !== path;
  state.openPath = path;
  if (changed) {
    state.fileContent = null;
    state.fileContentAt = undefined;
    state.fileHistory = null;
    state.fileError = null;
    state.fileMissing = false;
    state.openRevisions = {};
  }
  renderWorkspace();
  loadFile();
}

function refreshOpenFile() {
  if (state.openPath) loadFile();
}

function loadFile() {
  const id = state.sessionId, path = state.openPath, tab = state.fileTab, at = state.at;
  if (!path) return Promise.resolve();
  const base = '/api/sessions/' + encodeURIComponent(id);
  // Contents are addressed by scrub point; history is the whole log for a path.
  const url = tab === 'history'
    ? base + '/files/history?path=' + encodePath(path)
    : base + '/files?path=' + encodePath(path) + (at === null ? '' : '&at=' + at);
  state.fileError = null;
  state.fileMissing = false;
  return api.get(url).then(function (res) {
    if (state.sessionId !== id || state.openPath !== path) return;
    if (tab === 'history') {
      state.fileHistory = Array.isArray(res) ? res : [];
    } else {
      if (state.at !== at) return;   // scrubbed on past this response
      state.fileContent = res && typeof res === 'object' ? res.content : res;
      state.fileContentAt = at;
    }
    renderFileView();
  }).catch(function (e) {
    if (state.sessionId !== id || state.openPath !== path) return;
    if (tab === 'content' && state.at !== at) return;
    // A 404 here is information, not a failure: the path simply had not been
    // written yet (or had been removed) at this point in the log.
    if (e.status === 404) { state.fileMissing = true; state.fileContent = null; }
    else state.fileError = e.message;
    renderFileView();
  });
}

function renderFileView() {
  if (!sessionEls) return;
  const box = sessionEls.fileview;
  clear(box);
  if (!state.openPath) {
    box.appendChild(emptyState('No file selected.',
      'Pick a file above to read it as of the selected event, or open its full revision history.'));
    return;
  }

  const head = h('div', { class: 'file-view-head' }, [
    h('span', { class: 'fv-path', text: state.openPath, title: state.openPath }),
    h('div', { class: 'tabs' }, [
      tabButton('content', 'contents'),
      tabButton('history', 'history')
    ])
  ]);
  box.appendChild(head);

  if (state.fileError) {
    box.appendChild(errorBox('Could not read this file', state.fileError, loadFile));
    return;
  }

  if (state.fileTab === 'content') {
    if (state.fileMissing) {
      box.appendChild(emptyState(
        isHistorical() ? 'Not in the workspace here.' : 'No such file.',
        isHistorical()
          ? state.openPath + ' did not exist at event ' + state.at + '.'
          : state.openPath + ' is not in the workspace at HEAD.'));
      return;
    }
    if (state.fileContent === null || state.fileContent === undefined) {
      box.appendChild(h('div', { class: 'empty', text: 'loading…' }));
      return;
    }
    // The server folds the file to the scrub point for us; while a newer point
    // is in flight the previous contents stay up, dimmed, rather than flashing.
    const stale = state.fileContentAt !== state.at;
    const code = renderCode(state.fileContent);
    if (stale) code.classList.add('stale');
    box.appendChild(code);
    return;
  }

  const hist = state.fileHistory;
  if (hist === null) { box.appendChild(h('div', { class: 'empty', text: 'loading…' })); return; }
  if (!hist.length) {
    box.appendChild(emptyState('No recorded revisions.', 'Nothing in the log touched this path.'));
    return;
  }
  hist.forEach(function (rev, i) {
    box.appendChild(renderRevision(rev, i, hist));
  });
}

function renderRevision(rev, i, all) {
  const kind = eventKind(rev.type);
  const open = state.openRevisions[i] !== false; // expanded by default
  const wrap = h('div', { class: 'rev k-' + kind });
  wrap.appendChild(h('div', {
    class: 'rev-head',
    onclick: function () { state.openRevisions[i] = !open; renderFileView(); }
  }, [
    h('span', { text: open ? '▾' : '▸' }),
    h('span', { class: 'rev-idx', text: '#' + (rev.index !== undefined ? rev.index : '?') }),
    h('span', { class: 'rev-type', text: humanType(rev.type) }),
    rev.replace_all ? h('span', { class: 'chip', text: 'replace_all' }) : null,
    h('span', { class: 'rev-time', text: clockTime(rev.occurred_at), title: fullTime(rev.occurred_at) })
  ]));
  if (!open) return wrap;

  const body = h('div', { class: 'rev-body' });
  const hasIntent = typeof rev.old_string === 'string' && typeof rev.new_string === 'string';
  if (hasIntent) {
    body.appendChild(renderDiff(rev.old_string, rev.new_string));
  } else {
    // No edit intent recorded (a write, or the first revision): diff against
    // whatever the previous revision left behind so the change is still visible.
    const prev = i > 0 ? all[i - 1] : null;
    const before = prev && typeof prev.content === 'string' ? prev.content : '';
    const after = typeof rev.content === 'string' ? rev.content : '';
    if (!before && after) {
      body.appendChild(h('div', { class: 'rev-note', text: 'created — full contents:' }));
      body.appendChild(renderDiff('', after));
    } else if (!after && before) {
      body.appendChild(h('div', { class: 'rev-note', text: 'removed' }));
      body.appendChild(renderDiff(before, ''));
    } else {
      body.appendChild(renderDiff(before, after));
    }
  }
  wrap.appendChild(body);
  return wrap;
}

function tabButton(id, label) {
  return h('button', {
    class: 'tab' + (state.fileTab === id ? ' active' : ''),
    onclick: function () {
      if (state.fileTab === id) return;
      state.fileTab = id;
      renderFileView();
      loadFile();
    }
  }, label);
}

/* --- conversation ------------------------------------------------------ */

function renderConversation() {
  if (!sessionEls) return;
  const box = sessionEls.conversation;
  const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  clear(box);

  const v = view();
  const messages = Array.isArray(v.messages) ? v.messages : [];
  sessionEls.convMeta.textContent = messages.length
    ? plural(messages.length, 'message') + (isHistorical() ? ' @ ' + state.at : '')
    : '';

  if (v.__error) { box.appendChild(errorBox('Unavailable', v.__error, loadSnapshot)); return; }

  if (!messages.length) {
    box.appendChild(emptyState('No conversation yet.', isHistorical()
      ? 'Nothing had been said by event ' + state.at + '.'
      : 'Send the first turn below.'));
    return;
  }

  const conv = h('div', { class: 'conv' });
  messages.forEach(function (m) { conv.appendChild(renderMessage(m)); });
  box.appendChild(conv);
  if (stick) box.scrollTop = box.scrollHeight;
}

function renderMessage(m) {
  const role = (m && m.role) || 'assistant';
  const errored = !!(m && m.is_error);
  const calls = Array.isArray(m && m.tool_calls) ? m.tool_calls : [];
  const text = contentText(m && m.content);

  const wrap = h('div', {
    class: 'msg msg-' + (role === 'user' || role === 'tool' ? role : 'assistant') +
           (errored ? ' errored' : '')
  });
  wrap.appendChild(h('div', { class: 'msg-head' }, [
    h('span', { text: role }),
    errored ? h('span', { class: 'chip chip-fail', text: 'error' }) : null
  ]));

  if (text) {
    wrap.appendChild(h('div', {
      class: 'msg-body' + (role === 'tool' ? ' mono' : ''),
      text: role === 'tool' ? truncate(text, 4000) : text
    }));
  } else if (!calls.length) {
    wrap.appendChild(h('div', { class: 'msg-body mono', text: '(no content)' }));
  }

  if (calls.length) {
    const box = h('div', { class: 'calls' });
    calls.forEach(function (c) {
      const arg = firstArg(c && c.args);
      box.appendChild(h('div', { class: 'call', title: safeJson(c && c.args) }, [
        h('b', { text: (c && c.name) || 'tool' }),
        arg ? h('span', { class: 'arg', text: '  ' + arg }) : null
      ]));
    });
    wrap.appendChild(box);
  }
  return wrap;
}

function safeJson(v) {
  try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
}

/* --- turns ------------------------------------------------------------- */

function renderComposer() {
  if (!sessionEls) return;
  const busy = state.sending;
  sessionEls.input.disabled = busy;
  sessionEls.send.disabled = busy;
  sessionEls.send.textContent = busy ? 'Running…' : 'Send turn';
  const hint = sessionEls.hint;
  clear(hint);
  hint.className = 'composer-hint' + (busy ? ' busy' : '') + (isHistorical() && !busy ? ' warn' : '');
  if (busy) {
    hint.appendChild(h('span', { class: 'spinner' }));
    hint.appendChild(document.createTextNode(state.liveNote || 'turn in flight — this can take a minute'));
  } else if (isHistorical()) {
    hint.textContent = 'viewing history — a turn appends to HEAD; fork to branch from here';
  } else {
    hint.textContent = 'Ctrl+Enter to send · ↑/↓ in the log to scrub';
  }
}

function onSend(ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  if (state.sending) return;
  const input = sessionEls.input;
  const text = String(input.value || '').trim();
  if (!text) return;
  const id = state.sessionId;

  state.sending = true;
  state.liveNote = 'turn in flight — this can take a minute';
  renderComposer();

  api.post('/api/sessions/' + encodeURIComponent(id) + '/turns', { input: text })
    .then(function () {
      if (state.sessionId === id) input.value = '';
      toast('Turn complete.', 'good');
    })
    .catch(function (e) {
      toast('Turn failed: ' + e.message, 'bad');
    })
    .then(function () {
      // Always clear the in-flight flag, even if the user navigated away while
      // the turn ran -- otherwise the composer stays disabled for good.
      state.sending = false;
      state.liveNote = '';
      if (state.sessionId !== id) return;
      renderComposer();
      // The turn is atomic, so refetch the whole log rather than trusting the
      // events that streamed in mid-flight.
      return loadSession();
    });
}

let forking = false;

function forkAt(index, button) {
  if (forking) return;
  forking = true;
  if (button) button.disabled = true;
  const id = state.sessionId;
  api.post('/api/sessions/' + encodeURIComponent(id) + '/forks', { at: index })
    .then(function (res) {
      if (res && res.id) {
        toast('Forked at event ' + index + ' → ' + shortId(res.id), 'good');
        go('#/s/' + encodeURIComponent(res.id));
      } else {
        toast('Fork returned no session id.', 'bad');
      }
    })
    .catch(function (e) { toast('Fork failed: ' + e.message, 'bad'); })
    .then(function () {
      forking = false;
      if (button && button.isConnected) button.disabled = false;
    });
}

/* ===================================================================== */
/* server-sent events                                                    */
/* ===================================================================== */

let stream = null;
let backoff = 1000;
let treeRefreshTimer = null;
let freshSweepTimer = null;

const FRESH_MS = 1500;

function setConn(stateName, label) {
  const el = document.getElementById('conn');
  if (!el) return;
  el.dataset.state = stateName;
  el.querySelector('.conn-label').textContent = label;
}

function connect() {
  if (typeof EventSource === 'undefined') { setConn('down', 'no sse'); return; }
  try {
    stream = new EventSource('/api/stream');
  } catch (e) {
    setConn('down', 'stream error');
    scheduleReconnect();
    return;
  }
  stream.onopen = function () {
    const reconnected = backoff !== 1000;
    backoff = 1000;
    setConn('open', 'live');
    // The stream has no replay cursor, so anything appended while we were
    // disconnected was missed — resync whatever view is open.
    if (reconnected) {
      if (state.route.name === 'session' && !state.sending) loadSession();
      else if (state.route.name === 'tree') loadTree();
    }
  };
  stream.onmessage = function (msg) {
    let payload = null;
    try { payload = JSON.parse(msg.data); } catch (e) { return; }
    if (payload) onStreamEvent(payload);
  };
  stream.onerror = function () {
    if (stream) { stream.close(); stream = null; }
    setConn('down', 'reconnecting');
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  const wait = backoff;
  backoff = Math.min(backoff * 2, 30000);
  setTimeout(connect, wait);
}

function onStreamEvent(payload) {
  if (state.route.name === 'tree') {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(loadTree, 400);
    return;
  }
  if (!payload.session_id || payload.session_id !== state.sessionId) {
    // Another session moved; the tree will be refetched when we go back.
    return;
  }
  const index = typeof payload.index === 'number' ? payload.index : state.events.length + 1;
  const known = state.events.some(function (e) { return e.index === index; });
  if (!known) {
    // The stream payload is the full timeline row, so the appended event needs
    // no follow-up fetch to render its path, turn or error state correctly.
    state.events.push({
      index: index,
      type: payload.type,
      occurred_at: payload.occurred_at,
      summary: payload.summary,
      path: payload.path === undefined ? null : payload.path,
      turn_index: payload.turn_index === undefined ? null : payload.turn_index,
      is_error: payload.is_error === undefined ? null : payload.is_error
    });
    state.events.sort(function (a, b) { return (a.index || 0) - (b.index || 0); });
    state.freshIndices[index] = Date.now();
    scheduleFreshSweep();
    renderTimeline();
    renderScrubBar();
  }
  if (state.sending) {
    state.liveNote = truncate(humanType(payload.type) + (payload.summary ? ': ' + payload.summary : ''), 90);
    renderComposer();
  }
}

/* Drop expired highlights and repaint once, so the flash does not linger until
 * some unrelated render happens to clear it. */
function scheduleFreshSweep() {
  if (freshSweepTimer) return;
  freshSweepTimer = setTimeout(function () {
    freshSweepTimer = null;
    const now = Date.now();
    let remaining = 0;
    Object.keys(state.freshIndices).forEach(function (key) {
      if (now - state.freshIndices[key] >= FRESH_MS) delete state.freshIndices[key];
      else remaining++;
    });
    if (state.route.name === 'session') renderTimeline();
    if (remaining) scheduleFreshSweep();
  }, FRESH_MS + 50);
}

/* ===================================================================== */
/* boot                                                                  */
/* ===================================================================== */

window.addEventListener('hashchange', onRoute);
window.addEventListener('error', function (e) {
  if (e && e.message) toast('UI error: ' + e.message, 'bad');
});

// Global "back to live". onTimelineKey handles Escape itself and stops the
// event, so a keypress with the timeline focused never folds twice.
document.addEventListener('keydown', function (ev) {
  if (ev.key !== 'Escape') return;
  if (state.route.name !== 'session' || !isHistorical()) return;
  if (sessionEls && document.activeElement === sessionEls.input) return;
  selectEvent(null);
});

setConn('init', 'connecting');
onRoute();
connect();

})();
