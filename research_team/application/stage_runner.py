"""Driving one stage to its boundary, and asking a person to let it go.

`docs/design/stage-boundaries.md` is the specification and this is the whole of
it that is code. The one sentence that shape-checks everything below is §6.2's:
**a stage runner is `DispatchRun.run` with a stage where the topic is.** Fresh
session per unit of work, `release_project` in a `finally`, one holder at a
time -- all shipped, all tested, and this reuses them rather than restating
them.

**Turn-end is when the advance is evaluated, never when it is taken.** A turn
ends for four reasons -- the model wrote the artifacts and stopped, the model
ran out of things to say, the turn raised, a human cancelled it -- and only the
first may lead anywhere. `TurnOutcome` cannot tell the first from the second,
and a model asked whether it has finished says yes fluently, which
`auto_research.py` already refuses to trust for the research loop. So nothing
here reads a turn's prose. What decides is `stage_exit_condition` below,
computed over the aggregate as it stands *after* `_save_turn` has committed.

**The exit condition is good enough to decide when to ask, and not good enough
to decide instead of asking.** Presence plus structure says the shape is right;
all 21 implemented checks are graph and schema queries, so a well-formed
artifact of the wrong provenance passes every one of them. There is no
computation in this module, or anywhere, that distinguishes a *done* stage from
a merely *populated* one -- `workflow-engine.md` §4.4 works that failure
through and `stage-boundaries.md` open question 2 records that nobody has a
proposal for it. Nothing here should be read as claiming otherwise, and the
default being attended is the only mitigation there is.

**This module has no opinion about its own supervision.** There is no
`attended` flag, no constructor argument and no config option that lets a run
skip the gate. `AutonomyPolicy` is the single answer to "may this happen
without me": the runner *reads* `level_for(advance_stage)` and never writes the
policy, so an unattended run is reachable only through
`relax_all(include_stage_gates=True)` -- which is built, routed, and recorded
as `AutonomyChanged`. A second mechanism here would disagree with that one
eventually, and it would be the thing a caller sets without the recorded act.
`auto_research.py` states the same rule for the research loop: "a loop that
could lower its own floors would make `TOOL_FLOORS` advisory".

**Why this may execute `AdvanceStage` at all**, which `workflow-engine.md` §3.2
forbade. `stage-boundaries.md` §4.4 is the amendment and its reasoning is that
§3.2 protected the right property through the wrong invariant: the hazard is an
advance with *no decision behind it*, not the identity of the caller. Making
the tool the sole caller is sufficient and not necessary, and it costs
something §3.2 did not price -- it makes the model the only thing that can
propose a boundary, when the two facts that decide whether a stage is done are
computable. The narrowed rule is that asking and advancing are one function.
`_gate_and_advance` is that function, it is the only place in this package that
constructs an `AdvanceStage`, and
`test_advancing_is_only_reachable_through_the_function_that_asks` fails if a
second one appears.

**Every stop reason is a fold of committed state or of the turn's own event
span**, never a counter that only this process knows. That is the line between
a budget and a `LoopPolicy`, and `workflow-engine.md` §3.4 is emphatic that a
runner implementing looping in process state reproduces `LoopPolicy` where
nothing can audit it. Nothing here compares this turn's findings to last
turn's; the two counters that exist -- consecutive failures, consecutive
file-less turns -- ask only whether anything is happening, not whether it is
getting better.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.application.artifacts import artifact_path, parse_frontmatter
from research_team.application.autonomy import ADVANCE_STAGE_TOOL, AutonomyPolicy
from research_team.application.ports import ApprovalPort, ApprovalRequest
from research_team.application.session_service import SessionService, TurnOutcome
from research_team.application.stage_exit import (
    StageReview,
    findings_path,
    gate_context,
    refusal,
    render_review,
    review_stage,
)
from research_team.domain import FileDeleted, FileEdited, FileWritten
from research_team.domain.project import AdvanceStage, ProjectState, current_stage_of
from research_team.domain.workflow import Preset, StageBase
from research_team.workflows import PRESETS

logger = logging.getLogger(__name__)

__all__ = [
    "ExitCondition",
    "StageBudget",
    "StageOutcome",
    "StageRunSnapshot",
    "StageRunner",
    "StageWorkflow",
    "stage_exit_condition",
]

_FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

QUIET_TURNS_BEFORE_STOPPING = 2
"""How many consecutive turns may append no file event before the stage stops.

