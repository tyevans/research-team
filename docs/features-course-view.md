# The course view, indexed exhaustively

Read out of a clean worktree at `origin/main` = `5a5a7cf` ("Move what-is-running
into the nav bar", #86). Line numbers are pointers, not contracts.

Scope: everything the course page (`#/p/<projectId>/course`) presents, plus the
machinery behind it — the stage rail, the artifact list, the worker roster and
drawer, the autonomy surfaces, the run panel, the extraction pane, the
lesson/widget renderers its artifacts reach, and the backend that serves all of
it.

**Three categories are kept strictly apart throughout, because on this page they
are genuinely different and easily confused:**

- **Built and reachable** — a user can get to it from the UI today.
- **Built but unreachable** — the code exists, is tested, and no control, route
  or gesture leads to it. Sub-divide again: *deliberately deferred* (a docstring
  says why) vs *dropped on the floor* (nobody noticed).
- **Designed but unbuilt** — a design doc or a data field describes it and no
  implementation exists.

Where I could not settle a question by reading code, I say so (§7).

**Correction to the commissioning brief:** there is no
`research_team/workflows/stage_exit.py`. Stage-exit logic is
`research_team/application/stage_exit.py` (506 lines). `workflows/` contains only
`addie.py`, `hybrid.py`, `ubd.py`, `__init__.py`.

---

## 0. How a user reaches this page

| Route | Where |
| --- | --- |
| `#/p/<projectId>/course` | `frontend/src/presentation/routing/routes.ts:78-84` |
| `#/p/<projectId>/course/watching/<sessionId>` | same, `watching` segment |

`courseHref()` (`routes.ts:122`) builds both. The `watching` segment is a
**linkable drawer state**: a reload keeps the worker drawer open, and the URL can
be sent to somebody else. A truncated `.../watching` with no id after it still
parses as a course route with the drawer closed, deliberately.

Entry points found in the tree: the project list on home, and the breadcrumb.
Exits: the `Research` button, `Open holding session`, every artifact link, every
provenance-span link, and the run's session link.

---

## 1. Feature inventory

Numbered so a synthesiser can reference them. **66 distinct features.**

### 1.1 Page frame

**F1 — Preset name as the page title.** Renders `course.preset.name`, falling
back to the literal `Course` before the query resolves or when it fails.
*Where:* `CourseView.tsx:63`. *Depends on:* `GET /api/projects/{id}/course`.
*States:* pending → `"Course"`; loaded → preset name; error → still `"Course"` —
the heading does not change on error, only the body below it.

**F2 — Position subtitle.** `Stage N of M · <presetId> v<version>`.
*Where:* `CourseView.tsx:227-232`. *States:* when `position` is `null` — the
project's recorded stage id is not one the installed preset contains — it says so
in a full sentence rather than showing a wrong number. A real state:
`composition.py` tolerates a preset version mismatch and runs under what is
installed, so a project can sit at a stage id the current build has dropped.

**F3 — "Research" link.** `CourseView.tsx:67-69`. Always present, even when the
course 409s.

**F4 — "Open holding session" link.** Only when `course.holdingSessionId` is
non-null (`CourseView.tsx:70-74`). A project nobody has joined shows no link and
no explanation — see D2.

### 1.2 Worker roster ("Working now")

**F5 — Live roster of everything working on this project.** Rows for workers of
kind `run`, `turn`, `extraction`, `dispatch`, `stage`.
*Where:* `presentation/course/Workers.tsx`; model `domain/worker/worker.ts`.
*Depends on:* `GET /api/projects/{id}/workers`, **polled every 2000 ms**
(`Workers.tsx:10`). Not pushed — the roster is process-local server state, and
pushing it would mean making the session-keyed activity buffer project-aware.
*States:*
- *loading* → nothing until the first response.
- *empty + healthy* → "Nothing is running on this project." plus "N session(s)
  attached and quiet." or "No sessions are attached."
- *error, no prior data* → "Could not read what is running on this project. This
  build may not expose the roster." (the server 404s here rather than returning
  an empty list — a different claim, deliberately).
- *error, prior data* → keeps the last roster, adds a `stale` chip. Called out in
  the file as the one rule the component must not break.
- *stale and the last roster was empty* → refuses to say "nothing is running";
  says "As of the last roster that arrived, nothing was running."

**F6 — Running count chip.** `N running` when busy, `idle` otherwise
(`Workers.tsx:61-68`).

**F7 — Worker nesting.** A worker naming a `parent` present in the roster renders
indented under it. Orphans stay top-level (a parent can vanish between the poll
that named it and this render, and a dropped child would hide live work); a
self-parenting worker cannot make a cycle. *Where:* `nest()`, `worker.ts:49`.

**F8 — Open a worker's transcript.** A worker with a `sessionId` renders its
`detail` as an `aria-pressed` toggle that opens the worker drawer; clicking the
active one closes it. A worker without a session (extraction) renders as plain
text — deliberately not a dead button. The toggle writes `watching` into the URL,
so it is back-button-navigable. *Where:* `Workers.tsx:114-132`.

**F9 — Short session id** beside each openable row.

### 1.3 Extraction pane ("Reading into the graph")

**F10 — Live progress of a `remember` call.** Named stages in order, current one
marked `aria-current="step"`. A list rather than a percentage: the stages are not
equal in length, so any bar over them would be a made-up number.
*Where:* `ExtractionPane.tsx`; store `@application/knowledge/extraction-store.ts`.
*Depends on:* SSE frames of `kind === 'extraction'` plus
`GET /api/projects/{id}/extraction` for catch-up (which returns
`{current: [], last: []}` rather than 503 when unwired).
*States:* never run → "No extraction has run on this project yet."; running →
stage list; finished → collapsed `<details>`; failed → same with a failed tone
and the reported reason, or "No reason was reported."

**F11 — Model-call counter,** only during the `extracting` stage.

**F12 — Entity / relationship counts + domain,** only once an `extracted` stage
entry has arrived, so they are never rendered as misleading zeroes.

**F13 — Domain confidence in three outcomes, not two.** `null` → nothing said.
`0` → the words "fallback — treat the shape as unverified", explicitly so `0.00`
cannot read as a confident low score. Otherwise two decimals.
*Where:* `confidenceText`, `ExtractionPane.tsx:174`.

