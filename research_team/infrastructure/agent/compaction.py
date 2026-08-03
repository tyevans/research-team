"""The summarizing context strategy.

Lives in infrastructure because it is the one strategy that needs a model. The
decision it makes is recorded as a `ConversationCompacted` event, which is what
keeps it honest: the summary is written down once, replay reproduces the same
view, and folding to a point before it shows the conversation intact.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from research_team.application.context import Compaction, PreparedContext
from research_team.domain import SessionState

logger = logging.getLogger(__name__)

DEFAULT_TRIGGER_CHARS = 40_000
DEFAULT_KEEP_MESSAGES = 20

SUMMARY_PROMPT = (
    "You are compacting the transcript of a coding session so it can continue "
    "within a smaller context window.\n\n"
    "Write a summary that lets the agent carry on without re-reading what came "
    "before. Cover, in this order, and say 'none' where a section is empty:\n"
    "GOAL: what the user is ultimately trying to achieve.\n"
    "DONE: what has actually been accomplished, with file paths.\n"
    "DECISIONS: choices made and the reasoning, including options rejected.\n"
    "OPEN: what remains, and anything known to be broken or unverified.\n\n"
    "Be specific about paths and names. Do not invent progress that is not in "
    "the transcript. Reply with the summary alone."
)


class SummarizingStrategy:
    """Summarize the older part of the conversation once it grows too large.

    The summary replaces those messages *for the model only*; the log keeps
    them. A compaction is recorded as an event rather than recomputed each
    turn, so it costs one model call rather than one per turn, and two replays
    of the same log produce the same context.

    Note the tail is kept whole. A summary of the last few exchanges is where
    summarization does most of its damage -- recent detail is what the agent is
    actively using.
    """

    name = "compact"

    def __init__(
        self,
        model: BaseChatModel,
        *,
        trigger_chars: int = DEFAULT_TRIGGER_CHARS,
        keep_messages: int = DEFAULT_KEEP_MESSAGES,
    ) -> None:
        self._model = model
        self._trigger_chars = trigger_chars
        self._keep = keep_messages

    async def prepare(self, state: SessionState) -> PreparedContext:
        already = state.compacted_through
        live = state.messages[already:]
        if _size(live) < self._trigger_chars or len(live) <= self._keep:
            return PreparedContext(messages=self._view(state))

        # Everything except the tail becomes the new summary's territory.
        through = len(state.messages) - self._keep
        if through <= already:
            return PreparedContext(messages=self._view(state))

        summary = await self._summarize(
            state, previous=state.compaction_summary, upto=through
        )
        if not summary.strip():
            # An empty summary would be recorded forever and would stand in for
            # messages the model can then never see. A long context is a lesser
            # problem than a confident blank, so leave it uncompacted and try
            # again next turn.
            logger.warning(
                "summarizer returned nothing for %s; leaving the context uncompacted",
                state.session_id,
            )
            return PreparedContext(messages=self._view(state))

        compacted = state.model_copy(
            update={"compacted_through": through, "compaction_summary": summary}
        )
        return PreparedContext(
            messages=self._view(compacted),
            compaction=Compaction(summary=summary, through_index=through),
            notes=(
                f"compacted {through - already} message(s) into a summary; "
                "the log still holds them",
            ),
        )

    def _view(self, state: SessionState) -> list[dict]:
        """The message list as the model should see it, given any compaction."""
        if not state.compacted_through:
            return list(state.messages)
        preface = {
            "type": "human",
            "data": {
                "content": (
                    "Summary of the earlier part of this session, which has been "
                    f"compacted to save context:\n\n{state.compaction_summary}"
                )
            },
        }
        return [preface, *state.messages[state.compacted_through :]]

    async def _summarize(self, state: SessionState, *, previous: str, upto: int) -> str:
        """One model call over the messages being retired.

        Any earlier summary is included, so compaction is cumulative rather
        than forgetting whatever the last one had already condensed.
        """
        retiring = state.messages[state.compacted_through : upto]
        transcript = "\n\n".join(_render(message) for message in retiring)
        if previous:
            transcript = f"Summary so far:\n{previous}\n\nNew material:\n{transcript}"
        response = await self._model.ainvoke(
            [SystemMessage(SUMMARY_PROMPT), HumanMessage(transcript)]
        )
        return str(response.content).strip()


def _size(messages: list[dict]) -> int:
    return sum(len(str(m.get("data", {}).get("content", ""))) for m in messages)


def _render(message: dict) -> str:
    data = message.get("data", {})
    role = {"human": "user", "ai": "assistant", "tool": "tool"}.get(
        message.get("type", ""), message.get("type", "?")
    )
    calls = data.get("tool_calls") or []
    if calls:
        named = ", ".join(str(call.get("name")) for call in calls)
        return f"{role}: (called {named}) {str(data.get('content', ''))[:400]}"
    return f"{role}: {str(data.get('content', ''))[:1500]}"
