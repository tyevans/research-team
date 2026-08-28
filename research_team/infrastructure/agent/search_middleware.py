"""Resetting the search bound at the turn boundary.

`SearchAttempts` lives for as long as the caller that built it keeps a
reference -- nothing about the counter itself knows when a turn ends. Without
this, a `DeepAgentTurnExecutor` that reused one `SearchAttempts` across turns
(the natural thing to do, since it also reuses the tool instance) would let a
run of empty searches near the end of one turn carry into the next and bound
a turn that has not actually tried anything yet. A middleware built per turn
resets by construction; the `SearchAttempts` instance is not, so the turn's
counter has to be installed explicitly -- and installing it here is also
what scopes it to the turn at all, since `SearchAttempts` keeps the count in a
context variable this hook is the only writer of.
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware

from research_team.infrastructure.agent.search import SearchAttempts


class SearchAttemptsMiddleware(AgentMiddleware):
    """Clears one turn's empty-search streak before the turn starts."""

    def __init__(self, attempts: SearchAttempts) -> None:
        super().__init__()
        self._attempts = attempts

    @property
    def name(self) -> str:
        """Explicit rather than defaulted: `factory.py` raises when two
        middleware share a name, and the default is the class name."""
        return "search_attempts"

    def before_agent(self, state: Any) -> None:
        """Sync, unlike the `awrap_*` hooks -- this one only installs a
        counter before the model is ever called, so there is no streamed
        response to be sync-only-implemented ahead of.

        `begin_turn` rather than `reset`: reset clears the counter this context
        can already see, which under concurrency is another live turn's. This
        hook is also what puts the turn's counter in the context at all, so the
        tool's mutations are visible here and to nothing else.
        """
        self._attempts.begin_turn()
