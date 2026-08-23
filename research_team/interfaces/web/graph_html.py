"""One HTML file that draws a graph, with nothing else in it.

The whole point is that it opens from a mail attachment. No server, no
network request, no build step, no CDN -- because every one of those is a
way for a file somebody was sent to render as a blank page on their machine
six months from now.

**No force-simulation library, and that is the reason this file is small.**
`react-force-graph-2d` is around 60 kB minified before its d3-force
dependency, and every byte of it is there to decide where nodes go.
`graph_layout` has already decided, on the server, so the file below needs
only to draw points at coordinates it is handed and let a reader move the
view -- which is a few hundred lines of plain canvas code with no
dependencies at all. A 900-node export is about 200 kB, nearly all of it the
node names.

**Canvas rather than SVG.** SVG would give text selection and would scale
without a redraw, and it was rejected on size: 900 nodes and 1,400 edges is
2,300 DOM elements, which browsers lay out slowly and which roughly triples
the file next to a flat JSON array of the same data. The drawing is a picture
to look at, not a document to select text out of.

**The palette is the console's `tokens.css` values, copied.** A second copy
of six hex strings, and the alternative is worse: this file has to be
self-contained, so it cannot read the stylesheet, and a reader who has learnt
what colour a `concept` is in the console should not have to learn a second
scheme for the file they were sent. What it costs is that a palette change in
`tokens.css` does not reach exports until somebody changes it here too --
which is the failure to watch for, and is why the constant below names the
file it was copied from.
"""

import json

from research_team.application.graph_export import ExportGraph, to_payload

#: The console's `--k-*` kind tokens, copied. See this module's docstring for
#: why a copy rather than a read of `tokens.css`.
PALETTE = ("#a78bfa", "#6ba7f5", "#5ec98a", "#e2a457", "#5f7d8c", "#7e8b9b")


def color_for_type(entity_type: str) -> str:
    """Byte-for-byte the hash in `entity-colors.ts`, and in the viewer below.

    Two implementations of one hash in one file, which is a real cost and the
    cheaper of the two options: the canvas viewer computes colours in the
    browser from a payload that does not carry them, so its copy cannot be
    removed, and `course_html.py` renders SVG on the server and cannot reach
    the browser's. What holds them together is that all three -- here, the
    `<script>` below, and `entity-colors.ts` -- produce the same colour for
    the same type, which is what `tests/interfaces/test_course_html.py`
    asserts against a literal.
    """
    digest = 0
    for character in entity_type:
        digest = (digest * 31 + ord(character)) & 0xFFFFFFFF
        if digest >= 0x80000000:
            digest -= 0x100000000
    return PALETTE[abs(digest) % len(PALETTE)]