Two rather than one because the first can legitimately be a turn spent reading
-- a stage opening on `read_source` across a corpus writes nothing and is
working. More than two is a run paying for a model that has nothing to add.

Measured against the events the turn appended, not against its prose, which is
how `AutoRoundCompleted.produced_nothing` is measured in the other aggregate
and for the same reason. This is a count over what the log says; it decides
whether anything is happening, not whether the work is converging.
"""


@dataclass(frozen=True)
class StageBudget:
    """What one stage of a run is allowed to spend.

    Separate from `domain.auto_research.Budget` rather than reusing it. That
    type counts rounds, and a round is a research-loop concept with no meaning
    here -- a stage has turns and a boundary. Sharing the type would have half
    its fields be noise a reader has to decide to ignore, which is how a
    borrowed abstraction costs more than the duplication it saved.
    """

    max_turns_per_stage: int = 8
    """A ceiling, not a target. Reached means the stage did not converge and a
    person should look at it -- which the report says by name, because "the run
    stopped" and "the run stopped in ubd.stage2.evidence with two artifacts
    still missing" are different messages and only one is actionable."""
    max_consecutive_failures: int = 2
    """Turns that raised, back to back. `Budget.max_consecutive_failures` is
    the existing shape and this is deliberately the same idea; the count is
    reset by any turn that completes."""
    max_stages: int = 32
    """A stop for the whole run, so a preset edited mid-run into a cycle cannot
    spin here. No shipped preset comes close -- the longest is fifteen stages
    -- and a bound that is never reached is cheaper than the loop that is not
    bounded at all."""


@dataclass(frozen=True)
class ExitCondition:
    """Whether this stage's work is, structurally, finished.

    Three facts and their conjunction, kept apart rather than collapsed to a
    bool: a caller reporting why a run stopped needs to say *which* artifacts
    were missing, and a bool would make it re-derive them.
    """

    stage_id: str
    declared: tuple[str, ...]
    """Every path `stage_artifact_paths` says this stage owes."""
    missing: tuple[str, ...]
    """Declared and not present."""
    malformed: tuple[str, ...]
    """Present, and not readable as the artifact type the output declared.

    Failed on rather than passed over. `StageReview.unreadable` already reports
    this class and `stage_exit.py` is right that a file present but unreadable
    is worth refusing on -- handing it to a reviewer means letting them find
    out for themselves what the parser already knew.
    """
    review: StageReview

    @property
    def refused(self) -> bool:
        """A harness invariant failed, so nobody is asked anything.

        `stage_exit.py`'s reasoning applies verbatim: a self-screening critic
        and an uncited verdict both fail invisibly, so putting one to a human
        "converts an invariant back into advice, and hands them a judgement
        with nothing to look at". This holds at `advance_stage: auto` as well
        -- it is the floor under the unattended run, and the two failures it
        catches are exactly the ones that would otherwise produce a course
        claiming reviews it cannot evidence.
        """
        return self.review.blocked

    @property
    def satisfied(self) -> bool:
        """Every declared artifact present, readable, and no invariant failed.

        **False for a stage that declares no outputs**, which is why `declared`
        is tested rather than `missing` alone. Such a stage would otherwise be
        satisfied the instant it was entered. No stage in any shipped preset
        declares nothing -- walked across `ubd.pure`, `addie.pure` and
        `hybrid.default` -- but a `FieldStage` has neither generator nor critic
        and per `workflow-engine.md` §2.3 "an agent cannot execute it at all",
        so the case is one preset edit away. It is a human's stage: the run
        stops there and somebody advances it by hand with `advance_stage`.
        Writing the rule costs one condition; discovering it later costs a
        preset that silently skips a stage.

        Non-invariant findings do not appear here. `stage_exit.py` is explicit
        that findings inform and do not block, and that a pipeline refusing to
        advance on an advisory finding "teaches people to switch checks off".
        They travel to the reviewer in `gate_context`.
        """
        return (
            bool(self.declared)
            and not self.missing
            and not self.malformed
            and not self.refused
        )

    @property
    def evidence(self) -> str:
        """What the harness can honestly say about why the gate is being posed.

        This is what goes into `StageAdvanced.gate_decision`, which under the
        tool holds a model's `rationale` and under a runner cannot: there is no
        model in this path. Machine prose is the honest substitute and it is
        the more useful of the two, but it is a different kind of thing -- the
        field is evidence here and verdict there. `StageAdvanced.decision` is
        where the verdict went; see its docstring.
        """
        advisory = len(self.review.findings) - len(self.review.invariant_failures)
        return (
            f"{len(self.declared)} of {len(self.declared)} declared artifacts present; "
            f"{advisory} finding{'' if advisory == 1 else 's'}; "
            f"no invariant failures"
        )


