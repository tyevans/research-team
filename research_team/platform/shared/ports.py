"""Shared technical protocol interfaces and feed abstractions.

Contains pure, domain-agnostic ports (such as event feed readers and activity
reporters). Domain-specific ports live inside their respective bounded contexts
(e.g., `research_team.session.application.ports`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from eventsource import DomainEvent


@dataclass(frozen=True)
class FeedEntry:
    """One event from the global feed, with the cursor that follows it.

    `aggregate_id` rather than `session_id`, and `aggregate_type` beside it,
    because the feed carries multiple aggregate types with their own streams.
    """

    aggregate_id: UUID
    aggregate_type: str
    event: DomainEvent
    position: object
    """Opaque to us: compared and persisted, never inspected or arithmetic'd."""


class EventFeed(Protocol):
    """Reads the store's global feed, in append order.

    Separate from aggregate repositories because it answers:
    not "what does this entity look like" but "what has happened lately",
    which is what a live view needs across aggregates.
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
        """A position from text, or None if it is not one this store can place."""
        ...

    async def wait_for_append(self, timeout: float) -> None:
        """Return once something has been appended, or after `timeout`."""
        ...


MessageKind = Literal["assistant", "tool"]


@dataclass(frozen=True)
class ActivityMessage:
    """A whole message produced, reported before a turn commits."""

    message_id: str
    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class ActivityDelta:
    """A chunk of assistant prose, to append to `message_id`."""

    message_id: str
    text: str


@dataclass(frozen=True)
class ActivityRemark:
    """A line about the run/turn itself, not about anything the log will hold."""

    text: str


ActivityNote = ActivityMessage | ActivityDelta | ActivityRemark

ActivityReporter = Callable[[ActivityNote], None]


# Re-exports for backward compatibility:
_SESSION_PORTS = {
    "SessionRepository",
    "SessionSummaries",
    "SummaryHealth",
    "TurnAccountingError",
    "TurnActivityBuffer",
    "RecordedMessage",
    "TurnResult",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalRefused",
    "ApprovalPort",
    "TurnExecutor",
}

__all__ = [  # noqa: F822
    "FeedEntry",
    "EventFeed",
    "MessageKind",
    "ActivityMessage",
    "ActivityDelta",
    "ActivityRemark",
    "ActivityNote",
    "ActivityReporter",
    *_SESSION_PORTS,
    "CorpusReadPort",
]


def __getattr__(name: str) -> Any:
    if name in _SESSION_PORTS:
        import importlib

        mod = importlib.import_module("research_team.session.application.ports")
        val = getattr(mod, name)
        globals()[name] = val
        return val
    if name == "CorpusReadPort":
        import importlib

        mod = importlib.import_module("research_team.research.application.corpus_read")
        val = mod.CorpusReadPort
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
