# Increment C, slice 3b — the graph, the topic list, and the death of `research.css`

Slice 3a took MATERIAL's three static shelves and said what it left behind. This
is the rest: the graph facet, the topic-list cluster, the seed form that came
along for the ride, and the one thing three slices in a row have failed to do —
delete a stylesheet.

Read against the code at `bd4b16f`. Every `file:line` below was opened.

## 0. The headline, and why it differs from the plan

`increment-c-plan.md` §2.3 predicted `research.css` dies "effectively whole" and
slice 3a proved it could not, because what remained was QUEUE's. **This slice
owns QUEUE's half too, so the prediction comes true — but only because the
inventory is now complete rather than because 3a was wrong.** All 734 lines
belong to exactly three families:

| Lines | Family | Owner |
| --- | --- | --- |
| `:32–235` | topics, dispatch chip, topic documents, dispatch bar | `TopicQueue`, `TopicDocuments` |
| `:236–316` | status dialog, sub-questions | `TopicStatusDialog`, `SubQuestions` |
| `:334–521`, `:559–734` | graph, graph detail, graph legend | `GraphBrowser`, `GraphDetail`, `GraphLegend` |
| `:522–558` | seeding | `SeedForm`, mounted by `QueueHeader.tsx:120` |

The seed form is the surprise. It is neither the graph nor the topic list, it is
five class names, and it is the difference between deleting a file and leaving a
40-line orphan. **It is in scope for that reason alone**, which is a worse
reason than a design one and is stated plainly rather than dressed up.

So: `check-deleted.mjs`'s `STYLESHEETS` goes from 22 to 21, and it is the first
entry to leave since the array was frozen.

## 1. Scope

**In.** The five topic components, the four graph components, `SeedForm`,
threading the `topic` route id, demodalising `TopicStatusDialog` per §3.3, the
two unpadded-scroller focus rings §5.2 names, the deletion of `research.css`,
and the `check-deleted.mjs` bookkeeping that a deletion requires.

**Out.** `course.css` — none of its five families is graph, topic or seed
(`rail`, `workers`, `extraction`, `autonomy`, `allow-all`), so this slice cannot
kill it and does not pretend to. Slice 4 (the picker). `TopicRow`/`TopicDetail`
under `entity/topic/`, which are dressed by `entity.css` and are already on the
contract.

## 2. What actually changes, per task

Tasks A, C and D are disjoint in the files they write and can run together.
None of them touches `research.css`: they leave their class names behind as dead
rules, and task E deletes the whole file in one move. That is deliberate — three
agents editing one stylesheet is a merge, and a half-deleted stylesheet is a
state where no gate can tell whether the remainder is live.

### Task A — the topic-list cluster onto utilities

`TopicQueue.tsx` (280), `TopicList.tsx` (46), `SubQuestions.tsx` (156),
`TopicDocuments.tsx` (174). ~30 class names, of which **four already have no
rule and have been silently undressed** — `topic-filters` (`TopicQueue.tsx:152`),
`topic-dispatch-button` (`:254`), `topic-dispatch-queued` (`DispatchChip`),
`sub-question-resolve` (`SubQuestions.tsx:141`). That is the same defect as the
five undressed chips 3a found in `Findings`, in a second file, and the rewrite
either dresses them deliberately or records that they should stay bare.

`.topic-list` (`research.css:203–214`, `padding: 0`) is one of the two live
focus-ring exposures §5.2 names: full-width rows in an unpadded scroller, ring
drawn outward at `outline-offset: 1px`, clipped entirely. **It gets
`outline-offset: -2px` at the point it is rewritten**, with a browser test that
measures it, because that is the only place the fix is free.

### Task B — the `topic` facet becomes real (depends on A)

`#/p/<id>/topic/<tid>` parses today (`routes.ts:180`), routes to QUEUE
(`ProjectView.tsx:69`), and then **nothing reads the id** — `TopicList` is
mounted with `projectId` alone (`:311`). It is a linkable URL that renders the
default page: the same class 3a fixed for `doc`/`artifact`/`finding`, minus the
fix.

Two changes, and they are the same change:

1. Thread the id. `managing` is `useState` at `use-topic-queue.ts:31`; it
   becomes the route's, so opening a topic is navigation and a link to one
   works.
