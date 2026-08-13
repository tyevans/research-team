"""Driving a stage to its boundary, and what must never cross one.

Driven against a *real* `SessionService`, a real `Project` aggregate and a real
`ProjectWorkflow`, with only the turn itself faked. That split is deliberate and
it is where the value is: the runner's whole job is deciding what to do about
committed state, so a test that faked the session service would be asserting
that the runner talks to a mock in the order the mock expects. What is faked is
the model, which is what `test_topic_dispatch.py` fakes for the same reason --
except that a stage turn's output is several files with frontmatter, and
driving that through a tool-calling fake model would put a hundred lines of
message plumbing between each test and the thing it is testing. `_Turns` below
writes what a turn would have written, through the same service.

The four turn endings of `stage-boundaries.md` §3 each have a test, and three
of the four assert that *nothing advanced*. Those three are the design.
"""

import ast
import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect

from research_team.application.autonomy import ADVANCE_STAGE_TOOL, AutonomyPolicy
from research_team.application.course import course_progress
from research_team.application.ports import ApprovalDecision, ApprovalRequest
from research_team.application.session_service import TurnOutcome
from research_team.application.stage_runner import (
    QUIET_TURNS_BEFORE_STOPPING,
    StageBudget,
    StageRunner,
    stage_exit_condition,
)
from research_team.application.turn_supervisor import TurnCancelled
from research_team.domain import (
    CreateProject,
    Project,
    ProjectStageAdvanced,
    StageChecksEvaluated,
    ToolCallDecided,
)
from research_team.domain.project import SelectWorkflow
from research_team.domain.workflow import (
    ArtifactType,
    Check,
    DecideStage,
    DecisionGate,
    Generator,
    LedgerGate,
    Preset,
    ScreeningCritic,
    ScreenStage,
    SpecifyStage,
    StageOutput,
)
from research_team.infrastructure.persistence.project_workflow import ProjectWorkflow

# --- a preset small enough to drive ------------------------------------------


def _specify(stage_id: str, artifact: ArtifactType, *checks: Check) -> SpecifyStage:
    return SpecifyStage(
        id=stage_id,
        name=stage_id,
        spine=4,
        scope_level="unit",
        outputs=(StageOutput(artifact_type=artifact, cardinality="1..n"),),
        generator=Generator(role="author", prompt_ref="p/gen"),
        checks=checks,
    )


def _no_outputs(stage_id: str) -> DecideStage:
    """A stage declaring nothing. Last, so a run can reach it.

    `stage-boundaries.md` §3.4's rule guards a case no shipped preset has, so
    it has to be built here to be tested at all.
    """
    return DecideStage(
        id=stage_id,
        name=stage_id,
        spine=5,
        scope_level="unit",
        generator=Generator(role="analyst", prompt_ref="p/decide"),
        gate=DecisionGate(reviewer_role="sponsor", presents=("RequestBrief",)),
    )


def _self_reviewing(stage_id: str, generator_stage: str) -> ScreenStage:
    """A screen that reviews its own generator: one of the two invariants."""
    return ScreenStage(
        id=stage_id,
        name=stage_id,
        spine=4,
        scope_level="unit",
        outputs=(StageOutput(artifact_type=ArtifactType.VERDICT_LEDGER, cardinality="1..n"),),
        critic=ScreeningCritic(
            role="screener",
            prompt_ref="p/screen",
            criterion_doc="doc",
            separate_context=False,
        ),
        gate=LedgerGate(reviewer_role="sponsor", presents=("VerdictLedger.*",)),
        checks=(
            Check(
                check="shared.self_review_separation",
                params={"generator_stage": generator_stage},
            ),
        ),
    )


def _preset(*stages: Any, preset_id: str = "test.runner") -> Preset:
    return Preset(
        id=preset_id,
        name="Runner test preset",
        version="1",
        description="Built for these tests only.",
        spine_positions=tuple(sorted({stage.spine for stage in stages})),
        stages=tuple(stages),
        produces="design",
    )


TWO_STAGES = _preset(
    _specify("s.one", ArtifactType.INTENT),
    _specify("s.two", ArtifactType.EVIDENCE_SPEC),
    _no_outputs("s.end"),
)

STAGE_ONE_ARTIFACT = "/course/00-intent.md"
STAGE_TWO_ARTIFACT = "/course/01-evidence-spec.md"
"""`stage_number` is the stage's index, so the first stage's files are `00-`."""


def _artifact(artifact_type: str, stage: str) -> str:
    return f"---\nartifact_type: {artifact_type}\nstage: {stage}\n---\n\nbody\n"


@pytest.fixture(autouse=True)
def _preset_is_findable(monkeypatch):
    """The runner resolves its preset from `PRESETS`, as the composition root does.

    Registered for the duration of a test rather than shipped, because a preset
    built to exercise a budget has no business in the product's list -- and
    `test_stage_exit.py` already establishes that every shipped preset is held
    to rules this one would fail.
    """
    from research_team.application import stage_runner

    monkeypatch.setitem(stage_runner.PRESETS, TWO_STAGES.id, TWO_STAGES)


