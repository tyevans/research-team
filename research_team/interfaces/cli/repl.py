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
    ResearchSupervisor,
    RunAlreadyActive,
    SessionService,
)
from research_team.application.ports import ActivityNote
from research_team.domain import CreateProject
from research_team.domain.auto_research import Budget
from research_team.infrastructure import config
from research_team.interfaces.cli.formatters import (
    format_activity,
    format_autonomy,
    format_diff,
    format_file_history,
    format_files,
    format_log,
    format_resumed,
    format_round,
    format_run_report,
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

  Every session belongs to a project -- see Projects below to start one.

Autonomy (how much the agent may do without asking)
  /autonomy              every gated tool and its level
  /autonomy <tool> <l>   set one to auto, ask, or deny

Projects (sessions that share a filesystem lineage and a knowledge graph)
  /project             list every project, with its id
  /project new <name>  create a project
  /project use <name>  start a session that inherits the project's files

Autonomous research (works this project's topic queue, one topic per turn)
  /research            run until the queue empties or the budget stops it
  /research <n>        the same, capped at n rounds

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
    session_id: UUID | None = None
    """The session this terminal is looking at, or None before one is chosen.

    None at startup, and that is the whole of the "sessions live in projects"
    rule as the terminal sees it. A session needs a project, choosing a project
    is a decision only the person at the keyboard can make -- the workflow it
    runs is permanent -- and inventing one on their behalf would make that
    choice silently, once, forever. So the REPL opens with no session and says
    what to type.

    Every command that needs a session guards on this rather than the type
    system, which is the cost of the choice: `UUID | None` propagates into
    `_switch_to`, `release_project` and every handler that reads it. The
    alternative -- a separate "no session yet" REPL type -- buys the guarantee
    at the price of duplicating the dispatch table, which is worse.
    """
    policy: AutonomyPolicy = field(default_factory=AutonomyPolicy)
    """The same object the executor consults, when one was wired. A REPL given
    its own is honest rather than broken: `/autonomy` still reports and sets,
    it simply governs nothing."""

    research: ResearchSupervisor | None = None
    """The supervisor autonomous runs go through, when one was wired.

    Optional for the reason `policy` has a default: a REPL built over a bare
    `SessionService` in a test has no composition root behind it, and
    `/research` says so rather than the constructor demanding something most
    callers do not have."""

    @classmethod
    async def start(
        cls,
        service: SessionService,
        policy: AutonomyPolicy | None = None,
        research: ResearchSupervisor | None = None,
    ) -> "Repl":
        """A REPL with no session. `/project new` or `/project use` starts one.

        It used to create one here. It cannot now: a session belongs to a
        project, and this classmethod has no way to ask which -- it is called
        before the input loop exists, from `run` and from tests, and a project
        chosen without being asked for is a permanent workflow choice made by
        a default.
        """
        return cls(
            service,
            None,
            policy if policy is not None else AutonomyPolicy(),
            research,
        )


NO_SESSION = (
    "no session yet -- a session belongs to a project.\n"
    "  /project              list projects\n"
    "  /project new <name>   create one (then /project use it)\n"
    "  /project use <name>   start a session in an existing project"
)
"""What every session-needing command says before a project has been chosen.

Names all three commands rather than only the one that would have worked,
because which one is right depends on whether the project exists, and the
person who has just been refused does not necessarily know.
"""

_WITHOUT_A_SESSION = frozenset(
    {"/quit", "/help", "/project", "/sessions", "/resume", "/health", "/rebuild"}
)
"""Commands that work before a session exists.

`/sessions` and `/resume` are here because they are how you get back to work
already done, and `/health` and `/rebuild` because they are about the database
rather than about a session. Everything else needs one.
"""

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
        aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name=name))
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
        warning = await _switch_to(repl, new_session_id)
        joined = f"joined project {name}; session {repl.session_id}"
        return f"{joined}\n{warning}" if warning else joined

    return "usage: /project [new <name>|use <name>]"


