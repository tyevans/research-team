# One console, one verb

Read out of a clean worktree at `origin/main` = `4a86e89` ("Give this project an
embedding provider and a vector store, switched off", #88), against the four
feature indexes written at `5a5a7cf`. Line numbers are pointers, not contracts.

**The four indexes are two commits behind and it does not matter.** `git log
5a5a7cf..HEAD` is `65569e2` (redstring 0.5.0) and `4a86e89` (an embedding
provider, switched off). Neither touches `frontend/`. Every UI claim the four
reports make is current, and I checked that before trusting any of them.

**How the load-bearing claims were checked.** This document is a synthesis of
four surveys and the temptation is to inherit their confidence. Five claims do
most of the work below, and each was re-read in source rather than taken:

- *Nothing on the landing page is a link.* `grep -rn "href=" frontend/src/presentation/tree/`
  returns nothing; `grep -rn "navigate("` returns five call sites, including
  `SessionRow.tsx:20` (the whole row) and `ProjectList.tsx:415,450,457`
  (`Resume`, `Course`, `Research`). Confirmed.
- *The client drops the gate's evidence at the schema boundary.*
  `interfaces/web/approvals.py` sets `allowed_decisions` unconditionally and
  `context` when present, with a docstring explaining why the key is
  conditional. `infrastructure/http/dto.ts`'s `approvalDto` declares exactly
  `id`, `session_id`, `tool_name`, `description`, `args`.
  `domain/approval/approval.ts` has neither field and types
  `ApprovalDecision = 'approve' | 'reject'`. Confirmed, and it is a schema
  omission rather than a rendering choice — the fields never enter the
  frontend's type system.
- *`gate_context` is real and is not a rendered string.*
  `application/stage_exit.py:gate_context` returns `stage`, `findings_artifact`,
  `artifact_paths`, `blocked`, `artifacts_reviewed`, `links_reviewed`,
  `unimplemented_checks`, `unreadable_artifacts` and a findings list with
  `check`, `severity`, `message`, `cites`. Its docstring says outright that it
  is "deliberately not a rendered string" and that "shipping prose would close"
  the question of what a UI shows. Confirmed — the decision this document makes
  is the one that docstring left open.
- *`/api/projects` folds one aggregate per project.* `app.py:list_projects`
  loops `await service.project_state(project_id)` for every row. Confirmed.
- *There is no route to `StageRunner`.* `grep -rn "StageRunner" research_team/`
  outside its own module returns `composition.py:59,225,986`,
  `workers.py:193` (a docstring) and `workflow_tools.py:313` (a docstring).
  `grep -rn "stage_runner" research_team/interfaces/` returns nothing.
  Confirmed.

**What I did not check, and cannot.** Nothing here has been run. I did not
install dependencies, start the server, or open a browser; every layout claim
is arithmetic over class names and comments, not an observation. Per
`CLAUDE.md`, the suite passing carries no information about any of it, and per
`landing-page.md` §8 a change verified only against a fresh database is
unverified — which applies to nothing here directly, because this proposal asks
for no read-model change, and that is itself one of its arguments.

Short version, so the rest reads as argument rather than suspense:

- **The application has one verb.** Something takes a project, runs turns, and
  hands it back. Sessions, seeding runs, dispatches, autonomous runs, extraction
  and the unrouted stage runner are all that verb with a different subject. The
  four pages are four projections of it, and none of them says so. §1.
- **So the project is the page, and the page has three regions:** what is
  *queued* for the project, what *holds* it now, and what the work *left
  behind*. Every feature in all four reports lands in one of those three, in the
  shell, or is deliberately dropped. §3, §4.
- **The layout is not new.** It is `use-panes.ts` — the session view's three
  collapsible panes with width redistribution and a "at least one stays open"
  rule — with three new tenants. The session view already solved this and
  nothing else in the console reuses it. §3.2.
- **Decisions leave the page entirely.** Approvals and autonomy move into the
  shell beside the agent dock, because an approval is the one thing that must
  reach a person regardless of which route they are on — which is exactly the
  argument the dock's own comment already makes about running work. §3.4.
- **No event shape breaks, and that is a constraint rather than an
  accident.** Everything this proposal renders is already on the wire. §5.5.
  The cost is that `send_back` and `halt` stay unavailable, and the decision bar
  has to say so rather than silently hiding them. §5.4.
- **The first increment is the decision bar, and it ships alone.** Parse the two
  fields the server already sends, render `gate_context` with the findings
  renderer that already exists, and hoist approvals into the shell. Zero new
  requests, zero backend change, and it fixes the most consequential blind spot
  in the console. §9.
- **The strongest argument against all of it** is that the densest page in the
  console has one test file, and this merges two more pages into it. §11.

---

## 1. The idea

**This application has exactly one verb: something takes a project, runs turns,
and hands it back. Build the console on that verb instead of on the four nouns
it currently has.**

That is not a metaphor. It is `Project.decide` refusing a second `JoinProject`,
and it is the same five lines in three places — `TopicSeeder.seed`,
`DispatchRun.run`, and `POST /api/projects/{id}/auto-research`:

```python
session_id = await self._session.start_in_project(project_id)
try:
    await self._session.attach_project(project_id)
    ...
finally:
    await self._session.release_project(session_id)
```

`stage-boundaries.md` §6.2 puts the general form better than I can: "A stage
runner is `DispatchRun.run` with a stage where the topic is." That sentence is
about the backend, and it is also the whole of this document's frontend
argument. If a stage run, a topic dispatch, a seeding burst, an autonomous
round and a human's typed turn are the same shape, then a console that gives
each of them a different page is a console organised around implementation
history rather than around what happens.

Three consequences follow, and everything in §3 and §4 is one of them.

**A project has exactly one thing holding it, so a project page has exactly one
"now".** Today that "now" is spread across four surfaces that do not know about
each other: the landing row's `⟳ run · round 3` chip (L-F13), the course page's
worker roster (C-F5), the agent dock's popover (L-F42), and the session view's
composer, which reports a turn started elsewhere in a sentence (S-F54). Four
renderings of one fact, three of them on pages that cannot act on it — which is
the landing report's §11.3 exactly, and it generalises further than that report
claims.

**Everything that could hold it next is a queue, and the queues are
interchangeable.** The topic queue (R-F3.1), the stage list (C-F48), the session
list (L-F21) and the dispatch deque (R-F3.5) are four ranked lists of work
waiting on one sequential resource. They are drawn in four places, in four
visual languages, with four independent filter implementations. They should be
one list with row sources, because the project can only do one of them at a
time anyway — that is not a UI convenience, it is `Project.decide`.

**Everything else is residue, and the console currently calls it four different
things.** A "document" in this console means: a workspace file (S-F29), a corpus
source (R-F5.1), a topic-dispatch output (R-F4.4), or a course artifact (C-F55).
Two of those are literally both labelled `Documents` in the UI, in two places,
and the research report flags it (R-§8.5). They are all files or file-like
records that some run left behind, they are all read through renderers that
already exist, and three of the four already share the same `LessonDocument`
mount.

So: **queue, holder, material.** One project, one page, three regions.

### 1.1 What this is not

It is not "put the four pages behind tabs". A tab bar preserves the four models
and adds a control. The claim here is stronger and more expensive: that the
research view's own feeding controls being on the course page is not a wiring
mistake to be tidied but evidence that the *page boundary itself* is drawn in
the wrong place, and that once it is redrawn there is no course page and no
research page to reconcile.

It is also not "make everything one page". The picker (`#/`) stays a separate
route and gets *thinner*, and the session route (`#/s/<id>`) stays a top-level
linkable state because it is the single best-designed thing in the console.
§3.5, §7.

---

## 2. Why the four pages disagree, stated once

The landing report's §11 is the best piece of analysis in the four documents and
this proposal is largely a response to it. Its central observation — "It implies
a project is a row; every other page implies a project is a place" — is correct,
and it is worth extending in one direction its author did not take.

Each page is coherent *within* its own model. The course page really does treat
a workflow as the spine of everything, and its stage rail, its four artifact
states (C-F57) and its written-of-declared counts (C-F50) are all consequences
of that, done well. The research page really does treat a project as a corpus
being turned into a graph, and its rail-and-stage layout, its graph framing
rules and its legend are consequences of that, also done well. The session view
really does treat a session as a document, and its scrub, its fold-to-a-point
file viewer and its recorded-intent-versus-reconstructed diff (S-F37) are the
best work in the repository.

**The incoherence is entirely at the seams, and there are more seams than
pages.** The four reports found, independently:

| Seam | Reports |
|---|---|
| Autonomous research works the research view's queue and is controlled from the course page | R-§8.3 (and `CourseView`'s own comment concedes it) |
| Extraction fills the research view's graph and is narrated on the course page | R-§8.2 |
| Approvals are answerable from three surfaces, none of which is the one that asks most | S-F51, S-D19 |
| Two worker rosters, two poll intervals, one set of facts | C-D6 |
| Two drift reporters on one screen | L-F33 + L-F34, L-R14 |
| Two things called "Documents" | R-§8.5 |
| Two "file not here" messages, two code paths | S-D13 |
| The dispatch that wrote a document, and the session that ran it, cannot be joined | R-§8.6 |
| Conversation and timeline describe the same log and share no cross-reference | S-§14.15 |