# --- fakes -------------------------------------------------------------------


class _Approvals:
    """An `ApprovalPort` that answers from a script and records what it saw."""

    def __init__(self, *answers: ApprovalDecision) -> None:
        self._answers = list(answers)
        self.requests: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return self._answers.pop(0) if self._answers else ApprovalDecision(type="approve")


class _Turns:
    """A turn that writes what it was told to write, through the real service.

    Each entry in `script` is what one turn does: a mapping of path to content,
    an exception to raise, or an empty mapping for a turn that wrote nothing.
    The script is consumed in order and runs dry as an empty turn, so a test
    that under-specifies gets the quiet-turn stop rather than an IndexError
    that says nothing about the design.
    """

    def __init__(self, service, *script: Any) -> None:
        self._service = service
        self._script = list(script)
        self.inputs: list[str] = []

    async def run(self, session_id: UUID, user_input: str) -> TurnOutcome:
        self.inputs.append(user_input)
        step = self._script.pop(0) if self._script else {}
        if isinstance(step, BaseException):
            raise step
        before = len(await self._service.history(session_id))
        for path, content in step.items():
            await self._service.write_file(session_id, path, content)
        after = len(await self._service.history(session_id))
        return TurnOutcome(
            reply="done",
            turn_index=1,
            from_index=before + 1,
            to_index=max(after, before + 1),
        )


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
async def application(build_applications, fake_model):
    return await build_applications(model=fake_model)


@pytest.fixture
async def service(application):
    return application.service


@pytest.fixture
async def project_id(service):
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="course"))
    aggregate.execute(SelectWorkflow(preset=TWO_STAGES))
    await service.projects.save(aggregate)
    return aggregate.aggregate_id


@pytest.fixture
def policy():
    """Default-`auto` with the floor left alone, which is how a session starts.

    `advance_stage` therefore reads `ask`: `TOOL_FLOORS` raises a permissive
    default and never lowers a strict one.
    """
    return AutonomyPolicy(default="auto")


@pytest.fixture
def workflows(service):
    return lambda project_id: ProjectWorkflow(service.projects, project_id)


def _runner(service, turns, workflows, approvals, policy, **budget):
    return StageRunner(
        service, turns, workflows, approvals, policy, StageBudget(**budget) if budget else None
    )


async def _advances(service, project_id) -> list[ProjectStageAdvanced]:
    """Every `ProjectStageAdvanced` on the project's stream, read back from the store.

    From the store rather than from folded state, because the state records
    only where the project ended up: a run that advanced and was somehow rolled
    back would look identical to one that never advanced, and it is the
    *appends* the guarantee is about.
    """
    envelopes = await collect(
        service.projects.event_store.read_stream(StreamId(project_id, Project.aggregate_type))
    )
    return [
        envelope.event
        for envelope in envelopes
        if isinstance(envelope.event, ProjectStageAdvanced)
    ]


# --- the exit condition ------------------------------------------------------


def test_a_stage_missing_an_artifact_is_not_satisfied():
    condition = stage_exit_condition(TWO_STAGES, TWO_STAGES.stages[0], {})
    assert condition.missing == (STAGE_ONE_ARTIFACT,)
    assert not condition.satisfied


def test_a_stage_with_every_artifact_present_and_parsing_is_satisfied():
    condition = stage_exit_condition(
        TWO_STAGES,
        TWO_STAGES.stages[0],
        {STAGE_ONE_ARTIFACT: {"content": _artifact("Intent", "s.one")}},
    )
    assert condition.satisfied and condition.missing == ()


def test_an_artifact_naming_the_wrong_type_fails_the_condition():
    """Present, parses, real artifact type, wrong one.

    The path-based checks downstream would read this as the `Intent` the stage
    owed. Failing here is the difference between a reviewer being told the
    stage is done and being told which file is not what it claims.
    """
    condition = stage_exit_condition(
        TWO_STAGES,
        TWO_STAGES.stages[0],
        {STAGE_ONE_ARTIFACT: {"content": _artifact("EvidenceSpec", "s.one")}},
    )
    assert condition.malformed == (STAGE_ONE_ARTIFACT,)
    assert not condition.satisfied


def test_an_artifact_with_no_frontmatter_fails_the_condition():
    condition = stage_exit_condition(
        TWO_STAGES, TWO_STAGES.stages[0], {STAGE_ONE_ARTIFACT: {"content": "just prose"}}
    )
    assert condition.malformed == (STAGE_ONE_ARTIFACT,)


def test_a_stage_declaring_no_artifacts_is_never_satisfied():
    """§3.4. Otherwise such a stage is finished the instant it is entered.

    No shipped preset has one, so this guards a case one preset edit away --
    and the cost of not guarding it is a preset that silently skips a stage.
    """
    condition = stage_exit_condition(TWO_STAGES, TWO_STAGES.stages[2], {})
    assert condition.declared == () and not condition.satisfied


