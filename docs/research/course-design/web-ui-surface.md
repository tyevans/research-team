# The web UI surface, and what staged course-design workflows would need from it

Read out of the working tree at `research_team/interfaces/web/` and `research_team/application/` on
branch `main`. Line numbers are as of the current checkout; treat them as pointers, not contracts.

---

## 1. What the web UI is today

### 1.1 Shape

`create_app(service, feed, turns, lifespan=None, approvals=None, activity=None)`
(`research_team/interfaces/web/app.py:85`) builds a FastAPI app around an already-wired
`SessionService`. Composition stays outside — the app is handed its dependencies and never constructs
one. It is **stateless by construction**: every route names the session it acts on, so any number of
browsers can look at any number of sessions (`app.py:1-6`).

Static files are mounted at `/static` and `/` returns `static/index.html` (`app.py:507-512`), guarded by
`STATIC_DIR.is_dir()`.

### 1.2 Routes

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| GET | `/api/sessions` | `list_sessions` `:109` | from the summaries projection |
| POST | `/api/sessions` | `create_session` `:113` | body `NewSession{system_prompt?}` |
| GET | `/api/projects` | `list_projects` `:118` | folds `project_state` per row |
| POST | `/api/projects` | `create_project` `:134` | body `NewProject{name}`; name collision → 409 |
| POST | `/api/sessions/{id}/release` | `release_session` `:157` | advances the project tip; 409 if a turn runs |
| POST | `/api/projects/{id}/join` | `join_project` `:186` | body `JoinOptions{take_over=False}` |
| GET | `/api/health` | `health` `:240` | projection trustworthiness |
| POST | `/api/summaries/rebuild` | `rebuild_summaries` `:258` | |
| GET | `/api/tree` | `fork_tree` `:271` | |
| GET | `/api/sessions/{id}` | `get_session` `:275` | full `session_view` |
| GET | `/api/sessions/{id}/events` | `get_events` `:292` | timeline rows |
| GET | `/api/sessions/{id}/at/{at}` | `get_session_at` `:297` | time travel; folds, never writes |
| GET | `/api/sessions/{id}/files?path=&at=` | `get_file` `:306` | reads deleted files at a past `at` |
| GET | `/api/sessions/{id}/files/history?path=` | `get_file_history` `:326` | |
| POST | `/api/sessions/{id}/turns` | `run_turn` `:331` | body `NewTurn{input}` |
| POST | `/api/sessions/{id}/turns/cancel` | `cancel_turn` `:400` | |
| GET | `/api/sessions/{id}/turns/current` | `current_turn` `:414` | |
| GET | `/api/sessions/{id}/turns/current/activity` | `current_activity` `:433` | mid-turn catch-up |
| GET | `/api/sessions/{id}/approvals` | `pending_approvals` `:451` | mid-turn catch-up |
| POST | `/api/sessions/{id}/approvals/{approval_id}` | `decide_approval` `:461` | body `Decision{type, edited_args?, message?}` |
| POST | `/api/sessions/{id}/forks` | `fork_session` `:483` | body `NewFork{at}` |
| GET | `/api/stream` | `stream` `:491` | SSE |

Request models are Pydantic classes at `app.py:55-82` — `NewSession`, `NewTurn`, `NewFork`,
`NewProject`, `JoinOptions`, `Decision`. Any new endpoint should follow that convention.

### 1.3 The SSE stream — three channels, one connection

`_sse` (`app.py:517-613`) multiplexes **three** producers onto a single `text/event-stream`:

1. **Log events** — `LiveFeed.follow(from_position=...)` (`application/live_feed.py:33`), drained by a
   `pump()` task. These are the only frames that carry an SSE `id:`, which is the encoded feed position
   *following* the event. Serialized by `feed_event(session_id, event, index)`
   (`presenters.py:225`), which returns the same shape as a timeline row so a live-appended event
   renders identically to a fetched one.
2. **Approval frames** — `WebApprovals.listen()` (`approvals.py:116`), types `ApprovalRequested` /
   `ApprovalSettled`.