def render_html(graph: ExportGraph) -> str:
    """The whole viewer, with this graph's data inline.

    The payload is written into a `<script>` as a JSON literal with every
    `<` escaped as `\\u003c`. That is not decoration: an entity name
    containing the text `</script>` would otherwise close the tag early and
    the rest of the graph would render as visible page text. `json.dumps`
    does not do this on its own -- it escapes what JSON requires, and `<` is
    not one of those.
    """
    payload = json.dumps(to_payload(graph), ensure_ascii=False).replace("<", "\\u003c")
    title = graph.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _TEMPLATE.replace("__TITLE__", title).replace("__PAYLOAD__", payload)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #0b0e11; --panel: #111418; --line: #232a33;
    --fg: #d7dee7; --fg-dim: #a7b1bd; --accent: #e2a457;
    --link: rgba(138,149,163,0.35); --link-inferred: rgba(138,149,163,0.18);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--fg);
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    overflow: hidden;
  }
  #stage { position: absolute; inset: 0; }
  canvas { display: block; cursor: grab; }
  canvas.dragging { cursor: grabbing; }
  .panel {
    position: absolute; background: var(--panel);
    border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px;
  }
  #head { top: 12px; left: 12px; max-width: min(360px, calc(100% - 24px)); }
  #head h1 { margin: 0 0 2px; font-size: 13px; font-weight: 600; }
  #head p { margin: 0; color: var(--fg-dim); font-size: 11px; }
  #warn { color: var(--accent); }
  #search {
    margin-top: 8px; width: 100%; background: var(--bg); color: var(--fg);
    border: 1px solid var(--line); border-radius: 4px; padding: 4px 6px;
    font: inherit;
  }
  #legend { bottom: 12px; left: 12px; max-height: 40%; overflow: auto; }
  #legend div { display: flex; align-items: center; gap: 6px; font-size: 11px; }
  #legend i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  #detail {
    top: 12px; right: 12px; width: min(300px, calc(100% - 24px));
    max-height: calc(100% - 24px); overflow: auto; display: none;
  }
  #detail h2 { margin: 0 0 4px; font-size: 13px; }
  #detail .meta { color: var(--fg-dim); font-size: 11px; margin: 0 0 6px; }
  #detail ul { margin: 0; padding-left: 14px; font-size: 11px; color: var(--fg-dim); }
  #detail li { margin-bottom: 2px; }
  #detail button {
    margin-top: 8px; background: transparent; color: var(--fg-dim);
    border: 1px solid var(--line); border-radius: 4px; padding: 2px 6px;
    font: inherit; cursor: pointer;
  }
  #tip {
    position: absolute; pointer-events: none; display: none;
    background: var(--panel); border: 1px solid var(--line); border-radius: 4px;
    padding: 3px 6px; font-size: 11px; max-width: 320px;
  }
  #keys { bottom: 12px; right: 12px; color: var(--fg-dim); font-size: 11px; }
</style>
</head>
<body>
<div id="stage"><canvas id="canvas"></canvas></div>

<div class="panel" id="head">
  <h1 id="title"></h1>
  <p id="counts"></p>
  <p id="warn"></p>
  <input id="search" type="search" placeholder="Highlight by name"
         aria-label="Highlight by name">
</div>

<div class="panel" id="legend" aria-label="Entity types"></div>
<div class="panel" id="detail" role="region" aria-label="Selected entity"></div>
<div class="panel" id="keys">drag to pan &middot; scroll to zoom &middot; 0 to fit</div>
<div id="tip" role="tooltip"></div>

