"""The `TurnExecutor` port, implemented with deepagents and langchain."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from redstring import EmbeddingProvider
from redstring.llm.adapters.langchain import NO_THINKING
from redstring.llm.adapters.langchain_embedding import LangChainEmbeddingProvider

from research_team.application import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRefused,
    ApprovalRequest,
    AutonomyPolicy,
    TurnResult,
)
from research_team.application.grants import GrantRegistry
from research_team.application.knowledge_attachment import _compose
from research_team.application.ports import (
    ActivityDelta,
    ActivityMessage,
    GateReview,
    GateReviewer,
)
from research_team.domain import RecordToolDecision, Session
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

#: Middleware for one turn, resolved when that turn's agent is built.
#:
#: A plain sequence would be wrong for anything that depends on where the run
#: stands, because this executor rebuilds its agent on every pass and a
#: workflow stage can change between two of them. It takes the session rather
#: than closing over one so that a single executor can serve many.
MiddlewareProvider = Callable[[Session], Awaitable[Sequence[AgentMiddleware]]]

#: Extra tools for one turn, resolved when that turn's agent is built.
#:
#: The sibling of `MiddlewareProvider`, and it exists for the same reason plus
#: one more. `set_tools` covers a tool set that changes when a project is
#: attached; this covers one that changes when the *project* does, with no
#: attachment event to hang it off -- selecting a workflow is an HTTP call that
#: writes an event and returns, and a tool registered only at attach time would
#: be missing for the entire session that chose it.
#:
#: `StageMiddleware` can only filter down, so anything a stage might permit has
#: to be registered here at creation. A tool resolved per turn and a middleware
#: resolved per turn from the same fold is what keeps those two consistent.
ToolProvider = Callable[[Session], Awaitable[Sequence[BaseTool]]]

#: This turn's corpus mount: `/sources/<source_id>` -> file data.
#:
#: Per turn for a reason the two providers above do not have. `_read_files()`
#: is synchronous and the corpus port is not, so the mount has to be a snapshot
#: taken while there is still a coroutine to await in -- which is here, and
#: nowhere inside a file tool. The cost is one turn of staleness: a document
#: stored mid-turn is not greppable until the next one. `source_mount.py` has
#: the rest of the reasoning, including why that is affordable.
SourcesProvider = Callable[[Session], Awaitable[dict[str, Any]]]

SubagentProvider = Callable[[Session], Awaitable[Sequence[dict]]]
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


def build_model() -> BaseChatModel:
    """The local OpenAI-compatible endpoint, fully env-overridable."""
    return ChatOpenAI(
        model=config.model_name(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        temperature=0,
    )


def build_extraction_model() -> BaseChatModel:
    """The same endpoint as `build_model`, told not to think before answering.

    A second `ChatOpenAI` rather than `build_model().bind(extra_body=...)`,
    for two reasons. `extra_body` is a constructor field, and `bind` returns a
    `RunnableBinding`, not the `BaseChatModel` that `LangChainLlmProvider`
    is typed against. And the agent and the extractor genuinely want different
    request bodies, so two objects says what is true: this one is not the
    agent's model with a decoration, it is the extractor's model.

    redstring 0.4.0 made thinking-off the default for extraction, but only
    inside `LangChainLlmProvider.openai_compatible`. This project builds its
    own chat model and uses `__init__`, so that default never reached it --
    which is the bug this exists to close. `NO_THINKING` is imported rather
    than spelled out so a rename or a change of shape upstream breaks the
    build instead of quietly leaving extraction thinking again.

    See `config.extraction_thinking` for the measurement, the env override and
    the backends this field is rejected by.
    """
    return ChatOpenAI(
        model=config.model_name(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        temperature=0,
        extra_body=None if config.extraction_thinking() else dict(NO_THINKING),
    )


def build_embedding_provider() -> EmbeddingProvider:
    """The embedding endpoint, wrapped in redstring's port.

    A third client rather than a third use of `build_model`, for the reason
    `build_extraction_model` is a second one: this is a different model at a
    possibly different address answering a different API, and the only thing
    it shares with the chat client is that both speak OpenAI's protocol.

    `dimensions` is passed to `OpenAIEmbeddings` **and** declared to
    `LangChainEmbeddingProvider`, which looks redundant and is not. The first
    asks the server for that width -- OpenAI's `text-embedding-3-*` honour it
    and truncate, most local servers ignore it and return their native width.
    The second is what redstring checks the `VectorStore` against before
    embedding anything. Declaring only the second would let a server quietly
    return 1024 components into a store built for 768, which fails at the
    first write with `DimensionMismatchError` -- a poison event, so the ingest
    that triggered it is unrecoverable rather than retryable.

    Nothing here contacts the server. A wrong model name, a wrong width or an
    endpoint that serves no embeddings all surface on the first `embed`, which
    is during an ingest. `config.embedding_model` refuses an unset name here
    instead, which is the one failure that can be moved earlier.
    """
    return LangChainEmbeddingProvider(
        OpenAIEmbeddings(
            model=config.embedding_model(),
            base_url=config.embedding_base_url(),
            api_key=config.embedding_api_key(),
            dimensions=config.embedding_dimension(),
            check_embedding_ctx_length=False,
        ),
        model=config.embedding_model(),
        dimension=config.embedding_dimension(),
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
        middleware: Sequence[AgentMiddleware] = (),
        middleware_provider: MiddlewareProvider | None = None,
        tools_provider: ToolProvider | None = None,
        sources_provider: SourcesProvider | None = None,
        subagents_provider: SubagentProvider | None = None,
        gate_reviewer: GateReviewer | None = None,
        grants: GrantRegistry | None = None,
    ) -> None:
        self._model = model
        self._subagents = list(subagents)
        self._tools = list(tools)
        # Two ways in, because middleware divides cleanly into two kinds.
        # `middleware` is for anything true of this executor for its whole
        # life; `middleware_provider` is for anything true only of the turn
        # about to run -- which is what stage enforcement is, since the stage
        # is folded from the event log and moves while the executor does not.
        # Both default to nothing, so an executor wired without a workflow
        # builds precisely the agent it built before any of this existed.
        self._middleware = list(middleware)
        self._middleware_provider = middleware_provider
        self._tools_provider = tools_provider
        # Optional on this class's established convention -- an executor wired
        # without one builds precisely the agent it built before mounting
        # existed. The cost is real and worth naming: a composition that
        # forgets it produces a `grep` that finds no gathered source and says
        # nothing, which is the failure mounting exists to remove. The ask
        # executor makes the same argument required, because it has one
        # composition site and no test that constructs it bare.
        self._sources_provider = sources_provider
        self._subagents_provider = subagents_provider
        # Consulted per gated call, before the human is. Optional for the same
        # reason the two providers above are: an executor wired without a
        # workflow has nothing to review and poses exactly the approvals it
        # posed before this existed.
        self._gate_reviewer = gate_reviewer
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

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model_name", type(self._model).__name__)

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        """The registered tool set: what every turn starts from.

        Not the whole of what the next turn gets. A `tools_provider` adds what
        the run's own state implies -- today, the workflow gate -- and that
        cannot be reported here, because it depends on a session this property
        has not been given. A caller asking what a *particular* turn was bound
        has to watch the model, which is what the tests do.
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
            model=self._model,
            tools=turn_tools or None,
            backend=EventSourcedBackend(
                session, sources=await self._resolved_sources(session)
            ),
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
        run* implies right now, and there is no event to hang it off -- a
        workflow is chosen by an HTTP call that appends to the log and returns,
        with nothing to notify an executor holding a stale list.

        Resolved on every pass for the same reason the middleware is, and
        deliberately from the same fold: `StageMiddleware` filters down over
        what was registered at agent creation, so a tool that a stage might
        permit and this did not supply is a tool no stage can ever expose.
        """
        if self._tools_provider is None:
            return ()
        return await self._tools_provider(session)

    async def _resolved_sources(self, session: Session) -> dict[str, Any]:
        """This turn's corpus mount, or nothing.

        Resolved per pass rather than per turn, alongside the tools and the
        middleware. That is more work than the staleness contract requires --
        `SourcesProvider` promises only that a mount is current as of the turn
        -- and it is what keeps the three resolutions in one place, which is
        worth more than the saved reads: a pass that rebuilt its tools from a
        newer fold than its files would be a seam nobody thinks to look at.
        """
        if self._sources_provider is None:
            return {}
        return await self._sources_provider(session)

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
        gate = await self._review_gate(session, name, args)
        # Every decision from here down answers a review, when there was one.
        # The two above are recorded before `_review_gate` runs and get no
        # `review_id` on purpose: no review ran, so there is nothing to name.
        review_id = gate.review_id if gate is not None else None
        if gate is not None and gate.refusal is not None:
            # Refused without the human seeing it, which is the same shape as
            # the `deny` arm above and for a related reason: there is no
            # judgement here to put to anybody. `decided_by` is the harness
            # rather than policy, because policy said this tool was askable and
            # it was the check library that objected.
            session.execute(
                RecordToolDecision(
                    tool_name=name,
                    args=args,
                    decision="reject",
                    decided_by="harness",
                    review_id=review_id,
                )
            )
            return {"type": "reject", "message": gate.refusal}
        try:
            decision = await self._approvals.decide(
                ApprovalRequest(
                    session_id=session.aggregate_id,
                    tool_name=name,
                    args=args,
                    description=str(request.get("description") or ""),
                    allowed_decisions=tuple(review.get("allowed_decisions") or ()),
                    context=gate.context if gate is not None else None,
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
                    review_id=review_id,
                )
            )
            return {"type": "reject", "message": str(refused)}
        return self._apply(session, name, args, decision, review_id)

    async def _review_gate(self, session: Session, name: str, args: dict) -> GateReview | None:
        """What the harness has to say about this call, or nothing.

        Never lets the reviewer's failure become the turn's, exactly as
        `_report` refuses to let a browser feed cost a minute of model work.
        The asymmetry with the refusal path above is deliberate: an invariant
        that *failed* is a refusal, and an invariant that *crashed* is our bug,
        and charging the run for our bug is how a gate earns a reputation for
        being in the way.
        """
        if self._gate_reviewer is None:
            return None
        try:
            return await self._gate_reviewer(session, name, args)
        except Exception:
            logger.exception("gate reviewer raised; posing the approval unreviewed")
            return None

    def _apply(
        self,
        session: Session,
        name: str,
        args: dict,
        decision: ApprovalDecision,
        review_id: UUID | None = None,
    ) -> dict:
        """Record a human's decision and translate it into langchain's shape.

        `review_id` is passed in rather than obtained by re-running the
        reviewer: `_review_gate` emits the review event, so a second call would
        record a second review that nobody was asked about and halve every fire
        rate.
        """
        if decision.type == "edit":
            edited = dict(decision.edited_args or args)
            session.execute(
                RecordToolDecision(
                    tool_name=name,
                    args=args,
                    decision="edit",
                    decided_by="human",
                    edited_args=edited,
                    review_id=review_id,
                )
            )
            return {"type": "edit", "edited_action": {"name": name, "args": edited}}
        session.execute(
            RecordToolDecision(
                tool_name=name,
                args=args,
                decision=decision.type,
                decided_by="human",
                review_id=review_id,
            )
        )
        if decision.type == "approve":
            return {"type": "approve"}
        resumed = {"type": decision.type}
        if decision.message is not None:
            resumed["message"] = decision.message
        return resumed
