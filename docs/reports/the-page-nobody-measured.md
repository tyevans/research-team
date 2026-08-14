# The page nobody measured

The slice against `BACKLOG.md` B57 and `increment-c-plan.md` §6 question 3,
2026-08-14, branch `increment-d-scoping` off `origin/main` 2081660.

## The headline: two shipped defects, not two unmeasured numbers

B57 said the project page's three region widths were "chosen, not measured".
That was true and it was the smaller half. **Both bands the page renders in
were broken, and the measurement is what found them.**

**Above 1181px.** At 1181 — the narrowest viewport where a `Split` writes a
template at all — the fr shares are 337 / 506 / 337. MATERIAL's 337px had to
hold a five-tab strip that is **351px wide and neither wraps nor scrolls**, so
the Graph tab was painted past the pane's right edge: present, and unclickable.
QUEUE's seeding form went the same way 14px later. The floors were the session
view's, adopted unmeasured, and they were 64 and 72 pixels too small.

**Between 821 and 1180px there was no layout at all.** `Split` deliberately
writes no inline template below `--bp-wide` — `splitTemplate`'s `undefined` is
documented as "the load-bearing return", handing the band to media queries so a
stylesheet can reflow the panes. The session view took that handoff in
`responsive.css`. **The project view never did**, and the only rule in the band
is scoped to `[data-split='session']`. So the three regions resolved to a single
grid column, each still drawing itself as a column, with **nothing scrolling** —
`display: grid` there means `layout.css`'s stacked-mode `max-height: 60vh` never
applies and the surface owns the viewport. Measured at 1000×900: rows of
`375.98 / 375.98 / 148.03`. MATERIAL — the documents and the graph canvas —
got 148px with no way to reach the rest.

Folding a pane was worse, and is the half a reader meets by **clicking** rather
than by resizing: `Pane.tsx:126` keys the rail form on `stacked` rather than
`!wide`, so a collapsed pane in this band asks for a 34px rail with a rotated
title and no template grants it one. The folded QUEUE measured **1000×182px** —
a full-width horizontal block with a vertical title.

Both bands were bounded by bands that work, which is why four slices missed
them: below 821 the stack is deliberate, and at 1440 nothing is wrong. **1440
was the only width anyone had ever looked at, and it was never the width that
was wrong.**

## What shipped

| | before | after |
| --- | --- | --- |
| `PROJECT_TRACKS` floors | 280 / 320 / 280, unmeasured | **344 / 342 / 352**, measured |
| 821–1180px | one column, nothing scrolling | two columns, MATERIAL wrapped, 46vh cap |
| folding in that band | full-width block, vertical title | a 34px rail |
| both flanks folded | — | both rails |
| `TruncatedText`'s ring | three inert utilities | the console's global ring |

**At 1440 the page is pixel-identical**: 411 / 617 / 411 before and after.
`minmax(min, 1fr)` takes the floor only where the fr share falls under it, so
raising three minima changes the bottom of the band and nothing else.
Reweighting was rejected — it buys the same clearance by reshaping every width
above 1181 to fix its narrowest 60px.

## The enabling fact

**This slice is the first in the repository to resize the viewport in a test.**
The browser suite's 1440×900 is set once in `vite.config.ts` and all nineteen
existing files treat it as fixed and say so in prose. `page.viewport()` was
spiked before anything was built on it, because the whole shape of the work
depended on it: proved that it re-triggers `matchMedia`, that `useWide`'s
`useSyncExternalStore` subscription observes the change, and that React
re-renders. No second vitest project was needed.

Two costs, both handled rather than discovered:

- **The viewport is global to the run** and nothing else restores it, so an
  `afterEach` puts it back — a resize that leaked would surface in file order,
  which reads as flakiness.
- **Awaiting the resize is not awaiting the re-render.** The first helper polled
  `window.innerWidth` and read three columns at 1000px, because `innerWidth` is
  downstream of the resize and upstream of the render. The poll has to be on
  something React writes.

## Three findings the work produced that the plan did not ask for

