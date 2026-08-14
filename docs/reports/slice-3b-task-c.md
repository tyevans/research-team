# Slice 3b, task C — the graph cluster off `research.css`

Read against `bd4b16f`. Four components rewritten, 35 class names gone from the
graph's half of `research.css` (the file itself untouched, as briefed — task E
deletes it whole).

---

# Finding, separate from the rewrite: slice 3a shipped a focus-ring fix that has never applied

This is the more consequential of the two things in this report and is written
first for that reason. It is not a consequence of the graph rewrite; the graph
rewrite is only how it was found.

**What slice 3a claimed.** Its report states that the document row's inward
focus ring "came with it intact — the rules moved from `research.css` to a
`RING_INWARD` constant and nothing about the numbers changed", and that
`DocumentBrowser.browser.test.tsx` "is the measurement and still is". The
constant it shipped (`2ec37db`) was:

```
focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-[-2px]
```

**What was actually true.** `tokens.css:354` declares a global
`:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px }`,
**unlayered**. Tailwind utilities are emitted into `@layer utilities`, and an
unlayered normal declaration beats a layered one regardless of specificity — so
`.focus-visible\:outline-offset-\[-2px\]` at (0,2,0) loses to a bare
`:focus-visible` at (0,1,0). The class was in the attribute, the rule was in the
bundle, and the computed offset was `+1px` on every row. **The ring has been
clipped on the Documents tab since that slice**, exactly as it was before the
fix, and the browser test that would have said so was reported as carried across
without being run — 3a's report is explicit that no gate and no suite ran
locally and CI would be first. Nothing had run `test:browser` since.

**Measured** (Chromium, headless, 1440×900 per `vite.config.ts`, 2026-08-14),
`DocumentBrowser.browser.test.tsx` on this branch before any change:

| Test | Assertion | Result |
| --- | --- | --- |
| first document row | ring left `-2` vs clip left `1` | FAIL |
| a row further down | ring left `-2` vs clip left `1` | FAIL |
| the scroller itself | ring `35` vs border box `38` | FAIL |

3 of 4 red. Green after the fix.

Task A reached the same diagnosis independently, from the topic list, and
measured it the same way.

**The fix, and why it is not the `!` Task A used.** `.lay-ring-inward` in
`layout.css`:

```css
.lay-ring-inward:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
```

(0,2,0) against the global's (0,1,0), both unlayered, so it wins on specificity
in the only comparison that is allowed to happen. Tailwind's `!` modifier
(`outline-offset-[-2px]!`) also works — important reverses layer order — and I
chose against it on three counts: this codebase uses `!` nowhere, so it would be
establishing a first one to paper over a layering hazard; it leaves every future
inward ring one forgotten `!` away from the identical silent failure, which is
how this defect arrived in the first place; and correcting only the offset keeps
the width and colour depending on the global rule, which is the same coupling one
step shorter. Declaring the ring whole in one named place also gives the
measurement somewhere to live.

**Sites swept.** Every `focus-visible:outline-offset` utility and
`RING_INWARD`-style constant in `src/`:

| Site | State | Action |
| --- | --- | --- |
| `research/DocumentBrowser.tsx` | broken, 3 tests red | fixed → `lay-ring-inward` |
| `research/GraphPane.tsx` (`RESULT_ROW`) | written by me, same defect | `lay-ring-inward` |
| `research/GraphDetail.tsx` (`ROW`) | written by me, same defect | `lay-ring-inward` |
| `research/TopicQueue.tsx` | Task A's, fixed with a trailing `!` | left alone — see below |
| `common/TruncatedText.tsx:127` | `focus-visible:outline-offset-2`, no `!` | **left alone, flagged** |

`TruncatedText` is the third site and the only one nobody has touched. It asks
for `+2px` and gets the global's `+1px`, so the utility is equally inert — but
the offset is *positive*, so nothing is clipped and there is no visible defect,
only a declaration that does nothing. It is a shared primitive outside this
slice, and changing it would be a visual change (1px → 2px) made blind. Worth a
backlog entry, not a drive-by.

**The one thing left inconsistent, and it needs a decision above me.** The tree
now has two spellings of one fix: `.lay-ring-inward` in three files, and a
trailing `!` in `TopicQueue.tsx`. Both work and both are measured. I did not
edit `TopicQueue.tsx` because Task A is live in it and two agents in one file is
the failure this project keeps a rule about. **Recommendation: unify on
`.lay-ring-inward`** — the reasons above apply to the topic list identically,
and a one-line swap of Task A's constant body is all it costs. Say the word and
I will do it, or Task A can; what should not survive the slice is two.

---

## What was rewritten

