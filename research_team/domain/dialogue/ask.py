"""A conversation asked of a project: the questions, the answers, the citations.

Its own aggregate rather than a row in the ask registry, because the registry
is a bounded in-memory cache -- 64 entries, an hour idle -- and a conversation
that outlives the process it was asked in needs a stream, the same way a
`ResearchRun` needs one to survive the process dying at round forty. This is
the shape `docs/superpowers/specs/2026-08-16-ask-persistence-design.md` names
as the closest neighbour, and it looks like one: a short-lived, run-shaped
thing with its own id living beside a project.

**The id is minted by the server, not the browser.** Today's `chat_id` is a
string the browser chose, and `ConversationRegistry.get` checks the project it
was opened under rather than trusting it -- adequate for a key into a bounded
dict, not for something that becomes an aggregate id, a row key and a URL
segment. That is the identical hazard as letting a model choose an id, which
this codebase has already ruled against once. Task 4 does the minting; this
aggregate only types the id as a `UUID` and never accepts one shaped like a
browser string.

**`citations` is a tuple of `(kind, id)` pairs, `kind` currently only
`"source"`.** Deliberately not widened to include topics -- BACKLOG.md B52 is
the entry that does that, and a branch nothing can emit cannot be tested.
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
"""What a turn's answer pointed at. `id` is the cited thing's own id, as a
string -- a source in the corpus today, and only that, per the ruling above.
"""


# ---------------- events ----------------


@register_event
class AskConversationStarted(DomainEvent):
    """A conversation began, against one project. Must be the first event on
    the stream -- `decide` refuses `RecordAskTurn` against a conversation that
    has not started, so nothing else can be first.
    """

    aggregate_type: str = "AskConversation"
    project_id: UUID
    opened_at: datetime


@register_event
class AskTurnRecorded(DomainEvent):
    """One question answered, with the citations its answer rests on.

    Appended once per successful turn, from exactly where the in-memory
    registry used to be the only record -- see `AskService.ask`'s comment on
    why that has to be before the final `yield`, not after. A failed turn
    records nothing: this event is a fact about an answer that was given, not
    an attempt that was made.
    """

    aggregate_type: str = "AskConversation"
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)


# ---------------- commands ----------------


@dataclass(frozen=True)
class StartAskConversation:
    #: Which conversation to start. The creation command's target, minted by
    #: the server -- see the module docstring.
    conversation_id: UUID
    project_id: UUID
    opened_at: datetime


@dataclass(frozen=True)
class RecordAskTurn:
    conversation_id: UUID
    question: str
    answer: str
    citations: tuple[Citation, ...] = dc_field(default_factory=tuple)


AskConversationCommand = StartAskConversation | RecordAskTurn


# ---------------- state ----------------


class AskConversationState(BaseModel):
    """Everything derivable from a conversation's stream."""

    conversation_id: UUID | None = None
    project_id: UUID | None = None
    status: Literal["new", "started"] = "new"
    turns: int = 0

    @property
    def is_started(self) -> bool:
        return self.status == "started"


def initial_state() -> AskConversationState:
    return AskConversationState()


# ---------------- decide ----------------


def decide(command: AskConversationCommand, state: AskConversationState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce."""
    match command, state:
        case StartAskConversation(), AskConversationState(status="new"):
            return [
                AskConversationStarted(
                    aggregate_id=command.conversation_id,
                    project_id=command.project_id,
                    opened_at=command.opened_at,
                )
            ]
        case StartAskConversation(), _:
            raise CommandRejectedError("conversation already started")

        case RecordAskTurn(), AskConversationState(status="new"):
            raise CommandRejectedError("conversation not started")

        case RecordAskTurn(question=question, answer=answer, citations=citations), _:
            return [
                AskTurnRecorded(
                    aggregate_id=state.conversation_id,
                    question=question,
                    answer=answer,
                    citations=list(citations),
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: AskConversationState, event: DomainEvent) -> AskConversationState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case AskConversationStarted(project_id=project_id):
            return AskConversationState(
                conversation_id=event.aggregate_id,
                project_id=project_id,
                status="started",
            )

        case AskTurnRecorded():
            return state.model_copy(update={"turns": state.turns + 1})

    return state


class AskConversation(DeciderAggregate[AskConversationState, AskConversationCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = "AskConversation"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
