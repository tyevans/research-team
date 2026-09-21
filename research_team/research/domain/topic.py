"""A topic: a question the project is tracking, and what is known about it.

The corpus answers "what have we read". The graph answers "what entities do we
know". Neither answers "what are we trying to find out", and without that there
is no queue -- so an autonomous run has nothing to work through and no way to
stop except by claiming to be finished.

**A topic holds no findings and no needs-attention flag.** The fold keeps the
question, its status, what it links to, and how far the log had advanced when it
was last looked at. Whether it *needs attention* is computed on read, by
`application.topic_attention`, from this state plus the corpus. A stored flag is
a second source of truth: it is written by one code path, read by another, and
goes stale the moment an event arrives that nobody thought to re-evaluate. A
computed one cannot go stale, because there is nothing to keep in sync.

That is the same trade `CorpusState` makes with document text, for a different
reason: there, to keep snapshots small; here, to keep a derived judgement from
being mistaken for a recorded fact.

**Status is VEX's vocabulary, not `open`/`closed`.** A dependency scanner that
only tracked open and closed would be useless, because the interesting states
are "we looked and it does not apply" and "we are looking". Every transition
carries a required justification, for the same reason `CorpusDocumentDropped`
requires a reason: a topic that stops being pursued without one is
indistinguishable from a topic nobody got to.

**The last-look cursor is a log position, not a timestamp.** Staleness here is
evidence-based -- a topic is stale because specific events arrived after the
last look, and the finding can name them. Wall-clock staleness fires on dormant
projects where nothing happened, which is the alert nobody acts on.
"""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

TopicStatus = Literal["open", "investigating", "answered", "not_pursuing", "superseded"]
"""Where a topic stands.

Borrowed from VEX rather than `open`/`closed` because the states that matter
operationally are the middle ones. `not_pursuing` is a decision someone made and
has to justify; `superseded` says another topic now covers this ground, which is
what stops a merged question from looking abandoned.
"""

CLOSED_STATUSES: frozenset[str] = frozenset({"answered", "not_pursuing", "superseded"})
"""Statuses that take a topic out of the queue.

Named once here rather than spelled as a literal at each check: the attention
registry, the read model, and `decide` all need the same answer to "is this
still live", and three copies of a set literal is how they drift apart.
"""


# ---------------- events ----------------


@register_event
class TopicOpened(DomainEvent):
    """A question the project has decided to track. The creation event.

    `rationale` is required and non-empty. A topic that appears with no reason
    is the same failure as a source that disappears with no reason: it looks
    deliberate, nothing can tell you whether it was, and an autonomous run that
    can open topics silently can manufacture its own work forever.
    """

    aggregate_type: str = "Topic"
    project_id: UUID
    question: str
    rationale: str
    scope: str = ""
    """What would count as an answer, written down before the searching starts.

    Optional because a topic opened mid-conversation often cannot say yet. When
    it is present it is the pre-registered protocol of a systematic review: the
    thing that stops "we found something interesting" from being retrofitted
    into "that is what we were looking for".
    """


@register_event
class TopicSubQuestionAdded(DomainEvent):
    aggregate_type: str = "Topic"
    key: str
    question: str


@register_event
class TopicSubQuestionResolved(DomainEvent):
    aggregate_type: str = "Topic"
    key: str
    answer: str


@register_event
class TopicSourceLinked(DomainEvent):
    """A corpus document bears on this topic.

    `source_id` is the corpus's, not a new identifier: the whole point is that
    the topic and the corpus can be joined, so that dropping a source can raise
    the topics resting on it.
    """

    aggregate_type: str = "Topic"
    source_id: str
    relation: str = "supports"
    note: str = ""


@register_event
class TopicSourceUnlinked(DomainEvent):
    aggregate_type: str = "Topic"
    source_id: str
    reason: str


@register_event
class TopicEntityLinked(DomainEvent):
    aggregate_type: str = "Topic"
    entity_id: str
    name: str = ""