Nine seams is not four pages with rough edges. It is one application drawn as
four, and every one of those rows closes by construction under §1 rather than
needing its own fix.

---

## 3. The shape

### 3.1 Routes

Four routes become three, and the grammar becomes uniform.

| Route | Meaning |
|---|---|
| `#/` | the picker: projects, and nothing you work in |
| `#/p/<pid>` | the project page, default selection |
| `#/p/<pid>/<facet>/<id>[/…]` | the project page with one thing selected |
| `#/s/<sid>[/at/<n>][/file/<path>]` | one session's transcript, standalone |

`<facet>` is one of `session`, `topic`, `stage`, `entity`, `doc`, `file`,
`artifact`, `finding`. That is one grammar covering every linkable state the
console has today plus several it does not:

```
#/p/x/research/entity/abc   →  #/p/x/entity/abc
#/p/x/course/watching/s1    →  #/p/x/session/s1
#/p/x/course                →  #/p/x/stage/<current>
#/s/s1/at/12/file/a.md      →  #/p/x/session/s1/at/12/file/a.md   (and the short form still works)
```

Three properties this buys, all of which the routing module's own docstring
already claims and only the session route currently delivers:

- **A topic is linkable.** Today `Manage` is component state, so "look at this
  topic" is not a thing you can send.
- **An artifact is linkable.** Today it is a link into a *session's* file
  viewer, keyed by whichever session happens to hold the project.
- **A stage is linkable.** Today `openStage` is a single string in
  `CourseView`'s state (C-F51) and a course page always loads fully collapsed
  (C-P8).

`parseRoute` is a pure function over hash segments with a `default` arm
returning `home`, so mapping the two legacy shapes onto the new ones is a
handful of lines in one file and costs nothing at runtime. §5.1 prices what it
does not save.

### 3.2 The layout is `use-panes.ts`

The project page is three collapsible panes: **QUEUE**, **HOLDER**, **MATERIAL**.

This is not a new layout. It is `presentation/session/use-panes.ts` and
`Pane.tsx` with different tenants, and the session report is right to call the
width-redistribution behaviour "genuinely subtle and worth preserving" (S-F18):
a collapsed pane gives up a fixed 34px track rather than a min-width, the hook
owns `grid-template-columns` above 1181px and hands the tracks back to the media
queries below it because an inline style would outrank them, and collapsing
refuses to hide the last open pane (S-F17). Three responsive layouts already
exist (S-F19).

**The research view's `RailPane` is deleted and its stored preference group with
it.** Two pane mechanisms with different fold semantics — one unmounts the body
so a virtualizer does not measure a zero-height scroller (R-F1.1), one keeps a
34px labelled rail, one enforces a last-open rule and one deliberately does not
— is one mechanism too many, and the session view's is the more developed. The
unmount-on-fold behaviour is the part worth carrying across, because MATERIAL
holds two virtualizers.

Fixing `Pane.tsx`'s glyph-only accessible name (S-D2) then fixes it everywhere
at once. It is currently a known bug that `AgentWidget.tsx:130-133` explicitly
declines to spread.

### 3.3 What is in each region

**QUEUE** — everything that could take the project next, one ranked list with
five row sources: topics, stages, sessions, dispatches, and the seed/run
controls that fill it. The row sources are heterogeneous and the list is not,
because the resource they contend for is not.

- Header: preset name and position (C-F1, C-F2), the run panel's counters and
  controls (C-F18–F29), the dispatch bar (R-F3.6), the seed control (R-F2.1).
- Filter and slices: one filter (R-F3.2) over all row kinds, and four slices
  (R-F3.3) rewritten as `All` / `Needs you` / `Running` / `Done`. `Needs you`
  now spans a blocked topic, a stage whose gate is posed, and a pending
  approval — which is the first time that phrase has been true of everything it
  covers.
- Rows: a topic (R-F3.1), a stage (C-F50), a session (L-F23–F28), a running
  worker (C-F5–F9), with their existing chips.

**HOLDER** — what has the project now, or the last thing that did. This is the
session view, in place: scrub bar (S-F9–F15), timeline (S-F21–F28), conversation
(S-F42–F49), composer (S-F52–F58). Selecting a running worker in QUEUE opens its
transcript here; selecting nothing shows the holder, or an explicit "nothing is
holding this project" with a `Join` button — which closes C-D2 and C-P5, four
degradations that today explain themselves only in a `title`.

**MATERIAL** — everything the work left behind, faceted:

| Facet | Sources | Today |
|---|---|---|
| `workspace` | the holding session's files at a point | S-F29–F41 |
| `artifacts` | the preset's declared outputs | C-F55–F62 |
| `corpus` | stored sources | R-F5.1–F5.7 |
| `graph` | the knowledge graph | R-F6.1–F6.9 |
| `findings` | this stage's checks, and any gate's context | C-F46, C-F47 |
| `topic` | a selected topic's detail | R-F3.10, R-F4.1–F4.4 |

One reader, one selection model, one filter. The renderers do not change:
`Markdown`, `CodeBlock`, `DiffView`, `LessonDocument` and the four widget
components are all already shared, and `LessonDocument` is already mounted from
two places (`FileView.tsx:196`, `TopicDocuments.tsx:170`).

**The default facet is `workspace`, not `graph`,** and that is a bundle decision
rather than a taste one. `GraphCanvas` is `React.lazy` over ~60kB of
`react-force-graph-2d`, deliberately, so a session transcript never pays for it
(R-F6.1). Defaulting to `graph` would hand that cost to every project page load.