3. **Activity frames** — `TurnActivity.listen()` (`activity.py:88`), type `TurnActivity`.

Channels 2 and 3 carry **no `id:`**, deliberately: they are not log entries, so `Last-Event-ID` cannot
replay them. A reconnecting browser refetches via `/approvals` and `/turns/current/activity` instead.
The docstring at `app.py:536-544` argues the case for one connection rather than three: a second channel
per concern multiplies the ways a tab can be half-connected, and the moment that matters most is exactly
when a turn is halted or streaming.

Keepalive comments every `KEEPALIVE_SECONDS = 15.0` (`app.py:49`); disconnect polled every
`DISCONNECT_CHECK = 0.5` (`app.py:51`).

**This is the single most important extension point for workflows.** A new frame type rides this
connection by adding one producer task and one `queue.put` — no new endpoint, no new EventSource, no
change to reconnect semantics.

### 1.4 Activity accumulation and message ids

`TurnActivity` (`activity.py:38`) holds two dicts keyed by session: `_running` and `_discarded`, each
mapping `message_id -> entry`.

`_record` (`activity.py:107`) is where the accumulation happens, and the split matters:

- An `ActivityMessage` (whole message) **replaces** whatever is under that `message_id` — the whole
  message is what the log will record, so it wins over the deltas that preceded it.
- An `ActivityDelta` **appends** to `entry["text"]`.

So **the server accumulates; each broadcast frame carries the full prose so far, not an increment.**
The browser's `putActivity` (`static/app.js:2682`) therefore just overwrites by `message_id` and keeps an
`order` array for stable rendering — no client-side concatenation. This is why a dropped frame is
recoverable and why the catch-up route can return the running buffer verbatim.

`begin` / `settle` bracket the buffer (`activity.py:48`, `:61`). A committed turn's provisional copy is
**dropped** (the log is authoritative); a failed or cancelled turn's copy moves to `_discarded` and the
UI offers it as explicitly thrown away. `run_turn` drives both (`app.py:355-392`), including the subtle
no-settle path when two requests race (`app.py:361-364`).

### 1.5 Approvals

`WebApprovals` (`approvals.py:57`) implements `ApprovalPort`. `decide()` (`:66`) parks the request as an
`asyncio.Future`, announces `ApprovalRequested` on the feed, awaits, and in a `finally` forgets the row
and announces `ApprovalSettled` — reached on cancellation too, which is the point.

`PendingApproval.view()` (`approvals.py:37`) is the wire shape:

```json
{"id", "session_id", "tool_name", "args", "description", "allowed_decisions"}
```

`listen()` is **seeded** with everything already parked (`approvals.py:124-129`), unlike the activity
feed, because a browser connecting a moment after a call was gated would otherwise see nothing.

Client side: `renderApproval` (`app.js:2137`) draws a card with the tool name, description, a JSON dump
of `args`, and exactly **two buttons — Approve and Reject** (`app.js:2160-2178`). Note that
`allowed_decisions` includes `edit` (`infrastructure/agent/approval.py:14`) but the browser renders no
edit affordance; that capability exists on the port and in the API and is simply unexposed.

### 1.6 Projects

Listed by `list_projects` (`app.py:118`), one row per `project_view(...)`
(`presenters.py:203`): `{id, name, active_session_id, tip_at_event}`. The holder is in the row because it
decides what the row can offer (`presenters.py:210-215`).

`renderProjects` (`app.js:816`) renders a held project with **Resume** / **New session** and a free one
with **Open**. Joining goes through `POST /api/projects/{id}/join`, which calls
`SessionService.start_in_project` — the same use case as the REPL's `/project use` — so joining is
decided in exactly one place, the `Project` aggregate (`app.py:190-193`).

Two facts that matter for workflow placement:

- **A project is sequential.** `ProjectState` (`domain/project.py:66`) has `active_session_id`,
  `tip_session_id`, `tip_at_event`. Exactly one session holds it; `release_project` advances the tip,
  and that is the *only* way work reaches the next session (`app.py:159-167`).
