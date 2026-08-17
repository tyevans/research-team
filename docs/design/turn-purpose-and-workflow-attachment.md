# What kind of work a turn is, and which kinds the workflow drives

Read out of the working tree on branch `main` (at `155ca2c`) at
`research_team/composition.py`, `research_team/domain/session.py`,
`research_team/domain/commands.py`, `research_team/domain/events.py`,
`research_team/application/session_service.py`,
`research_team/application/research_round.py`,
`research_team/application/research_run.py`,
`research_team/application/topic_seeding.py`,
`research_team/application/topic_dispatch.py`,
`research_team/application/stage_runner.py`,
`research_team/application/autonomy.py`,
`research_team/infrastructure/agent/stage_middleware.py`,
`research_team/interfaces/web/app.py` and `research_team/workflows/`.
Line numbers are pointers, not contracts.

The ask, in the repo owner's words: *"auto research just shouldn't have the
workflow attached. during auto research it should be interested in
investigating the topics that are defined. it has no reason to see or advance
the workflows."* And, separately: topic investigation and source gathering
should be a phase that is genuinely not the workflow's first stage.

And the licence, also in their words: *"we don't need to care about existing
contracts or data, we can do anything that expresses what we want the
cleanest."* Nothing below is shaped by compatibility. Where a break is
deliberate it is written down, per `CLAUDE.md`; that is the only obligation
left.

## 1. What was verified, and where the brief was wrong

Each claim below was read out of the code named, not inferred.

- **A round is a turn on the run's session.** `composition.py:2141-2145`
  builds `TopicRoundRunner(topic_repository, lambda prompt: turns.run(session_id,
  prompt))`. `research_round.py`'s `ROUND_INSTRUCTIONS` is workflow-free and
  correct — it talks about `record_finding`, `link_source`, `open_topic` and
  nothing else. **Verified.**
- **Both per-turn hooks key off `running_workflow`.** `turn_tools`
  (`composition.py:1325`) is `workflow_tools` + `granted_tools`;
  `workflow_tools` (`:1161`) returns `()` only when `running_workflow` is
  `None`. `turn_middleware` (`:1336`) appends `StageMiddleware` (`:1441`) on
  the same condition. `running_workflow` (`:1107`) reads only
  `session.state.project_id` → the project's `preset_id`. It has no notion of
  who asked for the turn. **Verified.**
- **`advance_stage` is floored at `ask`.** `autonomy.py:67-71`,
  `TOOL_FLOORS[ADVANCE_STAGE_TOOL] = "ask"`, and the docstring says why: it *is*
  the review gate. So an unattended round that calls it hits an approval
  nobody answers. **Verified.**
- **The stage prompt lands in the system message of every round.**
  `StageMiddleware._system_message` (`stage_middleware.py:178-186`) *appends*
  `stage_prompt(...)` to whatever was there, and composition
  (`composition.py:1441-1478`) builds those instructions from the stage's
  methodology text, `stage_artifact_instructions`, `WORKFLOW_PROMPT` and
  `component_guidance`. So the system message says "you are in stage
  `ubd.step0.intake`, here is its methodology and where to write its
  artifacts" while the user message says "work this topic and record findings".
  This is the user-visible symptom. **Verified.**
- **The denylist claim is right, and slightly worse than the brief says.**
  `managed_tools_for` (`stage_middleware.py:88-101`) unions every stage's
  `tools` and subtracts `CORE_TOOLS`. Across the three presets, `tools=` appears
  exactly five times (`ubd.py:66`, `addie.py:79`, `hybrid.py:67,105,164`) and
  the union is `{list_sources, read_source, graph_search}`. `_permits`
  (`:156-166`) keeps a tool if it is not managed *or* the current stage claims
  it — so on any stage that declares no `tools` at all, which is the large
  majority, all three are withdrawn. A research round on such a stage cannot
  read the corpus or search the graph. **Verified.** The extra detail: the three
  withdrawn tools are precisely the corpus-reading tools a round most needs, and
  the stages that *do* declare them (`ubd.step0.intake`,
  `hybrid.step1.framing`, …) are exactly the intake stages — so the failure is
  worst on a project that has moved past intake, which is the state a project
  spends most of its life in.
- **One correction to the brief.** It lists "a person's turn, an auto-research
  round, a topic-seeding turn, a topic-dispatch turn, and a stage turn" as
  "at least four kinds"; it is five, and the fifth matters because the CLI has
  its own entry point (`interfaces/cli/repl.py:321`) that will need the same
  argument as the web route. Nothing else in the trace was wrong.