### 3.4 Decisions leave the page

**Approvals and autonomy move into the shell, beside the agent dock.**

The argument is the dock's own, verbatim from `App.tsx:70-76`: it sits in the
topbar "because 'what is running' is not a property of the page you happen to be
on — which is the whole reason it exists". *What is asking you* is not a property
of the page you happen to be on either, and it is more urgent than what is
running, because a parked approval blocks a turn and everything queued behind
it.

This is also the only honest place for autonomy. `AutonomyPolicy` is
instance-wide and the panel says so loudly, in a warning rendered on the control
rather than in a tooltip, shared verbatim between two surfaces via
`autonomy-copy.ts` because wording drift between them is treated as a
correctness bug (C-F33). A policy that governs every session in the process
sitting inside one project's page is a scope claim contradicted by its own
placement. In the shell, the claim is structural.

Three seams close in one move: the three-places problem (S-F51), the missing
autonomy control on the surface that asks most (S-D19), and the duplication
between `AutonomyPanel` and `AutonomyAllowAll` (C-F30–F38, C-F41), which already
share one unparameterised query key precisely so they cannot disagree (C-F38).

### 3.5 The picker gets thinner

`#/` keeps its purpose line, first-run page, search, recency headings,
virtualizer, drift banner and creation form. It loses the two destination
buttons (L-F17, L-F18), because there is one destination.

It also stops being where liveness is computed. Today the row's `⟳` chip costs
two requests per drawn row (L-F13), and the landing design's §8 answer 1 records
that this was judged worth it while naming the right fix as "still not done".
Under this proposal the fix is free: the agent dock already fetches
`GET /api/workers`, which folds only projects its supervisors named, and every
worker kind the chip cares about is in it. One request replaces `2N`. §6.1.

That also un-blocks the one thing the landing design wanted and could not have:
"a live project sorts first regardless of timestamp" (L-F7) was not built because
knowing liveness for every project meant a request per project *including ones
nobody scrolled to*. From a single roster, it is a sort key.

---

## 4. Where every feature goes

Feature ids collide across the four reports — all four use `F1`. I prefix by
report: **L-** landing, **R-** research, **C-** course, **S-** session. `D`/`G`/`P`
prefixes keep their reports' meaning. Landing §9's numbered rough edges I call
**L-R1**…**L-R17**.

Regions: **PICKER**, **QUEUE**, **HOLDER**, **MATERIAL**, **SHELL**, **DECISION
BAR**, **DROPPED**.

### 4.1 Landing page (L-F1 – L-F48)

| Id | Goes to | Note |
|---|---|---|
| L-F1 purpose sentence | PICKER | unchanged, still not dismissible |
| L-F2 first-run page | PICKER | guard fixed: require *both* session reads settled, closing L-R16 |
| L-F3 search | PICKER | now `#/?q=`, closing half of L-R10; also matches session and project ids |
| L-F4 `/` shortcut | SHELL | global, and joined by `?` for the help overlay (S-D5, S-D6) |
| L-F5 new-project disclosure | PICKER | unchanged |
| L-F6 recency headings | PICKER | unchanged, including `now()` from the container |
| L-F7 ranking | PICKER | the unbuilt "live sorts first" becomes buildable — §3.5 |
| L-F8 virtualizer | PICKER | **kept verbatim**, `getItemKey` and `scrollMargin` included — §7 |
| L-F9 live refresh | SHELL | gains `queryKeys.projects()` on `project` frames, closing L-R6 |
| L-F10 project name | PICKER | becomes `<a href={projectHref(id)}>` |
| L-F11 workflow chip | PICKER + QUEUE header | three states unchanged |
| L-F12 held/free chip | PICKER + HOLDER header | unchanged |
| L-F13 live activity chip | PICKER | re-sourced from the dock's roster; shows *all* workers, closing L-R11 |
| L-F14 stat line | PICKER | `N files` relabelled "file writes" — L-R7 is a labelling bug, not a fold |
| L-F15 Resume / New / Open | PICKER | all become anchors; `join` moves to HOLDER as well |
| L-F16 take-over confirm | PICKER | **wording verbatim** |
| L-F17 Course button | DROPPED | one destination |
| L-F18 Research button | DROPPED | one destination |
| L-F19 overflow → Delete | PICKER | the menu grows and finally earns itself — §8.3 |
| L-F20 current-session preview | PICKER | unchanged |
| L-F21 session fold / forest | PICKER + QUEUE | open set goes into the URL, closing the rest of L-R10 |
| L-F22 "nothing has run" | PICKER | now points at the project page |
| L-F23–F28 session row fields | PICKER + QUEUE | L-F25's `failedTurns` becomes a link into a filtered timeline, closing L-R12 |
| L-F29 row navigation | PICKER | `<a>`, closing L-R3 |
| L-F30 two-source fallback | PICKER | **kept verbatim, comment included** — §7 |
| L-F31 per-project forest rebuild | PICKER | unchanged |
| L-F32 `project_id` on summaries | — | the key everything groups on; untouched |
| L-F33 in-page drift banner | PICKER | stays here only |
| L-F34 topbar drift badge | SHELL | everywhere *else*; L-R14's duplication resolves. The reconnect re-check moves into the shared hook so both paths get it |
| L-F35 connection badge | SHELL | unchanged |
| L-F36 breadcrumbs | SHELL | names the project when `/api/projects` is warm, short id on a cold deep link — §8.2 |
| L-F37 toasts | SHELL | gains a keyboard route, closing L-R13 |
| L-F38 single SSE connection | SHELL | load-bearing, untouched |
| L-F39–F44 agent dock | SHELL | promoted: it becomes the *cross-project* queue-and-holder. Inverted preference key fixed (a break — §5.3) |
| L-F45–F48 new-project form | PICKER + QUEUE | reused on the project page for "choose a workflow later", closing C-D1/C-P4. L-F48's error defect fixed |

**L-R1** (`/api/projects` folds per project) is the standing cost and this
proposal does not fix it; §6.1 says what it does instead.
**L-R2, R3, R5, R6, R9, R10, R11, R12, R13, R14, R15, R16, R17** close as above.
**L-R4** (controls that 409 with no remedy) closes for the two turn-running
cases, because HOLDER has the cancel control; the "course button on an unshipped
preset" case closes because there is no course button.
**L-R7** becomes honest labelling. **L-R8** (`lastActivity` is session *start*)
needs a server fold and stays open; the row should say so in its `title`, which
is free.

**Landing §10's power gaps.** *Project page*: this proposal. *Change workflow*,
*release*, *cancel a run or turn*, *start a run*, *fork from the list*: all
reachable, routes already exist. *Sort and filter by more than recency*: PICKER
facets over fields already client-side. *Search by session id*: added.
*Link to a filtered view*: added. *Rename a project*: **stays impossible** — no
command exists and inventing one is out of scope. *Bulk operations* and
*archive*: **deliberately dropped**; one operator with dozens of projects does
not need multi-select, and archive is a lifecycle verb the domain does not have.
*Sessions predating projects*: `SessionStarted.project_id` became required in
#65, so the empty state's claim that they exist and are unreachable is now
stale copy and should be deleted. *Distinct file counts and true last-turn
time*: both need server folds; flagged, not proposed.

### 4.2 Research view