- **Joining inherits by forking.** `start_in_project` (`session_service.py:251`) forks from the
  project's stored tip so the filesystem folds out of one stream. **Only files come across; the
  conversation does not.**

Attachment is process-wide and last-join-wins — a documented, accepted limitation for a local
single-user tool (`app.py:196-207`).

### 1.7 Files and time travel

`session_view` (`presenters.py:114`) returns `files: [{path, size, revisions}]` sorted by path, where
`revisions` is a count of file events touching that path up to the scrub point (`_revision_counts`,
`:106`).

Scrubbing: `state.at` is `null` for HEAD or a 1-based event index. `selectEvent` → `loadSnapshot`
(`app.js:1328`, `:1343`) fetches `/at/{n}`; `view()` (`app.js:1381`) returns snapshot-or-head so every
renderer is scrub-agnostic. `renderWorkspace` (`app.js:1689`) draws the file list;
`renderFileView` (`app.js:1819`) draws contents with a `contents` / `history` tab pair and, for markdown
paths, a `rendered` / `source` toggle. `file_history` (`presenters.py:160`) returns every event that
touched a path including the recorded edit intent (`old_string` / `new_string` / `replace_all`), and
`renderDiff` (`app.js:221`) renders it with `DIFF_CONTEXT = 3`.

There is a hand-rolled markdown renderer at `app.js:284-468` (headings, lists, tables, code, inline
spans, links). It is not a library and has no dependency.

---

## 2. Client architecture

**Vanilla JavaScript, no framework, no build step, no dependencies.** Verified: there is no
`package.json` anywhere in the repo; `index.html` loads a single `<script src="/static/app.js">`
(`index.html:122`); `app.js` contains **zero** `import`/`export` statements and **zero** arrow
functions — it is deliberately written in a conservative `function`-declaration style with `const`/`let`.
2,795 lines, one file.

Structure:

- **`h(tag, attrs, children)`** (`app.js:17`) — a tiny hyperscript helper. Everything is built with it;
  there is no template string HTML and no `innerHTML` (which is also the XSS story).
- **Templates in HTML.** `index.html` holds `<template id="tpl-tree-view">` and `tpl-session-view`, kept
  there "so structure is inspectable" (`index.html:40`). `tpl(id)` clones one, `slot(root, name)` finds
  a `[data-slot="..."]`.
- **One global `state` object** (`app.js:503-546`) with ~35 documented fields — route, tree, session
  head, events, scrub position, open file, turn/cancel flags, `approvals`, `activity: {order, byId}`,
  `discarded`.
- **Render functions read `state` and rebuild their slot.** `clear(node)` then append. There is no
  diffing, no reactivity, no observer. Each renderer is idempotent and cheap because each owns a small
  subtree.
- **Routing** is hash-based: `parseHash` / `go` / `onRoute` (`app.js:581-658`), two routes — the tree
  view and `#/s/{session_id}`.
- **Mounting** caches slots once: `mountSessionView` (`app.js:950`) builds `sessionEls` with 15 named
  slot references and wires the composer's submit / Ctrl+Enter handlers.
- **SSE** is a single `EventSource` with manual reconnect and backoff (`connect` `:2479`,
  `scheduleReconnect` `:2540`, `backoff` `:2422`), and `onStreamEvent` (`:2546`) dispatches on
  `payload.type` — approval frames first, then `TurnActivity`, then log events.
- **Panes** are collapsible and sticky in `localStorage` under `rt.collapsedPanes` (`app.js:992`).

**What a new panel actually costs.** Concretely, for a stage-progress panel:

1. A `<section class="pane" data-pane="stages">` in `tpl-session-view`, plus a `data-slot`.
2. One line in the `sessionEls` map in `mountSessionView`.
3. A `renderStages()` function that clears its slot and rebuilds from `state`.
4. A few `state` fields.
5. A branch in `onStreamEvent` for a new frame type, calling `renderStages()`.
6. CSS in `style.css` (1,181 lines, hand-written, CSS custom properties, light/dark via
   `data-theme`).

