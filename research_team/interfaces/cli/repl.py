"""Terminal REPL: parsing, dispatch, and the input loop.

An adapter like any other -- it translates typed lines into use-case calls and
renders what comes back. No domain rules and no storage knowledge live here.

The REPL owns the notion of a *current* session, because that notion is its
own: one terminal, one person, one session at a time. The service underneath
serves any session it is asked about.
"""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from research_team.infrastructure import config
from research_team.interfaces.cli.formatters import (
    format_activity,
)
from research_team.interfaces.cli.repl_commands import (
    _WITHOUT_A_SESSION,
    HELP,
    MIN_PREFIX,
    NO_SESSION,
    RESEARCH_POLL_SECONDS,
    _handle_project,
    _handle_research,
    _resolve_session,
    _switch_to,
    handle_command,
)
from research_team.interfaces.cli.terminal_approvals import (
    DECISION_KEYS,
    Prompter,
    TerminalApprovals,
    _ask_terminal,
)
from research_team.platform.shared.ports import (
    ActivityNote,
)
from research_team.research.application.research_supervisor import (
    ResearchSupervisor,
)
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import SessionService

__all__ = [
    "DECISION_KEYS",
    "HELP",
    "MIN_PREFIX",
    "NO_SESSION",
    "RESEARCH_POLL_SECONDS",
    "_WITHOUT_A_SESSION",
    "Prompter",
    "Repl",
    "TerminalApprovals",
    "_ask_terminal",
    "_handle_project",
    "_handle_research",
    "_print_activity",
    "_resolve_session",
    "_switch_to",
    "handle_command",
    "run",
]


@dataclass
class Repl:
    """A service, plus which session this terminal is looking at."""

    service: SessionService
    session_id: UUID | None = None
    """The session this terminal is looking at, or None before one is chosen.

    None at startup, and that is the whole of the "sessions live in projects"
    rule as the terminal sees it. A session needs a project, choosing a project
    is a decision only the person at the keyboard can make, and inventing one
    on their behalf would put a session's whole history under a project nobody
    chose. So the REPL opens with no session and says what to type.

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
        chosen by a default is one nobody was asked about.
        """
        return cls(
            service,
            None,
            policy if policy is not None else AutonomyPolicy(),
            research,
        )


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
