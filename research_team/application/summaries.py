"""The `/sessions` read model.

A projection: the same events the aggregate folds, grouped by session instead
of replayed into one. Pure -- it takes events and returns rows, so it needs no
store and is trivially testable.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsource import DomainEvent

from research_team.domain import (
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)


@dataclass(frozen=True)
class SessionSummary:
    """One row of `/sessions`, derived by folding a session's events."""

    session_id: UUID
    started_at: datetime
    turns: int
    files: int
    first_message: str
    forked_from: UUID | None = None
    failed_turns: int = 0


def summarize_sessions(events: list[DomainEvent]) -> list[SessionSummary]:
    """Group events by session and fold each group into a row, newest first."""
    grouped: dict[UUID, list[DomainEvent]] = {}
    for event in events:
        grouped.setdefault(event.aggregate_id, []).append(event)

    summaries = [
        _summarize(session_id, session_events)
        for session_id, session_events in grouped.items()
    ]
    return sorted(summaries, key=lambda summary: summary.started_at, reverse=True)


def _summarize(session_id: UUID, events: list[DomainEvent]) -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        started_at=events[0].occurred_at,
        turns=max(
            (e.turn_index for e in events if isinstance(e, TurnCompleted)),
            default=0,
        ),
        files=len(
            {e.path for e in events if isinstance(e, FileWritten | FileEdited)}
            - {e.path for e in events if isinstance(e, FileDeleted)}
        ),
        first_message=_first_user_text(events),
        forked_from=next(
            (e.source_session_id for e in events if isinstance(e, SessionForkedFrom)),
            None,
        ),
        failed_turns=sum(1 for e in events if isinstance(e, TurnFailed)),
    )


def _first_user_text(events: list[DomainEvent]) -> str:
    for event in events:
        if isinstance(event, UserMessageSent):
            return str(event.message.get("data", {}).get("content", ""))
    return ""
