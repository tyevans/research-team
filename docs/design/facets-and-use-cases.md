# The material strip is full, and the check that says so does not run in CI

Written 2026-08-23 against `main` at 5b08f66.

**This document was wrong on its first pass and the correction is the useful
part.** The first draft argued that the project page has sixteen flat facets
with no grouping, and proposed adding a `FACET_GROUPS` constant. Both halves
were wrong, and finding out how they were wrong is what produced the real
finding.

## What the first draft missed

**A grouping already exists.** `regionOf` in `ProjectView.tsx` is total over
`Facet`, maps every facet to `queue` or `material`, and is asserted against
`FACETS` itself rather than against a copy
(`ProjectView.test.tsx`). Adding `FACET_GROUPS` would have been the second
list this repository's conventions warn about throughout.

**The ordering is not arbitrary either.** `MATERIAL_TABS` argues its order
line by line: artifacts beside the workspace because they are "the same shelf
at two ages"; the tree beside the graph because it is "the graph's own
material read a second way"; the timeline last because `TimelineCanvas` is
lazy and a default of `timeline` would pull it on every project page.

The first draft read those comments as evidence of an *undeclared* hierarchy.
They are the opposite: the hierarchy is declared, in the order of the array
and in the reasoning beside each entry.

## The real finding

`MATERIAL_TABS` carries this, and it is the sentence that matters:

> **Eleven tabs is where this strip stops fitting, which is worth knowing
> before the twelfth is added.**

It is measured, not estimated. Two tabs were already collapsed into one
because of it — `area` and `path` share the "Curriculum" tab and the pane
toggles between them internally — after the two-tab arrangement measured
837px of tabs against a 646px floor and produced two clipped controls in the
narrow band.

And the constraint is asserted. `project-tracks.browser.test.tsx` sums every
tab's width, adds the column gaps and the strip's padding, and requires:

```
expect(children).toHaveLength(MATERIAL_TABS.length)
expect(width('material')).toBeGreaterThanOrEqual(needed)
expect(floor).toBeGreaterThanOrEqual(needed)
```

That is a real gate on a real measurement, including the anti-rubber-stamp
half — the length check means a strip that silently dropped a tab cannot pass
by needing less room.

**It does not run in CI.** `npm run verify` chains format, lint, typecheck,
`test:coverage`, build, size and the deleted/tailwind checks. The browser
project is `npm run test:browser`, and `CLAUDE.md` states plainly that it is
"deliberately outside `verify` and outside CI, so nothing forces you to run
it."

So the twelfth tab merges green. Every gate passes, the strip overflows, and
the failure appears first to a person on a narrow window — which is the same
class of defect as the four `CLAUDE.md` records under "the real assertion was
written as a comment", except here the assertion exists and is simply not
reached.

## Why this is not solved by putting the browser suite in CI

That is the obvious answer and it is a bigger decision than this finding
supports. `CLAUDE.md` gives the reasons the suite is outside CI — it is a
minute against a second, it needs a Chromium download, and 923 jsdom tests
would be competing with a handful of browser ones for the same runtime
budget. Reversing that on the strength of one gate is not warranted, and it
is the user's call rather than a document's.

## What is warranted

**A cheap check, in the suite that does run, that fails when the strip grows.**

The full measurement needs a browser. The *count* does not. `MATERIAL_TABS`
is an exported array, and a jsdom or plain unit test asserting its length has
not changed costs nothing and runs in CI today:

```ts
// Eleven is where the strip was measured to stop fitting
// (`project-tracks.browser.test.tsx`). This is not a style rule: a twelfth
// tab overflows MATERIAL's 646px floor, and the assertion that would catch
// that lives in the browser suite, which CI does not run.
expect(MATERIAL_TABS).toHaveLength(11)
```

That is a tripwire rather than a measurement, and it should say so. It cannot
tell a twelfth tab from a relabelled eleventh, and a shorter set of labels
might genuinely fit twelve. What it does is make the twelfth tab a
conversation instead of a merge — the author sees the number, reads why, and
either runs the browser suite to re-measure or collapses two tabs the way
`area`/`path` were collapsed.

## The other thing worth recording

`DEFAULT_MATERIAL` is `'session'`, and the reason it is first is argued
twice: what a reader opening a project is asking, and the bundle cost of
defaulting to a tab that pulls a lazy canvas. Both arguments are sound and
both are about the *first* tab.

Nothing states what the eleventh tab is for. `area`/`path` is last "for the
bundle reason the graph tabs are last", which is an argument for not being
first, not an argument for being eleventh. If a tab has to go when a twelfth
arrives, there is no recorded basis for choosing it — the order encodes
adjacency and laziness, and neither ranks importance.

That is not a defect. It is the question the twelfth tab will ask, and it is
cheaper to notice now than in the pull request that has to answer it.
