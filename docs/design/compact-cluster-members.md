# Compact cluster membership on the course page

The course page ended with a flat list of every entity in the cluster: an
`<h3>` reading "66 entities in this cluster", then 66 rows, each carrying a
name link, the entity type and an optional date. On a real course the list was
longer than the course. This document records what replaced it, what was
rejected, and what is not verified.

## What changed

- `frontend/src/domain/knowledge/course-members.ts` (new). A pure fold,
  `groupMembers` and `countMatching`, beside `entity-tree.ts`.
- `frontend/src/presentation/curriculum/CourseMembers.tsx` (new). The fold as a
  disclosure.
- `frontend/src/presentation/curriculum/CoursePage.tsx`. The 17-line inline
  `<section>` became one line, `<CourseMembers projectId={...}
  members={members} />`.
- Tests: `course-members.test.ts` (9), `CourseMembers.test.tsx` (18).

The API response shape is untouched, and no Python changed.

## The design

**Collapsed by default, with the count on the toggle.** The list is not
reading material. It is the evidence for why the course exists, and a reader
consults it rather than reads it. So the default state is one line that says
how many, and the detail is one click or one Enter away.

*Rejected: show the first N with a "show all".* It answers a question nobody
asked — which N? — and any truncation point is arbitrary in a way a fold is
not. It also keeps a variable amount of vertical space on a page whose own
content should own that space.

**Grouped by entity type.** The type was already printed on all 66 rows, so
grouping *removes* text rather than adding structure on top of it, and the
per-type counts are the shape of the cluster — which is what a reader checking
"is this really one subject" wants first. Each group is its own disclosure with
its own count, matching `EntityTree`.

Groups are open once the outer fold is open. Opening the fold is an explicit
"show me"; answering that with a second screen of closed buttons would be a
worse list than the flat one. `EntityTreePane` reaches the same state by a
different route (`OPEN_ALL_BELOW = 200`, and a cluster is far below it), so
this is the sibling surface's behaviour at this size rather than a new rule.

**A filter above 12 members.** `type="search"` with an `aria-label`, copied
from `EntityTreePane`'s box. Below 12 the whole list is one glance and a search
box is one more control for a keyboard user to tab past. 12 is chosen, not
measured.

Filtering happens *before* grouping, which is `groupByType`'s stated contract
and is held to here for the same reason: filtering after grouping leaves a
heading whose count disagrees with what opening it shows. A `role="status"`
line reports "12 of 66 match" while a filter is active, because the list
shrinking silently is invisible to a screen reader.

**Ordering.** Groups are largest first, ties broken by type name. This is the
one deliberate departure from `groupByType`, which is alphabetical: the entity
tree is an index, where alphabetical is how you look something up, and this is
evidence, where the largest type is the claim. Within a group, members are
ordered by `centrality`, ties broken by name.

**Density.** Members are wrapping inline items rather than one row each. That
is affordable only because grouping moved the type off the row; 66 one-line
rows are a page, 66 wrapped names are a block.

## Reuse

`Disclosure` from `presentation/common/primitives.tsx` at both levels — no new
disclosure pattern was added. `groupMembers` is a new fold rather than a reuse
of `groupByType`, and that is a real duplication of about twenty lines. The
justification: the two sort the same-looking data by different keys to answer
different questions, they operate on different types (`GraphNode` versus
`AreaMember`, the latter carrying `centrality`), and one function with a mode
flag would be an abstraction over a coincidence of shape rather than a shared
rule.

## Accessibility

Real `<button>` disclosures with `aria-expanded` and `aria-controls`, from the
primitive. The count is part of the toggle's accessible name. Focus is visible
through `lay-ring-inward` on the member links — the named class, not the
`focus-visible:outline-offset-*` utility, which CLAUDE.md records as inert
against `tokens.css`'s unlayered global rule.

One accepted regression: the `<h3>` is gone, replaced by a `<section
aria-label="Cluster membership">`. A screen-reader user navigating this page by
heading no longer stops here. Keeping the heading meant wrapping the toggle in
it, which `Disclosure` cannot do — a `<button>` takes phrasing content and
`<h3>` is not phrasing content — so it would have meant a second disclosure
implementation on the same page. If heading navigation matters more than the
duplication, this is the trade to revisit.

