"""Terminal REPL. Formatting and dispatch only -- no domain logic."""

import asyncio
from typing import Any

from eventsource import DomainEvent

from research_team import runtime as rt
from research_team.events import FileDeleted, FileEdited, FileWritten
from research_team.runtime import AgentRuntime

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

HELP = """\
Commands:
  /log [n]         last n events (default 20)
  /files           files in the workspace, with revision counts
  /cat <path>      current contents of a file
  /history <path>  every event that touched a path
  /rewind <n>      continue from a fork at event n
  /fork <n>        fork at event n and switch to it
  /state           session id, event count, turn count, file count
  /help            this message
  /quit            exit

Anything else is sent to the agent as a turn."""


def _summary(event: DomainEvent) -> str:
    if isinstance(event, FILE_EVENTS):
        return event.path
    if hasattr(event, "turn_index"):
        return f"turn {event.turn_index}"
    if hasattr(event, "message"):
        return str(event.message.get("data", {}).get("content", ""))[:60]
    return ""


def format_log(events: list[DomainEvent], limit: int) -> str:
    if not events:
        return "(no events)"
    selected = events[-limit:]
    offset = len(events) - len(selected)
    return "\n".join(
        f"#{offset + i + 1:<4} {type(event).__name__:<24} {_summary(event)}"
        for i, event in enumerate(selected)
    )


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


async def handle_command(runtime: AgentRuntime, line: str) -> str | None:
    line = line.strip()
    if not line:
        return ""
    if not line.startswith("/"):
        return await rt.run_turn(runtime, line)

    command, _, argument = line.partition(" ")
    argument = argument.strip()

    if command == "/quit":
        return None
    if command == "/help":
        return HELP
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
            f"turns    {aggregate.state.turn_index}\n"
            f"files    {len(aggregate.state.files)}"
        )
    return f"unknown command {command!r} -- try /help"


async def main() -> None:
    runtime = await rt.build_runtime()
    print(f"session {runtime.session_id} -- /help for commands")
    while True:
        try:
            line = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            output = await handle_command(runtime, line)
        except Exception as error:  # noqa: BLE001 -- keep the REPL alive
            print(f"error: {type(error).__name__}: {error}")
            continue
        if output is None:
            return
        if output:
            print(output)


if __name__ == "__main__":
    asyncio.run(main())
