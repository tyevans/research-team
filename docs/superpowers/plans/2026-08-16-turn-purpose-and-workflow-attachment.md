# Turn purpose and workflow attachment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session states what kind of work it is doing, and the workflow attaches only to the kinds that should drive it — so an autonomous research round stops being handed stage 1's methodology, `advance_stage`, and a tool denylist that hides the corpus.

**Architecture:** A required `SessionPurpose` on `StartSession`/`SessionStarted`, folded onto `SessionState`. `running_workflow` — the single function both per-turn hooks already share so they cannot disagree — returns `None` for every purpose but `CHAT` and `WORKFLOW_STAGE`. No caller passes a boolean; the answer falls out of which class started the session, and a required argument means a seventh call site cannot be added without the type checker asking.

**Tech Stack:** Python 3.12+, pydantic v2, eventsource-py (event-sourced aggregates, `decide`/`evolve`), pytest/anyio, uv.

**Spec:** `docs/design/turn-purpose-and-workflow-attachment.md` — read it before Task 1. It carries the verification of the three defects and the argument for why the four-line grant-registry alternative was rejected.

## Global Constraints

- **Four gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository. **This change touches no frontend source**, so the frontend gate and the committed-console rebuild are not in play — do not run them, and do not touch `research_team/interfaces/web/static`.
- **Never run two `vitest` processes at once.** Not applicable here (no frontend work), noted so nobody starts one.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned. A comment restating the code is worse than none.
- **Commit messages carry the reasoning that does not fit in a comment:** what was considered and rejected, what the change costs, what is deliberately left undone.
- **If a test would pass with the change reverted, say so in its docstring.** Prove a test red before trusting it green.
- **An event no projection handles counts as APPLIED, not rejected.** So "the request succeeded" and "the run started" prove nothing. Assert on data — a row exists, a field carries the value the event carried.
- **This is a deliberate breaking change to stored payloads,** and the project is pre-release with no real data. Per `CLAUDE.md`'s Events section: say so in the field's docstring, say what no longer loads, and update the schema-evolution test to assert the **refusal** rather than deleting a case.
- **The template to mirror throughout is `project_id`.** The identical break was made for it — `domain/events.py:44-60`, `domain/commands.py:38-43`, `read_models.py:141-145`, `application/summaries.py:35-50`, and `tests/infrastructure/test_schema_evolution.py:370`. Match its docstrings' shape and candour rather than inventing a new house style.
- **Do not run the full test suite** on tasks 1–2 (~10 minutes); run the files you touched. The controller runs the full suite once before the PR.

---

### Task 1: `SessionPurpose` on the command, the event, and the fold

**Files:**
- Modify: `research_team/domain/session.py` (add the enum; add `purpose` to `SessionState`; fold it in `evolve`)
- Modify: `research_team/domain/commands.py:33-47` (`StartSession`)
- Modify: `research_team/domain/events.py:38-60` (`SessionStarted`)
- Modify: `research_team/domain/__init__.py` (export `SessionPurpose`)
- Test: `tests/domain/test_session.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `research_team.domain.SessionPurpose`, a `StrEnum` with members `CHAT = "chat"`, `WORKFLOW_STAGE = "workflow_stage"`, `RESEARCH_ROUND = "research_round"`, `TOPIC_SEEDING = "topic_seeding"`, `TOPIC_DISPATCH = "topic_dispatch"`. `StartSession.purpose: SessionPurpose` and `SessionStarted.purpose: SessionPurpose`, both required with no default. `SessionState.purpose: SessionPurpose` — see Step 3 for why this one *does* carry a default and why that is not a contradiction.

- [ ] **Step 1: Write the failing test for the enum reaching the state**

Add to `tests/domain/test_session.py`:

```python
async def test_a_session_remembers_what_kind_of_work_it_is_for():
    """The purpose reaches the state, which is the only place anything reads it.

    Would pass with `decide` returning a hard-coded CHAT, which is why the
    second half uses a non-default purpose: a build that ignored the command
    and folded the enum's first member would answer CHAT here and fail.
    """
    session_id = uuid4()
    session = Session.create_new(session_id)
    session.execute(
        StartSession(
            session_id=session_id,
            system_prompt="p",
            model_name="m",
            project_id=uuid4(),
            purpose=SessionPurpose.RESEARCH_ROUND,
        )
    )
    assert session.state.purpose is SessionPurpose.RESEARCH_ROUND
