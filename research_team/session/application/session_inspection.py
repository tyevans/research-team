"""Inspection, statistics, queries, and diffing for sessions."""

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.session.application.ports import (
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
)
from research_team.session.application.summaries import SessionSummary
from research_team.session.domain import Session, SessionPurpose

__all__ = [
    "SessionQueries",
    "SessionStats",
    "compute_session_stats",
    "diff_file_maps",
    "filter_session_messages",
]


@dataclass(frozen=True)
class SessionStats:
    """High-level derived state and metrics for one session."""

    session_id: UUID
    project_id: UUID | None
    status: str
    purpose: SessionPurpose
    turn_index: int
    failed_turns: int
    total_messages: int
    compacted_through: int
    file_count: int
    file_paths: tuple[str, ...]
    forked_from: UUID | None
    forked_at: int | None


def compute_session_stats(session: Session, session_id: UUID | None = None) -> SessionStats:
    """Derive high-level summary metrics from a loaded session."""
    sid = session_id if session_id is not None else getattr(session, "aggregate_id", None)
    state = session.state
    return SessionStats(
        session_id=sid,
        project_id=state.project_id,
        status=state.status,
        purpose=state.purpose,
        turn_index=state.turn_index,
        failed_turns=state.failed_turns,
        total_messages=len(state.messages),
        compacted_through=state.compacted_through,
        file_count=len(state.files),
        file_paths=tuple(sorted(state.files.keys())),
        forked_from=state.forked_from,
        forked_at=state.forked_at,
    )


def filter_session_messages(
    session: Session,
    *,
    role: str | None = None,
    query: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Search and filter messages recorded in a session."""
    messages = session.state.messages
    results: list[dict[str, Any]] = []
    for msg in messages:
        if role is not None and msg.get("type") != role:
            continue
        if query is not None:
            text = str(msg.get("data", {}).get("content", "")).lower()
            if query.lower() not in text:
                continue
        results.append(msg)
        if limit is not None and len(results) >= limit:
            break
    return results


def diff_file_maps(
    files1: Mapping[str, Any],
    files2: Mapping[str, Any],
) -> dict[str, Any]:
    """Diff file maps between two sessions.

    Returns added, removed, modified, and unchanged file paths along with
    line change metrics for modified files.
    """
    keys1 = set(files1.keys())
    keys2 = set(files2.keys())

    added = sorted(keys2 - keys1)
    removed = sorted(keys1 - keys2)
    common = sorted(keys1 & keys2)

    modified: dict[str, dict[str, Any]] = {}
    unchanged: list[str] = []

    for path in common:
        c1 = str(files1[path].get("content", ""))
        c2 = str(files2[path].get("content", ""))
        if c1 == c2:
            unchanged.append(path)
        else:
            lines1 = c1.splitlines(keepends=True)
            lines2 = c2.splitlines(keepends=True)
            diff = list(difflib.unified_diff(lines1, lines2))
            add_count = sum(
                1 for line in diff if line.startswith("+") and not line.startswith("+++")
            )
            del_count = sum(
                1 for line in diff if line.startswith("-") and not line.startswith("---")
            )
            modified[path] = {
                "added_lines": add_count,
                "removed_lines": del_count,
            }

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }


class SessionQueries:
    """Read-side queries, timeline scrub folds, and inspection over sessions."""

    def __init__(
        self,
        repository: SessionRepository,
        summaries: SessionSummaries,
    ) -> None:
        self._repository = repository
        self._summaries = summaries

    async def load(self, session_id: UUID) -> Session:
        """One session's aggregate, folded from its events."""
        return await self._repository.load(session_id)

    async def history(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        return await self._repository.events_for(session_id)

    async def state_at(self, session_id: UUID, at: int) -> Session:
        """The session as it stood after its first `at` events.

        A pure fold of a prefix -- nothing is written, nothing is forked. This
        is what makes scrubbing a timeline cheap: the log is the state, so any
        point in it can be reconstituted just by stopping the fold early.
        """
        events = await self.history(session_id)
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fold at {at}: session has {len(events)} events")
        aggregate = self._repository.create(session_id)
        aggregate.load_from_history(events[:at])
        return aggregate

    async def list_sessions(self) -> list[SessionSummary]:
        """Every session in the store, newest first.

        Read straight out of the projection's table.
        """
        return await self._summaries.list()

    async def summaries_health(self) -> SummaryHealth:
        """Whether `list_sessions` can currently be trusted."""
        return await self._summaries.health()

    async def rebuild_summaries(self) -> None:
        """Derive the session list from the log again. Safe at any time."""
        await self._summaries.rebuild()

    async def session_stats(self, session_id: UUID) -> SessionStats:
        """High-level summary metrics for a session."""
        session = await self.load(session_id)
        return compute_session_stats(session, session_id)

    async def find_messages(
        self,
        session_id: UUID,
        *,
        role: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search and filter messages recorded in a session."""
        session = await self.load(session_id)
        return filter_session_messages(session, role=role, query=query, limit=limit)

    async def diff_session_files(
        self, session_id: UUID, other_session_id: UUID
    ) -> dict[str, Any]:
        """Diff files between two sessions.

        Returns added, removed, modified, and unchanged file paths along with
        line change metrics for modified files.
        """
        s1 = await self.load(session_id)
        s2 = await self.load(other_session_id)
        return diff_file_maps(s1.state.files, s2.state.files)
