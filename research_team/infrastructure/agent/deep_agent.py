"""The `TurnExecutor` port, implemented with deepagents and langchain."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from research_team.infrastructure.agent.activity_stream import (
    MAIN_AGENT_NODE,
    _first_arg,
    _report,
    describe_activity,
    to_activity_delta,
    to_activity_message,
)
from research_team.infrastructure.agent.approval import interrupt_config
from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.messages import (
    encode_user_message,
    last_text,
    new_messages,
    to_payload_messages,
    to_recorded,
)
from research_team.infrastructure.agent.model_providers import (
    build_embedding_provider,
    build_extraction_model,
    build_model,
)
from research_team.knowledge.application.knowledge_attachment import _compose
from research_team.platform.shared.ports import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRefused,
    ApprovalRequest,
    TurnResult,
)
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.domain import (
    RecordToolDecision,
    Session,
)
from research_team.tenancy.application.grants import GrantRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "MAIN_AGENT_NODE",
    "DeepAgentTurnExecutor",
    "MiddlewareProvider",
    "ModelProvider",
    "SubagentProvider",
    "ToolProvider",
    "_first_arg",
    "_report",
    "build_embedding_provider",
    "build_extraction_model",
    "build_model",
    "describe_activity",
    "to_activity_delta",
    "to_activity_message",
]

#: Middleware for one turn, resolved when that turn's agent is built.
#:
#: A plain sequence would be wrong for anything that depends on where the run
#: stands, because this executor rebuilds its agent on every pass and what the
#: session holds changes between two of them -- `ComponentFeedback` reads the
#: file the previous turn's `edit_file` wrote, so a sequence built once would
#: validate every later turn against the state the first one saw. It takes the
#: session rather than closing over one so that a single executor can serve
#: many.
MiddlewareProvider = Callable[[Session], Awaitable[Sequence[AgentMiddleware]]]

#: Extra tools for one turn, resolved when that turn's agent is built.
#:
#: The sibling of `MiddlewareProvider`, and it exists for the same reason plus
#: one more. `set_tools` covers a tool set that changes when a project is
#: attached; this covers one that changes with no attachment event to hang it
#: off -- a run's fetch grant is registered by `start_run` partway through a
#: session that is already going, and a tool registered only at attach time
#: would be missing for the entire run that was granted it.
#:
#: Middleware can only filter the registered set down, never add to it, so any
#: tool a turn might be allowed has to be registered here at creation. Resolving
#: the tools and the middleware per turn from the same facts is what keeps the
#: two consistent.
ToolProvider = Callable[[Session], Awaitable[Sequence[BaseTool]]]

SubagentProvider = Callable[[Session], Awaitable[Sequence[dict]]]

#: The fourth of the per-turn seams, and the one that decides *who answers*
#: rather than what they are given. It exists because the model is the one
#: thing about a turn that a person configures per project and that the
#: executor was holding for the life of the process.
#:
#: `None` from a provider means "the executor's own model", which is what a
#: session belonging to no project resolves to -- not an error, and not a
#: reason to refuse the turn.
ModelProvider = Callable[[Session], Awaitable[BaseChatModel | None]]
"""The subagents this turn may dispatch, chosen from the session.

The fourth of the executor's per-turn seams, and it exists for a reason the
other three do not have: a subagent appears in the system prompt whether or not
it is ever called. A roster built for course authoring, offered to every chat
turn, is six paragraphs of instruction about work that turn cannot do -- so the
cost of a static list is paid on every session, not just on the ones that would
have used it.