```

Import `SessionPurpose` from `research_team.domain` alongside the existing imports in that file.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/domain/test_session.py::test_a_session_remembers_what_kind_of_work_it_is_for -v`
Expected: FAIL — `TypeError`/`ValidationError` on the unexpected `purpose` keyword (`StartSession` sets `extra="forbid"`, `commands.py:30`).

- [ ] **Step 3: Add the enum, the command field, the event field and the fold**

In `research_team/domain/session.py`, above `SessionState` (import `StrEnum` from `enum`; `domain/workflow.py:38` is the existing precedent for a `StrEnum` in this layer):

```python
class SessionPurpose(StrEnum):
    """What kind of work a session exists to do.

    The one thing that decides whether a workflow attaches to its turns. A
    `StrEnum` rather than a `Literal` because it is named at six production
    call sites and read in `composition.py`; a bare string would let a typo
    reach the fold and read as an unknown purpose, which -- see
    `WORKFLOW_DRIVEN` in `composition.py` -- fails safe into "no workflow" and
    would therefore be silent.

    Deliberately not a boolean. `drives_workflow: bool` was the cheaper shape
    and was rejected: three of these five are unattended in different ways
    (a round works a topic queue, a seeding turn opens topics, a dispatch turn
    writes one topic up), and collapsing them loses the ability to answer
    "which sessions were research rounds" -- the first question anyone
    debugging this feature asks.
    """

    CHAT = "chat"
    """A person, at a keyboard, in the web console or the REPL."""

    WORKFLOW_STAGE = "workflow_stage"
    """`StageRunner`, driving one stage of the selected preset."""

    RESEARCH_ROUND = "research_round"
    """One round of `ResearchRunDriver`, working the topic queue."""

    TOPIC_SEEDING = "topic_seeding"
    """`TopicSeeder`, opening a project's initial topics in one turn."""

    TOPIC_DISPATCH = "topic_dispatch"
    """`TopicDispatcher`, writing up what is known about one topic."""
```

Add to `SessionState`, beside `project_id` (`session.py:77`):

```python
    purpose: SessionPurpose = SessionPurpose.CHAT
    """What kind of work this session is for. See `SessionPurpose`.

    Defaulted here and required on the event, which looks inconsistent and is
    not: `initial_state()` takes no arguments (eventsource 0.12), so every
    field on the state needs a value that is true before any event exists --
    the same reason `session_id` and `project_id` are `| None` above despite
    being required on `SessionStarted`. The default is unreachable in practice:
    the fold replaces the state wholesale on `SessionStarted`, so no started
    session ever carries it.
    """
```

In `evolve`, extend the `SessionStarted` case (`session.py:314-325`) to capture and set it:

```python
        case SessionStarted(
            system_prompt=prompt,
            model_name=model,
            project_id=project_id,
            purpose=purpose,
        ):
            return SessionState(
                session_id=event.aggregate_id,
                status="started",
                system_prompt=prompt,
                model_name=model,
                project_id=project_id,
                purpose=purpose,
            )
```

In `research_team/domain/commands.py`, add to `StartSession` after `project_id`:

```python
    purpose: SessionPurpose
    #: What kind of work this session is for. Required and undefaulted, for the
    #: same reason `project_id` above is: a session whose purpose nobody stated
    #: cannot be expressed as a request in the first place, so `decide` never
    #: has to reject one and no caller can forget. Defaulting it to `CHAT` was
    #: considered and rejected -- it makes the safe value the silent one, so a
    #: caller who forgot would attach a workflow to an unattended run, which is
    #: precisely the defect this field exists to remove.
```