@register_event
class TopicInvestigated(DomainEvent):
    """A look happened, and here is how far the log had got when it did.

    Recorded even when the look found nothing -- that is what makes
    `topic.rework_thrash` computable, and what stops an autonomous run from
    re-reading the same material every round and calling it progress.
    """

    aggregate_type: str = "Topic"
    at_position: str
    """The global feed position at the moment of the look, as text.

    Text rather than a structured position because `Position` is the store's
    type and this is the domain. It is compared for equality and inequality
    only; nothing here parses it.
    """

    summary: str = ""
    by_run_id: UUID | None = None
    outcome: str | None = None
    """How the round ended: "produced", "nothing", or "failed".

    `None` means the round predates this field, and is deliberately not one of
    the three. Defaulting to "produced" would quietly stop `_rework_thrash`
    counting historic fruitless rounds; defaulting to "nothing" would claim
    every past round found nothing. Neither is a thing anybody observed.

    `summary` stays free text for a person to read. This is the part something
    can branch on -- and what nothing branches on today is exactly why a
    crashed round and a fruitless one were indistinguishable.

    Nothing reads this field yet -- a reader who greps for a consumer finds
    none, and has no defence against deleting it on that evidence alone. It is
    written anyway because the distinction it records is only capturable at
    the instant a round ends: a log that did not capture it then can never be
    back-filled later. Writing it now costs one nullable field and keeps a
    future consumer possible; not writing it makes the distinction gone for
    good for every round between now and whenever one is built.
    """


@register_event
class TopicFindingRecorded(DomainEvent):
    """Something was learned. The unit of progress.

    An autonomous round that produced no `TopicFindingRecorded`, linked no
    source and opened no sub-question is empty however fluently it described
    itself, which is the whole defence against confabulated progress.
    """

    aggregate_type: str = "Topic"
    summary: str
    source_ids: list[str] = Field(default_factory=list)


@register_event
class TopicGapRecorded(DomainEvent):
    """Something was looked for and not found. The unit of ruled-out effort.

    The twin of `TopicFindingRecorded`, and recorded for the same reason: a
    round that produced nothing otherwise leaves only free text, so every later
    run re-derives the same absence from nothing.

    `tried` is what the agent says it attempted, not what the search instance
    was asked -- `format_results` flattens the payload to text at receipt and
    nothing downstream can map a snippet back to its query. It is a claim,
    useful because it tells the next reader what not to repeat, and it should
    not be read as a record of requests actually made.

    Recording a gap does not change status and does not silence anything. It is
    evidence a person decides from.
    """

    aggregate_type: str = "Topic"
    looking_for: str
    tried: list[str] = Field(default_factory=list)


@register_event
class TopicContested(DomainEvent):
    """Two sources disagree, and nobody has adjudicated yet.

    Recorded rather than resolved on the spot. In procedural domains an
    apparent contradiction is usually an unstated conditional -- both experts
    are right under conditions neither stated -- so the useful output is the
    pair and the question, not a winner picked by whoever noticed.
    """

    aggregate_type: str = "Topic"
    key: str
    nature: str
    source_ids: list[str] = Field(default_factory=list)


@register_event
class TopicContestResolved(DomainEvent):
    aggregate_type: str = "Topic"
    key: str
    resolution: str
    justification: str


@register_event
class TopicStatusChanged(DomainEvent):
    aggregate_type: str = "Topic"
    to_status: str
    justification: str


@register_event
class TopicTriggerAcknowledged(DomainEvent):
    """Silence one trigger on one topic, until the log passes `until_position`.

    Expiry is required. An acknowledgement with no end is a permanently muted
    alarm that nobody remembers muting, which is how a monitoring system starts
    lying to the people who rely on it.
    """

    aggregate_type: str = "Topic"
    trigger: str
    reason: str
    until_position: str


# ---------------- commands ----------------


@dataclass(frozen=True)
class OpenTopic:
    #: Which topic to open. The one command whose target cannot be read back off
    #: the state, there being no state yet.
    topic_id: UUID
    project_id: UUID
    question: str
    rationale: str
    scope: str = ""


@dataclass(frozen=True)
class AddSubQuestion:
    key: str
    question: str


@dataclass(frozen=True)
class ResolveSubQuestion:
    key: str
    answer: str


@dataclass(frozen=True)
class LinkSource:
    source_id: str
    relation: str = "supports"
    note: str = ""


@dataclass(frozen=True)
class UnlinkSource:
    source_id: str
    reason: str


@dataclass(frozen=True)
class LinkEntity:
    entity_id: str
    name: str = ""


