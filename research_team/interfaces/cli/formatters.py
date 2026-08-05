"""Rendering of domain objects as terminal text. Pure functions, no I/O."""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.application import SessionSummary, SummaryHealth, TurnOutcome
from research_team.domain import (
    CodingSession,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    TurnFailed,
)

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)


def _summary(event: DomainEvent) -> str:
    if isinstance(event, FILE_EVENTS):
        return event.path
    if isinstance(event, ConversationCompacted):
        saved = (
            f", ~{event.tokens_before:,}->{event.tokens_after:,} tok"
            if event.tokens_before
            else ""
        )
        return f"first {event.through_index} messages summarized ({event.strategy}{saved})"
    if isinstance(event, SessionForkedFrom):
        return f"from {str(event.source_session_id)[:8]} at event {event.at_event}"
    if isinstance(event, TurnFailed):
        return f"turn {event.turn_index}: {event.error_type}: {event.error_message[:40]}"
    if hasattr(event, "turn_index"):
        return f"turn {event.turn_index}"
    if hasattr(event, "message"):
        prefix = "! " if getattr(event, "is_error", False) else ""
        content = prefix + str(event.message.get("data", {}).get("content", "")).strip()
        calls = event.message.get("data", {}).get("tool_calls") or []
        if calls:
            return "→ " + ", ".join(call.get("name", "?") for call in calls)
        return " ".join(content.split())[:60]
    return ""


def format_log(events: list[DomainEvent], limit: int) -> str:
    if not events:
        return "(no events)"
    selected = events[-limit:]
    offset = len(events) - len(selected)
    return "\n".join(
        f"#{offset + i + 1:<4} {event.occurred_at:%H:%M:%S}  "
        f"{type(event).__name__:<24} {_summary(event)}"
        for i, event in enumerate(selected)
    )


def format_sessions(summaries: list[SessionSummary], current: UUID) -> str:
    if not summaries:
        return "(no stored sessions)"
    rows = []
    for index, summary in enumerate(summaries, start=1):
        marker = "*" if summary.session_id == current else " "
        opening = " ".join(summary.first_message.split())[:40] or "(no messages)"
        notes = ""
        if summary.forked_from is not None:
            notes += f"  ⑂{str(summary.forked_from)[:8]}"
        if summary.failed_turns:
            notes += f"  {summary.failed_turns} failed"
        rows.append(
            f"{marker}{index:>3}  {str(summary.session_id)[:8]}  "
            f"{summary.started_at:%Y-%m-%d %H:%M}  "
            f"{summary.turns:>3} turns  {summary.files:>3} files  {opening}{notes}"
        )
    return "\n".join(rows)


def format_diff(events: list[DomainEvent], path: str) -> str:
    """Surface the edit intent that FileEdited already records."""
    edits = [e for e in events if isinstance(e, FileEdited) and e.path == path]
    if not edits:
        return f"(no recorded edits for {path})"
    blocks = []
    for number, edit in enumerate(edits, start=1):
        scope = " (all occurrences)" if edit.replace_all else ""
        blocks.append(
            f"edit {number}{scope}\n"
            + "\n".join(f"  - {line}" for line in edit.old_string.splitlines() or [""])
            + "\n"
            + "\n".join(f"  + {line}" for line in edit.new_string.splitlines() or [""])
        )
    return "\n\n".join(blocks)


def format_files(events: list[DomainEvent], files: dict[str, dict[str, Any]]) -> str:
    if not files:
        return "(no files)"
    revisions: dict[str, int] = {}
    for event in events:
        if isinstance(event, FILE_EVENTS):
            revisions[event.path] = revisions.get(event.path, 0) + 1
    lines = []
    for path in sorted(files):
        size = len(files[path].get("content", ""))
        lines.append(f"{path:<40} {size:>8}B  rev {revisions.get(path, 0)}")
    return "\n".join(lines)


def format_file_history(events: list[DomainEvent], path: str) -> str:
    rows = [
        f"#{i + 1:<4} {type(event).__name__}"
        for i, event in enumerate(events)
        if isinstance(event, FILE_EVENTS) and event.path == path
    ]
    return "\n".join(rows) if rows else f"(no history for {path})"


def format_state(session: CodingSession, event_count: int, context_mode: str = "full") -> str:
    state = session.state
    compacted = f"\ncontext  {context_mode}" + (
        f" ({state.compacted_through} message(s) behind a summary)"
        if state.compacted_through
        else ""
    )
    return (
        f"session  {state.session_id}\n"
        f"events   {event_count}\n"
        f"turns    {state.turn_index}"
        + (f" ({state.failed_turns} failed)" if state.failed_turns else "")
        + f"\nfiles    {len(state.files)}"
        + (
            f"\nforked   from {state.forked_from} at event {state.forked_at}"
            if state.forked_from
            else ""
        )
        + compacted
    )


def format_turn(outcome: TurnOutcome) -> str:
    """The agent's reply, with a pointer at what the turn wrote to the log.

    The footer is what makes `/log` navigable afterwards: it names the exact
    span to look at instead of leaving you to count backwards.
    """
    span = (
        f"#{outcome.from_index}"
        if outcome.from_index == outcome.to_index
        else f"#{outcome.from_index}-{outcome.to_index}"
    )
    footer = f"[turn {outcome.turn_index} · events {span}]"
    return f"{outcome.reply}\n{footer}" if outcome.reply else footer


def format_resumed(session: CodingSession) -> str:
    state = session.state
    return f"resumed {state.session_id} -- {state.turn_index} turns, {len(state.files)} files"


def format_autonomy(levels: dict[str, str]) -> str:
    """Every gated tool and how much rope it currently has."""
    return "\n".join(f"  {tool:<14} {level}" for tool, level in levels.items())


def format_summary_health(health: SummaryHealth) -> str:
    """Say plainly whether the session list can be trusted, and what to do.

    A health report that only prints numbers leaves the reader to work out
    whether they matter. The one number that does is `failed_events`, and its
    remedy is a single command, so the report names it.
    """
    if health.healthy:
        lag = " (catching up)" if health.behind else ""
        return f"session list  ok{lag}"
    if not health.following:
        return "session list  NOT FOLLOWING the log -- restart to resume"
    return (
        f"session list  DRIFTED: {health.failed_events} event(s) were never applied\n"
        f"              some rows are wrong; /rebuild to derive the list again"
    )