| Id | Goes to | Note |
|---|---|---|
| R-F0.1 four entry points | PICKER | collapse to one |
| R-F0.2 the `Course` link out | DROPPED | nowhere to go |
| R-F0.3 URL selection, `replace: true` | — | **kept with its reasoning**: browsing a graph grows it, so back cannot un-draw |
| R-F1.1 rail folding | HOLDER/MATERIAL panes | replaced by `use-panes.ts`; stored group is a break (§5.3) |
| R-F2.1 seed topics | QUEUE header | gains a `max_topics` control (R-§9.6) |
| R-F2.2 `SeedingRun.reply` | QUEUE | **surfaced** — the model's account of what it did |
| R-F3.1 ranked queue | QUEUE | one row source of five |
| R-F3.2 filter | QUEUE | filters all row kinds |
| R-F3.3 focus slices | QUEUE | `Needs you` widens to gates and approvals |
| R-F3.4 dispatch | QUEUE | the one disabled control and its reason kept exactly |
| R-F3.5 dispatch chips | QUEUE | finished chips still kept, not cleared |
| R-F3.6 dispatch bar + Stop | QUEUE header | now reports `{cancelled: N}` (R-§9.7) |
| R-F3.7 Manage dialog | MATERIAL `topic` | **dropped as a dialog**; the dead-button-on-a-slow-read state disappears with it |
| R-F3.8 live refresh | QUEUE | unchanged; the un-addressed topic frame stays a known cost |
| R-F3.9 state model | QUEUE | unchanged |
| R-F3.10 unrendered detail | MATERIAL `topic` | `rationale`, `scope`, `sourceIds`, `findingNotes`, `contested` all rendered — the single largest unlock in the research report |
| R-F4.1 status change | MATERIAL `topic` | mandatory justification kept |
| R-F4.2 dialog keyboard contract | — | partially lost; §5.2 prices it |
| R-F4.3 sub-questions | MATERIAL `topic` | unchanged, including the hand-invented `key` |
| R-F4.4 topic documents | MATERIAL `doc` | merged with the corpus facet's reader, closing R-§8.5 |
| R-F5.1 corpus list | MATERIAL `corpus` | virtualizer kept |
| R-F5.2 filter | MATERIAL | shared across facets |
| R-F5.3 document reader | MATERIAL | in the pane, not a drawer over the page |
| R-F5.4 live refresh | MATERIAL | unchanged |
| R-F5.5 state model | MATERIAL | the empty state can finally point somewhere honest |
| R-F5.6 range reads | MATERIAL | **built**, because C-F61's provenance links already carry `?start=&end=` |
| R-F5.7 unshown fields | MATERIAL | `uri`, `publishedAt`, `note`, `sha256` rendered |
| R-F6.1–F6.9 the graph | MATERIAL `graph` | essentially unchanged; framing rules, legend, `Reset` and the two truncation notes all kept, the notes finally distinguished (R-§7.6) |

**R-§7.1** (seven routes that 503 and read as server faults) and **C-D3**
(feature-off detection by regex over an error message) are the same defect and
close together: **the one backend change this document asks for is
`GET /api/capabilities`.** §6.3.
**R-§7.2** (`useDispatchTopic` and `useCancelDispatch` with no `onError` at all)
is a two-line fix and belongs in the first week regardless of this proposal.
**R-§7.3** 404s: the bad-entity URL gets a "not in this graph" state instead of
a persistent error line over a null panel.
**R-§7.4**: pinned nodes and reset are unresolved — §8.4.
**R-§7.5** (empty states with no next step): all three close, because the seed
control, the dispatch control and the graph are on the same page as the empty
state that names them.
**R-§7.7** keyboard: the graph gains a textual entity list, which is the only
honest keyboard route to a canvas.
**R-§8.1–8.7** are the seams §2 tabulates; all close by construction except 8.1
(`MAX_TOPICS` hardcoded), which the seed control fixes directly.
**R-§9**: items 1–7, 10, 13–17 close. Item 8 (cancel one queued dispatch) needs
a server route and is **not proposed** — `topic-dispatch.md` §5 argues cancel is
per project and a per-row control offers an action it cannot honour. Item 9
(retry a failed dispatch) becomes a labelled retry on the chip. Items 11
(restate a question) and 12 (delete or unresolve a sub-question) have no
commands and **stay impossible**; the interim for 11 is supersede-and-reopen and
the UI should at least link the two topics, which needs no new command.

### 4.3 Course view

| Id | Goes to | Note |
|---|---|---|
| C-F1, C-F2 | project page header, QUEUE header | `position === null` sentence kept |
| C-F3 Research link | DROPPED | |
| C-F4 Open holding session | DROPPED as a link | HOLDER *is* the holding session |
| C-F5–F9 worker roster | SHELL dock + QUEUE | the 2000ms poll dies; C-D6's two rosters become one. Nesting (C-F7) survives |
| C-F10–F17 extraction pane | QUEUE running section + MATERIAL `graph` | closes R-§8.2. C-F13's three-outcome confidence and C-F15's reconnect catch-up kept verbatim |
| C-F18–F29 run panel | QUEUE header | kept whole. C-F26's endings-in-words and their tones, and C-F27's "ending not seen", are among the best copy in the console. C-D10 fixed with a `stopping` state |
| C-F30–F38 autonomy panel | DECISION BAR | §3.4. C-F33's verbatim copy sharing, C-F36's `NO_POLICY` and C-F37's inline verbatim rejection all kept |
| C-F39–F45 worker drawer | dissolved, partially kept | HOLDER replaces it for this project; the drawer survives for the dock's *foreign-project* rows, which have nowhere else to go. §5.2 |
| C-F46, C-F47 findings | MATERIAL `findings` **and** DECISION BAR | the same renderer serves both — the highest-leverage reuse in this proposal. C-D7's vanishing-when-empty fixed |
| C-F48–F55 stage rail | QUEUE | C-F51's one-at-a-time becomes many (C-P9); C-F54's findings link lands in MATERIAL |
| C-F56–F62 artifacts | MATERIAL `artifacts` | four states (C-F57) and provenance chips (C-F61) unchanged; gains facets (C-P7); C-F62's degradation gains a `Join` button |
| C-F63 live refresh | SHELL | must stop invalidating `queryKeys.projects()` wholesale (C-D9) — §6.2 |
| C-F64–C-F66 file viewer, lessons, source reader | MATERIAL | renderers unchanged |

**C-D1** (a project with no workflow is a cul-de-sac) closes: the creation
form's workflow select is reused on the project page, and the route and
repository method both already exist.
**C-D2** closes: one `Join` control unlocks four degradations at once.
**C-D3** closes with §6.3.
**C-D4** (a missing extraction route is indistinguishable from "nothing ran")
closes with §6.3 too.
**C-D5** (provenance links can 503) closes the same way.
**C-D8** (`elapsed` does not tick) closes: the dock already ticks.
**C-D11** (the rail is one boundary behind on artifacts) closes by subscribing
to `FileWritten` for the *current stage's declared paths only* — a narrow
subscription rather than the blanket one C-F63 rightly refuses.
**C-D12** (`position === null` is not actionable) **stays open**: `_advanced`
refuses anything but a single forward step, so there is no route back and a UI
control would be a lie.
**C-D13** (stale and errored rosters look similar) closes with one roster.
**C-D14** (stage status is positional, not evidential) closes: the row carries
an evidential chip beside the positional one, because `0/2` already knows.
**C-D15** (the findings report is a bare path) closes: the findings facet renders
the fields, so `render_review` does not need a route.
**C-D16** (an unknown frame type is dropped with no log) is a two-line fix and
should just be done; it has already cost this project once, for `Extraction`.

