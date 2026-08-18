"""A guided conversation with a goal it can be measured against.

A second conversational aggregate beside `AskConversation`, and the spec's §1
gives the one-line reason it is not the same one re-prompted:
`AskConversationState` is four fields -- id, project, status, turn count --
with nowhere to put a goal or a stopping condition, and nothing in it can
express "this dialogue is trying to reach X and has not yet". A stopping
condition **is** state.

**`prompt` is the system's utterance and `reply` is the reader's**, in the
ordinary sense of both words. A socratic dialogue leads by questioning, so the
system asks and the reader answers -- which is the *inverse* of
`AskTurnRecorded`'s question/answer, deliberately. That inversion is the
feature, and a field layout that hid it is how someone later writes a socratic
turn that behaves like an ask turn.

**A turn is therefore a completed pair, and the newest question belongs to no
turn.** A turn pairs the reader's answer with the response it drew --
`Started(opening_prompt=Q1)`, `Turn(A1, Q2)`, `Turn(A2, Q3)` -- which is one
executor call per event and stores every utterance exactly once. The pairing
that seems more natural, a question with its own answer, leaves the newest
question belonging to no turn and forces it to be stored a second time; an
intermediate draft did that and put every system utterance in the log twice.

So the opening question is an orphan and lives on the start event, and the
question currently outstanding is *derived* -- the last turn's `prompt`, or
`opening_prompt` when there are none.

**The status is terminal and the ask's is not.** `AskConversation` has `new`
and `started` and correctly never ends, because an ask has no notion of being
finished. A dialogue that reached its stopping condition and then accepted
three more exchanges has a stopping condition in name only, so `concluded`
refuses everything.

**The id is minted by the server**, as `AskConversation`'s is and for the
identical reason: an aggregate id, a row key and a URL segment cannot be a
string a browser chose. `SocraticDialogueService.begin` does the minting; this
module only types it as a `UUID`.
"""

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

CitationKind = Literal["source"]

Citation = tuple[CitationKind, str]
"""What a reply rested on. Narrowed to `"source"` for `AskConversation`'s
stated reason: `read_source` is the only admitted tool that opens one
identified thing, and a branch nothing can emit cannot be tested."""

EvidenceKind = Literal["attempt", "assessment"]
"""Where an observation came from.

Two members and the difference is what a reader could argue with: `"attempt"`
means a component the reader answered and the server graded, which is a fact;
`"assessment"` means the model judged the reader's prose, which is an opinion.
A stopping condition met entirely by assessments is a dialogue that graded its
own homework, and keeping the kinds apart is what makes that visible later.
"""

ConclusionReason = Literal["met", "abandoned"]


# ---------------- events ----------------


@register_event
class SocraticDialogueStarted(DomainEvent):
    """A dialogue began, against one project, aimed at one thing.

    Must be the first event on the stream -- `decide` refuses every other
    command against a dialogue that has not started.

    `opening_prompt` defaults to empty for the schema-evolution strategy's
    case 1: it was added after the first draft of this event and an older
    payload without it reads as "the opening question was not recorded", which
    is honest -- the dialogue is still resumable from its goal and its turns.
    """

    aggregate_type: str = "SocraticDialogue"
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    opened_at: datetime


@register_event
class SocraticTurnRecorded(DomainEvent):
    """One exchange: what the reader answered, and what the dialogue said back.

    Appended once per successful turn. A failed turn records nothing, matching
    `AskTurnRecorded`: this is a fact about an exchange that happened, not an
    attempt that was made.

    **The pairing is reader-then-system, and it is not the same as the field
    naming.** `prompt` is the system's utterance and `reply` is the reader's
    (see the module docstring), but a *turn* pairs the reader's answer with the
    response it drew -- not a question with its own answer. That is the shape of
    one executor call, `reply` in and `prompt` out, and it stores every
    utterance in the conversation exactly once:

        Started(opening_prompt=Q1) / Turn(A1, Q2) / Turn(A2, Q3) / Concluded

    The alternative -- pairing each question with its answer -- leaves the
    newest question belonging to no turn, which then has to be stored a second
    time. An intermediate draft did that, with a `next_prompt` field, and put
    every system utterance in the log twice; two copies that can drift is a bug
    that surfaces only on a rebuild.

    So the opening question is an orphan and lives on
    `SocraticDialogueStarted.opening_prompt`, and the question currently
    outstanding is *derived* -- the last turn's `prompt`, or `opening_prompt`
    when there are none. `SocraticDialogueRow.pending_prompt` precomputes it;
    nothing stores it twice.

    `prompt` is a question on every turn but the last, where it is whatever the
    dialogue said as it concluded. The field is "what the dialogue said", and
    `SocraticDialogueConcluded` is what says the dialogue ended -- so nothing
    here has to encode "this one is not a question".
    """

    aggregate_type: str = "SocraticDialogue"
    reply: str
    prompt: str
    citations: list[Citation] = Field(default_factory=list)


@register_event
class SocraticProgressObserved(DomainEvent):
    """Something the reader demonstrated, and what showed it.

    Separate from `SocraticTurnRecorded` rather than a field on it, because
    progress and exchanges are not one-to-one in either direction: a turn can
    demonstrate nothing, and a graded `mcq` attempt can arrive without any
    exchange around it at all.
    """

    aggregate_type: str = "SocraticDialogue"
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""
    """What the evidence was, in whatever form it took -- a component id and
    its verdict for an attempt, the model's words for an assessment. Free text
    because the two shapes have nothing in common and a union of two typed
    payloads would be read by nothing."""