Defaults to nothing, so an executor wired without one builds precisely the
agent it built before this existed.
"""


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
        middleware: Sequence[AgentMiddleware] = (),
        middleware_provider: MiddlewareProvider | None = None,
        tools_provider: ToolProvider | None = None,
        subagents_provider: SubagentProvider | None = None,
        model_provider: ModelProvider | None = None,
        grants: GrantRegistry | None = None,
    ) -> None:
        self._model = model
        self._subagents = list(subagents)
        self._tools = list(tools)
        # Two ways in, because middleware divides cleanly into two kinds.
        # `middleware` is for anything true of this executor for its whole
        # life; `middleware_provider` is for anything true only of the turn
        # about to run, since the executor outlives any one turn's answer.
        # Both default to nothing, so an executor wired without either builds
        # precisely the agent it built before any of this existed.
        self._middleware = list(middleware)
        self._middleware_provider = middleware_provider
        self._tools_provider = tools_provider
        self._subagents_provider = subagents_provider
        self._model_provider = model_provider
        # An all-`auto` policy is the default so that wiring a supervisor is
        # opt-in: without one, nothing is gated and the executor behaves
        # exactly as it did before interrupts existed.
        self._policy = policy if policy is not None else AutonomyPolicy()
        self._approvals = approvals
        # `None` by default so every existing caller -- and every existing
        # test -- builds exactly the executor it always did: with no
        # registry, `interrupt_config` below has no grant it could ever find,
        # which is `_gate_for`'s own documented behaviour for this case.
        self._grants = grants

    async def _turn_model(self, session: Session) -> BaseChatModel:
        """Which model answers this turn.

        Falls back to the model this executor was constructed with, which is
        both the headless answer and the answer for a session belonging to no
        project. That fallback is why adding this seam changed no existing
        caller: an executor wired without a provider builds precisely the agent
        it built before.
        """
        if self._model_provider is None:
            return self._model
        return await self._model_provider(session) or self._model

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model_name", type(self._model).__name__)

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        """The registered tool set: what every turn starts from.

        Not the whole of what the next turn gets. A `tools_provider` adds what
        the run's own state implies -- today, a grant-bound `fetch` for a
        session some run's `FetchGrant` covers, which follows no redirects and
        charges its spend -- and that cannot be reported here, because it
        depends on a session this property has not been given. A caller asking
        what a *particular* turn was bound has to watch the model, which is
        what the tests do.
        """
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
        session: Session,
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
        session: Session,
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
        middleware = [*self._middleware, *await self._resolved_middleware(session)]
        # A per-turn tool must replace a registered one of the same name, not
        # sit beside it -- two tools named `fetch` would leave langgraph to
        # pick between them, which is not a decision this class delegates.
        # `_compose` already encodes that rule for `set_tools`
        # (application/knowledge_attachment.py); reused rather than
        # reimplemented so the two lifetimes (per-turn here, persistent there)
        # cannot silently drift into different shadowing rules.
        turn_tools = _compose(self._tools, await self._resolved_tools(session))
        agent = create_deep_agent(
            model=await self._turn_model(session),
            tools=turn_tools or None,
            backend=EventSourcedBackend(session),
            system_prompt=system_prompt,
            interrupt_on=interrupt_config(
                self._policy, session_id=session.aggregate_id, grants=self._grants
            ),
            # Resuming is impossible without one: `Command(resume=...)` needs
            # somewhere to have parked the halted graph. Per turn and in
            # memory, because nothing here outlives the turn -- the durable
            # record of what happened is the event log, not this.
            checkpointer=MemorySaver(),
            # Subagents share this backend, so their file writes land in the
            # same event log as everything else -- delegated work stays as
            # auditable as work the main agent does itself. The roster itself
            # is chosen per turn (see `SubagentProvider`): the `or None` below
            # is deepagents' own contract -- an empty sequence and `None` are
            # not the same thing to it.
            subagents=list(await self._turn_subagents(session)) or None,
            # Ahead of the tail deepagents appends, so anything here runs
            # *outside* `HumanInTheLoopMiddleware`: a stage narrows the tool
            # list first, and the gate then poses approvals over what survived.
            # The reverse order would gate calls the stage was going to forbid
            # anyway, which is a human asked to rule on a non-question.
            middleware=middleware,
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

    async def _resolved_middleware(self, session: Session) -> Sequence[AgentMiddleware]:
        """Whatever the provider says applies to this turn, or nothing.

        Asked on every pass because that is the only place the answer can come
        from. There is no graph state to read it out of: `_invoke` builds a
        `MemorySaver()` inline and the `thread_id` embeds `turn_index`, so the
        checkpoint is discarded the moment the turn ends. A stage therefore has
        to be reconstructed from the event log each time an agent is built.

        That is the design rather than a workaround, and the temptation to
        "fix" it by adding a durable checkpointer is the thing this paragraph
        exists to head off: a checkpointer holding stage would be a second
        record of where a run stands, sitting beside the log that already
        holds it, with nothing keeping the two honest. One source of truth,
        folded fresh, costs a replay per turn and cannot drift.
        """
        if self._middleware_provider is None:
            return ()
        return await self._middleware_provider(session)

    async def _resolved_tools(self, session: Session) -> Sequence[BaseTool]:
        """Whatever tools this turn gets on top of the registered set, or none.

        Kept separate from `set_tools` because the two answer different
        questions. `set_tools` is what a project attachment swaps in, and it
        persists until something swaps it back; this is what the *state of the
        run* implies right now, and there is no event to hang it off -- what
        a session may reach is changed by HTTP calls that append to the log and
        return, with nothing to notify an executor holding a stale list.

        Resolved on every pass for the same reason the middleware is, and
        deliberately from the same facts: middleware filters down over what was
        registered at agent creation, so a tool this provider does not supply
        is a tool no middleware can ever expose.
        """
        if self._tools_provider is None:
            return ()
        return await self._tools_provider(session)

    async def _turn_subagents(self, session: Session) -> Sequence[dict]:
        if self._subagents_provider is None:
            return self._subagents
        return await self._subagents_provider(session)

    async def _settle(self, session: Session, interrupts: Sequence[Any]) -> list[dict]:
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

    async def _decide(self, session: Session, request: dict, review: dict) -> dict:
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
        try:
            decision = await self._approvals.decide(
                ApprovalRequest(
                    session_id=session.aggregate_id,
                    tool_name=name,
                    args=args,
                    description=str(request.get("description") or ""),
                    allowed_decisions=tuple(review.get("allowed_decisions") or ()),
                )
            )
        except ApprovalRefused as refused:
            # The port refused to keep waiting -- nobody answered, so nobody
            # decided. Recorded the same way as the `deny` arm above rather
            # than through `_apply`, because `_apply` always writes
            # `decided_by="human"` and that would be a log entry claiming a
            # person saw this call and rejected it. Nobody did.
            session.execute(
                RecordToolDecision(
                    tool_name=name,
                    args=args,
                    decision="reject",
                    decided_by="policy",
                )
            )
            return {"type": "reject", "message": str(refused)}
        return self._apply(session, name, args, decision)

    def _apply(
        self,
        session: Session,
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
                tool_name=name,
                args=args,
                decision=decision.type,
                decided_by="human",
            )
        )
        if decision.type == "approve":
            return {"type": "approve"}
        resumed = {"type": decision.type}
        if decision.message is not None:
            resumed["message"] = decision.message
        return resumed
