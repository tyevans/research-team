"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

import functools
import logging
import random as random
from collections.abc import Sequence
from uuid import UUID

# Imported for its side effect as much as its names: redstring registers its
# event types at import time, and the session store may hold them -- the
# `Document` and `Consolidation` streams live in the same SQLite file as
# sessions. A read that meets a `DocumentExtracted` without this import raises
# `EventTypeNotFoundError`, including on the "no project at all" path, where
# nothing else would have pulled redstring in.
import httpx
import redstring.events  # noqa: F401
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from redstring import SlidingWindowChunker
from redstring.llm.adapters.langchain import LangChainLlmProvider

from research_team.application import (
    DEFAULT_SYSTEM_PROMPT,
    ApprovalPort,
    AutonomyPolicy,
    DispatchesInFlight,
    ExtractionChannel,
    KnowledgeAttachment,
    LiveFeed,
    ProjectGraphs,
    SessionService,
    TurnActivityBuffer,
    WorkerRoster,
)
from research_team.application.dialogue.ask import AskService, ConversationRegistry
from research_team.application.dialogue.socratic import (
    DialogueRegistry,
    SocraticDialogueService,
)
from research_team.application.knowledge import (
    KnowledgeError,
    SourceRef,
    source_id_for_url,
)
from research_team.application.research.corpus_editing import CorpusEditor
from research_team.application.research.document_extraction import DocumentExtractor
from research_team.application.research.perception import MediaPerceiver, PerceptionPort
from research_team.application.research.topics import TOPICS_PROMPT
from research_team.application.tenancy.grants import GrantRegistry
from research_team.domain import Session, SessionPurpose
from research_team.domain.research.media_proposals import MediaProposals
from research_team.infrastructure import config
from research_team.infrastructure.agent import (
    DeepAgentTurnExecutor,
    build_embedding_provider,
    build_extraction_model,
    build_model,
)
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.component_feedback import ComponentFeedback
from research_team.infrastructure.agent.corpus_tools import (
    CORPUS_PROMPT,
    build_corpus_tools,
)
from research_team.infrastructure.agent.fetch import (
    FETCH_CORPUS_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.fetch_media import build_fetch_media_tool
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
    build_knowledge_tools,
)
from research_team.infrastructure.agent.research_budget import ResearchBudget
from research_team.infrastructure.agent.search import (
    build_search_tool,
)
from research_team.infrastructure.agent.search_middleware import SearchAttemptsMiddleware
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.agent.topic_tools import (
    RepositoryTopics,
    build_topic_tools,
)
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.entity_cards import index_cards
from research_team.infrastructure.knowledge.entity_embeddings import (
    refresh_project_embeddings,
)
from research_team.infrastructure.knowledge.markdown_table_chunker import MarkdownTableChunker
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.stores import (
    build_card_vector_store,
    build_chunk_store,
    build_graph_store,
    build_vector_store,
)
from research_team.infrastructure.perception.readeverything_adapter import (
    build_perception_adapter,
)
from research_team.infrastructure.persistence import (
    EventStoreSessionRepository,
    build_ask_conversation_repository,
    build_corpus_repository,
    build_judgements_repository,
    build_learner_progress_repository,
    build_research_run_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.event_store import (
    build_course_authoring_run_repository,
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.telemetry import build_tracer
from research_team.wiring import (
    _PARTIAL_BUILD_RESOURCES,
    BuiltStores,
    BuiltTools,
    ContentPipeline,
    LazyAsyncResource,
    _CatalogFeatureRunner,
    _close_every_step,
    _context_parts,
    _CourseRunner,
    _extraction_model,
    _LazyArtStore,
    _LazyBlurbCache,
    _LazyCandidateArtStore,
    _LazyOutlineCache,
    _LazyProjectSummaries,
    _partial_build_teardown,
    _RealizedCourses,
    _run_detached,
    _subagents_for,
    _swallowing,
    build_ask_service,
    build_catalog_services,
    build_content_pipeline,
    build_corpus_editor,
    build_curation_tools,
    build_document_extractor,
    build_media_acquisition,
    build_media_perceiver,
    build_project_services,
    build_session_service,
    build_socratic_service,
    build_stores,
    build_supervisor_roster,
    build_tools,
)
from research_team.wiring.application import Application

__all__ = [
    "_PARTIAL_BUILD_RESOURCES",
    "Application",
    "AskService",
    "BuiltStores",
    "BuiltTools",
    "ContentPipeline",
    "ConversationRegistry",
    "CorpusEditor",
    "DeepAgentAskExecutor",
    "DeepAgentSocraticExecutor",
    "DialogueRegistry",
    "DocumentExtractor",
    "EventStoreSessionRepository",
    "LazyAsyncResource",
    "MediaPerceiver",
    "SocraticDialogueService",
    "_CatalogFeatureRunner",
    "_CourseRunner",
    "_LazyArtStore",
    "_LazyBlurbCache",
    "_LazyCandidateArtStore",
    "_LazyOutlineCache",
    "_LazyProjectSummaries",
    "_RealizedCourses",
    "_close_every_step",
    "_context_parts",
    "_extraction_model",
    "_partial_build_teardown",
    "_run_detached",
    "_subagents_for",
    "_swallowing",
    "build_application",
    "build_ask_conversation_repository",
    "build_ask_service",
    "build_catalog_services",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_corpus_repository",
    "build_curation_tools",
    "build_document_extractor",
    "build_learner_progress_repository",
    "build_media_perceiver",
    "build_service",
    "build_socratic_dialogue_repository",
    "build_socratic_service",
    "build_stores",
    "build_tools",
    "random",
]

logger = logging.getLogger(__name__)


def _build_application(
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
    grants: GrantRegistry | None = None,
    activity: TurnActivityBuffer | None = None,
    perception: PerceptionPort | None = None,
    media_http_client: httpx.AsyncClient | None = None,
    interaction_db_path: str | None = None,
) -> Application:
    """Wire everything over one event store.

    Creates no session: which session a caller is working on is the caller's
    business, and one application serves as many of them as ask.

    The repository backs both ports -- it is one connection to one log, read
    two ways -- so the service and the feed are always looking at the same
    events, with no chance of a live view lagging a different database.

    `grants` accepts an existing `GrantRegistry` for the same reason
    `approvals` does: `web.py` builds a `WebApprovals(grants=...)` *before*
    calling this function, and the two must share one registry or the gate
    and the tool would disagree about the same call -- the silent-failure
    mode this feature is most exposed to. `None` builds a fresh one, which is
    correct for the REPL (no `WebApprovals` to share with) and for every test
    that does not care.

    `activity` is the buffer every turn's provisional content flows through,
    and it arrives here for the same reason `approvals` does: `web.py` builds
    one `TurnActivity` and both halves of the channel must be that instance.
    The supervisor writes into it; the catch-up route reads out of it. `None`
    is the REPL's case and most tests' -- turns then run unbuffered, which is
    what happened on every path but the web one before this was wired.

    `perception` accepts an existing `PerceptionPort` for the same reason
    `approvals` does, and for one reason unique to this port: `build_perception_
    adapter()` builds a `ReadEverythingPerception`, whose *construction* touches
    no network -- capabilities are declared from configuration, not probed --
    but whose first `perceive()` does. `None` is correct for the REPL and for
    every test that does not perceive anything; a test that does must inject a
    fake here, exactly as the no-network guard tests in this module do, or it
    reaches whatever `AGENT_VISION_MODEL`/`AGENT_TRANSCRIBER_URL` happen to be
    set to in the environment the suite runs in.

    `media_http_client` accepts an existing `httpx.AsyncClient` for
    `MediaAcceptWorker`'s downloads, for the same reason `perception` does: a
    test hands in one built over `httpx.MockTransport`
    (`tests/application/test_media_acquisition.py`'s own `_client` helper) so
    accepting a proposal never reaches the network. `None` builds a real
    client, owned by this `Application` and closed in `close()`.
    """
    resolved_path = db_path if db_path is not None else config.default_db_path()
    resolved_interaction_path = (
        interaction_db_path
        if interaction_db_path is not None
        else config.interaction_db_path()
    )
    resolved_model = model if model is not None else build_model()
    # Extraction runs on its own model, not the agent's: it is the one job
    # here that is measurably better off not reasoning first.
    extraction_model = _extraction_model(model)
    mode = context_mode if context_mode is not None else config.context_mode()
    strategy, subagents, prompt_suffix = _context_parts(mode, resolved_model, system_prompt)
    resolved_policy = policy if policy is not None else AutonomyPolicy()
    resolved_grants = grants if grants is not None else GrantRegistry()
    # Synchronous, deliberately -- see `build_perception_adapter`'s own
    # docstring for why `build_application` is not `async def` for this one
    # port. Resolved here, beside the other three optional-port defaults,
    # rather than beside `document_extractor` below, so every override this
    # function accepts is decided in one place.
    resolved_perception = perception if perception is not None else build_perception_adapter()

    authoring_rounds = config.authoring_research_rounds()
    searxng = config.searxng_url()

    built_tools = build_tools(
        searxng_url=searxng,
        build_fetch=build_fetch_tool,
        build_search=build_search_tool,
    )
    tools = built_tools.tools
    recall = built_tools.recall
    pages = built_tools.pages
    search_attempts = built_tools.search_attempts
    prompt_suffix += built_tools.prompt_suffix

    media_curation_text, media_curation_search = build_curation_tools(
        extraction_model,
        searxng_url=searxng,
    )

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

    stores = build_stores(
        resolved_path=resolved_path,
        resolved_interaction_path=resolved_interaction_path,
        resolved_tracer=resolved_tracer,
    )
    repository = stores.repository
    corpus = stores.corpus
    blob_store = stores.blob_store
    topics = stores.topics
    settings_deps = stores.settings_deps
    effective_settings = stores.effective_settings
    definition_invalidation = stores.definition_invalidation
    ontology = stores.ontology
    media_proposals = stores.media_proposals
    asks = stores.asks
    dialogues = stores.dialogues
    users = stores.users
    user_recorder = stores.user_recorder
    authoring = stores.authoring
    interaction_store = stores.interaction_store
    interaction_log = stores.interaction_log
    interaction_recorder = stores.interaction_recorder
    tenants = stores.tenants
    authorizer = stores.authorizer
    summaries = stores.summaries
    catalog_runner = stores.catalog_runner
    blurb_cache = stores.blurb_cache
    art_store = stores.art_store
    project_summaries = stores.project_summaries
    candidate_art_store = stores.candidate_art_store
    outline_cache = stores.outline_cache
    course_runner = stores.course_runner

    async def granted_tools(session: Session) -> tuple[BaseTool, ...]:
        """A grant-bound `fetch`, for a session `resolved_grants` holds one for.

        Resolved per turn, from the one `GrantRegistry` this build shares
        with the approval gate (`interrupt_config`, below) and the driver
        that registers a run's grant when it starts (`start_run`) -- three
        consumers of one instance, which is the whole of what keeps the gate
        and this tool from disagreeing about the same call. Two registries
        would let a run's grant exist for the gate and not for the tool, or
        the reverse, and every unit test would still pass; see
        `application/grants.py` and the note beside `resolved_grants` above.

        `None` from `resolved_grants.get` means this session is not a
        registered run's session at all -- a person's own turn, or a run
        that has already stopped -- and the answer is nothing, leaving
        `fetch` (or, once a project is attached, `project_fetch`) exactly as
        it was. Shadowing here with an ungranted, grant-bound tool would turn
        off redirect-following and add a spend check to a session that was
        never a party to any of this.

        A *registered* session with an empty grant still gets one: an empty
        `FetchGrant` covers no host, so nothing new becomes reachable, but
        the tool built here also disables redirect-following for every call
        it makes (`fetch.py`'s `grant is not None` branch) -- a property an
        unattended run should have whether or not a person actually granted
        it hosts, not only once they do.

        Built with this project's corpus reader, mirroring `project_fetch`
        below -- otherwise a covered fetch under a grant would stop finding
        pages this project already has, for the whole time a grant is
        attached, which is a regression `_compose`'s shadowing would otherwise
        hide until someone noticed stale corpus reads.

        **The reader and the keeper key off `session.state.project_id` and
        nothing else.** They once came out of a fold that also required the
        project to have selected a preset, which reads as harmless and is not:
        it silently made both conditional on that selection, so a run on a
        project that had made none fetched with no corpus and saved nothing.
        A fetch is a fetch on the strength of the project alone.
        """
        grant = resolved_grants.get(session.aggregate_id)
        if grant is None:
            return ()
        project_id = session.state.project_id
        return (
            build_fetch_tool(
                recall=recall,
                corpus=(
                    ProjectCorpusReader(corpus, project_id, blob_store)
                    if project_id is not None
                    else None
                ),
                pages=pages,
                grant=grant,
                keep=_keeper(project_id) if project_id is not None else None,
            ),
        )

    def _keeper(project_id: UUID):
        """Save a fetched page to `project_id`'s corpus, without extracting it.

        Built here and nowhere else, which is what makes automatic saving a
        property of the *unattended run* rather than of fetching. This closure
        is only reached past `granted_tools`' `grant is None` check, and a
        registered grant is already this codebase's definition of a session
        nobody is watching (`GrantRegistry.is_unattended`). A person's own
        fetches keep the existing arrangement, where saving is a judgement the
        model makes with `remember_page` and `KNOWLEDGE_PROMPT` tells it not to
        save everything it happened to look at. Nobody is there to make that
        judgement in a run, and a page not saved before the round ends is gone.

        **`store_source`, not `ingest`.** An ingest is store-extract-
        consolidate and runs for minutes; calling it here would put that
        inside every `fetch`, and multiply extraction load by every page read
        rather than every page kept. The text is what cannot be recovered
        later -- the graph can always be built from it, by a `remember_page`
        on a page that proves to matter or by `/rebuild` -- so this saves the
        irrecoverable half at seconds rather than minutes and leaves the rest
        to a decision made with more information than "the page loaded".

        **The `source_id` is derived from the url, not the url.** This used to
        read "the url is the `source_id`", on the reasoning that the url is
        already what the page is and a prettier id would invent identity. The
        argument is sound and the consequence was not: a url contains `/`,
        `{source_id}` is one path segment, and uvicorn decodes the path before
        Starlette routes it -- so every per-source route 404'd for every page
        this closure ever kept. See `source_id_for_url` for the measurement.

        The cost of deriving it is that the model no longer knows the id from
        having typed the url, and `link_source` does not check that the id it
        is given exists -- so a model citing the url would write a dangling
        link, silently. `keep` returns the id for that reason and `fetch` puts
        it in the citation block; that return value is not decoration, it is
        what keeps the cite-immediately property the old id had for free.

        A later `remember_page` stores a second record of the same bytes, which
        `_store_document` allows deliberately -- worth knowing, since here it is
        one URI under two ids rather than the two-URIs case that rule was
        written for. `remember_page` now derives its id the same way, so the
        two ids agree and the second record is the same document rather than a
        differently-named one.
        """

        async def keep(url: str) -> str | None:
            retained = pages.get(url)
            # The attachment is process-wide and last-join-wins (see the web
            # layer's join), so `current` may belong to a project that is not
            # this run's. Without the guard a run's pages would land in
            # whichever project joined most recently -- silently, and visible
            # only as documents in the wrong corpus.
            knowledge = attachment.current
            if retained is None or knowledge is None:
                return None
            if attachment.attached_project_id != project_id:
                return None
            source_id = source_id_for_url(url)
            try:
                await knowledge.store_source(
                    SourceRef(
                        source_id=source_id,
                        text=retained.text,
                        uri=retained.uri,
                        title=retained.title,
                        published_at=retained.published_at,
                        fetched_at=retained.fetched_at,
                    )
                )
            except KnowledgeError:
                # Logged, not raised, and not reported to the model either.
                # The read succeeded and is about to be shown; a failed corpus
                # copy is worth less than the read, and a note about it in the
                # tool result would spend the model's attention on something it
                # did not ask for and cannot fix.
                logger.warning(
                    "could not keep %s for project %s", url, project_id, exc_info=True
                )
                # None on failure, so `fetch` cites nothing rather than an id
                # the corpus does not hold. The alternative -- returning the id
                # regardless -- would hand the model a citation that resolves to
                # a document the store just refused, which is the dangling link
                # this return value exists to prevent.
                return None
            return source_id

        return keep

    async def turn_tools(session: Session) -> tuple[BaseTool, ...]:
        """Everything this turn adds on top of the registered set.

        One source today, and still a seam rather than `granted_tools` passed
        straight to the executor: `_compose`'s by-name shadowing is what
        decides a collision between two per-turn providers, and the place that
        rule is applied is the place a second provider gets added.
        """
        return await granted_tools(session)

    async def turn_middleware(session: Session) -> tuple[AgentMiddleware, ...]:
        """This turn's middleware.

        `ComponentFeedback` is unconditional because a component can appear in
        any markdown file the agent writes, and a session nobody is watching
        closely is exactly where a malformed widget goes unnoticed.

        Resolved per turn rather than once at build, because the executor
        outlives any one turn's answer and a provider consulted once would
        pin the first turn's middleware onto every turn after it.
        """
        # Reads off the aggregate the tool just wrote through, so an `edit_file`
        # is validated against the document it produced rather than the
        # replacement it was given.
        return (
            ComponentFeedback(
                read=lambda path: session.state.files.get(path, {}).get("content")
            ),
            # Only when `search_attempts` is not `None` -- the same switch
            # that decided whether `web_search` was registered at all.
            # Installing this unconditionally would reset a counter that
            # exists in every build, including ones with no search tool to
            # bound, which is harmless today but asserts a dependency this
            # build does not have.
            *(
                (SearchAttemptsMiddleware(search_attempts),)
                if search_attempts is not None
                else ()
            ),
            # Authoring only, and on the purpose rather than on anything about
            # the turn -- `_subagents_for`'s reason exactly: a purpose is fixed
            # when the session starts, where a course directory appears partway
            # through phase 1 and would give phase 1 a different budget from
            # phase 2. Built fresh here on every pass, which is what resets the
            # count between phases; see `ResearchBudget` for why that is a
            # property of the wiring rather than of the class.
            *(
                (ResearchBudget(rounds=authoring_rounds),)
                if session.state.purpose is SessionPurpose.COURSE_AUTHORING
                and authoring_rounds > 0
                else ()
            ),
        )

    # Shared by the turn executor, the ask executor, `document_extractor`,
    # `editor` and `perceiver`: all of them read one project's corpus the same
    # way, and separate lambdas would be separate places a future change to how
    # a reader is built could drift. Defined here rather than beside its first
    # user below because the executors above it need it too.
    corpus_readers = lambda target_project_id: ProjectCorpusReader(  # noqa: E731
        corpus, target_project_id, blob_store
    )

    async def turn_subagents(session: Session) -> Sequence[dict]:
        """This turn's roster -- see `_subagents_for` for the choice it makes.

        A thin `async def` around a pure function, matching how `turn_tools`
        above is wired: the seam is async because the other providers are, not
        because anything here awaits.
        """
        return _subagents_for(session, subagents)

    async def turn_model(session: Session) -> BaseChatModel | None:
        """Which model answers this turn, resolved from its project.

        `None` for a session attached to no project, and for a build whose
        caller injected a model: the executor then uses the one it was
        constructed with, which is the process answer and the fake a test
        handed in. An injected model is a caller saying which model they want
        used -- `_extraction_model` refuses to second-guess the same statement
        for the same reason.

        This is the seam that makes the settings page's `Models` group reach a
        turn at all. `build_model()` above answers for the *process* and runs
        once, so before this the agent's model, endpoint and key were fixed at
        startup: a value saved against a project stored fine, resolved fine
        through `/api/settings/resolved`, and was read by nothing -- which is
        `application/effective.py`'s "the whole scoped store is decorative",
        arrived at through the one path that had no bundle.

        Per turn rather than per session, matching `turn_tools` and
        `turn_middleware`: the executor outlives any one turn, and a provider
        consulted once would pin the first turn's endpoint onto every turn
        after it -- including the turn right after somebody fixed a bad URL.
        Resolution is a dict lookup until a write bumps the revision, so the
        cost of asking every time is an await and a comparison.
        """
        if model is not None:
            return None
        project_id = session.state.project_id
        if project_id is None:
            return None
        return build_model(await effective_settings.research(project_id))

    executor = DeepAgentTurnExecutor(
        resolved_model,
        subagents=subagents,
        tools=tools,
        policy=resolved_policy,
        approvals=approvals,
        middleware_provider=turn_middleware,
        tools_provider=turn_tools,
        subagents_provider=turn_subagents,
        model_provider=turn_model,
        # The same registry `turn_tools` (via `granted_tools`) and `start_run`
        # (below) consult -- see `resolved_grants`'s own note for why there
        # is exactly one instance and what two would cost.
        grants=resolved_grants,
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
    # `None` everywhere when `AGENT_VECTOR_STORE=none`, which is the whole of
    # switching the feature off: nothing is constructed and nothing is probed.
    #
    # The *store* is no longer built here, and that is not a tidy-up.
    # `PgVectorStore.connect` is a coroutine which awaits `asyncpg.create_pool`
    # -- unlike `Neo4jGraphStore.connect`, which is an ordinary method building
    # a lazy driver -- and this function is synchronous, so building it here
    # produced an un-awaited coroutine that was passed onwards as if it were a
    # store. `ProjectGraphs` owns the open instead, because `open` is the first
    # `await` on the path to the store being used; the config is still *read*
    # here, so `AGENT_VECTOR_STORE=chroma` is still refused at startup rather
    # than at the first project open.
    vector_kind = config.vector_store()
    embedding_dimension = config.embedding_dimension()

    async def open_vector_store():
        return await build_vector_store(vector_kind, dimension=embedding_dimension)

    # The provider stays eager: it needs no network to build, and a
    # misconfigured model *name* is the one embedding failure that can be
    # caught at startup. The endpoint itself is probed on first ingest, in the
    # adapter.
    embedding_provider = (
        build_embedding_provider() if vector_kind != config.NO_VECTOR_STORE else None
    )

    graphs = ProjectGraphs(
        build_store=lambda: build_graph_store(config.graph_store()),
        rebuild=lambda store, target_project_id, **rebuild_kwargs: rebuild_graph(
            store, feed=repository.store, project_id=target_project_id, **rebuild_kwargs
        ),
        open_vector_store=open_vector_store,
        # Taken from the provider rather than from `config.embedding_model()`,
        # so the name the fold filters on is the name the writer stamps on the
        # event. Two reads of the same setting is how those come to disagree,
        # and a fold filtering on a name nothing writes is a vector store that
        # silently stays empty.
        embedding_model=embedding_provider.model if embedding_provider is not None else None,
        # In-memory unconditionally, even where the consolidation store is
        # pgvector. Card embeddings are folded from `EntitiesEmbedded` at open
        # exactly as chunks are folded from `DocumentChunked`, so the store is
        # derived and losing it costs a replay rather than data -- which is the
        # argument `build_chunk_store` already makes for the corpus. A second
        # pgvector table would buy durability the log already provides and cost
        # a schema, a DSN and a width to keep in step.
        build_card_vectors=(
            (lambda: build_card_vector_store(dimension=embedding_dimension))
            if embedding_provider is not None
            else None
        ),
        # Same `embedding_dimension` read above for the vector store, not a
        # second `config.embedding_dimension()` call: a corpus and the vector
        # store built from two separate reads could disagree if the env
        # changed between them, and `build_chunk_store`'s docstring is
        # explicit that a corpus built under one width can't accept vectors
        # of another without a rebuild.
        build_chunk_store=lambda: build_chunk_store(
            config.chunk_store(), dimension=embedding_dimension
        ),
        # No config switch and no `kind`: the co-mention index is three fields
        # per passage with no backend to choose, folded from the same
        # `DocumentChunked` events the corpus is. Unconditional for the reason
        # `build_card_vector_store` is in-memory unconditionally -- it is
        # derived, so having it costs a fold and not a decision. Unlike the
        # corpus it does **not** honour `AGENT_CHUNK_STORE=none`: that setting
        # turns off holding passage *text*, which this does not hold.
        build_co_mentions=CoMentionIndex,
        # Cards are chunked with the same settings as the quotable corpus, and
        # for a different reason than symmetry: a card is short, so the window
        # almost never fires, and matching the corpus keeps one number to
        # reason about instead of two that happen to agree.
        index_cards=lambda *, graph, cards, tenant_id: index_cards(
            graph=graph,
            cards=cards,
            tenant_id=tenant_id,
            chunker=SlidingWindowChunker(default_chunk_size=1000, default_overlap=500),
        ),
    )

    async def reembed_project(target_project_id: UUID) -> int:
        """Re-embed every entity in one project, from the graph as it stands.

        The repair route's engine. Assembles a card per canonical entity,
        embeds them, appends one `EntitiesEmbedded` and folds it straight into
        the project's card vector store -- so the effect is visible on the next
        projection rather than only after the next restart.

        Returns 0 rather than raising when embeddings are off, when the project
        has no entities, or when the provider declines: the route reports the
        number, and a build with `AGENT_VECTOR_STORE=none` should answer "0
        embedded" rather than an error every caller has to special-case.

        The event is appended *before* the store is written. Both orders leave
        a window, and this is the one whose failure is recoverable: an append
        that lands with no upsert is corrected by the next project open, while
        an upsert that lands with no append is a store holding vectors the log
        cannot reproduce -- which is the exact state this whole change exists
        to end.
        """
        if embedding_provider is None:
            return 0
        store = await graphs.open(target_project_id)
        card_vectors = graphs.card_vectors(target_project_id)
        if card_vectors is None:
            return 0
        return await refresh_project_embeddings(
            graph=store,
            provider=embedding_provider,
            event_store=repository.store,
            vectors=card_vectors,
            tenant_id=target_project_id,
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
        # The one place a background run picks up its project's settings.
        # `open_graph` is on the path of every ingest, every re-extraction and
        # every catalog sweep, and it is already parametrised by the project
        # id -- which is exactly why resolution keys on the id here rather
        # than on a request that most of those callers never had.
        #
        # Resolved per open, not per process. That is what makes a setting
        # saved through the API reach the *next* run: the bundle is cached on
        # `(project, revision)` and the stores bump the revision on write, so
        # this await is a dict lookup until somebody changes something and a
        # fresh resolve immediately after they do.
        settings = await effective_settings.extraction(target_project_id)
        # A caller that injected a model has said which model they want used,
        # and a fake has no endpoint to repoint -- see `_extraction_model`,
        # which makes the same call for the same reason. Everything else gets
        # a client built against this project's resolved model, endpoint and
        # credential, which is the whole point of the branch.
        project_extraction_model = (
            extraction_model if model is not None else build_extraction_model(settings)
        )
        knowledge = RedstringKnowledge(
            target_project_id,
            store=store,
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            # The name redstring reports and prompts against, matched to the
            # client beside it -- one field on `ExtractionSettings` rather than
            # two reads, because two reads of one setting is how a label comes
            # to name a model the run was not made on.
            provider=LangChainLlmProvider(project_extraction_model, model=settings.model),
            # `repository.publisher`, like every other repository built here,
            # and it was the one that did not have it. The corpus read model
            # follows the log through this bus, so without it a `remember`
            # appended `CorpusDocumentStored` and woke nothing: the event was
            # in the log, `topic_corpus_facts` had it (that repository
            # publishes), and `corpus_documents` stayed empty for the life of
            # the process -- which is "Documents" listing nothing while
            # research is visibly fetching pages. Not caught by a signature:
            # `event_publisher` is optional and defaults to None, so the wrong
            # wiring is the quiet one. See
            # `tests/integration/test_corpus_publishing.py`.
            corpus=build_corpus_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            # Same three arguments as the corpus, including the publisher, for
            # the reason the comment above gives: `event_publisher` is optional
            # and defaults to None, so the wrong wiring is the silent one.
            judgements=build_judgements_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            domain=settings.knowledge_domain,
            embeddings=embedding_provider,
            # `graphs.vectors()` rather than a captured store: `graphs.open`
            # above has already opened it, so this is a cached attribute read,
            # and routing both through the same owner is what keeps "the store
            # whose schema was ensured" and "the store this adapter writes to"
            # the same object.
            vector_store=await graphs.vectors(),
            # Per project, unlike the one above, and folded from the log at
            # the `graphs.open` two lines up -- so this is the store that
            # already holds every card embedding this project has recorded,
            # not a fresh one this ingest would start filling from empty.
            card_vector_store=graphs.card_vectors(target_project_id),
            concurrency=settings.concurrency,
            consolidation_batch=settings.consolidation_batch,
            # One chunker per project adapter rather than one for the process.
            # `SlidingWindowChunker` holds only its three numbers -- no buffer,
            # no state carried between `chunk` calls -- so sharing one would
            # save an object and buy nothing, while making the size look like
            # a process-wide fact when it is a per-adapter argument.
            #
            # Overlap and the boundary flags are left at redstring's defaults:
            # only the size is ours to choose, and passing the others would
            # freeze values we have no reason to hold against upstream's.
            # Wrapped so a chunk of table rows reaches the model with the
            # header naming its columns; without it, every chunk after the
            # first of a long table is rows whose cells mean nothing. This
            # does not change the chunk size -- `MarkdownTableChunker` makes
            # no boundary decisions, it only prepends a header the delegate's
            # cut left behind -- but a header-carrying chunk does exceed
            # `extraction_chunk_size` by the header's length. See that
            # module's docstring for why that was preferred to shrinking the
            # budget, and for the measurement.
            chunker=MarkdownTableChunker(
                SlidingWindowChunker(default_chunk_size=settings.chunk_size)
            ),
            # `graphs.chunks(...)`, not a second `build_chunk_store()` call:
            # `graphs.open` above already built this project's chunk store and
            # folded it in the same replay pass as the graph (see
            # `ProjectGraphs.open`), and a second store built here would be
            # empty. Indexing would write into it, replay would keep filling
            # the *other* one, and every read downstream would silently see
            # an empty corpus -- the exact failure this call is here to rule
            # out rather than the one it happens to avoid. `None` when
            # `AGENT_CHUNK_STORE=none`, matching `ProjectGraphs.chunks`'s own
            # None-when-off return.
            chunks=graphs.chunks(target_project_id),
            # `graphs.cards(...)`, for `chunks`' reason: `graphs.open` above
            # already built and filled this project's card store, and a second
            # one built here would be empty -- every ingest would re-card into
            # a store nothing reads while the store the reader holds stayed at
            # whatever `open` left. `None` when cards are off.
            cards=graphs.cards(target_project_id),
            # Where this ingest's entity links land live. They reach the log
            # either way -- `build_graph` records the chunking whenever it has
            # an event store -- so this is about the *current* session seeing
            # its own passages rather than about durability.
            # `graphs.co_mentions(...)` for `chunks`' reason: `open` already
            # folded this one, and a second built here would be written to by
            # ingest while every reader held the other.
            co_mentions=graphs.co_mentions(target_project_id),
        )
        # Both tool sets travel back through the one channel `KnowledgeAttachment`
        # already has. A second callable for the corpus would need its own copy of
        # the atomicity guarantee -- a failed attach leaves the executor's tools
        # untouched -- and two half-attached states are exactly what that
        # guarantee exists to rule out. The corpus reader needs nothing closed,
        # so `close_graph` stays about the graph.
        reader = ProjectCorpusReader(corpus, target_project_id, blob_store)
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
        project_fetch = build_fetch_tool(recall=recall, corpus=reader, pages=pages)
        # Unlike `project_fetch` above, `fetch_media` has no ungranted,
        # project-less form to shadow: `fetch` can run and simply not save
        # (`_keeper` below is the thing that decides that), but a
        # `fetch_media` that cannot store what it downloads is the exact
        # defect this tool was built to fix -- see `build_fetch_media_tool`'s
        # own refusal. So it exists only from here, once a project is
        # attached, rather than being registered unconditionally alongside
        # the base `fetch` in `tools` above and reaching for a project it
        # might not have.
        #
        # `editor` and `resolved_media_http_client` are both closed over from
        # the outer `build_application` scope, defined further down in this
        # function (`editor` beside `document_extractor`,
        # `resolved_media_http_client` beside `media_accept_worker`) --
        # ordinary in a nested `async def`, since Python resolves a closure's
        # free variables at call time, and `open_graph` is never called until
        # `build_application` has finished assembling both. Reusing the
        # worker's own client rather than building a second one is what
        # keeps "the connection pool a model's direct fetch uses" and "the
        # one an accepted proposal's download uses" the same pool, not two
        # that happen to agree on configuration today.
        fetch_media = build_fetch_media_tool(
            client=resolved_media_http_client,
            editor=editor,
            project_id=target_project_id,
        )
        return knowledge, (
            project_fetch,
            fetch_media,
            # The reporter is per-project and so is this closure, which is why
            # it is made here rather than passed in already bound. None when
            # nothing is listening: a build with no web layer has nobody to
            # tell, and `remember` is unchanged by its absence.
            *build_knowledge_tools(
                knowledge,
                report=extractions.reporter(target_project_id)
                if extractions is not None
                else None,
                pages=pages,
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

    session_wiring = build_session_service(
        repository=repository,
        executor=executor,
        summaries=summaries,
        system_prompt=system_prompt,
        prompt_suffix=prompt_suffix,
        context=strategy,
        tracer=resolved_tracer,
        attachment=attachment,
        graphs=graphs,
        activity=activity,
    )
    service = session_wiring.service
    turns = session_wiring.turns
    # Built here because `open_graph` is a closure over this build's stores:
    # the ask agent takes the project tools that closure assembles and keeps
    # the readers, so it cannot be constructed anywhere a caller could reach.
    # `time.monotonic` rather than wall-clock for both clocks, because the only
    # questions asked of them are durations -- how long a conversation has been
    # idle -- and a clock that can step backwards would evict a chat somebody
    # is in the middle of.
    ask_service = build_ask_service(
        model=resolved_model,
        open_graph=open_graph,
        project_files=service.project_files,
        store=repository.store,
        publisher=repository.publisher,
    )

    socratic_service = build_socratic_service(
        model=resolved_model,
        open_graph=open_graph,
        project_files=service.project_files,
        dialogues=dialogues,
        store=repository.store,
        publisher=repository.publisher,
        snapshot_store=repository.snapshot_store,
    )

    content_pipeline = build_content_pipeline(
        open_graph=open_graph,
        corpus_readers=corpus_readers,
        store=repository.store,
        publisher=repository.publisher,
        snapshot_store=repository.snapshot_store,
        blob_store=blob_store,
        perception=resolved_perception,
        perception_max_chars=config.perception_max_chars,
        extractions=extractions,
    )
    document_extractor = content_pipeline.document_extractor
    editor = content_pipeline.editor
    media_perceiver = content_pipeline.media_perceiver
    runs = build_research_run_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )
    topic_repository = build_topic_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )
    # Unsnapshotted, unlike `topic_repository` above -- `MediaProposals` has no
    # `build_media_proposal_repository` helper yet because nothing needing a
    # snapshot policy has been written against it, mirroring the bare
    # `AggregateRepository` construction `tests/application/
    # test_media_curation.py` already uses over `harness.event_store`. Built
    # over `repository.store`/`.publisher` so `MediaCurationService`'s writes
    # and `media_proposals`'s subscription above read and write the same log.
    media_proposal_repository = AggregateRepository(
        repository.store, MediaProposals, event_publisher=repository.publisher
    )
    # Task 11b: the accept route (below, in `create_app`) only appends
    # `MediaProposalAccepted` and answers 202 -- nothing downstream of it
    # calls `MediaAcceptWorker` unless this build hands it one. Built here,
    # after `media_proposal_repository`, `editor` and `media_perceiver` all
    # exist, rather than beside the other projections above: those three are
    # exactly the collaborators the worker needs, and `media_proposals` (the
    # runner just above) already satisfies `MediaProposalReadPort` on its own
    # -- see `MediaProposalRunner.get` -- so no separate read adapter is
    # built either. The same "construct once, in one place" reasoning that
    # motivates gathering the projections applies here too: a worker built
    # somewhere else, or not at all, is a worker nobody notices is missing
    # until an accepted proposal never turns into a source.

    project_services = build_project_services(
        topics=topics,
        topic_repository=topic_repository,
        graphs=graphs,
        ontology=ontology,
        definition_invalidation=definition_invalidation,
        corpus=corpus,
        blob_store=blob_store,
        extraction_model=extraction_model,
        repository=repository,
    )
    topic_reader = project_services.topic_reader
    definition_reader = project_services.definition_reader
    ontology_discoverer = project_services.ontology_discoverer
    catalog_recorder = project_services.catalog_recorder

    catalog_services = build_catalog_services(
        art_store=art_store,
        candidate_art_store=candidate_art_store,
        blurb_cache=blurb_cache,
        outline_cache=outline_cache,
        extraction_model=extraction_model,
        course_runner=course_runner,
        authoring=authoring,
        store=repository.store,
        publisher=repository.publisher,
    )
    art_matcher = catalog_services.art_matcher
    catalog_service = catalog_services.catalog_service
    blurb_writer = catalog_services.blurb_writer
    outline_writer = catalog_services.outline_writer
    blurb_sweep = catalog_services.blurb_sweep
    art_generator = catalog_services.art_generator
    art_sweep = catalog_services.art_sweep
    art_reroll = catalog_services.art_reroll
    course_repository = catalog_services.course_repository
    course_service = catalog_services.course_service

    supervisors = build_supervisor_roster(
        service=service,
        turns=turns,
        runs=runs,
        topics=topics,
        topic_repository=topic_repository,
        topic_reader=topic_reader,
        policy=resolved_policy,
        grants=resolved_grants,
        summaries=summaries,
        extractions=extractions,
        dispatches=dispatches,
        worker_roster_cls=WorkerRoster,
    )
    research_supervisor = supervisors.research
    topic_seeder = supervisors.topic_seeder
    course_author = supervisors.course_author
    dispatcher = supervisors.dispatcher
    worker_roster = supervisors.workers

    # Built last, deliberately: this used to be built ~250 lines earlier,
    # immediately after `media_perceiver`, where nothing built from
    # `resolved_media_http_client`/`media_accept_worker` was used before the
    # `Application(...)` call at the end of this function -- both names are
    # only read from inside closures (`open_graph`'s `fetch_media` below,
    # and `Application`'s own field) that Python resolves at call time, not
    # at definition time. Anything raising between the old site and
    # `Application(...)` left the client constructed with no owner to close
    # it, since `Application.close()` is unconditional but only exists once
    # an `Application` does. Moved here, directly preceding
    # `Application(...)`, instead of wrapped in `try/finally`: the window
    # closes by construction rather than by a handler that would itself
    # need testing (see `fece941`'s commit message for the full reasoning).
    #
    # `media_http_client` is a parameter, mirroring `perception` elsewhere in
    # this function, so a test can inject an `httpx.MockTransport` and never
    # reach the network --
    # exactly how `tests/application/test_media_acquisition.py`'s own fakes
    # work, and the no-network guarantee `build_application`'s docstring
    # already promises for `perception`.
    #
    # A bare `httpx.AsyncClient()` carries httpx's 5-second default read
    # timeout, which made `fetch_media.TIMEOUT = httpx.Timeout(30.0)` inert
    # for every caller through this composition site -- that constant only
    # applies on the branch where a caller builds its own client, and nothing
    # here ever did. Downloading a multi-megabyte video under a 5s ceiling is
    # how "stuck accepted forever" (see `MediaAcceptWorker.run`'s widened
    # exception handling) got hit routinely rather than rarely: a slow but
    # otherwise healthy host would trip `httpx.HTTPError` on ordinary size,
    # not just on an actually-broken one. 30s matches `fetch_media.TIMEOUT`
    # so the two paths that share `download_media` also share the ceiling
    # they run it under.
    media_acquisition = build_media_acquisition(
        media_proposals=media_proposals,
        media_proposal_repository=media_proposal_repository,
        editor=editor,
        media_perceiver=media_perceiver,
        media_http_client=media_http_client,
    )
    resolved_media_http_client = media_acquisition.client
    media_accept_worker = media_acquisition.worker
    media_accept_reconciler = media_acquisition.reconciler

    return Application(
        service=service,
        feed=LiveFeed(repository),
        turns=turns,
        context_mode=mode,
        summaries=summaries,
        corpus=corpus,
        blob_store=blob_store,
        topics=topics,
        settings=settings_deps,
        tenants=tenants,
        authorizer=authorizer,
        definitions=definition_invalidation,
        definition_readers=definition_reader,
        ontology=ontology,
        ontology_discoverers=ontology_discoverer,
        media_proposals=media_proposals,
        media_proposal_repository=media_proposal_repository,
        media_curation_text=media_curation_text,
        media_curation_search=media_curation_search,
        graphs=graphs,
        topic_readers=topic_reader,
        topic_repository=topic_repository,
        research=research_supervisor,
        topic_seeder=topic_seeder,
        course_author=course_author,
        reembed=reembed_project,
        dispatcher=dispatcher,
        workers=worker_roster,
        policy=resolved_policy,
        grants=resolved_grants,
        ask=ask_service,
        asks=asks,
        authoring_runs=build_course_authoring_run_repository(
            repository.store, repository.publisher
        ),
        authoring=authoring,
        socratic=socratic_service,
        dialogues=dialogues,
        users=users,
        user_recorder=user_recorder,
        interaction_log=interaction_log,
        interaction_recorder=interaction_recorder,
        _interaction_store=interaction_store,
        catalog=catalog_service,
        _catalog_runner=catalog_runner,
        catalog_recorder=catalog_recorder,
        blurbs=blurb_writer,
        _blurb_cache=blurb_cache,
        course_service=course_service,
        _course_runner=course_runner,
        course_repository=course_repository,
        outlines=outline_writer,
        _outline_cache=outline_cache,
        blurb_sweep=blurb_sweep,
        art_store=art_store,
        art_generator=art_generator,
        art_matcher=art_matcher,
        project_summaries=project_summaries,
        _candidate_art_store=candidate_art_store,
        art_sweep=art_sweep,
        art_reroll=art_reroll,
        document_extractor=document_extractor,
        editor=editor,
        perception=resolved_perception,
        perceiver=media_perceiver,
        media_accept_worker=media_accept_worker,
        media_accept_reconciler=media_accept_reconciler,
        media_reconcile_interval=config.media_reconcile_interval_seconds(),
        _media_http_client=resolved_media_http_client,
        _initial_project_id=project_id,
    )


@functools.wraps(_build_application)
def build_application(*args, **kwargs) -> Application:
    """`_build_application`, with a partial build unwound rather than leaked.

    B100. A raise anywhere in the body used to abandon the event store, the
    blob store and every projection runner built above it, and B5 makes that
    worse than a leak: the event store's aiosqlite worker thread is non-daemon,
    so the process hangs on exit instead of reporting the misconfiguration that
    caused the raise.

    **The teardown is scheduled, not awaited, when a loop is already running**,
    and that is the compromise this wrapper is. `build_application` is
    synchronous -- `build_perception_adapter`'s docstring says why it stays
    that way -- so there is no `await` available on the raise path. With a
    running loop the cleanup goes on it as a task and completes once control
    returns there, which is after the exception has already reached the
    caller; with no running loop it is run to completion under `asyncio.run`.
    So a caller that catches the error and immediately inspects the filesystem
    can observe the store still open. Stated rather than hidden: what this
    guarantees is that the resources are closed, not when.

    `functools.wraps` over `*args, **kwargs` rather than restating two dozen
    keyword parameters: the duplicate signature is the thing that would drift.
    `inspect.signature` still resolves through `__wrapped__`, so callers and
    tooling see the real parameters.
    """
    try:
        return _build_application(*args, **kwargs)
    except BaseException as error:
        steps = _partial_build_teardown(error, _build_application.__code__)
        if steps:
            _run_detached(_close_every_step(*steps))
        raise


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