@register_event
class SocraticDialogueConcluded(DomainEvent):
    """The dialogue ended, and why."""

    aggregate_type: str = "SocraticDialogue"
    reason: ConclusionReason


# ---------------- commands ----------------


@dataclass(frozen=True)
class StartSocraticDialogue:
    dialogue_id: UUID
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str
    opened_at: datetime


@dataclass(frozen=True)
class RecordSocraticTurn:
    dialogue_id: UUID
    reply: str
    prompt: str
    citations: tuple[Citation, ...] = dc_field(default_factory=tuple)


@dataclass(frozen=True)
class ObserveSocraticProgress:
    dialogue_id: UUID
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""


@dataclass(frozen=True)
class ConcludeSocraticDialogue:
    dialogue_id: UUID
    reason: ConclusionReason


SocraticCommand = (
    StartSocraticDialogue
    | RecordSocraticTurn
    | ObserveSocraticProgress
    | ConcludeSocraticDialogue
)


# ---------------- state ----------------


class SocraticDialogueState(BaseModel):
    """Everything derivable from a dialogue's stream.

    **`observations` holds the texts, not a count**, unlike
    `AskConversationState.turns`. The state has to be able to express what the
    reader has demonstrated so far, and a counter cannot. The cost is a fold
    that grows with the dialogue rather than staying constant, which is
    recorded on `build_socratic_dialogue_repository` where the snapshot
    decision lives.
    """

    dialogue_id: UUID | None = None
    project_id: UUID | None = None
    topic: str = ""
    goal: str = ""
    stopping_condition: str = ""
    status: Literal["new", "started", "concluded"] = "new"
    turns: int = 0
    observations: list[str] = Field(default_factory=list)

    @property
    def is_started(self) -> bool:
        return self.status == "started"

    @property
    def is_concluded(self) -> bool:
        return self.status == "concluded"


def initial_state() -> SocraticDialogueState:
    return SocraticDialogueState()


# ---------------- decide ----------------


def decide(command: SocraticCommand, state: SocraticDialogueState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce."""
    match command, state:
        case StartSocraticDialogue(), SocraticDialogueState(status="new"):
            return [
                SocraticDialogueStarted(
                    aggregate_id=command.dialogue_id,
                    project_id=command.project_id,
                    topic=command.topic,
                    goal=command.goal,
                    stopping_condition=command.stopping_condition,
                    opening_prompt=command.opening_prompt,
                    opened_at=command.opened_at,
                )
            ]
        # Concluded is checked before every other refusal, `StartSocraticDialogue`
        # included, because a concluded dialogue is neither `new` nor merely
        # started and the two messages say different things to whoever reads
        # them. Ordered after the one arm that must win -- a `new` state can
        # never be `concluded`, so starting a fresh dialogue is unaffected.
        #
        # This arm sat *below* the `Start` catch-all in the first draft, which
        # made a start against a concluded dialogue report "already started"
        # while this comment claimed otherwise. Unreachable in practice (ids are
        # server-minted, so reuse cannot happen) and therefore worth nothing but
        # the comment being true; `test_starting_a_concluded_dialogue_says_so`
        # is what fails if it moves back.
        case _, SocraticDialogueState(status="concluded"):
            raise CommandRejectedError("dialogue already concluded")

        case StartSocraticDialogue(), _:
            raise CommandRejectedError("dialogue already started")

        case _, SocraticDialogueState(status="new"):
            raise CommandRejectedError("dialogue not started")

        case RecordSocraticTurn(reply=reply, prompt=prompt, citations=citations), _:
            return [
                SocraticTurnRecorded(
                    aggregate_id=state.dialogue_id,
                    reply=reply,
                    prompt=prompt,
                    citations=list(citations),
                )
            ]

        case ObserveSocraticProgress(
            observation=observation, evidence=evidence, detail=detail
        ), _:
            return [
                SocraticProgressObserved(
                    aggregate_id=state.dialogue_id,
                    observation=observation,
                    evidence=evidence,
                    detail=detail,
                )
            ]

        case ConcludeSocraticDialogue(reason=reason), _:
            return [SocraticDialogueConcluded(aggregate_id=state.dialogue_id, reason=reason)]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: SocraticDialogueState, event: DomainEvent) -> SocraticDialogueState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case SocraticDialogueStarted(
            project_id=project_id, topic=topic, goal=goal, stopping_condition=condition
        ):
            return SocraticDialogueState(
                dialogue_id=event.aggregate_id,
                project_id=project_id,
                topic=topic,
                goal=goal,
                stopping_condition=condition,
                status="started",
            )

        # A counter, not the text. Which question is outstanding is a *read*
        # concern -- the last turn's `prompt`, or `opening_prompt` -- and no
        # decision in this module needs it, so the aggregate does not carry it.
        case SocraticTurnRecorded():
            return state.model_copy(update={"turns": state.turns + 1})

        case SocraticProgressObserved(observation=observation):
            return state.model_copy(
                update={"observations": [*state.observations, observation]}
            )

        case SocraticDialogueConcluded():
            return state.model_copy(update={"status": "concluded"})

    return state


class SocraticDialogue(DeciderAggregate[SocraticDialogueState, SocraticCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = "SocraticDialogue"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
