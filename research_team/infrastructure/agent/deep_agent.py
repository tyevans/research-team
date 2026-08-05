"""The `TurnExecutor` port, implemented with deepagents and langchain."""

from collections.abc import Sequence
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from research_team.application import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRequest,
    AutonomyPolicy,
    TurnResult,
)
from research_team.domain import CodingSession, RecordToolDecision
from research_team.infrastructure import config
from research_team.infrastructure.agent.approval import interrupt_config
from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.messages import (
    encode_user_message,
    last_text,
    new_messages,
    to_payload_messages,
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

    def __init__(
        self,
        model: BaseChatModel,
        *,
        subagents: Sequence[dict] = (),
        tools: Sequence[BaseTool] = (),
        policy: AutonomyPolicy | None = None,
        approvals: ApprovalPort | None = None,
    ) -> None:
        self._model = model
        self._subagents = list(subagents)
        self._tools = list(tools)
        # An all-`auto` policy is the default so that wiring a supervisor is
        # opt-in: without one, nothing is gated and the executor behaves
        # exactly as it did before interrupts existed.
        self._policy = policy if policy is not None else AutonomyPolicy()
        self._approvals = approvals

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model_name", type(self._model).__name__)

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        """What this executor will hand the agent on its next turn."""
        return tuple(self._tools)

    def set_tools(self, tools: Sequence[BaseTool]) -> None:
        """Replace the tool set for subsequent turns.

        Safe between turns because `_invoke` builds the agent from `_tools` on
        every pass -- there is no long-lived agent holding a stale list. Not
        safe *during* a turn, and nothing calls it there: attaching a project
        happens from the REPL's command loop, which is not inside a turn.
        """
        self._tools = list(tools)

    def encode_user_message(self, text: str) -> dict:
        return encode_user_message(text)

    async def execute(
        self,
        session: CodingSession,
        *,
        messages: list[dict],
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult:
        sent = to_payload_messages(messages)
        after = await self._invoke(session, sent, system_prompt, on_activity)
        return TurnResult(
            messages=tuple(to_recorded(message) for message in new_messages(len(sent), after)),
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

        A gated tool call halts the graph instead of running, so one turn can
        take several passes: stream, settle whatever was interrupted, resume,
        stream again. `reported` deliberately survives the loop -- it counts
        messages already announced, and restarting it each pass would replay
        the whole turn's activity to the caller on every resume.

        Kept as a separate seam so tests can force a mid-turn failure.
        """
        agent = create_deep_agent(
            model=self._model,
            tools=self._tools or None,
            backend=EventSourcedBackend(session),
            system_prompt=system_prompt,
            interrupt_on=interrupt_config(self._policy),
            # Resuming is impossible without one: `Command(resume=...)` needs
            # somewhere to have parked the halted graph. Per turn and in
            # memory, because nothing here outlives the turn -- the durable
            # record of what happened is the event log, not this.
            checkpointer=MemorySaver(),
            # Subagents share this backend, so their file writes land in the
            # same event log as everything else -- delegated work stays as
            # auditable as work the main agent does itself.
            subagents=self._subagents or None,
        )
        run_config = {
            "configurable": {"thread_id": f"{session.aggregate_id}:{session.state.turn_index}"}
        }

        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        payload: Any = {"messages": messages}
        while True:
            state: dict[str, Any] = {}
            async for state in agent.astream(payload, config=run_config, stream_mode="values"):
                final = state.get("messages", final)
                if on_activity is not None:
                    for message in final[reported:]:
                        note = describe_activity(message)
                        if note:
                            on_activity(note)
                reported = len(final)
            interrupts = state.get("__interrupt__")
            if not interrupts:
                return final
            decisions = await self._settle(session, interrupts)
            payload = Command(resume={"decisions": decisions})

    async def _settle(self, session: CodingSession, interrupts: Sequence[Any]) -> list[dict]:
        """One decision per interrupted call, in the order they were requested.

        The order and the count are both load-bearing: langchain pairs the
        decisions with `action_requests` positionally and raises if the lengths
        disagree, so this walks the requests rather than the tools it expected.
        """
        decisions: list[dict] = []
        for interrupt in interrupts:
            value = getattr(interrupt, "value", interrupt)
            requests = value["action_requests"]
            reviews = value.get("review_configs") or [{}] * len(requests)
            for request, review in zip(requests, reviews, strict=False):
                decisions.append(await self._decide(session, request, review))
        return decisions

    async def _decide(self, session: CodingSession, request: dict, review: dict) -> dict:
        """Settle one interrupted call, recording the decision either way.

        `deny` is refused here without the human ever seeing it -- that is the
        whole difference between it and `ask`, and the reason the `when`
        predicate can get away with returning a bool.
        """
        name = request["name"]
        args = dict(request.get("args") or {})
        if self._policy.level_for(name) == "deny" or self._approvals is None:
            session.execute(
                RecordToolDecision(
                    tool_name=name, args=args, decision="reject", decided_by="policy"
                )
            )
            return {
                "type": "reject",
                "message": f"The {name} tool is not permitted in this session.",
            }
        decision = await self._approvals.decide(
            ApprovalRequest(
                session_id=session.aggregate_id,
                tool_name=name,
                args=args,
                description=str(request.get("description") or ""),
                allowed_decisions=tuple(review.get("allowed_decisions") or ()),
            )
        )
        return self._apply(session, name, args, decision)

    def _apply(
        self,
        session: CodingSession,
        name: str,
        args: dict,
        decision: ApprovalDecision,
    ) -> dict:
        """Record a human's decision and translate it into langchain's shape."""
        if decision.type == "edit":
            edited = dict(decision.edited_args or args)
            session.execute(
                RecordToolDecision(
                    tool_name=name,
                    args=args,
                    decision="edit",
                    decided_by="human",
                    edited_args=edited,
                )
            )
            return {"type": "edit", "edited_action": {"name": name, "args": edited}}
        session.execute(
            RecordToolDecision(
                tool_name=name, args=args, decision=decision.type, decided_by="human"
            )
        )
        if decision.type == "approve":
            return {"type": "approve"}
        resumed = {"type": decision.type}
        if decision.message is not None:
            resumed["message"] = decision.message
        return resumed