RESEARCH_POLL_SECONDS = 1.0
"""How often `/research` refolds the run to see whether a round has landed.

Polling rather than a subscription because the alternative is a second channel
carrying what the log already has -- the same argument the web feed makes for
reading the store rather than the bus. A round is a whole turn, so a second is
already far finer than the thing being watched.
"""


async def _handle_research(repl: "Repl", argument: str) -> str:
    """`/research [rounds]`: work this session's project queue until it stops.

    Refuses outside a project, because there is no queue to work: topics
    belong to a project, and a session without one has no tools to record
    findings with either.

    Runs through the supervisor rather than awaiting the driver directly, so
    that Ctrl-C can ask the run to stop between rounds instead of abandoning
    it mid-turn -- and so the terminal can print each round as it lands rather
    than going quiet for however long the whole run takes.
    """
    if repl.research is None:
        return "autonomous runs are not wired into this REPL"
    session = await repl.service.load(repl.session_id)
    project_id = session.state.project_id
    if project_id is None:
        return "no project -- /project use <name> first; topics belong to a project"
    budget = None
    if argument:
        if not argument.isdigit() or int(argument) < 1:
            return "usage: /research [max-rounds]"
        rounds = int(argument)
        budget = Budget(max_rounds=rounds, max_turns=rounds * 2)

    try:
        run = repl.research.start(project_id, repl.session_id, budget=budget)
    except RunAlreadyActive as error:
        return str(error)
    print(f"run {str(run.run_id)[:8]} started on project {project_id}")
    print("(ctrl-c asks it to stop after the round it is in)")

    # One waiter for the whole loop rather than one per poll: awaiting the run
    # again each second would leave a wrapper future behind on every tick, and
    # a failure would then be raised into each of them.
    waiter = asyncio.ensure_future(repl.research.wait(project_id))
    seen = -1
    try:
        while True:
            done, _ = await asyncio.wait({waiter}, timeout=RESEARCH_POLL_SECONDS)
            state = await repl.research.state(run.run_id)
            if state is not None and state.rounds != seen:
                seen = state.rounds
                if state.rounds:
                    topic = str(state.in_flight_topic) if state.in_flight_topic else None
                    print(format_round(state.rounds, state.findings, topic))
            if done:
                report = waiter.result()
                break
    except KeyboardInterrupt:
        # Asked, not killed: the round in flight finishes and records its
        # stop, which is what makes `cancelled` a reason in the log rather
        # than a run that simply goes quiet.
        repl.research.cancel(project_id)
        print("\n(stopping after this round)")
        report = await waiter
    if report is None:
        return "the run ended without reporting"
    return format_run_report(report)