1. **A flank cannot be railed from CSS.** My brief proposed collapsing one flank
   in the middle band. Task A overrode it for a mechanical reason: `.is-collapsed`
   comes from React state, so a 34px track around a pane that is *not* collapsed
   **clips a full pane** rather than railing it. Doing it properly means seeding
   the collapsed set. Rejected with a reason, not adopted because I said so.
2. **Both flanks collapsed at once was unhandled**, found by me and confirmed
   independently by review. `toggleCollapsed` refuses only when *every* pane
   would close, so folding two of three is two clicks away; the two `:has()`
   rules have identical specificity and each writes the whole
   `grid-template-columns`, so the later simply won and the earlier pane kept a
   full-width track while still drawing as a rail. Fixed here. **The session
   block has the identical bug and was deliberately left with it** — pre-existing,
   and now filed, so the duplication between the two blocks carries a difference
   rather than just a repeated shape.
3. **The bottom edge of the band was two pixels short.** After the fix, QUEUE's
   share at 821 is `821 × (1/2.4)` = 342.08 — under the 344 floor task B had just
   measured, so the defect fixed above 1181 was still reachable from underneath
   across the bottom ~5px. Predicted arithmetically, then **settled by writing
   the test first**: `expected 342.078125 to be greater than or equal to 344`.
   The round-1 comment had said "the minima never bind", which is exactly the
   sentence that stops anyone looking.

## B56, settled

The three `focus-visible:` utilities on `TruncatedText` are **deleted**, not
repaired. Measured with them present and absent: identical — `2px solid` at
**1px** offset, where the utility asks for 2px, because `tokens.css`'s
`:focus-visible` is unlayered and beats `@layer utilities` regardless of
specificity. Making them work would buy one pixel more offset on every truncated
label in the console, a visual change to a shared primitive made blind, to
honour a declaration nobody wrote for a reason. B56 asked for the call to be
made by someone looking at it; it was.

The new test pins `outlineOffset: '1px'` — the global's value — so a future
attempt to make the utility work goes red and forces the decision to be
conscious.

## What is measured, and what is still only reasoned

Measured: the three floors, both bands' arrangements, the rail widths, the
boundary at 1181, and the focus ring.

**Still reasoned:** the weights. `1 / 1.5 / 1` claims HOLDER is what a reader
watches and the flanks are interchangeable, and nothing here measures that — the
floors say where a region *breaks*, not where it is *good*, and a test cannot
tell the difference. The docstring now says which half is which, which is a
smaller gap than the one it replaces but is not no gap.

Also inherited rather than derived: the 46vh cap in the new band rule is the
session view's number. The fixture that could exercise it exists — task B's, with
six documents and a mounted graph — but it is in task B's file and the assertion
that guards the cap is in task A's, so it is vacuous today and says so.

## Verification

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 230 files already formatted |
| `uv run pytest` | **2391 passed**, 9 deselected, 218s |
| `cd frontend && npm run verify` | full chain — build, size, `deleted`, `check:tailwind` |
| `npm run test:browser` | **22 files / 70 tests** |

The browser suite is not a gate and is the reason this slice exists; it was run
on the **combined** tree by me, not only by each task against its own.

`app` is **72.7 kB of 80 kB**, up 0.1 from the CSS rule. Total 285.7 of 512.

Every test was proved red first. Two of the red proofs were more interesting
than the tests: task A's boundary claim went red where its author predicted it
would pass, and task B's first floor assertion measured the fixture rather than
the arrangement and stayed red *after* the fix, which is how it was found.

## Left undone, deliberately

- **Nothing below 821px was measured.** B57 asked for all three responsive
  layouts and this slice did two. B57 is closed with that said rather than
  implied.
- **The session block's both-flanks bug**, filed rather than fixed.
- **Teaching `Split` the middle arrangement** instead of each view declaring its
  own. Two views now declare it, which `layout.css:124-141` allows for; a third
  would be the case for the primitive change.
- **The rotated title on a collapsed wrapped pane**, which both views carry.
  It is a `Pane`/`stacked` change.
- **Seeding the collapsed set** so a flank starts railed in the middle band.
  Available and cheap; not in scope.
- **The weights**, which need a definition of "reads better wide" sharp enough
  to assert — a research question rather than a test.