**C-G1** `StageRunner`: **not routed here, deliberately.** `composition.py:230-234`
argues it should be built after a human has driven a preset by hand, "because the
thing that would falsify its design is a prompt". What this proposal does instead
is *reserve the seat*: `Worker.kind` already includes `'stage'`, QUEUE already
renders workers, so the day a route exists a stage run appears with no frontend
work. That is the right relationship between a UI and a deferred capability.
**C-G2, C-G3, C-G8** (prompts, generators, critics): **not a UI problem, and the
redesign must not imply otherwise.** A console that looked finished over an
engine with 6 of 38 prompts resolved would be actively misleading.
**C-G4** `gate_context`: §9, the first increment.
**C-G5** `allowed_decisions`: §9 and §5.4 — half of it, honestly.
**C-G6** `StageAdvanced.decision`: gains its first consumer.
**C-G7** `ubd.uncoverage`: out of scope, a preset-binding question.
**C-G9** widgets: reachable already; both mount points survive.
**C-G10** (nothing says an artifact is interactive): closes for the *selected*
artifact only, because `/files/parsed` is a request per file and doing it for a
51-artifact preset on load is not worth the answer.
**C-G11**: no corpus write route, no graph write route, no run history,
per-dispatch cancel — all stay unbuilt, all named in the UI's empty states
rather than implied by them.
**C-P1–P16**: P1 deferred with C-G1; P2, P3 in §9; P4, P5, P6, P7, P8, P9, P13
close; P10 (re-run checks on demand) stays unrouted; P11 (`prompt_digest`)
blocked on C-G2; P12 (verify a provenance span) **deliberately not built** —
C-F61 is right that resolving spans is a check's question and would cost a
document read per row; P14 (per-project autonomy) is a domain question, not a UI
one; P15 closes with C-D14; P16 unchanged.

### 4.4 Session view

| Id | Goes to | Note |
|---|---|---|
| S-F1 linkable route | — | **kept and generalised**; it is the model for §3.1 |
| S-F2 replace not push | HOLDER | kept, with its reasoning |
| S-F3 session store | HOLDER | opened by the project page as well as the session route |
| S-F4 whole-page error | HOLDER | becomes region-level: one failed session read must not blank a project page |
| S-F5, S-F6 stream and reconnect | SHELL | unchanged, including the two different guarantees |
| S-F7 fresh highlight | HOLDER | unchanged |
| S-F8 error toasts | SHELL | unchanged |
| S-F9–F15 scrub bar | HOLDER header | S-F13's copy kept; D8's misreport needs a server change and is flagged, not proposed |
| S-F16 Escape → live | HOLDER | kept, and finally documented (S-D5) |
| S-F17–F20 panes | **whole app** | promoted; §3.2 |
| S-F21–F28 timeline | HOLDER | S-F24's fork column gains visible state (S-D7). Virtualization and filters (S-§14.3) deferred and priced — §6.4 |
| S-F29–F41 workspace | MATERIAL `workspace` | S-D10 fixed: invalidate `file`, `fileHistory` and `lesson` keys on turn end |
| S-F42–F49 conversation | HOLDER | merged with the timeline (S-§14.15) — deferred and priced, §6.4 |
| S-F50, S-F51 approvals | DECISION BAR | one place instead of three; taken down by `ApprovalSettled`, not by the click handler — §7 |
| S-F52–F58 composer | HOLDER | S-F58's historical warning kept; S-D15 (sending while scrubbed) deliberately unchanged |
| S-F59 breadcrumbs | SHELL | §8.2 |
| S-F60 agent dock | SHELL | §3.4 |
| S-F61 badges | SHELL | unchanged |

**S-D1** `window.confirm` → `Confirm.tsx`, which already exists.
**S-D2** fixed once for the whole app (§3.2).
**S-D3** nine title-only explanations: addressed by the `?` overlay plus inline
text where a region has room, which is more of them than before.
**S-D4, S-D12, S-D14, S-D22, S-D24**: small, named, fixed in passing.
**S-D9** closes with S-D10.
**S-D11** (history ignores the scrub point) is a *correct* choice with nothing on
screen; MATERIAL says so in one line.
**S-D13** two "file not here" messages become one.
**S-D16**: pane layout stays a preference and fold state stays component state.
Both are right and the reasoning should be written down rather than the
behaviour changed — a shared link that reproduced someone's collapsed panes
would be a link to a different screen than they meant to send.
**S-D17, S-D18** silent failures: surfaced as region-level notes, not toasts.
**S-D19** closes with §3.4. **S-D20** is §9.
**S-D21** `system_prompt`: a HOLDER header disclosure, "what this agent was
told" — which is also where a resolved stage prompt would go if C-G2 ever lands.
**S-D23** (no presentation tests) is the risk, not a placement — §11.
**S-§12** unreachable 1–9: 1 above; 2, 3, 4 in §9; 5 in §3.4; 6 (`startedAt` on
the session page) added to the HOLDER header; 7 (`decision` on project frames)
gains a consumer with C-G6; 8 with S-D1; 9 (`at` echo discarded) **deliberately
left** — trusting the client's own scrub state is correct, and the echo is a
cross-check nobody needs.
**S-§13** unbuilt 1–5: 1 is §9; 2 is §3.4; 3 (the design language never
back-ported) is real and this proposal inherits it — §6.5; 4 **explicitly
preserved**: there is no authentication, the learner toggle is a presentation
affordance documented as one in three places, and any redesign that makes it
look like a permission boundary is a regression; 5 (empty `artifact_paths` on
the tool path) must be handled by the decision bar, not assumed away.
**S-§14** power gaps: 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 15, 18, 19 close or are
scheduled. 1 and 2 (compare two points, diff two workspaces) become a MATERIAL
compare mode, deferred. 11 (name a session) **stays impossible** — no field
exists server-side, and the report is right that this is a real feature rather
than a wiring gap. 14 (download, export) **dropped for now**. 16 (raw event
payload) **dropped**: `/events` returns rows, not payloads, and adding a payload
route to satisfy curiosity is a poor trade. 17 (follow tool calls in the
conversation pane) closes with the timeline merge, deferred.

### 4.5 The count

Nothing is unplaced. Explicitly dropped, with reasons above: L-F17, L-F18, the
duplicate research entry points in R-F0.1, R-F0.2, R-F3.7-as-a-dialog, C-F3,
C-F4, bulk operations, archive, session download/export, raw event payloads, and
the stale pre-project-sessions copy. Explicitly left impossible because no
command exists: rename a project, name a session, restate a topic question,
delete or unresolve a sub-question, go back a stage.

---

## 5. What breaks

### 5.1 URLs

`#/p/<id>/course` and `#/p/<id>/research` stop existing as distinct pages.
`parseRoute` maps both onto the new grammar, so links survive, but *what they
land on* changes: a `course` link opens the project page with the current stage
selected, not a page whose entire content is stages.

**What it buys:** one grammar, and three things that are not linkable today
becoming linkable (a topic, an artifact, a stage). §3.1.

`#/s/<id>` does **not** break. It stays a top-level route because it is the
best-designed thing in the console and because a transcript genuinely is a
document you send someone.

### 5.2 Behaviour

