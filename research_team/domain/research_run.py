"""An autonomous research run: what it did, and why it stopped.

Its own aggregate rather than state on a session, because a run outlives any
one turn and has to survive the process dying at round forty. Everything the
driver needs to resume is folded from this stream.

**Two invariants shape every event here**, and both are asserted by tests rather
than merely documented:

- **No round without a reason.** A round names the triggers that put its topic
  in the queue, and the evidence those triggers cited. A run that cannot say why
  it looked at something is indistinguishable from one picking at random.
- **No stop without evidence.** `StopReason` is a closed enum and every value is
  recomputable from the events before it. "Done" must be a fold, never a claim:
  a model asked whether it has finished says yes fluently, which is exactly the
  failure this aggregate exists to make impossible.

**Progress is measured in artifacts, not narration.** `ResearchRoundCompleted`
carries counts of what the round actually appended. A round that recorded no
finding, linked no source and opened no sub-question is empty however well it
described itself, and `produced_nothing` is what the novelty-decay stop reads.
"""

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

StopReason = Literal[
    "queue_empty",
    "budget_exhausted",
    "no_new_findings",
    "max_rounds",
    "error_rate",
    "cancelled",
]
"""Why a run ended. A closed set, on purpose.

Free text is an addition to one of these, never a substitute. Every value is
computable from the log without asking the agent: `queue_empty` from the
queue, the rest from this stream's own counters. There is deliberately no
`agent_decided_it_was_done`.
"""

DEFAULT_MAX_ROUNDS = 25
"""The universal backstop, applied even when nothing else trips.

Not a target. A run that reaches it has almost certainly failed to converge,
which is why `max_rounds` is a distinct stop reason from `queue_empty` rather
than both reading as success.
"""

DEFAULT_QUIET_ROUNDS = 3
"""Consecutive empty rounds before novelty decay stops the run.

Three rather than one because a single empty round is ordinary -- plenty of
real investigations come back with nothing. Three in a row is a loop that has
stopped learning, and continuing spends tokens to re-read what it has read.
"""

DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
"""Failed turns in a row before the run gives up.

The condition most autonomous loops forget: a run that fails every round still
"runs", burning budget and reporting nothing, until a human notices.
"""


class Budget(BaseModel):
    """What a run is allowed to spend.

    Rounds and turns are counted separately because they diverge: a round that
    fails and is retried spends a turn without advancing a round, and a budget
    that could not tell them apart would let a crash-looping run continue
    indefinitely.
    """

    max_rounds: int = DEFAULT_MAX_ROUNDS
    max_turns: int = DEFAULT_MAX_ROUNDS * 2
    quiet_rounds: int = DEFAULT_QUIET_ROUNDS
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES


# ---------------- events ----------------


@register_event
class ResearchRunStarted(DomainEvent):
    """A run began, against one project, under this budget and this policy.

    `autonomy_snapshot` records the tool policy as it stood at the start. The
    policy is mutable mid-turn, so without this "was it allowed to do that?"
    stops being answerable the moment anyone changes a level -- and that is
    exactly the question an audit of an unattended run asks first.

    `read_only` is recorded rather than inferred. The default run works over
    the corpus and graph already held, because `fetch` floors at `ask` and an
    unattended loop that hits an approval either deadlocks or is auto-rejected.
    That is the security posture working, not a limitation to route around.

    `fetch_hosts`/`fetch_budget` are the pre-authorization: which hosts a
    granted run may fetch from, and how many calls it gets. Unlike
    `autonomy_snapshot`, which is written here and nowhere folded onto
    `ResearchRunState` (so "what tool policy did this run start under" is
    answerable only by reading this one event by hand), `evolve` below
    carries these two onto state -- because enforcement needs to answer "what
    was this run allowed to do?" from a fold, the same way `exhausted()`
    answers "should this run stop?" without re-deriving anything. Defaults of
    `[]` and `0` are a run granted nothing, which is every run before this
    field existed and every run today that nobody authorizes.
    """

    aggregate_type: str = "ResearchRun"
    project_id: UUID
    session_id: UUID
    budget: dict = Field(default_factory=dict)
    autonomy_snapshot: dict = Field(default_factory=dict)
    read_only: bool = True
    fetch_hosts: list[str] = Field(default_factory=list)
    fetch_budget: int = 0


@register_event
class ResearchRoundStarted(DomainEvent):
    """One round began, on one topic, for these reasons.

    `triggers` and `evidence` are the "no round without a reason" invariant made
    concrete: the triggers say what raised the topic, and the evidence carries
    the ids they cited. A reason string would be a claim; these are checkable
    against the corpus.
    """

    aggregate_type: str = "ResearchRun"
    round_number: int
    topic_id: UUID
    triggers: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    queue_depth: int = 0