- **One thing the brief did not say, and the design depends on it.** A run's
  session is *not* minted by the driver. It is minted by the HTTP route —
  `app.py:2767`, `session_id = await service.start_in_project(project_id)` —
  and handed to `research.start(...)`. Likewise the join route mints one at
  `app.py:2712`, `TopicSeeder` at `topic_seeding.py:134`, `TopicDispatcher` at
  `topic_dispatch.py:337`, `StageRunner` at `stage_runner.py:463`, the CLI at
  `repl.py:321`. **Every kind of turn already has its own session, and every
  one of the six call sites already knows which kind it is starting.** That is
  the seam this design uses, and it is a fact about the current code rather
  than something the design has to create.

## 2. The recommendation

**Put the purpose on the session, at `StartSession`/`SessionStarted`, with no
default; make `running_workflow` return `None` for every purpose that is not
`chat` or `workflow_stage`.**

Concretely:

```python
# domain/session.py (or a new domain/purpose.py if the import graph objects)
class SessionPurpose(StrEnum):
    CHAT = "chat"                      # a person, in the web app or the CLI
    WORKFLOW_STAGE = "workflow_stage"  # StageRunner, driving one stage
    RESEARCH_ROUND = "research_round"  # ResearchRunDriver's rounds
    TOPIC_SEEDING = "topic_seeding"    # TopicSeeder
    TOPIC_DISPATCH = "topic_dispatch"  # TopicDispatcher
```

