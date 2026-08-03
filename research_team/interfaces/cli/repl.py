"""Terminal REPL: parsing, dispatch, and the input loop.

An adapter like any other -- it translates typed lines into use-case calls and
renders what comes back. No domain rules and no storage knowledge live here.

The REPL owns the notion of a *current* session, because that notion is its
own: one terminal, one person, one session at a time. The service underneath
serves any session it is asked about.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from research_team.application import ActivityReporter, SessionService
from research_team.infrastructure import config
from research_team.interfaces.cli.formatters import (
    format_diff,
    format_file_history,
    format_files,
    format_log,
    format_resumed,
    format_sessions,
    format_state,
    format_turn,
)

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


@dataclass
class Repl:
    """A service, plus which session this terminal is looking at."""

    service: SessionService
    session_id: UUID

    @classmethod
    async def start(cls, service: SessionService) -> "Repl":
        return cls(service, await service.create_session())


async def _resolve_session(repl: Repl, argument: str) -> UUID | str:
    """Accept a 1-based list position or an id prefix. Returns an error string.

    A digit string is only read as a position when it *is* one. Session ids are
    hex, so roughly one in forty starts with eight digits -- and treating those
    as an out-of-range list position made exactly those sessions impossible to
    resume by prefix.
    """
    summaries = await repl.service.list_sessions()
    if argument.isdigit() and 1 <= int(argument) <= len(summaries):
        return summaries[int(argument) - 1].session_id

    matches = [s for s in summaries if str(s.session_id).startswith(argument)]
    if len(matches) == 1:
        return matches[0].session_id
    if len(matches) > 1:
        return f"{argument!r} matches {len(matches)} sessions -- use more characters"
    if argument.isdigit():
        # Nothing matched it as a prefix either, so it was meant as a position.
        return f"no session {argument}: {len(summaries)} stored"
    return f"no session matching {argument!r}"


async def handle_command(
    repl: Repl,
    line: str,
    on_activity: ActivityReporter | None = None,
) -> str | None:
    """Run one input line. Returns text to print, or None to exit the REPL."""
    service = repl.service
    line = line.strip()
    if not line:
        return ""
    if not line.startswith("/"):
        outcome = await service.run_turn(repl.session_id, line, on_activity)
        return format_turn(outcome)

    command, _, argument = line.partition(" ")
    argument = argument.strip()

    if command == "/quit":
        return None
    if command == "/help":
        return HELP
    if command == "/sessions":
        return format_sessions(await service.list_sessions(), repl.session_id)
    if command == "/resume":
        if not argument:
            return "usage: /resume <list-position|session-id>"
        resolved = await _resolve_session(repl, argument)
        if isinstance(resolved, str):
            return resolved
        session = await service.load(resolved)
        repl.session_id = resolved
        return format_resumed(session)
    if command == "/new":
        repl.session_id = await service.create_session()
        return f"started {repl.session_id}"
    if command == "/diff":
        if not argument:
            return "usage: /diff <path>"
        return format_diff(await service.history(repl.session_id), argument)
    if command == "/log":
        limit = int(argument) if argument.isdigit() else 20
        return format_log(await service.history(repl.session_id), limit)
    if command == "/files":
        session = await service.load(repl.session_id)
        return format_files(await service.history(repl.session_id), session.state.files)
    if command == "/cat":
        if not argument:
            return "usage: /cat <path>"
        session = await service.load(repl.session_id)
        entry = session.state.files.get(argument)
        return entry["content"] if entry else f"{argument}: not found"
    if command == "/history":
        if not argument:
            return "usage: /history <path>"
        return format_file_history(await service.history(repl.session_id), argument)
    if command in ("/rewind", "/fork"):
        if not argument.isdigit():
            return f"usage: {command} <event-number>"
        try:
            repl.session_id = await service.fork(repl.session_id, int(argument))
        except ValueError as error:
            return str(error)
        verb = "rewound to" if command == "/rewind" else "forked at"
        return f"{verb} event {argument}; session {repl.session_id}"
    if command == "/state":
        events = await service.history(repl.session_id)
        return format_state(
            await service.load(repl.session_id),
            len(events),
            service.context_strategy,
        )
    return f"unknown command {command!r} -- try /help"


async def run(service: SessionService) -> None:
    """Drive a session until the user leaves. The service is closed on the way out.

    The service is passed in rather than built here: choosing adapters is the
    composition root's job, and a REPL that builds its own would be one more
    place that knows which database and which model the app happens to use.
    """
    try:
        repl = await Repl.start(service)
        stored = await service.list_sessions()
        print(f"session {repl.session_id}")
        print(f"database {config.default_db_path()}")
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
                output = await handle_command(repl, line, on_activity=print)
            except KeyboardInterrupt:
                # The turn's own events are discarded whole -- the log keeps
                # the last completed turn rather than a partial one -- but the
                # attempt still earns a TurnFailed marker, so an interrupted
                # turn is visible in `/log` rather than silently absent.
                print("\n(interrupted -- turn discarded, attempt recorded)")
                continue
            except Exception as error:  # noqa: BLE001 -- keep the REPL alive
                print(f"error: {type(error).__name__}: {error}")
                continue
            if output is None:
                return
            if output:
                print(output)
    finally:
        await service.close()
