# Where "what is running" lives

The console answers "what is running" in three places. One of them breaks the
rule `Shell.tsx` states for the other two, pays for a request every two seconds
to do it, and is the one a reader called dead. This moves each half of that
surface to the region whose question it answers, and deletes what is left.

## The problem, as measured

`Shell.tsx` gives chrome its scope test, quoting `App.tsx` on the agent dock:

> "what is running" is not a property of the page you happen to be on -- which
> is the whole reason it exists.

Three surfaces answer that question today:

| Surface | Scope | Source | Cost |
|---|---|---|---|
| `AgentWidget` (chrome, every route) | everything, everywhere | `workers.everywhere()` under `queryKeys.runningAgents()` | one shared query, refreshed off frames |
| `ProjectActivity` (landing-page row chip) | one project, filtered from the same cache | same key | **zero** additional requests |
| `WorkerList` via `Workers` (QUEUE header) | one project | `workers.on(projectId)` under `queryKeys.workers(projectId)` | **one request every 2s per open project page, forever** |

The third is the violation. It is a page-local read of a fact the chrome
already holds, and `Workers.tsx` states its own cost plainly: "one request
every two seconds per open course page, mostly to be told nothing changed."

Beside it in the same card sits `ExtractionPane`, which is **not** a duplicate
-- nothing else in the console shows extraction stages, model calls, or
`consolidating 41/802`. It is orphaned rather than redundant, and a header band
sized for its idle state is the wrong home for a view whose interesting state
streams for minutes.

The reported symptom was the card, not the architecture: dead when idle (two
negative sentences under two headings), visually flat, two widgets sharing one
box, and low density. Every one of those follows from the placement.

## The decision

Split the card by scope. Each half goes to the region whose question it
answers; the card itself stops existing.

### 1. The roster leaves QUEUE entirely

`Workers`, `WorkerList` and `WorkerListUnavailable` are deleted. The dock is
the answer, and `ProjectActivity` remains the landing-page one.

**What this costs, stated rather than argued away:** the roster's per-worker
"open this session" button goes with it. The dock has the same affordance
(`AgentRow` -> `WorkerDrawer`), one click further away, and it is the *same
drawer component*. A reader on a project page who wants to watch a worker now
opens the dock rather than reading a list already on screen.

**And the two are not equivalent, which is the part worth stating precisely.**
The roster's button *navigated* -- `onWatch` in `ProjectView:525` writes
`sessionSelection(sessionId)` with `replace = false`, so a watched worker
became a URL and a back-button destination. The dock's row opens an overlay
and writes nothing. So this deletes the only path from "a worker is running" to
"that worker's transcript is in the address bar".

Checked rather than assumed: `sessionSelection` has three other producers
(`ProjectView:411`, the Holding-session tab at `ProjectView:597`,
`CoursePage:193`), so the `session` facet keeps its grammar, its href-writers
and its tests. What is lost is one entry point, not the destination.

Two consequences fall out and are in scope here rather than left as litter:

