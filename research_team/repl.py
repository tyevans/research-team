"""Terminal REPL. Formatting and dispatch only -- no domain logic."""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team import runtime as rt
from research_team.events import (
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    TurnFailed,
)
from research_team.runtime import AgentRuntime

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

HELP = """\
Workspace
  /files           files in the workspace, with revision counts
  /cat <path>      current contents of a file
  /history <path>  every event that touched a path
  /diff <path>     each recorded edit to a path, old -> new

Event log
  /log [n]         last n events (default 20)
  /state           session id, event count, turn count, file count

Time travel
  /rewind <n>      continue from a fork at event n
  /fork <n>        fork at event n and switch to it

Sessions (persisted to SQLite; they survive restarts)
  /sessions        list every stored session, newest first
  /resume <n|id>   switch to a stored session by list position or id
  /new             start a fresh session

  /help            this message
  /quit            exit

Anything else is sent to the agent as a turn."""


def _summary(event: DomainEvent) -> str:
    if isinstance(event, FILE_EVENTS):
        return event.path
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


def format_sessions(summaries: list[rt.SessionSummary], current: UUID) -> str:
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


async def _switch_to(runtime: AgentRuntime, session_id: UUID) -> str:
    """Point the runtime at an existing session, adopting its stored prompt."""
    aggregate = await runtime.repo.load(session_id)
    runtime.session_id = session_id
    runtime.system_prompt = aggregate.state.system_prompt or runtime.system_prompt
    return (
        f"resumed {session_id} -- "
        f"{aggregate.state.turn_index} turns, {len(aggregate.state.files)} files"
    )


async def _resolve_session(runtime: AgentRuntime, argument: str) -> UUID | str:
    """Accept a 1-based list position or an id prefix. Returns an error string."""
    summaries = await rt.list_sessions(runtime)
    if argument.isdigit():
        index = int(argument)
        if not 1 <= index <= len(summaries):
            return f"no session {index}: {len(summaries)} stored"
        return summaries[index - 1].session_id
    matches = [s for s in summaries if str(s.session_id).startswith(argument)]
    if not matches:
        return f"no session matching {argument!r}"
    if len(matches) > 1:
        return f"{argument!r} matches {len(matches)} sessions -- use more characters"
    return matches[0].session_id


async def handle_command(
    runtime: AgentRuntime,
    line: str,
    on_activity: Callable[[str], None] | None = None,
) -> str | None:
    line = line.strip()
    if not line:
        return ""
    if not line.startswith("/"):
        return await rt.run_turn(runtime, line, on_activity)

    command, _, argument = line.partition(" ")
    argument = argument.strip()

    if command == "/quit":
        return None
    if command == "/help":
        return HELP
    if command == "/sessions":
        return format_sessions(await rt.list_sessions(runtime), runtime.session_id)
    if command == "/resume":
        if not argument:
            return "usage: /resume <list-position|session-id>"
        resolved = await _resolve_session(runtime, argument)
        if isinstance(resolved, str):
            return resolved
        return await _switch_to(runtime, resolved)
    if command == "/new":
        fresh = await rt.start_session(runtime)
        return f"started {fresh}"
    if command == "/diff":
        if not argument:
            return "usage: /diff <path>"
        return format_diff(await rt.history(runtime), argument)
    if command == "/log":
        limit = int(argument) if argument.isdigit() else 20
        return format_log(await rt.history(runtime), limit)
    if command == "/files":
        aggregate = await runtime.repo.load(runtime.session_id)
        return format_files(await rt.history(runtime), aggregate.state.files)
    if command == "/cat":
        if not argument:
            return "usage: /cat <path>"
        aggregate = await runtime.repo.load(runtime.session_id)
        entry = aggregate.state.files.get(argument)
        return entry["content"] if entry else f"{argument}: not found"
    if command == "/history":
        if not argument:
            return "usage: /history <path>"
        return format_file_history(await rt.history(runtime), argument)
    if command in ("/rewind", "/fork"):
        if not argument.isdigit():
            return f"usage: {command} <event-number>"
        try:
            if command == "/rewind":
                await rt.rewind(runtime, int(argument))
                return f"rewound to event {argument}; session {runtime.session_id}"
            new_id = await rt.fork(runtime, int(argument))
            runtime.session_id = new_id
            return f"forked at event {argument}; session {new_id}"
        except ValueError as error:
            return str(error)
    if command == "/state":
        events = await rt.history(runtime)
        aggregate = await runtime.repo.load(runtime.session_id)
        return (
            f"session  {runtime.session_id}\n"
            f"events   {len(events)}\n"
            f"turns    {aggregate.state.turn_index}"
            + (
                f" ({aggregate.state.failed_turns} failed)"
                if aggregate.state.failed_turns
                else ""
            )
            + f"\nfiles    {len(aggregate.state.files)}"
            + (
                f"\nforked   from {aggregate.state.forked_from} "
                f"at event {aggregate.state.forked_at}"
                if aggregate.state.forked_from
                else ""
            )
        )
    return f"unknown command {command!r} -- try /help"


async def main() -> None:
    runtime = await rt.build_runtime()
    try:
        stored = await rt.list_sessions(runtime)
        print(f"session {runtime.session_id}")
        print(f"database {rt.default_db_path()}")
        if len(stored) > 1:
            print(f"{len(stored) - 1} earlier session(s) -- /sessions to list")
        print("/help for commands")

        while True:
            try:
                line = await asyncio.to_thread(input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return
            try:
                output = await handle_command(runtime, line, on_activity=print)
            except KeyboardInterrupt:
                # The turn is abandoned before its events are saved, so the
                # log keeps the last completed turn rather than a partial one.
                print("\n(interrupted -- turn discarded)")
                continue
            except Exception as error:  # noqa: BLE001 -- keep the REPL alive
                print(f"error: {type(error).__name__}: {error}")
                continue
            if output is None:
                return
            if output:
                print(output)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