**The topic dialog stops being a modal.** R-F4.2 is a well-built focus trap that
re-queries `FOCUSABLE_SELECTOR` on every keypress because adding a sub-question
grows the dialog. A pane cannot make a modal's guarantee. What it buys is that
`Manage` stops being a button with no feedback until a request lands (R-F3.7),
and that a topic's detail is linkable. **This is a real loss and I would not
pretend otherwise**: a modal is the right container for a form with a mandatory
justification field, and if the status-change form turns out to need one it
should stay a `Confirm`-style dialog *inside* the pane rather than the pane
becoming a dialog again.

**The worker drawer mostly dissolves.** C-F39–F45 exists because there is no
place to watch a worker without leaving the page; HOLDER is that place. It
survives for the dock's foreign-project rows, which is the case it was really
built for (L-F42 calls it "the only cross-project way into a live transcript").
What breaks is the habit of watching a worker in *this* project without losing
your place — which is now the same thing as selecting it, and is therefore
better, but is a different gesture.

**The run panel and the extraction pane move.** Anyone with muscle memory loses
them from the course page. What it buys is R-§8.2 and R-§8.3: the controls that
feed the graph stop being on a different page from the graph.

### 5.3 Stored preferences

Three break, all of them one-time and none of them data:

- `collapsedPanes('research')` becomes meaningless when `RailPane` goes. A user
  who folded the seeding pane away finds it open once.
- `collapsedPanes('session')` describes three panes whose tenants change.
- `agents.popover` should be **un-inverted**. Today the stored name means *open*,
  inverting the port's sense (L-F40) as a deliberate trade so the default is
  closed. It works, and it means a reader inspecting `rt.collapsedPanes.agents`
  in devtools sees a reversed name. Fixing it closes an open dock once.

Each of these is a preference re-set on first load, and each should be a
deliberate key rename rather than a silent reinterpretation, so a stale value
reads as absent rather than as its opposite.

### 5.4 Contracts

`approvalDto` gains `allowed_decisions` and `context`. On the wire this is
additive and non-breaking — `approvals.py`'s own docstring notes that `context`
appears only when there is one, precisely so a client switching on the key gets
a reliable answer. In the client's type system it is a widening:
`Approval` gains two fields and `ApprovalDecision` goes from two values to four
(`approve`, `reject`, `edit`, `respond`), with `edited_args` and `message` on
the POST body, all of which `application/ports.py:294` and the HTTP `Decision`
body already support.

**The honest part, and the one I expect to be argued with.** `allowed_decisions`
can name `send_back` and `halt`. Those are **not** representable in the log:
`_advanced` (`domain/project.py:293`) computes `ids[at + 1]` and raises for
everything else including going back, and `StageAdvanced` is the only stage
event. `workflow-engine.md` §3.4 established this and `stage-boundaries.md` §8.3
confirms it stayed true.

So the decision bar must render `send_back` and `halt` **as named and
unavailable, with the reason**, rather than filtering them out. Filtering them
is how you recreate C-G5's exact failure in a new place: the stage rail already
displays a gate's permitted decisions as text (C-F53) and then offers two
buttons, neither of which is one of them, and the report is right that this is
the page naming what you may answer and then not letting you answer it. A
decision bar that silently drops two of four would be the same bug, better hidden.

### 5.5 Event shapes

**Nothing.** No new event, no field on an existing event, no aggregate.
`CLAUDE.md` requires a deliberate event-shape break to be written down rather
than done silently, and the thing to write down here is that there is none and
that this was a constraint rather than a coincidence: every field this proposal
renders is already on the wire, and the two capabilities I most wanted —
`send_back` and `halt` as answerable decisions — are declined in §5.4 precisely
because having them would require one.

The one addition is an HTTP route with no event behind it (§6.3).

---

## 6. What it costs

### 6.1 Requests, on the picker

Today, with `D` drawn rows: `GET /api/projects` (which folds one aggregate per
project server-side), `/api/tree`, `/api/sessions`, `/api/health`, `/api/workers`
once the dock has ever been opened, plus **two per drawn row** —
`/api/projects/{id}/auto-research` and `/api/projects/{id}/workers`. At `D = 8`
that is **21 requests**.

Proposed: the same five, and **zero per row**, because every worker kind the
chip reports is already in the single `GET /api/workers` roster the dock
fetches, which "folds only projects its supervisors named" (`app.py:1239`).
**5 requests.**

Two caveats, both real. `/api/workers` 404s when the roster is not wired, where
`/auto-research` today distinguishes "disabled" from "nothing running" by
string-matching its 404 detail (L-F13, C-D3) — §6.3 is how that stays
distinguishable. And the roster is process-local, so a restart shows an empty
roster; `workers.py` argues that is the truth, and the chip's existing "render
nothing rather than an error" rule already handles it.

**`/api/projects`'s O(projects) fold is not fixed by this proposal.** It is
L-R1, C-D9, and `landing-page.md` §5's named 500-project wall, and it wants the
treatment `/api/sessions` got — a projection kept current by a subscription. Out
of scope, and this proposal makes it *less* pressing on the picker and *more*
pressing on the project page, which is open for longer.

### 6.2 Requests and re-renders, on the project page

First paint costs the union of what the course and research pages cost today:
`/course`, `/workers`, `/extraction`, `/auto-research`, `/autonomy`, `/topics`,
`/sources`, `/graph`, `/topics/seed`, `/dispatch` — about **11**, against 6 and
5 on the two pages it replaces. A user who visits both today already pays 11
plus a second `/api/projects`. So: **more per project visit, less per session of
work**, and I would not claim more than that.

Two polls die. `Workers.tsx` polls every 2000ms and `RunPanel` polls every
2000ms while a run is live (C-F5, C-F28). The roster's poll is replaced by the
dock's frame-driven refresh, which already exists. The run's poll **stays**,
because a run's counters are folded from its own aggregate and are not on the
stream, and pretending otherwise would be inventing a frame.

**One re-render fix is required rather than optional.** `useCourseRefresh`
invalidates `queryKeys.projects()` on **every** project frame (C-F63, C-D9), so
a busy project re-folds the whole project list — one aggregate per project,
server-side, per frame. That is survivable on a page you visit; it is not
survivable on a page you leave open. It must become a single-row invalidation
before this merge, and that is a prerequisite, not a follow-up.

### 6.3 The one backend change

**`GET /api/capabilities`** — a static map of what this build wired, answered
from the same `None`-means-unwired parameters `create_app` already takes.

It replaces: seven routes whose 503 reads as a server fault rather than a build
without the feature (R-§7.1); a regex over a 404 message as the only way to tell
"autonomous research is off" from "autonomous research failed"
(`project-repository.ts:95`, C-D3); a swallowed error that makes a missing
extraction route indistinguishable from "nothing ran" (C-D4); and a provenance
link that can 503 with no warning on the row (C-D5).

It also earns its place under the merge specifically: a single page that renders
five row sources and six facets needs to know which of them can exist before it
draws six empty states. Today the four pages each discover that by failing.

`tests/interfaces/test_web_entrypoint.py` (added in #67, reading
`inspect.signature(create_app)`) is what keeps a new parameter from shipping
unpassed, and `topic-dispatch.md` §9 is right that it does not cover `main.py` —
a capability map is exactly the kind of thing that would be wrong there and
green everywhere.

### 6.4 Work that must be built rather than moved

Most of §4 is relocation. These are not:

