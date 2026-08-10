"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

# Imported for its side effect as much as its names: redstring registers its
# event types at import time, and the session store may hold them -- the
# `Document` and `Consolidation` streams live in the same SQLite file as
# sessions. A read that meets a `DocumentExtracted` without this import raises
# `EventTypeNotFoundError`, including on the "no project at all" path, where
# nothing else would have pulled redstring in.
import redstring.events  # noqa: F401
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from redstring.llm.adapters.langchain import LangChainLlmProvider

from research_team.application import (
    DEFAULT_SYSTEM_PROMPT,
    ApprovalPort,
    AutonomyPolicy,
    AutoResearchDriver,
    ContextStrategy,
    DispatchesInFlight,
    ElideToolResults,
    ExtractionChannel,
    FullHistory,
    KnowledgeAttachment,
    LiveFeed,
    ProjectGraphs,
    ResearchSupervisor,
    SessionService,
    SummaryProjects,
    TopicRoundRunner,
    TurnSupervisor,
    WorkerRoster,
)
from research_team.application.artifacts import stage_artifact_instructions
from research_team.application.autonomy import ADVANCE_STAGE_TOOL, FETCH_TOOL
from research_team.application.components import component_guidance
from research_team.application.ports import GateReview
from research_team.application.session_service import NO_SEARCH_CLAUSE
from research_team.application.stage_exit import (
    findings_path,
    gate_context,
    refusal,
    render_review,
    review_stage,
)
from research_team.application.stage_runner import StageRunner
from research_team.application.topic_dispatch import TopicDispatcher
from research_team.application.topic_read import TopicReadPort
from research_team.application.topic_seeding import TopicSeeder
from research_team.application.topics import TOPICS_PROMPT
from research_team.domain import CodingSession, ProjectState, current_stage_of
from research_team.domain.auto_research import Budget
from research_team.domain.commands import WriteFile
from research_team.domain.topic import Topic
from research_team.domain.workflow import Preset
from research_team.infrastructure import config
from research_team.infrastructure.agent import (
    DeepAgentTurnExecutor,
    build_embedding_provider,
    build_extraction_model,
    build_model,
)
from research_team.infrastructure.agent.compaction import SummarizingStrategy
from research_team.infrastructure.agent.component_feedback import ComponentFeedback
from research_team.infrastructure.agent.corpus_tools import (
    CORPUS_PROMPT,
    build_corpus_tools,
)
from research_team.infrastructure.agent.delegation import (
    DEFAULT_SUBAGENTS,
    DELEGATION_PROMPT,
)
from research_team.infrastructure.agent.fetch import (
    FETCH_CORPUS_PROMPT,
    FETCH_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
    build_knowledge_tools,
)
from research_team.infrastructure.agent.recall import Recall
from research_team.infrastructure.agent.search import SEARCH_PROMPT, build_search_tool
from research_team.infrastructure.agent.stage_middleware import (
    StageMiddleware,
    managed_tools_for,
)
from research_team.infrastructure.agent.topic_tools import (
    RepositoryTopics,
    build_topic_tools,
)
from research_team.infrastructure.agent.workflow_tools import (
    WORKFLOW_PROMPT,
    EndTurnOnStageAdvance,
    build_workflow_tools,
)
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.stores import (
    build_graph_store,
    build_vector_store,
)
from research_team.infrastructure.persistence import (
    CorpusRunner,
    EventStoreSessionRepository,
    SessionSummaryRunner,
    TopicRunner,
    build_auto_research_repository,
    build_corpus_repository,
    build_learner_progress_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.project_workflow import ProjectWorkflow
from research_team.infrastructure.persistence.topic_reader import ProjectTopicReader
from research_team.infrastructure.telemetry import build_tracer
from research_team.workflows import PRESETS

logger = logging.getLogger(__name__)


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

    corpus: CorpusRunner
    """Keeps the corpus table following the log. Idle until `start()`.

    A field rather than something reached through the service, because the
    corpus is read by two callers that share nothing else: the agent, through
    the tools attached with a project, and the web layer, which lists and
    reads any project's sources without attaching anything."""

    topics: TopicRunner
    """Keeps the topic tables following the log. Idle until `start()`.

    A field for the same reason `corpus` is one: the queue is read by the
    agent through the tools attached with a project, and by anything driving an
    autonomous run, which shares nothing else with a session."""

    graphs: ProjectGraphs
    """The single owner of every project's open graph store in this instance.

    A field rather than something reached only through `open_graph`'s
    closure, because a graph-browsing read route needs to `open` the same
    store the attached agent writes to, and a delete route needs to `close` it --
    neither is reachable through the executor or the service, so this is
    where both go looking."""

    topic_readers: Callable[[UUID], TopicReadPort]
    """One project's `TopicReadPort`, built fresh per call.

    A factory rather than a bare repository, for the reason `_reader` in
    `app.py` is a function and not a field: the web layer has no business
    knowing that a topic reader is assembled from a queue projection, an
    aggregate repository and a corpus-facts callable -- that is composition
    knowledge, and handing it out piecemeal would make every future change to
    how a reader is built a change to the web layer too. This closes over the
    one `AggregateRepository[Topic]` also used by `start_run` below, so
    there is exactly one such object, not a second built to avoid depending
    on this field."""

    topic_repository: AggregateRepository[Topic]
    """The `Topic` aggregate repository, for routes that change a topic's state.

    Exposed directly rather than behind a factory, unlike `topic_readers`:
    an `AggregateRepository[Topic]` needs no project bound at construction --
    `load` takes the topic id and the aggregate carries its own `project_id`
    -- so there is no per-project object to assemble and nothing a factory
    would buy here. The same object `topic_readers` and `start_run` already
    close over, not a second one, for the reason given above. Mirrors
    `SessionService.projects`, which exposes the `Project` repository the
    same way for the same reason: a write that is not a session use case has
    nowhere else to reach for the aggregate it needs."""

    research: ResearchSupervisor
    """Autonomous runs over this instance's topic queues.

    A field rather than something built where it is used, because a run needs
    four things that only this module holds together -- the run repository, the
    topic repository, the queue projection and the turn supervisor -- and both
    front ends want the same one. Two supervisors over one database would each
    believe they held the only run on a project."""

    topic_seeder: TopicSeeder
    """Names a project's first topics in one turn, given a subject.

    A field for the same reason `research` is one: both front ends want the
    same object, and it is built from the same `service` and `turns` this
    module already holds -- nothing a factory would buy over exposing the
    one instance directly, the way `topic_repository` is exposed rather than
    rebuilt per call."""

    dispatcher: TopicDispatcher
    """Writes down what this project understands about one topic, in one turn.

    A field for the same reason `topic_seeder` is one, and built from the same
    three things this module already holds -- `service`, `turns` and
    `topic_readers`. The reader in particular must be *this* instance's: the
    dispatcher numbers a topic's directory by its position in the project's
    topic list, and a second reader over the same database would answer the
    same question, which is exactly why building one here rather than
    threading it through would look harmless and be a second source of a fact
    the front end also reads."""

    stage_runner: StageRunner
    """Drives a project's stages, asking at every boundary it reaches.

    A field and not a route, deliberately. `workflow-engine.md` §5 and
    `stage-boundaries.md` open question 1 both say the same thing: the runner
    should be built *after* a human has prompted a preset through by hand,
    because the thing that would falsify its design is a prompt, and no preset
    resolves end to end yet. Exposing it here makes it usable and testable
    without committing a front end to a button that would spend a budget on
    stages whose prompts do not exist. `TopicDispatcher` was reachable the
    same way before `/dispatch` existed.

    Built from the same `service`, `turns`, `approvals` and `policy` the rest
    of this module holds -- the policy especially, for the reason stated where
    it is constructed."""

    workers: WorkerRoster
    """Everything in flight on a project, for a front end that wants to show it.

    A field for the same reason `research` is one: it needs three things only
    this module holds together -- the session service, the turn supervisor and
    the research supervisor -- and both front ends want the same answer from
    the same three."""

    policy: AutonomyPolicy
    """Per-tool autonomy levels for this instance, mutable after construction.

    Exposed here rather than buried in the executor because a front end that
    lets someone change autonomy mid-session needs a handle to mutate -- this
    is that handle, whichever adapter (CLI, web) drives it."""

    _initial_project_id: UUID | None = None
    """`project_id`, if `build_application` was given one. Attached in
    `start()` rather than at construction, because attaching talks to a
    store and building is deliberately synchronous."""

    @property
    def knowledge(self) -> RedstringKnowledge | None:
        """This instance's currently attached knowledge graph, or None.

        Not a fixed field: which project is attached can change after
        construction, now that a REPL can `/project use` into one. Reads
        through the service, which is what actually owns the attachment --
        so this and `service.current_knowledge` can never disagree.
        """
        return self.service.current_knowledge

    async def attach_project(self, project_id: UUID) -> None:
        """Open `project_id`'s graph and give the executor its tools.

        Thin delegation: the service owns the attachment and its atomicity
        guarantee (a failure here must leave `knowledge` at None and the
        executor's tools unchanged), because the REPL calls the same method
        on the service directly -- this exists so the build-time
        `project_id=` path below has one path to go through as well, not two.
        """
        await self.service.attach_project(project_id)

    async def detach_project(self) -> None:
        """Close whatever graph is attached and restore the tools without it."""
        await self.service.detach_project()

    async def start(self) -> None:
        """Open what needs a running event loop to open.

        Building an application is deliberately synchronous -- it picks
        adapters and wires them, nothing more -- because the web entrypoint
        constructs it before uvicorn has a loop, and an aiosqlite connection
        made on one loop cannot be used from another. Anything that has to be
        opened *inside* the loop that will use it is opened here, including
        attaching `_initial_project_id`, if `build_application` was given one
        -- so an unreachable Neo4j fails here, at start, rather than mid-turn.
        """
        await self.summaries.start()
        await self.corpus.start()
        await self.topics.start()
        if self._initial_project_id is not None:
            await self.attach_project(self._initial_project_id)

    def turns_tools(self) -> tuple[BaseTool, ...]:
        """The tools available to this instance's agent, for tests that assert on them.

        Reaches into the executor's public `tools` property rather than a
        parallel copy: the executor's tuple is the one actually bound to the
        model, so this is what a test needs to check against."""
        return self.service._executor.tools

    async def summaries_caught_up(self) -> None:
        """Wait until the `/sessions` projection has seen everything appended.

        The read model is eventually consistent by construction -- a turn
        commits to the log and the projection follows -- which is invisible to
        a person clicking around and maddening to a test. This is the seam that
        makes the lag addressable rather than something to sleep through.
        """
        await self.summaries.caught_up()

    async def topics_caught_up(self) -> None:
        """Block until the topic tables have seen everything appended so far.

        Load-bearing rather than a test affordance, for the reason the corpus
        equivalent is: an autonomous round records a look and then asks for the
        next topic, and the gap between the append and the row is exactly where
        it would be handed back the topic it just finished.
        """
        await self.topics.caught_up()

    async def corpus_caught_up(self) -> None:
        """Wait until the corpus projection has seen everything appended.

        The same seam `summaries_caught_up` provides, for the same reason: a
        `remember` commits to the log and the table follows, so a caller that
        stores a document and immediately lists it would otherwise be racing
        the projection.
        """
        await self.corpus.caught_up()

    async def close(self) -> None:
        """Stop anything still running, then let go of the store.

        Cancelling first means an in-flight turn unwinds into a recorded
        failure rather than being abandoned mid-write. The projection stops
        before the store it reads through does, for the same reason.
        `detach_project` is safe to call whether or not anything is attached.

        Runs stop before turns do, and that order is the point: a run asked to
        stop finishes the round it is in, and a turn cancelled underneath it
        would make that round a recorded failure rather than the last one. The
        wait is bounded by whatever the in-flight turn takes.
        """
        await self.research.stop_all()
        await self.turns.cancel_all()
        await self.summaries.stop()
        await self.corpus.stop()
        await self.topics.stop()
        await self.service.close()
        await self.detach_project()
        # Every project this instance ever opened a graph for, not just the
        # one that happened to be attached -- `detach_project` above only
        # releases that one, and a read route can have opened others through
        # `graphs` directly without ever attaching them.
        await self.graphs.close_all()


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


def _extraction_model(injected: BaseChatModel | None) -> BaseChatModel:
    """The chat model knowledge extraction runs on, given what the caller passed.

    An injected model is handed back untouched. `build_application(model=...)`
    is how tests supply fakes, and a fake is not a `ChatOpenAI` -- it has no
    `extra_body` to set, and rebuilding one here would quietly point extraction
    at a real endpoint the test never asked for. Wrapping the injected model in
    a copy carrying `extra_body` would be no better: nothing guarantees the
    fake can be copied, and a caller who injects a model has said which model
    they want used.

    A model this project built for itself is a `ChatOpenAI` against
    `config.base_url()`, so extraction gets its own with thinking turned off --
    see `build_extraction_model`. The agent's model is deliberately left
    alone; only extraction is measured to be better off not reasoning.
    """
    return injected if injected is not None else build_extraction_model()


def build_application(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    context_mode: str | None = None,
    tracer: Tracer | None = None,
    approvals: ApprovalPort | None = None,
    extractions: ExtractionChannel | None = None,
    dispatches: DispatchesInFlight | None = None,
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
    # Extraction runs on its own model, not the agent's: it is the one job
    # here that is measurably better off not reasoning first.
    extraction_model = _extraction_model(model)
    mode = context_mode if context_mode is not None else config.context_mode()
    strategy, subagents, prompt_suffix = _context_parts(mode, resolved_model, system_prompt)
    resolved_policy = policy if policy is not None else AutonomyPolicy()

    # Opened before the tools below so the knowledge adapter can share this
    # connection's event store and snapshot store rather than opening its own
    # (BACKLOG B5: a second `SQLiteSnapshotStore` leaks a non-daemon thread).
    repository = EventStoreSessionRepository.open(resolved_path)

    # Two tools leave the process, and they are withheld differently because
    # there are two different things to withhold them with.
    #
    # `fetch` is registered unconditionally: there is no instance to leave
    # unconfigured, and a research agent that can see five snippets and never
    # read a page is not much of one. Its floor of `ask` is the switch instead
    # -- present and discoverable, but it cannot reach anything until a person
    # says so once. See `TOOL_FLOORS`.
    #
    # `web_search` keeps its configuration switch: an instance is a real thing
    # someone has to stand up, and "unset means absent" is a stronger promise
    # than any gate, so there is no reason to trade it for one.
    # One memo for both network tools and for every session this application
    # serves. Process-wide rather than per-session because `build_fetch_tool`
    # is called once here -- and correct at that scope for the same reason it
    # is safe: it holds only responses from public URLs, which are the same
    # bytes whoever asked. Nothing project-scoped may ever go in it.
    recall = Recall()
    tools: tuple[BaseTool, ...] = (build_fetch_tool(recall=recall),)
    prompt_suffix += FETCH_PROMPT

    searxng = config.searxng_url()
    if searxng is not None:
        tools += (build_search_tool(searxng, limit=config.searxng_results(), recall=recall),)
        prompt_suffix += SEARCH_PROMPT
    else:
        prompt_suffix += NO_SEARCH_CLAUSE

    if project_id is not None:
        # A `project_id=` at build time scopes the whole application to that
        # project, not just sessions started through `start_in_project` --
        # `create_session` on an application built this way still gets the
        # knowledge tools (the `_initial_project_id` path, attached at
        # `start()`), so its default prompt has to describe them too, the
        # same way `start_in_project`'s per-session prompt does. Otherwise a
        # session it creates has `remember` on the executor and no idea the
        # tool exists.
        prompt_suffix += KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT

    resolved_tracer = tracer if tracer is not None else build_tracer()
    # Built here rather than beside `summaries` below because `open_graph`
    # closes over it: the corpus tools are attached with a project, and the
    # thing they read has to exist by the time that callable is defined.
    corpus = CorpusRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # Same reasoning as `corpus`: `open_graph` closes over it, so the thing the
    # topic tools read has to exist by the time that callable is defined.
    topics = TopicRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )

    async def running_workflow(
        session: CodingSession,
    ) -> tuple[UUID, ProjectState, Preset] | None:
        """The workflow this session's run is under, or None if there is none.

        None is the answer for a session outside a project and for a project
        that never selected a workflow -- which is every project written before
        workflows existed. Those runs get exactly the agent they got before:
        no gate tool, no middleware, nothing to reason about.

        Folded off the `Project` aggregate on every turn rather than held
        anywhere, for the reason `_resolved_middleware` sets out at length: the
        checkpointer is per-turn, so the event log is the only place where
        "where does this run stand" survives, and it is deliberately the only
        place. A replay per turn is the price of not having two answers.

        Shared by the two callers below so they cannot disagree. A turn where
        the gate tool is bound but the stage filter is absent, or the reverse,
        would be a run gated by half a workflow -- and the failure would look
        like a model behaving oddly rather than like a wiring fault.
        """
        project_id = session.state.project_id
        if project_id is None:
            return None
        state = (await repository.projects.load(project_id)).state
        if state.preset_id is None:
            return None
        preset = PRESETS.get(state.preset_id)
        if preset is None:
            # A preset that was shipped when the run started and has since been
            # renamed or withdrawn. Gating on a preset we do not have would
            # mean inventing one; running ungated is at least the behaviour the
            # project had before it chose, and it is visible in the log.
            logger.warning(
                "project %s runs unknown workflow %s; no stage gate applied",
                project_id,
                state.preset_id,
            )
            return None
        if state.preset_version != preset.version:
            # Gated by what is installed, not by what was selected. Editing a
            # preset is expected -- they are content -- and refusing to run
            # would strand every project mid-flight on an edit. The event log
            # keeps `preset_version`, so a later reader can still tell which
            # revision each stage was actually decided under.
            logger.info(
                "project %s selected %s v%s; running under installed v%s",
                project_id,
                preset.id,
                state.preset_version,
                preset.version,
            )
        return project_id, state, preset

    async def workflow_tools(session: CodingSession) -> tuple[BaseTool, ...]:
        """`advance_stage`, for a run that has a workflow to advance through.

        Registered per turn rather than with the project's other tools, which
        is the awkward-looking half of this and the load-bearing half. A
        workflow is selected by `POST /api/projects/{id}/workflow`: it appends
        an event and returns, with no attachment to hang a tool registration
        off. Bound at attach time instead, the gate would be missing for the
        whole of the session that chose the workflow -- which is every session,
        the first time.

        Bound to one project through `ProjectWorkflow`, so the tool cannot be
        pointed at another run. The preset comes from the same fold the stage
        filter uses, so the stage the model is held to and the stage list the
        tool advances along are always the same list.
        """
        running = await running_workflow(session)
        if running is None:
            return ()
        project_id, _, preset = running
        return build_workflow_tools(
            ProjectWorkflow(repository.projects, project_id), preset=preset
        )

    async def turn_middleware(session: CodingSession) -> tuple[AgentMiddleware, ...]:
        """This turn's middleware: component feedback always, the stage gate if any.

        `ComponentFeedback` is unconditional because a component can appear in
        any markdown file the agent writes, workflow or no workflow, and a
        session driving no preset is exactly where nobody is watching the
        transcript closely enough to notice a malformed widget.

        `managed_tools_for` takes the union across *every* stage rather than
        the current stage's list, because the middleware is a denylist: the
        executor registers all of them once at agent creation -- `factory.py`
        rejects a tool that was not -- and the gate withdraws what this stage
        does not claim. Narrowing this to one stage would leave the next
        stage's tools permanently visible.

        `advance_stage` is subtracted from that union, which is the deliberate
        answer to "should the gate tool be available in every stage". It should.
        A stage is a gate because leaving it *requires a human*, not because
        the model cannot ask -- `TOOL_FLOORS` floors this tool at `ask`, so
        every crossing is an interrupt somebody has to answer, in every stage,
        including the ones whose preset declares no `gate` of its own. Hiding
        it per stage would buy nothing (the human is already in the way) and
        cost the run its only way forward: a stage that claims a tool list, as
        `hybrid.step1.framing` does, would be enterable and not leavable.

        Subtracted here rather than in `StageMiddleware` because the middleware
        takes `managed_tools` as an argument precisely so this decision belongs
        to the caller -- the mechanism is "hide what the stage does not claim",
        and which tools are exempt from that is policy. Doing it here also
        means the exemption survives a preset that names `advance_stage` in
        some stage's `tools`, which would otherwise pull it into the managed
        set and hide it from every stage that did not.

        The instructions are the stage's artifact block -- which files it owes,
        at which paths, with which frontmatter -- derived from the stage's own
        declared outputs, so a preset edit cannot leave the prompt describing
        files nothing looks for. `WORKFLOW_PROMPT` joins it because a bound
        tool nobody explained is a tool the model calls at the wrong moment:
        it says the gate asks a human, and that advancing is for when this
        stage's outputs exist, not for when the model has run out to say.
        """
        # Reads off the aggregate the tool just wrote through, so an `edit_file`
        # is validated against the document it produced rather than the
        # replacement it was given.
        base: tuple[AgentMiddleware, ...] = (
            ComponentFeedback(
                read=lambda path: session.state.files.get(path, {}).get("content")
            ),
            # In `base` rather than beside `StageMiddleware` below, because
            # `advance_stage` is bound whenever a workflow is running -- which
            # includes the arm where the stage is not one the preset defines
            # and no stage gate is applied at all. It is inert without a result
            # carrying `STAGE_ADVANCED`, so a session with no workflow pays a
            # scan of the trailing tool messages and nothing else.
            EndTurnOnStageAdvance(),
        )

        running = await running_workflow(session)
        if running is None:
            return base
        project_id, state, preset = running
        stage = current_stage_of(state, preset)
        if stage is None:
            logger.warning(
                "project %s is at stage %s, which %s does not define; no stage gate applied",
                project_id,
                state.current_stage,
                preset.id,
            )
            return base
        return (
            *base,
            StageMiddleware(
                stage,
                managed_tools=managed_tools_for(preset.stages) - {ADVANCE_STAGE_TOOL},
                instructions=(
                    stage_artifact_instructions(preset, stage)
                    + WORKFLOW_PROMPT
                    # Derived from this stage's declared outputs, so a stage
                    # writing source claims is told nothing about widgets and a
                    # stage writing assessment items is told which ones an
                    # assessment is made of. Empty for most stages, by design.
                    + component_guidance(stage.outputs)
                ),
            ),
        )

    async def gate_review(
        session: CodingSession, tool_name: str, args: dict
    ) -> GateReview | None:
        """Run the stage's checks before anyone is asked to let it go.

        Only for `advance_stage`. Every other gated tool is gated because it
        costs money or leaves the process, and there is nothing about a web
        search for a human to have found out beforehand; running a course
        review for one would be work nobody reads.

        The findings artifact is written straight onto the aggregate rather
        than through the agent's filesystem, because the agent is suspended
        inside an interrupt at this point and has no turn in which to write
        anything.

        **It is not visible to the reviewer while they decide, and neither are
        the artifacts they are deciding about.** `session.execute` appends to
        `uncommitted_events`; the only thing that writes to the store is
        `_save_turn`, at the *end* of the turn, and `DeepAgentTurnExecutor`
        holds no repository with which to do otherwise. `GET
        /api/sessions/{id}/files` loads the aggregate from the store, so
        everything this turn has written -- the stage's outputs and this report
        -- is invisible to that route until the turn finishes. This paragraph
        replaces a claim that the file was "in the log and in the viewer
        immediately", which was never true.

        What the reviewer actually gets at the interrupt is `gate_context`,
        carried inline on the `ApprovalRequest` and delivered over SSE: the
        findings, the counts, the checks that could not run. That is real
        evidence and it is why the gate is not blind. What it is missing is the
        artifacts themselves. Closing that gap is a visibility change (put the
        stage's files in the context) rather than a durability one, and it is
        deliberately not made here -- see the PR that added
        `EndTurnOnStageAdvance`, which records why committing mid-turn was
        rejected.

        The *model* does not see the report until its next turn rebuilds state
        from the aggregate. That is the right way round -- the report is for
        the reviewer, and a model that could read its own report mid-decision
        would be tempted to argue with it.

        A run whose project has no workflow, or whose stage the preset does
        not define, gets `None`: there is no stage to check, and inventing one
        to have something to report would be the gate making things up.
        """
        if tool_name != ADVANCE_STAGE_TOOL:
            return None
        running = await running_workflow(session)
        if running is None:
            return None
        _, state, preset = running
        stage = current_stage_of(state, preset)
        if stage is None:
            return None
        review = review_stage(preset, stage, session.state.files)
        path = findings_path(preset, stage)
        session.execute(
            WriteFile(path=path, file_data={"content": render_review(review, preset)})
        )
        return GateReview(context=gate_context(review, path), refusal=refusal(review))

    executor = DeepAgentTurnExecutor(
        resolved_model,
        subagents=subagents,
        tools=tools,
        policy=resolved_policy,
        approvals=approvals,
        middleware_provider=turn_middleware,
        tools_provider=workflow_tools,
        gate_reviewer=gate_review,
    )

    # The single owner of an open graph store per project: `open_graph` below
    # borrows from it rather than building its own, which is what lets a read
    # route see the same store extraction just wrote to instead of
    # a second one rebuilt independently and stale from the moment it exists.
    # One provider and one store for the process, not one per project.
    # `OpenAIEmbeddings` holds a connection pool and the vectors are tenant-
    # scoped inside the store, so a second set per project would buy isolation
    # that redstring already provides and pay for it in sockets. Built eagerly
    # rather than per `open_graph` so a misconfigured *name* -- the one failure
    # that does not need the network to detect -- surfaces at startup; the
    # endpoint itself is probed on first ingest, in the adapter.
    #
    # `None, None` when `AGENT_VECTOR_STORE=none`, which is the whole of
    # switching the feature off: nothing is constructed and nothing is probed.
    vector_store = build_vector_store(
        config.vector_store(), dimension=config.embedding_dimension()
    )
    embedding_provider = build_embedding_provider() if vector_store is not None else None

    graphs = ProjectGraphs(
        build_store=lambda: build_graph_store(config.graph_store()),
        rebuild=lambda store, target_project_id: rebuild_graph(
            store, feed=repository.store, project_id=target_project_id
        ),
    )

    async def open_graph(
        target_project_id: UUID,
    ) -> tuple[RedstringKnowledge, tuple[BaseTool, ...]]:
        """Build one project's `RedstringKnowledge` over its shared graph store.

        The store itself comes from `graphs`, which owns it for as long as
        the project stays open -- not just for the duration of this
        attachment. Raises before anything is returned if `graphs.open`
        fails -- an unreachable Neo4j or a replay `KnowledgeError` -- which is
        what lets `KnowledgeAttachment.attach` stay atomic: nothing here is
        handed back for it to wire in until the store has actually opened.
        Unlike the store this used to build for itself, a store that fails to
        open here is *not* closed on the way out: `graphs` is what decided to
        build it, and only `graphs` gets to decide it is done with it --
        closing a cache's handle out from under it on a failure it did not
        cause would leave the cache holding a closed store the next `open`
        would hand straight back out.
        """
        store = await graphs.open(target_project_id)
        knowledge = RedstringKnowledge(
            target_project_id,
            store=store,
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            provider=LangChainLlmProvider(extraction_model, model=config.model_name()),
            corpus=build_corpus_repository(
                repository.store, snapshot_store=repository.snapshot_store
            ),
            domain=config.knowledge_domain(),
            embeddings=embedding_provider,
            vector_store=vector_store,
        )
        # Both tool sets travel back through the one channel `KnowledgeAttachment`
        # already has. A second callable for the corpus would need its own copy of
        # the atomicity guarantee -- a failed attach leaves the executor's tools
        # untouched -- and two half-attached states are exactly what that
        # guarantee exists to rule out. The corpus reader needs nothing closed,
        # so `close_graph` stays about the graph.
        reader = ProjectCorpusReader(corpus, target_project_id)
        # The topic tools ride the same channel, for the reason the corpus
        # tools do: `KnowledgeAttachment` already carries the atomicity
        # guarantee that a failed attach leaves the executor's tools untouched,
        # and a second callable would need its own copy of it.
        topic_port = RepositoryTopics(
            build_topic_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            topics,
            target_project_id,
        )
        # Shadows the base `fetch` for as long as this project is attached --
        # see `_compose` in `knowledge_attachment.py`. It is the same tool
        # with one more place to look: this project's own sources, which is
        # the only lookup that can return something citable.
        project_fetch = build_fetch_tool(recall=recall, corpus=reader)
        return knowledge, (
            project_fetch,
            # The reporter is per-project and so is this closure, which is why
            # it is made here rather than passed in already bound. None when
            # nothing is listening: a build with no web layer has nobody to
            # tell, and `remember` is unchanged by its absence.
            *build_knowledge_tools(
                knowledge,
                report=extractions.reporter(target_project_id)
                if extractions is not None
                else None,
            ),
            *build_corpus_tools(reader),
            *build_topic_tools(topic_port, target_project_id),
        )

    async def close_graph(knowledge: RedstringKnowledge) -> None:
        """A no-op: detaching a project from one session no longer closes its store.

        Before `graphs` existed, this was the only thing that closed a graph
        store, so it closed the one `knowledge` held. Now the store outlives
        any single attachment -- `graphs` is what opened it and `graphs` is
        what gets to close it, on project delete or process shutdown. Closing
        it here too would pull it out from under the cache: `graphs` would
        still list the project as open, and the next `open` would hand back a
        store that no longer accepts calls instead of rebuilding a working one.
        """

    attachment = KnowledgeAttachment(
        executor,
        tools,
        open_graph=open_graph,
        close_graph=close_graph,
    )

    summaries = SessionSummaryRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    service = SessionService(
        repository,
        executor,
        summaries,
        repository.projects,
        default_system_prompt=system_prompt + prompt_suffix,
        context=strategy,
        # Resolved once and shared: whether this process exports traces is a
        # deployment decision, and the composition root is where deployment
        # decisions live. The projection gets the same instance, so a turn and
        # the read-model work it causes are read off one trace rather than two.
        tracer=resolved_tracer,
        # A session started in a project gets this appended to its prompt;
        # one started plainly does not, so it never hears
        # about tools it was not given.
        # `TOPICS_PROMPT` belongs here for the same reason the other three do,
        # and its absence was a plain oversight: `open_graph` attaches
        # `build_topic_tools` alongside the knowledge and corpus tools, so a
        # joined session has always *had* `open_topic` -- and was never told.
        # The comment beside the build-time suffix above already names this
        # exact failure ("no idea the tool exists") while claiming parity with
        # this line, which is what made the gap invisible.
        #
        # Visible from the outside as an autonomous run that stops on its first
        # round with `queue_empty` forever: the only thing that can put a topic
        # on the queue is the agent calling `open_topic`, the driver never opens
        # one itself, and nothing had told the agent the tool was there.
        knowledge_prompt=(
            KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT
        ),
        # The service owns the attachment: `/project use` calls
        # `service.attach_project` directly, so it lives where the REPL
        # already reaches rather than behind a second accessor on `Application`.
        attachment=attachment,
        # Learner progress rides the same log and the same snapshot table as
        # everything else, keyed by the session it belongs to. Wired here
        # rather than defaulted inside the service, because which store an
        # aggregate lands in is exactly the decision this root exists to make.
        progress=build_learner_progress_repository(
            repository.store, repository.publisher, snapshot_store=repository.snapshot_store
        ),
        # So `delete_project` can evict the deleted project's cached store --
        # the same `graphs` `open_graph` above borrows from, not a second
        # instance that would cache independently of the one attachment uses.
        graphs=graphs,
    )
    turns = TurnSupervisor(service)
    runs = build_auto_research_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )
    topic_repository = build_topic_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )

    def topic_reader(target_project_id: UUID) -> TopicReadPort:
        """This project's `TopicReadPort`, over the one repository above.

        Built per call rather than held, mirroring `ProjectCorpusReader`
        above: the project is bound at construction so no caller can pass a
        different one, and a call is cheap enough (three attribute reads and
        an object) that there is no reason to cache it.
        """
        return ProjectTopicReader(
            topics, topic_repository, topics.corpus_facts, target_project_id
        )

    async def start_run(
        run_id: UUID,
        run_project_id: UUID,
        session_id: UUID,
        budget: Budget | None,
        cancelled,
    ):
        """One autonomous run: a driver, bound to one session's turns.

        Built per run rather than once, because `run_round` closes over the
        session the rounds are turns on. The driver itself holds no state, so
        there is nothing to share by keeping one around.

        Rounds go through `turns` rather than straight to the service, which
        is what makes "one turn at a time per session" cover an autonomous run
        as well as a person typing: a `/turns` POST arriving mid-run is refused
        with the 409 it would get from any other second turn, rather than
        interleaving with a round.

        `read_only` is read from the policy rather than asserted. The default
        is a read-only run because `fetch` floors at `ask` and an unattended
        approval deadlocks -- but someone who has set `fetch` to `auto` has a
        run that can leave the process, and recording `read_only=True` over
        that would put a false claim in the audit trail of the one kind of run
        that most needs a true one. The policy is read here and never written,
        which is what keeps `TOOL_FLOORS` a floor rather than a suggestion.
        """
        return await AutoResearchDriver(
            runs,
            topic_repository,
            topics.queue,
            run_round=TopicRoundRunner(
                topic_repository,
                lambda prompt: turns.run(session_id, prompt),
            ),
            # The queue is a projection, so the look a round just recorded is
            # not in the table the next round reads until it catches up.
            # Without this the run is handed back the topic it has just
            # finished, which looks exactly like a loop that cannot learn.
            settle=topics.caught_up,
        ).run(
            run_project_id,
            session_id,
            budget=budget,
            run_id=run_id,
            cancelled=cancelled,
            autonomy_snapshot=resolved_policy.levels(),
            read_only=resolved_policy.level_for(FETCH_TOOL) != "auto",
        )

    research_supervisor = ResearchSupervisor(start_run, runs)
    # Built over the same `service` and `turns` a person's own turns run
    # through -- a seeding turn is a turn like any other, and `TopicSeeder`
    # joins and releases the project the same way `start_auto_research` does.
    topic_seeder = TopicSeeder(service, turns)
    # Same `service` and `turns` again: a dispatch turn is a turn like any
    # other. `topic_reader` is the same factory the read routes close over, so
    # the number in `/topics/<nn>-<slug>/` and the order the topic list renders
    # in cannot come from two different reads.
    dispatcher = TopicDispatcher(service, turns, topic_reader)
    # The same `service`, `turns` and `resolved_policy` again. The policy in
    # particular must be *this* instance's and not a copy: it is what decides
    # whether the runner asks at a boundary, and a second policy object would
    # let a run cross gates the operator had not relaxed -- which is the one
    # property `stage-boundaries.md` §4.4 insists no second mechanism may
    # decide. `approvals` is the same port the tool gate poses through, so a
    # reviewer sees one kind of request whichever route proposed the advance.
    stage_runner = StageRunner(
        service,
        turns,
        lambda target: ProjectWorkflow(repository.projects, target),
        approvals,
        resolved_policy,
    )
    # The same object the tools report through, not a second one: the roster's
    # "an extraction is running" and the pane's frames are two reads of one
    # buffer, and two instances would let them disagree.
    worker_roster = WorkerRoster(
        service,
        turns=turns,
        runs=research_supervisor,
        extractions=extractions,
        # Passed in rather than built here for `extractions`' reason: the
        # queue the routes enqueue into and the one the roster reads must be
        # the same object, and only the process that owns both can say so.
        dispatches=dispatches,
        # The same runner the `stage_runner` field exposes. A second instance
        # would hold its own in-flight dict and the dock would show nothing
        # while a stage was being driven -- the exact failure #79 fixed for
        # extractions by insisting on one buffer.
        stages=stage_runner,
        # The projection, not the service: `everywhere` needs session -> project
        # for the turns it finds, and asking the service would fold a session
        # per running turn to learn something a read-model column already says.
        summaries=SummaryProjects(summaries),
    )

    return Application(
        service=service,
        feed=LiveFeed(repository),
        turns=turns,
        context_mode=mode,
        summaries=summaries,
        corpus=corpus,
        topics=topics,
        graphs=graphs,
        topic_readers=topic_reader,
        topic_repository=topic_repository,
        research=research_supervisor,
        topic_seeder=topic_seeder,
        dispatcher=dispatcher,
        stage_runner=stage_runner,
        workers=worker_roster,
        policy=resolved_policy,
        _initial_project_id=project_id,
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
