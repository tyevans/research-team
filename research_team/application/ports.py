"""The interfaces the application layer needs the outside world to satisfy.

Ports are declared here, next to the code that calls them, and implemented in
`research_team.infrastructure`. Nothing in this module knows about SQLite,
langchain, or deepagents; those are details chosen at composition time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from eventsource import DomainEvent

from research_team.domain import CodingSession

if TYPE_CHECKING:
    # Imported for typing only: `summaries` imports nothing from here, and
    # keeping it that way is what stops the ports module from depending on a
    # use case that depends on it.
    from research_team.application.summaries import SessionSummary

ActivityReporter = Callable[[str], None]
"""Called with a one-line progress note while a turn is in flight."""


class SessionRepository(Protocol):
    """Loads and stores `CodingSession` aggregates, and reads raw event streams.

    The raw reads exist because this is an event-sourced application: the log
    itself is a first-class read model (`/log`, `/history`, `/diff`, forking),
    not just the aggregate's private bookkeeping.
    """

    def create(self, session_id: UUID) -> CodingSession:
        """A new, unsaved aggregate. Does not touch storage."""
        ...

    async def load(self, session_id: UUID) -> CodingSession: ...

    async def save(self, session: CodingSession) -> None:
        """Append the aggregate's pending events atomically."""
        ...

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        ...

    async def close(self) -> None: ...


class SessionSummaries(Protocol):
    """The `/sessions` list, as a thing that is stored rather than computed.

    Separate from `SessionRepository` because it is the query side: it answers
    from a view maintained by a projection, and knows nothing about aggregates
    or streams. There is deliberately no method here for reading every event --
    that was the full scan this port exists to replace.
    """

    async def list(self) -> list["SessionSummary"]:
        """Every session, newest first."""
        ...




@dataclass(frozen=True)
class FeedEntry:
    """One event from the global feed, with the cursor that follows it."""

    session_id: UUID
    event: DomainEvent
    position: object
    """Opaque to us: compared and persisted, never inspected or arithmetic'd."""


class EventFeed(Protocol):
    """Reads the store's global feed, across all sessions, in append order.

    Separate from `SessionRepository` because it answers a different question:
    not "what does this session look like" but "what has happened lately",
    which is what a live view needs.
    """

    async def latest_position(self) -> object | None:
        """The cursor at the end of the feed right now, or None if it is empty."""
        ...

    async def read_since(self, position: object | None) -> list[FeedEntry]:
        """Everything appended after `position`. Exclusive; None means from the start."""
        ...

    def encode_position(self, position: object) -> str:
        """A position as text, for handing to a client that may hand it back."""
        ...

    def decode_position(self, raw: str) -> object | None:
        """A position from text, or None if it is not one this store can place.

        Returning None rather than raising is the contract: the text comes from
        outside, so "unusable" is an ordinary answer and the caller is expected
        to have somewhere else to start.
        """
        ...

    async def wait_for_append(self, timeout: float) -> None:
        """Return once something has been appended, or after `timeout`.

        A hint, not a guarantee, and deliberately carries no events: the reader
        still asks the store what is new, so ordering and completeness stay the
        store's business. All this saves is the wait -- an implementation that
        cannot tell when a write happened may simply sleep, and the only cost
        is latency the caller had already agreed to.
        """
        ...


class TurnAccountingError(Exception):
    """The agent returned something the log cannot faithfully record.

    Distinct from a turn that merely failed. A failed turn is an ordinary
    event -- the model timed out, the endpoint refused -- and gets a
    `TurnFailed` marker. This means our own accounting of what the agent
    added has drifted, so recording *anything* would be recording a lie.
    It propagates without touching the log.
    """


MessageKind = Literal["assistant", "tool"]


@dataclass(frozen=True)
class RecordedMessage:
    """One message the agent produced, ready to become an event.

    `payload` is opaque to the application layer: it is stored and replayed
    verbatim, and only the executor that produced it knows its shape.
    """

    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class TurnResult:
    """What one agent pass produced, beyond the file events it already emitted."""

    messages: tuple[RecordedMessage, ...]
    reply_text: str


class TurnExecutor(Protocol):
    """Runs the agent for one turn.

    File mutations are recorded on the aggregate as they happen -- the agent's
    filesystem *is* the aggregate -- while conversation messages come back in
    the result for the caller to append. That split is deliberate: the caller
    decides whether the turn is committed at all, and a turn that raises is
    discarded whole, aggregate included.
    """

    @property
    def model_name(self) -> str: ...

    def encode_user_message(self, text: str) -> dict:
        """The stored payload for a user's message, in the executor's format."""
        ...

    async def execute(
        self,
        session: CodingSession,
        *,
        messages: list[dict],
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult:
        """Run one pass over `messages`, which is what the model will see.

        The caller chooses those, rather than the executor reading them off the
        session: what the model is shown is a use-case decision (see
        `research_team.application.context`), and the executor must not quietly
        disagree with what the caller counted as sent.
        """
        ...