@dataclass(frozen=True)
class RecordInvestigation:
    at_position: str
    summary: str = ""
    by_run_id: UUID | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class RecordFinding:
    summary: str
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecordGap:
    looking_for: str
    tried: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecordContest:
    key: str
    nature: str
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolveContest:
    key: str
    resolution: str
    justification: str


@dataclass(frozen=True)
class SetTopicStatus:
    to_status: TopicStatus
    justification: str


@dataclass(frozen=True)
class AcknowledgeTrigger:
    trigger: str
    reason: str
    until_position: str


TopicCommand = (
    OpenTopic
    | AddSubQuestion
    | ResolveSubQuestion
    | LinkSource
    | UnlinkSource
    | LinkEntity
    | RecordInvestigation
    | RecordFinding
    | RecordGap
    | RecordContest
    | ResolveContest
    | SetTopicStatus
    | AcknowledgeTrigger
)


# ---------------- state ----------------


class SubQuestion(BaseModel):
    question: str
    answer: str | None = None
    """None means open. The count of these is `topic.unanswered`."""


class Contest(BaseModel):
    nature: str
    source_ids: list[str] = Field(default_factory=list)
    resolution: str | None = None


class Acknowledgement(BaseModel):
    reason: str
    until_position: str


class TopicState(BaseModel):
    """Everything derivable from the topic's stream.

    Deliberately absent: any finding text, any attention flag, any score. The
    findings are in the log and belong to a read model; attention is computed;
    and a score would be a number nobody could re-derive.
    """

    topic_id: UUID | None = None
    """None before the topic exists. Set by the fold of `TopicOpened`."""

    project_id: UUID | None = None
    status: Literal[
        "new", "open", "investigating", "answered", "not_pursuing", "superseded"
    ] = "new"
    """`new` is "does not exist yet" and is not a `TopicStatus`.

    The house vocabulary from `project.py` and `corpus.py`: `decide` matches on
    it to reject everything but creation, and keeping it distinct from the five
    real statuses is what stops "never opened" from reading as "open".
    """

    question: str = ""
    scope: str = ""
    rationale: str = ""
    sub_questions: dict[str, SubQuestion] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    """Live links only. An unlink removes it, the event staying in the log."""

    entity_ids: list[str] = Field(default_factory=list)
    contests: dict[str, Contest] = Field(default_factory=dict)
    acknowledgements: dict[str, Acknowledgement] = Field(default_factory=dict)
    investigations: int = 0
    findings: int = 0
    gaps: int = 0
    """Looks that were written down as having found nothing.

    A count, like `findings`, and not a reason to stop: a topic with twenty
    gaps stays live and stays in the queue. Every response to that is a
    person's."""

    last_investigated_at: str | None = None
    """The `at_position` of the most recent look. None means never looked."""

    findings_at_last_investigation: int = 0
    """`findings` as of the previous look, so thrash is computable.

    An investigation that is followed by another investigation with no finding
    in between is rework. Keeping the counter at the moment of the look is what
    lets `decide` stay a pure function of state rather than reaching for the
    log.
    """

    @property
    def open_sub_questions(self) -> list[str]:
        return [key for key, sub in self.sub_questions.items() if sub.answer is None]

    @property
    def unresolved_contests(self) -> list[str]:
        return [key for key, contest in self.contests.items() if contest.resolution is None]

    @property
    def is_live(self) -> bool:
        """Whether this topic can still be queued. `new` is not live either."""
        return self.status in ("open", "investigating")


def initial_state() -> TopicState:
    return TopicState()


# ---------------- decide ----------------