| Work | Why it is new |
|---|---|
| The unified QUEUE with five row sources | four ranked lists with four filter implementations become one; the ranking function across heterogeneous rows is genuinely new design |
| The MATERIAL facet shell and one selection model | six facets with one filter, one URL segment and one empty-state discipline |
| `GateReview` — the `gate_context` renderer | §9; reuses `severityLabel` and `Findings.tsx`'s row shape, but the grouping is the decision the docstring left open |
| `GET /api/capabilities` and its client | §6.3 |
| Timeline virtualization | the timeline is not virtualised (S-§14.3) and a project page keeps it mounted far longer than a session page does |
| The timeline/conversation merge | S-§14.15, "the single largest missed affordance" — and a rewrite of `segmentTranscript` and `Timeline` against a page with no tests |
| A `?` help overlay | S-D6: the keyboard model is undocumented and inconsistent across four components |
| Tests for `presentation/session/` | S-D23; not optional under a merge |

The last two rows are the ones a plan will be tempted to drop, and the last one
is the one that must not be.

### 6.5 Bundle and design language

The bundle budget is `app-` 57 and `total` 512 (`landing-page.md` §8), and
`npm run verify` fails on it — one of the two checks that only exist in the
chain. A merged page grows `app-`. `GraphCanvas` stays lazy and the default
facet is `workspace` (§3.3), so the ~60kB force-graph chunk is still not paid by
a reader who came for a transcript.

`panes.css` uses ad-hoc `7px`/`12px`/`34px` rather than the `--space-*` scale,
because the session view predates the design language `landing-page.md` §6
established and it was never back-ported (S-§13.3). Promoting `use-panes.ts` to
the whole app promotes that debt with it. It should be paid during the promotion
rather than after, because the tokens `landing-page.md` §6 lists as *genuinely
missing* — `--line-strong`, the four `--tint-*`, `--shadow-1`, `--space-1`…`6`
— are exactly the ones a three-region page with nested padding needs.

---

## 7. What is right and must survive

A proposal that finds everything wrong is as useless as one that finds nothing.
These are load-bearing and this document changes none of them.

- **`SessionTree`'s two-source fallback** (L-F30), verbatim, comment included.
  Taking whichever source has more rows because the two projections can disagree
  about *membership* is subtle, correct, and tested. "A truthful degradation
  beats a 'no sessions yet' that is a lie" is the best sentence in the frontend.
- **The session route as a linkable state** (S-F1). It is the model §3.1 copies.
- **`ProjectList`'s virtualizer details** (L-F8): `getItemKey` by id, the
  `scrollMargin` re-measured with no dependency array, every row measured rather
  than estimated. All three were paid for once and the reasons are in the code.
- **`use-panes.ts`'s width redistribution** (S-F18), which is why §3.2 exists.
- **The confirmation wording** (L-F16, L-F19). "Its files carry over to the new
  session. Its conversation does not." is exactly right and changes container
  only.
- **The error-code convention**: 503 "this build wired no model", 404 "this
  build cannot tell you", 409 "the request was fine, a choice is missing". C-§2
  is right that it is worth carrying into a redesign, and §6.3 makes it
  *legible* rather than replacing it.
- **Approvals taken down by `ApprovalSettled`, not by the click handler**
  (S-F50). That is what makes answering in the REPL, in another tab, or here all
  work, and the decision bar inherits it unchanged.
- **The copy that distinguishes states nobody else would have separated**:
  three-outcome domain confidence (C-F13), four artifact states (C-F57),
  written-of-declared rather than a percentage (C-F50), endings in words with
  tones where only `queue_empty` earns `done` (C-F26), "ending not seen"
  (C-F27), `severityLabel` mapping `human_gate` to "needs a person" (C-F46),
  recorded intent versus reconstructed diff (S-F37), the compaction panel
  (S-F46). None of this changes and most of it gets *more* readers.
- **`component_guidance`'s gating** (C-G9). A stage writing source claims has no
  use for two kilobytes of widget syntax. Nothing here disturbs it.
- **The learner toggle as a presentation affordance**, documented as one in
  three places (S-§13.4). There is no authentication; a redesign that made it
  look like a permission boundary would be a regression.
- **Graph browsing replacing rather than pushing history** (R-F0.3). Browsing a
  graph grows it, so a back button restoring a previous entity could not un-draw
  what that click added.

---

## 8. Where I disagree with the reports

They are evidence, not scripture, and four disagreements are worth stating.

**8.1 The session report calls S-D10 "the most consequential defect I found". I
would rank C-G4 above it.** A file the agent just rewrote showing its old
contents is bad, and it is *visible once noticed* — the list says `r4` beside a
viewer showing revision 3, and a reader who spots it once will distrust the pane
forever after, which is the correct response. A stage gate answered against a
JSON blob of tool arguments, with the findings the server computed *for that
moment* nowhere on screen, is invisible by construction: the reviewer does not
know what they were not shown, and approving is the cheap answer. Two indexers
found C-G4 from opposite directions, which is itself the tell. Both should be
fixed; only one of them is a defect you cannot discover by using the product.

**8.2 The breadcrumb's refusal to name a project is right today and stops being
right under this proposal.** `Breadcrumbs.tsx` names the project by short id
because "a transcript knows which project it belongs to, but not what that
project is called" and fetching the name would delay every session load (L-§11.2,
S-F59). That reasoning is sound and I do not want it overturned by assertion.
Under this proposal a session is normally reached *through* its project page,
whose `/api/projects` row is already in the query cache — so the name is free on
the warm path and the short id remains correct on a cold deep link. The rule
becomes "name it if you already know it", which costs nothing and is not the
same as "fetch it".

**8.3 The landing report calls the one-item `⋯` menu "a click that buys only
concealment" (L-R15). I think it was right to build and is about to be
right.** A menu holding one destructive verb is indeed overhead. Under this
proposal it holds *Delete*, *Release* (the route exists and is offered nowhere),
and *Change workflow* (the route exists and is reachable only at creation,
C-D1). Three verbs, one of them destructive, is what an overflow menu is for.

**8.4 The research report marks pinned nodes surviving a reset as "unsure" and
flags it rather than asserting it (R-§7.4). I could not settle it either and I
am not going to let it gate anything.** `onNodeClick` sets `fx`/`fy` and nothing
clears them; `loadWhole` reuses node objects by id, so the pins plausibly
survive. It wants a test, not a design decision, and a design that depended on
the answer would be a design resting on an unread fact.

I also record one place where the reports agree and I think both understate it.
Research §7.2 calls `useDispatchTopic` having no `onError` "the single clearest
defect found". It is clearer than that: two mutations in one file both declare
only `onSuccess`, so a 503, a 404 and a 422 all produce *nothing visible* — and
`Write understanding` is the primary action of the research page. It is two
lines and it should not wait for a redesign.

---

## 9. The first increment: the decision bar

**Parse the two fields the server already sends, render `gate_context`, and move
approvals into the shell.**

It is worth shipping alone, against the current four-page console, with no
route change, no layout change and no backend change.

**What it is.**

1. `approvalDto` gains `allowed_decisions: z.array(z.string()).default([])` and
   an optional `context`. Both are already serialised at
   `interfaces/web/approvals.py:51,54`, on the REST route *and* the
   `ApprovalRequested` SSE frame.
2. `Approval` gains `allowedDecisions` and `context`. `ApprovalDecision` widens
   to four values, offered only where `allowedDecisions` names them, and
   `send_back`/`halt` render as named-and-unavailable with the reason (§5.4).