def stage_exit_condition(
    preset: Preset, stage: StageBase, files: Mapping[str, Mapping[str, Any]]
) -> ExitCondition:
    """The exit condition of `stage-boundaries.md` §3.1, over committed files.

    Pure, and takes the files rather than reading them, so the caller controls
    *when* the snapshot was taken. That is the whole point: the design's claim
    is that the condition is computed over committed state, and a function that
    fetched its own would let a caller compute it mid-turn without noticing.

    The artifact type is checked against what the output *declared* rather than
    merely being a valid `ArtifactType`. A stage that wrote an `Intent` to the
    path its `EvaluationPlan` output names has produced a file that parses, is
    a real artifact, and is not the one the preset asked for -- and the
    path-based checks downstream would read it as the plan.
    """
    declared: list[str] = []
    missing: list[str] = []
    malformed: list[str] = []
    for output in stage.outputs:
        path = artifact_path(preset, stage, output)
        declared.append(path)
        entry = files.get(path)
        if entry is None:
            missing.append(path)
            continue
        front, _ = parse_frontmatter(str(entry.get("content", "")))
        if front is None or str(front.get("artifact_type")) != output.artifact_type.value:
            malformed.append(path)
    return ExitCondition(
        stage_id=stage.id,
        declared=tuple(declared),
        missing=tuple(missing),
        malformed=tuple(malformed),
        review=review_stage(preset, stage, files),
    )


class StageWorkflow(Protocol):
    """One project's stage position, read and moved.

    The same shape `infrastructure/agent/workflow_tools.py` declares for the
    tool, restated here rather than imported for the reason `topic_dispatch.py`
    gives about `TopicReaderFor`: `application` may not import
    `infrastructure`, and `test_imports_point_inward` enforces it.
    `ProjectWorkflow` satisfies both structurally, which is the intent -- the
    tool and the runner move a stage through exactly one adapter.
    """

    async def project_state(self) -> ProjectState: ...

    async def advance(self, command: AdvanceStage) -> ProjectState: ...


WorkflowFor = Callable[[UUID], StageWorkflow]
"""A project's workflow adapter, by project id. As `TopicReaderFor`."""


class TurnRunner(Protocol):
    """The slice of `TurnSupervisor` a stage turn needs. As `TopicDispatcher`'s."""

    async def run(self, session_id: UUID, user_input: str) -> TurnOutcome: ...


@dataclass(frozen=True)
class StageOutcome:
    """What happened to one stage, in the shape a report wants.

    `stopped_because` is a code and `detail` is prose. Both, because the two
    readers differ: a caller deciding whether to continue reads the code, and a
    person reading why their run stopped needs the stage named and the
    artifacts listed. §7.4's point is that "the run stopped" and "the run
    stopped because ubd.stage2.evidence never produced its GRASPS situation"
    are different messages and only one is actionable.
    """

    stage_id: str
    session_id: UUID
    advanced: bool
    stopped_because: str
    """One of: `advanced`, `rejected`, `invariant`, `no_outputs`, `budget`,
    `quiet`, `failed`, `cancelled`, `final_stage`."""
    detail: str
    turns: int