In `research_team/domain/events.py`, add to `SessionStarted` after `project_id`:

```python
    purpose: SessionPurpose
    """What kind of work this session is for. See `domain.session.SessionPurpose`.

    Required and deliberately not defaulted, matching `project_id` above.

    This is a **breaking change to stored payloads**: a `SessionStarted`
    written before this field existed no longer loads, and there is no
    validator to translate one. A default would have to be `CHAT`, and
    asserting that every session ever recorded was a person at a keyboard is a
    claim about history this build cannot make -- the auto-research sessions in
    any existing database are exactly the ones it would be wrong about.
    Chosen over a shim while the project is pre-release and holds no real data;
    `tests/infrastructure/test_schema_evolution.py` pins the refusal.
    """
```

Wire the import in both modules and export `SessionPurpose` from `research_team/domain/__init__.py` (add to the imports from `.session` and to `__all__`).

- [ ] **Step 4: Run the test and watch it pass**

Run: `uv run pytest tests/domain/test_session.py -v`
Expected: PASS. Other tests in this file that construct `StartSession` will now fail on the missing argument — fix them in this step by passing `purpose=SessionPurpose.CHAT`, which is what they were.

- [ ] **Step 5: Pin the refusal in the schema-evolution test**

Add to `tests/infrastructure/test_schema_evolution.py`, directly after `test_session_started_without_project_id_no_longer_loads` (`:370`) and modelled on it — read that test first, including its docstring's note about why it writes against a fresh id and why it depends on `started`:

```python
async def test_session_started_without_purpose_no_longer_loads(repository, started, db_path):
    """The second deliberate break in this file, and it reads like the first.

    `SessionStarted` gained a required `purpose` so that a workflow attaches
    only to the kinds of turn that should drive it. A payload written before
    the field existed cannot be translated: the only available default is
    `CHAT`, and the sessions in an old database this build would be wrong
    about are exactly the auto-research ones the field was added to fix.

    So the payload is rejected at read. Pinned here because "old data stops
    loading" should cost a test to change. Affordable only because the project
    is pre-release and holds no real data.
    """
    session_id = uuid4()
    await _write_old_event(
        db_path,
        session_id,
        version=1,
        event_type="SessionStarted",
        payload={
            "system_prompt": "p",
            "model_name": "m",
            "project_id": str(uuid4()),
        },
    )
    with pytest.raises(ValidationError):
        await repository.load(session_id)
```

Match `_write_old_event`'s actual signature and the sibling test's call shape exactly — read it rather than trusting the sketch above; if the helper takes different keywords, use its keywords.

- [ ] **Step 6: Prove it red, then green**

Run: `uv run pytest tests/infrastructure/test_schema_evolution.py -v`
Expected: the new test PASSES (the field is already required from Step 3). **Prove it is not vacuous**: temporarily give `SessionStarted.purpose` a `= SessionPurpose.CHAT` default, re-run, and confirm the new test FAILS. Remove the default. Note in the commit message that this was done.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/domain/ tests/infrastructure/test_schema_evolution.py -q
git add -A && git commit -m "Let a session say what kind of work it is for

A turn is handed the workflow on the strength of one question --
does this session's project have a preset -- which cannot tell an
autonomous research round from a person at a keyboard. `SessionPurpose`
is the fact that question was missing.

Required on both the command and the event, undefaulted. A `CHAT`
default was the cheaper option and is the wrong one twice over: it
makes the safe value the silent one, so a forgotten call site attaches
a workflow to an unattended run; and as a *stored* default it would
assert that every session ever recorded was a person, which is wrong
about exactly the auto-research sessions this exists to fix.

So old SessionStarted payloads no longer load. Deliberate, written
into the field, and pinned as a refusal in the schema-evolution test
rather than by deleting the case -- and that test was proved red by
temporarily defaulting the field, not assumed green.