- `App.test.tsx`'s `puts a watched worker in the address bar under the session
  facet` drives that button, and its own comment claims it is "the only test in
  the repository that sees which one is written, because `Workers` takes
  `onWatch` as a prop and never builds an href". That claim is now stale --
  `CoursePage:193` builds exactly that href -- but the test still dies with its
  subject. It is **repointed, not deleted**: the surviving producer with a
  visible href is the one that should carry the assertion.
- `select(next, replace = true)` in `ProjectView` has exactly one caller
  passing `false`, and it is this one. With it gone the parameter is dead
  flexibility; it is removed in the same change, and the docstring arguing the
  glance-versus-destination distinction goes with it, because after this every
  selection on the page is a glance.

**What it buys:** the 2s poll is deleted, `workers.on(projectId)` loses its
only consumer, `queryKeys.workers(projectId)` loses both of its (`Workers.tsx`
and the invalidation in `use-project.ts:69`), and `watching`/`onWatch` stop
threading from `ProjectView` through `QueueHeader`, which passed them to
nothing else.

### 2. The dock starts polling while it is open

This is the part that makes the move honest rather than a straight deletion.
`Workers.tsx` records why it could not be replaced by the dock's mechanism, and
it is a guarantee rather than an oversight:

> a turn's events *append atomically when the turn commits*
> (`session_service.run_turn`): while a turn is running, the feed carries
> nothing about it at all. A `turn` worker is in the roster for exactly the
> interval in which no frame can arrive, so a frame-driven refresh would show
> it only after it had gone -- which is to say, never.

with the measurement in
`tests/integration/test_turn_visibility.py::test_a_turns_events_all_become_visible_at_once`,
and the conclusion: "the dock's frame-only refresh understates a turn's
liveness. That is the dock's bug, not an argument for copying it here."

Taking this design means fixing the dock's bug. `useRunningAgents` adds
`refetchInterval: expanded ? 2_000 : false` to the roster query -- the same
interval `Workers` used, on the same guarantee, gated on the widget being open.

**Cost, plainly:** a request every 2s while somebody is looking at the dock,
against today's every 2s on every open project page whether anyone is looking
or not. The collapsed dock keeps its frame-only refresh, which is correct for
the count it draws: a run or a dispatch appearing does produce a frame; only a
turn does not, and a turn is the case the open panel now covers.

`ProjectActivity` shares the key and gains nothing and loses nothing -- it does
not set an interval, and React Query applies intervals per observer.

### 3. Extraction moves to the Graph tab, as a float on the stage

`ExtractionPane` moves from `presentation/project/queue/` to
`presentation/research/`, beside `GraphPane`, and mounts as a row of the
Graph pane's existing top-left command column.

**Why the Graph tab.** "Reading into the graph" is the story of how that canvas
got its nodes. A reader watching an ingest is watching the thing this tab
draws, and the tab already reloads itself on every `graph` frame -- so today a
reader can watch the canvas fill with no account of what is filling it, and
watch this pane count entities with no drawing of them.

**Why a float rather than a band above the stage.** The pane already states the
rule: "The canvas is the layer, and the controls sit on top of it rather than
in a column above it. Stacked, every search pushed the drawing down." The
top-left column at `absolute top-3 left-3`, capped at
`min(320px, calc(100% - 20px))`, is a `flex-col gap-2` stack of exactly this
kind of transient panel -- notices about capping, missing edges, search
progress. Extraction is one more, and the richest.

**Position within the column: first, above the search bar.** A running
extraction outranks a search box for the reader's attention, and it is the only
row in the column that is time-bounded.

Not bottom-left (`GraphLegend`), not the right column (`GraphDetail` takes
`inset-y-3 right-3` whenever an entity is selected, which is most of the time a
reader is doing anything).

**Costs.** The column is capped at 320px, so the merge list is narrower than it
was; it is already capped and scrolled by `.extraction-merge-list` for its own
reasons, so this narrows an already-bounded list. And the Graph tab is
`React.lazy` over ~60kB of `react-force-graph-2d`, so watching an ingest now
pulls a canvas -- acceptable, because the canvas is what the ingest is
building and the reader is going to want it drawn.

### 4. The float renders only when it has something to say

This is the fix for "dead when idle", and it falls out of the move rather than
being applied to it.

`ExtractionView`'s third state -- "No extraction has run on this project yet."
-- is **the same claim** the Graph stage's own empty state already makes:

> This graph is empty / Nothing has been extracted into this project yet.
> Ingest a document to start building it.

So the float does not render at all when `current` and `last` are both null.
The stage says it, once, in the place a reader is already looking.

**And the same fold fixes a lie the current code tells.** During a project's
first ingest the Graph tab renders "This graph is empty -- nothing has been
extracted into this project yet" while an extraction is running, because the
canvas has no nodes until the first `graph` frame lands. With the float
adjacent, the empty state takes a third branch: with `current` non-null it
reads as extraction in progress rather than as nothing ever having happened.
This is a pre-existing defect the placement makes visible; it is fixed here
because leaving two adjacent elements contradicting each other is worse than
either was alone.

### 5. What the float looks like

One card, one voice -- the four complaints answered.

**Header line**, replacing the `<h3>Reading into the graph</h3>` heading and
the separate `worker-head`:

```
● Extracting                                    14/61
```

A status dot carrying `--k-tool` (extraction's roster colour, so the float and
the dock's dot agree), the stage in words, and the count in flight right-
aligned. When only a finished run remains, the dot is hollow and the line reads
`Last extraction · <sourceId>`.

**Stage trail**, replacing the wrapped pill list. The pills become one
connected run of segments: stages already passed filled at `--fg-faint`, the
one in flight at `--accent` with a slow shimmer.

**There are no pending segments, and the first draft of this section was wrong
to promise them.** `Extraction.stages` is the stages *reached so far*, appended
as frames arrive -- not a declared pipeline. Drawing greyed future segments
would mean hard-coding an order, and that order is not one thing:
`ExtractionStage` carries perception's `perceiving`/`perceived` alongside
extraction's `storing`/`extracting`/`extracted`/`consolidating`/`consolidated`,
plus `failed`, which can arrive after any of them. A fixed track would draw a
transcription as an extraction that has skipped four steps.

So the trail grows rather than fills, which is the honest shape and is what the
existing code already does -- the change is that the segments touch and the
current one is marked by more than a colour. The existing comment stays true
for the new drawing: a bar over unequal stages would be a made-up number, and
this measures nothing.

**Counts** stay exactly as they are, in mono, including
`confidenceText`'s three-outcome rule.

**The merge list** stays behind the disclosure for the finished run and
inline-capped for the running one, unchanged.

**Motion** is off under `prefers-reduced-motion: reduce`. The dot's pulse and
the shimmer are the only two animations.

### 6. What QUEUE becomes

With the "Working now" card gone, `QueueHeader` holds only things a reader
*acts on*: ask, be-asked, run, seed, autonomy. That is the region's stated job
-- "what is there to do" -- and it is the first time the header has held only
that. It also returns roughly a card's height to the queue list below it.

## What is deliberately not done

- **No backend deletion in this change.** `workers.on` loses its frontend
  consumer, but whether `/api/projects/{id}/workers` has other callers is a
  separate survey with its own Python gates. Filed to `BACKLOG.md` instead.
- **No new MATERIAL tab.** `MATERIAL_TABS` records the measurement -- nine
  tabs, a 646px floor against 837px of tabs, eleven is where the strip stops
  fitting -- and calls the ~150px of headroom deliberately unspent, with the
  `course` split the standing candidate for it. A float spends none of it.
- **The dock is not restyled.** It works, and it is not what was complained
  about.
- **`WorkerDrawer` is untouched.** The dock uses it; only its second caller
  goes.

## Verification

The four gates, plus `test:browser` -- this change moves a component into a
positioned float and adds two animations, which is exactly the class
`CLAUDE.md` says jsdom cannot judge.

The assertions that must exist, and what each one fails on:

1. **The float is absent with no extraction, present with one.** Fails if the
   fold in §4 regresses to rendering an empty card.
2. **The Graph stage does not claim emptiness while an extraction runs.**
   Fails on the pre-existing lie in §4. Red before the fix.
3. **The dock's roster refetches on an interval while open and not while
   closed.** Fails if §2 is dropped -- which is the failure mode that would
   otherwise ship silently, because a turn's invisibility is exactly the case
   no frame can reveal. Fake timers.
4. **`workers.on` has no caller.** A grep-shaped test, or its absence from the
   port. Fails if the deletion is partial.
5. **Browser mode: the float's box does not overlap the search bar's box, and
   `GraphDetail` open does not overlap the float.** Fails on the collision the
   float's position is chosen to avoid -- and cannot be written in jsdom,
   which lays nothing out.
6. **Browser mode: the current stage segment computes a different colour from
   its neighbours.** The `data-state`-on-one-element defect `CLAUDE.md`
   records shipped past a green jsdom suite; this is the same shape.
7. **Both animations are suppressed under `prefers-reduced-motion`.**

8. **`sessionSelection` still reaches the address bar from a surviving
   producer.** Fails if repointing `App.test.tsx`'s watched-worker test turns
   into deleting it, which would leave the facet's href unasserted -- the state
   that test's own comment was written to prevent.

Deleted with their subjects: `WorkerList.test.tsx`, `Workers.test.tsx`,
`WorkerList.stories.tsx`. `ExtractionPane.test.tsx` and
`ExtractionView.stories.tsx` move with the component and gain the fold's cases.
`App.test.tsx`'s watched-worker test is repointed per §1 rather than deleted.
`ProjectView.browser.test.tsx` measures the QUEUE region and its measurement
changes with the card removed.