| File | Was | Now |
| --- | --- | --- |
| `GraphPane.tsx` (`GraphBrowser`) | 14 class names | utilities + `PANEL`/`RESULT_ROW`/`NOTICE` constants, `STAGE_FIELD` inline style |
| `GraphDetail.tsx` | 11 | utilities + a `ROW` constant |
| `GraphLegend.tsx` | 7 | utilities + a `NOTE` constant |
| `GraphCanvas.tsx` | 1 (`graph-canvas`) | `absolute inset-0`, plus `data-graph-canvas` |

`GraphCanvas`'s `getComputedStyle` palette mechanism is untouched, as briefed.

Four `data-` hooks added for the browser test to query by, following slice 3a's
`[data-document-scroll]` precedent: `data-result-scroll`, `data-result-row`,
`data-edge-scroll`, `data-edge-row`.

## The z-index decision, in full

**Outcome: one named class, `.lay-region-float` in `layout.css`, whose only
declaration is `z-index: var(--z-sticky)`. All three floats carry it.**

There was no precedent to follow. The brief asked me to find how an
already-migrated sticky element does it; there is none. Every `z-index` in
`src/styles/` outside `tokens.css` is in a stylesheet — `layout.css`'s
`.lay-overlay-host`, `states.css`'s toasts, `workspace.css`'s
`.file-view-head`, and the three graph rules — and nothing in `src/presentation`
sets one at all, by class or inline. The migration has simply never met this
case.

**What I rejected, and why it matters more than what I chose.** Tailwind will
happily generate `z-[var(--z-sticky)]`, and it satisfies the letter of what
`stacking.test.ts`'s docstring says it wants: "a `z-index` may only be a
`var(--z-*)` whose token is declared in `tokens.css`". It is also exactly the
hole that test was written to close, one file further away. `SOURCES` is
`readdirSync('src/styles')` — the check reads stylesheets and nothing else, so a
utility is generated into an asset it never opens. The class that shipped the
original defect (`.agents-panel` at 40 over a modal backdrop at 20) would be
reachable again as `z-[40]` in a `className`, with a green build. The test's own
docstring anticipates the shape and says "extend `SOURCES` rather than granting
it an exception" — but extending it to sweep TSX means either matching arbitrary
`z-[…]` utilities by regex over component files, which collides with the stories
that set `position: fixed` inline on purpose (the reason inline styles were left
out of scope in the first place), or accepting that the sweep is now
approximate. An inline `style={{ zIndex }}` is the same hole with less disguise.

So: **the honest move was to stop the rewrite one declaration short.** Three
elements that each need one property that must live in a swept stylesheet get
one class that declares that property and nothing else. It cannot grow into a
second dressing for these panels — there is nothing else in it — and it is in
`layout.css` rather than a new file because a stacking role is layout's to own
and `--z-sticky`'s own definition ("things that float *within* a region and must
not escape it") is a layout statement. It also means `check-deleted.mjs`'s
frozen `STYLESHEETS` array is untouched by this task, which keeps task E's edit
to that file a single line.

The cost, stated: `research.css` dying does not mean the graph is 100 %
utilities. It is 35 rules replaced by utilities and one three-line rule that
moved house. Anyone reading "the stylesheet is dead" should know that.

`tokens.css`'s inventory comment (now around `:190`) is updated to say all of
this — that `.file-view-head` still names the token directly, that the graph's
three floats now reach it through `.lay-region-float`, and why a utility was
refused.

## The rings — what was actually measured

Chromium, headless, at the 1440×900 viewport `vite.config.ts` sets, on
2026-08-14. Scroller `p-[4px]`, ring `outline-width: 2px`.

**Before (the outward ring the utility left in place), graph results panel:**

| | value |
| --- | --- |
| computed `outline-offset` | `1px` (not `-2px` — the utility lost) |
| row border box | `12..328` |
| ring reach | `9..331` |
| scroller clip (padding box) | `11..329` |

Two pixels outside the clip on each side. The plan's §5.2 predicted "1px of
slack, marginal not broken" from the padding arithmetic — 4px padding against a
3px reach. **That arithmetic was right about the geometry and wrong about the
conclusion, because the offset it assumed was never the offset in force.** The
`+1px` global applied, not `-2px`, so it was clipped rather than marginal.

**After `.lay-ring-inward`:**

| | results panel | detail edges |
| --- | --- | --- |
| computed `outline-offset` | `-2px` | `-2px` |
| row border box | `15..325` | `595..885` |
| ring reach | `15..325` | `595..885` |
| scroller clip | `11..329` | `591..889` |

4px of clearance each side, and the ring is drawn wholly inside the row, so it
survives any future tightening of the scroller's padding.

`DocumentBrowser`'s own numbers, and why a class rather than `!`, are in the
finding at the top of this report.

## Stacking, measured

