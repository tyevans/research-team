"""Terminal REPL: parsing, dispatch, and the input loop.

An adapter like any other -- it translates typed lines into use-case calls and
renders what comes back. No domain rules and no storage knowledge live here.

The REPL owns the notion of a *current* session, because that notion is its
own: one terminal, one person, one session at a time. The service underneath
serves any session it is asked about.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from eventsource import CommandRejectedError

from research_team.application import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalRequest,
    AutonomyPolicy,
    SessionService,
)
from research_team.domain import CreateProject
from research_team.infrastructure import config
from research_team.interfaces.cli.formatters import (
    format_autonomy,
    format_diff,
    format_file_history,
    format_files,
    format_log,
    format_resumed,
    format_sessions,
    format_state,
    format_summary_health,
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
  /health          whether the session list is derived from a healthy projection
  /rebuild         rebuild the session list from the log (safe at any time)

Time travel
  /rewind <n>      continue from a fork at event n
  /fork <n>        fork at event n and switch to it

Sessions (persisted to SQLite; they survive restarts)
  /sessions        list every stored session, newest first
  /resume <n|id>   switch to a stored session by list position or id
  /new             start a fresh session

Autonomy (how much the agent may do without asking)
  /autonomy              every gated tool and its level
  /autonomy <tool> <l>   set one to auto, ask, or deny

Projects (sessions that share a filesystem lineage and a knowledge graph)
  /project             list every project, with its id
  /project new <name>  create a project
  /project use <name>  start a session that inherits the project's files

  /help            this message
  /quit            exit

Anything else is sent to the agent as a turn."""


Prompter = Callable[[str], Awaitable[str]]
"""Asks the person a question and waits for the line they type."""


async def _ask_terminal(prompt: str) -> str:
    """Read one line without blocking the loop the turn is running on.

    A bare `input()` inside a coroutine stops everything -- including the
    turn that is waiting on this answer, and the keepalives and cancellation
    that surround it. The REPL's own loop reads the same way.
    """
    try:
        return await asyncio.to_thread(input, prompt)
    except (EOFError, KeyboardInterrupt):
        # Nobody is there, or they gave up. Either way the call is not
        # approved, and a hung turn would be the worse answer.
        return ""


DECISION_KEYS = {"a": "approve", "y": "approve", "r": "reject", "n": "reject", "e": "edit"}


@dataclass
class TerminalApprovals:
    """An `ApprovalPort` that asks whoever is at this terminal.

    Prints in the same register as the activity notes a turn already emits --
    a gated call is one more thing happening inside the turn, and giving it its
    own visual language would make the interruption read as a different program
    talking.
    """

    ask: Prompter = _ask_terminal
    show: Callable[[str], None] = print

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.show(f"· {request.tool_name} -- approval needed")
        for key, value in request.args.items():
            self.show(f"  ↳ {key}: {value}")
        while True:
            answer = (await self.ask("  [a]pprove  [r]eject  [e]dit > ")).strip().lower()
            choice = DECISION_KEYS.get(answer[:1]) if answer else "reject"
            if choice is None:
                self.show("  ↳ answer a, r, or e")
                continue
            if choice != "edit":
                return ApprovalDecision(choice)
            return ApprovalDecision("edit", edited_args=await self._amend(request.args))

    async def _amend(self, args: dict) -> dict:
        """Offer each argument for replacement; an empty line keeps it."""
        edited = dict(args)
        for key, value in args.items():
            replacement = (await self.ask(f"  {key} [{value}] > ")).strip()
            if replacement:
                edited[key] = replacement
        return edited


@dataclass
class Repl:
    """A service, plus which session this terminal is looking at."""

    service: SessionService
    session_id: UUID
    policy: AutonomyPolicy = field(default_factory=AutonomyPolicy)
    """The same object the executor consults, when one was wired. A REPL given
    its own is honest rather than broken: `/autonomy` still reports and sets,
    it simply governs nothing."""

    @classmethod
    async def start(
        cls, service: SessionService, policy: AutonomyPolicy | None = None
    ) -> "Repl":
        return cls(
            service,
            await service.create_session(),
            policy if policy is not None else AutonomyPolicy(),
        )


MIN_PREFIX = 4
"""Shorter than this is a list position, never an id prefix.

Both readings are possible for a short run of digits, and picking whichever
happens to match makes the command's behaviour depend on the random ids in the
database: `/resume 97` would usually report a bad position and occasionally
resume a session that happened to start with "97". Session ids are shown eight
characters wide, so a one- or two-character "prefix" was never one.
"""


