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
    SessionPurpose,
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
    project_id: UUID
    """The project this session shares a filesystem and knowledge graph with.

    Here because a list of sessions with no project key cannot be grouped
    under the projects they belong to, which is what the console's landing
    page is: projects, with their sessions inside them.

    No longer `| None`. A session that belongs to no project was once a real
    state; it is now unreachable, because `SessionStarted` requires a project
    and there is no other way to start one. The console can stop asking.

    Declared above the defaulted fields rather than in the position it used to
    hold: this is a dataclass, so a field with no default cannot follow one
    that has a default. That moves it in the positional argument order, which
    nothing here depends on -- every construction site names its fields.
    """
    purpose: SessionPurpose
    """What kind of work this session was for. See `domain.commands.SessionPurpose`.

    Required, matching `SessionStarted.purpose`, and declared above the
    defaulted fields for the same dataclass-ordering reason as `project_id`
    above -- a field with no default cannot follow one that has a default.
    """
    forked_from: UUID | None = None
    forked_at: int | None = None
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
        #
        # No default. `next` raises `StopIteration` on a stream with no
        # `SessionStarted`, which is what a stream with no creation event
        # deserves: it is not a session. A `None` default here would have
        # turned that corruption into a summary claiming the session belongs
        # to no project -- a shape the type no longer permits and the console
        # no longer renders, so it would surface somewhere further away.
        project_id=next(e.project_id for e in events if isinstance(e, SessionStarted)),
        # Same reasoning as `project_id` immediately above: `SessionStarted` is
        # the only event carrying it, required to be first on the stream, and
        # a stream with none is not a session.
        purpose=next(e.purpose for e in events if isinstance(e, SessionStarted)),
    )


def _first_user_text(events: list[DomainEvent]) -> str:
    for event in events:
        if isinstance(event, UserMessageSent):
            return str(event.message.get("data", {}).get("content", ""))
    return ""