Nothing reads the purpose yet; this commit only makes it sayable."
```

---

### Task 2: Every call site states its kind

**Files:**
- Modify: `research_team/application/session_service.py:468-527` (`start_in_project`)
- Modify: `research_team/interfaces/web/app.py:2712` (join route → `CHAT`), `:2767` (auto-research route → `RESEARCH_ROUND`)
- Modify: `research_team/application/topic_seeding.py:134` (→ `TOPIC_SEEDING`)
- Modify: `research_team/application/topic_dispatch.py:337` (→ `TOPIC_DISPATCH`)
- Modify: `research_team/application/stage_runner.py:463` (→ `WORKFLOW_STAGE`)
- Modify: `research_team/interfaces/cli/repl.py:321` (→ `CHAT`)
- Modify: `tests/conftest.py:214` (the `project_session` helper)
- Modify: every other test that calls `start_in_project` or builds `StartSession`/`SessionStarted` directly — the files are `tests/integration/test_advance_stage_gate.py`, `tests/integration/test_stage_is_prompted.py`, `tests/integration/test_workflow_stage.py`, `tests/infrastructure/test_persistence.py`, `tests/application/test_session_service_project.py`, `tests/application/test_session_service.py`, `tests/application/test_topic_seeding.py`, `tests/interfaces/test_repl_project.py`, `tests/infrastructure/test_check_telemetry.py`, `tests/integration/test_course_artifacts.py`, `tests/integration/test_research_run_end_to_end.py`, `tests/application/test_stage_runner.py`, `tests/domain/test_project.py`, `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `SessionPurpose` from Task 1.
- Produces: `SessionService.start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID` — positional-or-keyword, **no default**. Later tasks rely on this signature and on `tests/conftest.py`'s helper accepting an optional `purpose` keyword that defaults to `SessionPurpose.CHAT`.

- [ ] **Step 1: Write the failing test**

Add to `tests/application/test_session_service_project.py`:

```python
async def test_the_session_carries_the_purpose_it_was_started_for(service):
    """A run's session is a research round, and the session itself says so.

    The point of the whole change is that this fact is on the session rather
    than inferred from a registry, so this asserts the stored state and not
    the argument it was given.
    """
    project = ...  # follow this file's existing project-creation shape
    session_id = await service.start_in_project(project, SessionPurpose.RESEARCH_ROUND)
    session = await service.repository.load(session_id)
    assert session.state.purpose is SessionPurpose.RESEARCH_ROUND
```

Use whatever this file already uses to create a project and to reach the session repository — read the neighbouring tests and match them; do not invent a fixture.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/application/test_session_service_project.py::test_the_session_carries_the_purpose_it_was_started_for -v`
Expected: FAIL — `start_in_project()` takes 2 positional arguments but 3 were given.

- [ ] **Step 3: Widen `start_in_project` and pass it through**

In `session_service.py`, change the signature to `async def start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID:` and add to the docstring:

```
        `purpose` is required and undefaulted so that every caller states what
        it is starting. Six call sites do, and the type checker is what stops a
        seventh from quietly inheriting whichever default looked harmless --
        see `SessionPurpose` for why the harmless-looking one is `CHAT` and why
        that is the bug rather than the fallback.
```

Pass `purpose=purpose` into the `StartSession(...)` on the first-join branch (`:502-509`).

**The fork branch is the half that is easy to miss, and it is verified, not suspected.** There are exactly two `StartSession` issuers in the whole codebase — checked with `grep -rn "StartSession(" research_team/`. The second is inside `_fork_files_from`, at `session_service.py:592-601`, which is the second-and-later-session path.

So `_fork_files_from` gains a `purpose: SessionPurpose` keyword-only parameter (it is already keyword-only past `session_id`, `:568-576`), threaded from `start_in_project` and passed into its `StartSession` at `:593`. A build that wires only the first-join branch gives every project past its first session the default purpose, **and every test that creates a single session still passes** — the file's own comment at `:517-521` records that exact mistake being made before with `project_name`, which is why this was checked rather than assumed. Add a comment on the new parameter saying so.

- [ ] **Step 4: Update the six production call sites**

Each gets the purpose named in the Files list above. At `app.py:2767` (the auto-research route) add:

```python
            # RESEARCH_ROUND, and this is the line that detaches the workflow:
            # `running_workflow` returns None for it, so the rounds get neither
            # `advance_stage` nor the stage prompt nor the stage tool denylist.
            # See docs/design/turn-purpose-and-workflow-attachment.md.
            session_id = await service.start_in_project(project_id, SessionPurpose.RESEARCH_ROUND)