That is genuinely on the order of 150-250 lines across four files, with no toolchain.

**Does this codebase want a build step? No — and it should not get one for this.** The no-build property
is load-bearing here: the app is a local single-user tool served by the same FastAPI process, `python -m`
and a browser is the entire dev loop, and there is no CI step that would build assets. Introducing Vite +
a framework to add a stage panel would cost more than every UI change the workflow feature needs put
together. The honest caveat is that `app.js` is already 2,795 lines in one file, and the workflow work
will add several hundred more; if it starts to hurt, **split into several `<script>` files sharing the
same globals** before reaching for a bundler. That is a change of file layout, not of technology.

---

## 3. Workflow selection UX

### The options

**At session creation** (`POST /api/sessions` with `NewSession`). Cheapest — the field already exists
alongside `system_prompt`. But a session is a conversation, and a Backward Design run over a real
research corpus will not fit in one. Bind the workflow here and every continuation session has to
re-declare it, with nothing stopping two sessions in the same project from declaring different ones.

**At project creation** (`POST /api/projects` with `NewProject`). A project is the thing that persists
across sessions, holds the filesystem lineage, and is joined sequentially. That matches a workflow run's
lifetime almost exactly. The cost is rigidity: a project would be committed to a methodology before any
research exists, and you cannot run ADDIE over a corpus you gathered under a project created for
Backward Design without making a new project.

**As a mid-session command.** Maximum flexibility, worst durability story — and it collides directly with
the finding from the deepagents report that LangGraph state does not survive a turn, so "the workflow I
picked" would have to become an event anyway.

### Recommendation: bind the workflow to the **project**, but set it as an explicit event, not at creation

Create projects as they are created today. Add a separate, idempotent-ish `set workflow` action that
records a domain event on the `Project` aggregate. This gets the right lifetime (a workflow run spans
sessions, exactly as a project does) without forcing the choice before there is anything to run it
against, and it puts the fact on the log where the stage machinery already has to read from.

Sessions inherit it. `start_in_project` already forks the filesystem from the tip; the workflow name and
current stage index come from the project's folded state and are used to build the `StageMiddleware`
per turn — which is precisely the reconstruction path the deepagents report established is required.

API surface, following the existing conventions:

```python
# ILLUSTRATIVE — app.py, alongside NewProject / JoinOptions

class WorkflowChoice(BaseModel):
    """Which instructional-design methodology this project runs."""
    workflow: str            # "backward-design" | "addie" | "tyler"

@app.get("/api/workflows")
async def list_workflows():
    """The selectable methodologies and their stages. Static; no session needed."""
    return [
        {"name": "backward-design", "label": "Backward Design (UbD)",
         "stages": [{"key": "desired-results", "label": "Desired results",
                     "artifact": "/course/01-desired-results.md"}, ...]},
        ...
    ]

@app.post("/api/projects/{project_id}/workflow")
async def set_workflow(project_id: UUID, body: WorkflowChoice):
    """Choose the methodology. 409 once a stage has been completed."""
    ...

@app.get("/api/projects/{project_id}/workflow")
async def get_workflow(project_id: UUID):
    """Chosen workflow, current stage, and per-stage status/artifact."""
    ...
```

`project_view` (`presenters.py:203`) gains `workflow` and `stage` so the project list can show
"Backward Design · Stage 2/3" without a second request — the same argument the docstring already makes
for `active_session_id` being in the row.

`NewProject` optionally gains `workflow: str | None = None` as a convenience for "create and choose in
one click", but the authoritative path stays the separate endpoint.

**Changing methodology mid-run should be refused with a 409**, not silently allowed. Stage artifacts
produced under one methodology are not stage artifacts of another, and a UI that lets you switch is
promising a migration nobody is going to write. The escape hatch already exists and is idiomatic here:
fork, or create a new project.