`graph-dressing.browser.test.tsx` asserts `--z-sticky` is declared and non-empty
(an undeclared custom property makes the browser drop the declaration, which
looks exactly like the rule being obeyed), that exactly three elements carry
`.lay-region-float`, that each computes `z-index: 10` and `position: absolute`
(a `z-index` on a static element does nothing), and that the canvas is a
positioned sibling at `auto` that precedes them in DOM order.

## Tests

- `GraphPane.test.tsx` (30), `GraphCanvas.test.tsx`, `GraphLegend.test.tsx` —
  **43 pass, unchanged.** Not one of them asserted a class name, so nothing had
  to be rewritten and no coverage was traded. `graph-store.test.ts` untouched.
- `graph-dressing.browser.test.tsx` — new, 4 cases: the two rings, the legend
  note's single-side border, and the stacking inventory. The two ring cases were
  **proved red** (offset measured `1`, expected `-2`) before `.lay-ring-inward`
  and are green after. The border and stacking cases were **not** proved red;
  the docstring says so and says what would make each red.

  It also had a bug of its own, found by running the full suite rather than the
  file: the stacking case queried `[data-fake-canvas]` straight after `render`,
  and `GraphCanvas` is `React.lazy` even when mocked, so the element arrives a
  microtask after React commits. Green alone and red in company — the shape
  `CLAUDE.md` warns about in the other direction. It now waits for the canvas,
  and every query is scoped to the render container rather than `document`, so a
  leaked render from a neighbouring file cannot be counted.
- Full `npm run test:browser`: **57 pass, 19 files**, twice consecutively (was
  52 passing with 5 failing when this task started).
- `scripts/` + `src/presentation/research` + `src/styles`: 227 pass.

`check-tailwind.mjs`, `check-size.mjs`, `stacking.test.ts`, `check-deleted.test.ts`
all pass. Every arbitrary utility introduced was grepped out of the built
`index.css` and emits a rule — including `min(320px,100% - 20px)` (Tailwind
strips the `calc()` wrapper; `min()` does its own arithmetic, so this is correct
CSS), `color-mix(in srgb,var(--color-bg) 88%,transparent)`, `font-size:11px`,
`grid-template-columns:10px 1fr auto` and the eight arbitrary paddings. I did
**not** run `npm run verify`, `pytest` or `ruff`, per the brief.

## The two other places a utility could not go

1. **The stage's graph-paper field** is a module-level inline style
   (`STAGE_FIELD` in `GraphPane.tsx`). `bg-[image:…]` would take it — two
   `linear-gradient`s over a `color-mix`, every space underscored, comma-joined
   inside one bracket — and `check-tailwind.mjs` does not cover the `bg-`
   family, so a typo in that string emits nothing, warns nothing, and shows
   nothing on a stage that is meant to be nearly blank. It carries no `z-index`,
   so it is outside what `stacking.test.ts` exists to stop.
2. **The entity-type `<select>`'s `max-width: 40%`** is an inline style. The
   rule it replaces was deliberately `select.graph-entity-type` rather than a
   bare class, because `composer.css`'s unlayered `select.input { max-width:
   22rem }` outranks one — and a `max-w-[40%]` utility loses that contest twice
   over, on specificity *and* on layer. It is the same hazard as the ring, met a
   second time in the same file. It goes when `.input` does.

## What the plan got wrong

1. **§2's ring prediction.** "1px of slack, marginal rather than broken" for
   `.graph-results-panel` and `.graph-detail-edges`. Correct arithmetic, wrong
   premise: those two `padding: 4px` rules were being measured against a `-2px`
   offset that a sibling component had failed to apply, and against the actual
   `+1px` the rings were clipped by 2px per side. The recommendation
   (`outline-offset: -2px`) was right anyway.
2. **§2's z-index framing assumed a precedent might exist.** None does. This is
   the first migrated element in the codebase that needs a stacking order.
3. **Not the plan's fault, but worth recording against §5.2's ledger:** slice
   3a's focus-ring fix is listed there as delivered for the document row. It was
   written and did not apply — see the finding at the top. The general shape is
   the one 3a itself named, *an unlayered rule beats `@layer utilities`*, and it
   bit the very slice that wrote the warning, in the same commit.

## What I could not do

- **Nothing in scope was skipped.** All 35 class names are off the components.
- Not attempted, and not mine: the three `PROJECT_TRACKS` region widths (still
  chosen rather than measured, a fourth slice running), anything below
  `--bp-wide`, and `.extraction-merge-list`.
- **`DocumentBrowser.tsx` is edited** — two lines, turning `RING_INWARD` into
  `'lay-ring-inward'` plus its docstring. It was not in my file list, but it was
  also not fenced off, and leaving three red browser tests and a shipped-broken
  focus ring in place for task F to trip over would have been worse. Flagging it
  so whoever else is in that file knows.
- `docs/reports/slice-3b-task-c.md` and the code are **not committed**.