@dataclass(frozen=True)
class StageRun:
    """Every stage this run touched, in order, and why it ended."""

    project_id: UUID
    stages: tuple[StageOutcome, ...] = ()

    @property
    def stopped_because(self) -> str:
        return self.stages[-1].stopped_because if self.stages else "no_workflow"


@dataclass(frozen=True)
class StageRunSnapshot:
    """One stage being driven, as `WorkerRoster` needs to describe it.

    Declared beside the runner rather than in `workers.py` because the runner
    is what produces it, matching `DispatchSnapshot`'s reasoning from the other
    direction. Carries the session id, unlike `DispatchSnapshot`: a stage runner
    holds one session per stage and that session's transcript *is* the detail
    view, so pointing at it costs nothing and saves a reader a hop.
    """

    stage_id: str
    preset_id: str
    turns: int = 0
    started_at: datetime | None = None
    session_id: UUID | None = None


@dataclass
class _Progress:
    """The two counters, and nothing that could grow into a convergence check.

    Both are folds over what happened rather than judgements about it, which is
    the distinction §7.5 draws: a budget bounds how much is spent and needs no
    opinion about the work; a loop policy decides whether the work is
    converging and does. The moment something here compared this turn's
    findings to last turn's, it would have become the second kind.
    """

    turns: int = 0
    consecutive_failures: int = 0
    quiet_turns: int = 0
    files_written: list[str] = field(default_factory=list)