**UNVERIFIED**: whether `Project` currently tolerates a new event type without a projection rebuild. The
`Project` aggregate is a `DeciderAggregate` (`domain/project.py:154`) so adding a command/event pair is
routine, but `/api/health` and `rebuild_summaries` exist because projections *can* go stale — check
whether the summaries projection needs to learn the new event or can ignore it.

---

## 4. Stage progress display

### What to show

A stage rail: "Stage 2 of 5 — Evidence", each stage as `done` / `current` / `blocked`, each done stage
linking to its artifact path (which opens in the existing workspace pane), and the blocked ones saying
*why* ("needs Stage 1 approved").

### Where the data comes from

Two sources, and they should stay separate for the same reason log frames and activity frames are
separate today:

1. **Durable stage state** — folded from the project's events (`WorkflowChosen`, `StageAdvanced`,
   or whatever the domain settles on). Served by `GET /api/projects/{id}/workflow` and refetched on
   the frames below. This is authoritative.
2. **Live stage transitions** — a new SSE frame so the rail moves without a poll.

### New SSE frame

Stage transitions **are** log events (that is the whole point of routing them through the aggregate), so
unlike approvals and activity they *do* carry a feed position and ride channel 1 for free. A
`StageAdvanced` event will already arrive at `onStreamEvent` as an ordinary timeline row via
`feed_event`. The client change is a branch that also refreshes the stage rail:

```js
// ILLUSTRATIVE — app.js, inside onStreamEvent after the existing event push
if (payload.type === 'StageAdvanced' || payload.type === 'WorkflowChosen') {
  loadWorkflow();   // GET /api/projects/{id}/workflow, then renderStages()
}
```

That is the cheapest correct design: no new channel, no new catch-up route, replay-safe via
`Last-Event-ID`, and it reuses `event_summary` (`presenters.py:30`) for the timeline row by adding one
`isinstance` branch.

A **provisional** "entering stage 2" note *before* the event commits would have to ride the activity
channel and be treated as discardable — worth having only if stages turn out to be long enough that the
rail feels frozen. Defer it.

### Projection: its own, not `summaries`

The existing summaries projection (`SessionSummaryRunner`) is per-session and exists to make
`/api/sessions` follow the log; it is already the thing `/api/health` warns about going stale
(`app.py:240-256`). Workflow state is **per-project**, has different keys and a different consistency
requirement, and — critically — can be answered by **folding the `Project` aggregate directly**, exactly
as `project_state` already does (`session_service.py:175`). A project has few events; there is no
performance case for a projection.

**Recommendation: fold, don't project.** `GET /api/projects/{id}/workflow` loads the aggregate and
returns its state, the same shape `list_projects` already uses per row. No new eventual-consistency
surface, nothing new for `/api/health` to have to vouch for.

---

## 5. The gate review UI

This is the section where the honest answer is *no*.

### What the existing machinery gives for free

- **Blocking a turn on a human.** `WebApprovals.decide` parks a future and the turn genuinely waits
  (`approvals.py:66`). That is real, it is tested, and it is the hard part.
- **Announce + catch-up.** `ApprovalRequested` on the feed, seeded `listen()`, and `GET /approvals` for a
  tab that arrived late.
- **Cancellation safety.** The `finally` at `approvals.py:76-87` frees the row whether the human answered
  or the turn was cancelled underneath them.
- **Recording the decision.** `DeepAgentTurnExecutor._decide` / `_apply`
  (`infrastructure/agent/deep_agent.py`) writes a `RecordToolDecision` event for every outcome, including
  policy-refused ones.
- **Four decision types already modelled.** `ApprovalDecision{type, edited_args, message}`
  (`application/ports.py`) supports `approve` / `edit` / `reject` / `respond`, and the executor maps all
  of them to langchain's resume vocabulary.

Map that onto what a gate needs:

| Gate action | Existing decision type | Fit |
| --- | --- | --- |
| Approve | `approve` | exact |
| Approve with edits | `edit` (`edited_args`) | **poor — see below** |
| Send back with notes | `reject` + `message` | good |
| Halt the run | — | **missing** |

