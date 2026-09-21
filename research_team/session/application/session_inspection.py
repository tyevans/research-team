"""Inspection, statistics, and diffing for sessions."""

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_team.session.domain import Session, SessionPurpose

__all__ = [
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