def test_an_invariant_failure_refuses_rather_than_failing_quietly():
    preset = _preset(
        _specify("s.gen", ArtifactType.INTENT),
        _self_reviewing("s.screen", "s.gen"),
        _no_outputs("s.end"),
    )
    condition = stage_exit_condition(preset, preset.stages[1], {})
    assert condition.refused and not condition.satisfied


def test_advisory_findings_do_not_fail_the_condition():
    """`stage_exit.py`: findings inform, they do not block.

    Would pass with the change reverted only if the condition ignored findings
    entirely -- which is what it must do for everything but invariants, so this
    is the test that stops someone tightening it into a veto.
    """
    preset = _preset(
        _specify(
            "s.one",
            ArtifactType.INTENT,
            Check(check="shared.orphan", params={"artifact_type": "Intent"}),
        ),
        _specify("s.two", ArtifactType.EVIDENCE_SPEC),
        _no_outputs("s.end"),
    )
    condition = stage_exit_condition(
        preset,
        preset.stages[0],
        {STAGE_ONE_ARTIFACT: {"content": _artifact("Intent", "s.one")}},
    )
    assert condition.review.findings
    assert not condition.review.blocked
    assert condition.satisfied


# --- the four ways a turn ends -----------------------------------------------


async def test_a_turn_that_wrote_the_artifacts_reaches_the_gate_and_advances(
    service, project_id, workflows, policy
):
    """Ending one: the model wrote what the stage owed. The only one that advances."""
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(
        service,
        {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")},
        {STAGE_TWO_ARTIFACT: _artifact("EvidenceSpec", "s.two")},
    )

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert [outcome.stage_id for outcome in run.stages] == ["s.one", "s.two", "s.end"]
    assert [outcome.advanced for outcome in run.stages] == [True, True, False]
    assert run.stages[-1].stopped_because == "no_outputs"
    assert len(approvals.requests) == 2

    state = (await service.projects.load(project_id)).state
    assert state.current_stage == "s.end"


async def test_a_turn_that_wrote_nothing_advances_nothing(
    service, project_id, workflows, policy
):
    """Ending two: the model ran out of things to say.

    Nothing in a `TurnOutcome` tells this apart from ending one, which is the
    reason the runner reads committed files rather than the turn's report.
    """
    approvals = _Approvals()
    turns = _Turns(service, {}, {}, {})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert run.stages[0].stopped_because == "quiet"
    assert run.stages[0].turns == QUIET_TURNS_BEFORE_STOPPING
    assert approvals.requests == []
    assert await _advances(service, project_id) == []


async def test_a_failed_turn_advances_nothing(service, project_id, workflows, policy):
    """Ending three: the turn raised and `_record_failure` appended a marker."""
    approvals = _Approvals()
    turns = _Turns(service, RuntimeError("model unreachable"), RuntimeError("again"))

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert run.stages[0].stopped_because == "failed"
    assert "model unreachable" not in run.stages[0].detail  # the *last* one is named
    assert approvals.requests == []
    assert await _advances(service, project_id) == []


async def test_a_cancelled_turn_advances_nothing_and_is_not_retried(
    service, project_id, workflows, policy
):
    """Ending four, emphatically. A human who stopped a turn did not ask for another.

    Asserts on the outcome rather than on `_is_cancellation`, which matches on
    a type name: if that predicate stops matching, this fails as "the run
    counted a cancellation as a failure and started another turn", which is the
    behaviour that matters.
    """
    approvals = _Approvals()
    turns = _Turns(service, TurnCancelled(uuid4()), {STAGE_ONE_ARTIFACT: "never reached"})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert run.stages[0].stopped_because == "cancelled"
    assert len(turns.inputs) == 1
    assert await _advances(service, project_id) == []


# --- what stops an advance ---------------------------------------------------


async def test_a_stage_whose_artifacts_are_absent_never_has_its_gate_posed(
    service, project_id, workflows, policy
):
    """However many turns end. §8.4's first behavioural requirement."""
    approvals = _Approvals()
    turns = _Turns(service, *[{"/notes/scratch.md": "not a course file"}] * 6)

    run = await _runner(
        service, turns, workflows, approvals, policy, max_turns_per_stage=6
    ).run(project_id)

    assert run.stages[0].stopped_because == "budget"
    assert STAGE_ONE_ARTIFACT in run.stages[0].detail
    assert approvals.requests == []
    assert await _advances(service, project_id) == []


async def test_an_invariant_failure_stops_the_run_without_posing_a_gate(
    service, project_id, workflows, policy, monkeypatch
):
    """`stage_exit.py`'s rule, at the runner: refuse rather than ask.

    There is nothing here for a human to weigh -- a self-screening critic
    passes nearly everything and looks like a working filter -- so posing it
    would be asking for a rubber stamp.
    """
    from research_team.application import stage_runner

    preset = _preset(
        _specify("s.gen", ArtifactType.INTENT),
        _self_reviewing("s.screen", "s.gen"),
        _no_outputs("s.end"),
    )
    monkeypatch.setitem(stage_runner.PRESETS, preset.id, preset)
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="c"))
    aggregate.execute(SelectWorkflow(preset=preset))
    await service.projects.save(aggregate)

    approvals = _Approvals()
    turns = _Turns(service, {"/course/00-intent.md": _artifact("Intent", "s.gen")})
    run = await _runner(service, turns, workflows, approvals, policy).run(
        aggregate.aggregate_id
    )

    # Stage one advances; the screen behind it refuses before anyone is asked.
    assert run.stages[-1].stopped_because == "invariant"
    assert "self_review_separation" in run.stages[-1].detail
    assert len(approvals.requests) == 1  # stage one's, and no second


