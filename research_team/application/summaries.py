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
    SessionStarted,
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
    forked_at: int | None = None
    failed_turns: int = 0
    project_id: UUID | None = None
    """The project this session shares a filesystem and knowledge graph with.

    Here because a list of sessions with no project key cannot be grouped
    under the projects they belong to, which is what the console's landing
    page is: projects, with their sessions inside them. `None` is a session
    that belongs to no project, which is a real state and not a gap.
    """


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


@dataclass(frozen=True)
class ForkNode:
    """A session in the lineage forest, with the sessions forked from it."""

    session: SessionSummary
    children: tuple["ForkNode", ...] = ()


def build_fork_tree(summaries: list[SessionSummary]) -> list[ForkNode]:
    """Arrange sessions into the forest their fork lineage describes.

    Roots are sessions that were not forked from anything -- including any
    whose parent is missing from the input, so a session never disappears just
    because its ancestor is gone.
    """
    known = {summary.session_id for summary in summaries}
    children: dict[UUID, list[SessionSummary]] = {}
    roots: list[SessionSummary] = []
    for summary in summaries:
        parent = summary.forked_from
        if parent is not None and parent in known:
            children.setdefault(parent, []).append(summary)
        else:
            roots.append(summary)

    def node(summary: SessionSummary) -> ForkNode:
        return ForkNode(
            session=summary,
            children=tuple(
                node(child)
                for child in sorted(
                    children.get(summary.session_id, []),
                    key=lambda child: child.started_at,
                )
            ),
        )

    return [node(root) for root in roots]


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
        forked_at=next(
            (e.at_event for e in events if isinstance(e, SessionForkedFrom)),
            None,
        ),
        failed_turns=sum(1 for e in events if isinstance(e, TurnFailed)),
        # `SessionStarted` is the only event carrying it, and it is required to
        # be first on the stream -- so a session's project is fixed the moment
        # it exists and there is no later event to fold over.
        project_id=next(
            (e.project_id for e in events if isinstance(e, SessionStarted)),
            None,
        ),
    )


def _first_user_text(events: list[DomainEvent]) -> str:
    for event in events:
        if isinstance(event, UserMessageSent):
            return str(event.message.get("data", {}).get("content", ""))
    return ""
