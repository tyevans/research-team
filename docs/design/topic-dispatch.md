# Dispatching an agent from a topic

Read out of the working tree at `research_team/domain/`,
`research_team/application/`, `research_team/interfaces/web/`,
`research_team/workflows/` and `frontend/src/` on branch `main` (at `aae5b74`,
after #66 and #67).
Line numbers are pointers, not contracts — several of the files named here are
being edited concurrently, so check before trusting a number.

**How the load-bearing claims were checked.** Three of the arguments below rest
on an absence, and an absence is the easiest thing to get wrong by reading
too little. Each was verified by grep over the tree rather than inferred:

- *No generator prompts exist* (§6): `prompt_ref` appears outside
  `workflows/` and `tests/` in exactly one place, `checks.py:1110`, which
  compares the string to detect a critic sharing a generator's prompt. There
  is no `prompts/` directory. `stage_middleware.py:60` states the gap in its
  own docstring — "Notably absent: the prompt" — and
  `test_stage_middleware.py:117` describes "prompt text as composition would
  resolve it", a conditional about code that was never written.
- *The feed is filtered by aggregate type* (§5): `read_since`
  (`event_store.py:354`) reads one type at a time and admits sessions and
  topics only. Note this was fixed recently and its docstring is worth
  reading — before the fix "no topic event has ever reached the SSE feed",
  while two modules' comments already claimed otherwise. That is the exact
  failure mode this note exists to avoid.
- *Unknown SSE frames are dropped silently* (§5): `decodeFrame`'s `default:`
  branch returns `null` on a failed parse, with no log.

Everything asserted about behaviour under a *populated* database is untested
here, because this document proposes and implements nothing. Anyone building
from it should treat "a fresh database passes" as not yet an answer — see
`CLAUDE.md` on read models, and §8 of `landing-page.md` beside this file for
what that cost the last time.

The ask: from a topic in the research view, dispatch an agent to do one of
three things — **(1)** research the topic and fetch primary sources, **(2)**
write down our understanding of it in markdown, **(3)** make a course from the
topic and the material gathered for it.

This document says what a "dispatched agent" already is in this system's own
terms, resolves the one-live-session-per-project constraint that three actions
across many topics runs straight into, and says which of the three is nearly
free, which is moderate, and which is asking for something the data model does
not currently have a place to put.

Short version, so the rest can be read as argument rather than suspense:

- **Action 2 is the cheapest and should ship first.** It is `TopicSeeder`
  with a different prompt and a different output path. It adds no domain event.
- **Action 1 is a filter on machinery that already exists** —
  `AutoResearchDriver` restricted to one topic — plus one additive event field.
  Its "fetch primary sources" half is blocked on `BACKLOG.md` B24 and should
  ship *attended* rather than waiting for it.
- **Action 3 as literally specified collides with the data model.** A project
  has exactly one course, it is a view over one workflow preset selected once
  and never re-selectable, and stages advance one at a time behind a human
  gate. There is no place to put a second, per-topic course — and the
  project-scoped course it would build on is missing its generator prompts and
  has no stage driver, so "mostly built" is wrong in both directions. The
  nearest good version is that a topic dispatch produces a **lesson** — one
  widget-bearing markdown document — not a course. §6 argues this at length
  because it is the place where getting it wrong is expensive.

---

## 1. What a "dispatched agent" already is here

There are five concepts in the neighbourhood, and it matters which one this is.

**A session** (`domain/session.py`) is one event log: messages, tool calls,
files. Since `76f31b0` a session exists only inside a project, and
`SessionService.start_in_project` is the only way to make one.

**A project** (`domain/project.py`) is a filesystem lineage and a knowledge
graph. It is *sequential by construction*: `JoinProject` is refused by name
when `active_session_id` is set, and the refusal names the holder. One session
holds a project at a time. This is the constraint §2 is about.

**A turn** is one atomic model call plus its tool calls, run through
`TurnSupervisor`. All-or-nothing: a failure discards the aggregate's turn
events and appends a lone `TurnFailed`.

**An autonomous run** (`domain/auto_research.py`, `application/auto_research.py`,
`application/research_supervisor.py`) is a loop of rounds over a project's
*topic queue*. Its own aggregate, because a run outlives any one turn. Two
invariants shape it: no round without a reason, no stop without evidence —
`StopReason` is a closed enum and every value is recomputable from the log.
`ResearchSupervisor` runs it as a background task, one per project, refused up
front, with `start` / `active` / `cancel` / `state` / `wait`.

**A seeding run** (`application/topic_seeding.py`, `interfaces/web/seeding.py`)
is the one that matters most for this design, and its module docstring is
already the argument this document would otherwise have to make:

> `auto_research.py` argues at length for round-per-turn scheduling, because
> investigation is long, failure-prone and unbounded. […] Seeding shares none
> of those properties. It is one bounded burst of naming […] **The atomicity
> that makes a long run worthless makes a short one clean.**

`TopicSeeder.seed` joins the project (`start_in_project` + `attach_project`),
runs exactly one turn, and releases in a `finally`. It holds no aggregate, no
driver, and no state the log does not have. `SeedingActivity` beside it is the
side channel that tells a browser a run is in flight, with a catch-up GET for
a tab that reconnected.

**So a topic dispatch is not a new concept.** It is one of these two, chosen
per action by the same test seeding applied to itself:

| Action | Bounded? | Shape |
|---|---|---|
| 1. Research and fetch sources | No — unbounded, failure-prone, wants many rounds | An `AutoResearchRun` scoped to one topic |
| 2. Write our understanding | Yes — read what we have, write one file | One turn, `TopicSeeder`-shaped |
| 3. Make a lesson | Yes — read what we have, write one file | One turn, `TopicSeeder`-shaped |

A new aggregate was considered and is rejected in §7.

*What would falsify the split:* if action 2 or 3 turns out to want to fetch
material it does not have, it stops being bounded and becomes action 1 followed
by action 2. That is the right decomposition anyway, and it is what the UI in
§8 nudges toward, but if in practice every "write our understanding" press
wants a research pass first then these should be one queued pair rather than
two buttons.

## 2. The crux: one live session per project

Three actions across forty topics, and a project that admits one session at a
time. This is the part a shallow design gets wrong, so it is worth being exact
about what the constraint *is*.

`Project.decide` refuses a second `JoinProject`. That refusal is not a lock
protecting a race; it is the filesystem model. The project stores a lineage
pointer — whose stream, and how far in — and a new session forks from exactly
that point, so the filesystem still folds out of a single stream and scrubbing
a session's timeline still refolds it. Two concurrent holders would mean two
divergent tips and no answer to "what are this project's files".

Three options, and only one survives.

**(a) Relax it.** Allow concurrent sessions in a project. This is the obvious
move and it is wrong: it discards the property the whole filesystem design
rests on, in exchange for parallelism on a single-operator local tool where
the models are running on `localhost:8080` and are not parallel anyway. Not
proposed. If parallel dispatch ever becomes genuinely necessary, the way in is
per-topic *sub-projects* with their own lineage, not a project with two tips —
and that is a much larger design than this one.

**(b) Run every dispatch as a turn on whatever session currently holds the
project.** Cheapest possible. Rejected: it puts an agent's unrelated work into
the middle of a human's conversation, it makes the dispatch's context whatever
that conversation happens to contain, and it has no answer at all when no
session is holding the project — which is the normal state of a project you
have not opened today.

**(c) Each dispatch takes the project the way seeding and auto-research already
take it, and dispatches queue.** This is the proposal.

`start_in_project` → `attach_project` → run → `release_project` in a `finally`,
exactly as `TopicSeeder.seed` and `POST /api/projects/{id}/auto-research` both
do today. The dispatch holds the project for its duration and hands the tip
back, so the files it wrote are inherited by whatever runs next.

**The one thing this adds over today is a queue rather than a refusal.**
`SeedingActivity.start` and `ResearchSupervisor.start` both raise
`RunAlreadyActive`, which is correct for a control that appears once on a page.
A dispatch control appears on *every topic row*. With forty topics and three
actions each, "the project is busy" is the answer to nearly every second press,
and a UI whose primary control usually refuses is a UI people stop pressing.

So: **`DispatchQueue`, one per project, FIFO, at most one in flight.** It is a
supervisor in the same family as `TurnSupervisor`, `ResearchSupervisor` and
`SeedingActivity` — process-local, holding a deque of pending dispatches and
the task for the running one. Pressing dispatch on a busy project enqueues and
answers 202 with a queue position, rather than 409.

**Cost, stated plainly:** the queue is process-local, so a restart loses
everything pending and the browser will show three "queued" chips that will
never run. That is the same trade every supervisor here already makes, and
`workers.py` states it — "a restart shows an empty roster, which is the truth:
nothing is running". The difference is that a queued dispatch is a *user
intention* rather than a running process, and losing an intention silently is
worse than losing a process. Two mitigations, and I recommend the first:

1. **On restart, the queue is empty and the UI says so.** The catch-up GET in
   §5 returns `{running: null, queued: []}`, the chips clear, and the user
   presses again. Honest, and one line.
2. Persist the queue as events. This is where a `TopicDispatch` aggregate would
   earn its place — and §7 argues it does not yet.

**Concurrency across projects is unaffected.** The constraint is per project;
two projects dispatch in parallel today and will continue to.

*What would falsify the queue:* if in practice a user only ever dispatches one
thing and waits for it, `RunAlreadyActive` is simpler and the queue is
speculative machinery. I do not believe that — the owner's own question was
"what does a user do with three of them running at once" — but it is one class,
and starting without it and adding it when the first 409 annoys someone is a
defensible order.

## 3. What each action actually runs

### Action 1 — research and fetch primary sources

This is `AutoResearchDriver` with its queue restricted to one topic.

`AutoResearchDriver.run` reads `TopicQueuePort.evaluate(project_id)` each round
and claims the most urgent topic. Restricting it is a filter over that list, not
a new driver. `TopicRoundRunner` already runs one round as one turn against one
topic and counts what reached the topic's stream rather than what the model said
— which is the whole defence against confabulated progress, and it applies
unchanged.

The stop reasons still all hold. `queue_empty` becomes "this topic no longer
wants attention", which is exactly what the trigger registry computes. Novelty
decay, budget and consecutive-failure stops are untouched.

**The fetch half is the problem, and it is `BACKLOG.md` B24 verbatim.** `fetch`
floors at `ask` in `TOOL_FLOORS`, deliberately, and B24 spells out why an
unattended loop cannot lift it:

> an unattended loop that reaches an approval either deadlocks on a future
> nobody will resolve or is auto-rejected outright. So a run is read-only over
> the corpus and graph the project already holds.

B24 also names the honest fix — a scoped, counted, run-expiring
pre-authorization, a domain allowlist with a fetch budget granted as an event
and dead when the run ends — and explicitly rejects the shortcut ("not a
blanket N auto-approvals, which is `auto` with a counter"). That work is real
and is not in this design.

**What this design does instead: ship action 1 attended.** The user pressed a
button on a topic row; they are at the browser; the approval path (interrupt,
announce, prompt, recorded `ToolCallDecided`) already works end to end and is
already surfaced. A dispatch is *not* an unattended overnight loop — that is
what `auto-research` is — so the objection B24 raises does not apply with the
same force. A dispatched research agent that stops and asks "may I fetch
`https://…`?" is a reasonable thing for a tool with one local operator.

Consequences to state rather than hide:

- A dispatch left running while the browser is closed will stall on an approval
  nobody answers until its budget or the turn timeout ends it. The queue behind
  it stalls with it. The UI must therefore make an outstanding approval loud
  (§8), and cancel must work while blocked.
- With `AGENT_SEARXNG_URL` unset there is no `web_search` tool at all, so "find
  primary sources" degrades to "work from the model's own knowledge and the
  corpus". That is the same posture `SEEDING_PROMPT` takes, and the prompt
  should be written as a decision procedure the same way — "call `web_search`
  only if…" — so it describes one deployment rather than two.

### Action 2 — populate our understanding, in markdown

One turn. Read the topic, its linked sources, its sub-questions, its findings,
and the project's graph; write one markdown file; stop.

Everything it needs is already bound in a session attached to a project:
`list_topics` / `record_finding` / `link_source` (`topic_tools.py`),
`list_sources` / `read_source` (`corpus_tools.py`), the recall and knowledge
tools, and `write_file` on the session's own filesystem.

**Output path.** `artifacts.py` establishes the convention — one directory so
"what did this run make" is a listing rather than a search, a numeric prefix so
the directory reads top to bottom, and frontmatter naming its own provenance.
The same convention, one directory over:

```
/topics/<nn>-<slug>/understanding.md
```

with frontmatter carrying `topic_id`, `question`, `dispatched_at`, and the
source ids it drew on. `<nn>` is the topic's position in the project's topic
list at the time the directory was first written, for the same reason
`stage_number` exists: alphabetical file listing is the only ordering the
viewer has.

Reusing `/course` for this would be wrong — `COURSE_DIR`'s docstring says it is
"everything a workflow produces", and a topic synthesis is not produced by a
workflow. Two directories, two provenances.

**This adds no domain event.** The file lands as `FileWritten` on the
dispatching session's stream, which is already on the live feed, already
scrubbable, already diffable, already rendered by the file viewer. Any findings
the agent records land as `TopicFindingRecorded` on the topic. There is nothing
new to write down.

### Action 3 — make a course

See §6. It is the one that does not fit, and the argument needs room.

## 4. Events, and what they must remain readable as

`domain/events.py` opens with the two supported schema-evolution cases, and
`tests/infrastructure/test_schema_evolution.py` enforces them by writing
old-shaped payloads straight into the events table.

**This design adds exactly one field to one event, and it is a case-1
addition.**

```python
class AutoRunStarted(DomainEvent):
    ...
    topic_id: UUID | None = None
    """The single topic this run was scoped to, or None for the whole queue.

    Default None because that is precisely what a payload written before topic
    dispatch existed meant: every run was a run over the project's whole queue.
    The absence reads as the old behaviour rather than as "unrecorded", which
    is the strongest form of case 1.
    """
```

`AutoResearchRun`'s existing invariants survive it. `AutoRoundStarted` still
carries `triggers` and `evidence`; the round still names why the topic was
raised; `StopReason` is unchanged and every value stays recomputable.

**Add the case to `test_schema_evolution.py`**: write an `AutoRunStarted`
payload with no `topic_id` key, fold it, assert `topic_id is None` and that the
run reads as a whole-queue run. Prove it red first by making the field required.

**Actions 2 and 3 add no events at all.** Their output is `FileWritten` and
their side effects on the topic are the existing topic events. This is worth
stating loudly because it is the strongest argument for the shape in §1: a
feature that adds no vocabulary to the log is a feature that cannot break
anyone's stored history.

**What is deliberately *not* recorded:** "a dispatch was requested". There is
no `TopicDispatchRequested` event. Seeding made the same call and said so —
"the log has `open_topic` calls and nothing that says a seeding run started or
finished" — and the consequence is identical: running/queued/failed is
provisional process state answered by a catch-up route, not by folding a
stream. §7 says what would change that.

## 5. How progress reaches the browser

There is one SSE route, `GET /api/stream` (`web/app.py:1595`). It carries every
appended domain event to every listening browser, plus four non-event side
channels multiplexed into the same connection — approvals, turn activity,
extraction, and seeding — each with a PascalCase `type` the client switches on.
`Last-Event-ID` resumes the event half; the side channels cannot be replayed,
which is exactly why each has a catch-up GET beside it. Filtering by aggregate
type happens in the browser, not on the route.

So a dispatch is observed on three levels, and only the third is new:

**1. What it did — already works, and this is not luck.** `read_since` in
`infrastructure/persistence/event_store.py` filters the feed to exactly
`(CodingSession.aggregate_type, Topic.aggregate_type)`, because the SQLite file
is shared with redstring's `Document` and `Consolidation` streams whose
aggregate ids no subscriber can place. **That tuple is the gate on this whole
channel: an aggregate type not in it never reaches SSE at all.** Because this
design adds no aggregate (§7), it adds nothing to that tuple, and
`FileWritten`, `TopicFindingRecorded`, `TopicSourceLinked` and
`AutoRoundCompleted` are already on the feed the moment they are appended.
`TopicList` already invalidates its query off topic frames
(`useTopicRefresh`), so a dispatch that opens a sub-question or records a
finding updates the list with no new plumbing.

*Except the graph.* `application/research/graph-store.ts` subscribes to nothing
— no `useStream`, no `useFrameRefresh`, no refetch interval — so entities a
dispatch extracts do not appear until the user searches again. That is a
pre-existing gap and a wider one than it looks (entity writes are redstring
streams, deliberately excluded from `read_since`), so this design does not try
to close it. It is worth knowing that a research dispatch will visibly move the
topic list and visibly *not* move the graph beside it, and worth a `BACKLOG.md`
entry if there is not one.

**2. What it is saying while it says it — in flight, assume it lands.** A round
is a turn and a turn is atomic, so nothing reaches the log until it completes.
`BACKLOG.md` B25 names this precisely and says the fix is the second channel
`on_activity` already gives the REPL. That streaming-turn-activity work is in
progress. **This design assumes it lands** and does nothing about it: a
dispatch's turn is a turn, so whatever narration turns get, dispatches get, and
building a parallel narration channel here would be a second answer to a
question already being answered.

**3. Is one running, is one queued, how did the last one go — new, and small.**
A `DispatchActivity` in `interfaces/web/`, shaped exactly like
`SeedingActivity`, which is shaped like `extraction.py`, which is shaped like
`activity.py`. Frame type `DISPATCH`. Per project, holding the running
dispatch, the queue, and the last finished one per topic. Plus the catch-up
read:

```
POST   /api/projects/{project_id}/topics/{topic_id}/dispatch   → 202
GET    /api/projects/{project_id}/dispatch                     → running + queued + last
POST   /api/projects/{project_id}/dispatch/cancel              → 200
```

`POST` body names the action (`research` | `understanding` | `lesson`). 202
because the work has not been done when it answers — the same reasoning
`start_auto_research`'s docstring gives. The response carries a dispatch id and
a queue position.

Cancel is per project, not per dispatch, matching
`ResearchSupervisor.cancel` — with the running dispatch stopping after its
current round or turn, and the queue cleared. A per-dispatch cancel that could
pull item three out of the middle of the queue is a nicety; it can wait.

**One trap on the client, and it is silent.** `decodeFrame` in
`infrastructure/sse/event-stream.ts` switches on the frame's `type`, and
anything with no explicit `case` falls through to `default:`, where it is
parsed as a log frame, fails `logFrameDto` + `isEventIndex`, and is **dropped
with no error**. A `DISPATCH` frame published by the server with no
`case 'Dispatch':` added to that switch is a feature that appears to do nothing
and logs nothing. The `Extraction` case already carries a comment recording
exactly this bug. Four places, in order: the `_sse` pump in `web/app.py`, a
`dispatchFrameDto` in `infrastructure/http/dto.ts` (with enum-ish fields kept
as `z.string()`, per the `topicFrameDto` precedent), a `{kind: 'dispatch'}`
variant on `FeedFrame` in `application/ports/event-stream.ts`, and the `case`
in `decodeFrame`.

**The Workers roster gains a kind.** `workers.py`'s `WorkerKind` is
`Literal["run", "turn", "extraction"]`; add `"dispatch"`. `Worker.detail` is
composed server-side by design ("composing it here keeps two front ends from
disagreeing"), so a dispatch's detail reads `understanding · spaced repetition`.
This is a widening of a `Literal` on a process-local dataclass — no event, no
migration.

## 6. Action 3, honestly: this is not a course

The owner asked to "create a course from the gathered research material and the
topic". Taken literally, this is the one part of the request the system has no
place for, and the reasons are structural rather than incidental.

**A course here is a view over a workflow preset, not a document.**
`GET /api/projects/{id}/course` calls `course_progress(preset, state, files)`,
which joins the preset's stage list, the project's current stage, and the
project's filesystem. There is no course object. There is a preset, a position,
and a directory of `/course/NN-*.md` artifacts.

**A project has exactly one, chosen once, and cannot change it.**
`Project.decide` refuses a second `SelectWorkflow` by name, and the reason in
the code is not squeamishness — "a run's whole audit trail is gated by one
preset's stage list; swapping it midway would leave decisions recorded against
rules that no longer exist". `NewProjectForm` therefore offers the choice only
at creation.

**Stages advance one at a time, forwards only, behind a human gate.**
`_advanced` refuses skipping ahead ("the failure the whole workflow engine
exists to prevent") and refuses going back. `advance_stage` floors at `ask` in
`TOOL_FLOORS` because *the stage boundary is the review gate*.

Put those together and a per-topic course is not expressible. It would need
either a second preset selection on a project that refuses one, or a stage that
runs once per topic in an aggregate whose entire purpose is that stages run
exactly once in order. Neither is a small change; both attack the thing the
workflow engine exists to guarantee.

**And the workflow is the right home for a real course — but it is less
finished than it looks.** Fifteen gated stages with declared artifacts and
coverage checks is what "make a course" means in this codebase, and the
skeleton is excellent: the stage/gate data model, the discriminated stage
union, `advance_stage` with its human gate, artifact paths and frontmatter, the
21-check library, `course_progress` and the stage rail are all built and
tested.

**What is not built is the part that writes anything.** Every stage carries a
`Generator(role=…, prompt_ref="prompts/tyler/candidates")` and most carry a
`Critic`, and **there is no resolver, no `prompts/` directory, and no loader**.
Outside the preset definitions, the only reference to `prompt_ref` anywhere is
`checks.py:1110`, which compares the *string* to detect a critic sharing a
generator's prompt. So the instructional-design intelligence of fifteen stages
is unwritten; a model working a stage is told only which files to write and
with what frontmatter. There is likewise no stage runner — nothing turns
"advance to `tyler.step1b.candidates`" into a model turn, so a human must sit
in a session and prompt each stage by hand. `Critic`, `ScreeningCritic`,
`adversarial_second_pass`, `amend_upstream`, `LoopPolicy` and `MaturityGate.rungs`
are all validated data that nothing executes.

This matters to the present design in one specific way: **"action 3 is nearly
built" is false in both directions.** It is not 80% built for topics (it is
0%), and the project-scoped course it would have inherited is itself missing
its generator prompts and its driver. Building a topic-scoped course on that
base would mean writing the prompt library and the stage driver first, which is
a much larger project than the one being asked for and should be chosen
deliberately if at all.

If the owner wants a real course about a topic, the path that works today is:
make a project for it, select a preset at creation, let the topic's material be
the source documents — and accept that each stage is driven by hand.

### The nearest good version: a lesson

What the owner probably wants from a button on a topic row is not twenty gated
stages. It is **one document a learner can work through**, produced from what
we know about this topic. That has a name in this codebase already, and all of
its machinery exists:

- `frontend/src/domain/lesson/widgets.ts` — four widget shapes (`flashcards`,
  `mcq`, `cloze`, `checklist`), readers that narrow an open record and default
  rather than throw.
- `frontend/src/presentation/lesson/LessonDocument.tsx` and the four renderers.
- `frontend/src/domain/lesson/attempt.ts` and
  `application/lesson/use-attempts.ts` — so these are interactive, with
  recorded attempts, not decorative.
- `research_team/application/components.py` — the server-side parser, the
  authoring reference, and `ComponentFeedback`, applied unconditionally per
  `composition.py:556` so a malformed widget is caught in *any* markdown the
  agent writes, preset or no preset.

So action 3 becomes: **write `/topics/<nn>-<slug>/lesson.md`, a markdown
document carrying `component:` fences.** One turn, `TopicSeeder`-shaped,
identical in structure to action 2 and differing in its prompt and its declared
outputs. It renders in the existing viewer with the existing widgets and the
existing attempt tracking.

*What would falsify this:* if the owner says "no, I mean a real course — the
staged, gated, artifact-bearing thing", then this feature is not a topic
dispatch at all. It is "create a project seeded from this topic", which is a
different and larger feature, and §9 lists it as the open question I could not
resolve.

### Why the widget system is unused, and the one honest fix

The owner's read — "we made a widget system and have not leveraged it" — is
right about the symptom and slightly off about the cause. The system is built
and wired; what is missing is that **nothing ever tells the model it exists**
outside a workflow preset.

`composition.py:628` calls `component_guidance(stage.outputs)`, and
`component_guidance` returns text only when a declared artifact type appears in
`COMPONENTS_FOR`. Outside a preset there is no stage, so there are no outputs,
so there is no guidance. The validator still catches a malformed widget; none
are ever written, because none are ever asked for.

**That gating is correct and this design does not touch it.**
`component_guidance`'s docstring is right: a stage writing source claims has no
use for two kilobytes of widget syntax, and a prompt carrying it anyway teaches
the model that most of its instructions do not apply to it. Blanket-injecting
the reference into every prompt is the obvious wrong answer.

**The fix is that `component_guidance` never required a stage.** Its signature
is `component_guidance(outputs: Iterable[Any])`, and it reads only
`output.artifact_type` and `getattr(output, "subtype", None)`. So a dispatch
action declares a tuple of `StageOutput`s of its own, and the same function
produces the same guidance under the same rule — the gating is preserved
exactly, keyed off the dispatch's declared outputs instead of a stage's.

The mapping, and this is where the two actions genuinely differ:

| Action | Declared output | In `COMPONENTS_FOR`? | Guidance |
|---|---|---|---|
| 2. Understanding | `SourceDossier` | No | **None, deliberately** |
| 3. Lesson | `Experience` + `EvidenceSpec` | Yes, both | `flashcards`, `cloze`, `checklist` (practice) and `mcq`, `cloze` (assessment) |

**Action 3 needs no new mapping.** `COMPONENTS_FOR` already carries
`EXPERIENCE: ("flashcards", "cloze", "checklist")` — "practice, not assessment;
recall and procedure, where being wrong costs nothing" — and
`EVIDENCE_SPEC: ("mcq", "cloze")` — "the components that have a right answer; a
deck is not evidence of anything". That split is exactly the one a lesson wants,
and it was written before this feature was asked for. Declaring both outputs is
the whole of the change.

**Action 2 should get no widget guidance, and this is a recommendation rather
than an oversight.** `SourceDossier` is absent from `COMPONENTS_FOR`, and it
should stay absent. A synthesis of what we know is explanation, and
`component_guidance`'s own closing line says so: "Prose is still right for
explanation. A component earns its place when the learner should *do*
something." A dossier padded with flashcards is a worse dossier. If the owner
wants the understanding document to be operable, the right answer is to dispatch
action 3 after action 2, not to widget-ise action 2.

**`Rubric`, `Criteria` and `TaxonomySelection` stay unregistered.** Nothing here
needs them, and `COMPONENTS_FOR`'s docstring already made the call — "telling a
model to express a rubric as a checklist would get a rubric-shaped checklist,
which is worse than prose". No argument in this design disturbs that.

**One real gap, and it is presentational.** Widgets render only in
`FileView.tsx`, which is keyed by `(session_id, path)` and lives in the session
route. The research view has no file viewer, so a lesson written by a dispatch
is reachable only if you know which session wrote it. **Action 3 is not done
until the topic detail can open its own documents.** That is a frontend route
plus a reuse of `useLesson`, and it is the largest single piece of work in this
design.

## 7. Why no new aggregate

The tempting move is a `TopicDispatch` aggregate: `DispatchRequested`,
`DispatchStarted`, `DispatchCompleted`, `DispatchFailed`, folding into a
durable queue. It is rejected for now, and the argument should be checkable.

**What an aggregate buys:** a queue that survives restart; "every dispatch this
topic ever had" as a fold rather than a projection nobody built; a place to put
B24's scoped fetch pre-authorization when it arrives.

**What it costs:** four events in the permanent vocabulary, a fourth supervisor
that must reconcile a persisted queue against process state on startup, and —
the expensive one — a decision about what to do with a stream that has a
`DispatchStarted` and no terminal event because the process died. `ResearchSupervisor`'s
docstring already refuses to guess at that, and refuses for a good reason:
"inventing one at startup would be this module claiming to know why a run it
never saw ended."

**And the log already answers the questions that matter.** What a dispatch did
is `FileWritten` and the topic's own events, timestamped and ordered, on the
session's stream. What is missing is only "somebody pressed a button", which is
process state and is answered by the catch-up route.

*What would change this:* the first time someone wants dispatch history — "what
have we ever asked about this topic, and when" — or the first time a lost queue
across a restart actually costs someone work. Then `TopicDispatch` is the right
answer and should be added deliberately, not retrofitted onto
`AutoResearchRun`. Note that if it arrives, `AutoRunStarted.topic_id` from §4
becomes redundant but stays readable, which is the correct kind of leftover.

## 8. The UI

### Where the control lives

On the topic row in `TopicList`, and in the topic detail dialog. A split
button, not three buttons — three buttons per row on a list of forty topics is
120 controls on a rail pane about 320px wide.

```
┌──────────────────────────────────────────────────────────┐
│ TOPICS                          all ▾   [ search      ]  │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ ⚠ How does spacing interval affect retention?        │ │
│ │   investigating · 3 sources · 2 open      [Dispatch ▾]│ │
│ ├──────────────────────────────────────────────────────┤ │
│ │   What counts as a primary source here?              │ │
│ │   open · 0 sources                        [Dispatch ▾]│ │
│ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘

  [Dispatch ▾] opens:
  ┌────────────────────────────────────┐
  │ Research and fetch sources         │   ← may ask to fetch
  │ Write our understanding            │
  │ Build a lesson                     │
  └────────────────────────────────────┘
```

"Build a lesson", not "Create a course" — §6. If the label says course, every
user will expect the `/course` route to change, and it will not.

### While it is running

```
│ │ ⚠ How does spacing interval affect retention?        │ │
│ │   investigating · 3 sources · 2 open                 │ │
│ │   ⟳ research · round 2 · reading source 4      [stop]│ │
```

The chip's text is `Worker.detail` composed server-side, so the roster on the
landing page and the row here say the same words. Round counters arrive as
domain events; the "reading source 4" half arrives on the turn-activity channel
once that lands (§5), and reads as `⟳ research · round 2` until then.

### Three at once

```
│ │ ⟳ research · round 2 · reading source 4        [stop] │ │
   …
│ │ ⧗ queued · 1st                              [cancel] │ │
   …
│ │ ⧗ queued · 2nd                              [cancel] │ │
```

Queue position, per row, live. The pane header carries the aggregate — `TOPICS
· 1 running, 2 queued` — so a reader who scrolled away from the running row
still knows. `[stop]` on the running one is the project cancel; `[cancel]` on a
queued one drops it from the deque without touching what is running.

### When it asks to fetch

The approval interrupt is the one thing that must not be quiet, because
everything behind it stalls:

```
│ │ ⏸ research · waiting for you                          │ │
│ │   fetch https://example.org/paper.pdf   [allow] [deny]│ │
```

Inline on the row, and mirrored in the existing approvals surface. `BACKLOG.md`
B17 notes the browser offers only approve and reject though `edit` works end to
end — unchanged here, and worth closing separately.

### When it fails

A turn failure appends `TurnFailed` and discards the turn. The row shows the
error with a retry, and it *persists* — a chip that vanishes on the next render
is how a user concludes the button does nothing:

```
│ │ ✕ understanding · failed · model timed out    [retry] │ │
```

The failure must not skip the `finally` that releases the project.
`TopicSeeder.seed` already gets this right and says why: "the failure this
exists to prevent is a run that dies holding the project — locked out of every
later seed or turn over a crash that cost seconds and produced nothing."

### Empty, and first use

A topic with no linked sources and no findings should not offer "Write our
understanding" as an equal option — there is nothing to synthesise, and the
result will be the model's own prior knowledge presented as project findings.
Grey it with a reason ("nothing gathered for this topic yet") and lead with
research. This is the only place in the design where an action is conditionally
disabled, and it is worth it: the failure it prevents is confabulation that
looks like a deliverable.

## 9. What I am not proposing, and what I could not decide

### Not proposing

- **Concurrent sessions in a project.** §2(a).
- **A `TopicDispatch` aggregate,** for now. §7.
- **A per-topic course, or a second workflow preset per project.** §6.
- **Registering `Rubric`, `Criteria` or `TaxonomySelection` components.** §6.
- **Lifting `fetch`'s floor, or a blanket auto-approval budget.** B24 names the
  right shape and this is not it. Attended dispatch instead.
- **A new narration channel for dispatch turns.** B25's work is in flight; a
  dispatch's turn is a turn.
- **Resuming a dispatch after a restart.** The queue is empty and the UI says
  so. §2.

### What the composition root gains, and the guard that will catch it

`create_app` gains two parameters: `dispatch` (the `DispatchQueue`) and
`dispatch_activity` (the side channel). Both follow the established pattern of
`None` meaning "this build did not wire it", with the routes answering 404
rather than 403 the way `auto-research` does.

**`tests/interfaces/test_web_entrypoint.py`, added in #67, is what makes this
safe.** It reads `inspect.signature(create_app)` and asserts `web.py` supplies
every parameter, precisely because this bug has now shipped three times — a
dependency added to the factory, every test constructing the app itself and
passing it, and the one call production makes not passing it, so every test is
green and the running server answers 503. `corpus` went out that way and so did
`topic_repository`.

**The guard does not cover `main.py`.** The REPL is a second composition site,
and a dispatch is exactly the kind of thing a REPL user would want (`/dispatch
<topic> understanding`, beside the existing `/research`). Either wire it there
in the same change, or decide deliberately that dispatch is web-only and say so
— what must not happen is a third composition site silently missing a
dependency that only the web guard checks. Extending that guard to `main.py` is
its own small piece of work and is worth doing while the reasoning is fresh.

`WorkerRoster` also gains the dispatch queue as a fourth in-flight source, and
`workers.py` warns about exactly this: a composition root handing over
mismatched halves of a channel shows a roster that disagrees with its own pane,
and nothing in either signature catches it. The queue and the activity channel
must be the same object's two views, wired once.

### The one other backend change outside the dispatch path

`component_guidance` needs to be reachable without a `Stage` — it already is,
by signature; what is needed is a caller. Concretely, `turn_middleware` in
`composition.py` gains a branch for "this session is running a dispatch with
declared outputs", parallel to its existing "this session is running a preset
stage" branch, and both end up calling the same function. `ComponentFeedback`
stays unconditional and unchanged.

### Order of work

1. **Action 2**, end to end: route, `DispatchQueue`, `DispatchActivity`, the
   topic-row control, `/topics/<nn>-<slug>/understanding.md`. No new event, no
   widget question, no fetch question. It proves the whole path.
2. **The topic document viewer.** Without it, actions 2 and 3 write files
   nobody can find. Largest single piece.
3. **Action 3 as a lesson**, once 2 exists to render it — the incremental cost
   is a prompt and two declared outputs.
4. **Action 1**, attended, with `AutoRunStarted.topic_id` and its
   schema-evolution case.
5. B24's scoped pre-authorization, separately, if unattended fetching is ever
   wanted.

### Open questions for the owner

1. **Does "course" mean a course?** Everything in §6 turns on this. If the
   answer is "yes, the staged gated thing", this feature is "create a project
   from this topic" and is a different, larger design. If the answer is "I want
   something a person can learn from", it is a lesson and §6 stands. **This is
   the one I could not resolve and the most expensive to get wrong.**
2. **Should a dispatch be allowed to fetch while nobody is watching?** §3 ships
   it attended. If the answer is "it must run overnight", B24 becomes a
   prerequisite rather than a follow-up.
3. **Queue, or refuse?** §2 recommends a queue and names the cheaper start.
4. **Should action 2 overwrite or accumulate?** A second "write our
   understanding" on the same topic — does it rewrite `understanding.md`, or
   write `understanding-2.md`? Overwrite is my recommendation, because the
   filesystem is event-sourced and every prior version is already recoverable by
   scrubbing, so a second file would be a second mechanism for history that
   already exists. But it is the owner's document.