```

- [ ] **Step 5: Update the test call sites**

Give `tests/conftest.py`'s helper an optional keyword so the common case stays short and the split stays expressible:

```python
async def project_session(
    service, name: str | None = None, purpose: SessionPurpose = SessionPurpose.CHAT
) -> UUID:
```

...passing it through to `start_in_project`. Match the helper's real name and signature — read `tests/conftest.py:200-215` first.

Then fix the remaining direct callers. Most are `CHAT`; the exceptions are `tests/application/test_topic_seeding.py` (`TOPIC_SEEDING`), `tests/application/test_stage_runner.py` (`WORKFLOW_STAGE`), and `tests/integration/test_research_run_end_to_end.py` (`RESEARCH_ROUND`) — a test that drives one of those code paths should say the purpose that path really uses, or it is testing a shape production never produces.

- [ ] **Step 6: Run the affected tests**

Run: `uv run pytest tests/application tests/domain tests/interfaces/test_repl_project.py -q`
Expected: PASS. Then `uv run pytest tests/integration tests/infrastructure -q`.
Do **not** run the full suite here.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A && git commit -m "Make every session say what it is for

Six production call sites, each of which already knew which kind of
turn it was starting and had nowhere to put it. Required rather than
defaulted so the type checker asks the seventh.

The fork branch of start_in_project needed it as well as the first-join
branch, and that is the one worth naming: a build that wires only the
first join gives every session past a project's first the default
purpose, and every test that creates a single session still passes.
The same mistake was made here before with project_name, and the
comment recording it is why this one was checked.

Nothing reads the purpose yet. Still no behaviour change."
```

---

### Task 3: The workflow attaches only to the kinds that drive it

This is the task that carries the change. The two before it were plumbing.

**Files:**
- Modify: `research_team/composition.py:1107-1159` (`running_workflow`)
- Test: `tests/integration/test_workflow_attachment.py` (create)

**Interfaces:**
- Consumes: `SessionState.purpose` (Task 1), populated call sites (Task 2).
- Produces: module-level `WORKFLOW_DRIVEN: frozenset[SessionPurpose]` in `composition.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_workflow_attachment.py`. It needs a project that has selected a preset **and advanced past its first stage**, because the first stage is one of the five that declares `tools=` and would hide the third defect. Follow `tests/integration/test_workflow_stage.py` and `test_stage_is_prompted.py` for how this repo builds a composed app around a project with a preset — read both before writing.

```python
async def test_a_research_round_is_not_given_the_workflow(...):
    """The three defects, one assertion each.

    All three fail today and pass after. Reverting the `running_workflow`
    change fails all three again -- checked, not assumed.

    (3) is the one a test written only from the bug report would miss, and it
    is the one that silently breaks rounds: `StageMiddleware` is a denylist
    over the union of every stage's declared tools, so on any stage that
    declares none -- the large majority -- `list_sources`, `read_source` and
    `graph_search` are all withdrawn, and a round cannot read the corpus it
    exists to read.
    """
    session = ...  # started with purpose=SessionPurpose.RESEARCH_ROUND
    tools = await turn_tools(session)
    middleware = await turn_middleware(session)

    assert not any(t.name == "advance_stage" for t in tools)
    assert not any(m.name == "stage_gate" for m in middleware)
    bound = {t.name for t in <the tools actually bound for this turn>}
    assert {"list_sources", "read_source", "graph_search"} <= bound


async def test_a_person_still_gets_the_workflow(...):
    """The mirror, and what stops the fix being "delete StageMiddleware".

    Same project, same stage, `purpose=CHAT`: `advance_stage` is bound, the
    stage gate is installed, and the system message names the current stage.
    """
```