### Where it runs out

1. **`edited_args` is the wrong shape for artifact edits.** `edit` replaces a *tool call's arguments*.
   A reviewer approving Stage 1 with edits is editing a **markdown artifact in the filesystem**, possibly
   thousands of words, not a JSON arg dict. Shoehorning a document into `edited_args` would (a) make the
   edit invisible to the file-history view, which is the one place edits are supposed to be auditable,
   and (b) round-trip a document through an approval payload for no reason. The right primitive already
   exists: **let the reviewer edit the file**, which produces a `FileEdited` event with recorded intent,
   and *then* approve. The gate decision stays small.
2. **The card has no room for what a reviewer must read.** `renderApproval` (`app.js:2137`) is a tool
   name, a description, and `safeJson(args)` in a strip at the bottom of the conversation pane
   (`index.html:106`). A gate reviewer needs to read a full artifact, see a critic's findings, and see a
   cut list. That is a view, not a card.
3. **No `halt`.** Nothing in the current vocabulary means "stop the whole workflow run", as distinct from
   "reject this call". `reject` returns a message to the model, which will carry on.
4. **`ApprovalRequest` carries no artifact references.** Its fields are
   `session_id, tool_name, args, description, allowed_decisions` — no place for artifact paths, critic
   findings, or a rejected-items list.
5. **The browser exposes only Approve and Reject** (`app.js:2160-2178`). Even `edit`, which the port and
   API already support, has no affordance.

### Recommendation: reuse the mechanism, replace the presentation

Do **not** build a parallel blocking path. The park-announce-resolve machinery is the expensive,
correct, tested part, and a second one would double the ways a turn can hang.

Do extend it in three narrow places:

1. **Widen `ApprovalRequest` with an optional structured payload.** One added field — call it
   `context: dict | None` — carrying `{artifact_paths, findings, cut_list, stage}` for a gate request and
   `None` for every ordinary tool gate. `PendingApproval.view()` passes it through. Everything that does
   not understand it ignores it. This is additive and does not disturb the existing gating path.
2. **Add `halt` to the decision vocabulary**, and map it in `_apply` to a reject *plus* a domain event
   that marks the run stopped. Note the deliberate absence of `respond` from `ALLOWED_DECISIONS`
   (`infrastructure/agent/approval.py:14`) — answering on a tool's behalf invents a result. `halt` does
   not have that problem: it records a real human decision.
3. **Render gate approvals in a different component.** Branch on the presence of `context` in
   `renderApprovals` (`app.js:2128`): ordinary tool gates keep today's card; a gate request renders a
   review panel that can occupy the workspace pane, show the artifact via the existing file viewer, list
   findings, and offer four buttons. Same `POST /api/sessions/{id}/approvals/{approval_id}`, same
   `Decision` body plus the new type.

**The one thing that genuinely does not fit and should not be forced:** a gate review that a human wants
to leave and come back to tomorrow. The current approval is an in-memory `asyncio.Future` inside a
running turn — process restart loses it, and the turn is holding an open model session while the human
reads. For a gate meant to be answered in minutes, that is fine and matches the existing design. For a
gate meant to be answered across days, the turn must **end** at the stage boundary and a *new* turn
resume after approval, with the pending-gate state on the log. That is a different mechanism, and it is
worth being explicit in the spec about which kind of gate is being built. **Recommendation: build the
in-turn gate first** (it reuses everything), and treat durable cross-session gates as a later,
separately-specified feature.

---

## 6. Artifact browsing

### What exists

- A flat, path-sorted file list with size and revision count (`presenters.py:148-155`,
  `renderWorkspace` `app.js:1689`).
- Contents at HEAD or any scrub point, including files deleted since (`get_file` `app.py:306`).
- Full per-path history with recorded edit intent and a 3-line-context diff renderer
  (`file_history` `presenters.py:160`, `renderDiff` `app.js:221`).
- Markdown rendering with a rendered/source toggle (`app.js:284`, `renderModeButton` `:1925`).
- Keyboard navigation of the file list (`onFilesKey` `app.js:1746`).