2. **The status dialog stops being a `Drawer`.** §3.3 asked for this and gave
   the reason the loss is small: phase-1 of `check-deleted.mjs` records that its
   hand-rolled focus trap is already gone, so what goes is modality, not the
   keyboard contract. The mandatory-justification form **stays a `Confirm`
   inside the pane** — §5.2's own conclusion, and `Confirm` exists.

### Task C — the graph cluster onto utilities

`GraphPane.tsx` (381, container + `GraphBrowser`), `GraphCanvas.tsx` (361),
`GraphDetail.tsx` (121), `GraphLegend.tsx` (77). ~30 class names.

Three of them carry `z-index: var(--z-sticky)` (`research.css:391, 578, 690`),
and `scripts/stacking.test.ts` polices that token while `tokens.css:168–170`
names these three components as its inventory. **A utility rewrite must not
launder a z-index past that rule.** Find the precedent an already-migrated
sticky element set and follow it; if none exists, the honest move is a named
class that stays in a stylesheet, and the report says which.

`GraphCanvas` reads theme tokens through `getComputedStyle` (`:148`) rather than
CSS. That is untouched — it is the canvas, and a canvas cannot inherit a class.

`.graph-results-panel` (`research.css:678–684`) and `.graph-detail-edges`
(`:853–861`) carry `padding: 4px` against a 3px ring: 1px of slack, marginal
rather than broken. Rewrite them inward too, or measure and say they are fine.

### Task D — the seed form

`SeedForm.tsx:46–82`, five classes (`.seed-panel`, `.seed-form`, `.seed-input`,
`.seed-status`, `.seed-failed`). The smallest task here and the one that decides
whether `research.css` dies.

### Task E — delete the file (depends on A, C, D)

1. `rm frontend/src/styles/research.css` and its import.
2. `check-deleted.mjs:427` — remove `'research.css'` from `STYLESHEETS`. The
   array fails on removals as well as additions, so this is required, not
   optional; `check-deleted.test.ts:61` fails until it lands.
3. A new rule over `where: 'styles'` forbidding `/^\.topic-/m`,
   `/^\.sub-question/m`, `/^\.graph-/m`, `/^\.seed-/m`, mirroring the existing
   `C3` rule (`:365–378`) and its stated reason: a re-added unlayered rule beats
   `@layer utilities`.
4. **Two `why` strings become false.** `:346` says "`course.css` and
   `research.css` themselves are still alive" and `:367` says "Neither file
   dies". Edit them; a rule whose reasoning is stale is worse than no rule.
5. Two rules scope to `presentation/research` (`:81–87`, `:200–206`). If that
   directory empties, they bind to nothing — rescope or annotate, do not delete
   silently.
6. `tokens.css:168–170` names the three `--z-sticky` users. Whatever task C
   decided, this comment has to agree with it.

### Task F — measure it (depends on all)

The four gates, plus `npm run test:browser`, plus the two browser measurements
this slice owes: the `.topic-list` ring, and the graph's sticky overlays still
stacking correctly after the rewrite. Bundle measured the way 3a measured it —
gzip each built asset against `HEAD` — because the graph is `React.lazy` over
~60 kB and this is the slice where that becomes checkable.

## 3. What this slice will not measure

Stated up front so the report does not discover it.

- **The three region widths.** `PROJECT_TRACKS`'s numbers have been "chosen
  rather than measured" for three slices; slice 2 said slice 3 was the honest
  place for it because it wanted a page with the graph on it. This is that
  slice. If it is skipped again, the report says so and it becomes a backlog
  entry rather than a fourth deferral.
- **Anything below `--bp-wide`.** Unchanged from 3a.
- **`.extraction-merge-list`**, the second focus-ring exposure. It is QUEUE's
  markup but the extraction pane's, not the topic list's, and it is not rewritten
  here.

## 4. Verification

Per `CLAUDE.md`: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run pytest`, `cd frontend && npm run verify` — all four, and the two ruff
commands are repo-wide. `npm run test:browser` separately and never concurrently
with another vitest.

Report to `docs/reports/increment-c-slice-3b.md`, following 3a's shape: what the
plan asked for against what the code said, what was measured and how, and what
is still not measured.
