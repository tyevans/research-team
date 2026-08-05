"""The `TurnExecutor` port, implemented with deepagents and langchain."""

import logging
from collections.abc import Sequence
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
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
from research_team.application.ports import ActivityDelta, ActivityMessage
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

logger = logging.getLogger(__name__)


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


def to_activity_message(message: BaseMessage) -> ActivityMessage | None:
    """A whole message as a provisional note, or None if it cannot be keyed.

    Built from `to_recorded` rather than from a second reading of the message,
    so what streams and what is eventually recorded cannot disagree about kind
    or payload -- that divergence is the failure mode this channel most needs
    to avoid.

    A message with no id is dropped rather than given a synthetic one: the id
    is what the browser accumulates deltas against, and a guessed one would
    splice two messages into one bubble.
    """
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    recorded = to_recorded(message)
    return ActivityMessage(
        message_id=str(message_id),
        kind=recorded.kind,
        payload=recorded.payload,
        is_error=recorded.is_error,
    )


MAIN_AGENT_NODE = "model"
"""The graph node the top-level agent's model call runs under.

Subagents stream on the same channel. Without this discriminator a subagent's
internal reasoning would render as the main agent's answer to the user.
"""


def to_activity_delta(chunk: Any) -> ActivityDelta | None:
    """A prose delta from a `messages`-mode chunk, or None if it is not one.

    Returns None for tool calls, for subagent chunks, and for anything without
    text -- this channel carries only what a person is waiting to read.

    The type test is `AIMessage`, which covers `AIMessageChunk` because it
    subclasses it. Testing for the chunk type alone would report nothing at
    all from a non-streaming model, which delivers one whole message here.
    """
    try:
        message, metadata = chunk
    except (TypeError, ValueError):
        return None
    if metadata.get("langgraph_node") != MAIN_AGENT_NODE:
        return None
    if not isinstance(message, AIMessage):
        return None
    if getattr(message, "tool_calls", None):
        return None
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    text = message.text if isinstance(getattr(message, "text", None), str) else message.content
    if not isinstance(text, str) or not text:
        return None
    return ActivityDelta(message_id=str(message_id), text=text)


def _report(
    on_activity: ActivityReporter | None, note: ActivityMessage | ActivityDelta
) -> None:
    """Deliver one note to the reporter, never letting it fail the turn.

    A minute of model work is not worth discarding because a browser feed
    raised -- this is a side channel to a human watching, not a dependency
    the turn's outcome should ever hinge on.
    """
    if on_activity is None:
        return
    try:
        on_activity(note)
    except Exception:
        logger.exception("activity reporter raised; continuing the turn")


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

        Streams both `"values"` and `"messages"` from one pass: `values`
        chunks carry the full state, from which `final` and the durable
        record are built exactly as before; `messages` chunks carry
        token-level prose deltas for a human waiting on the reply. A local
        model can take a minute per turn, and silence for that long is
        indistinguishable from a hang.

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
            async for mode, chunk in agent.astream(
                payload,
                config=run_config,
                # Two modes from one pass. `values` is what the durable record
                # is built from, exactly as before; `messages` exists only to
                # let prose reach a waiting human before the turn commits. One
                # pass rather than two is what keeps them from disagreeing.
                stream_mode=["values", "messages"],
            ):
                if mode == "values":
                    state = chunk
                    final = state.get("messages", final)
                    for message in final[reported:]:
                        note = to_activity_message(message)
                        if note is not None:
                            _report(on_activity, note)
                    reported = len(final)
                elif mode == "messages":
                    delta = to_activity_delta(chunk)
                    if delta is not None:
                        _report(on_activity, delta)
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
