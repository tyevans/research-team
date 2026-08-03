"""Deciding what the model is shown.

A session's message list only grows, and every turn re-sends it. Left alone
that ends a long session at the context window. The interesting question is
*where* to intervene, and event sourcing answers it: not inside the agent.

Measured against this codebase, a middleware that rewrites the running message
list -- langchain's `SummarizationMiddleware` does, via
`RemoveMessage(REMOVE_ALL_MESSAGES)` -- silently breaks how a turn is recorded.
We identify what a turn produced by slicing the agent's returned list at the
length we sent; rewritten history makes that slice meaningless, and the turn
lands in the log missing its assistant messages and tool results. The log
becomes a confident lie, which is worse than a crash.

So the intervention happens at the *fold*. The log always holds every message;
a strategy decides which of them, and in what form, are handed to the model for
the next turn. Turn accounting is untouched, because we still know exactly what
we sent. Time travel is untouched, because nothing is removed.

(Middleware that only rewraps the outbound request -- langchain's
`ContextEditingMiddleware` hooks `wrap_model_call` and leaves state alone -- is
safe by the same reasoning, and is what `elide` is modelled on.)
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from research_team.domain import SessionState


@dataclass(frozen=True)
class Compaction:
    """A summary a strategy wants recorded, standing in for a run of messages."""

    summary: str
    through_index: int
    """1-based index of the last message the summary stands in for."""


@dataclass(frozen=True)
class PreparedContext:
    """What to send the model this turn, and anything to record first."""

    messages: list[dict[str, Any]]
    compaction: Compaction | None = None
    """Recorded as an event before the turn, so replay reproduces this view."""
    notes: tuple[str, ...] = field(default_factory=tuple)
    """Human-readable account of what was left out, for the REPL and the UI."""


class ContextStrategy(Protocol):
    """Chooses what the model sees, given everything the session remembers."""

    name: str

    async def prepare(self, state: SessionState) -> PreparedContext: ...


# ---------------------------------------------------------------- full


class FullHistory:
    """Send everything. The default, and the right answer until it isn't.

    Cheapest and most faithful: the model sees exactly what happened. It is
    also the only strategy that cannot lose a detail the agent needed, which is
    why it stays the default rather than being retired.
    """

    name = "full"

    async def prepare(self, state: SessionState) -> PreparedContext:
        return PreparedContext(messages=list(state.messages))


# ---------------------------------------------------------------- elide


DEFAULT_KEEP_RESULTS = 6
DEFAULT_MAX_RESULT_CHARS = 2000


class ElideToolResults:
    """Replace older tool results with a placeholder, keeping recent ones whole.

    Tool results dominate a coding session's context: a file read costs
    thousands of characters and is then replayed on every later turn forever.
    They are also the safest thing to drop *here specifically*, because the
    workspace is a virtual filesystem the agent still has -- if it needs the
    contents again it can read the file again, and that read is itself an
    auditable event.

    Pure, deterministic, and needs no model call, so it costs nothing and never
    surprises you. It cannot help with a conversation that is long in prose
    rather than in tool output; reach for `compact` then.
    """

    name = "elide"

    def __init__(
        self,
        *,
        keep_results: int = DEFAULT_KEEP_RESULTS,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        self._keep = keep_results
        self._max_chars = max_result_chars

    async def prepare(self, state: SessionState) -> PreparedContext:
        messages = list(state.messages)
        tool_positions = [
            index
            for index, message in enumerate(messages)
            if message.get("type") == "tool"
        ]
        stale = set(tool_positions[: max(0, len(tool_positions) - self._keep)])
        if not stale:
            return PreparedContext(messages=messages)

        elided = 0
        prepared: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if index in stale:
                shortened = _placeholder(message, self._max_chars)
                # A short result is left alone: shrinking it saves nothing and
                # a note claiming otherwise would be false.
                elided += shortened is not message
                message = shortened
            prepared.append(message)

        if not elided:
            return PreparedContext(messages=prepared)
        return PreparedContext(
            messages=prepared,
            notes=(
                f"shortened {elided} older tool result(s); "
                "the files are still readable",
            ),
        )


def _placeholder(message: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Shrink one tool result, keeping enough to know what it was.

    The head of the result is kept rather than dropping it whole: "which file
    was this" is usually the part the model needs, and it is usually first.
    """
    data = dict(message.get("data", {}))
    content = str(data.get("content", ""))
    if len(content) <= max_chars:
        return message
    kept = content[:max_chars]
    data["content"] = (
        f"{kept}\n\n[{len(content) - max_chars} more characters elided to save "
        "context; read the file again if you need them]"
    )
    return {**message, "data": data}
