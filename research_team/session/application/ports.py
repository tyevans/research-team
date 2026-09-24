"""Session application ports and contracts.

Ports and protocol interfaces for the Session bounded context, defining how
the use cases orchestrate session lifecycles, turns, approvals, and projections.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from eventsource import DomainEvent

from research_team.platform.shared.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityNote,
    ActivityRemark,
    ActivityReporter,
    MessageKind,
)
from research_team.session.domain import Session

if TYPE_CHECKING:
    from research_team.session.application.summaries import SessionSummary


class SessionRepository(Protocol):
    """Loads and stores `Session` aggregates, and reads raw event streams.

    The raw reads exist because this is an event-sourced application: the log
    itself is a first-class read model (`/log`, `/history`, `/diff`, forking),
    not just the aggregate's private bookkeeping.
    """

    def create(self, session_id: UUID) -> Session:
        """A new, unsaved aggregate. Does not touch storage."""
        ...

    async def load(self, session_id: UUID) -> Session: ...

    async def save(self, session: Session) -> None:
        """Append the aggregate's pending events atomically."""
        ...

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        ...

    async def close(self) -> None: ...

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, from the creation events."""
        ...


@dataclass(frozen=True)
class SummaryHealth:
    """Whether the `/sessions` list can be trusted right now."""

    failed_events: int
    following: bool
    behind: bool

    @property
    def healthy(self) -> bool:
        return self.failed_events == 0 and self.following


class SessionSummaries(Protocol):
    """The `/sessions` list, as a thing that is stored rather than computed."""

    async def list(self) -> list["SessionSummary"]: ...

    async def health(self) -> SummaryHealth: ...

    async def rebuild(self) -> None: ...


class TurnAccountingError(Exception):
    """The agent returned something the log cannot faithfully record."""


class TurnActivityBuffer(Protocol):
    """Holds a turn's provisional content for as long as the turn lasts."""

    def begin(self, session_id: UUID) -> None: ...

    def reporter(self, session_id: UUID) -> ActivityReporter: ...

    def settle(self, session_id: UUID, *, committed: bool) -> None: ...


@dataclass(frozen=True)
class RecordedMessage:
    """One message the agent produced, ready to become an event."""

    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class TurnResult:
    """What one agent pass produced, beyond the file events it already emitted."""

    messages: tuple[RecordedMessage, ...]
    reply_text: str


@dataclass(frozen=True)
class ApprovalRequest:
    """A request for a human to approve, edit, or reject a gated tool call."""

    session_id: UUID
    tool_name: str
    args: dict
    description: str
    allowed_decisions: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalDecision:
    """A human's response to an ApprovalRequest."""

    type: str
    edited_args: dict | None = None
    message: str | None = None


class ApprovalRefused(Exception):
    """Raised by an `ApprovalPort` instead of a decision when no human decision was made."""


class ApprovalPort(Protocol):
    """Asks a human to approve, edit, or reject a gated tool call."""

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...


class TurnExecutor(Protocol):
    """Runs the agent for one turn."""

    @property
    def model_name(self) -> str: ...

    @property
    def tools(self) -> tuple[Any, ...]: ...

    def encode_user_message(self, text: str) -> dict: ...

    async def execute(
        self,
        session: Session,
        *,
        messages: list[dict],
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult: ...


__all__ = [
    "ActivityDelta",
    "ActivityMessage",
    "ActivityNote",
    "ActivityRemark",
    "ActivityReporter",
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRefused",
    "ApprovalRequest",
    "MessageKind",
    "RecordedMessage",
    "SessionRepository",
    "SessionSummaries",
    "SummaryHealth",
    "TurnAccountingError",
    "TurnActivityBuffer",
    "TurnExecutor",
    "TurnResult",
]