3. A `GateReview` component renders `gate_context`: the stage, `blocked`, the
   findings grouped by severity through the *existing* `severityLabel`
   (`domain/project/course.ts:113`), citations, the unimplemented-check warning
   that `Findings.tsx` already words well, `findings_artifact` as a link, and
   `artifact_paths` as links — **guarded for empty**, because the hand-driven
   tool path passes no paths and the files genuinely are not there yet
   (`gate_context`'s own docstring says so, and S-§13.5 flags it).
4. `Approvals` moves to a shell-level bar. The component does not change; its
   three existing call sites (session view, worker drawer, and the course page
   through the drawer) become one, and `AutonomyAllowAll` moves beside it.

**What it costs.** Zero new requests: the fields are on the wire, and the
approvals feed already seeds new listeners with pending approvals
(`approvals.py:137`) so a browser connecting a moment after a call was gated
still sees it. One new listener on the existing single `EventSource` — a
shell-level subscription to `approvalRequested`/`approvalSettled` *not* scoped
by session, which is the only genuinely new plumbing.

**What it buys.** C-G4, C-G5 (half), C-P2, C-P3, S-D19, S-D20, S-§12.2,
S-§12.3, S-§12.4, S-§13.1, S-§13.2, S-§14.7, S-§14.8, S-§14.9, R-§8.7. It gives
`StageAdvanced.decision` (C-G6) its first consumer, several merges after it was
added with "Nothing reads it yet" in its docstring. And it settles the question
`gate_context`'s docstring deliberately left open — "what a UI shows and how it
groups it is a decision nobody has enough use to make yet" — which is now false,
because two independent indexers found the gap from opposite directions and that
is enough use.

**It also ships the first tests in `presentation/session/`,** which today has
exactly one test file for twelve components (S-D23). That is not incidental: a
new component in the densest, least-covered directory is the cheapest place to
start paying that down, and every increment after this one needs the net.

**Why it is the right first thing rather than the easiest.** It is the one
change that is true under *every* version of this proposal and under no version
of it — if the merge in §3 is rejected entirely, the decision bar is still
right, because "an approval must reach a person regardless of which page they
are on" does not depend on how many pages there are.

---

## 10. What I am not proposing

- **A route to `StageRunner`.** C-G1. `composition.py:230-234` argues it should
  be built after a human has driven a preset by hand, and it is right. §4.3
  reserves the seat instead.
- **`send_back`, `halt` or `amend_upstream` as answerable decisions.** §5.4.
  Three of five `Decision` values cannot be written to the log, and
  `workflow-engine.md` §3.4 reserves the fix for a separate document. Offering
  them would be C-G5's bug with better graphics.
- **Any new event, field or aggregate.** §5.5.
- **Concurrent sessions in a project.** `topic-dispatch.md` §2(a) is right that
  this discards the property the whole filesystem design rests on.
- **Fixing the prompt library, or implying it is fixed.** C-G2, C-G3.
  `hybrid.default` is the default preset and has the worst prompt coverage; a
  console that looked finished over that would be the most expensive kind of
  misleading. If anything, the stage rail should be *more* honest about it.
- **A per-dispatch cancel.** R-§9.8 needs a server route, and
  `topic-dispatch.md` §5 argues a per-row control offers an action the server
  cannot honour.
- **Resolving provenance spans.** C-P12. C-F61 is right: whether a span still
  says what it said is a check's question, and answering it in the row costs a
  document read per row.
- **Bulk operations, archive, or multi-select.** §4.1. One operator, dozens of
  projects.
- **A new design system or dependency.** `Button`, `Chip`, `EmptyState`,
  `ErrorBox`, `Loading`, `Disclosure`, `Drawer` and `Confirm` cover everything
  here except the QUEUE's heterogeneous row, which is a `Disclosure` with
  different chrome.
- **Multi-user affordances.** There is no authentication, the server binds
  `127.0.0.1`, and `landing-page.md` §8 answer 4 settled that "held by 3f2a…"
  stays informational. Everything above assumes one person and would be wrong
  for a hosted build.
- **Renaming `gate_decision`.** `stage-boundaries.md` §9 open question 4 is
  right that it is a stored-shape change worth doing only alongside something
  else.

---

## 11. Open questions, and the argument against this

### The strongest argument against this proposal

**It merges two pages into the densest page in the console, and that page has
one test file.**

`presentation/session/` contains `use-panes.test.tsx` and nothing else — no test
for `SessionView`, `Timeline`, `ScrubBar`, `Composer`, `Conversation`,
`Segments`, `Compaction`, `Approvals`, `FileList`, `FileView`, `FileHistory` or
`ActivityFeed`. `session-store.test.ts` covers the state machine well and
nothing covers what is drawn from it. The session report's own conclusion is the
one to answer: **"Any redesign here is a redesign without a net."**

And this repository's record on exactly this class of change is bad, twice over,
both recorded in `landing-page.md` §8. A virtualizer keyed by array index left a
122px hole at three projects. A read-model column that every test and every
fresh database was happy with answered 500 on the only database anybody had.
Both were layout-and-data restructures of the kind §3 proposes, both passed the
suite, and both were found by a person using the product.

I do not have a rebuttal that makes the risk go away. The three things that
reduce it are: §9 ships alone and touches none of it; `use-panes.ts` is promoted
rather than rewritten, so the subtlest existing behaviour moves as code and not
as a description; and the test debt is priced as a prerequisite in §6.4 rather
than as a follow-up. If the owner reads that as insufficient, the honest smaller
version of this document is §9 plus §3.4 plus the linkable-navigation fixes in
§4.1, and the merge waits until `presentation/session/` has a net.

### The second argument against it

**The holder loop is a server concept and a user may not have it.** A person
thinks "I want to look at my course", not "I want to see what is queued against
this project's sequential resource". Organising the UI around the domain model
risks making the console teach the model before it does anything useful.

The counter, which I believe but cannot test: the model already leaks
everywhere. `held by 3f2a…`, `free`, `not held`, take-over confirmations,
"the holding session has a turn running; cancel it first", `Join`. A user of
this console has already met the constraint several times; they have just never
been shown the thing it constrains.

### Open questions for the owner

1. **Is the merge worth it before there are tests?** §11. This is the one I
   could not resolve and the most expensive to get wrong. Everything else here
   is contingent on it.
2. **Does the picker still deserve a page?** If the realistic ceiling is a dozen
   projects, `#/` could be a shell-level project switcher and the console could
   have exactly one page. That is a cleaner answer and I do not know whether it
   is a smaller one — `landing-page.md` §7 question 3 had the same shape and the
   answer that removed a region turned out to be right.
3. **Should QUEUE rank across row kinds, or group by kind?** One ranked list is
   the argument in §1; a grouped list is easier to reason about and reproduces
   four lists in one pane. I take the ranked arm and it is the part of §3.3 I am
   least sure of, because there is no evidence about which one a real queue of
   forty topics and fifteen stages reads better.
4. **Does the timeline/conversation merge belong in this proposal at all?**
   S-§14.15 calls it the largest missed affordance and §6.4 prices it as a
   rewrite. It is separable, and it may deserve its own document rather than a
   row in this one's cost table.
5. **Is `GET /api/capabilities` one route or a slippery slope?** §6.3 argues it
   replaces four distinct failure-detection hacks. The counter is that every
   capability it names is a thing the composition root can already answer by
   being wired, and a map that drifts from the wiring would be worse than a
   regex over an error message that at least comes from the code that failed.
