"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

from dataclasses import dataclass
from uuid import UUID

# Imported for its side effect as much as its names: redstring registers its
# event types at import time, and the session store may hold them -- the
# `Document` and `Consolidation` streams live in the same SQLite file as
# sessions. A read that meets a `DocumentExtracted` without this import raises
# `EventTypeNotFoundError`, including on the "no project at all" path, where
# nothing else would have pulled redstring in.
import redstring.events  # noqa: F401
from eventsource.observability import Tracer
from langchain_core.language_models import BaseChatModel
from redstring.llm.adapters.langchain import LangChainLlmProvider

from research_team.application import (
    DEFAULT_SYSTEM_PROMPT,
    ApprovalPort,
    AutonomyPolicy,
    ContextStrategy,
    ElideToolResults,
    FullHistory,
    LiveFeed,
    SessionService,
    TurnSupervisor,
)
from research_team.application.session_service import NO_NETWORK_CLAUSE
from research_team.infrastructure import config
from research_team.infrastructure.agent import DeepAgentTurnExecutor, build_model
from research_team.infrastructure.agent.compaction import SummarizingStrategy
from research_team.infrastructure.agent.delegation import (
    DEFAULT_SUBAGENTS,
    DELEGATION_PROMPT,
)
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
    build_knowledge_tools,
)
from research_team.infrastructure.agent.search import SEARCH_PROMPT, build_search_tool
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.stores import build_graph_store
from research_team.infrastructure.persistence import (
    EventStoreSessionRepository,
    SessionSummaryRunner,
)
from research_team.infrastructure.telemetry import build_tracer


@dataclass(frozen=True)
class Application:
    """The wired application: use cases, plus a live view of the same log."""

    service: SessionService
    feed: LiveFeed
    turns: TurnSupervisor
    context_mode: str
    """How this instance manages context. Not the same as the strategy name:
    `delegate` sends the full history and simply has less of it."""

    summaries: SessionSummaryRunner
    """Keeps `/sessions` following the log. Idle until `start()`."""

    policy: AutonomyPolicy
    """Per-tool autonomy levels for this instance, mutable after construction.

    Exposed here rather than buried in the executor because a front end that
    lets someone change autonomy mid-session needs a handle to mutate -- this
    is that handle, whichever adapter (CLI, web) drives it."""

    knowledge: RedstringKnowledge | None
    """This project's knowledge graph, or None with no project configured.

    No project means no store was opened and no tools were registered -- the
    same posture `search` has without an instance configured, and what keeps
    the README's sandbox claim honest for anyone who has not opted in."""

    async def start(self) -> None:
        """Open what needs a running event loop to open.

        Building an application is deliberately synchronous -- it picks
        adapters and wires them, nothing more -- because the web entrypoint
        constructs it before uvicorn has a loop, and an aiosqlite connection
        made on one loop cannot be used from another. Anything that has to be
        opened *inside* the loop that will use it is opened here.
        """
        await self.summaries.start()
        if self.knowledge is not None:
            # `ensure_schema` is the first call that actually talks to a
            # Neo4j server, so an unreachable one fails here -- at start,
            # where it can stop the process -- rather than mid-turn.
            # Idempotent, and a no-op for the in-memory store, which has no
            # such method.
            store = self.knowledge.graph_store
            if hasattr(store, "ensure_schema"):
                await store.ensure_schema()
            await rebuild_graph(
                store,
                feed=self.knowledge.event_store,
                project_id=self.knowledge.project_id,
            )

    def turns_tools(self) -> tuple:
        """The tools available to this instance's agent, for tests that assert on them.

        Reaches into the executor rather than tracking a separate copy: the
        executor's tuple is the one actually bound to the model, so this is
        what a test needs to check against, not a parallel record that could
        drift from it."""
        return tuple(self.service._executor._tools)

    async def summaries_caught_up(self) -> None:
        """Wait until the `/sessions` projection has seen everything appended.

        The read model is eventually consistent by construction -- a turn
        commits to the log and the projection follows -- which is invisible to
        a person clicking around and maddening to a test. This is the seam that
        makes the lag addressable rather than something to sleep through.
        """
        await self.summaries.caught_up()

    async def close(self) -> None:
        """Stop anything still running, then let go of the store.

        Cancelling first means an in-flight turn unwinds into a recorded
        failure rather than being abandoned mid-write. The projection stops
        before the store it reads through does, for the same reason.
        """
        await self.turns.cancel_all()
        await self.summaries.stop()
        await self.service.close()
        if self.knowledge is not None:
            store = self.knowledge.graph_store
            if hasattr(store, "close"):
                await store.close()