For reading a generated course artifact, **this is already good** — a markdown file at
`/course/01-desired-results.md` renders, diffs, and scrubs with no new code at all.

### What is missing

1. **No grouping or ordering beyond alphabetical.** `sorted(state.files.items())`. Naming artifacts
   `01-`, `02-` makes lexical order match stage order — a convention, and cheap, and it should be adopted
   for exactly this reason. But research inputs, drafts, and final artifacts will interleave in one flat
   list. A `data-slot` group header keyed by path prefix (`/course/`, `/research/`, `/drafts/`) is the
   minimum useful change.
2. **No typed artifacts.** Everything is `{path, size, revisions}`. If stage subagents use
   deepagents' `response_format` to return typed structures, the type is not in the file list and the
   viewer has only markdown-or-plaintext. Storing typed artifacts as JSON *next to* the markdown and
   rendering them with a schema-aware view is a real addition, not a tweak.
3. **No provenance links.** Nothing connects "this learning objective" to "the research document it came
   from". The event log has the raw material — `FileWritten` carries the turn index, and the knowledge
   graph has `source_id`s — but there is no join and no UI. This is the largest genuinely new piece of
   work in the artifact story.
4. **No alignment matrices.** An objectives × assessments × activities grid is a cross-artifact view.
   Nothing in the current UI renders anything that is not a single file. Realistically this is either a
   generated markdown table (free — the markdown renderer already does tables, `splitTableRow`
   `app.js:370`) or a bespoke component. **Generate it as a markdown table first**; it costs nothing and
   answers the question.
5. **No diff between two arbitrary revisions.** History shows each revision's diff against its
   predecessor; comparing r1 to r5 directly is not offered.

---

## 7. Incremental build order

**Step 1 — the smallest thing that makes workflows usable.** No new UI components at all:

- `GET /api/workflows` (static list) and `POST /api/projects/{id}/workflow`.
- A workflow `<select>` next to the existing `#project-name` input in `tpl-tree-view`
  (`index.html:62`).
- `workflow` and `stage` in `project_view`, shown as a chip in the project row beside the existing
  `held` / `free` chip (`app.js:816-870`).
- Stage artifacts written to `/course/NN-*.md`, which the existing file viewer already renders.
- Stage transitions as domain events, which the existing timeline already displays once
  `event_summary` (`presenters.py:30`) learns one `isinstance` branch.

At this point a user can pick a methodology, run it, watch stages land in the event log, and read the
artifacts. **No new panel, no new SSE frame, no new approval path.**

**Step 2 — visible stage progress.** The stage rail: new pane in `tpl-session-view`, one `sessionEls`
entry, `renderStages()`, `loadWorkflow()` triggered from `onStreamEvent`. Roughly the 150-250 lines
estimated in §2.

**Step 3 — the gate review UI.** `context` on `ApprovalRequest`, `halt` in the decision vocabulary, and
the branch in `renderApprovals` that renders a review panel instead of a card. Build this only after
Step 1 has shown what a reviewer actually needs to see — the field list for `context` is a guess until
then, and getting it wrong is expensive because it crosses the port boundary.

**Deferrable, in order of decreasing regret:**

- Provenance links (§6.3) — real value, real work, and nothing else blocks on it.
- Typed artifact views (§6.2) — only matters if stage subagents actually use `response_format`.
- Alignment matrices as a component — generate markdown tables instead and see if that suffices.
- Provisional pre-commit stage notes on the activity channel (§4).
- Durable cross-session gates (§5) — a separate mechanism; do not let it creep into Step 3.
- Arbitrary revision-to-revision diffs (§6.5).

**Flagged UNVERIFIED throughout**: whether adding a `Project` event type requires touching the summaries
projection; whether `event_summary`'s fallback branches (`presenters.py:56-64`) render a new event type
acceptably before a dedicated branch is added; and the exact field list for the gate `context` payload,
which cannot be settled until a real stage output exists to review.