class StageRunner:
    """Drives a project's stages, asking at every boundary it reaches.

    One session per *stage*, not per turn. Turns within a stage share a
    session because the boundary is what breaks the conversation, and breaking
    it every turn would throw away the context that makes turn two a revision
    rather than a restart -- the findings from `review_stage` are fed in as
    input, and a model that cannot see what it wrote last turn cannot act on a
    finding about it. The cost is that a long stage grows its context;
    `ContextService` already compacts and records `CompactConversation` when it
    does, so this is a cost the system already prices.

    A retried stage is not resumed: a failed turn left a marker and no work,
    and the session's conversation now ends with a failure it will otherwise
    try to explain. That is why the failure count lives per stage and a stage
    that exhausts it stops rather than restarting in place.
    """

    def __init__(
        self,
        session: SessionService,
        turns: TurnRunner,
        workflows: WorkflowFor,
        approvals: ApprovalPort | None,
        policy: AutonomyPolicy,
        budget: StageBudget | None = None,
    ) -> None:
        self._session = session
        self._turns = turns
        self._workflows = workflows
        self._approvals = approvals
        # Read, never written. There is no method on this class that sets a
        # level, and `test_the_runner_never_writes_the_autonomy_policy` fails
        # if one appears -- the rule `auto_research.py` states for the research
        # loop, which is that a component able to lower its own gate makes the
        # gate advisory.
        self._policy = policy
        self._budget = budget or StageBudget()
        self._running: dict[UUID, StageRunSnapshot] = {}

    # ---- what is in flight, for the roster ----

    def in_flight(self, project_id: UUID) -> StageRunSnapshot | None:
        return self._running.get(project_id)

    def active_projects(self) -> tuple[UUID, ...]:
        """Every project with a stage being driven. Keyed by project already,
        so `WorkerRoster.everywhere` pays nothing to ask."""
        return tuple(self._running)

    # ---- the run ----

    async def run(self, project_id: UUID) -> StageRun:
        """Drive stages forward until something stops the run.

        The loop is over stages and not over turns: each iteration takes a
        fresh session, works one stage to its boundary or to a stop, and
        releases. That is the fresh session `advance_stage`'s prose has
        promised since #74 and nothing implemented -- `release_project` and
        `start_in_project` were used by dispatch and seeding and by no workflow
        code at all.

        Stops the moment a stage does not advance. Every non-advancing outcome
        is either a refusal, a budget, or a human saying no, and none of them
        is improved by trying the next stage anyway.
        """
        outcomes: list[StageOutcome] = []
        workflow = self._workflows(project_id)
        for _ in range(self._budget.max_stages):
            state = await workflow.project_state()
            preset = PRESETS.get(state.preset_id or "")
            if preset is None:
                break
            stage = current_stage_of(state, preset)
            if stage is None:
                # The project's recorded stage is not one of this preset's.
                # Reported rather than repaired: the project and the workflow
                # it is being run under disagree, and picking one would hide
                # which. The tool answers the same situation the same way.
                logger.warning(
                    "project %s is at stage %s, which %s does not define",
                    project_id,
                    state.current_stage,
                    preset.id,
                )
                break
            outcome = await self._run_stage(project_id, workflow, preset, stage)
            outcomes.append(outcome)
            if not outcome.advanced:
                break
        return StageRun(project_id=project_id, stages=tuple(outcomes))

    async def _run_stage(
        self, project_id: UUID, workflow: StageWorkflow, preset: Preset, stage: StageBase
    ) -> StageOutcome:
        """One stage, in one fresh session, from entry to boundary or to a stop.

        `release_project` runs in `finally` for the reason `TopicDispatcher`
        and `TopicSeeder` both give verbatim: the failure it prevents is a run
        that dies holding the project. A stage runner is the longest-lived
        version of that hazard in the system -- a dispatch holds the project
        for one turn and this holds it for a whole stage -- so it is the place
        the `finally` earns most.
        """
        session_id = await self._session.start_in_project(project_id)
        self._running[project_id] = StageRunSnapshot(
            stage_id=stage.id,
            preset_id=preset.id,
            started_at=datetime.now(UTC),
            session_id=session_id,
        )
        progress = _Progress()
        try:
            await self._session.attach_project(project_id)
            return await self._work(project_id, session_id, workflow, preset, stage, progress)
        finally:
            self._running.pop(project_id, None)
            await self._session.release_project(session_id)

    async def _work(
        self,
        project_id: UUID,
        session_id: UUID,
        workflow: StageWorkflow,
        preset: Preset,
        stage: StageBase,
        progress: _Progress,
    ) -> StageOutcome:
        """The turn loop, with the exit condition evaluated between turns.

        **The condition is evaluated before the first turn**, deliberately, and
        it can be satisfied there: a human who wrote this stage's artifacts by
        hand and then started a runner gets the gate posed without a turn
        running. That is surprising and it is correct -- the work is done, and
        a turn with nothing to do would be a model call spent discovering that.
        Said here because the alternative reads as a bug.
        """
        while True:
            files = await self._session.project_files(project_id)
            condition = stage_exit_condition(preset, stage, files)

            if condition.refused:
                return self._stopped(
                    stage, session_id, "invariant", refusal(condition.review) or "", progress
                )
            if condition.satisfied:
                return await self._gate_and_advance(
                    project_id, session_id, workflow, preset, stage, condition, progress
                )
            if not condition.declared:
                return self._stopped(
                    stage,
                    session_id,
                    "no_outputs",
                    f"{stage.id} declares no artifacts, so nothing here can tell whether "
                    f"it is finished. It is a human's stage: advance it by hand.",
                    progress,
                )
            if progress.turns >= self._budget.max_turns_per_stage:
                return self._stopped(
                    stage, session_id, "budget", _shortfall(condition), progress
                )
            if progress.quiet_turns >= QUIET_TURNS_BEFORE_STOPPING:
                return self._stopped(
                    stage,
                    session_id,
                    "quiet",
                    f"{QUIET_TURNS_BEFORE_STOPPING} consecutive turns wrote no file. "
                    + _shortfall(condition),
                    progress,
                )

            stop = await self._one_turn(session_id, preset, stage, condition, progress)
            if stop is not None:
                return stop
            # Refreshed so the roster's "turn 3" is the turn actually running
            # rather than the one this stage started on. `replace` rather than
            # mutation because the snapshot crosses to a reader that must not
            # see it change under itself mid-render.
            snapshot = self._running.get(project_id)
            if snapshot is not None:
                self._running[project_id] = replace(snapshot, turns=progress.turns)

    async def _one_turn(
        self,
        session_id: UUID,
        preset: Preset,
        stage: StageBase,
        condition: ExitCondition,
        progress: _Progress,
    ) -> StageOutcome | None:
        """Run one turn and fold what it did into `progress`, or stop the stage.

        Returns `None` to keep going. The three ways a turn ends that are not
        "it wrote something" are handled here and **none of them advances
        anything**, which is the distinction the whole design turns on:

        - *cancelled* stops immediately and without counting against a budget.
          A human who stopped a turn did not ask for another one, and a runner
          that treated cancellation as a failure to retry would restart the
          work they just interrupted.
        - *raised* counts, and exhausting the count stops the stage. The turn
          discarded its aggregate and appended a lone failure marker, so
          nothing it did is durable.
        - *wrote nothing* counts separately, against `QUIET_TURNS_BEFORE_
          STOPPING`.
        """
        try:
            outcome = await self._turns.run(session_id, _turn_input(preset, stage, condition))
        except Exception as error:  # noqa: BLE001 -- a raised turn is a stop, not a crash
            if _is_cancellation(error):
                return self._stopped(
                    stage,
                    session_id,
                    "cancelled",
                    f"the turn on session {session_id} was cancelled",
                    progress,
                )
            progress.turns += 1
            progress.consecutive_failures += 1
            if progress.consecutive_failures >= self._budget.max_consecutive_failures:
                return self._stopped(
                    stage,
                    session_id,
                    "failed",
                    f"{progress.consecutive_failures} consecutive turns raised; "
                    f"the last was {type(error).__name__}: {error}",
                    progress,
                )
            return None

        progress.turns += 1
        progress.consecutive_failures = 0
        written = await self._files_written(session_id, outcome)
        if written:
            progress.quiet_turns = 0
            progress.files_written.extend(written)
        else:
            progress.quiet_turns += 1
        return None

    async def _files_written(self, session_id: UUID, outcome: TurnOutcome) -> list[str]:
        """Which paths this turn touched, from the events it actually appended.

        Read off the span `run_turn` reports rather than by diffing the
        filesystem, because the two answer different questions: a turn that
        rewrote a file with identical content changed no bytes and did work,
        and a diff would call it quiet. §7.1 asks for this to be measured
        "against the events the turn appended, not against its prose", and the
        span is what makes that exact and cheap.
        """
        events = await self._session.history(session_id)
        span = events[outcome.from_index - 1 : outcome.to_index]
        return [event.path for event in span if isinstance(event, _FILE_EVENTS)]

    async def _gate_and_advance(
        self,
        project_id: UUID,
        session_id: UUID,
        workflow: StageWorkflow,
        preset: Preset,
        stage: StageBase,
        condition: ExitCondition,
        progress: _Progress,
    ) -> StageOutcome:
        """Ask, and then -- only then, and only here -- advance.

        **This is the only function in `research_team.application` that
        constructs an `AdvanceStage`, and it asks first.** That is the whole
        enforcement of the guarantee `workflow-engine.md` §3.2 protected by
        making the tool the sole caller, restated as the property rather than
        the mechanism: `stage-boundaries.md` §4.4's amendment permits a
        component to execute the command *if and only if* it has, immediately
        beforehand and in the same function, obtained an approval or observed
        that the operator set `advance_stage` to `auto`. Splitting the ask from
        the advance across two functions would leave the second reachable
        without the first, and nothing in the type system would notice.
        `test_advancing_is_only_reachable_through_the_function_that_asks` is
        what fails if someone splits them.

        `advance_stage: auto` means the boundary passes unattended, and that is
        already true today: it is what `relax_all(include_stage_gates=True)`
        does, it has an HTTP route, and every level change is recorded as
        `AutonomyChanged`. Reading the policy here is not creating that
        capability -- it is the first thing that uses it. The decision is
        recorded as `decided_by="policy"` so an audit can tell a person's
        approval from a standing one, which `ToolCallDecided` already
        distinguishes.

        The findings artifact is written through the *session* rather than
        handed to the reviewer inline. It reaches the store immediately, which
        is the structural half of B36 evaporating: the gate is posed after
        `_save_turn`, so the artifacts and this report are already loadable by
        `GET /api/sessions/{id}/files` while the reviewer decides.
        """
        following = _next_stage_id(preset, stage)
        if following is None:
            return self._stopped(
                stage,
                session_id,
                "final_stage",
                f"{stage.id} is the last stage of {preset.id}; there is nothing to "
                f"advance to.",
                progress,
            )

        review = condition.review
        path = findings_path(preset, stage)
        await self._session.write_file(session_id, path, render_review(review, preset))

        # Here rather than inside `review_stage`, which is the obvious-looking
        # place: `course_progress` calls `review_stage` on every course view to
        # show live findings, so instrumenting the computation would count a
        # page refresh as a check run and every rate would be measured against
        # how often somebody looked. Emission belongs at the gate, which is the
        # event being counted. Before the `deny` branch below, because a check
        # that fired at a gate nobody was allowed to open still ran.
        review_id = uuid4()
        await self._session.record_stage_review(
            session_id,
            review_id=review_id,
            project_id=project_id,
            stage=stage.id,
            preset=preset.id,
            preset_version=str(preset.version),
            evaluated=review.evaluated,
            unimplemented=review.unimplemented_bindings,
            posed_by="runner",
        )

        args = {"rationale": condition.evidence}
        level = self._policy.level_for(ADVANCE_STAGE_TOOL)
        # No port and a gate that asks means there is nobody to ask, which is
        # a refusal and not a licence. `_decide` in the turn executor treats
        # the same situation the same way, and the alternative -- advancing
        # because no reviewer was wired -- would make the guarantee depend on
        # a composition detail rather than on the policy.
        if level == "ask" and self._approvals is None:
            level = "deny"
        if level == "deny":
            await self._session.record_tool_decision(
                session_id, ADVANCE_STAGE_TOOL, args, "reject", "policy", review_id=review_id
            )
            return self._stopped(
                stage,
                session_id,
                "rejected",
                f"advance_stage is denied in this session, so {stage.id} cannot be left.",
                progress,
            )

        if level == "auto":
            decided_by, decision_type, message = "policy", "approve", ""
        else:
            decided_by = "human"
            answer = await self._approvals.decide(
                ApprovalRequest(
                    session_id=session_id,
                    tool_name=ADVANCE_STAGE_TOOL,
                    args=args,
                    description=(f"Leave {stage.id} for {following}. {condition.evidence}."),
                    allowed_decisions=("approve", "edit", "reject", "respond"),
                    context=gate_context(review, path, artifact_paths=condition.declared),
                )
            )
            decision_type = answer.type
            message = answer.message or ""
            if decision_type == "edit" and answer.edited_args:
                args = dict(answer.edited_args)

        await self._session.record_tool_decision(
            session_id,
            ADVANCE_STAGE_TOOL,
            args,
            decision_type,
            decided_by,
            review_id=review_id,
        )
        if decision_type not in ("approve", "edit"):
            # A rejected gate stops the run. The alternative -- feed the
            # rejection back and try again -- is a loop with a convergence
            # policy in it, which is `LoopPolicy` reimplemented in process
            # state; and a reviewer who rejects twice for the same reason is
            # saying the run is not the thing that will fix it. Their message
            # is carried out so it can become the next turn's input if they
            # resume by hand. Cheap to change later, hard to unwind if wrong
            # in the other direction.
            return self._stopped(
                stage,
                session_id,
                "rejected",
                message or f"the reviewer answered {decision_type!r}",
                progress,
            )

        await workflow.advance(
            AdvanceStage(
                preset=preset,
                to_stage=following,
                decided_by=decided_by,
                # Evidence, not verdict: there is no model rationale on this
                # path. See `StageAdvanced.gate_decision`.
                gate_decision=str(args.get("rationale") or condition.evidence),
                decision="approve_with_edits" if decision_type == "edit" else "approve",
            )
        )
        return StageOutcome(
            stage_id=stage.id,
            session_id=session_id,
            advanced=True,
            stopped_because="advanced",
            detail=f"advanced to {following}",
            turns=progress.turns,
        )

    def _stopped(
        self,
        stage: StageBase,
        session_id: UUID,
        because: str,
        detail: str,
        progress: _Progress,
    ) -> StageOutcome:
        return StageOutcome(
            stage_id=stage.id,
            session_id=session_id,
            advanced=False,
            stopped_because=because,
            detail=detail,
            turns=progress.turns,
        )