def decide(command: TopicCommand, state: TopicState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `project.decide` and `corpus.decide`
    do. The "topic does not exist yet" rejection is a single case rather than a
    guard repeated per command.
    """
    topic_id = state.topic_id
    match command, state:
        case OpenTopic(), TopicState(status="new"):
            if not command.question.strip():
                raise CommandRejectedError("a topic needs a question")
            if not command.rationale.strip():
                # The same argument as a drop's reason. A topic that appears
                # with no rationale cannot be told apart from one an
                # autonomous run invented to keep itself busy.
                raise CommandRejectedError("a topic needs a rationale")
            return [
                TopicOpened(
                    aggregate_id=command.topic_id,
                    project_id=command.project_id,
                    question=command.question,
                    rationale=command.rationale,
                    scope=command.scope,
                )
            ]
        case OpenTopic(), _:
            raise CommandRejectedError("topic already opened")

        case _, TopicState(status="new"):
            raise CommandRejectedError("topic not opened")

        case AddSubQuestion(key=key, question=question), _:
            if key in state.sub_questions:
                raise CommandRejectedError(f"sub-question {key!r} already exists")
            if not question.strip():
                raise CommandRejectedError("a sub-question needs a question")
            return [TopicSubQuestionAdded(aggregate_id=topic_id, key=key, question=question)]

        case ResolveSubQuestion(key=key, answer=answer), _:
            sub = state.sub_questions.get(key)
            if sub is None:
                raise CommandRejectedError(f"unknown sub-question {key!r}")
            if sub.answer is not None:
                raise CommandRejectedError(f"sub-question {key!r} is already resolved")
            if not answer.strip():
                raise CommandRejectedError("resolving a sub-question requires an answer")
            return [TopicSubQuestionResolved(aggregate_id=topic_id, key=key, answer=answer)]

        case LinkSource(source_id=source_id, relation=relation, note=note), _:
            if source_id in state.source_ids:
                # Idempotent rather than rejected: an autonomous round that
                # re-reads a source it already linked has done nothing wrong,
                # and a raise here would fail the whole turn over it.
                return []
            return [
                TopicSourceLinked(
                    aggregate_id=topic_id, source_id=source_id, relation=relation, note=note
                )
            ]

        case UnlinkSource(source_id=source_id, reason=reason), _:
            if source_id not in state.source_ids:
                raise CommandRejectedError(f"source {source_id!r} is not linked")
            if not reason.strip():
                raise CommandRejectedError("unlinking a source requires a reason")
            return [
                TopicSourceUnlinked(aggregate_id=topic_id, source_id=source_id, reason=reason)
            ]

        case LinkEntity(entity_id=entity_id, name=name), _:
            if entity_id in state.entity_ids:
                return []
            return [TopicEntityLinked(aggregate_id=topic_id, entity_id=entity_id, name=name)]

        case (
            RecordInvestigation(
                at_position=at, summary=summary, by_run_id=run_id, outcome=outcome
            ),
            _,
        ):
            if not at.strip():
                raise CommandRejectedError("an investigation must say where the log stood")
            return [
                TopicInvestigated(
                    aggregate_id=topic_id,
                    at_position=at,
                    summary=summary,
                    by_run_id=run_id,
                    outcome=outcome,
                )
            ]

        case RecordFinding(summary=summary, source_ids=source_ids), _:
            if not summary.strip():
                raise CommandRejectedError("a finding needs a summary")
            return [
                TopicFindingRecorded(
                    aggregate_id=topic_id, summary=summary, source_ids=list(source_ids)
                )
            ]

        case RecordGap(looking_for=looking_for, tried=tried), _:
            if not looking_for.strip():
                raise CommandRejectedError("a gap needs to say what was looked for")
            if not [item for item in tried if item.strip()]:
                # Both required, for `TopicOpened`'s reason. A gap with nothing
                # tried says only "we do not know", which the topic already
                # said by being open.
                raise CommandRejectedError("a gap needs to say what was tried")
            return [
                TopicGapRecorded(
                    aggregate_id=topic_id, looking_for=looking_for, tried=list(tried)
                )
            ]

        case RecordContest(key=key, nature=nature, source_ids=source_ids), _:
            if key in state.contests:
                raise CommandRejectedError(f"contest {key!r} already recorded")
            if not nature.strip():
                raise CommandRejectedError("a contest needs a description")
            return [
                TopicContested(
                    aggregate_id=topic_id,
                    key=key,
                    nature=nature,
                    source_ids=list(source_ids),
                )
            ]

        case ResolveContest(key=key, resolution=resolution, justification=justification), _:
            contest = state.contests.get(key)
            if contest is None:
                raise CommandRejectedError(f"unknown contest {key!r}")
            if contest.resolution is not None:
                raise CommandRejectedError(f"contest {key!r} is already resolved")
            if not justification.strip():
                raise CommandRejectedError("resolving a contest requires a justification")
            return [
                TopicContestResolved(
                    aggregate_id=topic_id,
                    key=key,
                    resolution=resolution,
                    justification=justification,
                )
            ]

        case SetTopicStatus(to_status=to_status, justification=justification), _:
            if not justification.strip():
                # Every status transition is a judgement, and the ones that
                # take a topic out of the queue are exactly the ones a later
                # reader will want explained.
                raise CommandRejectedError("a status change requires a justification")
            if to_status == state.status:
                raise CommandRejectedError(f"topic is already {to_status}")
            return [
                TopicStatusChanged(
                    aggregate_id=topic_id, to_status=to_status, justification=justification
                )
            ]

        case AcknowledgeTrigger(trigger=trigger, reason=reason, until_position=until), _:
            if not reason.strip():
                raise CommandRejectedError("an acknowledgement requires a reason")
            if not until.strip():
                # An acknowledgement with no expiry is a silenced alarm nobody
                # remembers silencing, which is the failure mode that makes
                # monitoring systems stop being believed.
                raise CommandRejectedError("an acknowledgement requires an expiry position")
            return [
                TopicTriggerAcknowledged(
                    aggregate_id=topic_id,
                    trigger=trigger,
                    reason=reason,
                    until_position=until,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: TopicState, event: DomainEvent) -> TopicState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case TopicOpened(question=question, rationale=rationale, scope=scope):
            return TopicState(
                topic_id=event.aggregate_id,
                project_id=event.project_id,
                status="open",
                question=question,
                rationale=rationale,
                scope=scope,
            )

        case TopicSubQuestionAdded(key=key, question=question):
            return state.model_copy(
                update={
                    "sub_questions": {
                        **state.sub_questions,
                        key: SubQuestion(question=question),
                    }
                }
            )

        case TopicSubQuestionResolved(key=key, answer=answer):
            existing = state.sub_questions.get(key)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "sub_questions": {
                        **state.sub_questions,
                        key: existing.model_copy(update={"answer": answer}),
                    }
                }
            )

        case TopicSourceLinked(source_id=source_id):
            if source_id in state.source_ids:
                return state
            return state.model_copy(update={"source_ids": [*state.source_ids, source_id]})

        case TopicSourceUnlinked(source_id=source_id):
            return state.model_copy(
                update={"source_ids": [s for s in state.source_ids if s != source_id]}
            )

        case TopicEntityLinked(entity_id=entity_id):
            if entity_id in state.entity_ids:
                return state
            return state.model_copy(update={"entity_ids": [*state.entity_ids, entity_id]})

        case TopicInvestigated(at_position=at):
            return state.model_copy(
                update={
                    "investigations": state.investigations + 1,
                    "last_investigated_at": at,
                    # Snapshot the finding count *as of this look*, so the next
                    # look can tell whether anything came of this one.
                    "findings_at_last_investigation": state.findings,
                    # A look moves a topic out of `open`, which is what stops
                    # the queue from re-offering it as never-investigated.
                    "status": ("investigating" if state.status == "open" else state.status),
                }
            )

        case TopicFindingRecorded():
            return state.model_copy(update={"findings": state.findings + 1})

        case TopicGapRecorded():
            # Counts, and nothing else. Deliberately does not touch status:
            # see the event's docstring.
            return state.model_copy(update={"gaps": state.gaps + 1})

        case TopicContested(key=key, nature=nature, source_ids=source_ids):
            return state.model_copy(
                update={
                    "contests": {
                        **state.contests,
                        key: Contest(nature=nature, source_ids=list(source_ids)),
                    }
                }
            )

        case TopicContestResolved(key=key, resolution=resolution):
            existing = state.contests.get(key)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "contests": {
                        **state.contests,
                        key: existing.model_copy(update={"resolution": resolution}),
                    }
                }
            )

        case TopicStatusChanged(to_status=to_status):
            return state.model_copy(update={"status": to_status})

        case TopicTriggerAcknowledged(trigger=trigger, reason=reason, until_position=until):
            return state.model_copy(
                update={
                    "acknowledgements": {
                        **state.acknowledgements,
                        trigger: Acknowledgement(reason=reason, until_position=until),
                    }
                }
            )

    return state


class Topic(DeciderAggregate[TopicState, TopicCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Project` and `Corpus` exactly: the class attributes bind directly
    to the module-level functions rather than wrapping them in new method
    bodies, so there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "Topic"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
