# Task A — the 821–1180 band, measured

Branch `increment-d-scoping`, worktree `gate-review-tooltip`, 2026-08-14.
Scope: plan §3 task A of `docs/superpowers/plans/2026-08-14-the-page-nobody-measured.md`.

Files changed:

- `frontend/src/styles/responsive.css` — new `[data-split='project']` block
- `frontend/src/presentation/project/project-responsive.browser.test.tsx` — new

`ProjectView.browser.test.tsx` was not touched. Its docstring's claim that the
whole file sits "above `--bp-wide`, the only band in which a `Split` writes a
template at all" is still true.

## 1. The spike: `page.viewport()` works, and I am on it

**Mechanism 1, not the fallback.** No second vitest project was added.

A throwaway probe rendering `useWide('wide')` and `useWide('narrow')` was driven
through four viewports and asserted at each. It passed on the first run:

| viewport | `wide` / `narrow` |
| --- | --- |
| 1440×900 (the run's default) | `true` / `true` |
| 1000×900 | `false` / `true` |
| 700×900 | `false` / `false` |
| 1440×900 (restored) | `true` / `true` |

So `page.viewport()` re-triggers `matchMedia`, the `change` event reaches
`useWide`'s `useSyncExternalStore` subscription (`use-wide.ts:33-51`), and React
re-renders. The probe file was deleted after the spike; the fact is recorded in
the new test file's docstring, which is where anyone writing the twentieth
browser test will look.

### The hazard I got wrong once, which is worth more than the spike

`page.viewport()` resolving is not React having committed, and **`window.innerWidth`
is not a proxy for it either**. My first `widen` helper polled `innerWidth`, and
claim 1 read **three** columns at 1000px:

```
AssertionError: expected [ ... ] to have a length of 2 but got 3
```

`innerWidth` already said 1000 while `Split` still had `wide === true` and its
three-track inline template still on the element. `innerWidth` is downstream of
the resize and upstream of the render, which is exactly the wrong place.

The poll has to be on something React writes. It is now the inline style —
`splitTemplate` returns `undefined` below `--bp-wide` and React omits the
property, which is the same handoff the stylesheet depends on:

```ts
await expect.poll(() => split().style.gridTemplateColumns === '').toBe(width < 1181)
```

**Viewport restoration:** an `afterEach` puts it back to 1440×900, commented with
the reason (nothing else in the suite does — the viewport is global to the run,
set once at `vite.config.ts:288`). Proved effective rather than assumed: running
this file together with `ProjectView.browser.test.tsx` interleaves them, and all
nine pass. The whole browser suite is **21 files / 63 tests, all passing**.

## 2. What the band actually did — §1 confirmed, and one part is worse

Measured in Chromium on the real `ProjectView` **before any CSS change**.
`grid-template-columns` / `grid-template-rows` as the browser computed them on
`.lay-split[data-split='project']`:

| viewport | display | columns | rows |
| --- | --- | --- | --- |
| 1440×900 | grid | `411.42px 617.14px 411.42px` | `900px` |
| 1000×900 | grid | **`1000px`** | `375.98px 375.98px 148.03px` |
| 900×900 | grid | **`900px`** | `375.98px 375.98px 148.03px` |
| 800×900 | flex | none | none (the deliberate stack) |

**Plan §1 is correct.** In the band the three regions resolve to a single grid
column. Each still draws itself as a column (`.lay-pane` keeps its
`border-right`, and `Split`'s `stacked` is `false` here).

**One thing is worse than §1 says.** Because the split is still `display: grid`
in this band and not `flex`, `layout.css`'s stacked-mode
`.lay-pane-body { max-height: 60vh }` does **not** apply, and the surface owns
the viewport above 821px. So the three stacked regions were crushed into 900px
with nothing scrolling: MATERIAL — the documents and the graph canvas — got
**148.03px**, and there was no scroller to recover it from. The plan describes a
stack; the measurement is a stack that is also clipped.

**The rail, checked specifically as asked.** `Pane.tsx:126` keys the rail form on
`stacked`, not `!wide`, so in this band a collapsed pane rotates its title and
asks for 34px. Folding QUEUE at 1000×900 measured:

```
COLLAPSED cols=1000px queue={"width":1000,"height":182.359375, ...}
```

A full-width 1000×182px block with a vertical title. No template granted the
rail, exactly as the plan predicted. This is the half a reader meets by
**clicking**, not by resizing, which makes it the more likely one to have been
seen and not reported.

## 3. The arrangement chosen, and what I rejected

**Chosen: two columns — QUEUE | HOLDER — with MATERIAL wrapped onto its own
full-width row beneath them, capped at 46vh.**

This mirrors the session view's own declaration rather than inventing a second
shape for the same band, and the 46vh cap is that rule's number adopted, not
independently derived. HOLDER carries the 1.4fr, per the lead's prior that it is
the region a reader watches.

Rejected:

- **Three columns at their minima.** `PROJECT_TRACKS`'s floors sum to 880px.
  That does not fit at 821 at all, and at 900 it gives every region exactly its
  floor — and a floor is where a column *stops being a list*, not a target.
- **Wrapping HOLDER instead of MATERIAL.** HOLDER is a scrub bar, two scrollers
  and a pinned composer. The measurement above shows what ~376–410px does to
  it, and 46vh of 900 is 414. The graph canvas takes a wide short box far better
  than a transcript does.
- **The lead's prior — a flank collapsed to its rail.** I am overriding this,
  and the reason is mechanical rather than aesthetic: **it cannot be done from
  CSS.** The rail form comes from `.is-collapsed`, which `Split` derives from
  the collapsed set — React state. A 34px grid track around a pane that is *not*
  collapsed **clips a full pane**; it does not rail it. Doing it properly means
  seeding the collapsed set in `use-project-panes.ts`, which is task B's file.
  The collapse *path* is still handled: `:has([data-pane='queue'].is-collapsed)`
  and the HOLDER equivalent shrink a track to `var(--rail-w)` when a reader
  folds one, which is what makes the rail defect above go away.

Carried over from the session view deliberately, wart included: a collapsed
MATERIAL on its full-width row still gets a vertical title, because `stacked` is
false. `responsive.css` drops its `max-height` so the row closes up around it.
Fixing the rotation means changing what `Pane` does with `stacked` — a primitive
change, not this slice's.

**The signal, noted and not built** (plan §3 says to): two views now declare
their own middle arrangement in `responsive.css`. `layout.css:124-141` allows for
exactly that. A **third** would be the case for teaching `Split` how many columns
to fall back to and which pane may wrap.

## 4. Red proofs

With the new `@media (width >= 821px) and (width < 1181px)` /
`[data-split='project']` block removed from `responsive.css` and nothing else
changed, all four tests fail:

```
× gives the project split two columns and a wrapped MATERIAL between 821 and 1180
  → expected [ '1000px' ] to have a length of 2 but got 1
× keeps every region above its floor in the band
  → expected 375.984375 to be greater than or equal to 486
× gives a folded flank its rail width in the band
  → expected 1000 to be close to 34, received difference is 966, but expected 0.5
× hands the layout back to Split at 1181
  → expected [ '1180px' ] to have a length of 2 but got 1
```

Restored, all four pass.

**Claim 4 going red was not my prediction and the docstring now says so.** I
wrote it expecting to pass either way, on the reasoning that a boundary guard's
subject is the edit that would break it. Wrong: 1180 is *inside* the band, and
the band had no rule. Only the 1181 half is the boundary guard; both are kept.

**One assertion was wrong in the other direction and is recorded in the test.**
Claim 2 first asserted `material.height > 300` — "MATERIAL is no longer
squeezed" — and it stayed red **after** the fix, at 149.03px. The wrapped row is
`minmax(0, auto)`: 46vh is a cap, not a height, and this fixture's MATERIAL has
no documents and no graph. That assertion was measuring the fixture, which is the
trap `CLAUDE.md` and two claims in `ProjectView.browser.test.tsx` already record.
It was replaced with the fixture-independent guarantee — the top row cannot be
given less than 54vh however tall MATERIAL grows — which is red at 375.98 before
and green at 751 after.

## 5. Verification run

Serially, one vitest process at a time.

- `npx vitest run --project browser src/presentation/project/project-responsive.browser.test.tsx` — 4 passed
- the two project browser files together — 9 passed (this is the viewport-leak check)
- `npm run test:browser` — 21 files, 63 tests, passed
- `npx vitest run scripts/theme.test.ts src/presentation/session/use-session-panes.test.tsx src/presentation/session/SessionView.test.tsx src/presentation/project/ProjectView.test.tsx` — 27 passed (the jsdom siblings that read `responsive.css` or `BREAKPOINTS`)
- `npx tsc --noEmit` — clean
- `npx eslint` on the new file — clean
- `npx prettier --check` on both files — clean

Not run, per the brief: `npm run verify`, the full jsdom suite, and the Python
gates. The lead runs those.

## 6. Left undone, deliberately

- **`Split` learning the middle arrangement.** Out of scope per plan §3; the
  second declaration is the signal and it is written down in `responsive.css`.
- **The collapsed wrapped pane's rotated title**, on both this view and the
  session view. It is a `Pane`/`stacked` change.
- **Any change to the session view**, including the `:has()` duplication now
  visible between the two blocks. Factoring them together would touch the
  session rule.
- **The 46vh cap is inherited, not measured.** This fixture's MATERIAL is empty,
  so nothing here exercises the cap; the assertion that guards it is vacuous
  today and says so in its comment. It becomes a real measurement in the slice
  that gives MATERIAL its documents and its graph — which is the same deferral
  task B is honouring for the widths.
- **Nothing below 821 or above 1181 was re-measured** beyond the boundary test;
  those bands were already covered and were not the subject.

---

# Fix round 1

2026-08-14, same branch and worktree. Both findings accepted; both fixed. No
scope beyond them.

## Finding 1 — both flanks collapsed at once

**Confirmed, and it was mine to have caught.** Claim 3 only ever folded QUEUE.
`toggleCollapsed` refuses only when *every* pane would close, so with three
tracks the second fold is reachable in two clicks, and my two single-collapse
rules have identical specificity and each write the whole
`grid-template-columns` — so the later one (HOLDER's) simply won and QUEUE kept
a full track under a rotated title. The exact defect shape the block was written
to remove, one click further in.

Added `responsive.css`, after the two single rules so it wins on source order
rather than on specificity — which is what the existing pair already relies on:

```css
.lay-split[data-split='project']:has([data-pane='queue'].is-collapsed):has(
    [data-pane='holder'].is-collapsed
  ) {
  grid-template-columns: var(--rail-w) var(--rail-w);
}
```

New test, claim 5, `rails both flanks when both are folded`. It asserts the two
rectangles rather than the template string, because the template is the thing
that was wrong — reading `grid-template-columns` back would have agreed with
whichever rule won. It also re-reads QUEUE's width *after* the second fold
rather than trusting the poll from the first, since the whole defect is the
second collapse silently undoing the first pane's track.

**Proved red** with only the combined rule removed and both single rules left in
place, at 1000×900:

```
× rails both flanks when both are folded
  → expected 966 to be close to 34, received difference is 932, but expected 0.5
```

QUEUE at 966px — a rail's rotated title stretched across two thirds of the
viewport. The other four tests stayed green under that removal, which is what
makes claim 5 a distinct claim rather than a restatement.

**The session block was not touched.** Its identical latent bug for
`timeline` + `workspace` at `responsive.css:40-45` is pre-existing and yours to
file. My CSS comment now says so explicitly, so the duplication between the two
blocks carries a recorded *difference* and not just a repeated shape: whoever
merges them owes the session view this rule.

## Finding 2 — the stale floor sum

Correct, and the number was wrong in the direction that weakens my own argument
by being cited at all. `PROJECT_TRACKS` is now 344 / 342 / 352 = **1038**, not
880. The comment now gives the new sum, says the floors were *raised by
measurement in this same slice*, and cites what the measurement found — MATERIAL
getting a 337px share at 1181 for a 351px tab strip, leaving the Graph tab
painted past the pane edge and unclickable. So the band comment now rests on a
measured floor rather than a chosen one, and the argument against three columns
here is stronger than the version it replaces: 1038 clears 1180 only by leaving
142px to share between three regions.

**One thing I changed that was not asked for, stated because it is a judgement
call.** I added a short comment above the band's own template explaining why its
`minmax(280px, …)` / `minmax(320px, …)` were *not* raised to B's measured
344/342: the two floors sum to 686, so at 821 and above the fr shares are
already wider than either pair and the minima never bind. Raising them would
read as a decision and decide nothing. No declaration changed — comment only.

## Verification

Serially, one vitest process.

- `npx vitest run --project browser src/presentation/project/project-responsive.browser.test.tsx` — **5 passed**
- red proof above, then restored
- `npm run test:browser` — **22 files / 69 tests, passed** (68 before claim 5)
- `npx tsc --noEmit`, `npx eslint`, `npx prettier --check` — all clean

Not run, per the brief: `npm run verify`, the jsdom suite, the Python gates.

## Not done, as instructed

Seeding the collapsed set; anything in `use-project-panes.ts` or task B's files;
making the 46vh assertion non-vacuous; the session block's own both-flanks rule.

---

# Fix round 2

2026-08-14. One finding, against the reasoning I added in round 1. Accepted and
fixed. **Your arithmetic verified by measurement first**, as asked.

## The arithmetic, settled by a test rather than derived

I wrote the bottom-edge test **before** touching the CSS, so the first run of it
is the measurement. At 821×900, against round 1's `minmax(280px, 1fr)`:

```
× clears QUEUE’s measured floor at the bottom of the band
  → expected 342.078125 to be greater than or equal to 344
```

**You were right, to within a rounding digit.** You predicted 342.1 from
821 × (1/2.4); the browser gives **342.078125**. QUEUE was two pixels under a
floor that task B *measured* — the width below which the 317px non-wrapping
seeding form paints outside a box that clips it with no scroller and no
ellipsis. The same defect B fixed above 1181, reached from underneath, across
roughly the bottom 5px of the band.

My round-1 comment was wrong in the way that mattered: "the minima never bind"
is exactly the sentence that would have stopped anyone from looking.

## The fix

`responsive.css`, QUEUE's floor raised to `PROJECT_TRACKS`'s measured 344 in
both rules that write a QUEUE track — the base template and the
holder-collapsed one:

```css
grid-template-columns: minmax(344px, 1fr) minmax(320px, 1.4fr);
/* and */
grid-template-columns: minmax(344px, 1fr) var(--rail-w);
```

Measured after, at 821×900: **`344px | 476.984px`**, against 342.078 / 478.906
before. The floor binds and the row still fills exactly 821.

**HOLDER's stays at 320, and the comment now says why rather than leaving it
implicit** — your check confirmed: its floor is 342 and its share at 821 is
~479, and the band only widens from there, so raising it would change no pixel
at any width. The rewritten comment states plainly that one of the two floors
binds and the other cannot, which is the honest version of what round 1 claimed.

The bottom-edge test asserts **both** floors, so the fact that HOLDER's is
unreachable is pinned rather than assumed: a future reweighting that brings it
into reach fails here instead of silently clipping.

## New test — claim 6, `clears QUEUE’s measured floor at the bottom of the band`

821 is the narrowest viewport at which this arrangement applies at all, so it is
where the columns are thinnest and the only place a floor can bind. Nothing
covered it: claim 4 asserts 1181 and 1180, both at the top of the band. Red proof
is the run quoted above.

It also asserts the two columns still sum to 821 — raising a floor moves the
boundary between them rather than adding a gap or overflowing.

## Verification

- `npx vitest run --project browser …project-responsive.browser.test.tsx` — **6 passed**
- `npm run test:browser` — **22 files / 70 tests, passed** (69 before claim 6)
- `npx tsc --noEmit`, `npx eslint`, `npx prettier --check` — clean

Untouched, as instructed: task B's files, the session block, the round-1
both-flanks rule and its comment.