def _next_stage_id(preset: Preset, stage: StageBase) -> str | None:
    """The one legal move, computed the same way the domain enforces it.

    `_advanced` computes `ids[at + 1]` and refuses everything else; deriving it
    the same way here means the runner and the aggregate cannot disagree about
    which stage is next, and a disagreement would surface as a
    `CommandRejectedError` rather than as a skipped stage.
    """
    ids = [entry.id for entry in preset.stages]
    at = ids.index(stage.id)
    return ids[at + 1] if at + 1 < len(ids) else None


def _shortfall(condition: ExitCondition) -> str:
    """Which artifacts the stage still owes, named.

    §7.4's requirement: a run that stopped must not be reported only as having
    stopped. "ubd.stage2.evidence is missing /course/03-assessment-plan.md" is
    actionable and "the budget ran out" is not.
    """
    parts = []
    if condition.missing:
        parts.append("missing " + ", ".join(condition.missing))
    if condition.malformed:
        parts.append(
            "not readable as the declared artifact type: " + ", ".join(condition.malformed)
        )
    return f"{condition.stage_id} " + ("; ".join(parts) if parts else "did not finish")


def _is_cancellation(error: BaseException) -> bool:
    """Whether a turn ended because somebody stopped it.

    Matched on the type's name rather than by importing `TurnCancelled`:
    `turn_supervisor.py` imports `session_service.py`, and importing it back
    here would be a cycle through the module this one already depends on. The
    cost is that a rename of that class silently stops matching, which is why
    `test_a_cancelled_turn_advances_nothing` asserts on the outcome rather than
    on this predicate.
    """
    return type(error).__name__ == "TurnCancelled"


def _turn_input(preset: Preset, stage: StageBase, condition: ExitCondition) -> str:
    """What the next turn is told: what is still owed, and what the checks found.

    Feeding findings back is `workflow-engine.md` §3.1's "single highest-value
    thing a driver does, and it costs nothing" -- the checks are graph and
    schema queries and none needs a model call.

    Says nothing about the gate, the stage's identity, its artifact paths or
    its tools. All four are already in the system prompt that `StageMiddleware`
    composes, and a turn input that repeated them would be the copy that goes
    stale -- `prompts.py` makes the same argument about what a prompt file may
    not name.
    """
    lines = ["Continue this stage."]
    if condition.missing:
        lines.append("Still to write: " + ", ".join(condition.missing))
    if condition.malformed:
        lines.append(
            "Written but not readable as the artifact type the stage declares "
            "(check the frontmatter): " + ", ".join(condition.malformed)
        )
    findings = [
        f"- [{finding.severity}] {finding.check}: {finding.message}"
        for finding in condition.review.findings
    ]
    if findings:
        lines.append(
            "The stage's own checks found these. They do not block the advance; "
            "they are what a reviewer will read."
        )
        lines.extend(findings)
    return "\n".join(lines)