@register_event
class ResearchRoundCompleted(DomainEvent):
    """One round finished, having produced this much.

    The counts are of events the round actually appended to the topic's stream.
    They are what novelty decay reads, which is what stops a run whose rounds
    describe progress they did not make.
    """

    aggregate_type: str = "ResearchRun"
    round_number: int
    topic_id: UUID
    findings: int = 0
    sources_linked: int = 0
    sub_questions_opened: int = 0

    @property
    def produced_nothing(self) -> bool:
        return not (self.findings or self.sources_linked or self.sub_questions_opened)


@register_event
class ResearchRoundFailed(DomainEvent):
    """A round's turn failed, or was refused, and the run carried on.

    Recorded rather than raised, so one bad topic does not end a run -- but
    counted, so a run failing every round stops instead of burning its budget
    reporting nothing.
    """

    aggregate_type: str = "ResearchRun"
    round_number: int
    topic_id: UUID
    error_type: str
    error_message: str = ""


@register_event
class ResearchRunStopped(DomainEvent):
    """The run ended, for exactly one of the reasons in `StopReason`.

    `unexamined_topics` is the count still wanting attention when it stopped,
    and it is reported on the face of the result rather than buried. A run that
    stops with work outstanding must not read as success -- the same posture a
    `FieldGate` takes when it emits a result with its gates explicitly
    unsatisfied instead of pretending they passed.
    """

    aggregate_type: str = "ResearchRun"
    reason: str
    detail: str = ""
    rounds: int = 0
    findings: int = 0
    unexamined_topics: int = 0


# ---------------- commands ----------------


@dataclass(frozen=True)
class StartRun:
    #: Which run to start. The creation command's target.
    run_id: UUID
    project_id: UUID
    session_id: UUID
    budget: Budget = dc_field(default_factory=Budget)
    autonomy_snapshot: dict | None = None
    read_only: bool = True
    fetch_hosts: list[str] = dc_field(default_factory=list)
    fetch_budget: int = 0


@dataclass(frozen=True)
class BeginRound:
    topic_id: UUID
    triggers: list[str]
    evidence: list[str]
    queue_depth: int = 0


@dataclass(frozen=True)
class CompleteRound:
    topic_id: UUID
    findings: int = 0
    sources_linked: int = 0
    sub_questions_opened: int = 0


@dataclass(frozen=True)
class FailRound:
    topic_id: UUID
    error_type: str
    error_message: str = ""


@dataclass(frozen=True)
class StopRun:
    reason: StopReason
    detail: str = ""
    unexamined_topics: int = 0


ResearchRunCommand = StartRun | BeginRound | CompleteRound | FailRound | StopRun


# ---------------- state ----------------


class ResearchRunState(BaseModel):
    """Everything derivable from a run's stream.

    The counters here are the whole of the stop logic: every `StopReason` other
    than `queue_empty` is a comparison between one of these and the budget, so a
    stop is recomputable by anyone reading the log.
    """

    run_id: UUID | None = None
    project_id: UUID | None = None
    session_id: UUID | None = None
    status: Literal["new", "running", "stopped"] = "new"
    budget: Budget = Budget()
    read_only: bool = True
    fetch_hosts: list[str] = Field(default_factory=list)
    fetch_budget: int = 0
    """What this run was pre-authorized to fetch, folded from the start event.

    Bounds the tool, not the run -- `exhausted()` below does not read these,
    and must not: a run whose fetch budget is spent keeps working over the
    corpus it already has.
    """

    rounds: int = 0
    turns: int = 0
    findings: int = 0
    consecutive_quiet_rounds: int = 0
    consecutive_failures: int = 0
    in_flight_topic: UUID | None = None
    """The topic of a round that began and has not ended.

    Set means the process died mid-round, which is distinguishable from a topic
    nobody picked -- and that distinction is what lets a resumed run avoid
    re-claiming work it may already have done.
    """

    stop_reason: str | None = None
    topics_seen: list[UUID] = Field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def exhausted(self) -> "StopReason | None":
        """The first budget condition this run has tripped, if any.

        Pure and total, so the driver never decides for itself when to stop: it
        asks, and the answer is a fold of the log. Order matters only for which
        reason is reported when two trip at once, and it is deliberate --
        failures first, because a run that is failing should say so rather than
        report that it ran out of rounds.
        """
        if self.consecutive_failures >= self.budget.max_consecutive_failures:
            return "error_rate"
        if self.consecutive_quiet_rounds >= self.budget.quiet_rounds:
            return "no_new_findings"
        if self.rounds >= self.budget.max_rounds:
            return "max_rounds"
        if self.turns >= self.budget.max_turns:
            return "budget_exhausted"
        return None