## What was tested

Every test was proved red before being trusted green, by breaking the
implementation with `sed`/`python` edits and restoring from a `cp` backup —
never `git checkout <file>`, per CLAUDE.md.

Breaks taken, and what each turned red:

| Break | Red |
| --- | --- |
| `useState(false)` → `useState(true)` (open by default) | 14 of 18 |
| Groups closed by default | 8 of 18 |
| `role="status"` removed | 1 (the announcement test) |
| Filter term never reaches the fold | 4 |
| Group order alphabetical instead of by size | 1 |
| Member order by name instead of centrality | 1 |

The alphabetical break is worth recording: only **one** of the two group-order
tests caught it. The first uses `person`/`place`, where the larger group also
sorts first alphabetically, so it passes under either rule — exactly CLAUDE.md's
"a formula correct on every case a test naturally reaches" shape. The second
test exists solely to separate the two rules and is marked as such in its
docstring.

Also measured: the type group's button is named `person2`, not `person 2`,
without a literal text node between the two spans — accessible-name computation
concatenates text nodes and ignores the flex gap. A space placed *inside* the
count's span does not fix it either (name computation trims each node); that
was tried and failed the same way. `EntityTree` has the same defect on its own
group headings and was left alone, being another surface.

Gates run on the touched files only, per the dispatch: `npx vitest run` on the
three affected test files (41 pass), `npx prettier --check`, `npx eslint`, `npx
tsc --noEmit`. The full suite and `npm run verify` were not run.

## What is NOT verified

- **Anything visual.** No browser test, no screenshot, no measurement. The
  wrapping inline list, the density, the fold's spacing and how the group
  counts sit against the type names are all reasoned, not seen. jsdom lays
  nothing out. If the wrapped list reads badly, nothing here would have caught
  it — a `*.browser.test.tsx` or an eye is what settles it.
- **The `.input` class on the filter box.** It is `EntityTreePane`'s class name
  and is defined in two stylesheets (`composer.css` and `tree.css`); which one
  wins inside a curriculum pane was not checked.
- **Real data.** Everything was exercised against constructed members. The
  reference course
  (`#/p/6e7bd68f-68e6-422f-a11d-3c2e4612de55/course/resolution`) was not
  opened.
- **`centrality` values in practice.** The ordering is now driven by a number
  that nothing in the console previously read. If the projection writes zeros
  or near-uniform values, the intra-group order degrades silently to
  alphabetical (the tie-break) and looks fine. Nothing asserts that real
  centralities vary — the same shape as the "0 shared passages" defect in
  CLAUDE.md.

## Not hooked up

1. **`centrality` was on the wire and read by nothing.** `AreaMember.centrality`
   has been carried by the area projection since it shipped, with a careful
   docstring about not comparing it across areas, and no surface in the console
   rendered or sorted by it. This change is its first consumer. It is still not
   *shown* — only used to order — so a reader cannot tell a central member from
   a peripheral one, and nothing would notice if the projection started writing
   a constant. Worth either surfacing (a weight on the row) or asserting over a
   real ingest.

2. **This surface emits no interaction-log events.** `EntityTreePane` takes
   `useInteractionLog()` and its graph store emits; `CourseMembers` emits
   nothing, so "did anyone ever open the membership fold, and did they filter
   it" is unanswerable — which is precisely the question that would say whether
   collapsed-by-default was the right default. Deliberately not wired here: the
   log's context defaults to a silent emitter, and CLAUDE.md is explicit that a
   test asserting "no events were sent" passes whether the feature works or was
   never wired at all. Wiring it needs a test that a recorded event reached the
   sink, which is more than this task's scope.

3. **`AreaDetail.tsx` still renders the old flat list.** It has the identical
   markup this replaced — name link, type, temporal, one row each — over the
   same `AreaMember[]`. `CourseMembers` is a drop-in for it (it takes
   `projectId` and `members` and nothing else). Left alone because the dispatch
   named the course page, and because an area's detail pane may want a
   different default openness; but the duplication is now the kind that drifts.

4. **`EntityTree`'s group headings are named "person2".** The same
   accessible-name defect measured here. One space fixes it. Out of scope, and
   somebody should take it.