For assertion (3), reach the *bound* set — the tools that survive `StageMiddleware._permits`, not the raw registration. `StageMiddleware.awrap_model_call` (`stage_middleware.py:143-152`) is what narrows them, so either drive a turn and inspect the request, or assert directly that no `stage_gate` middleware is present *and* separately that the middleware, when constructed for a `CHAT` session on this stage, does withdraw those three. The second is a weaker claim honestly stated; prefer the first if the harness in the sibling integration tests makes it reachable. **Say in the docstring which one you did.**

Also assert the system message the chain produces contains neither `## Current stage` nor a distinctive phrase from `WORKFLOW_PROMPT`.

- [ ] **Step 2: Run and watch all three fail**

Run: `uv run pytest tests/integration/test_workflow_attachment.py -v`
Expected: FAIL on each of the three assertions. Record the actual failure output in the commit message — it is the measurement of the defect.

- [ ] **Step 3: The early return**

In `composition.py`, above `running_workflow`:

```python
WORKFLOW_DRIVEN = frozenset({SessionPurpose.CHAT, SessionPurpose.WORKFLOW_STAGE})
"""The purposes a workflow attaches to.

An allowlist rather than a denylist of the unattended kinds, so a purpose
added later gets no workflow until somebody says it should. The failure
directions are not symmetric: a new unattended kind that wrongly *keeps* the
workflow is the bug this whole change removes and is invisible -- nothing
raises, the stage prompt simply argues with the round prompt and the model
picks one. A new kind that wrongly *loses* it is a missing stage prompt, which
whoever added the kind sees on the first turn.
"""
```

And at the top of `running_workflow`:

```python
        if session.state.purpose not in WORKFLOW_DRIVEN:
            # An autonomous round, a seeding turn or a dispatch turn. Three
            # things follow from returning None here, and the third is the one
            # nobody reported: no `advance_stage` (floored at `ask`, so an
            # unattended call is an approval nobody answers), no stage prompt
            # arguing with the round's own instructions, and no stage tool
            # denylist -- which on any stage declaring no `tools` of its own
            # was withdrawing `list_sources`, `read_source` and `graph_search`
            # from a round whose entire job is reading the corpus.
            return None
```

Placed **before** the `project_id is None` check so the purpose decides first and the reasoning reads in one direction.

- [ ] **Step 4: Run and watch it pass**

Run: `uv run pytest tests/integration/test_workflow_attachment.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Prove the revert**

Comment out the early return, re-run, confirm all three assertions in the first test fail again and the mirror test still passes. Restore. Say in the commit message that this was done.

- [ ] **Step 6: Run the neighbouring suites**

Run: `uv run pytest tests/integration tests/application/test_topic_seeding.py tests/application/test_topic_dispatch.py -q`
Expected: PASS. A stage-runner or advance-gate test that breaks here is a real signal — `WORKFLOW_STAGE` must still get everything it had.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A && git commit -m "Stop handing the workflow to turns that are not doing it

An auto-research round is a turn on the run's session, and every turn
asked one question -- does this session's project have a preset. So a
round got stage 1's methodology in its system message while its user
message asked it to investigate a topic, and the system message won.
That is the reported symptom: runs 'advance into phase 0/1 by
themselves'.

Two more followed from the same wiring and neither was reported. It
got `advance_stage`, floored at `ask`, so an unattended round could
reach an approval nobody would answer. And it got StageMiddleware's
denylist, which is the union of every stage's declared tools -- only
five stages across the three presets declare any -- so on every other
stage `list_sources`, `read_source` and `graph_search` were withdrawn
from a round whose whole job is reading the corpus. That one is worst
on a project past intake, which is where a project spends its life.

An allowlist, not a denylist, because the two failure directions are
not symmetric: a new unattended kind that keeps the workflow is silent,
and one that loses it is a missing stage prompt somebody sees at once.

Rejected: keying off the fetch-grant registry. Four lines, ships today,
and wrong three ways -- it fixes only the run (seeding and dispatch
register no grant), it makes 'has a fetch grant' mean 'is not doing
workflow work' so granting a person hosts would silently drop their
workflow, and the grant is registered inside the driver while the
session is started outside it, leaving a window where a turn would see
the workflow. Reasoning in
docs/design/turn-purpose-and-workflow-attachment.md.

Proved by reverting: the three assertions fail again with the early
return commented out."
```

