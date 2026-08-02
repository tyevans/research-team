"""The `TurnExecutor` port, implemented with deepagents and langchain."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_openai import ChatOpenAI

from deepagents import create_deep_agent

from research_team.application import ActivityReporter, TurnResult
from research_team.domain import CodingSession
from research_team.infrastructure import config
from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.messages import (
    encode_user_message,
    last_text,
    new_messages,
    to_langchain,
    to_recorded,
)


def build_model() -> BaseChatModel:
    """The local OpenAI-compatible endpoint, fully env-overridable."""
    return ChatOpenAI(
        model=config.model_name(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        temperature=0,
    )


def describe_activity(message: BaseMessage) -> str | None:
    """A one-line progress note for a message, or None if it is not worth showing."""
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return "· " + ", ".join(
            f"{call['name']}({_first_arg(call.get('args', {}))})" for call in tool_calls
        )
    if isinstance(message, ToolMessage):
        first_line = str(message.content).strip().splitlines()
        return f"  ↳ {first_line[0][:70]}" if first_line else None
    return None


def _first_arg(args: dict[str, object]) -> str:
    for key in ("file_path", "path", "pattern", "command"):
        if key in args:
            return str(args[key])
    return ""


class DeepAgentTurnExecutor:
    """Runs one turn through a deepagents agent bound to the aggregate.

    The agent's filesystem is the aggregate: `EventSourcedBackend` turns every
    file tool call into a domain event as it happens. Conversation messages are
    handed back instead, so the caller keeps control of whether the turn is
    committed at all.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model_name", type(self._model).__name__)

    def encode_user_message(self, text: str) -> dict:
        return encode_user_message(text)

    async def execute(
        self,
        session: CodingSession,
        *,
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult:
        sent = to_langchain(session.state)
        after = await self._invoke(session, sent, system_prompt, on_activity)
        return TurnResult(
            messages=tuple(
                to_recorded(message) for message in new_messages(len(sent), after)
            ),
            reply_text=last_text(after),
        )

    async def _invoke(
        self,
        session: CodingSession,
        messages: list[BaseMessage],
        system_prompt: str,
        on_activity: ActivityReporter | None,
    ) -> list[BaseMessage]:
        """Run one agent pass, reporting tool activity as it happens.

        Streams with `stream_mode="values"`, where each chunk is the full
        state. That yields live progress and the final message list from a
        single pass -- a local model can take a minute per turn, and silence
        for that long is indistinguishable from a hang.

        Kept as a separate seam so tests can force a mid-turn failure.
        """
        agent = create_deep_agent(
            model=self._model,
            backend=EventSourcedBackend(session),
            system_prompt=system_prompt,
            checkpointer=None,
        )

        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        async for state in agent.astream({"messages": messages}, stream_mode="values"):
            final = state["messages"]
            if on_activity is not None:
                for message in final[reported:]:
                    note = describe_activity(message)
                    if note:
                        on_activity(note)
            reported = len(final)
        return final
