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
  // Housekeeping, before the generic buckets: nothing else should claim it.
  if (t.indexOf('compact') >= 0) return 'compaction';
  if (t.indexOf('fail') >= 0 || t.indexOf('error') >= 0) return 'failure';
  if (t.indexOf('fork') >= 0 || t.indexOf('session') >= 0) return 'session';
  if (t.indexOf('tool') >= 0) return 'tool';
  if (t.indexOf('file') >= 0) return 'file';
  if (t.indexOf('message') >= 0) return 'message';
  if (t.indexOf('turn') >= 0) return 'turn';
  return 'other';
}

/* A deliberate cancellation arrives as a TurnFailed carrying cancelled:true.
 * It is an outcome, not a crash, so it must never render as a failure. */
function isCancellation(ev) {
  return !!ev && ev.cancelled === true;
}

/* TurnCompleted / TurnFailed both end a turn. */
function isTurnEnd(type) {
  const t = String(type || '').toLowerCase();
  return t.indexOf('turn') >= 0 && (t.indexOf('completed') >= 0 || t.indexOf('failed') >= 0);
}

/* The most recent TurnFailed row, if any -- where catch-up's `discarded`
 * content (itself index-less) belongs. */
function lastFailedTurnIndex() {
  for (let i = state.events.length - 1; i >= 0; i--) {
    const t = String(state.events[i].type || '').toLowerCase();
    if (t.indexOf('turn') >= 0 && t.indexOf('failed') >= 0) return state.events[i].index;
  }
  return null;
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

/* --- markdown ------------------------------------------------------------
 * A small block+inline renderer for the file viewer. It builds DOM nodes
 * directly rather than assembling HTML, so file contents -- which are written
 * by tools and models, not by us -- can never become markup. It covers what
 * the docs in this repo actually use; anything it does not recognise falls
 * through as literal text, which is the safe failure for a *viewer*. */

function isMarkdownPath(path) {
  return /\.(md|markdown|mdown|mkd)$/i.test(path || '');
}

function renderMarkdown(text) {
  const box = h('div', { class: 'md' });
  const lines = splitLines(text);
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i++; continue; }

    // fenced code -- opening fence wins over every inline rule inside it
    const fence = /^\s*(```+|~~~+)\s*([^\s`]*)/.exec(line);
    if (fence) {
      const marker = fence[1][0];
      const body = [];
      i++;
      while (i < lines.length &&
             !new RegExp('^\\s*' + marker + '{' + fence[1].length + ',}\\s*$').test(lines[i])) {
        body.push(lines[i]); i++;
      }
      i++; // consume closing fence (or run off the end, which is fine)
      const pre = h('pre', { class: 'md-code' }, [h('code', { text: body.join('\n') })]);
      if (fence[2]) pre.dataset.lang = fence[2];
      box.appendChild(pre);
      continue;
    }

    const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) {
      box.appendChild(mdInline(h('h' + heading[1].length, { class: 'md-h' }), heading[2]));
      i++; continue;
    }

    if (/^\s*(([-*_])\s*)\2{2,}\s*$/.test(line)) {
      box.appendChild(h('hr', { class: 'md-hr' })); i++; continue;
    }

    if (/^\s*>/.test(line)) {
      const quoted = [];
      while (i < lines.length && (/^\s*>/.test(lines[i]) || (quoted.length && lines[i].trim()))) {
        quoted.push(lines[i].replace(/^\s*>\s?/, '')); i++;
      }
      box.appendChild(h('blockquote', { class: 'md-quote' }, [renderMarkdown(quoted.join('\n'))]));
      continue;
    }

    // table: a header row followed by a delimiter row of dashes
    if (line.indexOf('|') !== -1 && i + 1 < lines.length &&
        /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1]) && lines[i + 1].indexOf('-') !== -1) {
      const table = h('table', { class: 'md-table' });
      const thead = h('thead');
      thead.appendChild(mdRow(splitTableRow(line), 'th'));
      table.appendChild(thead);
      const tbody = h('tbody');
      i += 2;
      while (i < lines.length && lines[i].indexOf('|') !== -1 && lines[i].trim()) {
        tbody.appendChild(mdRow(splitTableRow(lines[i]), 'td')); i++;
      }
      table.appendChild(tbody);
      box.appendChild(table);
      continue;
    }

    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const consumed = mdList(lines, i, box);
      i = consumed;
      continue;
    }

    // paragraph: runs until a blank line or the start of another block
    const para = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      para.push(lines[i].trim()); i++;
    }
    box.appendChild(mdInline(h('p', { class: 'md-p' }), para.join(' ')));
  }

  if (!box.firstChild) box.appendChild(h('div', { class: 'empty', text: '(empty file)' }));
  return box;
}

function isBlockStart(line) {
  return /^\s*(#{1,6}\s|>|```|~~~|([-*+]|\d+[.)])\s)/.test(line) ||
         /^\s*(([-*_])\s*)\2{2,}\s*$/.test(line);
}

function splitTableRow(line) {
  return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|')
    .map(function (c) { return c.trim(); });
}

function mdRow(cells, tag) {
  const tr = h('tr');
  cells.forEach(function (c) { tr.appendChild(mdInline(h(tag), c)); });
  return tr;
}

/* Lists are indentation-nested. Returns the index of the first line after the
 * list so the caller can carry on from there. */
function mdList(lines, start, box) {
  const first = /^(\s*)([-*+]|\d+[.)])\s+/.exec(lines[start]);
  const baseIndent = first[1].length;
  const ordered = /\d/.test(first[2]);
  const list = h(ordered ? 'ol' : 'ul', { class: 'md-list' });
  let i = start;

  while (i < lines.length) {
    const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
    if (!m) {
      // a blank line only ends the list if the next line is not a deeper
      // continuation of it
      if (!lines[i].trim() && i + 1 < lines.length &&
          /^(\s*)([-*+]|\d+[.)])\s+/.test(lines[i + 1]) &&
          /^(\s*)/.exec(lines[i + 1])[1].length >= baseIndent) { i++; continue; }
      break;
    }
    const indent = m[1].length;
    if (indent < baseIndent) break;
    // a switch between bullets and numbers at this level starts a new list
    // rather than continuing this one
    if (indent === baseIndent && /\d/.test(m[2]) !== ordered) break;
    if (indent > baseIndent) { i = mdList(lines, i, list.lastChild || list); continue; }

    const li = h('li', { class: 'md-li' });
    const task = /^\[([ xX])\]\s+(.*)$/.exec(m[3]);
    if (task) {
      li.appendChild(h('span', { class: 'md-task', text: task[1] === ' ' ? '☐' : '☑' }));
      mdInline(li, ' ' + task[2]);
    } else {
      mdInline(li, m[3]);
    }
    list.appendChild(li);
    i++;
  }

  box.appendChild(list);
  return i;
}

