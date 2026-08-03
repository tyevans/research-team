"""Domain objects rendered as the JSON the browser consumes.

The web equivalent of the CLI's formatters: pure functions, no I/O, and the
only place that knows the wire shape. Keeping them here means the API can be
reshaped for the UI without anything below noticing.
"""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.application import ForkNode, SessionSummary
from research_team.domain import (
    CodingSession,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    TurnFailed,
)

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

_ROLE_FOR_TYPE = {"human": "user", "ai": "assistant", "tool": "tool"}


def event_summary(event: DomainEvent) -> str:
    """One line describing an event, for the timeline."""
    if isinstance(event, SessionStarted):
        return event.model_name
    if isinstance(event, FileEdited):
        # The path alone says less than the log already knows: the edit intent
        # is recorded, so show what actually changed.
        return f"{event.path}  {_snippet(event.old_string)} → {_snippet(event.new_string)}"
    if isinstance(event, FILE_EVENTS):
        return event.path
    if isinstance(event, SessionForkedFrom):
        return f"from {str(event.source_session_id)[:8]} at event {event.at_event}"
    if isinstance(event, TurnFailed):
        if event.cancelled:
            return f"turn {event.turn_index}: cancelled"
        return f"turn {event.turn_index}: {event.error_type}: {event.error_message[:80]}"
    if hasattr(event, "turn_index"):
        return f"turn {event.turn_index}"
    if hasattr(event, "message"):
        data = event.message.get("data", {})
        calls = data.get("tool_calls") or []
        if calls:
            return "→ " + ", ".join(call.get("name", "?") for call in calls)
        return " ".join(str(data.get("content", "")).split())[:120]
    return ""


def _snippet(text: str, limit: int = 30) -> str:
    """One line of an edit string, short enough to sit in a timeline row."""
    first = " ".join(text.split())
    return first[:limit] + "…" if len(first) > limit else first or "(nothing)"


def event_row(index: int, event: DomainEvent) -> dict[str, Any]:
    """One timeline row. `index` is 1-based, matching the REPL's numbering."""
    return {
        "index": index,
        "type": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
        "summary": event_summary(event),
        "path": getattr(event, "path", None),
        "turn_index": getattr(event, "turn_index", None),
        "is_error": getattr(event, "is_error", None),
        # None on everything that is not a failed turn, so a client can tell
        # "stopped on purpose" from "broke" without reading prose.
        "cancelled": getattr(event, "cancelled", None),
    }


def event_rows(events: list[DomainEvent]) -> list[dict[str, Any]]:
    return [event_row(i, event) for i, event in enumerate(events, start=1)]


def message_view(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    return {
        "role": _ROLE_FOR_TYPE.get(payload.get("type", ""), payload.get("type", "")),
        "content": data.get("content", ""),
        "tool_calls": [
            {"name": call.get("name", "?"), "args": call.get("args", {})}
            for call in (data.get("tool_calls") or [])
        ],
        "is_error": data.get("status") == "error",
    }


def _revision_counts(events: list[DomainEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if isinstance(event, FILE_EVENTS):
            counts[event.path] = counts.get(event.path, 0) + 1
    return counts


def session_view(
    session: CodingSession, events: list[DomainEvent], *, at: int | None = None
) -> dict[str, Any]:
    """A session's full state. `at` marks a scrubbed view rather than HEAD."""
    state = session.state
    revisions = _revision_counts(events if at is None else events[:at])
    return {
        "id": str(state.session_id),
        "system_prompt": state.system_prompt,
        "model_name": state.model_name,
        "turn_index": state.turn_index,
        "failed_turns": state.failed_turns,
        "forked_from": str(state.forked_from) if state.forked_from else None,
        "forked_at": state.forked_at,
        "event_count": len(events),
        "at": at,
        "files": [
            {
                "path": path,
                "size": len(data.get("content", "")),
                "revisions": revisions.get(path, 0),
            }
            for path, data in sorted(state.files.items())
        ],
        "messages": [message_view(payload) for payload in state.messages],
    }


def file_history(events: list[DomainEvent], path: str) -> list[dict[str, Any]]:
    """Every event that touched one path, with the edit intent where recorded."""
    rows = []
    for index, event in enumerate(events, start=1):
        if not isinstance(event, FILE_EVENTS) or event.path != path:
            continue
        row = {
            "index": index,
            "type": type(event).__name__,
            "occurred_at": event.occurred_at.isoformat(),
            "content": getattr(event, "file_data", {}).get("content"),
            "old_string": None,
            "new_string": None,
            "replace_all": None,
        }
        if isinstance(event, FileEdited):
            row["old_string"] = event.old_string
            row["new_string"] = event.new_string
            row["replace_all"] = event.replace_all
        rows.append(row)
    return rows


def summary_view(summary: SessionSummary) -> dict[str, Any]:
    return {
        "id": str(summary.session_id),
        "started_at": summary.started_at.isoformat(),
        "turns": summary.turns,
        "files": summary.files,
        "first_message": summary.first_message,
        "forked_from": str(summary.forked_from) if summary.forked_from else None,
        "forked_at": summary.forked_at,
        "failed_turns": summary.failed_turns,
    }


def tree_view(nodes: list[ForkNode]) -> list[dict[str, Any]]:
    return [
        {**summary_view(node.session), "children": tree_view(list(node.children))}
        for node in nodes
    ]


def feed_event(session_id: UUID, event: DomainEvent, index: int | None) -> dict[str, Any]:
    """One live event, as pushed over SSE.

    Carries the same fields as a timeline row, so a live-appended event renders
    identically to a fetched one and the browser needs no follow-up request to
    colour it correctly.
    """
    return {
        "session_id": str(session_id),
        **event_row(index if index is not None else 0, event),
    }