---

### Task 4: Say which sessions were rounds, in the read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py:137-145` (`SessionSummaryRow`), `:211-222` (`_on_started`)
- Modify: `research_team/application/summaries.py:27-52` (`SessionSummary`), and `to_summary` at `read_models.py:163`
- Test: `tests/infrastructure/test_read_models.py` (or wherever the session projection is already tested — find it)

**Interfaces:**
- Consumes: `SessionStarted.purpose`.
- Produces: `SessionSummaryRow.purpose` and `SessionSummary.purpose`, both `SessionPurpose`, required, declared **above** any defaulted field (`SessionSummary` is a dataclass — `summaries.py:46-49` records this exact constraint).

- [ ] **Step 1: Write the failing test**

The row must carry the value the event carried — per `CLAUDE.md`, "the projection ran" proves nothing:

```python
async def test_a_rounds_session_is_recorded_as_a_round():
    """Asserts the stored value, not that the projection didn't raise.

    An event no projection handles counts as APPLIED, so a test that only
    checked the row exists would pass with the handler never reading `purpose`.
    """
    # ... start a session with purpose=RESEARCH_ROUND, let the projection settle
    assert row.purpose is SessionPurpose.RESEARCH_ROUND
```

- [ ] **Step 2: Run it, watch it fail**

Expected: FAIL — no such attribute.

- [ ] **Step 3: Add the column and the field**

`SessionSummaryRow.purpose: SessionPurpose`, with a docstring mirroring `project_id`'s at `:142-145` — required, and a row without one could only come from a database written before the field existed, which this build does not load because the event itself refuses to validate.

In `_on_started`, add `purpose=event.purpose` beside `project_id`, and extend that handler's existing comment: this is likewise the only event that carries it, so no later handler can change it and a replay from any checkpoint re-derives the same value.

Add `purpose` to `SessionSummary` and to `to_summary`.

- [ ] **Step 4: Run it, watch it pass**

Run: `uv run pytest tests/infrastructure/ -q`

- [ ] **Step 5: Verify against a database that predates the change**

**Non-negotiable, and it is the gate a fresh database cannot give you.** `CLAUDE.md`'s read-model section exists because this shipped once.

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
```

Then start the app with the printed `AGENT_DB=` line and load `/api/sessions`.

**Expect this to fail, and expect it to be correct that it fails.** `purpose` is a required column with no default, so `generate_additive_migration` refuses the set categorically; an empty `session_summary_rows` is dropped and recreated, and a populated one re-raises and asks for `/rebuild`. But the rebuild replays `SessionStarted` payloads that have no `purpose`, which Task 1 made unloadable — so against a real database **the answer is that this database cannot be carried forward at all.**

That is the accepted outcome, not a bug to engineer around: pre-release, no real data, and the event break was taken deliberately in Task 1. What this step is for is *finding out in a worktree rather than in the owner's console.* **Record what actually happened** — which error, at which point, with the real database's row count — in the commit message and in a short note appended to `docs/design/turn-purpose-and-workflow-attachment.md` under a new "What this does to an existing database" heading. If it somehow succeeds, that is a more interesting result and must be reported rather than quietly accepted.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A && git commit -m "Record what kind of session each row was

Two lines at the one moment they are free. 'Which sessions were
research rounds' is the first question anyone debugging this asks, and
adding the column later means a backfill against events that would have
to be replayed anyway.

Measured against a copy of the real database rather than a fresh one,
per the rule in CLAUDE.md: <what actually happened, verbatim>."
```