async def _switch_to(repl: "Repl", new_session_id: UUID) -> str | None:
    """Move the REPL's cursor, releasing any project the outgoing session held.

    Every path that reassigns `repl.session_id` -- `/resume`, `/new`,
    `/rewind`/`/fork`, `/project use` -- goes through this rather than
    assigning directly. Without it, a session that held a project keeps
    "holding" it (per `Project.state.active_session_id`) even after nobody is
    driving it anymore: `release_project` was previously only called at
    REPL exit, so switching sessions leaked the project it held with no
    command able to get it back. `release_project` is a no-op for a session
    that held nothing, so this is safe to call on every switch.

    Detaching the knowledge graph belongs here for the same reason: whatever
    is attached belongs to the session being left, not the one about to
    start. `detach_project` is a no-op when nothing is attached, so this is
    safe on every switch.

    The incoming session's own `project_id` -- not whether it holds the
    project's filesystem lease -- decides whether to attach a graph.
    `/resume` can land on an old session that belongs to a project without
    that session being the project's current holder; its recorded
    `SessionStarted` prompt still describes `remember`/`graph_search`/
    `unmerge`, so the executor must have them regardless of who holds the
    lease. That is why this calls `attach_project`, never `JoinProject` --
    attaching the graph and taking the lease are different things, and
    issuing `JoinProject` here would reacquire a lease `/resume` has no
    business taking, reopening the leak Task 12 closed. `/project use`
    reaches this too, through the session `start_in_project` already gave a
    `project_id`, so it needs no separate attach call of its own.

    Returns a warning to show the user if attaching failed -- the switch and
    the detach above still happened, so the session is never left unusable
    over a graph that would not open, only without knowledge tools.
    """
    # Guarded, because the REPL now starts with no session and the first
    # `/project use` switches *from* that state -- there is no outgoing
    # session to release, and `release_project(None)` raises inside
    # `StreamId` rather than no-opping. This is the propagation `Repl.
    # session_id` warns about, at the one site that meets it first.
    if repl.session_id is not None:
        await repl.service.release_project(repl.session_id)
    await repl.service.detach_project()
    repl.session_id = new_session_id
    session = await repl.service.load(new_session_id)
    if session.state.project_id is None:
        return None
    try:
        await repl.service.attach_project(session.state.project_id)
    except Exception as error:  # noqa: BLE001 -- report, do not take the REPL down
        return f"knowledge graph unavailable: {error}"
    return None


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
        if repl.session_id is None:
            return NO_SESSION
        outcome = await service.run_turn(repl.session_id, line, on_activity)
        return format_turn(outcome)

    command, _, argument = line.partition(" ")
    argument = argument.strip()

    # Before dispatch rather than inside each handler: most commands read
    # `repl.session_id`, and one guard that lists its exceptions is easier to
    # keep true than fifteen that each have to remember. The exceptions are
    # the commands whose whole job is to get you a session, plus the ones
    # about the database rather than about a session.
    if repl.session_id is None and command not in _WITHOUT_A_SESSION:
        return NO_SESSION

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
        warning = await _switch_to(repl, resolved)
        resumed = format_resumed(session)
        return f"{resumed}\n{warning}" if warning else resumed
    if command == "/new":
        # Kept as a command purely to answer for itself. It started a
        # project-less session, which no longer exists as a thing; removing it
        # outright would answer `unknown command '/new'`, which is true and
        # unhelpful to the one person who has the old habit.
        return (
            "/new is gone -- a session belongs to a project.\n"
            "  /project new <name>, or /project use <name>"
        )
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
            forked_id = await service.fork(repl.session_id, int(argument))
        except (ValueError, CommandRejectedError) as error:
            return str(error)
        warning = await _switch_to(repl, forked_id)
        verb = "rewound to" if command == "/rewind" else "forked at"
        forked = f"{verb} event {argument}; session {repl.session_id}"
        return f"{forked}\n{warning}" if warning else forked
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
    if command == "/research":
        return await _handle_research(repl, argument)
    if command == "/state":
        events = await service.history(repl.session_id)
        return format_state(
            await service.load(repl.session_id),
            len(events),
            service.context_strategy,
        )
    return f"unknown command {command!r} -- try /help"


def _print_activity(note: ActivityNote) -> None:
    """Format and print a note, or stay silent if there is nothing to show."""
    line = format_activity(note)
    if line is not None:
        print(line)


async def run(
    service: SessionService,
    policy: AutonomyPolicy | None = None,
    research: ResearchSupervisor | None = None,
) -> None:
    """Drive a session until the user leaves. The service is closed on the way out.

    The service is passed in rather than built here: choosing adapters is the
    composition root's job, and a REPL that builds its own would be one more
    place that knows which database and which model the app happens to use.
    """
    repl: Repl | None = None
    try:
        repl = await Repl.start(service, policy, research)
        stored = await service.list_sessions()
        print(f"database {config.default_db_path()}")
        if stored:
            print(f"{len(stored)} stored session(s) -- /sessions to list")
        # The count is now every stored session rather than every one but this
        # terminal's own, because this terminal no longer has one to exclude.
        print(NO_SESSION)
        print("/help for commands")

        while True:
            try:
                line = await asyncio.to_thread(input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return
            try:
                output = await handle_command(repl, line, on_activity=_print_activity)
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
        # A session that is never released holds the project forever --
        # nothing else takes it back for a terminal that just closes. The
        # `session_id` guard is new and is not the same as the old "never
        # joined a project" no-op: a terminal that was opened and closed
        # without choosing a project now has nothing to release at all.
        if repl is not None and repl.session_id is not None:
            await service.release_project(repl.session_id)
        await service.close()
