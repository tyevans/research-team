"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

import functools
import logging
import random as random
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
from langchain_core.language_models import BaseChatModel

from research_team.dialogue.application.ask import AskService, ConversationRegistry
from research_team.dialogue.application.socratic import (
    DialogueRegistry,
    SocraticDialogueService,
)
from research_team.infrastructure import config
from research_team.infrastructure.agent import (
    build_model,
)
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.corpus_tools import (
    CORPUS_PROMPT,
)
from research_team.infrastructure.agent.fetch import (
    FETCH_CORPUS_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
)
from research_team.infrastructure.agent.search import (
    build_search_tool,
)
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.perception.readeverything_adapter import (
    build_perception_adapter,
)
from research_team.infrastructure.persistence import (
    EventStoreSessionRepository,
    build_ask_conversation_repository,
    build_corpus_repository,
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
from research_team.platform.shared.live_feed import LiveFeed
from research_team.platform.shared.ports import (
    ApprovalPort,
    TurnActivityBuffer,
)
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.document_extraction import DocumentExtractor
from research_team.research.application.perception import MediaPerceiver, PerceptionPort
from research_team.research.application.topics import TOPICS_PROMPT
from research_team.research.domain.media_proposals import MediaProposals
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import (
    DEFAULT_SYSTEM_PROMPT,
    SessionService,
)
from research_team.session.application.workers import (
    DispatchesInFlight,
    ExtractionChannel,
    WorkerRoster,
)
from research_team.tenancy.application.grants import GrantRegistry
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
    build_graph_opener,
    build_knowledge_attachment,
    build_media_acquisition,
    build_media_perceiver,
    build_project_graphs,
    build_project_services,
    build_session_service,
    build_socratic_service,
    build_stores,
    build_supervisor_roster,
    build_tools,
    build_turn_executor,
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
    "build_fetch_tool",
    "build_graph_opener",
    "build_knowledge_attachment",
    "build_learner_progress_repository",
    "build_media_perceiver",
    "build_project_graphs",
    "build_search_tool",
    "build_service",
    "build_socratic_dialogue_repository",
    "build_socratic_service",
    "build_stores",
    "build_tools",
    "build_turn_executor",
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

    corpus_readers = lambda target_project_id: ProjectCorpusReader(  # noqa: E731
        corpus, target_project_id, blob_store
    )

    executor = build_turn_executor(
        resolved_model=resolved_model,
        injected_model=model,
        subagents=subagents,
        tools=tools,
        policy=resolved_policy,
        approvals=approvals,
        grants=resolved_grants,
        corpus=corpus,
        blob_store=blob_store,
        recall=recall,
        pages=pages,
        search_attempts=search_attempts,
        authoring_rounds=authoring_rounds,
        effective_settings=effective_settings,
        get_attachment=lambda: attachment,
        build_fetch=lambda **kw: build_fetch_tool(**kw),
    )

    wired_graphs = build_project_graphs(
        repository.store,
    )
    graphs = wired_graphs.graphs
    embedding_provider = wired_graphs.embedding_provider
    reembed_project = wired_graphs.reembed_project

    open_graph = build_graph_opener(
        graphs=graphs,
        effective_settings=effective_settings,
        model=model,
        extraction_model=extraction_model,
        repository=repository,
        corpus=corpus,
        topics=topics,
        blob_store=blob_store,
        recall=recall,
        pages=pages,
        extractions=extractions,
        get_media_http_client=lambda: resolved_media_http_client,
        get_editor=lambda: editor,
        embedding_provider=embedding_provider,
        build_fetch=lambda **kw: build_fetch_tool(**kw),
    )

    attachment = build_knowledge_attachment(
        executor,
        tools,
        open_graph=open_graph,
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