**F14 — Consolidation progress and merge verdicts.** `consolidating i/total` and
an append-only list of merge lines, indexed because the same verdict can
legitimately repeat.

**F15 — Reconnect recovery.** `catchUp()` on mount **and on every SSE
reconnect** — these are side-channel frames with no feed position, so
`Last-Event-ID` cannot replay them, and a socket that dropped mid-ingest would
otherwise leave the pane stopped on the last frame, which on screen is
indistinguishable from a hung extraction. *Where:* `ExtractionPane.tsx:53-56`.

**F16 — Project-scoped frame filtering.** The store discards frames addressed to
other projects; the live feed is application-wide and fanned out to every
listener.

**F17 — Silent degradation when the route is missing.** `catchUp()` errors are
swallowed to `noop` (`ExtractionPane.tsx:42`). See D4.

### 1.4 Run panel ("Autonomous research")

A run works the **project's topic queue**, not the workflow's stages. It renders
even when the project has no workflow at all — which is why it sits above the
course panes rather than inside them.

**F18 — Start a run, with an optional round cap.** Number input (`min=1`) and a
"Start a run" button. *Where:* `RunPanel.tsx:104-162`.
*Depends on:* `POST /api/projects/{id}/auto-research`.
*Cap parsing:* `parseRoundCap` (`domain/research/run.ts:152`) — an empty string is
a **valid** choice meaning "the domain's own budget"; anything that is not an
integer ≥ 1 is rejected client-side with a toast before any request.

**F19 — Feature-off state.** When the server says autonomous research is not
enabled, the whole panel is replaced by a block naming `AGENT_AUTO_RESEARCH=1`
and the reason it defaults off (nothing authenticates the port; it is the one
route that would spend an hour of model time for whoever called it).
*Where:* `RunPanel.tsx:84-93`. Detection is a **regex over the 404 message** —
see D3.

**F20 — Status chip.** `no run` / `starting` / `running` / `stopped` / `ended`.
`starting` covers both the 202 body with no fold yet and `status === 'new'`.

**F21 — Read-only chip,** with a tooltip: the run is under a policy that floors
`fetch` at `ask`, so it works from material already in hand rather than
deadlocking on an approval nobody is there to answer.

**F22 — Five counters,** each with an explanatory `title`: rounds (against cap or
`∞`), turns, findings, quiet rounds (against budget), failures. Findings are
counted by folding the topic before and after the turn, not by reading the reply
— "a round that describes a breakthrough and records nothing is an empty round".

**F23 — "working on" line.** The topic whose round is in flight, or "between
rounds — no topic claimed right now" (live) / "no topic in flight" (stopped).

**F24 — Open the run's session.** The rounds are turns on that session, so it is
where everything the agent actually said is readable.

**F25 — Stop after this round.** `POST /api/projects/{id}/auto-research/cancel`.
Deliberately does not kill the round in flight; the panel keeps saying "running"
until the poll says otherwise, and a toast says "Asked the run to stop after this
round."

**F26 — Endings in words, with a tone.** Six known stop reasons — `queue_empty`,
`max_rounds`, `budget_exhausted`, `no_new_findings`, `error_rate`, `cancelled` —
each with a label, headline and paragraph. **Only `queue_empty` earns the `done`
tone**; everything else is `short` or `bad`, so a skimmed green box cannot mean
"finished" when it isn't. An unrecognised reason falls back to the un-finished
reading. *Where:* `domain/research/run.ts:75-133`.

**F27 — "ending not seen".** If the panel saw a run live and the run then leaves
the live route without an ending, it says "It ended; this page did not see how"
rather than retracting to "no run" — which would quietly withdraw an ending
nobody read. *Where:* `ENDING_NOT_SEEN`, `run.ts:136`; `seenLive` at
`RunPanel.tsx:48` (state set during render, not a ref, so a discarded render
cannot report a run that was never shown as live).

**F28 — Adaptive polling.** 2000 ms only while live; a stopped run is not polled.

**F29 — "Start another run"** from inside the ending box, carrying the cap input.

### 1.5 Autonomy panel

**F30 — Collapsed disclosure with a level tally.** A native `<details>` starting
closed; the summary carries chips like `6 ask`, `2 auto`. Native so it gets
keyboard behaviour, screen-reader expanded state, and find-in-page opening it to
reach a match. It starts closed because open it filled the first screen with 8
tools × 3 radios before a single stage or artifact.
*Where:* `AutonomyPanel.tsx:61-73`; `levelTally`, `domain/autonomy/autonomy.ts:104`.

**F31 — One radio group per gated tool.** Rows come from the **server's** `gated`
list, never a list in the frontend, so the panel cannot silently miss a newly
gated tool (drift would show as a missing switch — a tool nobody can manage from
the web, with nothing on screen to say so). Levels offered are
`auto`/`ask`/`deny` **plus** whatever unknown level the server currently reports
for that tool, so an unfamiliar setting is visible and undoable.
*Where:* `levelsToOffer`, `autonomy.ts:86`.

**F32 — Level meaning text** per row. A tool the server named as gated but gave
no level for renders "This build was not told what level this tool is at." —
never defaulted to `ask`, which would be inventing a safety claim nobody made.

**F33 — Instance-wide scope warning,** rendered on the control (not in a
tooltip), shared verbatim with the drawer surface via `autonomy-copy.ts`. Wording
drift between the two surfaces is treated as a correctness bug: one policy object
serves every session in the process, while the audit record lands only on this
session.

**F34 — "review gate" marking.** Tools in `stageGates` get a chip and an
explanatory sentence (`STAGE_GATE_HELD`). They can be set to `auto` one
deliberate click at a time, but are never swept along by allow-all.

**F35 — Read-only mode with a reason.** With no holding session there is nothing
to record the audit against, so controls are disabled and `NO_SESSION` says why.
No write is attempted and none is fabricated (`use-autonomy.ts:100-104`).

**F36 — Unwired-policy state.** A 404 on `GET /api/autonomy` is told apart from
any other read failure and rendered as `NO_POLICY` — never as an empty set of
switches, which would imply "nothing is gated".