async def _resolve_session(repl: Repl, argument: str) -> UUID | str:
    """Accept a 1-based list position or an id prefix. Returns an error string.

    A digit string is read as a position when it is a plausible one, and only
    then. Session ids are hex, so roughly one in forty starts with eight
    digits -- treating those as an out-of-range position made exactly those
    sessions impossible to resume by the prefix the UI prints.
    """
    summaries = await repl.service.list_sessions()
    looks_like_position = argument.isdigit() and len(argument) < MIN_PREFIX

    if argument.isdigit() and 1 <= int(argument) <= len(summaries):
        return summaries[int(argument) - 1].session_id
    if looks_like_position:
        return f"no session {argument}: {len(summaries)} stored"

    matches = [s for s in summaries if str(s.session_id).startswith(argument)]
    if len(matches) == 1:
        return matches[0].session_id
    if len(matches) > 1:
        return f"{argument!r} matches {len(matches)} sessions -- use more characters"
    if argument.isdigit():
        return f"no session {argument}: {len(summaries)} stored"
    return f"no session matching {argument!r}"


async def _handle_project(repl: "Repl", argument: str) -> str:
    """`/project` (list), `/project new <name>` (create), `/project use <name>`.

    Goes through `SessionService`'s own project accessors (`list_projects`,
    `projects`) rather than a private hop into its repository -- BACKLOG B8
    flagged that pattern for a proper accessor instead of a third case.
    """
    service = repl.service
    if not argument:
        projects = await service.list_projects()
        if not projects:
            return "no projects yet -- /project new <name> to create one"
        return "\n".join(f"{name}  {project_id}" for project_id, name in projects)

    sub, _, rest = argument.partition(" ")
    name = rest.strip()

    if sub == "new":
        if not name:
            return "usage: /project new <name>"
        existing = await service.list_projects()
        collision = next(
            (pid for pid, existing_name in existing if existing_name == name), None
        )
        if collision is not None:
            return f"project {name!r} already exists ({collision})"
        aggregate = service.projects.create_new(uuid4())
        aggregate.execute(CreateProject(name=name))
        await service.projects.save(aggregate)
        return f"created project {name} ({aggregate.aggregate_id})"

    if sub == "use":
        if not name:
            return "usage: /project use <name>"
        existing = await service.list_projects()
        match = next((pid for pid, existing_name in existing if existing_name == name), None)
        if match is None:
            return f"{name!r}: no such project"
        try:
            new_session_id = await service.start_in_project(match)
        except CommandRejectedError as error:
            # Worded verbatim: it names the session holding the project,
            # which is the next thing anyone asks.
            return str(error)
        repl.session_id = new_session_id
        return f"joined project {name}; session {repl.session_id}"

    return "usage: /project [new <name>|use <name>]"


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
        except (ValueError, CommandRejectedError) as error:
            return str(error)
        verb = "rewound to" if command == "/rewind" else "forked at"
        return f"{verb} event {argument}; session {repl.session_id}"
    if command == "/autonomy":
        if not argument:
            return format_autonomy(repl.policy.levels())
        parts = argument.split()
        if len(parts) != 2:
            return "usage: /autonomy [<tool> <auto|ask|deny>]"
        tool, level = parts
        try:
            repl.policy.set(tool, level)  # type: ignore[arg-type]
        except ValueError as error:
            # A typo is an ordinary thing to type at a prompt, and the policy
            # already words the complaint better than a generic traceback.
            return str(error)
        await service.record_autonomy_change(repl.session_id, tool, level)
        return f"{tool}: {level}"
    if command == "/health":
        return format_summary_health(await service.summaries_health())
    if command == "/rebuild":
        await service.rebuild_summaries()
        return "session list rebuilt from the log"
    if command == "/project":
        return await _handle_project(repl, argument)
    if command == "/state":
        events = await service.history(repl.session_id)
        return format_state(
            await service.load(repl.session_id),
            len(events),
            service.context_strategy,
        )
    return f"unknown command {command!r} -- try /help"


async def run(service: SessionService, policy: AutonomyPolicy | None = None) -> None:
    """Drive a session until the user leaves. The service is closed on the way out.

    The service is passed in rather than built here: choosing adapters is the
    composition root's job, and a REPL that builds its own would be one more
    place that knows which database and which model the app happens to use.
    """
    repl: Repl | None = None
    try:
        repl = await Repl.start(service, policy)
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
        # A no-op for a session that never joined a project. A session that
        # is never released holds the project forever -- nothing else takes
        # it back for a terminal that just closes.
        if repl is not None:
            await service.release_project(repl.session_id)
        await service.close()