def _context_parts(
    mode: str, model: BaseChatModel, system_prompt: str
) -> tuple[ContextStrategy, tuple[dict, ...], str]:
    """Turn a mode name into a strategy, subagents, and a prompt suffix.

    The three modes treat the same problem differently: `elide` shortens what
    is replayed, `compact` replaces it with a summary, and `delegate` keeps it
    from accumulating by sending work to a fresh context. Only this function
    knows the mapping; everything else takes what it is given.
    """
    if mode == "elide":
        return (
            ElideToolResults(
                keep_results=config.context_keep_results(),
                clear_over_chars=config.context_clear_over_chars(),
            ),
            (),
            "",
        )
    if mode == "compact":
        return (
            SummarizingStrategy(
                model,
                trigger_tokens=config.context_trigger_tokens(),
                keep_messages=config.context_keep_messages(),
            ),
            (),
            "",
        )
    if mode == "delegate":
        # Delegation does not transform the history -- there is simply less of
        # it, because the expensive work happened somewhere else.
        return FullHistory(), DEFAULT_SUBAGENTS, DELEGATION_PROMPT
    return FullHistory(), (), ""


def build_application(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    context_mode: str | None = None,
    tracer: Tracer | None = None,
    approvals: ApprovalPort | None = None,
    policy: AutonomyPolicy | None = None,
    project_id: UUID | None = None,
) -> Application:
    """Wire everything over one event store.

    Creates no session: which session a caller is working on is the caller's
    business, and one application serves as many of them as ask.

    The repository backs both ports -- it is one connection to one log, read
    two ways -- so the service and the feed are always looking at the same
    events, with no chance of a live view lagging a different database.
    """
    resolved_path = db_path if db_path is not None else config.default_db_path()
    resolved_model = model if model is not None else build_model()
    mode = context_mode if context_mode is not None else config.context_mode()
    strategy, subagents, prompt_suffix = _context_parts(mode, resolved_model, system_prompt)
    resolved_policy = policy if policy is not None else AutonomyPolicy()

    # Opened before the tools below so the knowledge adapter can share this
    # connection's event store and snapshot store rather than opening its own
    # (BACKLOG B5: a second `SQLiteSnapshotStore` leaks a non-daemon thread).
    repository = EventStoreSessionRepository.open(resolved_path)

    # Search is the one tool that leaves the process, so it is registered only
    # when an instance is configured -- unset means the agent gets no network
    # tool at all, which is what keeps the README's sandbox claim true for
    # anyone who has not opted in.
    searxng = config.searxng_url()
    if searxng is not None:
        tools = (build_search_tool(searxng, limit=config.searxng_results()),)
        prompt_suffix += SEARCH_PROMPT
    else:
        tools = ()
        prompt_suffix += NO_NETWORK_CLAUSE

    # The knowledge graph belongs to a project. No project, no tools and no
    # store -- the same posture search has without an instance configured.
    if project_id is not None:
        knowledge = RedstringKnowledge(
            project_id,
            store=build_graph_store(config.graph_store()),
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            provider=LangChainLlmProvider(resolved_model, model=config.model_name()),
            domain=config.knowledge_domain(),
        )
        tools = (*tools, *build_knowledge_tools(knowledge))
        prompt_suffix += KNOWLEDGE_PROMPT
    else:
        knowledge = None

    executor = DeepAgentTurnExecutor(
        resolved_model,
        subagents=subagents,
        tools=tools,
        policy=resolved_policy,
        approvals=approvals,
    )
    resolved_tracer = tracer if tracer is not None else build_tracer()
    summaries = SessionSummaryRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    service = SessionService(
        repository,
        executor,
        summaries,
        default_system_prompt=system_prompt + prompt_suffix,
        context=strategy,
        # Resolved once and shared: whether this process exports traces is a
        # deployment decision, and the composition root is where deployment
        # decisions live. The projection gets the same instance, so a turn and
        # the read-model work it causes are read off one trace rather than two.
        tracer=resolved_tracer,
    )
    return Application(
        service=service,
        feed=LiveFeed(repository),
        turns=TurnSupervisor(service),
        context_mode=mode,
        summaries=summaries,
        policy=resolved_policy,
        knowledge=knowledge,
    )


def build_service(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    context_mode: str | None = None,
    tracer: Tracer | None = None,
) -> SessionService:
    """Just the use cases, for callers with no use for a live feed."""
    return build_application(
        model=model,
        system_prompt=system_prompt,
        db_path=db_path,
        context_mode=context_mode,
        tracer=tracer,
    ).service
