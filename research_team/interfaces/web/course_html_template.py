"""Offline HTML export template for course book rendering."""

_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  /* The console's `tokens.css` values, copied -- `graph_html.py`'s reasoning
     applies unchanged: this file cannot read a stylesheet, and a reader who
     has learnt the console's colours should not learn a second scheme. */
  :root {
    --bg: #0b0e11; --panel: #111418; --line: #232a33;
    --fg: #d7dee7; --fg-dim: #a7b1bd; --accent: #e2a457;
    --edge: rgba(138,149,163,0.35); --ok: #5ec98a; --no: #e2705a;
    --measure: 42rem;
  }
  /* Light is the default a phone in daylight wants and dark is what a laptop
     at night wants, so the page follows the reader rather than choosing. Both
     palettes are declared; neither is a filter over the other. */
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #fbfaf8; --panel: #ffffff; --line: #e2ddd4;
      --fg: #22262b; --fg-dim: #5f6a75; --accent: #9a5f14;
      --edge: rgba(95,106,117,0.45);
      /* Darkened from the dark palette's #5ec98a/#e2705a, which are chosen
         to sit on #0b0e11 and are unreadable on white. A verdict a reader
         cannot read is a verdict that did not happen. */
      --ok: #17703f; --no: #a8321c;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 16px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
          Helvetica, Arial, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  .wrap { max-width: var(--measure); margin: 0 auto; padding: 1.5rem 1.1rem 6rem; }
  h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 .3rem; }
  h2 { font-size: 1.3rem; margin: 2.6rem 0 .6rem; padding-top: 1.4rem;
       border-top: 1px solid var(--line); }
  h3 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  h4, h5, h6 { font-size: 1rem; margin: 1.4rem 0 .3rem; }
  p, ul, ol, blockquote, table { margin: 0 0 .9rem; }
  a { color: var(--accent); }
  code { font: .88em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  pre { background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
        padding: .7rem .8rem; overflow-x: auto; }
  blockquote { border-left: 3px solid var(--line); margin-left: 0; padding-left: .9rem;
               color: var(--fg-dim); }
  hr { border: 0; border-top: 1px solid var(--line); margin: 1.6rem 0; }
  .settled { margin: .75rem 0 0; border-left: 3px solid var(--accent);
             padding-left: .6rem; font-size: .9rem; }
  .meta { color: var(--fg-dim); font-size: .85rem; margin: 0 0 .2rem; }
  .quiet { color: var(--fg-dim); font-size: .82rem; margin: .4rem 0 0; }
  nav { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
        padding: .8rem 1rem .8rem 1.6rem; margin: 1.4rem 0; }
  nav ol { margin: 0; padding-left: .6rem; }
  nav ul { margin: .2rem 0 .4rem; padding-left: 1rem; list-style: none; }
  nav ul a { color: var(--fg-dim); }
  section { scroll-margin-top: 1rem; }
  article { scroll-margin-top: 1rem; }
  .unit { color: var(--fg); }

  /* Widgets. One panel treatment for all ten, so a reader learns the frame
     once and the differences inside it read as differences of kind. */
  .w { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
       padding: .9rem 1rem; margin: 1.2rem 0; }
  .w-kind { text-transform: uppercase; letter-spacing: .08em; font-size: .68rem;
            color: var(--fg-dim); margin: 0 0 .35rem; }
  .w-title { font-weight: 600; margin: 0 0 .5rem; }
  .w p:last-child { margin-bottom: 0; }
  .absent { color: var(--fg-dim); border-left: 3px solid var(--accent);
            padding-left: .8rem; margin: .5rem 0 0; font-size: .92rem; }
  .live { margin: .7rem 0 0; font-size: .88rem; }
  button { font: inherit; color: var(--fg); background: transparent;
           border: 1px solid var(--line); border-radius: 6px; padding: .35rem .8rem;
           cursor: pointer; }
  button:hover { border-color: var(--accent); }
  input[type=text] { font: inherit; color: var(--fg); background: var(--bg);
    border: 1px solid var(--line); border-radius: 4px; padding: .1rem .35rem; }
  .opts, .cards, .checks { list-style: none; padding: 0; margin: .6rem 0; }
  .opts > li, .checks > li { margin: .3rem 0; }
  .opts label, .checks label { display: flex; gap: .55rem; align-items: baseline;
                               cursor: pointer; }
  .fb, .note { margin: .2rem 0 .4rem 1.7rem; font-size: .9rem; color: var(--fg-dim); }
  .verdict { margin: .6rem 0 0; font-weight: 600; }
  .verdict.right { color: var(--ok); }
  .verdict.wrong { color: var(--no); }
  .rationale { margin-top: .7rem; border-top: 1px solid var(--line); padding-top: .6rem; }
  .cloze-text { line-height: 2.2; }
  .blank.right { border-color: var(--ok); }
  .blank.wrong { border-color: var(--no); }
  .revealed { color: var(--ok); font-size: .85em; margin-left: .25rem; }
  .flip { width: 100%; text-align: left; }
  .flip[aria-expanded=true] { border-color: var(--accent); }
  .back { padding: .5rem .8rem; border-left: 3px solid var(--accent); margin: .3rem 0 .6rem; }
  .req { color: var(--fg-dim); font-size: .78rem; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: .93rem; }
  th, td { border: 1px solid var(--line); padding: .35rem .55rem; text-align: left;
           vertical-align: top; }
  thead th { background: var(--bg); }
  .quotes figure { margin: .7rem 0 0; }
  .quotes blockquote { border-left: 3px solid var(--accent); font-size: .95rem;
                       color: var(--fg); margin: 0; }
  figcaption { color: var(--fg-dim); font-size: .82rem; margin-top: .25rem; }
  .figure { overflow-x: auto; }
  /* `min-width` with the scrolling wrapper above it, and it is what makes
     these figures readable on a phone. A 1,000-unit viewBox scaled to a
     375px column puts the node labels at about four device pixels -- present,
     selectable, and unreadable. Below 30rem the figure scrolls sideways at a
     legible size instead; above it, `width: 100%` governs as before.
     Measured in Chromium at 390x844, not reasoned. */
  .figure svg { display: block; width: 100%; min-width: 30rem; height: auto;
    max-height: 70vh; }
  .params { color: var(--fg-dim); font-size: .88rem; }
  @media (max-width: 30rem) { .wrap { padding: 1rem .8rem 4rem; } h1 { font-size: 1.35rem; } }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>__TITLE__</h1>
  <p class="meta">Exported __EXPORTED__ from project __PROJECT__, authoring run __RUN__.</p>
  <p class="meta">This file needs no server and no network. Its links point back at
     <code>__ORIGIN__</code>, which is the address this export was requested from — they
     only work for someone who can reach it.</p>
  <p class="meta">A teaching copy: the questions grade themselves here, which means the
     answers are in the file. Do not use it as an exam paper.</p>
  __SETTLED__
  __NEVERSTARTED__
  __NOTWRITTEN__
</header>
__NAV__
__BODY__
</div>
<script>
(function () {
  'use strict';

  /* `grading.py`'s `normalize_answer`, in the browser. Case and spacing are
     typing; word choice is knowledge. It is not byte-identical: Python's
     `casefold` folds a handful of pairs (German sharp s, for one) that
     `toLowerCase` leaves alone, so a cloze answer separated from a reader's
     only by such a pair is marked wrong here and right on the server. Stated
     rather than fixed -- the fix is a case-folding table in every exported
     file. */
  function normalise(value) {
    return String(value == null ? '' : value).trim().replace(/\s+/g, ' ').toLowerCase();
  }

  document.querySelectorAll('.w-mcq').forEach(function (widget) {
    var key = JSON.parse(widget.getAttribute('data-key'));
    var verdict = widget.querySelector('.verdict');
    var rationale = widget.querySelector('.rationale');
    widget.querySelector('.check').addEventListener('click', function () {
      var picked = [];
      widget.querySelectorAll('input').forEach(function (input, index) {
        if (input.checked) picked.push(index);
      });
      /* Set equality, not overlap -- `_grade_mcq`'s reasoning, which is that
         anything looser marks a reader who ticked everything as correct. */
      var right = picked.length === key.length &&
        picked.every(function (i) { return key.indexOf(i) !== -1; });
      widget.querySelectorAll('.fb').forEach(function (note, index) {
        note.hidden = picked.indexOf(index) === -1;
      });
      verdict.textContent = right ? 'Correct.'
        : picked.length === 0 ? 'Nothing selected.' : 'Not quite.';
      verdict.className = 'verdict ' + (right ? 'right' : 'wrong');
      verdict.hidden = false;
      if (rationale) rationale.hidden = false;
    });
  });

  document.querySelectorAll('.w-cloze').forEach(function (widget) {
    var verdict = widget.querySelector('.verdict');
    widget.querySelector('.check').addEventListener('click', function () {
      var hits = 0, total = 0;
      widget.querySelectorAll('.blank').forEach(function (input) {
        var expected = input.getAttribute('data-answer');
        var right = input.value.trim() !== '' &&
          normalise(input.value) === normalise(expected);
        input.classList.remove('right', 'wrong');
        input.classList.add(right ? 'right' : 'wrong');
        total += 1;
        if (right) hits += 1;
        /* The answer is revealed per blank, having been attempted -- including
           a blank left empty, because the reader submitted and the item is
           spent. `_grade_cloze` makes the same call. */
        var after = input.nextElementSibling;
        if (!after || !after.classList.contains('revealed')) {
          var shown = document.createElement('span');
          shown.className = 'revealed';
          shown.textContent = expected;
          input.parentNode.insertBefore(shown, input.nextSibling);
        }
      });
      verdict.textContent = hits + ' of ' + total + ' correct.';
      verdict.className = 'verdict ' + (hits === total ? 'right' : 'wrong');
      verdict.hidden = false;
    });
  });

  document.querySelectorAll('.flip').forEach(function (button) {
    button.addEventListener('click', function () {
      var open = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', open ? 'false' : 'true');
      button.nextElementSibling.hidden = open;
    });
  });
})();
</script>
</body>
</html>
"""