**F37 — Verbatim server rejection.** A rejected write renders the server's own
400 message (e.g. `unknown autonomy level: 'sometimes'`) inline with
`role="alert"` beside the control, not as a toast — a faded toast leaves a switch
whose position matches nothing. Nothing is recorded on a rejection.

**F38 — Single shared cache.** One unparameterised query key
(`queryKeys.autonomy()`) shared by this panel and the drawer's allow-all, seeded
from the write response *and* invalidated. The two surfaces cannot disagree.

### 1.6 Worker drawer

**F39 — Watch a worker's transcript over the course page.** Builds its **own**
session store via `createSessionStore`, closed on unmount so open/close cycles
cannot leak live SSE subscribers. Always opens at HEAD — never a derived scrub
position, because a drawer opened historically would silently stop updating with
nothing on screen to say why. *Where:* `WorkerDrawer.tsx`.

**F40 — Answer approvals from inside the drawer.** The real `Approvals`
component, above the conversation because a blocked agent is the most urgent
thing the drawer can contain. Approve / Reject only — see G4, G5.

**F41 — "Stop being asked" (allow-all) beside the approvals.** Two buttons,
deliberately not one with a checkbox (a checkbox left ticked from a previous
visit is exactly the accident that matters here):
- *Allow everything except the review gate* — accent tone; disabled when nothing
  is left to change.
- *Also allow the review gate* — quiet tone, separate, titled "Also autos the
  workflow review gate, so a run can cross stage boundaries unattended";
  disabled when no stage gate is still asking.
After a write it reports **what actually moved** ("Changed 3 tool(s): …") or
"Nothing moved — those tools were already set that way.", plus what stayed put
and why. *Where:* `AutonomyAllowAll.tsx`.

**F42 — No composer, on purpose.** Read-only means no composing, not no deciding.
The empty-conversation copy is overridden so it does not invite the reader to
send a turn there is no control for.

**F43 — Activity feed** for the watched session, inside the drawer.

**F44 — Drawer a11y.** Modal announcement, focus moved in on open, focus returned
on unmount, Escape to close, Tab and Shift+Tab wrap inside the trap (including
approval buttons once they appear). Asserted by `WorkerDrawer.test.tsx:232-330`.

**F45 — "Open the session"** action in the drawer header.

### 1.7 Findings ("This stage's checks")

**F46 — The current stage's check findings.** Severity chip, check name, message,
and an optional suggested edit (`→ …`). `severityLabel` maps `human_gate` to
"needs a person" and `critic_gate` to "needs a critic pass", explicitly so a
reader does not file them with the failures just because they arrived in the same
list. *Where:* `Findings.tsx`; `severityLabel`, `domain/project/course.ts:113`.
*Scope:* **only the current stage** (`course.py:331`). A stage already left has a
findings artifact recorded at the moment it was left, and recomputing against a
course that has since grown would present a different table as the one the
reviewer gated on.
*Empty:* the whole section renders `null` — see D7.

**F47 — Unimplemented-check warning.** A dedicated row naming declared checks that
nothing implements: "Nothing they would have found is known." Silence about these
is treated as worse than declaring none.
*Where:* `Findings.tsx:28-39`; source `course.py:341` ← `stage_exit.review_stage`.

### 1.8 Stage rail

**F48 — Every stage of the preset, run or not.** A rail built from what happened
could only show what happened; the question this answers is what was *supposed*
to. *Where:* `StageRail.tsx`; data `course_progress`, `application/course.py:292`;
presenter `stage_progress_view`, `interfaces/web/presenters.py:372`.

**F49 — Pane meta:** `N of M left behind` (stages with `status === 'done'`).

**F50 — Per-row:** status dot, index, name, artifact count, status chip. The
count is **written-of-declared** (`2/3`), never a percentage, with a `rail-short`
class when short — "a stage owing two artifacts with one written is a specific
situation, and 50% is not". A stage declaring no artifacts shows an em dash
titled "This stage declares no artifact of its own."
*Caveat:* `status` ∈ `done|current|upcoming|unknown` and is **positional only**.
A stage advanced past with nothing written still reads `done`; only its `0/2`
count says otherwise. See D14.

**F51 — Expand one stage at a time.** `aria-expanded` toggle button; opening
another closes the first (`openStage` is a single value, `CourseView.tsx:45`).

**F52 — Stage detail metadata row:** stage id, `spine N`, scope level, kind.

**F53 — Gate decisions preview.** What a human is allowed to answer at this
stage's gate, joined with `·`, plus the reviewer role in parentheses when
declared. `halt` is called out as worth seeing in advance, because "the pipeline
is structurally biased toward producing its own output". **Display only** — see
G5 for why none of these can actually be given.

**F54 — Findings report link** for the stage, through `CourseFileLink`. The path
is `{COURSE_DIR}/{NN}-check-findings.md`, fetched through the session file route.

**F55 — Per-stage artifact list,** or "Produces no artifact of its own; its
result is recorded elsewhere."

### 1.9 Artifact list