---

### Task 5: Tell a round that gathering sources is the job

**Files:**
- Modify: `research_team/application/research_round.py:38-66` (`ROUND_INSTRUCTIONS`)
- Test: `tests/application/test_research_round.py` (find the existing file for this module)

**Interfaces:** Consumes nothing; changes prompt text only.

- [ ] **Step 1: Why this ships with the rest**

Until Task 3, the stage prompt was accidentally supplying a round with a sense of mission. Removing it leaves `ROUND_INSTRUCTIONS` as the only instruction the model gets, and it currently mentions `link_source` only in a list of tools. Shipping Task 3 without this leaves a round told *less* than it used to be told, which will read as a regression.

- [ ] **Step 2: Edit the prompt**

Add a paragraph making source gathering a first-class outcome. It must stay consistent with what the module already says — the existing text about `_keeper` ("a page you fetch in this round is kept in the corpus for you") is accurate and must not be contradicted. Something in the register of the existing prose:

```
"Gathering is part of the work, not preparation for it. A round that "
"finds and links a source this topic did not have has produced "
"something, and `sources_linked` is counted exactly as findings are. "
"Reading widely and linking nothing is the empty round described above."
```

Update the docstring below the constant to say why this was added — that the stage prompt used to supply this implicitly, and that removing the workflow from research rounds is what made it necessary to say out loud.

- [ ] **Step 3: Check the tests that assert on this text**

Run: `uv run pytest tests/application/ -k round -v`
Some test may assert on `ROUND_INSTRUCTIONS`' content. If one does, update it; if none does, say so in the commit message rather than adding one — a test asserting a prompt contains a sentence is a change-detector, and this repo would rather have the absence noted than the test.

- [ ] **Step 4: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A && git commit -m "Say that gathering sources is the round's job

The stage prompt used to supply a round with a sense of mission by
accident. With the workflow detached, ROUND_INSTRUCTIONS is the only
thing a round is told, and it named link_source only in a tool list --
so a round would have been told less than before, which reads as a
regression in the thing that was just fixed.

<note here whether any test asserted on this text>"
```

---

## Self-Review

**Spec coverage.** §2's recommendation → Tasks 1–3. §2.1's event break and its documentation → Task 1 Steps 3, 5, 7. §2.1's optional read-model column → Task 4 (taken; the owner confirmed "in"). §3's "same piece of work, not a separate one" prompt edit → Task 5. §4's named test → Task 3 Step 1, including the mirror. §4's listed test changes → Task 2 Step 5. §4's fixture trap → Task 2 Step 5 (the helper takes a purpose so a suite of all-chat sessions cannot hide the split) and Task 3 Step 1 (starts its own session, not from `project_session`). §5's break list → Tasks 1, 2, 4 and this plan's Global Constraints. §2.2 and §2.3's rejected alternatives → recorded in Task 3's commit message, which is where `git log` will want them.

**No spec requirement is unimplemented.**

**Type consistency.** `SessionPurpose` is the name in every task. `start_in_project(project_id, purpose)` is positional-or-keyword in Tasks 2, 3 and 4. `WORKFLOW_DRIVEN` is named only in Task 3 and in the `SessionPurpose` docstring written in Task 1 — Task 1's docstring forward-references it, which is deliberate and correct once Task 3 lands.

**Known soft spots, flagged rather than hidden.** Task 2 Step 3's fork branch is described from `session_service.py:513-524` without having read `_fork_files_from`'s body; the implementer must read it and may find the session is created differently than assumed. Task 3 Step 1's assertion (3) has two possible shapes and the plan says to prefer the stronger and to state which was used. Task 4 Step 5 predicts a failure it has not observed and says to report what actually happens.
