# Entities as a tree

A seventh MATERIAL tab on the project page: the same entities the Graph tab
draws, listed under collapsible type headings instead of wired into a canvas.

```
[-] concept
    - Backpropagation
    - Gradient descent
[+] study
[-] person
    - Geoffrey Hinton
```

## Why

The graph answers "what is this connected to". It answers "what is in this
project" badly: a force simulation of nine hundred nodes is a hairball, and the
only way to enumerate what has been extracted is to read dots. The timeline is
already precedent for the shape of this change — same material, a different
reading of it, its own facet and its own tab. This is the third such reading:
same material, ordered by kind.

It is also the only reading of the graph that costs no canvas. A reader who
wants to know what is in a project should not download `react-force-graph-2d`
to find out.

## Scope

Frontend only. No backend route, no read model, no event, no projection. The
data is what `GET /api/projects/{id}/graph` already returns and what
`graph-store.loadAll()` already fetches.

Deliberately out of scope, and named so nobody adds them mid-slice:

- Nesting by relationship (a real tree of `contains` edges). The grouping here
  is by `entityType`, which is a partition — every entity is in exactly one
  group, no cycles, no orphans. A relationship tree has neither property, and
  deciding what to do about an entity reachable two ways is a design question
  this feature does not need to answer to be useful.
- Virtualization. See "Size and the cap" below.
- Multi-select, drag, rename, delete. The tree selects; it does not edit.

## Architecture

Four pieces, each testable alone.

### 1. `domain/knowledge/entity-tree.ts` — the fold

```ts
export interface EntityGroup {
  readonly entityType: string
  readonly entities: readonly GraphNode[]
}

export const groupByType = (
  nodes: readonly GraphNode[],
  filter?: string,
): readonly EntityGroup[]
```

Pure, no React, no store — the same shape and the same reason as `graph.ts`
next to it. Sorting is part of the contract and is asserted: groups by type
name, entities by `name`, both with `localeCompare` so a corpus with accents
orders the way a reader expects rather than by code point. An empty group
cannot exist, because a group is only created by an entity landing in it.

`filter` is a case-insensitive substring over `name`, applied *before*
grouping, so filtering to nothing leaves no group rather than a screen of empty
headings.

Ties chosen deliberately: entities with equal names keep input order (sort is
stable in every engine this ships to), which means the server's ordering shows
through rather than being scrambled by the client.

### 2. `presentation/research/EntityTree.tsx` — the drawing

Pure-presentational. Takes `groups`, the open set, the selected id, and three
callbacks. Renders:

