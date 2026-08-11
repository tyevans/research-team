"""Resetting the search bound at the turn boundary.

`SearchAttempts` lives for as long as the caller that built it keeps a
reference -- nothing about the counter itself knows when a turn ends. Without
this, a `DeepAgentTurnExecutor` that reused one `SearchAttempts` across turns
(the natural thing to do, since it also reuses the tool instance) would let a
run of empty searches near the end of one turn carry into the next and bound
a turn that has not actually tried anything yet. `StageMiddleware` resets per
turn by being rebuilt per turn; this counter is not, so the reset has to
happen explicitly.
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
        """Explicit for the same reason `StageMiddleware.name` is: `factory.py`
        raises when two middleware share a name, and the default is the class
        name."""
        return "search_attempts"

    def before_agent(self, state: Any) -> None:
        """Sync, unlike `StageMiddleware.awrap_model_call` -- this hook only
        clears a counter before the model is ever called, so there is no
        streamed response to be sync-only-implemented ahead of."""
        self._attempts.reset()