**F56 — All declared artifacts, flattened across stages,** with `N of M written`
in the pane header. *Empty state:* "This workflow declares no artifacts. /
Nothing here is missing; the preset simply names no outputs." — currently
**unreachable**, because all 33 stages across the three shipped presets declare at
least one output (verified in `stage-boundaries.md`'s own walk of `PRESETS`).

**F57 — Four artifact states, not two.** missing; present with no readable
frontmatter; present claiming sources; present claiming its reasoning was the
model's own. The last two are both legitimate and must not look alike.
*Where:* `Artifacts.tsx:17`.

**F58 — Artifact row:** basename (linked when present), artifact type + subtype,
cardinality, `written` / `not written` chip whose title names the exact declared
path.

**F59 — Missing-frontmatter note:** "No readable frontmatter, so nothing can tell
what this is or what it rests on."

**F60 — Missing-fields note:** names which frontmatter fields are absent.

**F61 — Provenance row.** Source spans render as links into the source reader at
the cited offsets — `/api/projects/{p}/sources/{s}?start=&end=`. Deliberately
**unresolved**: whether a span still says what it said is a check's question, and
answering it here would cost a document read per row.
*Chips:* `inferred` (not a defect — a stage whose reasoning is its own and says
so is working as designed), `N unreadable`, and `claims nothing` (neither a
source nor an admission of inference — the one shape the contract calls never
right, computed server-side precisely so a client cannot rederive it wrongly).
"No provenance block at all." when the block is absent.

**F62 — `CourseFileLink` degradation.** With no holding session, a file name
renders as muted text titled "No session is holding this project, so there is
nothing to open the file in. Join the project to read it." Course files are read
through the holding session because that is where the file viewer lives, and a
second reader here would be a worse copy of it.

### 1.10 Live refresh

**F63 — The rail moves without a reload.** Subscribes to **every** project frame
scoped to this project id, not only stage advances: `WorkflowSelected` is what
turns "No course to show" into a rail, and the lifecycle events move the
holding-session link. Invalidates three keys: `course`, `workers`, `projects`.
Deliberately does **not** subscribe to log frames — refetching on every token
would cost more than the artifact list being one stage boundary behind.
*Where:* `useCourseRefresh`, `CourseView.tsx:207`. Fixed in #82; the missing half
had been on the server, where the feed filtered `Project` streams out entirely.
*Note:* there is **no `course` frame type on the stream.** Nothing on SSE is
course-specific; the page learns of change only indirectly, via the `project`
frame, and refetches for itself.

### 1.11 One hop out — reached only from this page's links

**F64 — Session file viewer** (`FileView.tsx`), where every artifact link lands.
Markdown, diffs, per-file history. Routes: `GET /api/sessions/{id}/files`,
`/files/history`, `/files/parsed`.

**F65 — Lesson document rendering with interactive widgets.** When a course
artifact contains fenced `component:` blocks, the file viewer renders it through
`LessonDocument` instead of plain markdown.
*Where:* `presentation/lesson/LessonDocument.tsx`, mounted at `FileView.tsx:196`
(and at `research/TopicDocuments.tsx:170`).
*Renderers:* `flashcards`, `mcq`, `cloze`, `checklist`.
*Degradation is per block:* an unknown type renders as a labelled code block; a
known type whose fields did not parse renders its own source plus a panel naming
the failing paths and messages. Neither takes the document down.
*Grading is server-side only:* the learner projection strips the answer key before
it leaves the server (`?view=author|learner`, a `Literal` so a typo is a 422
rather than a silent answer-key leak), and `domain/lesson/attempt.ts` is shaped so
the browser cannot construct a verdict — there is no constructor from a score.
*Author/learner toggle:* `ComponentAudience`, defaulting to `author` (the console's
reader is the person building the course), rendered only when the document
actually has components.
*Widget behaviours:* cloze one-at-a-time vs all-at-once (`activeBlank` — every
blank reopens once all are filled, so a learner can revise before submitting);
mcq single vs multiple answer (radio vs checkbox, and it changes what a
submission means); checklist persistence to `POST /api/sessions/{id}/progress/checklist`;
flashcard flip. Verdicts carry feedback lines, a rationale, per-blank marks and
durable `ItemProgress` counted server-side. A returning learner sees "You answered
this correctly … before" but **not** a reconstructed verdict panel — the record
holds scores, not the author's feedback text, and inventing a panel from a score
would put words in their mouth.
*An "answers withheld" badge* marks a component whose key was stripped, with a
title explaining the raw file is still readable from the source toggle.

**F66 — Source reader at a cited span,** from a provenance link.

---

## 2. Backend surface behind the page

Every route lives in one function, `create_app` at
`research_team/interfaces/web/app.py:340`. There is no `APIRouter` anywhere;
`approvals.py`, `dispatch.py`, `extraction.py`, `seeding.py`, `activity.py` are
state-holder collaborators, not routers.

| Method | Path | Line | Serves | Notable failures |
| --- | --- | --- | --- | --- |
| GET | `/api/projects/{id}/course` | 559 | F1,F2,F46–F62 | **409** no preset (message lists valid ids); **409** preset this build does not ship (message names the id); **404** unknown project or `status=="new"` |
| GET | `/api/projects/{id}/workflow` | 521 | — | `{workflow, stage}`, both nullable |
| POST | `/api/projects/{id}/workflow` | 527 | preset selection | 404 unknown preset; **409** re-selection |
| GET | `/api/workflows` | 427 | preset list | static; hybrid first — the order *is* the recommendation |
| GET | `/api/projects/{id}/workers` | 1261 | F5–F9 | **404** when no roster |
| GET | `/api/workers` | 1239 | topbar widget | **404** when no roster |
| GET | `/api/projects/{id}/extraction` | 1279 | F10 catch-up | 200 `{current:[],last:[]}` when unwired |
| GET | `/api/projects/{id}/auto-research` | 1221 | F20–F24 | **404** with an `AGENT_AUTO_RESEARCH` message when disabled |
| POST | `/api/projects/{id}/auto-research` | 1159 | F18 | same |
| POST | `/api/projects/{id}/auto-research/cancel` | 1298 | F25 | |
| GET | `/api/autonomy` | 1700 | F30–F36 | **404** "the autonomy policy is not wired up" |
| POST | `/api/sessions/{sid}/autonomy` | 1711 | F31 | **400** carrying the policy's own message; nothing recorded on rejection |
| POST | `/api/sessions/{sid}/autonomy/allow-all` | 1751 | F41 | returns `{changed}` + full map |
| GET | `/api/sessions/{sid}/approvals` | 1655 | F40 | `[]` when unwired |
| POST | `/api/sessions/{sid}/approvals/{aid}` | 1665 | F40 | **404** unwired, or already-answered / turn-cancelled (an honest race) |
| GET | `/api/sessions/{sid}/files` | 1381 | F64 | 404 not found *at that moment*; 400 bad `at` |
| GET | `/api/sessions/{sid}/files/parsed` | 1417 | F65 | `view` is a `Literal` → 422 on a typo |
| GET | `/api/sessions/{sid}/files/history` | 1390 | F64 | |
| POST | `/api/sessions/{sid}/attempts` | 1435 | F65 grading | |
| GET/POST | `/api/sessions/{sid}/progress[/checklist]` | 1473/1486 | F65 | |
| GET | `/api/projects/{id}/sources/{sid}` | 633 | F61 | **503** when no corpus read model |
| POST | `/api/projects/{id}/join` | 1105 | (not on this page) | 409 held or holder mid-turn |
| GET | `/api/stream` | 1783 | F10, F63 | SSE |

**Error-code convention, worth carrying into a redesign.**
`503` = "this build has no read/write model wired" (`_reader:599`,
`_topic_reader:657`, `_topic_repo:885`, `_graph_reader:982`).
`404` on `/api/workers`, `/api/autonomy` and `/api/projects/{id}/auto-research`
= "this build cannot tell you" — chosen over a permissive default *and* over 403,
because a 403 would disclose to an unauthenticated caller that an unattended
research loop exists behind the port.
`409` on `/course` = the request was fine, a choice is missing.

**SSE frames.** One connection (`GET /api/stream` → `_sse()` at `app.py:1811`).
Keepalive every 15 s (`KEEPALIVE_SECONDS`, `app.py:112`); disconnect polled every
0.5 s.

*Logged frames* carry `id: <cursor>` and replay on reconnect (`app.py:1926-1955`),
dispatched on `aggregate_type`:
- `project_change` — aggregate id *is* the project id. **This is how
  `StageAdvanced` reaches the course view, and it is the only frame that signals
  a stage boundary.** (→ F63)
- `feed_event` — session-scoped; `FileWritten` arrives here, which is how a new
  artifact becomes visible. The course view deliberately ignores it (F63).
- `topic_change` — carries **no `project_id`**, deliberately (only `TopicOpened`
  has one, and a read-model lookup per frame on an always-open connection was
  refused).
- `corpus_change`, `graph_change`.

*Side-channel frames* have **no id and cannot be replayed** (`app.py:1923`); a
reconnecting tab must refetch from the matching catch-up route:
`TurnActivity`, `ApprovalRequested`/`ApprovalSettled` (uniquely, new listeners
*are* seeded with pending approvals, `approvals.py:137`), `Extraction`,
`Seeding`, `Dispatch`.

**Trap:** `dispatch.py:61` records that a frame type published server-side but
not switched on in the client's `decodeFrame` is **dropped silently** — the
default branch parses it as a log frame, fails, returns null, logs nothing. The
comment records that this actually happened once, for `Extraction`.

**Application modules behind it:** `application/course.py` (`course_progress`,
`course_view`), `application/stage_exit.py` (`review_stage`, `findings_path`,
`gate_context`, `render_review`, `refusal`), `application/checks.py`,
`application/components.py`, `application/workers.py`
(`WorkerRoster.everywhere`), `application/autonomy.py` (`AutonomyPolicy`,
`TOOL_FLOORS`, `relax_all`), `application/prompts.py` (see G2).

---

## 3. Dead ends and rough edges

**D1 — A project with no workflow is a cul-de-sac.** The course page 409s with
"select one of … first", and there is **no control on this page to select one**.
`GET /api/workflows` and `POST /api/projects/{id}/workflow` both exist and both
are wired in the frontend repository (`project-repository.ts:31,41`), but the only
caller is `NewProjectForm.tsx:63` — the create-a-project form on the home page. A
project created without a preset can never be given one from the web UI. The
error message instructs the reader to do something the UI cannot do.

**D2 — No holding session degrades four things at once.** With
`holdingSessionId === null`: the "Open holding session" link vanishes with no
explanation (F4); every artifact name becomes unclickable muted text (F62); the
autonomy panel goes read-only (F35); and the artifact → file-viewer → widget path
(F65, F66) is entirely unreachable. Only F62 explains itself, and only in a
`title`. **Nothing on the page offers a "join this project" control**, though
`POST /api/projects/{id}/join` exists and is used elsewhere.

**D3 — Feature-off detection is a regex over an error message.** `saysDisabled`
matches `/not enabled|AGENT_AUTO_RESEARCH/` against a 404 body
(`project-repository.ts:95`). Any rewording of the server's message turns the
"autonomous research is off" explanation back into a generic failure. There is no
capability endpoint.

**D4 — A missing extraction route is indistinguishable from "nothing ran".**
`catchUp()` errors are swallowed (`ExtractionPane.tsx:42`), so the pane says "No
extraction has run on this project yet." — a claim it cannot back up. Deliberate
and documented; still a lie the reader cannot detect. (Mitigated in practice: the
route returns 200 with empty lists rather than erroring.)

**D5 — Every provenance link can 503.** `/api/projects/{id}/sources/{sid}` 503s
when no corpus read model is configured, and nothing on the artifact row warns
first.

**D6 — Two worker rosters on one screen.** Since #86 the topbar carries a global
what-is-running popover (`presentation/agents/AgentWidget.tsx`, `GET /api/workers`)
while the course page keeps its own per-project panel (F5,
`GET /api/projects/{id}/workers`). Two requests, two poll intervals, two
renderings of overlapping facts; neither references the other.

**D7 — The findings section vanishes entirely when empty.** `Findings.tsx:12`
returns `null` when there are no findings *and* no unimplemented checks. A reader
cannot distinguish "the checks ran and found nothing" from "no checks ran" from
"this build has no check library".

**D8 — `elapsed` does not tick; a dispatch's queued count has no field.** Recorded
as found-and-not-fixed in #86's own commit message.

**D9 — `/api/projects` folds one aggregate per project,** and F63 invalidates
`queryKeys.projects()` on **every** project frame — so a busy project makes the
whole project list re-fold. Also recorded in #86.

**D10 — Cancel has no "stopping" state.** F25's label and tooltip are honest, but
after the request settles the panel shows plain `running` again; only the button
text changed while in flight.

**D11 — The rail is one stage boundary behind on artifacts.** Documented and
accepted at `CourseView.tsx:200-206`. A user watching a stage write files sees the
counts move only when the stage advances — even though `FileWritten` is on the
stream and would answer.

**D12 — `position === null` is explained but not actionable.** F2 tells the reader
their project sits at a stage the preset does not contain. There is no control to
correct it, and `_advanced` (`domain/project.py:293`) refuses anything but a
single forward step, so there is no route back either.

**D13 — Stale and errored rosters look similar.** Both are a small chip or a `sub`
paragraph; a reader who misses the `stale` chip reads a frozen roster as live.

**D14 — Stage status is positional, not evidential.** `done|current|upcoming|unknown`
is computed from position in the preset. A stage advanced past having written
nothing still renders `done` with a green-ish chip; only the `0/2` artifact count
contradicts it, and only if the reader looks. This is the rail's single most
misleading affordance.

**D15 — The findings report is a bare path.** F54 links `{COURSE_DIR}/{NN}-check-findings.md`
into the file viewer. There is no endpoint that renders a review
(`stage_exit.render_review` exists and is not routed), so the reviewer reads raw
markdown.

**D16 — A new frame type the client does not know is dropped with no log.** See
the `decodeFrame` trap in §2. A server that grows a frame the course page should
react to fails silently on this page.

---

## 4. Built but **not reachable** from the UI

The most valuable section. Sub-labelled by *why* it is unreachable, because
"deliberately deferred" and "dropped on the floor" call for opposite responses.

### G1 — `StageRunner`: the whole driver, composed and unrouted. *(Built; deliberately deferred.)*

`research_team/application/stage_runner.py` (≈820 lines, class at `:359`) drives a
stage to its boundary: runs turns, computes `stage_exit_condition` over
**committed** state, counts consecutive failures and file-less turns, runs the
stage's checks, poses the approval and advances. Fully tested
(`tests/application/test_stage_runner.py`, ~900 lines, including
`test_advancing_is_only_reachable_through_the_function_that_asks`).

It **is** constructed in the composition root (`composition.py:986`), exposed as
`Application.stage_runner` (`:225`, `:1030`), and handed to the worker roster as
`stages=` (`:1009`) — so a driven stage *would* appear in F5 and in the topbar
widget as a `stage` worker.

**Nothing calls `StageRunner.run(project_id)`.** Verified by grep over
`research_team/` and `tests/`: only the composition construction and the test
file. No HTTP route, no CLI command, no other application module.

**This is deliberate and documented.** Its docstring in `composition.py:230-234`
says: *"A field and not a route, deliberately. `workflow-engine.md` §5 and
`stage-boundaries.md` open question 1 both say the same thing: the runner should
be built after a human has prompted a preset through by hand, because the thing
that would falsify its design is a prompt, and no preset resolves end to end
yet."* The named precedent is `TopicDispatcher`, which was reachable the same way
before `/dispatch` existed.

Consequences:
- `Worker.kind` includes `'stage'` (`domain/worker/worker.ts:10`) and that value
  can never appear today.
- `StageRunSnapshot` and `StageRun.stopped_because()` have no consumer.
- **There is no HTTP route to advance a stage at all.** The only two paths to
  `AdvanceStage` are the agent's `advance_stage` tool
  (`infrastructure/agent/workflow_tools.py:218`) and `StageRunner`. A human
  looking at the course view cannot advance a stage except by opening a session,
  instructing a model to call the tool, and then approving it.

### G2 — The prompt library resolves and is never called. *(Built; deliberately deferred, blocked on G3.)*

`research_team/application/prompts.py` implements `DirectoryPromptLibrary`,
`load_prompts`, `parse_prompt`, `resolve`, `stage_prompt`, `role_line`,
`prompt_digest`, `unresolved`, `orphaned_refs`, `shared_ref_problems`,
`intended_for_disagreements`. **Every one of these is exercised only by
`tests/application/test_prompts.py`. There is no production caller of any of
them.**

Where a resolved prompt would go is `composition.py:661-675`, which still builds:

```python
instructions=(
    stage_artifact_instructions(preset, stage)
    + WORKFLOW_PROMPT
    + component_guidance(stage.outputs)
),
```

Three mechanical terms, no methodology. It feeds a **different** function of the
same name — `infrastructure/agent/stage_middleware.py:93` — whose `StageLike`
protocol docstring says outright: *"Notably absent: the prompt."*

So even the six prompt files that exist (G3) never reach a model. **From the
model's point of view, `ubd.pure` and `addie.pure` currently run identically.**
`prompts.py`'s own docstring is honest that `unresolved()` "is written and tested
and has no caller yet", because wiring it would refuse to build for every preset
shipped today.

The designed failure mode, once wired, is a hard refusal: `PromptError` from
`DirectoryPromptLibrary.prompt` (`prompts.py:288-293`), explicitly with no
fallback, because "a stage running without its methodology produces output that
passes every structural check and is wrong in the one way nobody can see."

### G3 — 38 `prompt_ref`s, 6 prompts. *(Designed but unbuilt — the content.)*

Counted from the tree (`grep -rhoP 'prompt_ref\s*=\s*"[^"]+"' research_team/`):
**49 uses, 38 unique.** On disk: `prompts/ubd/` contains exactly six files —
`context.md`, `intake.md`, `sequence.md`, `stage1_generate.md`,
`stage2_generate.md`, `stage3_generate.md`. All six are `kind: generator`.

**6 of 38 resolve (16%). 32 do not.**

| Preset | Stages | Refs | Unresolved |
| --- | --- | --- | --- |
| `hybrid.default` (**the default preset**) | 15 | 22 | 20 |
| `addie.pure` | 12 | 17 | 17 (all) |
| `ubd.pure` | 6 | 10 | 4 |

Nothing exists under `prompts/addie/` (17 refs), `prompts/tyler/` (8 refs) or
`prompts/hybrid/` (3 refs). `ubd.pure` is closest to complete: every generator
resolves; its four critics (`context_critique`, `stage1_critique`,
`stage2_critique`, `stage3_critique`) do not. Two prompts (`stage2_generate`,
`stage3_generate`) are legitimately shared with `hybrid.default` and declare it in
`intended_for`. No prompt file is orphaned; `shared_ref_problems()` is clean.

`DEFAULT_PRESET_ID = "hybrid.default"` (`research_team/workflows/__init__.py:23`)
— **the preset with the worst prompt coverage is the one a new project gets, and
it is listed first in `/api/workflows` because "the order is the recommendation".**

**Writing all 32 prompts would still change nothing at runtime without the
`composition.py` wiring in G2.** The gap is two-layered and both layers are
load-bearing; either alone is inert.

### G4 — `gate_context` is computed at every stage boundary and never shown. *(Built server-side; dropped on the floor by the client.)*

`ApprovalRequest.context` (`application/ports.py:278`) carries, for a stage
advance: the stage id, the findings-artifact path, the artifact paths, whether the
stage is blocked, and counts of artifacts and links reviewed
(`stage_exit.gate_context:486-492`). The web adapter serialises it —
`interfaces/web/approvals.py:54` sets `view["context"]` — on both the REST route
and the `ApprovalRequested` SSE frame.

The frontend **drops it**. `approvalDto` (`infrastructure/http/dto.ts:208-214`)
declares only `id`, `session_id`, `tool_name`, `description`, `args`.
`domain/approval/approval.ts` has no `context` field. `Approvals.tsx` renders
`safeJson(approval.args)` and two buttons.

So the single most consequential decision on this page — letting a stage go — is
made against a JSON blob of tool arguments, with the check findings the server
computed *specifically for that moment* nowhere on screen. The
`findings_artifact` path is in the payload and is not linked. The CLI does not
render it either, so this is not "the web is behind the terminal" — **nothing
renders it.**

### G5 — `allowed_decisions` is sent and discarded. *(Built server-side; dropped on the floor.)*

`ApprovalRequest.allowed_decisions` is serialised at
`interfaces/web/approvals.py:51`. The frontend DTO drops it, and
`ApprovalDecision` is hardcoded to `'approve' | 'reject'`
(`domain/approval/approval.ts:19`).

Meanwhile the stage rail **displays** the gate's permitted decisions as text
(F53). A reader is told this gate accepts `send_back` or `halt`, and given two
buttons, neither of which is that. The page names what you may answer and then
does not let you answer it.

Note the domain half is a *separate* limitation, and a deeper one: `_advanced`
(`domain/project.py:293`) refuses everything but a single forward step, and
`StageAdvanced` is the only stage event — so `send_back`, `halt` and
`amend_upstream` are **unrepresentable in the log** even if the UI offered them
(`workflow-engine.md` §3.4). `approve_with_edits` is the one that *is*
representable and *is* stored — see G6. Executing `LoopPolicy` is a domain change,
not a UI change.

### G6 — `StageAdvanced.decision` is written and read by nothing. *(Built; no consumer.)*

Added in #80 (`domain/project.py:105-121`). Its own docstring: "Nothing reads it
yet." Confirmed — no presenter, no route, no frontend field. `approve_with_edits`
is described there as "the cheapest real signal about which stages need better
prompts", and it currently enters the log and stops. It exists because a runner
writing machine prose into `gate_decision` would otherwise leave the human's
verdict with nowhere to live.

### G7 — `ubd.uncoverage` is registered and bound by nothing. *(Built; unreachable.)*

Recorded in `workflow-engine.md` §1: 21 checks implemented and bound, plus one
registered and unused. It can never appear in F46, and F47 does not surface it
either — F47 counts checks a *preset declares* that nothing implements, which is
the mirror case.

### G8 — Generator / Critic machinery is inert. *(Built as data; no executor.)*

Every `_Authored` stage carries a `Generator`; eighteen carry a `Critic` with
`separate_context: True`. Per `workflow-engine.md`'s own reproducible grep,
nothing outside `workflows/` reads `.generator` or `.critic` except
`checks.py:1099-1100`, and only to compare them for **inequality**.
`reviewer_role` escapes as far as `course.py:324` → `presenters.py:382` → the
stage rail (F53) and nowhere else. `loop_policy`, `max_iterations`,
`convergence_check`, `adversarial_second_pass`, `over_generate_factor`,
`taxonomy_binding` and `require_citation` are read by nothing outside their own
declarations. The design says a critic would have to be a `task` subagent
(`delegation.py`), at 3–10× the tokens.

### G9 — Widget renderers exist; almost nothing produces widgets. *(Built and reachable; starved of input.)*

This claim is commonly overstated, so precisely:

- The renderers **are reachable**. `LessonDocument` is mounted from
  `FileView.tsx:196` — exactly where a course artifact link lands — and from
  `TopicDocuments.tsx:170`. A course artifact containing `component:` fences
  **will** render as widgets today.
- What is missing is *production*. `component_guidance`
  (`application/components.py:604`) is the only thing that ever tells a model to
  emit a widget, and `COMPONENTS_FOR` (`components.py:573-588`) scopes it to five
  artifact types: `EVIDENCE_SPEC` → mcq/cloze, `EXPERIENCE` →
  flashcards/cloze/checklist, `BUILD` → the whole registry, `SEQUENCE` →
  checklist, `MONITORING_PLAN` → checklist. Every other stage is told nothing
  about widgets, deliberately — "a prompt that carries it anyway teaches the model
  that most of its instructions do not apply to it".
- The stages that *would* be told are concentrated in `addie.pure` and
  `hybrid.default` — the two presets holding 37 of the 38 missing prompt refs. So
  **the stages best positioned to author widgets are precisely the ones with no
  methodology prompt at all.**
- `Rubric`, `Criteria` and `TaxonomySelection` have a natural component in the
  design's §3.8 table and no registered type, so `COMPONENTS_FOR` omits them;
  `ordering` is named in a comment as "not registered yet".

Net: renderers reachable, four widget types implemented, pipeline wired end to
end, and the content that would flow through it does not exist because of G3.

### G10 — Nothing on the course page says an artifact is interactive.

Even though F65 works, the artifact row shows type, subtype, cardinality and
provenance — never whether the file contains components. A user must open the file
to find out, and only if there is a holding session (D2).

### G11 — Other application capabilities with no HTTP route.

- **`stage_exit.render_review`** — the findings artifact is *written*
  (`composition.py:734`, `stage_runner.py:666`) and surfaced only as a path
  string. No endpoint renders or returns a review (D15).
- **`review_stage` on demand** — pure over the course directory, explicitly noted
  in `workflow-engine.md` §3.1 as callable without an approval in flight.
  Reachable over HTTP only as a read-only side effect of `GET /course`.
- **No corpus write route.** `ProjectCorpusReader` exposes `list_sources`,
  `read_document` and `read_media`; the first two are routed, `read_media` is
  not yet. There is no HTTP way to store, drop or re-ingest a
  source — agent-tool-only. A browser can read the corpus and never add to it.
- **No knowledge-graph write route.** `remember` / `unmerge` are gated tools; the
  HTTP graph surface is read-only.
- **`DISPATCH_ACTIONS = frozenset({"understanding"})`** — `research` and `lesson`
  are designed in `docs/design/topic-dispatch.md` and unbuilt; the route 422s on
  them **by name** (`NewDispatch.action` is a plain `str` rather than a `Literal`
  precisely so the refusal can say what does exist).
- **Run history.** `GET /api/projects/{id}/auto-research` serves only the *live*
  run; "every run this project has ever done" is a projection nobody has built,
  and the docstring rejects answering it with a stream scan.
- **Per-dispatch cancel** is deliberately not built; only per-project, because the
  UI shows one stop control on the pane header.
- *Inverse case:* `SetTopicStatus`, `AddSubQuestion`, `ResolveSubQuestion` are
  routed with **no agent tool**, deliberately human-only — an autonomous run can
  learn a question is answered, but only a reader gets to say the project is done
  asking it. This is the one place the human/machine asymmetry runs the other way,
  and it is a good pattern the course page does not use.

---

## 5. What a power user cannot do that the data model would support

**P1 — Start a stage.** The runner is built, composed and observable through the
roster (G1). One POST route exposes it. Today the only way to move a course
forward is a human opening a session and typing instructions — fifteen times for
`hybrid.default`, six for `ubd.pure`.

**P2 — See what the checks found at the moment they are asked to approve.** The
data is already in the approval payload (G4).

**P3 — Answer a gate with anything but approve/reject.** `allowed_decisions` is
transmitted (G5) and `approve_with_edits` is storable (G6). Two buttons.

**P4 — Choose or change a workflow after project creation.** Route and repository
method both exist (D1).

**P5 — Join a project from the course page,** unlocking F4, F62, F65, F66 and
write access in F35. The route exists.

**P6 — Read a stage's findings history.** Only the current stage's findings are
served (F46), by deliberate design — but a findings artifact exists for every
stage already left, linked one at a time from inside an expanded rail row (F54).
There is no timeline, no comparison, no "what did each gate see".

**P7 — Filter, sort or facet the artifact list.** `allArtifacts` flattens every
stage's outputs into one list with no controls. `present`, `artifactType`,
`stageId` and every provenance flag are on the model; none is a facet. A 15-stage
preset yields a long unfiltered column.

**P8 — Jump to, or auto-open, the current stage.** `openStage` starts `null`, so
the page always loads fully collapsed even when `position` is known. No search
either.

**P9 — Expand more than one stage.** `openStage` is a single string
(`CourseView.tsx:45`); two stages' artifacts cannot be compared side by side.

**P10 — Re-run a stage's checks on demand** (G11).

**P11 — See which revision of the workflow produced an artifact.** `prompt_digest`
is implemented (`prompts.py:305`) and never written to any frontmatter, because
G2. `artifacts.py` does write `preset` and `preset_version`, and the artifact row
surfaces neither.

**P12 — Verify a provenance span.** F61 renders spans unresolved by design; the
corpus reader could answer whether the cited offsets still say what the artifact
claims, and nothing asks.

**P13 — Cancel a turn from the drawer.** `POST /api/sessions/{id}/turns/cancel`
exists; the drawer offers only approvals and reading.

**P14 — Scope autonomy per project or per session.** The model is deliberately
instance-wide and says so loudly (F33), yet the *write* is recorded against a
session — so there is already a per-session audit trail for a policy with no
per-session scope. Two projects on one instance cannot have different levels.

**P15 — Distinguish a `done` stage that produced nothing** (D14) without reading
the count.

**P16 — Get an unattended course.** Possible today, and only through
`relax_all(include_stage_gates=True)` — F41's second button. That is deliberate:
`stage-boundaries.md` §4.4 argues autonomy is something an operator has already
decided, not something a driver grants. But since G1 means there is no driver,
pressing that button currently unlocks nothing a person is not still driving by
hand.

---

## 6. Where code and comments disagree

- `Workers.tsx:110-111` says extraction's "detail view is the extraction pane,
  which a later task adds". The pane exists (F10). **Stale.**
- `infrastructure/agent/workflow_tools.py:313` reads "`StageRunner` now keeps that
  promise for a driven run", which invites the reading that runs are driven. No
  run can be driven; there is no caller (G1). **Misleading in isolation, correct
  in context.**
- `docs/design/workflow-engine.md` §2.3 describes the `composition.py` prompt
  wiring as if it were the design under construction; a reader could take it for
  shipped. It is not (G2). `prompts.py` itself is honest.
- `domain/project.py:117` "Nothing reads it yet" — **accurate, verified.**
- `CourseView.tsx:104` "renders read-only and says why rather than offering
  controls that would 404" — **accurate.**
- `CourseView.tsx:158-162`'s "This workflow declares no artifacts" empty state
  describes a case no shipped preset can produce (F56).

---

## 7. Confidence notes

- Route table, error codes and SSE frame taxonomy: read out of
  `research_team/interfaces/web/app.py` at the lines cited, and independently
  confirmed by a second agent reading the same file.
- **`StageRunner` has no caller:** verified by grep over `research_team/` and
  `tests/`; only the `composition.py` construction and the test file appear. I did
  not check for dynamic dispatch by string, and there is no plugin registry here
  that would permit it.
- **`prompts.py` has no production caller:** verified by grepping every public
  name in the module.
- **Prompt counts** reproduced independently twice, agreeing at 49 uses / 38
  unique / 6 on disk / 6 resolving.
- **`context` and `allowed_decisions` dropped by the client:** verified by reading
  `interfaces/web/approvals.py:51,54` against
  `frontend/src/infrastructure/http/dto.ts:208-214` and
  `frontend/src/domain/approval/approval.ts`. This is a schema-level omission, not
  a rendering choice — the fields never enter the frontend's type system.
- **I did not run the application.** Nothing here is an observation of a live run;
  every state described is read off code. Per `CLAUDE.md`, the suite passing
  carries no information about any of it.
- I did not audit `Cloze.tsx`, `Mcq.tsx`, `Flashcards.tsx` and `Checklist.tsx`
  line by line. F65's widget behaviours are read from the domain layer
  (`widgets.ts`, `attempt.ts`) and the shared renderer primitives, which is where
  the load-bearing rules live; per-widget markup details may hold small features
  not listed.
- The claim that no shipped preset has a zero-output stage is taken from
  `stage-boundaries.md`'s stated walk of `PRESETS`; I did not re-walk it.