def initial_state() -> ResearchRunState:
    return ResearchRunState()


# ---------------- decide ----------------


def decide(command: ResearchRunCommand, state: ResearchRunState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce."""
    run_id = state.run_id
    match command, state:
        case StartRun(), ResearchRunState(status="new"):
            return [
                ResearchRunStarted(
                    aggregate_id=command.run_id,
                    project_id=command.project_id,
                    session_id=command.session_id,
                    budget=command.budget.model_dump(),
                    autonomy_snapshot=command.autonomy_snapshot or {},
                    read_only=command.read_only,
                    fetch_hosts=list(command.fetch_hosts),
                    fetch_budget=command.fetch_budget,
                )
            ]
        case StartRun(), _:
            raise CommandRejectedError("run already started")

        case _, ResearchRunState(status="new"):
            raise CommandRejectedError("run not started")

        case _, ResearchRunState(status="stopped"):
            # A stopped run is finished. Appending to it would make the stop
            # event a lie, and the stop is the thing an audit reads first.
            raise CommandRejectedError("run already stopped")

        case BeginRound(topic_id=topic_id, triggers=triggers, evidence=evidence), _:
            if not triggers:
                # The "no round without a reason" invariant, enforced where it
                # can actually be enforced. A round with no triggers cannot say
                # why it chose its topic.
                raise CommandRejectedError("a round must name the triggers that raised it")
            if state.in_flight_topic is not None:
                raise CommandRejectedError(
                    f"round {state.rounds} is still in flight on {state.in_flight_topic}"
                )
            return [
                ResearchRoundStarted(
                    aggregate_id=run_id,
                    round_number=state.rounds + 1,
                    topic_id=topic_id,
                    triggers=list(triggers),
                    evidence=list(evidence),
                    queue_depth=command.queue_depth,
                )
            ]

        case CompleteRound(topic_id=topic_id), _:
            if state.in_flight_topic is None:
                raise CommandRejectedError("no round is in flight")
            return [
                ResearchRoundCompleted(
                    aggregate_id=run_id,
                    round_number=state.rounds,
                    topic_id=topic_id,
                    findings=command.findings,
                    sources_linked=command.sources_linked,
                    sub_questions_opened=command.sub_questions_opened,
                )
            ]

        case FailRound(topic_id=topic_id, error_type=error_type), _:
            if state.in_flight_topic is None:
                raise CommandRejectedError("no round is in flight")
            return [
                ResearchRoundFailed(
                    aggregate_id=run_id,
                    round_number=state.rounds,
                    topic_id=topic_id,
                    error_type=error_type,
                    error_message=command.error_message[:500],
                )
            ]

        case StopRun(reason=reason, detail=detail, unexamined_topics=unexamined), _:
            return [
                ResearchRunStopped(
                    aggregate_id=run_id,
                    reason=reason,
                    detail=detail,
                    rounds=state.rounds,
                    findings=state.findings,
                    unexamined_topics=unexamined,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: ResearchRunState, event: DomainEvent) -> ResearchRunState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case ResearchRunStarted(project_id=project_id, session_id=session_id):
            return ResearchRunState(
                run_id=event.aggregate_id,
                project_id=project_id,
                session_id=session_id,
                status="running",
                budget=Budget(**event.budget) if event.budget else Budget(),
                read_only=event.read_only,
                fetch_hosts=list(event.fetch_hosts),
                fetch_budget=event.fetch_budget,
            )

        case ResearchRoundStarted(topic_id=topic_id):
            seen = state.topics_seen
            return state.model_copy(
                update={
                    "rounds": state.rounds + 1,
                    "turns": state.turns + 1,
                    "in_flight_topic": topic_id,
                    "topics_seen": seen if topic_id in seen else [*seen, topic_id],
                }
            )

        case ResearchRoundCompleted():
            produced = bool(
                event.findings or event.sources_linked or event.sub_questions_opened
            )
            return state.model_copy(
                update={
                    "findings": state.findings + event.findings,
                    # Reset on any production, not just a finding: linking a
                    # source or opening a sub-question is real progress, and a
                    # run doing that is still learning.
                    "consecutive_quiet_rounds": (
                        0 if produced else state.consecutive_quiet_rounds + 1
                    ),
                    "consecutive_failures": 0,
                    "in_flight_topic": None,
                }
            )

        case ResearchRoundFailed():
            return state.model_copy(
                update={
                    "consecutive_failures": state.consecutive_failures + 1,
                    "in_flight_topic": None,
                }
            )

        case ResearchRunStopped(reason=reason):
            return state.model_copy(update={"status": "stopped", "stop_reason": reason})

    return state


class ResearchRun(DeciderAggregate[ResearchRunState, ResearchRunCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = "ResearchRun"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
