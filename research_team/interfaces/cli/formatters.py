"""Rendering of domain objects as terminal text. Pure functions, no I/O."""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.application import (
    RunReport,
    SessionSummary,
    SummaryHealth,
    TurnOutcome,
)
from research_team.application.check_telemetry_read import CheckStat
from research_team.application.ports import ActivityDelta, ActivityNote, ActivityRemark
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

ACTIVITY_RESULT_WIDTH = 70
"""Matches what the terminal has always shown for a tool result."""


def format_activity(note: ActivityNote) -> str | None:
    """One terminal line for a note, or None if it is not worth showing.

    Deliberately silent for prose and deltas: the transcript prints the reply
    when the turn completes, and echoing it token by token into a scrolling
    terminal would be noise. This is the terminal's presenter for the same
    notes the web UI renders as content.

    Payloads arrive from message_to_dict, with a nested structure: the actual
    message data lives under the 'data' key.
    """
    if isinstance(note, ActivityDelta):
        return None
    if isinstance(note, ActivityRemark):
        # The "· " that used to be applied by session_service before it handed
        # the line over. It belongs here: which glyph a line starts with is a
        # property of this terminal, and the web UI wants none of it.
        return f"· {note.text}"

    # Payloads from deep_agent have a nested structure with 'data' key
    # (from langchain's message_to_dict).
    data = note.payload["data"]

    calls = data.get("tool_calls") or []
    if calls:
        return "· " + ", ".join(
            f"{call.get('name', '?')}({_first_arg(call.get('args') or {})})" for call in calls
        )
    if note.kind == "tool":
        content = data.get("content", "")
        lines = str(content).strip().splitlines()
        return f"  ↳ {lines[0][:ACTIVITY_RESULT_WIDTH]}" if lines else None
    return None


def _first_arg(args: dict) -> str:
    """Extract the first significant argument from a call's args dict."""
    for key in ("file_path", "path", "pattern", "command"):
        if key in args:
            return str(args[key])
    return ""


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


def format_run_report(report: RunReport) -> str:
    """How an autonomous run ended, in the counts the log can back up.

    Leads with the reason rather than the work, because the reason is what
    decides whether the work is finished: `queue_empty` with nothing
    outstanding is the only ending that means done, and every other reason
    means the run stopped with work still in front of it. `finished_cleanly`
    is the report's own judgement of that, so this does not restate it.
    """
    verdict = "finished" if report.finished_cleanly else "stopped"
    parts = [
        f"{verdict}: {report.reason}",
        f"{report.rounds} round(s)",
        f"{report.findings} finding(s)",
    ]
    if report.unexamined_topics:
        parts.append(f"{report.unexamined_topics} topic(s) still want attention")
    return f"run {str(report.run_id)[:8]} -- " + ", ".join(parts)


def format_round(rounds: int, findings: int, topic: str | None) -> str:
    """One progress line, printed when a run's fold has moved on.

    In the same register as the activity notes a turn already prints: a round
    is a turn with a reason attached, and giving it its own visual language
    would make one program look like two.
    """
    working = f" -- on topic {topic[:8]}" if topic else ""
    return f"· round {rounds} ({findings} finding(s) so far){working}"


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


STANDING_GATE_MARK = "*"
"""Marks a check that cannot pass, so its 100% is not read as a defect."""

_CHECKS_HEADER = (
    f"{'check':<34} {'ran':>5} {'fired':>6} {'fire%':>6} "
    f"{'over':>5} {'refus':>6} {'auto':>5} {'med s':>7}"
)


def format_checks(stats: list[CheckStat]) -> str:
    """Per-check fire and override rates, most-firing first.

    Counts beside the percentage rather than the percentage alone: 1 of 1 and
    200 of 200 both render as 100%, and they warrant opposite conclusions about
    whether a check earns its place -- which is the only question this table is
    for.

    Two absences are printed as absences rather than as zeros, because a zero
    here would be a claim. `med s` is `-` on the tool path, where the review and
    the decision are committed together and the interval measures serialization
    (see the spec's honesty constraints). `fire%` is `-` for a check that has
    only ever been bound without being registered, which has no rate at all.

    Standing gates are marked rather than dropped: `ubd.uncoverage` and
    `addie.expert_gap_flag` are meant to fire every time, and hiding them would
    leave someone wondering why a bound check has no row.
    """
    if not stats:
        return "no checks have run in this project yet"
    lines = [_CHECKS_HEADER]
    for stat in stats:
        name = stat.check + (STANDING_GATE_MARK if stat.standing_gate else "")
        rate = f"{100 * stat.fired / stat.evaluated:.0f}%" if stat.evaluated else "-"
        median = (
            f"{stat.median_seconds_to_decision:.1f}"
            if stat.median_seconds_to_decision is not None
            else "-"
        )
        lines.append(
            f"{name:<34} {stat.evaluated:>5} {stat.fired:>6} {rate:>6} "
            f"{stat.overridden:>5} {stat.refused:>6} {stat.auto_approved:>5} {median:>7}"
        )
    unimplemented = [stat for stat in stats if stat.unimplemented]
    if unimplemented:
        # Named individually rather than counted: an unimplemented binding is a
        # typo or a rename, and the name is the whole of the fix.
        names = ", ".join(stat.check for stat in unimplemented)
        lines.append(f"bound but not registered: {names}")
    if any(stat.standing_gate for stat in stats):
        lines.append(f"{STANDING_GATE_MARK} always fires by design -- it is a standing gate")
    return "\n".join(lines)