- one `<button aria-expanded>` per group, carrying the type's colour swatch
  (`colorForType`, the same function the legend and canvas use — a reader who
  has learnt the graph's colours does not learn a second scheme) and the
  group's count;
- a nested `<ul>` of entity rows when open, each a full-width bare button in
  the row vocabulary `GraphDetail`'s `ROW` establishes: `border-0` first, a
  transparent 2px left gutter that lights up on hover and focus, and
  `lay-ring-inward`.

**Not `role="tree"`.** ARIA's tree pattern obliges arrow-key navigation, typeahead
and a roving tabindex; a `role="tree"` without them is a promise to a screen
reader that the keyboard does not keep, which is worse than the nested-list
semantics a disclosure gives for free. This is two levels of grouped list with
disclosure buttons, and it says so. If someone later wants the full pattern,
that is a Radix accordion and its own slice.

**The fold is `primitives.tsx`'s `Disclosure`, not a new one.** It already
does exactly this — a `<button aria-expanded aria-controls>` over a region,
chosen over `<details>` precisely so the open state survives a re-render driven
from elsewhere, which is the property this pane needs when a `graph` frame
lands mid-read. Writing a second one would be a second caret to keep in step
with the first.

**No new dependency.** Pulling `@radix-ui/react-accordion` in would put a
package in the `ui` bucket to replace a primitive this repository already
ships.

### 3. `presentation/research/EntityTreePane.tsx` — the subscription

The peer of `GraphPane` and `TimelinePane`, and structurally a copy of the
latter: build a `createGraphStore` keyed to the project, `loadAll()` on mount,
`useFrameRefresh` on `graph` frames for this project, hold the filter term, and
hand `GraphDetail` the selection.

Selection is the route's, not the pane's — `entity: string | null` in,
`onEntity` out — for the reason `GraphPane` documents: two copies of one fact
is two places for the address bar and the drawing to disagree.

`GraphDetail` is reused with `onRemove` omitted and `showInGraphHref` supplied,
which is exactly the arrangement `TimelinePane` uses and exactly what those two
optional props were added for. There is no drawing here to prune, so offering
"Remove" would be a button that either does nothing or silently changes a
different tab.

Open/closed state lives here, above the drawing, so it survives a re-render
from a `graph` frame — a tree that collapsed itself every time extraction
landed would be unusable during the one activity that makes it change.

**Default openness is a rule, not a preference:** every group opens if the
graph has ≤ 200 entities, and every group is closed above that. The point of
the tab is enumeration, and a screen of collapsed headings enumerates nothing;
but 900 rows painted at once is the hairball in a different font. 200 is chosen,
not measured, and the comment will say so. It is recomputed only when the entity
count crosses the threshold, never on every load, or a reader's collapses would
be undone by a frame.

### 4. Wiring

- `routes.ts`: `'tree'` joins `FACETS`. It is a `PlainFacet`, so `Selection`
  and `projectHref` need no change — the grammar is uniform by construction and
  `routes.test.ts` already asserts that over `FACETS` itself — which means its
  `cases` table must gain a `tree` row in the same commit, by design: that
  assertion exists so a new facet cannot arrive untested.
- `ProjectView.tsx`: `'tree'` joins `MaterialFacet`, and `{ id: 'tree', label:
  'Tree' }` joins `MATERIAL_TABS` **directly after `entity`** — it is a second
  reading of the graph's material, so it sits with the graph, and Timeline stays
  last. `regionOf` is total over `Facet` and will fail to compile until `tree`
  is mapped to `material`, which is the intended behaviour of that totality.
- The `TabPanel` mirrors `entity`'s: `flex min-h-0 flex-1 flex-col`, no
  `overflow-auto` — the pane owns its own scroller.

## The tab strip floor, which this change breaks

`PROJECT_TRACKS`' MATERIAL floor is 422px, and the file records that it is set
by the tab strip, that the strip neither wraps nor scrolls, and that the number
had to move the last time a tab was added. A seventh tab makes it move again.

`project-tracks.browser.test.tsx` will go red, and that is the gate working.
The fix is to re-measure in Chromium the way that file documents — narrow until
the strip paints past the pane's edge, take the first clean width, add the
pixel or two of slack the existing rows carry — and write the new number with a
row in the table and a note saying which tab moved it. **Not** to relax the
assertion.

This is the single most likely thing to be got wrong by reverting to a
plausible number, so it is called out here rather than left to be discovered.

## Size and the cap

The bundle budget will move and the owner has said that is acceptable. Expect
`app` (currently 80 kB) to grow by roughly a kilobyte; `total` has 276 kB of
slack and will not bite. Raise whichever bucket trips, record the measurement
in `check-size.mjs` in the style of the notes already there, and do not shave
the feature to fit — the standing instruction is that exploration outranks
bundle size at this stage.

Nothing here is lazy-loaded. `GraphCanvas` is lazy because it is 60 kB of
force-graph; this is a list, and a `React.lazy` boundary around it would buy a
round trip's latency to save nothing measurable.

**The server's cap shows through, and the pane must say so.** `loadAll` sets
`partial` when the graph exceeded `MAX_GRAPH_NODES`, and a truncated tree looks
exactly like a complete one — the same defect the canvas has a notice for. The
pane carries the same notice, in the same words, for the same reason. A tree
that silently lists 500 of 900 entities is worse than the canvas doing it,
because a list reads as an inventory.

Virtualization is not part of this. The cap bounds the row count, `VirtualList`
exists for the day it is needed, and adding it now would mean measuring a
scroller before there is a reason to.

## Errors and emptiness

Three states, and they must not collapse into one — this is the mistake
`GraphPane`'s empty state was written to correct.

| condition | what it says |
| --- | --- |
| fetch failed | "The entities could not be read" — never "empty" |
| fetched, nothing extracted | "Nothing has been extracted into this project yet" |
| filtered to nothing | "Nothing matched" — the filter is the cause, not the corpus |

## Testing

`*.test.tsx` (jsdom) carries everything jsdom can judge, which here is nearly
everything: the fold's sorting and filtering, disclosure toggling `aria-expanded`
and the group's rows appearing and disappearing, selection reaching `onEntity`,
the three empty states, the cap notice, and the default-open threshold on both
sides of 200.

One browser test, and only one, because there is exactly one claim jsdom cannot
make: the entity rows use `lay-ring-inward`, and whether a focus ring is drawn
inside the row's box is a computed style. `graph-dressing.browser.test.tsx` is
the precedent and the place — extend it rather than adding a file, unless the
tree's rows want a fixture that file cannot host.

Nothing in the fold or the pane needs a browser. Nothing in the tree needs a
fake repository beyond what `GraphPane.test.tsx` already sets up.

**A test that would pass with the pane removed is not a test of the pane.** The
assertion is that an entity's name is on screen under its type's heading — not
that the panel rendered without throwing.

## Verification

All four gates, per `CLAUDE.md`: `uv run ruff check .`, `uv run ruff format
--check .`, `uv run pytest`, and `cd frontend && npm run verify`. The Python
gates run even though no Python changes — they run over the whole repository
and are the ones that fail in CI after a frontend-only change is called done.

Plus `npm run test:browser`, because the tab strip's floor is a measurement and
`project-tracks.browser.test.tsx` is where it lives.