<script id="graph-data" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  'use strict';
  var data = JSON.parse(document.getElementById('graph-data').textContent);
  var nodes = data.nodes;
  var edges = data.edges;

  /* The console's `--k-*` kind tokens, copied. See this file's Python
     docstring for why a copy rather than a read. */
  var PALETTE = ['#a78bfa', '#6ba7f5', '#5ec98a', '#e2a457', '#5f7d8c', '#7e8b9b'];

  /* Byte-for-byte the hash in `entity-colors.ts`. It has to be: an export
     whose `concept` nodes are a different colour from the console's would
     make the two drawings of one graph look like drawings of two. */
  function colorForType(entityType) {
    var hash = 0;
    for (var i = 0; i < entityType.length; i += 1) {
      hash = (hash * 31 + entityType.charCodeAt(i)) | 0;
    }
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }

  var byId = Object.create(null);
  nodes.forEach(function (node) { byId[node.id] = node; });

  /* Which edges touch each node, resolved once. The detail panel needs it on
     every click and a scan of every edge per click is the one operation here
     that is linear in the graph *and* on an interaction path. */
  var incident = Object.create(null);
  edges.forEach(function (edge) {
    (incident[edge.source] || (incident[edge.source] = [])).push(edge);
    (incident[edge.target] || (incident[edge.target] = [])).push(edge);
  });

  var canvas = document.getElementById('canvas');
  var ctx = canvas.getContext('2d');
  var tip = document.getElementById('tip');
  var detail = document.getElementById('detail');

  var view = { scale: 1, x: 0, y: 0 };
  var selected = null;
  var hovered = null;
  var highlight = '';
  var width = 0, height = 0;

  /* How big a node is drawn on *screen*, so the mark stays the same size at
     every zoom -- the same choice `GraphCanvas` documents. Shrinks as the
     graph grows: 5px dots on a 900-node drawing are a solid mat. */
  var RADIUS = nodes.length > 600 ? 3 : nodes.length > 200 ? 4 : 5.5;

  /* The zoom at which names start being drawn, and it depends on how many
     names there are rather than being a constant. `compute_layout` normalises
     every drawing to a 1000-unit square, so the typical gap between two nodes
     is about `1000 / sqrt(n)` layout units, and the gap in screen pixels is
     that times the zoom. A drawn label is wide: measured at 11px monospace,
     the 28-character cap below is about 185px across. 100 is deliberately
     under that -- graph labels always overlap somewhat, and holding out for
     no overlap at all would mean never showing them -- but well above the 60
     this was first written at, which put 220 names on one screen as an
     unreadable mat. Judged by eye against a rendered file, not derived.

     A 40-node graph therefore shows names as soon as it opens and a
     2,000-node one waits until somebody has zoomed into a part of it, which
     is the same bargain `GraphCanvas` strikes with its flat 0.7 -- but stated
     in terms of the thing that actually decides it. */
  var LABEL_AT = (100 * Math.sqrt(Math.max(nodes.length, 1))) / 1000;

  function resize() {
    var ratio = window.devicePixelRatio || 1;
    width = window.innerWidth;
    height = window.innerHeight;
    /* `style.width`, not `clientWidth`. `clientWidth` is a read-only getter,
       and this file runs under `'use strict'` -- assigning to it throws, which
       takes `resize` down before it ever paints and leaves a canvas at its
       300x150 default with the panels around it rendering perfectly. Caught by
       opening the file, not by any check: the page looks loaded. */
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    /* `setTransform`, not `scale`: this runs on every resize, and `scale`
       multiplies into whatever transform was already there -- so a window
       dragged wider twice would draw at four times the device ratio. */
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function bounds() {
    if (!nodes.length) return { minX: -1, minY: -1, maxX: 1, maxY: 1 };
    var b = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    nodes.forEach(function (n) {
      if (n.x < b.minX) b.minX = n.x;
      if (n.y < b.minY) b.minY = n.y;
      if (n.x > b.maxX) b.maxX = n.x;
      if (n.y > b.maxY) b.maxY = n.y;
    });
    return b;
  }

  function fit() {
    var b = bounds();
    var pad = 60;
    /* `|| 1` guards the one-node and all-coincident cases, where the span is
       zero and the scale would be Infinity -- the canvas then draws nothing
       at all, which reads as a broken file rather than as a small graph. */
    var spanX = (b.maxX - b.minX) || 1;
    var spanY = (b.maxY - b.minY) || 1;
    view.scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
    /* A ceiling, for the same reason the console caps its fit: a graph of
       three nodes fitted to the window draws each one as a dinner plate. */
    view.scale = Math.min(view.scale, 3);
    view.x = width / 2 - ((b.minX + b.maxX) / 2) * view.scale;
    view.y = height / 2 - ((b.minY + b.maxY) / 2) * view.scale;
    draw();
  }

  function toScreen(node) {
    return { x: node.x * view.scale + view.x, y: node.y * view.scale + view.y };
  }

  function matches(node) {
    return highlight !== '' && node.name.toLowerCase().indexOf(highlight) !== -1;
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);

    var near = selected === null ? null : Object.create(null);
    if (near) {
      near[selected] = true;
      (incident[selected] || []).forEach(function (e) {
        near[e.source] = true; near[e.target] = true;
      });
    }

    edges.forEach(function (edge) {
      var a = byId[edge.source], b = byId[edge.target];
      if (!a || !b) return;
      var lit = near !== null && (edge.source === selected || edge.target === selected);
      var pa = toScreen(a), pb = toScreen(b);
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.strokeStyle = lit ? '#e2a457'
        : edge.inferred ? 'rgba(138,149,163,0.18)' : 'rgba(138,149,163,0.35)';
      ctx.lineWidth = lit ? 1.6 : 1;
      /* Dashed for inferred, matching the console: an inferred edge is
         arithmetic over two dates, not something a document said, and the
         two must not draw the same. */
      ctx.setLineDash(edge.inferred ? [2, 2] : []);
      ctx.stroke();
    });
    ctx.setLineDash([]);

    nodes.forEach(function (node) {
      var p = toScreen(node);
      /* Off-screen nodes are skipped rather than drawn and clipped. At a
         zoom where a reader is reading labels most of a large graph is
         outside the window, and the text calls are the expensive part. */
      if (p.x < -80 || p.y < -80 || p.x > width + 80 || p.y > height + 80) return;

      var dim = (near !== null && !near[node.id]) || (highlight !== '' && !matches(node));
      ctx.globalAlpha = dim ? 0.18 : 1;
      var color = colorForType(node.entity_type);

      ctx.beginPath();
      ctx.arc(p.x, p.y, RADIUS, 0, 2 * Math.PI);
      /* Hollow means synthesised by a derivation pass rather than extracted
         from a document -- `GraphEntity.inferred`. A class node that drew
         like an extracted entity would assert a document said something no
         document said. */
      if (node.inferred) {
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
      } else {
        ctx.fillStyle = color; ctx.fill();
      }

      if (node.id === selected || (highlight !== '' && matches(node))) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, RADIUS + 3.5, 0, 2 * Math.PI);
        ctx.strokeStyle = '#e2a457'; ctx.lineWidth = 1.5; ctx.stroke();
      }

      if (view.scale >= LABEL_AT || node.id === selected) {
        var name = node.name;
        var label = name.length > 28 ? name.slice(0, 27) + '…' : name;
        ctx.font = '11px ui-monospace, Menlo, Consolas, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillStyle = '#d7dee7';
        ctx.fillText(label, p.x, p.y + RADIUS + 3);
      }
      ctx.globalAlpha = 1;
    });
  }

  function nodeAt(x, y) {
    var best = null, bestDistance = (RADIUS + 5) * (RADIUS + 5);
    for (var i = nodes.length - 1; i >= 0; i -= 1) {
      var p = toScreen(nodes[i]);
      var dx = p.x - x, dy = p.y - y;
      var d = dx * dx + dy * dy;
      if (d <= bestDistance) { bestDistance = d; best = nodes[i]; }
    }
    return best;
  }

  function showDetail(node) {
    if (!node) { detail.style.display = 'none'; return; }
    var lines = (incident[node.id] || []).map(function (edge) {
      var other = edge.source === node.id ? byId[edge.target] : byId[edge.source];
      var arrow = edge.source === node.id ? '→' : '←';
      return {
        type: edge.relationship_type,
        arrow: arrow,
        name: other ? other.name : edge.target
      };
    });
    detail.textContent = '';
    var h = document.createElement('h2');
    h.textContent = node.name;
    var meta = document.createElement('p');
    meta.className = 'meta';
    meta.textContent = node.entity_type + (node.temporal ? ' · ' + node.temporal : '');
    var list = document.createElement('ul');
    lines.forEach(function (line) {
      var item = document.createElement('li');
      /* Built through `textContent` rather than an HTML string. Entity names
         here are model output and contain angle brackets often enough that
         `innerHTML` would render fragments of them as markup -- and this file
         is opened from `file://`, where a page has more reach than one served
         over http. */
      item.textContent = line.arrow + ' ' + line.type + ': ' + line.name;
      list.appendChild(item);
    });
    var close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Clear selection';
    close.addEventListener('click', function () {
      selected = null; showDetail(null); draw();
    });
    detail.appendChild(h); detail.appendChild(meta);
    if (lines.length) detail.appendChild(list);
    detail.appendChild(close);
    detail.style.display = 'block';
  }

  var dragging = false, moved = false, lastX = 0, lastY = 0;

  canvas.addEventListener('mousedown', function (event) {
    dragging = true; moved = false;
    lastX = event.clientX; lastY = event.clientY;
    canvas.classList.add('dragging');
  });

  window.addEventListener('mouseup', function (event) {
    if (dragging && !moved) {
      var hit = nodeAt(event.clientX, event.clientY);
      selected = hit ? hit.id : null;
      showDetail(hit);
      draw();
    }
    dragging = false;
    canvas.classList.remove('dragging');
  });

  window.addEventListener('mousemove', function (event) {
    if (dragging) {
      var dx = event.clientX - lastX, dy = event.clientY - lastY;
      /* A few pixels of slack before a click becomes a drag. Without it a
         mouse that moves one pixel between press and release swallows the
         click, and selecting a node becomes something that works four times
         in five. */
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) moved = true;
      view.x += dx; view.y += dy;
      lastX = event.clientX; lastY = event.clientY;
      tip.style.display = 'none';
      draw();
      return;
    }
    var hit = nodeAt(event.clientX, event.clientY);
    if (hit !== hovered) {
      hovered = hit;
      if (hit) {
        tip.textContent = hit.name + ' (' + hit.entity_type + ')' +
          (hit.temporal ? ' — ' + hit.temporal : '');
        tip.style.display = 'block';
      } else {
        tip.style.display = 'none';
      }
    }
    if (hit) {
      tip.style.left = (event.clientX + 12) + 'px';
      tip.style.top = (event.clientY + 12) + 'px';
    }
  });

  canvas.addEventListener('wheel', function (event) {
    event.preventDefault();
    var factor = Math.pow(1.0015, -event.deltaY);
    var next = Math.min(Math.max(view.scale * factor, 0.02), 40);
    /* Zoom about the pointer, not the origin: the point under the cursor
       stays under the cursor. Zooming about the canvas centre means the thing
       a reader is pointing at slides away as they zoom toward it. */
    view.x = event.clientX - (event.clientX - view.x) * (next / view.scale);
    view.y = event.clientY - (event.clientY - view.y) * (next / view.scale);
    view.scale = next;
    draw();
  }, { passive: false });

  document.getElementById('search').addEventListener('input', function (event) {
    highlight = event.target.value.trim().toLowerCase();
    draw();
  });

  window.addEventListener('keydown', function (event) {
    if (event.target && event.target.tagName === 'INPUT') return;
    if (event.key === '0') fit();
    else if (event.key === '+' || event.key === '=') { view.scale *= 1.2; draw(); }
    else if (event.key === '-') { view.scale /= 1.2; draw(); }
    else if (event.key === 'Escape') { selected = null; showDetail(null); draw(); }
  });

  window.addEventListener('resize', resize);

  document.getElementById('title').textContent = data.title;
  document.getElementById('counts').textContent =
    nodes.length + ' entities · ' + edges.length + ' relationships · ' + data.scope;
  if (data.truncated) {
    document.getElementById('warn').textContent =
      'Truncated: this is part of a larger graph, not all of it.';
  }

  var types = {};
  nodes.forEach(function (n) { types[n.entity_type] = (types[n.entity_type] || 0) + 1; });
  var legend = document.getElementById('legend');
  Object.keys(types).sort().forEach(function (type) {
    var row = document.createElement('div');
    var swatch = document.createElement('i');
    swatch.style.background = colorForType(type);
    var label = document.createElement('span');
    label.textContent = type + ' (' + types[type] + ')';
    row.appendChild(swatch); row.appendChild(label);
    legend.appendChild(row);
  });

  resize();
  fit();
})();
</script>
</body>
</html>
"""