async def test_an_invariant_failure_refuses_even_when_the_gate_is_unattended(
    service, project_id, workflows, monkeypatch
):
    """§4.5: the unattended run still has a floor, and this is it.

    The two invariants are the failures that would otherwise produce a course
    claiming reviews it cannot evidence, so `advance_stage: auto` does not
    reach them.
    """
    from research_team.application import stage_runner

    preset = _preset(
        _specify("s.gen", ArtifactType.INTENT),
        _self_reviewing("s.screen", "s.gen"),
        _no_outputs("s.end"),
    )
    monkeypatch.setitem(stage_runner.PRESETS, preset.id, preset)
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="c"))
    aggregate.execute(SelectWorkflow(preset=preset))
    await service.projects.save(aggregate)

    unattended = AutonomyPolicy(default="auto")
    unattended.relax_all(include_stage_gates=True)
    approvals = _Approvals()
    turns = _Turns(service, {"/course/00-intent.md": _artifact("Intent", "s.gen")})

    run = await _runner(service, turns, workflows, approvals, unattended).run(
        aggregate.aggregate_id
    )

    assert run.stages[-1].stopped_because == "invariant"
    assert approvals.requests == []


async def test_a_rejected_gate_stops_the_run_and_leaves_the_stage_where_it_was(
    service, project_id, workflows, policy
):
    """§4.6. The alternative -- feed it back and retry -- is where a spin comes from."""
    approvals = _Approvals(ApprovalDecision(type="reject", message="the intents are thin"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert run.stages[0].stopped_because == "rejected"
    assert run.stages[0].detail == "the intents are thin"
    assert await _advances(service, project_id) == []
    assert (await service.projects.load(project_id)).state.current_stage is None


async def test_a_denied_advance_stops_without_asking_anybody(service, project_id, workflows):
    """`deny` is the difference between "ask me" and "no": nobody is consulted."""
    denied = AutonomyPolicy(default="auto")
    denied.set(ADVANCE_STAGE_TOOL, "deny")
    approvals = _Approvals()
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, denied).run(project_id)

    assert run.stages[0].stopped_because == "rejected"
    assert approvals.requests == []
    assert await _advances(service, project_id) == []


# --- the guarantee -----------------------------------------------------------


async def test_no_stage_advanced_without_a_decision_recorded_against_it(
    service, project_id, workflows, policy
):
    """The amended form of the test `workflow-engine.md` §3.2 asked for.

    §3.2 asked for "drive a stage to completion and check no `ProjectStageAdvanced`
    was appended", which was the right test for a design where the driver may
    not execute the command. `stage-boundaries.md` §4.4 narrows the rule to
    *no advance with no decision behind it*, which is strictly stronger and is
    what this asserts: every `ProjectStageAdvanced` on the project's stream is
    matched by a `ToolCallDecided` on some session, for `advance_stage`, that
    let it through.

    Would pass trivially against a runner that never advanced, so
    `test_a_turn_that_wrote_the_artifacts_reaches_the_gate_and_advances` is
    what makes this test's subject exist.
    """
    approvals = _Approvals(ApprovalDecision(type="approve"), ApprovalDecision(type="approve"))
    turns = _Turns(
        service,
        {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")},
        {STAGE_TWO_ARTIFACT: _artifact("EvidenceSpec", "s.two")},
    )

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    advances = await _advances(service, project_id)
    assert len(advances) == 2

    approvals_recorded = []
    for outcome in run.stages:
        approvals_recorded += [
            event
            for event in await service.history(outcome.session_id)
            if isinstance(event, ToolCallDecided)
            and event.tool_name == ADVANCE_STAGE_TOOL
            and event.decision in ("approve", "edit")
        ]
    assert len(approvals_recorded) == len(advances)
    assert {event.decided_by for event in approvals_recorded} == {"human"}


def test_advancing_is_only_reachable_through_the_function_that_asks():
    """`AdvanceStage` is constructed once in `application`, in a function that asks.

    Grep-shaped, over the source, because there is no type that can express it:
    a future change that split the ask from the advance across two functions
    would leave the second reachable without the first, and every behavioural
    test above would still pass. §4.2 calls this "the guarantee's whole
    enforcement" and it is the reason the amendment to §3.2 is safe.

    Fails today if `_gate_and_advance` is split, if a second construction site
    appears anywhere under `research_team/application/`, or if the one that
    exists stops calling `ApprovalPort.decide`.
    """
    package = Path(__file__).resolve().parents[2] / "research_team" / "application"
    sites: list[tuple[str, str, bool]] = []
    for module in sorted(package.rglob("*.py")):
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            calls = [inner for inner in ast.walk(node) if isinstance(inner, ast.Call)]
            advances = any(
                isinstance(call.func, ast.Name) and call.func.id == "AdvanceStage"
                for call in calls
            )
            if not advances:
                continue
            asks = any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "decide"
                for call in calls
            )
            sites.append((module.name, node.name, asks))

    assert sites == [("stage_runner.py", "_gate_and_advance", True)], sites


def test_the_runner_never_writes_the_autonomy_policy():
    """Mirrors the rule `auto_research.py` states for the research loop.

    A component that could lower its own gate makes the gate advisory. The
    runner holds the policy and may only read it, so `set` and `relax_all` must
    not appear -- and an `attended=` flag would be the same hole through a
    different door, which is why the constructor is checked for one too.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "research_team"
        / "application"
        / "stage_runner.py"
    ).read_text()
    tree = ast.parse(source)
    forbidden = {"relax_all", "set"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert not (
                isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_policy"
                and node.func.attr in forbidden
            ), f"the runner calls policy.{node.func.attr}"

    init = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    names = {arg.arg for arg in init.args.args + init.args.kwonlyargs}
    assert not names & {"attended", "unattended", "auto_approve", "skip_gate"}


# --- the unattended path, which is a configuration and not a feature ----------


async def test_an_operator_who_relaxed_the_stage_gate_is_not_asked(
    service, project_id, workflows
):
    """§4.4. The runner reads the policy; it does not own the decision.

    `relax_all(include_stage_gates=True)` is the existing, deliberate,
    HTTP-routed act, and this is the first thing in the system that uses it.
    The advance is still recorded, as `decided_by="policy"`, so an audit can
    tell a standing decision from a person's.
    """
    unattended = AutonomyPolicy(default="auto")
    unattended.relax_all(include_stage_gates=True)
    approvals = _Approvals()
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, unattended).run(project_id)

    assert run.stages[0].advanced
    assert approvals.requests == []
    decisions = [
        event
        for event in await service.history(run.stages[0].session_id)
        if isinstance(event, ToolCallDecided)
    ]
    assert [event.decided_by for event in decisions] == ["policy"]


async def test_relaxing_everything_except_the_stage_gate_still_asks(
    service, project_id, workflows
):
    """The default relax is not a way to reach an unattended boundary.

    `STAGE_GATE_TOOLS` exists so that "stop asking me about every fetch" does
    not quietly become "stop asking me about the review", and this is that
    exclusion observed from the runner rather than from the policy's own unit
    test.
    """
    relaxed = AutonomyPolicy(default="auto")
    relaxed.relax_all()
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    await _runner(service, turns, workflows, approvals, relaxed).run(project_id)

    assert len(approvals.requests) == 1


# --- the fresh session, which #74's prose promised and nothing implemented ----


async def test_each_stage_runs_in_its_own_session(service, project_id, workflows, policy):
    """§2.3. The turn broke; the session did not, until this.

    Would have failed before the runner existed for the reason that there was
    nothing to fail -- `grep -rn 'release_project|start_in_project'` returned
    dispatch, seeding, the REPL and the web app, and no workflow code at all.
    """
    approvals = _Approvals(ApprovalDecision(type="approve"), ApprovalDecision(type="approve"))
    turns = _Turns(
        service,
        {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")},
        {STAGE_TWO_ARTIFACT: _artifact("EvidenceSpec", "s.two")},
    )

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    sessions = [outcome.session_id for outcome in run.stages]
    assert len(set(sessions)) == len(sessions)


async def test_the_next_stage_inherits_the_files_and_not_the_conversation(
    service, project_id, workflows, policy
):
    """What a fresh session is *for*: a workspace is shared and a chat history is not.

    The second stage must be able to see the first stage's artifact -- it is
    the input to its own work -- and must not be carrying the first stage's
    messages, which is the one thing the boundary exists to break.
    """
    approvals = _Approvals(ApprovalDecision(type="approve"), ApprovalDecision(type="approve"))
    turns = _Turns(
        service,
        {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")},
        {STAGE_TWO_ARTIFACT: _artifact("EvidenceSpec", "s.two")},
    )

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)
    first, second = run.stages[0].session_id, run.stages[1].session_id

    later = await service.state_at(second, len(await service.history(second)))
    assert STAGE_ONE_ARTIFACT in later.state.files
    assert first != second

    # What crossed the boundary, by event type. `_fork_files_from` copies file
    # events and nothing else, and `SessionStarted` is the new session's own.
    # A conversation event here would mean the fork carried a chat history,
    # which is the one thing the boundary exists to break.
    inherited = {
        event.__class__.__name__
        for event in (await service.history(second))[: len(await service.history(first))]
    }
    assert "FileWritten" in inherited
    assert not inherited & {
        "UserMessageSent",
        "AssistantMessageAdded",
        "ToolResultRecorded",
        "TurnCompleted",
    }


async def test_the_project_is_released_even_when_a_stage_raises(
    service, project_id, workflows, policy
):
    """The `finally` that `TopicDispatcher` and `TopicSeeder` both argue for.

    A stage runner holds the project for a whole stage rather than one turn,
    so a run that died holding it would strand the project for longer than any
    existing caller could.

    Raises `CancelledError` rather than an ordinary exception, deliberately: an
    ordinary one is *handled* -- it becomes a failure count and a stop, which
    is `test_a_failed_turn_advances_nothing` -- and would prove nothing about
    the `finally`. A `BaseException` is what actually escapes the runner, and
    the process being shut down under a live run is the case that produces one.
    """

    class _Explodes:
        async def run(self, session_id, user_input):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _runner(service, _Explodes(), workflows, _Approvals(), policy)._run_stage(
            project_id,
            workflows(project_id),
            TWO_STAGES,
            TWO_STAGES.stages[0],
        )

    assert (await service.projects.load(project_id)).state.active_session_id is None


# --- what the reviewer is handed ---------------------------------------------


async def test_the_gate_carries_the_paths_this_stage_produced(
    service, project_id, workflows, policy
):
    """B36's remainder: the reviewer should not have to know where a stage writes.

    Paths and not contents. The durability half of B36 evaporated structurally
    -- the gate is posed after the turn committed, so the file viewer already
    answers -- and this is the visibility half that is left.
    """
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    await _runner(service, turns, workflows, approvals, policy).run(project_id)

    context = approvals.requests[0].context
    assert context["artifact_paths"] == [STAGE_ONE_ARTIFACT]
    assert context["stage"] == "s.one"


async def test_the_artifacts_are_in_the_store_when_the_gate_is_posed(
    service, project_id, workflows, policy
):
    """The whole structural point of moving the decision between turns.

    B36 exists because the gate was posed against evidence that had reached
    nothing: `_save_turn` is the only thing that appends and it runs after the
    executor returns. Here the reviewer is asked afterwards, so the file
    viewer's own route -- which loads from the store -- answers.
    """
    seen: dict[str, Any] = {}

    class _Looks:
        async def decide(self, request):
            seen.update(await service.project_files(project_id))
            return ApprovalDecision(type="approve")

    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})
    await _runner(service, turns, workflows, _Looks(), policy).run(project_id)

    assert STAGE_ONE_ARTIFACT in seen
    assert "/course/00-check-findings.md" in seen


async def test_the_gate_decision_recorded_is_evidence_rather_than_a_model_rationale(
    service, project_id, workflows, policy
):
    """§8.2. There is no model on this path, so there is no rationale to record.

    What the harness can honestly write is what it counted. The reviewer's
    verdict lives in `decision`, which is the field this design made a
    prerequisite.
    """
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    await _runner(service, turns, workflows, approvals, policy).run(project_id)

    [advance] = (await _advances(service, project_id))[:1]
    assert "1 of 1 declared artifacts present" in advance.gate_decision
    assert advance.decision == "approve"
    assert advance.decided_by == "human"


async def test_an_edited_gate_is_recorded_as_approved_with_edits(
    service, project_id, workflows, policy
):
    """The one `Decision` value beyond `approve` a runner can actually produce.

    `workflow-engine.md` §6 argues this delta is the best available signal for
    which stages need better prompts, and it is the reason the field was worth
    adding rather than merely worth having.
    """
    approvals = _Approvals(
        ApprovalDecision(type="edit", edited_args={"rationale": "the intents are the point"})
    )
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    await _runner(service, turns, workflows, approvals, policy).run(project_id)

    advance = (await _advances(service, project_id))[0]
    assert advance.decision == "approve_with_edits"
    assert advance.gate_decision == "the intents are the point"


async def test_the_findings_the_checks_produced_reach_the_next_turn(
    service, project_id, workflows, policy
):
    """§3.1's "single highest-value thing a driver does, and it costs nothing".

    The turn input names what is still owed. Nothing about the gate, the stage
    or its paths, all of which `StageMiddleware` already composes -- a turn
    input that repeated them would be the copy that goes stale.
    """
    approvals = _Approvals()
    turns = _Turns(service, {}, {})

    await _runner(service, turns, workflows, approvals, policy).run(project_id)

    assert STAGE_ONE_ARTIFACT in turns.inputs[0]
    assert "advance_stage" not in turns.inputs[0]


# --- what is in flight, for the roster ---------------------------------------


async def test_a_stage_being_driven_reports_itself_as_running(
    service, project_id, workflows, policy
):
    """A runner invisible while it works would be the odd one out on the dock.

    Runs, dispatches and extractions all report themselves; a stage runner
    holds a project for longer than any of them, so it is the one somebody is
    most likely to be looking for.
    """
    seen: list[Any] = []
    runner: StageRunner

    class _Peeks:
        async def run(self, session_id, user_input):
            seen.append(runner.in_flight(project_id))
            return TurnOutcome(reply="", turn_index=1, from_index=1, to_index=1)

    runner = _runner(service, _Peeks(), workflows, _Approvals(), policy)
    assert runner.in_flight(project_id) is None

    await runner.run(project_id)

    assert seen and seen[0] is not None
    assert seen[0].stage_id == "s.one"
    assert seen[0].preset_id == TWO_STAGES.id
    assert runner.in_flight(project_id) is None
    assert runner.active_projects() == ()


async def test_a_stage_sees_artifacts_written_after_the_project_was_released(
    service, project_id, workflows, policy
):
    """The owner's failure, in the shape the runner meets it.

    Something released the project and the session carried on working -- which
    is exactly what an auto-research run does, because it starts a session,
    stops, releases in its `after` hook, and leaves the person in the session
    it made. The stage's artifacts are written into a released session, so the
    tip names that session and a point before the first of them.

    Before the catch-up the runner started the stage from an empty filesystem,
    ran a turn against work that already existed, and the artifacts stayed
    where nothing could reach them. Proved red on `satisfied`.
    """
    stranded = await service.start_in_project(project_id)
    await service.release_project(stranded)
    await service.write_file(stranded, STAGE_ONE_ARTIFACT, _artifact("Intent", "s.one"))

    files = await service.project_files(project_id)
    assert STAGE_ONE_ARTIFACT in files
    assert stage_exit_condition(TWO_STAGES, TWO_STAGES.stages[0], files).satisfied

    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_TWO_ARTIFACT: _artifact("EvidenceSpec", "s.two")})
    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    # The first stage advanced without a turn -- its work was already done --
    # and the second stage's session can still see it, which is the property
    # the whole boundary exists to provide.
    assert run.stages[0].advanced
    later = await service.load(run.stages[1].session_id)
    assert STAGE_ONE_ARTIFACT in later.state.files


# --- check telemetry ---------------------------------------------------------
#
# The gate is where a check run becomes a fact worth counting. Everything below
# asserts on `service.history`, which reads the committed session stream, rather
# than on anything the runner returns: a review that only reached a return value
# would be missing from exactly the runs that mattered.

_GATE_CHECKS = (
    Check(check="shared.orphan", params={"type": "EvidenceSpec", "must_link_to": "Intent"}),
    Check(check="addie.no_such_check", severity="advisory"),
)
"""One check that runs and passes, and one binding naming nothing registered.

Bound to `EvidenceSpec`, which stage one does not produce, so the check runs
over an empty domain and finds nothing -- which is the case the denominator
exists for and the one a findings file cannot record at all. Bound to `Intent`
it fires, and a review where everything fired would not distinguish "recorded
every binding" from "recorded every finding".

`addie.no_such_check` follows the spelling `test_stage_exit.py` established for
a name that is not and will not be registered. Both are here because the two
land in different fields of the event, and the distinction between them --
"passed" against "never ran" -- is the one the denominator exists to keep.
"""


async def _checked_project(service, monkeypatch) -> tuple[UUID, Preset]:
    """A project running a preset whose first stage actually binds checks.

    `TWO_STAGES` binds none, so a review of it has an empty denominator and
    every assertion below would hold vacuously.
    """
    from research_team.application import stage_runner

    preset = _preset(
        _specify("s.one", ArtifactType.INTENT, *_GATE_CHECKS),
        _specify("s.two", ArtifactType.EVIDENCE_SPEC),
        _no_outputs("s.end"),
        preset_id="test.runner.checked",
    )
    monkeypatch.setitem(stage_runner.PRESETS, preset.id, preset)
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="checked"))
    aggregate.execute(SelectWorkflow(preset=preset))
    await service.projects.save(aggregate)
    return aggregate.aggregate_id, preset


async def _reviews(service, session_id) -> list[StageChecksEvaluated]:
    return [
        event
        for event in await service.history(session_id)
        if isinstance(event, StageChecksEvaluated)
    ]


async def _gate_decisions(service, session_id) -> list[ToolCallDecided]:
    return [
        event
        for event in await service.history(session_id)
        if isinstance(event, ToolCallDecided) and event.tool_name == ADVANCE_STAGE_TOOL
    ]


async def test_the_gate_records_what_the_checks_were_asked(
    service, workflows, policy, monkeypatch
):
    """Every bound check reaches the log, not only the ones that fired.

    `shared.orphan` passes against a well-formed Intent, so a record modelled
    on the findings file would say nothing at all about this gate. It is the
    entry reading "ran, found nothing" that makes a fire rate divisible.
    """
    project_id, preset = await _checked_project(service, monkeypatch)
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    [review] = await _reviews(service, run.stages[0].session_id)
    assert review.posed_by == "runner"
    assert review.project_id == project_id
    assert review.stage == "s.one"
    assert review.preset == preset.id
    assert review.preset_version == "1"
    assert [entry["check"] for entry in review.evaluated] == ["shared.orphan"]
    assert review.evaluated[0]["findings"] == 0
    # The unimplemented binding is in neither `evaluated` nor a finding: it did
    # not run, and recording it as a run that passed is the specific lie the
    # second field exists to prevent.
    assert [entry["check"] for entry in review.unimplemented] == ["addie.no_such_check"]
    assert review.unimplemented[0]["severity"] == "advisory"


async def test_the_decision_names_the_review_it_answered(
    service, workflows, policy, monkeypatch
):
    """The join. Fails if `review_id` is dropped anywhere along the path.

    Nothing else connects the two: `ToolCallDecided` names no stage, and
    `ProjectStageAdvanced`, which does, is on the project's stream and is not written
    at all when a gate is refused.
    """
    project_id, _ = await _checked_project(service, monkeypatch)
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    session_id = run.stages[0].session_id
    [review] = await _reviews(service, session_id)
    [decision] = await _gate_decisions(service, session_id)
    assert decision.decision == "approve"
    assert decision.review_id == review.review_id


async def test_a_rejected_gate_still_records_both(service, workflows, policy, monkeypatch):
    """Rejections are the signal an override rate is measured against.

    They are also the case with no `ProjectStageAdvanced` behind them -- the project
    stream records nothing at all when a gate is refused -- so if this pair is
    missing, the most interesting outcome is the one that leaves no trace.
    """
    project_id, _ = await _checked_project(service, monkeypatch)
    approvals = _Approvals(ApprovalDecision(type="reject", message="thin"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)

    session_id = run.stages[0].session_id
    [review] = await _reviews(service, session_id)
    [decision] = await _gate_decisions(service, session_id)
    assert decision.decision == "reject"
    assert decision.review_id == review.review_id
    assert await _advances(service, project_id) == []


async def test_a_gate_nobody_was_asked_to_open_is_recorded_as_policy(
    service, workflows, monkeypatch
):
    """`advance_stage: auto` emits both events with `decided_by="policy"`.

    Recorded rather than skipped, because a standing approval is a real
    outcome; reported separately by the read surface, because counting it as
    an override would describe a system ignoring its checks when what happened
    is that nobody was asked.
    """
    project_id, _ = await _checked_project(service, monkeypatch)
    unattended = AutonomyPolicy(default="auto")
    unattended.relax_all(include_stage_gates=True)
    approvals = _Approvals()
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, unattended).run(project_id)

    session_id = run.stages[0].session_id
    [review] = await _reviews(service, session_id)
    [decision] = await _gate_decisions(service, session_id)
    assert approvals.requests == []
    assert (decision.decision, decision.decided_by) == ("approve", "policy")
    assert decision.review_id == review.review_id


async def test_a_denied_gate_records_the_review_it_refused(service, workflows, monkeypatch):
    """`advance_stage: deny` never poses anything, and the checks still ran.

    The review is emitted before the deny branch for this reason. A check that
    fired at a gate nobody was allowed to open still ran, and dropping it would
    make a denied session look like a session with no checks in it.
    """
    project_id, _ = await _checked_project(service, monkeypatch)
    denied = AutonomyPolicy(default="auto")
    denied.set(ADVANCE_STAGE_TOOL, "deny")
    approvals = _Approvals()
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})

    run = await _runner(service, turns, workflows, approvals, denied).run(project_id)

    session_id = run.stages[0].session_id
    [review] = await _reviews(service, session_id)
    [decision] = await _gate_decisions(service, session_id)
    assert approvals.requests == []
    assert (decision.decision, decision.decided_by) == ("reject", "policy")
    assert decision.review_id == review.review_id


async def test_viewing_a_course_records_no_telemetry(service, workflows, policy, monkeypatch):
    """`course_progress` recomputes findings on every view and must not count.

    Emission is at the gate, not in `review_stage`, precisely so that a page
    refresh is not a check run. Fails if anyone moves the event into
    `review_stage`, which is the obvious-looking place for it.

    Here rather than in `test_course.py`, which the plan named: `course_progress`
    takes a preset, a state and a filesystem and holds no session, so a test
    beside it could only assert that a function with nothing to emit onto
    emitted nothing. What is worth pinning is that neither it nor `review_stage`
    has grown a session, and that needs a real one with a gate already recorded
    on it to be a claim rather than a nod.
    """
    project_id, preset = await _checked_project(service, monkeypatch)
    approvals = _Approvals(ApprovalDecision(type="approve"))
    turns = _Turns(service, {STAGE_ONE_ARTIFACT: _artifact("Intent", "s.one")})
    run = await _runner(service, turns, workflows, approvals, policy).run(project_id)
    session_id = run.stages[0].session_id
    before = await _reviews(service, session_id)
    assert before, "the gate recorded nothing, so this would prove nothing about a view"

    state = await service.project_state(project_id)
    files = await service.project_files(project_id)
    for _ in range(3):
        course_progress(preset, state, files)

    assert await _reviews(service, session_id) == before
