"""Terminal interactive approval port and CLI prompter.

Prompts user for approval on tool execution within the terminal session loop.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from research_team.platform.shared.ports import (
    ApprovalDecision,
    ApprovalRequest,
)

__all__ = [
    "DECISION_KEYS",
    "Prompter",
    "TerminalApprovals",
    "_ask_terminal",
]

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