`StartSession.purpose: SessionPurpose` — required, no default, exactly as
`project_id` is required today and for the same stated reason
(`commands.py:44-47`: so that the wrong thing "cannot be expressed as a
request in the first place"). `SessionStarted.purpose: SessionPurpose`,
folded into `SessionState.purpose` by `evolve` (`session.py:313-325`).
`SessionService.start_in_project(project_id, purpose)` — positional-or-keyword,
no default, so the six call sites named in §1 each state their kind and a
seventh cannot be added without the type checker asking.

Then `running_workflow` (`composition.py:1107`) gains one early return:

```python
if session.state.purpose not in WORKFLOW_DRIVEN:   # {CHAT, WORKFLOW_STAGE}
    return None
```

That is the whole of the behavioural change. Both consumers already share
`running_workflow` for the stated reason that they must not disagree
(`composition.py:1121-1125`), and putting the test there keeps that property.
No caller passes a `False`; the answer falls out of which class started the
session.

**Which purposes see the workflow, and why.**

- `CHAT` — **yes.** A person is at the keyboard; `advance_stage`'s `ask` floor
  resolves against a human who is there to answer it, which is the entire
  premise of `TOOL_FLOORS`' note on that tool. The stage prompt is orientation
  they asked for by selecting a workflow.
- `WORKFLOW_STAGE` — **yes.** This turn *is* the workflow. `StageRunner`
  (`stage_runner.py:411-449`) loops over stages and takes a fresh session per
  stage; removing the middleware here would leave the stage runner running
  stages with no stage prompt, which is not a fix, it is the same bug pointed
  the other way.
- `RESEARCH_ROUND` — **no.** The user's ask, and all three defects in §1.
- `TOPIC_SEEDING` — **no.** `TopicSeeder.seed` opens a broad set of topics for
  a subject in one turn (`topic_seeding.py:110-134`). It has no stage, and a
  stage's artifact-path instructions would tell it to write files it has no
  business writing.
- `TOPIC_DISPATCH` — **no**, and this one is the least obvious. A dispatch
  writes `topics/<nn>-<slug>/understanding.md` (`topic_dispatch.py:130-138`)
  from a prompt that names that path. A `StageMiddleware` running alongside
  appends `stage_artifact_instructions` naming a *different* path, so the
  system message and the user message disagree about where the output goes.
  Nothing raises; the file lands wherever the model resolves the conflict.
  This is the same defect as the research round's, unreported only because
  dispatch is newer and less used. **Unverified** that it has been observed in
  the wild — it is read off the two prompts, not off a transcript.

### 2.1 What this costs

Three things, stated rather than discovered later.

**It is an event-shape break, and a deliberate one.** Every `SessionStarted`
already stored has no `purpose`, and a required field means those payloads no
longer load. Per `CLAUDE.md`'s Events section this must be written into the
field's docstring (as `SessionStarted.project_id` already writes its own break),
and `tests/infrastructure/test_schema_evolution.py` must gain a case asserting
the **refusal** — an old-shaped payload raises — rather than losing a case.
The alternative, defaulting to `CHAT`, is cheaper and wrong: it makes the safe
value the silent one, so any future caller that forgets gets a workflow
attached to an unattended run, which is the bug being fixed.

**The purpose is fixed for the life of the session, and a session outlives one
turn.** For five of the five kinds that is exactly right — each driver mints
its own session, verified at the six call sites in §1 — but it means "purpose"
is genuinely a *session* property and calling it a *turn* property would be a
lie. If someone later wants a person to take over a run's session mid-flight
and chat in it, they will need a `SessionPurposeChanged` event, not a
per-turn argument. That is a real future cost and it is not paid now.

**One more field on the row, if the console should show it.** The session
summary projection writes `project_id` on `SessionStarted` and nowhere else
(`read_models.py:211-222`, with a comment about why that is the only place).
Adding `purpose` beside it is two lines — and per `CLAUDE.md`'s read-model rule
it must be checked against a copy of a real database via
`research_team.infrastructure.persistence.local_copy`, not a fresh one. I
recommend adding it: "which sessions were research rounds" is the first
question anyone debugging this feature will ask, and the column is free at the
same moment the event changes. If the console does not need it yet, skip it —
but then skip it *knowingly*, because adding it later means a backfill.

### 2.2 The four-line alternative, and why not

`running_workflow` could return `None` when `resolved_grants.get(session.aggregate_id)`
is not `None`. The driver registers a grant for every run at start —
`research_run.py:204-220`, deliberately even for a read-only run with no hosts,
"so `GrantRegistry.is_unattended` can find it" — and releases it in `_stop`
and in a `finally` (`:273`). `composition.py:1237`'s `_keeper` already treats a
registered grant as *this codebase's* definition of "nobody is watching this
session". Four lines, no event change, no migration, ships today.

It is the right *emergency* fix and the wrong *design*, for three reasons that
compound:

1. It fixes one of the three unattended kinds. Seeding and dispatch register
   no grant, so both keep the workflow attached and dispatch keeps the
   two-paths-in-one-prompt defect of §2.
2. It makes "has a fetch grant" mean "is not doing workflow work", which is a
   coincidence of the current wiring rather than a fact about either concept.
   The day someone grants fetch hosts to a person's chat session — a plausible
   feature, "let this conversation reach these domains" — that person silently
   loses their workflow, and the symptom is a model that has forgotten which
   stage it is in.
3. The grant is registered *inside* `ResearchRunDriver.run` and the session is
   started *outside* it, in the route (`app.py:2767`). So there is a window —
   the `attach_project` call and the `research.start` hand-off between them —
   where the session exists, is not registered, and any turn on it would see
   the workflow. Nothing runs a turn in that window today. Nothing stops one.

If a fix is wanted before the design lands, do it as the four lines *and* file
the design; do not let the four lines close the question.

### 2.3 Why not fix it at the two consumers, or at `turns.run`

At the consumers: `workflow_tools` and `turn_middleware` would each need the
same test, which is precisely the "a run gated by half a workflow" failure
`running_workflow`'s own docstring says it exists to prevent
(`composition.py:1121-1125`). Rejected.

At `turns.run(session_id, prompt, purpose=...)`: this reads attractive —
purpose is arguably a property of the *ask* — but `TurnSupervisor.run`
(`turn_supervisor.py:114`) hands off to `SessionService.run_turn`, which builds
the agent through `tools_provider`/`middleware_provider` that receive a
`Session` and nothing else (`deep_agent.py:394`, `composition.py:1594-1595`).
Threading a purpose through would mean widening that provider protocol, and the
providers already have a `Session` in hand — so putting the fact on the session
costs nothing extra and reaches them for free. Rejected, but it is the closest
runner-up and the reason it loses is mechanical, not conceptual.

## 3. The second half: an investigation phase

**Recommendation: do not add a stage, and do not add a phase. Investigation is
already first-class and is not a workflow concept; the change that makes it
work is the one above plus one prompt edit.**

The argument, from what is already there:

- Topics *are* the investigation model. `TopicSeeder` opens them
  (`topic_seeding.py`), `TopicAttention` and the queue decide which one is
  starved, `ResearchRunDriver` works them in rounds until novelty decays
  (`research_run.py`), `TopicDispatcher` writes up what was learned. Nothing in
  that path is a stage and nothing in it should be.
- Source gathering is already automatic in exactly the place the user wants it.
  `_keeper` (`composition.py:1237`) keeps every page a round fetches into the
  corpus, without extraction, *because* nobody is watching — and it is bound
  only on a granted (i.e. run) session. "Source gathering is always worth
  having up front" is already true of the auto-research path and only of it.
- The workflow's stage 0 is a *different* activity that happens to share a
  word. `ubd.step0.intake` is "Corpus ingestion and domain concept mapping"
  (`ubd.py:57-58`), and it is one of the five stages that declares
  `tools=("list_sources", "read_source", "graph_search")` (`ubd.py:66`). It
  reads a corpus that already exists and maps it onto the unit being designed.
  It is not "go find out about this subject"; it is "take stock before
  designing". A new stage 0 would duplicate topics with a worse data model —
  stages have no queue, no novelty decay, no per-topic findings — for the sake
  of a name.

So the user's "topic investigation should be a stage genuinely separate from
the workflow's first stage" is granted by *removing* the accidental
attachment, not by adding a stage. Once a research round no longer carries
`ubd.step0.intake`'s prompt, investigation *is* the separate phase: it runs
before or beside the workflow, on its own sessions, with its own tools and its
own stopping rule.

The one prompt edit: `ROUND_INSTRUCTIONS` (`research_round.py:38`) currently
says nothing about source gathering being expected, because until now the
stage prompt was accidentally supplying a sense of mission. With that gone the
round prompt is the only instruction, and it should say plainly that gathering
and linking sources is a first-class outcome of a round — it already mentions
`link_source` and `_keeper`'s behaviour, so this is a sentence of emphasis, not
a new contract.

**This is the same piece of work, not a separate one**, and that is the
recommendation: shipping the purpose change without the prompt edit leaves a
round that has been told less than it used to be told, which will read as a
regression.

## 4. Tests

A test that would pass with the change reverted is worthless, and
`CLAUDE.md`'s Events section adds a sharper form of it here: an event no
projection handles counts as APPLIED, so "the run started" and "the request
succeeded" prove nothing about any of this.

**The new test that fails today and passes after** — the one that carries the
whole change:

`tests/composition/test_workflow_attachment.py::test_a_research_round_is_not_given_the_workflow`
Build the composition root against a project that has selected `hybrid.default`
and advanced past its first stage (so the current stage declares no `tools`).
Start a session with `purpose=RESEARCH_ROUND`. Call the real `turn_tools` and
`turn_middleware` with that session and assert three things, each of which is
one of §1's three defects:

1. no tool named `advance_stage` in `turn_tools`;
2. no `StageMiddleware` in `turn_middleware` — and, stronger, that the system
   message the middleware chain produces contains neither `## Current stage`
   nor any of `WORKFLOW_PROMPT`;
3. that `list_sources`, `read_source` and `graph_search` all survive into the
   bound tool set.

Today all three fail. Reverting the change fails all three again. (3) is the
one that would be missed by a test written only from the user's complaint, and
it is the one that silently breaks rounds.

The mirror test, on the same fixture with `purpose=CHAT`, asserting all three
of those things are *present*, is what stops the fix from being "delete
`StageMiddleware`".

**Tests that must change:**

- Every `start_in_project` call site in tests — `tests/conftest.py:214` is the
  shared one (`project_session` fixture), plus
  `tests/application/test_session_service_project.py` (many),
  `tests/application/test_stage_runner.py:957`. The fixture should pass `CHAT`
  and a second fixture should offer `RESEARCH_ROUND`, because a suite where
  every session is a chat session cannot see the split.
- `tests/infrastructure/test_schema_evolution.py` — a case asserting an old
  `SessionStarted` payload without `purpose` is **refused**, per §2.1.
- Any test constructing `StartSession` or `SessionStarted` directly.
- `tests/application/test_topic_seeding.py` and `test_topic_dispatch.py` if
  they drive `start_in_project` through a fake session service; the fake's
  signature changes.

**The fixture trap `CLAUDE.md` names, applied here.** The dominant test shape
in this repo seeds through `project_session`, which will pass `CHAT`. A test
written on top of that fixture *cannot* observe the research-round path, in
exactly the way the entity-definitions tests could not observe a missing
`graphs.open`. At least one test per purpose must start from a session that
fixture did not create.

## 5. What breaks, in one list

- `SessionStarted` payloads written before this change no longer load.
  Deliberate; documented in the field; asserted as a refusal in the
  schema-evolution test. Pre-release, no real data.
- `SessionService.start_in_project` grows a required argument — six production
  call sites (`app.py:2712`, `app.py:2767`, `topic_seeding.py:134`,
  `topic_dispatch.py:337`, `stage_runner.py:463`, `repl.py:321`) and every test
  that starts a session.
- `session_summary_rows` gains a `purpose` column if §2.1's optional half is
  taken — `apply_schema` reconciles it, and it must be exercised against a copy
  of a real database, not a fresh one.
- Behaviourally: seeding, dispatch and research-round turns lose the stage
  prompt, `advance_stage`, and the tool denylist. Chat and stage turns are
  unchanged. Nothing in the HTTP contract changes.
