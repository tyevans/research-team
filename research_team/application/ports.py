"""The interfaces the application layer needs the outside world to satisfy.

Ports are declared here, next to the code that calls them, and implemented in
`research_team.infrastructure`. Nothing in this module knows about SQLite,
langchain, or deepagents; those are details chosen at composition time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from eventsource import DomainEvent

from research_team.domain import CodingSession

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

    async def all_events(self) -> list[DomainEvent]:
        """Every event across every session, for building projections."""
        ...

    async def close(self) -> None: ...


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
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult: ...