/* Inline spans. One pass, longest-match-first, appending into `parent`. */
const MD_INLINE = [
  { re: /^`([^`]+)`/,                    make: function (m) { return h('code', { class: 'md-inline-code', text: m[1] }); } },
  { re: /^!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/, make: function (m) { return mdLink(m[2], m[1] || m[2], true); } },
  { re: /^\[([^\]]+)\]\(([^)\s]+)[^)]*\)/,  make: function (m) { return mdLink(m[2], m[1], false); } },
  { re: /^<((?:https?|mailto):[^>\s]+)>/, make: function (m) { return mdLink(m[1], m[1], false); } },
  { re: /^\*\*([^*]+)\*\*|^__([^_]+)__/,  make: function (m) { return mdInline(h('strong'), m[1] || m[2]); } },
  { re: /^\*([^*]+)\*|^_([^_]+)_/,        make: function (m) { return mdInline(h('em'), m[1] || m[2]); } },
  { re: /^~~([^~]+)~~/,                   make: function (m) { return mdInline(h('del'), m[1]); } }
];

function mdInline(parent, text) {
  let buf = '';
  let i = 0;
  function flush() { if (buf) { parent.appendChild(document.createTextNode(buf)); buf = ''; } }

  while (i < text.length) {
    if (text[i] === '\\' && i + 1 < text.length) { buf += text[i + 1]; i += 2; continue; }
    let hit = null;
    const rest = text.slice(i);
    for (let r = 0; r < MD_INLINE.length; r++) {
      const m = MD_INLINE[r].re.exec(rest);
      if (m) { hit = { m: m, make: MD_INLINE[r].make }; break; }
    }
    if (hit) { flush(); parent.appendChild(hit.make(hit.m)); i += hit.m[0].length; continue; }
    buf += text[i]; i++;
  }
  flush();
  return parent;
}

/* Only http(s) and mailto become real links; anything else (including
 * javascript: and data:) renders as plain text carrying its own target. */
function mdLink(href, label, isImage) {
  if (/^(https?:|mailto:)/i.test(href)) {
    return h('a', {
      class: 'md-link', href: href, target: '_blank', rel: 'noopener noreferrer',
      title: href
    }, [(isImage ? '🖼 ' : '') + label]);
  }
  return h('span', { class: 'md-link-inert', text: label, title: href });
}

/* ===================================================================== */
/* api                                                                   */
/* ===================================================================== */

const api = {
  get: function (path) { return request('GET', path, null); },
  post: function (path, body) { return request('POST', path, body === undefined ? {} : body); },
  del: function (path) { return request('DELETE', path, null); }
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
  // projects (control surface only -- no graph visualisation here)
  projects: null,           // /api/projects
  projectsError: null,
  workflows: [],            // /api/workflows -- static presets, no error state
  // session view
  sessionId: null,
  head: null,               // /api/sessions/{id}
  events: [],
  at: null,                 // null === HEAD, else 1-based event index
  snapshot: null,           // /api/sessions/{id}/at/{n} (null when at HEAD)
  openPath: null,
  timelineCol: 0,           // grid column with the tab stop: 0 event, 1 fork
  compactionOpen: { summary: true, messages: false },
  // Which tool runs the reader has opened, keyed by the index of the first
  // message in the run. Collapsed is the default: a run is machinery, and
  // the prose around it is what the conversation is actually saying.
  toolOpen: {},
  fileTab: 'content',       // 'content' | 'history'
  fileRender: 'rendered',   // 'rendered' | 'source' -- markdown files only
  fileContent: null,
  fileContentAt: undefined, // the scrub point fileContent was fetched for
  fileHistory: null,
  fileError: null,
  fileMissing: false,       // 404: the path does not exist at this point
  openRevisions: {},        // history index -> bool
  sending: false,          // this tab has a POST /turns in flight
  turnRunning: false,      // a turn is running on the session (maybe another tab)
  watchedTurn: null,       // {turn_index, started_at, elapsed_seconds, from_index}
  cancelling: false,       // POST /turns/cancel in flight
  cancelSettled: null,     // last cancel's `settled` flag
  awaitingUnwind: false,   // cancelled but not settled: log not final yet
  turnNote: null,          // {tone, text, range?, recheck?} shown when idle
  turnStartedAt: null,     // ms timestamp of our own in-flight turn
  sessionError: null,
  loadingSnapshot: false,
  freshIndices: {},
  approvals: {},           // id -> approval view, gated calls waiting on a person
  approvalDeciding: null,  // id of the approval whose POST is in flight
  activity: { order: [], byId: {} },  // provisional content for the running turn
  discarded: {},                      // failed turn index -> provisional content
  lastEndedAt: null                   // server ms-epoch of the last turn-end frame (see fetchTurnRunning)
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
  stopTick();
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
      state.turnStartedAt = null;
      state.timelineCol = 0;
      state.freshIndices = {};
      // A turn in flight belongs to the session we just left; the composer we
      // are about to mount is a different one and must start enabled.
      state.sending = false;
      state.turnRunning = false;
      state.watchedTurn = null;
      state.cancelling = false;
      state.cancelSettled = null;
      state.awaitingUnwind = false;
      state.turnNote = null;
      state.loadingSnapshot = false;
      state.approvals = {};
      state.approvalDeciding = null;
      // Leaving the session leaves its provisional content behind too --
      // otherwise a stale bubble from the old session would flash in the new
      // one before the first activity frame (or the turn end) replaces it.
      state.activity = { order: [], byId: {} };
      state.discarded = {};
      state.lastEndedAt = null;
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
  root.querySelector('[data-act="new-project"]').addEventListener('click', createProject);
  loadWorkflows();
  clear(slot(root, 'tree'));
  slot(root, 'tree').appendChild(h('div', { class: 'empty', text: 'loading sessions…' }));
  clear(slot(root, 'projects'));
  slot(root, 'projects').appendChild(h('div', { class: 'empty', text: 'loading projects…' }));
  loadProjects();
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

/* ===================================================================== */
/* projects (control surface: list, create, join -- no graph view here) */
/* ===================================================================== */

/* The workflow choice sits on the create row because a project may only
 * choose once -- the aggregate refuses a second selection, since a run's
 * audit trail is gated by one preset's stage list. Creation is therefore the
 * moment the choice is free, and offering it later would mostly be offering
 * something that will be refused. Projects created before this existed keep a
 * "no workflow" chip; giving them one is the stage rail's job, not this row's.
 *
 * Option text is the server's `label`, not the preset name: what a preset
 * produces and where it stops is the actual choice, and a bare list of three
 * methodology names only means something to someone who has read the
 * research. */
function loadWorkflows() {
  return api.get('/api/workflows').then(function (res) {
    state.workflows = Array.isArray(res) ? res : [];
    renderWorkflowOptions();
  }).catch(function () {
    // A failure here costs the choice, not the page: creating a project
    // without a workflow stays legal, and the select keeps its one option.
    state.workflows = [];
  });
}

function renderWorkflowOptions() {
  const select = document.getElementById('project-workflow');
  if (!select) return;
  clear(select);
  select.appendChild(h('option', { value: '', text: 'no workflow' }));
  state.workflows.forEach(function (w) {
    select.appendChild(h('option', { value: w.id, text: w.label, title: w.description }));
  });
}

function loadProjects() {
  return api.get('/api/projects').then(function (res) {
    state.projects = Array.isArray(res) ? res : [];
    state.projectsError = null;
    if (state.route.name === 'tree') renderProjects();
  }).catch(function (e) {
    state.projects = null;
    state.projectsError = e.message;
    if (state.route.name === 'tree') renderProjects();
  });
}

function renderProjects() {
  if (!root) return;
  const box = slot(root, 'projects');
  if (!box) return;
  clear(box);

  if (state.projectsError) {
    box.appendChild(errorBox('Could not load projects', state.projectsError, function () {
      clear(box);
      box.appendChild(h('div', { class: 'empty', text: 'retrying…' }));
      loadProjects();
    }));
    return;
  }
  if (!state.projects || !state.projects.length) {
    box.appendChild(emptyState('No projects yet.',
      'Create one to share a filesystem and knowledge graph across sessions.'));
    return;
  }
  const ul = h('ul', { class: 'tree' });
  state.projects.forEach(function (p) {
    const held = p.active_session_id;
    const li = h('li');
    // A held project offers two honest choices instead of one that fails:
    // go to whoever holds it, or end that session and take the project on.
    // "Join" was only ever correct for a free project.
    const actions = held
      ? [
          h('button', {
            class: 'btn btn-sm',
            title: 'Open the session currently holding this project',
            onclick: function () { go('#/s/' + encodeURIComponent(held)); }
          }, [document.createTextNode('Resume')]),
          h('button', {
            class: 'btn btn-sm btn-accent',
            title: 'End the holding session, then start a new one from its work',
            onclick: function () { takeOverProject(p); }
          }, [document.createTextNode('New session')])
        ]
      : [
          h('button', {
            class: 'btn btn-sm btn-accent',
            onclick: function () { joinProject(p.id); }
          }, [document.createTextNode('Open')])
        ];
    li.appendChild(h('div', { class: 'node' }, [
      h('div', { class: 'node-top' }, [
        h('span', { class: 'node-id', text: p.name }),
        h('span', { class: 'node-msg empty', text: shortId(p.id) }),
        held
          ? h('span', { class: 'chip chip-held', title: 'held by session ' + held },
              ['held by ' + shortId(held)])
          : h('span', { class: 'chip', text: 'free' }),
        workflowChip(p)
      ]),
      h('div', { class: 'node-actions' }, actions.concat([
        h('button', {
          class: 'btn btn-sm btn-danger',
          title: 'Retire this project',
          onclick: function () { deleteProject(p); }
        }, [document.createTextNode('Delete')])
      ]))
    ]));
    ul.appendChild(li);
  });
  clear(box);
  box.appendChild(ul);
}

/* One chip, showing the preset and how far through it this project is.
 * "4 of 15" rather than the stage id alone: the id is precise and says
 * nothing about progress, which is the thing a list is being scanned for. */
function workflowChip(project) {
  if (!project.workflow) {
    return h('span', {
      class: 'chip',
      title: 'No workflow selected. Projects choose one when they are created.'
    }, ['no workflow']);
  }
  const stage = project.stage;
  const text = stage
    ? project.workflow.name + ' · ' + stage.index + '/' + stage.of
    : project.workflow.name;
  const title = stage
    ? 'Stage ' + stage.index + ' of ' + stage.of + ': ' + stage.name +
      ' (' + stage.id + ')'
    // No stage means the preset is not one this build ships, so there is no
    // stage list to place the project in. Say that rather than guess.
    : 'Workflow ' + project.workflow.id + ' is not available in this build';
  return h('span', { class: 'chip', title: title }, [text]);
}

let creatingProject = false;

function createProject(ev) {
  if (creatingProject) return;
  const input = document.getElementById('project-name');
  const select = document.getElementById('project-workflow');
  const name = input ? input.value.trim() : '';
  const presetId = select ? select.value : '';
  if (!name) { toast('Enter a project name first.', 'bad'); return; }
  creatingProject = true;
  const button = ev && ev.currentTarget;
  if (button) button.disabled = true;
  api.post('/api/projects', { name: name }).then(function (res) {
    if (input) input.value = '';
    const created = res && res.id;
    if (!presetId || !created) {
      toast('Created project ' + (res && res.name || name) + '.', 'good');
      return;
    }
    // Two calls, and the second can fail on its own. The project still
    // exists when it does, so the toast says exactly that rather than
    // "could not create" -- a user told creation failed would try again and
    // hit the duplicate-name 409.
    return api.post('/api/projects/' + encodeURIComponent(created) + '/workflow',
                    { preset_id: presetId })
      .then(function (w) {
        toast('Created project ' + (res.name || name) + ' running ' +
              (w && w.workflow ? w.workflow.name : presetId) + '.', 'good');
      })
      .catch(function (e) {
        toast('Created project ' + (res.name || name) +
              ', but its workflow was not set: ' + e.message, 'bad');
      });
  }).catch(function (e) {
    toast('Could not create project: ' + e.message, 'bad');
  }).then(function () {
    loadProjects();
    creatingProject = false;
    if (button && button.isConnected) button.disabled = false;
  });
}

let joiningProject = false;

/* Deleting retires a project: it stops accepting sessions and leaves the
 * list. The confirmation says what survives, because "delete" in most tools
 * means the work goes too, and here it does not -- the sessions keep their
 * logs, their files and their history. */
let deletingProject = false;

function deleteProject(project) {
  if (deletingProject) return;
  const held = project.active_session_id;
  const lines = ['Delete project "' + project.name + '"?', ''];
  if (held) {
    lines.push('Session ' + shortId(held) + ' is still holding it and will be ended first.');
  }
  lines.push('Its sessions keep their own logs, files and history — they just');
  lines.push('cannot rejoin. The knowledge graph\'s contents are left in place.');
  if (!window.confirm(lines.join('\n'))) return;

  deletingProject = true;
  api.del('/api/projects/' + encodeURIComponent(project.id) +
          (held ? '?release_holder=true' : ''))
    .then(function () {
      toast('Deleted project ' + project.name + '.', 'good');
      loadProjects();
    })
    .catch(function (e) { toast('Could not delete project: ' + e.message, 'bad'); })
    .then(function () { deletingProject = false; });
}

/* Taking over ends someone else's session, so it asks first -- and says what
 * it will do, since "end that and start fresh" is not obviously the same
 * thing as "join". The holder's work is not lost: releasing it is exactly
 * what advances the project's tip, which the new session then inherits. */
function takeOverProject(project) {
  const holder = shortId(project.active_session_id);
  const ok = window.confirm(
    'End session ' + holder + ' and start a new one in ' + project.name + '?\n\n' +
    'Its files carry over to the new session. Its conversation does not.'
  );
  if (ok) joinProject(project.id, true);
}

function joinProject(projectId, takeOver) {
  if (joiningProject) return;
  joiningProject = true;
  api.post('/api/projects/' + encodeURIComponent(projectId) + '/join',
           { take_over: !!takeOver }).then(function (res) {
    if (res && res.warning) toast('Joined, but ' + res.warning, 'bad');
    if (res && res.id) go('#/s/' + encodeURIComponent(res.id));
    else toast('Joined but no session id was returned.', 'bad');
  }).catch(function (e) {
    toast('Could not join project: ' + e.message, 'bad');
  }).then(function () {
    joiningProject = false;
  });
}

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
    approvals: slot(root, 'approvals'),
    activity: slot(root, 'activity'),
    composer: slot(root, 'composer'),
    input: slot(root, 'input'),
    send: slot(root, 'send'),
    cancel: slot(root, 'cancel'),
    hint: slot(root, 'composer-hint')
  };
  sessionEls.composer.addEventListener('submit', onSend);
  sessionEls.cancel.addEventListener('click', cancelTurn);
  sessionEls.input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); onSend(ev); }
  });
  // Once you start writing the next turn, the last one's outcome is history.
  sessionEls.input.addEventListener('input', function () {
    if (state.turnNote) { state.turnNote = null; renderComposer(); }
  });
  setUpPaneToggles();
  sessionEls.timeline.appendChild(h('div', { class: 'empty', text: 'loading event log…' }));
  renderComposer();
}

/* --- collapsible panes --------------------------------------------------
 * Three panes on one screen means each is narrower than it wants to be, and
 * which one you need is a function of what you are doing -- reading a diff,
 * following the log, or talking. Collapsing is per-pane, sticky across
 * reloads, and refuses to hide the last open pane (a view with nothing in it
 * has no way back except a toggle you can no longer see). */
const PANE_STORAGE_KEY = 'rt.collapsedPanes';
const PANE_RAIL = '34px';

function loadCollapsedPanes() {
  try {
    const raw = window.localStorage.getItem(PANE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(function (n) { return typeof n === 'string'; }) : [];
  } catch (e) {
    return []; // private mode, disabled storage, or junk left by an older build
  }
}

function saveCollapsedPanes(names) {
  try { window.localStorage.setItem(PANE_STORAGE_KEY, JSON.stringify(names)); } catch (e) { /* not worth failing over */ }
}

function setUpPaneToggles() {
  const panes = root.querySelectorAll('[data-pane]');
  for (let i = 0; i < panes.length; i++) {
    const pane = panes[i];
    pane.querySelector('[data-act="collapse"]').addEventListener('click', function () {
      togglePane(pane.dataset.pane);
    });
  }
  applyCollapsedPanes();
}

function togglePane(name) {
  const collapsed = loadCollapsedPanes();
  const at = collapsed.indexOf(name);
  if (at === -1) {
    const panes = root.querySelectorAll('[data-pane]');
    if (collapsed.length >= panes.length - 1) {
      toast('At least one pane has to stay open.', 'bad');
      return;
    }
    collapsed.push(name);
  } else {
    collapsed.splice(at, 1);
  }
  saveCollapsedPanes(collapsed);
  applyCollapsedPanes();
}

function applyCollapsedPanes() {
  if (!root) return;
  const grid = root.querySelector('.panes');
  if (!grid) return;
  const collapsed = loadCollapsedPanes();
  const panes = root.querySelectorAll('[data-pane]');
  const widths = [];
  for (let i = 0; i < panes.length; i++) {
    const pane = panes[i];
    const isCollapsed = collapsed.indexOf(pane.dataset.pane) !== -1;
    pane.classList.toggle('collapsed', isCollapsed);
    const button = pane.querySelector('[data-act="collapse"]');
    button.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
    button.title = isCollapsed ? 'Expand this pane' : 'Collapse this pane';
    button.textContent = isCollapsed ? '▸' : '◂';
    // The rail is a fixed track rather than a min-width so the space it gives
    // up goes to the open panes, which is the entire point of collapsing.
    widths.push(isCollapsed ? PANE_RAIL : (pane.dataset.pane === 'workspace'
      ? 'minmax(320px, 1.5fr)'
      : 'minmax(280px, 1.05fr)'));
  }
  // Only the three-column layout has its tracks driven from here. The
  // narrower breakpoints reflow the panes themselves (two columns, then a
  // single stack), and an inline grid-template would silently outrank those
  // media queries -- so below 1180px this hands the columns back to the
  // stylesheet, which sizes collapsed panes with its own :has() rules.
  if (window.matchMedia('(min-width: 1181px)').matches) {
    grid.style.gridTemplateColumns = widths.join(' ');
  } else {
    grid.style.removeProperty('grid-template-columns');
  }
}

// Crossing a breakpoint changes who owns the columns, so recompute there.
window.addEventListener('resize', function () {
  if (state.route.name === 'session') applyCollapsedPanes();
});

function loadSession() {
  const id = state.sessionId;
  return Promise.all([
    api.get('/api/sessions/' + encodeURIComponent(id)),
    api.get('/api/sessions/' + encodeURIComponent(id) + '/events'),
    // A turn may already be running (another tab, or a reload mid-turn). This
    // is advisory, so a failure here must not fail the whole load.
    fetchTurnRunning(id).catch(function () { return null; }),
    // A tab that (re)loads mid-approval never saw the ApprovalRequested frame
    // -- this is how it catches up. Advisory like the turn check above.
    api.get('/api/sessions/' + encodeURIComponent(id) + '/approvals')
      .catch(function () { return []; })
  ]).then(function (res) {
    if (state.sessionId !== id) return;
    state.head = res[0] || {};
    state.events = Array.isArray(res[1]) ? res[1] : [];
    state.sessionError = null;
    applyRunning(res[2]);
    setApprovals(res[3]);
    renderCrumbs();
    renderTimeline();
    if (state.at !== null) loadSnapshot();
    else { state.snapshot = null; renderWorkspace(); renderConversation(); renderScrubBar(); }
    // A tab that (re)loads mid-turn never saw the activity frames, and they
    // carry no position for Last-Event-ID to resume from -- this is the only
    // way it finds out what is provisionally in flight. Best-effort, like the
    // running/approvals checks above.
    catchUpActivity(id);
  }).catch(function (e) {
    if (state.sessionId !== id) return;
    state.sessionError = e.message;
    renderSessionError();
  });
}

/* Best-effort catch-up for provisional content: called from loadSession
 * (mount, or mid-turn reload) and from connect()'s reconnect handler (an SSE
 * drop loses these frames outright -- they carry no feed position, so
 * Last-Event-ID cannot replay them the way it does for the log). Shared
 * rather than duplicated so both call sites get the same staleness handling. */
function catchUpActivity(id) {
  const activitySeqAtRequest = turnEndSeq;
  api.get('/api/sessions/' + encodeURIComponent(id) + '/turns/current/activity')
    .then(function (body) {
      if (state.sessionId !== id) return;
      // Same non-atomicity as /turns/current (see fetchTurnRunning): the
      // activity buffer's own settle() and the TurnCompleted/TurnFailed
      // event it settles around are two steps, not one, so `running` here
      // can still list a turn that, on this connection, already ended --
      // and turnEndSeq alone does not catch it, because this call can be
      // triggered BY that very reconciliation (foreignTurnEnded calls
      // loadSession right after correctly clearing state.activity), so
      // turnEndSeq does not change between request and response at all.
      // The frame-based mechanism (onStreamEvent/onActivityFrame) is what
      // now owns turnRunning correctly, so trust ITS verdict over this
      // GET's: only accept a positive answer here if something is already
      // believed to be running by that authoritative path. Callers that
      // cannot yet be sure (a reconnect, where a turn may have started
      // entirely during the gap) must resync turnRunning itself first --
      // see connect()'s reconnect handler, which calls refreshRunning()
      // before this, precisely so that belief is current by the time this
      // guard checks it.
      if (turnEndSeq === activitySeqAtRequest && (state.sending || state.turnRunning)) {
        (body.running || []).forEach(putActivity);
      }
      renderActivity();
      // The discarded buffer isn't tied to an index server-side (it's just
      // "the last failed turn's content"), so pin it to that turn's
      // TurnFailed row here, the same place a live frame would have put it.
      if (body.discarded && body.discarded.length) {
        const idx = lastFailedTurnIndex();
        if (idx !== null) {
          state.discarded[idx] = body.discarded;
          renderTimeline();
        }
      }
    })
    .catch(function () { /* catch-up is best-effort */ });
}

/* Reconcile "is a turn running" with what this tab is doing. Our own POST owns
 * state.sending; turnRunning is only ever about a turn we did not start.
 *
 * This is only ever asked at mount (or on demand): a tab that arrives mid-turn
 * has missed the earlier frames. Once running, the stream tells us when it ends
 * -- TurnCompleted/TurnFailed are ordinary domain events -- so there is no poll.
 */
function applyRunning(res) {
  if (!res || typeof res.running !== 'boolean') return;
  const foreign = res.running && !state.sending;
  if (foreign === state.turnRunning) return;
  state.turnRunning = foreign;
  if (foreign) {
    state.turnNote = null;
    startTick();
    state.watchedTurn = {
      turn_index: typeof res.turn_index === 'number' ? res.turn_index : null,
      started_at: res.started_at || null,
      elapsed_seconds: typeof res.elapsed_seconds === 'number' ? res.elapsed_seconds : null,
      from_index: null   // filled by the first frame we see for this turn
    };
  } else {
    state.watchedTurn = null;
    stopTick();
  }
  renderComposer();
  // A flip either way can change what onActivityFrame was waiting to show (or
  // hide, if a straggler's optimistic refreshRunning came back negative).
  renderActivity();
}

/* Elapsed time is the only thing that moves while a turn runs, so repaint the
 * composer once a second to keep it honest. Display only -- no requests. */
let tickTimer = null;

function startTick() {
  if (tickTimer) return;
  tickTimer = setInterval(function () {
    if (!state.sending && !state.turnRunning) { stopTick(); return; }
    renderComposer();
  }, 1000);
}

function stopTick() {
  if (!tickTimer) return;
  clearInterval(tickTimer);
  tickTimer = null;
}

// Bumped every time a TurnCompleted/TurnFailed frame is reconciled (see
// onStreamEvent). Unlike a GET to /turns/current, a turn-end frame is
// strictly ordered on this connection and can never be stale -- so every GET
// against that endpoint (below, and the mount-time one in loadSession) is
// checked against this, not the other way around.
let turnEndSeq = 0;

/* GET /turns/current, but distrust a positive answer that names a turn which
 * started no later than the last turn-end this connection already saw. The
 * backend clears its "current turn" tracker and emits the
 * TurnCompleted/TurnFailed event as two separate steps, not atomically -- so
 * a response can say running:true for tens of milliseconds after this
 * connection already saw that same turn end, REGARDLESS of when the request
 * was sent (this is not a narrow in-flight window; the server side itself
 * lags). That includes the request loadSession() fires on every call, which
 * foreignTurnEnded triggers right after correctly clearing turnRunning --
 * without this, that GET would immediately undo it.
 *
 * This used to compare turn_index instead of started_at, which is unsound: a
 * TurnFailed event carries turn_index = state.turn_index + 1 but the session
 * deliberately does NOT advance state.turn_index on failure ("the turn did
 * not happen" -- see domain/session.py), so a retry after a failure computes
 * the exact same turn_index again. Comparing indices made a failed turn
 * permanently suppress rendering for every retry afterward, since each
 * retry's /turns/current kept reporting the same "already-ended" index.
 * started_at does not have this problem: a retry always starts strictly
 * after the failure it followed, so comparing timestamps (both server-clock,
 * matching the occurred_at this was set from) tells a genuine new turn apart
 * from a straggler regardless of how many times turn_index repeats.
 *
 * turnEndSeq is kept as a second, cheaper check for the (rarer) true
 * in-flight case. Only the positive case is ever downgraded -- running:false
 * is always safe to trust. */
function fetchTurnRunning(id) {
  const seqAtRequest = turnEndSeq;
  return api.get('/api/sessions/' + encodeURIComponent(id) + '/turns/current')
    .then(function (res) {
      const startedAt = res && res.started_at ? Date.parse(res.started_at) : NaN;
      if (res && res.running &&
          (turnEndSeq !== seqAtRequest ||
           (state.lastEndedAt !== null && !isNaN(startedAt) && startedAt < state.lastEndedAt))) {
        return { running: false, turn_index: null, started_at: null, elapsed_seconds: null };
      }
      return res;
    });
}

let runningCheckInFlight = false;

function refreshRunning(announce) {
  const id = state.sessionId;
  // Events arrive in bursts; one check at a time is enough.
  if (!id || runningCheckInFlight) return Promise.resolve();
  runningCheckInFlight = true;
  return fetchTurnRunning(id)
    .then(function (res) {
      runningCheckInFlight = false;
      if (state.sessionId !== id) return;
      const wasRunning = state.turnRunning;
      applyRunning(res);
      if (wasRunning && !state.turnRunning) {
        setNote('good', 'the turn running elsewhere finished');
        loadSession();
      } else if (announce && !state.turnRunning && !state.sending) {
        setNote('good', 'nothing is running — you can send a turn');
        renderComposer();
      }
    })
    .catch(function (e) {
      runningCheckInFlight = false;
      if (state.sessionId !== id) return;
      if (announce) { setNote('warn', 'could not check — ' + e.message, null, true); renderComposer(); }
    });
}

/* A turn started elsewhere ended on the stream. Its span is derivable from the
 * frames themselves: the closing frame's own index is to_index, and the first
 * frame we saw after it started (its UserMessageSent) is from_index. */
function foreignTurnEnded(payload) {
  const watched = state.watchedTurn;
  const to = typeof payload.index === 'number' ? payload.index : null;
  const from = watched && typeof watched.from_index === 'number' ? watched.from_index : to;
  const cancelled = isCancellation(payload);

  state.turnRunning = false;
  state.watchedTurn = null;
  stopTick();

  if (cancelled) {
    setNote('calm', 'the turn running elsewhere was cancelled — its events were discarded');
  } else if (/failed/i.test(String(payload.type || ''))) {
    setNote('warn', 'the turn running elsewhere failed');
  } else if (from !== null && to !== null) {
    const range = {
      turn_index: typeof payload.turn_index === 'number' ? payload.turn_index
        : (watched ? watched.turn_index : null),
      from_index: from,
      to_index: to
    };
    markFresh(from, to);
    setNote('good', 'the turn running elsewhere finished', range);
  } else {
    setNote('good', 'the turn running elsewhere finished');
  }
  renderComposer();
  // Stream frames are timeline rows only -- they carry no message content and
  // no file contents. The conversation and workspace panes can only be brought
  // up to date by refetching, so a turn ending always costs one load.
  loadSession();
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

  // Project state belongs here because it changes what typing into this
  // session means: whether the work lands somewhere the next session will
  // see, and whether the agent can reach the graph its prompt promises.
  const head = state.head || {};
  if (head.project_id) {
    const attached = head.knowledge_attached;
    bar.appendChild(h('span', {
      class: 'scrub-project' + (head.holds_project ? '' : ' stale-hold'),
      title: head.holds_project
        ? 'This session holds the project. End it to pass its files on.'
        : 'Another session has taken this project over; work here no longer reaches it.'
    }, [
      h('span', { class: 'chip', text: 'project ' + shortId(head.project_id) }),
      h('span', {
        class: 'chip ' + (attached ? 'chip-ok' : 'chip-warn'),
        title: attached
          ? 'The knowledge graph is attached; remember/graph_search are available.'
          : 'No knowledge graph attached — the agent has no remember/graph_search here.'
      }, [attached ? 'graph on' : 'graph off']),
      head.holds_project ? null : h('span', { class: 'chip chip-warn', text: 'not held' })
    ]));
  }

  const actions = h('div', { class: 'scrub-actions' });
  if (!isHistorical() && head.project_id && head.holds_project) {
    actions.appendChild(h('button', {
      class: 'btn btn-sm',
      title: 'Hand this session\'s files back to the project and stop working here',
      onclick: function (e) { endSession(e.currentTarget); }
    }, 'End session'));
  }
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

/* Ending a session is the other half of joining a project, and the only way
 * work done here reaches the next session: releasing advances the project's
 * tip. Named "End session" rather than "Release" because that is the thing
 * the user is trying to do; the lease is an implementation detail of it. */
function endSession(button) {
  const head = state.head || {};
  if (!window.confirm(
    'End this session and hand its files back to the project?\n\n' +
    'The log stays readable and forkable. The project becomes free, and the ' +
    'next session in it starts from this one\'s files.'
  )) return;
  if (button) button.disabled = true;
  api.post('/api/sessions/' + encodeURIComponent(state.route.id) + '/release', {})
    .then(function (res) {
      if (res && res.released) {
        toast('Session ended. ' + shortId(head.project_id) + ' is free.', 'good');
        loadProjects();
        go('#/');
      } else {
        toast('This session is not in a project.', 'bad');
      }
    })
    .catch(function (e) { toast('Could not end session: ' + e.message, 'bad'); })
    .then(function () { if (button && button.isConnected) button.disabled = false; });
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
  // Must be read BEFORE clear(): emptying the box detaches the focused row and
  // focus falls to <body>, which would make this test always false.
  const hadFocus = box.contains(document.activeElement);
  clear(box);
  sessionEls.timelineMeta.textContent = state.events.length
    ? plural(state.events.length, 'event') : '';

  if (!state.events.length) {
    box.appendChild(emptyState('The log is empty.',
      'Send a turn below — every message, tool call and file write lands here in order.'));
    return;
  }

  // A grid, not a listbox: each row carries a primary action (scrub to it) AND
  // a secondary one (fork here). role="grid" is the pattern that legitimately
  // allows a focusable control inside a row, so the fork button can be reached
  // with the keyboard instead of being hidden from assistive tech.
  const list = h('div', { class: 'timeline', role: 'grid',
                          id: 'timeline-grid',
                          'aria-label': 'event timeline',
                          'aria-rowcount': String(state.events.length + 1),
                          'aria-colcount': '2' });
  list.addEventListener('keydown', onTimelineKey);

  state.events.forEach(function (ev, i) {
    const index = typeof ev.index === 'number' ? ev.index : i + 1;
    const cancelled = isCancellation(ev);
    const kind = cancelled ? 'cancelled' : eventKind(ev.type);
    const selected = state.at === index;
    const future = isHistorical() && index > state.at;
    const summary = ev.summary === null || ev.summary === undefined ? '' : String(ev.summary);
    const row = h('div', {
      class: 'ev k-' + kind + (selected ? ' selected' : '') + (future ? ' future' : '') +
             (ev.is_error && !cancelled ? ' is-error' : '') +
             (state.freshIndices[index] ? ' fresh' : ''),
      role: 'row',
      id: 'ev-' + index,
      'aria-rowindex': String(i + 1),
      'aria-selected': selected ? 'true' : 'false',
      // Roving tabindex: exactly one row is in the tab order at a time.
      tabindex: selected ? '0' : '-1',
      dataset: { index: String(index), row: '1' },
      title: humanType(ev.type) + '\n' + fullTime(ev.occurred_at) +
             (summary ? '\n' + summary : ''),
      onclick: function () { selectEvent(index); }
    }, [
      h('div', { class: 'ev-cell', role: 'gridcell' }, [
        h('span', { class: 'ev-idx', text: String(index) }),
        h('span', { class: 'ev-rail' }),
        h('span', { class: 'ev-main' }, [
          h('span', { class: 'ev-type' }, [
            humanType(ev.type),
            typeof ev.turn_index === 'number' ? h('span', { class: 'ev-path' }, ' · turn ' + ev.turn_index) : null,
            ev.strategy ? h('span', { class: 'ev-strategy', text: ' · ' + ev.strategy }) : null
          ]),
          h('span', { class: 'ev-summary' }, [
            // The summary stands alone (it has to, for the live feed), so for a
            // file event it already opens with the path -- don't print it twice.
            ev.path && summary.indexOf(ev.path) !== 0
              ? h('span', { class: 'ev-path', text: ev.path + '  ' }) : null,
            summary ? truncate(summary, 160) : (ev.path ? '' : '—')
          ])
        ]),
        h('span', { class: 'ev-time', text: clockTime(ev.occurred_at) })
      ]),
      // A real, reachable control: ArrowRight moves into this cell. No
      // aria-hidden, because role="grid" permits a widget inside a cell.
      h('div', { class: 'ev-cell ev-cell-act', role: 'gridcell' },
        h('button', {
          class: 'btn btn-ghost ev-fork',
          tabindex: '-1',
          'aria-label': 'Fork a new session at event ' + index,
          title: 'fork a new session at event ' + index,
          onclick: function (e) { e.stopPropagation(); forkAt(index, e.currentTarget); }
        }, 'fork here'))
    ]);
    list.appendChild(row);
    const discarded = renderDiscarded(index);
    if (discarded) list.appendChild(discarded);
  });

  const atHead = state.at === null;
  list.appendChild(h('div', {
    class: 'head-marker' + (atHead ? ' selected' : ''),
    role: 'row',
    id: 'ev-head',
    'aria-rowindex': String(state.events.length + 1),
    'aria-selected': atHead ? 'true' : 'false',
    tabindex: atHead ? '0' : '-1',
    dataset: { row: '1', head: '1' },
    onclick: function () { selectEvent(null); }
  }, [
    h('div', { class: 'ev-cell', role: 'gridcell', text:
      atHead ? '● HEAD — live' : '○ HEAD — click to return to live' }),
    h('div', { class: 'ev-cell ev-cell-act', role: 'gridcell' })
  ]));

  box.appendChild(list);
  scrollSelectedIntoView();
  // Re-rendering replaces the focused node; put focus back where it was.
  if (hadFocus) focusTimelineRow();
}

/* The row that owns the tab stop: the selected event, or HEAD. */
function currentTimelineRow() {
  if (!sessionEls) return null;
  return sessionEls.timeline.querySelector('.ev.selected, .head-marker.selected');
}

function focusTimelineRow() {
  const row = currentTimelineRow();
  if (!row) return;
  if (state.timelineCol === 1) {
    const button = row.querySelector('.ev-fork');
    if (button) { button.focus(); return; }
    state.timelineCol = 0;
  }
  row.focus();
}

function scrollSelectedIntoView() {
  if (!sessionEls) return;
  const el = sessionEls.timeline.querySelector('.ev.selected, .head-marker.selected');
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
}

function onTimelineKey(ev) {
  const total = state.events.length;
  if (!total) return;

  // Column navigation stays within the focused row: left is the event itself,
  // right is its fork action.
  if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
    const row = currentTimelineRow();
    if (!row) return;
    const button = row.querySelector('.ev-fork');
    ev.preventDefault();
    ev.stopPropagation();
    state.timelineCol = (ev.key === 'ArrowRight' && button) ? 1 : 0;
    focusTimelineRow();
    return;
  }

  // Enter/Space act on whatever cell is focused.
  if (ev.key === 'Enter' || ev.key === ' ') {
    const row = currentTimelineRow();
    if (!row) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (state.timelineCol === 1) {
      const button = row.querySelector('.ev-fork');
      if (button) button.click();
    } else if (row.dataset.head) {
      selectEvent(null);
    } else {
      selectEvent(parseInt(row.dataset.index, 10));
    }
    return;
  }

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
  // Moving rows returns to the primary column, so the fork button is never
  // silently carried along as you scrub.
  state.timelineCol = 0;
  const target = next > total ? null : next;
  if (target !== state.at) selectEvent(target);
  else focusTimelineRow();
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

  const markdown = isMarkdownPath(state.openPath);
  const head = h('div', { class: 'file-view-head' }, [
    h('span', { class: 'fv-path', text: state.openPath, title: state.openPath }),
    markdown && state.fileTab === 'content' ? h('div', { class: 'tabs' }, [
      renderModeButton('rendered', 'rendered'),
      renderModeButton('source', 'source')
    ]) : null,
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
    const view = (markdown && state.fileRender !== 'source')
      ? renderMarkdown(state.fileContent)
      : renderCode(state.fileContent);
    if (stale) view.classList.add('stale');
    box.appendChild(view);
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

/* Rendered/source is a view toggle, not a tab: it needs no refetch, since
 * both modes render the contents already in hand. */
function renderModeButton(id, label) {
  return h('button', {
    class: 'tab' + ((state.fileRender || 'rendered') === id ? ' active' : ''),
    onclick: function () {
      if ((state.fileRender || 'rendered') === id) return;
      state.fileRender = id;
      renderFileView();
    }
  }, label);
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
  const compacted = compactedThrough(v, messages.length);
  sessionEls.convMeta.textContent = messages.length
    ? plural(messages.length, 'message') +
      (compacted ? ' · ' + compacted + ' compacted' : '') +
      (isHistorical() ? ' @ ' + state.at : '')
    : '';

  if (v.__error) { box.appendChild(errorBox('Unavailable', v.__error, loadSnapshot)); return; }

  if (!messages.length) {
    box.appendChild(emptyState('No conversation yet.', isHistorical()
      ? 'Nothing had been said by event ' + state.at + '.'
      : 'Send the first turn below.'));
    return;
  }

  const conv = h('div', { class: 'conv' });
  // How many leading messages the model now sees as a summary instead. Absent
  // or 0 on most sessions, and 0 again when scrubbed to before the compaction.
  const through = compacted;
  if (through > 0) {
    conv.appendChild(renderCompaction(v, messages.slice(0, through), through));
    appendMessages(conv, messages.slice(through), through);
  } else {
    appendMessages(conv, messages, 0);
  }
  box.appendChild(conv);
  if (stick) box.scrollTop = box.scrollHeight;
}

function compactedThrough(v, messageCount) {
  const raw = v && v.compacted_through;
  if (typeof raw !== 'number' || !isFinite(raw) || raw <= 0) return 0;
  // Never let a stale or oversized count eat the whole conversation.
  return Math.min(Math.floor(raw), messageCount);
}

/* Nothing was deleted -- the log still holds every message, and so does this
 * pane. What changed is what the MODEL is shown: a summary standing in for
 * everything above the boundary. Make that distinction the visible idea. */
function renderCompaction(v, hidden, through) {
  const summary = typeof v.compaction_summary === 'string' ? v.compaction_summary : '';
  const openSummary = state.compactionOpen.summary;
  const openMessages = state.compactionOpen.messages;

  const wrap = h('section', { class: 'compaction', 'aria-label': 'compacted context' });

  wrap.appendChild(h('div', { class: 'compaction-head' }, [
    h('span', { class: 'compaction-mark', 'aria-hidden': 'true' }),
    h('span', { class: 'compaction-title', text:
      'context compacted — the model sees a summary of the first ' +
      plural(through, 'message') }),
  ]));

  if (summary) {
    wrap.appendChild(disclosure('summary shown to the model', openSummary, function () {
      state.compactionOpen.summary = !openSummary;
      renderConversation();
    }, h('div', { class: 'compaction-summary', text: summary })));
  } else {
    wrap.appendChild(h('div', { class: 'compaction-note',
      text: 'no summary text was returned with this session.' }));
  }

  wrap.appendChild(disclosure(
    plural(through, 'superseded message') + ' — still in the log, not sent to the model',
    openMessages,
    function () {
      state.compactionOpen.messages = !openMessages;
      renderConversation();
    },
    compactionMsgs(hidden)));

  wrap.appendChild(h('div', { class: 'compaction-boundary' },
    h('span', { text: 'context boundary · everything below is sent verbatim' })));

  return wrap;
}

function compactionMsgs(hidden) {
  const box = h('div', { class: 'compaction-msgs' });
  appendMessages(box, hidden, 0);
  return box;
}

function disclosure(label, open, toggle, body) {
  const id = 'disc-' + Math.random().toString(36).slice(2, 8);
  const wrap = h('div', { class: 'disc' });
  wrap.appendChild(h('button', {
    class: 'disc-head',
    type: 'button',
    'aria-expanded': open ? 'true' : 'false',
    'aria-controls': id,
    onclick: toggle
  }, [
    h('span', { class: 'disc-caret', 'aria-hidden': 'true', text: open ? '▾' : '▸' }),
    label
  ]));
  const region = h('div', { class: 'disc-body', id: id });
  if (open) region.appendChild(body); else region.hidden = true;
  wrap.appendChild(region);
  return wrap;
}

/* --- tool runs ----------------------------------------------------------
 * A turn that reads six files and greps twice is eight messages of machinery
 * around one sentence of reasoning. Rendered flat, the machinery buries the
 * sentence. So consecutive machinery collapses into one line that says what
 * ran, and opens on demand. Prose is never what gets hidden: an assistant
 * message that says something stays visible, and only its call list folds. */

function msgCalls(m) {
  return Array.isArray(m && m.tool_calls) ? m.tool_calls : [];
}

/* Pure machinery: a tool result, or a wordless assistant turn that only
 * dispatched calls. Anything with prose in it is not machinery. */
function isToolActivity(m) {
  const role = (m && m.role) || 'assistant';
  if (role === 'tool') return true;
  return role === 'assistant' && msgCalls(m).length > 0 && !contentText(m && m.content);
}

function appendMessages(conv, messages, offset) {
  let i = 0;
  while (i < messages.length) {
    if (!isToolActivity(messages[i])) {
      conv.appendChild(renderMessage(messages[i], offset + i));
      i += 1;
      continue;
    }
    let j = i;
    while (j < messages.length && isToolActivity(messages[j])) j += 1;
    conv.appendChild(renderToolRun(messages.slice(i, j), offset + i));
    i = j;
  }
}

/* "Read ×3, Bash, Grep" -- the names in the order they first ran, so the
 * summary reads as a trace of the run and not as an alphabetised inventory. */
function toolTally(messages) {
  const order = [];
  const counts = {};
  let total = 0;
  messages.forEach(function (m) {
    msgCalls(m).forEach(function (c) {
      const name = (c && c.name) || 'tool';
      if (!counts[name]) { counts[name] = 0; order.push(name); }
      counts[name] += 1;
      total += 1;
    });
  });
  return {
    total: total,
    label: order.map(function (n) {
      return counts[n] > 1 ? n + ' ×' + counts[n] : n;
    }).join(', ')
  };
}

function renderToolRun(messages, index) {
  const key = 'run:' + index;
  const open = !!state.toolOpen[key];
  const tally = toolTally(messages);
  const errored = messages.some(function (m) { return !!(m && m.is_error); });

  // Results arrive as their own messages, so a run with no calls in it at all
  // is possible on a replay that starts mid-turn. Count messages instead.
  const count = tally.total || messages.length;

  const label = h('span', { class: 'run-label' }, [
    h('b', { text: plural(count, 'tool call') }),
    tally.label ? h('span', { class: 'run-names', text: ' · ' + tally.label }) : null,
    errored ? h('span', { class: 'chip chip-fail', text: 'error' }) : null
  ]);

  const body = h('div', { class: 'run-msgs' });
  messages.forEach(function (m, k) { body.appendChild(renderMessage(m, index + k)); });

  const wrap = disclosure(label, open, function () {
    state.toolOpen[key] = !open;
    renderConversation();
  }, body);
  wrap.classList.add('run');
  return wrap;
}

function renderMessage(m, index) {
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
    // The model writes markdown, so assistant turns are rendered as markdown.
    // Tool results are not: they are data, and their value is being shown
    // byte-for-byte. User messages stay literal for the same reason -- what
    // was typed is what was sent. An errored turn also stays literal, since
    // a raw failure is easier to read than a half-parsed one.
    if (role === 'assistant' && !errored) {
      const body = h('div', { class: 'msg-body' });
      body.appendChild(renderMarkdown(text));
      wrap.appendChild(body);
    } else {
      wrap.appendChild(h('div', {
        class: 'msg-body' + (role === 'tool' ? ' mono' : ''),
        text: role === 'tool' ? truncate(text, 4000) : text
      }));
    }
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
    // A message that also said something keeps its own fold, so the prose is
    // what you see first. Inside a run the fold is already above us.
    if (isToolActivity(m)) {
      wrap.appendChild(box);
    } else {
      const key = 'calls:' + index;
      const open = !!state.toolOpen[key];
      const tally = toolTally([m]);
      wrap.appendChild(disclosure(
        h('span', { class: 'run-label' }, [
          h('b', { text: plural(calls.length, 'tool call') }),
          tally.label ? h('span', { class: 'run-names', text: ' · ' + tally.label }) : null
        ]),
        open,
        function () { state.toolOpen[key] = !open; renderConversation(); },
        box
      ));
    }
  }
  return wrap;
}

function safeJson(v) {
  try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
}

/* --- approvals ----------------------------------------------------------
 * A gated call parks the turn until a person answers it here, in the REPL,
 * or in another tab -- whichever gets there first. ApprovalSettled, not the
 * click handler, is what clears a card: that is what makes the other two
 * paths work too, instead of only the one this tab drove. */

function setApprovals(list) {
  const next = {};
  (Array.isArray(list) ? list : []).forEach(function (a) { if (a && a.id) next[a.id] = a; });
  state.approvals = next;
  renderApprovals();
}

function fetchApprovals(id) {
  return api.get('/api/sessions/' + encodeURIComponent(id) + '/approvals')
    .then(function (list) { if (state.sessionId === id) setApprovals(list); })
    .catch(function () { /* advisory -- the next reconnect or reload tries again */ });
}

function renderApprovals() {
  if (!sessionEls || !sessionEls.approvals) return;
  const box = sessionEls.approvals;
  clear(box);
  Object.keys(state.approvals).forEach(function (id) {
    box.appendChild(renderApproval(state.approvals[id]));
  });
}

function renderApproval(a) {
  const deciding = state.approvalDeciding === a.id;
  return h('div', { class: 'approval' }, [
    h('div', { class: 'approval-head' }, [
      h('span', { text: 'wants to run' }),
      h('b', { text: a.tool_name })
    ]),
    a.description ? h('div', { class: 'approval-desc', text: a.description }) : null,
    h('div', { class: 'approval-args', text: safeJson(a.args) }),
    h('div', { class: 'approval-actions' }, [
      h('button', {
        class: 'btn btn-accent', type: 'button', disabled: deciding,
        onclick: function () { decideApproval(a, 'approve'); }
      }, 'Approve'),
      h('button', {
        class: 'btn btn-quiet', type: 'button', disabled: deciding,
        onclick: function () { decideApproval(a, 'reject'); }
      }, 'Reject')
    ])
  ]);
}

/* langchain's vocabulary, not ours -- "accept" is not a valid decision type. */
function decideApproval(a, type) {
  if (state.approvalDeciding) return;
  state.approvalDeciding = a.id;
  renderApprovals();
  api.post(
    '/api/sessions/' + encodeURIComponent(a.session_id) + '/approvals/' + encodeURIComponent(a.id),
    { type: type }
  ).catch(function (e) {
    // A 404 here just means someone else already answered it; ApprovalSettled
    // will have cleared the card already, so there is nothing left to undo.
    if (e.status !== 404) toast('Could not record decision: ' + e.message, 'bad');
  }).then(function () {
    if (state.approvalDeciding === a.id) state.approvalDeciding = null;
    renderApprovals();
  });
}

/* --- turns ------------------------------------------------------------- */

function renderComposer() {
  if (!sessionEls) return;
  // "busy" covers a turn we started AND one started elsewhere on this session.
  const busy = state.sending || state.turnRunning;
  const cancel = sessionEls.cancel;

  sessionEls.input.disabled = busy;
  sessionEls.send.disabled = busy;
  sessionEls.send.textContent = state.sending ? 'Running…'
    : state.turnRunning ? 'Turn running' : 'Send turn';

  cancel.hidden = !busy;
  cancel.disabled = state.cancelling;
  cancel.textContent = state.cancelling ? 'Cancelling…' : 'Cancel turn';

  const hint = sessionEls.hint;
  clear(hint);
  const note = state.turnNote;
  const tone = busy ? 'busy' : note ? note.tone : (isHistorical() ? 'warn' : '');
  hint.className = 'composer-hint' + (tone ? ' ' + tone : '');

  if (busy) {
    hint.appendChild(h('span', { class: 'spinner' }));
    hint.appendChild(h('span', { class: 'txt', text:
      state.cancelling ? 'cancelling — waiting for the turn to unwind'
        : state.sending ? sendingLabel()
        : watchedLabel() }));
    return;
  }

  if (note) {
    hint.appendChild(h('span', { class: 'txt', text: note.text }));
    if (note.range) hint.appendChild(rangeChip(note.range));
    if (note.recheck) {
      hint.appendChild(h('button', {
        class: 'turn-range', type: 'button',
        onclick: function () { refreshRunning(true); }
      }, 're-check'));
    }
    return;
  }

  hint.appendChild(h('span', { class: 'txt', text: isHistorical()
    ? 'viewing history — a turn appends to HEAD; fork to branch from here'
    : 'Ctrl+Enter to send · ↑/↓ in the log to scrub' }));
}

/* A turn saves atomically at the end, so NOTHING reaches the event stream while
 * it runs -- every frame lands at once when it commits. There is no per-tool
 * progress to show here, and claiming otherwise would be a lie. Elapsed time is
 * the one thing that genuinely moves, so that is what these two labels report. */
function sendingLabel() {
  const age = elapsedLabel(state.turnStartedAt);
  return 'turn in flight' + (age ? ' · ' + age : '') +
         ' — events appear when it completes';
}

/* "turn 4 · started 40s ago, elsewhere" for a turn this tab is only watching. */
function watchedLabel() {
  const w = state.watchedTurn;
  if (!w) return 'a turn started elsewhere is running on this session';
  const bits = [];
  if (typeof w.turn_index === 'number') bits.push('turn ' + w.turn_index);
  const age = watchedAge(w);
  bits.push(age === null ? 'running elsewhere' : 'started ' + age + ' ago, elsewhere');
  bits.push('events appear when it completes');
  return bits.join(' · ');
}

function elapsedLabel(startedMs) {
  if (!startedMs) return '';
  const secs = Math.max(0, Math.round((Date.now() - startedMs) / 1000));
  return secs < 90 ? secs + 's' : Math.round(secs / 60) + 'm';
}

function watchedAge(w) {
  // started_at is preferred: it keeps counting up as the turn runs, whereas
  // elapsed_seconds is a snapshot taken when we asked.
  const started = parseTime(w.started_at);
  const secs = started ? (Date.now() - started.getTime()) / 1000
    : (typeof w.elapsed_seconds === 'number' ? w.elapsed_seconds : null);
  if (secs === null) return null;
  const whole = Math.max(0, Math.round(secs));
  return whole < 90 ? whole + 's' : Math.round(whole / 60) + 'm';
}

/* "turn 3 · events 14–21" — clicking scrubs to where the turn began. */
function rangeChip(range) {
  const from = range.from_index, to = range.to_index;
  const label = (typeof range.turn_index === 'number' ? 'turn ' + range.turn_index + ' · ' : '') +
    (from === to ? 'event ' + from : 'events ' + from + '–' + to);
  return h('button', {
    class: 'turn-range',
    type: 'button',
    title: 'jump to event ' + from,
    onclick: function () { selectEvent(from); }
  }, label);
}

function onSend(ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  if (state.sending || state.turnRunning) return;
  const input = sessionEls.input;
  const text = String(input.value || '').trim();
  if (!text) return;
  const id = state.sessionId;

  state.sending = true;
  state.turnNote = null;
  state.turnStartedAt = Date.now();
  startTick();
  renderComposer();

  api.post('/api/sessions/' + encodeURIComponent(id) + '/turns', { input: text })
    .then(function (res) {
      if (state.sessionId === id) input.value = '';
      // The turn reports exactly where it landed, so highlight that span
      // instead of diffing the log against what we had before.
      const range = turnRange(res);
      if (range) {
        markFresh(range.from_index, range.to_index);
        setNote('good', 'turn complete', range);
      } else {
        setNote('good', 'turn complete');
      }
      toast('Turn complete.', 'good');
    })
    .catch(function (e) {
      if (e.status === 499) {
        // Cancelled on purpose. Not a failure -- no toast, no red.
        setNote('calm', state.cancelSettled === false
          ? 'cancel delivered — the turn is still unwinding'
          : 'turn cancelled — its events were discarded');
      } else if (e.status === 409) {
        setNote('warn', String(e.message || 'a turn is already running on this session'), null, true);
      } else {
        setNote('warn', 'turn failed — ' + e.message);
        toast('Turn failed: ' + e.message, 'bad');
      }
    })
    .then(function () {
      // Always clear the in-flight flag, even if the user navigated away while
      // the turn ran -- otherwise the composer stays disabled for good.
      state.sending = false;
      state.turnStartedAt = null;
      stopTick();
      if (state.sessionId !== id) return;
      renderComposer();
      // The turn is atomic, so refetch the whole log rather than trusting the
      // events that streamed in mid-flight.
      return loadSession();
    });
}

function turnRange(res) {
  if (!res || typeof res !== 'object') return null;
  if (typeof res.from_index !== 'number' || typeof res.to_index !== 'number') return null;
  return { turn_index: res.turn_index, from_index: res.from_index, to_index: res.to_index };
}

function setNote(tone, text, range, recheck) {
  state.turnNote = { tone: tone, text: text, range: range || null, recheck: !!recheck };
}

function markFresh(from, to) {
  if (typeof from !== 'number' || typeof to !== 'number') return;
  const now = Date.now();
  for (let i = from; i <= to; i++) state.freshIndices[i] = now;
  scheduleFreshSweep();
}

function cancelTurn() {
  if (state.cancelling) return;
  const id = state.sessionId;
  state.cancelling = true;
  renderComposer();
  api.post('/api/sessions/' + encodeURIComponent(id) + '/turns/cancel', {})
    .then(function (res) {
      if (state.sessionId !== id) return;
      // Either way the composer returns to idle; only the wording differs.
      state.turnRunning = false;
      state.watchedTurn = null;
      if (res && res.cancelled) {
        // settled:false means the cancel landed but the turn was still
        // unwinding -- don't claim the log is final; a TurnFailed frame is
        // still on its way over the stream.
        const settled = res.settled !== false;
        state.cancelSettled = settled;
        // Not settled: the log is not final yet, so wait for the TurnFailed
        // frame before trusting what we have.
        state.awaitingUnwind = !settled;
        // The POST /turns still in flight will settle as a 499 and write the
        // note; only speak up here when this tab is not the one that sent it.
        if (!state.sending) {
          setNote('calm', settled
            ? 'turn cancelled — its events were discarded'
            : 'cancel delivered — the turn is still unwinding');
        }
      } else {
        setNote('calm', 'nothing was running');
      }
    })
    .catch(function (e) {
      if (state.sessionId !== id) return;
      setNote('warn', 'could not cancel — ' + e.message, null, true);
      toast('Cancel failed: ' + e.message, 'bad');
    })
    .then(function () {
      state.cancelling = false;
      if (state.sessionId !== id) return;
      renderComposer();
      if (!state.sending) loadSession();
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
// The last feed position we were handed. EventSource sends it back on
// reconnect by itself; we keep our own copy only to tell "resumed from a
// cursor" apart from "never had one", which decides whether a reconnect
// needs a full resync.
let lastEventId = null;
let treeRefreshTimer = null;
let freshSweepTimer = null;
let backoffResetTimer = null;

const FRESH_MS = 1500;

function setConn(stateName, label) {
  const el = document.getElementById('conn');
  if (!el) return;
  el.dataset.state = stateName;
  el.querySelector('.conn-label').textContent = label;
}

async function refreshHealth() {
  // The session list is answered from a projection, so it can be wrong in a
  // way that reading it will never reveal. This is the only signal.
  let health = null;
  try {
    const response = await fetch('/api/health');
    if (!response.ok) return;
    health = (await response.json()).summaries;
  } catch (e) { return; }
  const el = document.getElementById('drift');
  if (!el || !health) return;
  if (health.healthy) { el.hidden = true; return; }
  el.querySelector('.drift-label').textContent = health.following
    ? `list drifted (${health.failed_events})`
    : 'list not updating';
  // Only a drifted list has a remedy from here; a stopped projection needs a
  // restart, which a browser cannot do.
  el.querySelector('.drift-fix').hidden = !health.following;
  el.hidden = false;
}

async function rebuildSummaries() {
  const button = document.getElementById('drift-fix');
  if (!button) return;
  button.disabled = true;
  button.textContent = 'rebuilding';
  try {
    await fetch('/api/summaries/rebuild', { method: 'POST' });
    await refreshHealth();
    if (state.route.name === 'tree') loadTree();
  } catch (e) {
    // Leave the badge up: the problem it reports is still there.
  } finally {
    button.disabled = false;
    button.textContent = 'rebuild';
  }
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
    // Only treat the connection as healthy once it has STAYED open. A server
    // that accepts and immediately drops would otherwise reset the backoff on
    // every attempt, turning reconnection into a one-per-second reload loop.
    clearTimeout(backoffResetTimer);
    backoffResetTimer = setTimeout(function () { backoff = 1000; }, 5000);
    setConn('open', 'live');
    refreshHealth();
    // Every frame carries its feed position as an SSE id, and EventSource
    // replays it in Last-Event-ID on reconnect, so the server resumes from
    // where we left off and the gap arrives as ordinary events. The resync is
    // only for the case where we never got an id to send back — a connection
    // that dropped before its first event, which the server cannot place.
    if (reconnected && !lastEventId) {
      if (state.route.name === 'session' && !state.sending) loadSession();
      else if (state.route.name === 'tree') loadTree();
    } else if (reconnected && state.route.name === 'session' && state.sessionId) {
      // Approval frames carry no feed position, so Last-Event-ID resumes the
      // log but not these -- reconcile them on every reconnect regardless.
      fetchApprovals(state.sessionId);
      // Activity frames carry no feed position either, and the buffer's own
      // design note is explicit that surviving a dropped connection is the
      // reason it exists at all -- without this, a laptop waking mid-turn
      // would show a frozen provisional pane for the rest of that turn, the
      // exact symptom the buffer was built to prevent. refreshRunning() runs
      // first and is awaited: catchUpActivity's guard trusts turnRunning as
      // the authoritative belief, but a turn may have started entirely
      // during the gap, so that belief has to be brought current before the
      // guard checks it, not after.
      if (!state.sending) {
        const id = state.sessionId;
        refreshRunning().then(function () {
          if (state.sessionId === id) catchUpActivity(id);
        });
      }
    }
  };
  stream.onmessage = function (msg) {
    if (msg.lastEventId) lastEventId = msg.lastEventId;
    let payload = null;
    try { payload = JSON.parse(msg.data); } catch (e) { return; }
    if (payload) onStreamEvent(payload);
  };
  stream.onerror = function () {
    if (stream) { stream.close(); stream = null; }
    clearTimeout(backoffResetTimer);
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
  // Approval frames ride the same connection but are not log entries -- they
  // carry no index and must not be treated as one. See approvals.py's `_sse`
  // docstring for why they get no id of their own.
  if (payload.type === 'ApprovalRequested' || payload.type === 'ApprovalSettled') {
    onApprovalFrame(payload);
    return;
  }
  // Provisional turn content rides the same connection but is not a log entry
  // either -- same reasoning as approvals above, see onActivityFrame.
  if (payload.type === 'TurnActivity') {
    onActivityFrame(payload);
    return;
  }
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
  // Remember where a turn we are only watching began: its first frame is the
  // UserMessageSent that opened it, which is exactly from_index.
  if (state.turnRunning && !state.sending && state.watchedTurn &&
      state.watchedTurn.from_index === null && !isTurnEnd(payload.type)) {
    state.watchedTurn.from_index = index;
  }

  // Log frames and activity frames are different channels on purpose: this one
  // is the durable record, arriving in a burst when the turn commits, while
  // provisional content streams in above via onActivityFrame.

  // Everything below reconciles a turn ending, and must run only once per
  // turn -- guard on !known (a genuinely new frame), not on state.turnRunning.
  // A reconnect can replay an already-known TurnCompleted/TurnFailed, and
  // unlike turnRunning (which onActivityFrame's refreshRunning() can now flip
  // from outside this function) known/index is this function's own, so it is
  // the one guard here immune to that race.
  if (!known && isTurnEnd(payload.type)) {
    turnEndSeq++;
    // Server clock, not the browser's: it is what a racing /turns/current
    // response's own started_at gets compared against in fetchTurnRunning,
    // so both sides of that comparison come from the same clock.
    state.lastEndedAt = payload.occurred_at ? Date.parse(payload.occurred_at) : Date.now();
    // A turn ending -- ours or one we're only watching -- reconciles whatever
    // streamed in as activity. On success the real log events (just pushed
    // above) are the record now, so provisional content is dropped outright:
    // it would only duplicate what is about to render from state.events. On
    // failure nothing was appended but the marker itself, so what streamed is
    // the only trace of the attempt -- keep it, behind a disclosure, on this
    // row.
    if (String(payload.type).toLowerCase().indexOf('failed') >= 0) {
      const provisional = state.activity.order
        .map(function (id) { return state.activity.byId[id]; })
        .filter(Boolean);
      if (provisional.length) state.discarded[index] = provisional;
    }
    state.activity = { order: [], byId: {} };
    renderActivity();
    renderTimeline();

    // TurnCompleted / TurnFailed close a turn. For one we were watching, that
    // frame IS the completion signal -- no polling, no follow-up request.
    // This no longer requires state.turnRunning to already be true:
    // refreshRunning() (see onActivityFrame) asks the server whether a turn
    // is running, and the server clears that answer and emits this very
    // frame in two separate steps, not atomically -- so a response can say
    // running:true a moment after this frame already said otherwise, wrongly
    // setting turnRunning true with nothing left to correct it if this branch
    // stayed conditional on the flag it exists to fix. A turn-end frame for a
    // turn we didn't start is authoritative regardless of what we believed.
    if (!state.sending) {
      foreignTurnEnded(payload);
      return;
    }
  }

  // A cancel that returned settled:false left the turn unwinding; its closing
  // frame is the signal that the log is finally trustworthy.
  if (state.awaitingUnwind && isTurnEnd(payload.type)) {
    state.awaitingUnwind = false;
    setNote('calm', 'turn cancelled — its events were discarded');
    renderComposer();
    loadSession();
  }
}

// Provisional turn content. Not a log entry -- it carries no index, and the
// events it previews may never be appended at all if the turn fails.
function onActivityFrame(payload) {
  if (state.route.name !== 'session' || payload.session_id !== state.sessionId) return;
  putActivity(payload);
  // A turn's ordinary log frames only arrive in a burst when it commits (see
  // the comment in onStreamEvent), so a tab that did not send this turn and
  // has not polled /turns/current has no other way to learn one is running --
  // this frame is the only early signal it gets. But activity and log frames
  // are pumped onto the SSE connection by two independent tasks (app.py's
  // _sse), so a frame can legitimately straggle in after the turn it belongs
  // to has already committed -- there is no turn id on the frame to tell the
  // two cases apart client-side. Rather than trust the frame's mere arrival
  // (which would resurrect a turn that already ended and leave a provisional
  // bubble nothing will ever clear), ask the server: refreshRunning() is a
  // real GET, so a straggler for an ended turn correctly reports not-running
  // and never flips turnRunning at all. applyRunning() re-renders activity
  // once the answer is in, whichever way it goes.
  if (!state.sending && !state.turnRunning) refreshRunning();
  renderActivity();
}

// The server already accumulates delta text (each frame's `text` is the full
// prose so far, not an increment), so the browser stores whole entries rather
// than appending -- one accumulator, on the side that has to answer the
// catch-up route anyway. A whole message replaces any accumulated prose under
// the same message_id, which this overwrite handles for free.
function putActivity(entry) {
  const id = entry.message_id;
  if (!state.activity.byId[id]) state.activity.order.push(id);
  state.activity.byId[id] = entry;
}

function renderActivity() {
  if (!sessionEls || !sessionEls.activity) return;
  const box = sessionEls.activity;
  clear(box);
  // state.turnRunning is documented as "only ever about a turn we did not
  // start" (see applyRunning) -- the tab that sent the turn tracks it via
  // state.sending instead, so both must gate this, not turnRunning alone.
  if ((!state.sending && !state.turnRunning) || !state.activity.order.length) return;
  state.activity.order.forEach(function (id) {
    const entry = state.activity.byId[id];
    if (entry) box.appendChild(renderProvisional(entry));
  });
}

/* A whole-message entry's `payload` is raw message_to_dict output -- content
 * and tool_calls sit under "data", not at the top level (the same nesting
 * event_summary() unwraps server-side for the timeline, and message_view()
 * unwraps for /conversation). Mirror that here rather than reading
 * payload.content directly, which is always undefined. */
function activityBody(payload) {
  const data = (payload && payload.data) || {};
  const calls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
  if (calls.length) {
    // Same "→ name, name" shape presenters.py's event_summary() uses for a
    // tool-calling assistant message, so a provisional bubble reads like the
    // timeline row it is about to become.
    return '→ ' + calls.map(function (c) { return (c && c.name) || '?'; }).join(', ');
  }
  return contentText(data.content);
}

function renderProvisional(entry) {
  // A whole message clears `text` server-side and populates `payload`
  // instead, so prefer `text` (the delta accumulator) and fall back to the
  // message content.
  const body = entry.text || activityBody(entry.payload);
  return h('div', { class: 'provisional provisional-' + entry.kind }, [
    h('div', { class: 'provisional-tag', text: 'in progress — not yet recorded' }),
    h('div', { class: 'provisional-body', text: body })
  ]);
}

/* A discarded turn's provisional content: everything that streamed in before
 * a TurnFailed marker with nothing else to show for it. Ephemeral -- gone on
 * reload -- which the disclosure's label says plainly. */
function renderDiscarded(index) {
  const entries = state.discarded[index];
  if (!entries || !entries.length) return null;
  return h('details', { class: 'discarded' }, [
    h('summary', { text: 'discarded — not recorded' }),
    entries.map(function (entry) { return renderProvisional(entry); })
  ]);
}

function onApprovalFrame(payload) {
  if (state.route.name !== 'session' || payload.session_id !== state.sessionId) return;
  if (payload.type === 'ApprovalRequested') {
    state.approvals[payload.id] = payload;
  } else {
    // Settled elsewhere or here -- either way, the card comes down.
    delete state.approvals[payload.id];
    if (state.approvalDeciding === payload.id) state.approvalDeciding = null;
  }
  renderApprovals();
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
document.getElementById('drift-fix').addEventListener('click', rebuildSummaries);
onRoute();
connect();
refreshHealth();

})();
