"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository
from fastapi import (
    FastAPI,
    HTTPException,
    Response,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers

from research_team.application import (
    AutonomyPolicy,
    LiveFeed,
    SessionService,
    TurnSupervisor,
    WorkerRoster,
)
from research_team.application.area_projection import GraphTooLarge
from research_team.application.ask import AskService
from research_team.application.blobs import BlobStorePort
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.course_authoring import CourseAuthor
from research_team.application.course_catalog import (
    ArtGeneratorPort,
    BlurbTextPort,
    CatalogService,
    OutlineTextPort,
)
from research_team.application.course_realization import CourseService
from research_team.application.curriculum import CurriculumService
from research_team.application.document_extraction import DocumentExtractor
from research_team.application.graph_read import GraphReadPort
from research_team.application.media_acquisition import MAX_UPLOAD_BYTES as MAX_UPLOAD_BYTES
from research_team.application.media_acquisition import MediaAcceptWorker
from research_team.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.application.perception import (
    MediaPerceiver,
    PerceptionPort,
)
from research_team.application.project_graphs import ProjectGraphs
from research_team.application.project_summaries import ProjectSummaries
from research_team.application.socratic import SocraticDialogueService
from research_team.application.timeline_read import TimelineReadPort
from research_team.application.topic_dispatch import (
    TopicDispatcher,
)
from research_team.application.topic_seeding import TopicSeeder
from research_team.domain.course import Course
from research_team.domain.media_proposals import MediaProposals
from research_team.domain.topic import Topic
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours
from research_team.infrastructure.knowledge.svg_sanitiser import SvgSanitiser
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import (
    ArtStore,
    AskConversationRunner,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import WebApprovals
from research_team.interfaces.web.art_sweep import ArtReroll, ArtSweep
from research_team.interfaces.web.auth import (
    AuthConfig,
    AuthGate,
    SessionSigner,
    SessionStore,
    register_auth_routes,
)
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.blurb_sweep import BlurbSweep
from research_team.interfaces.web.catalog import (
    CatalogDeps,
    CatalogFeatureRecorders,
    CatalogFeatures,
    catalog_router,
)
from research_team.interfaces.web.dialogues import (
    AskRequest as AskRequest,
)
from research_team.interfaces.web.dialogues import (
    DialogueDeps,
    dialogue_router,
)
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.export import ExportDeps, export_router
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.interfaces.web.presenters import summary_view
from research_team.interfaces.web.seeding import SeedingActivity
from research_team.interfaces.web.settings import SettingsDeps, settings_router
from research_team.interfaces.web.sources import SourceDeps, source_router
from research_team.interfaces.web.stream import (
    DISCONNECT_CHECK as DISCONNECT_CHECK,
)
from research_team.interfaces.web.stream import (
    KEEPALIVE_SECONDS as KEEPALIVE_SECONDS,
)
from research_team.interfaces.web.stream import (
    StreamDeps as StreamDeps,
)
from research_team.interfaces.web.stream import (
    _sse as _sse,
)
from research_team.interfaces.web.stream import (
    stream_router as stream_router,
)
from research_team.interfaces.web.system import SystemDeps, system_router
from research_team.interfaces.web.topics import (
    MAX_BULK_DISPATCH as MAX_BULK_DISPATCH,
)
from research_team.interfaces.web.topics import (
    BulkDispatch as BulkDispatch,
)
from research_team.interfaces.web.topics import (
    NewDispatch as NewDispatch,
)
from research_team.interfaces.web.topics import (
    NewSeed as NewSeed,
)
from research_team.interfaces.web.topics import (
    NewSubQuestion as NewSubQuestion,
)
from research_team.interfaces.web.topics import (
    StatusChange as StatusChange,
)
from research_team.interfaces.web.topics import (
    SubQuestionAnswer as SubQuestionAnswer,
)
from research_team.interfaces.web.topics import (
    TopicDeps,
    topic_router,
)
from research_team.interfaces.web.topics import (
    TopicReaders as TopicReaders,
)

from .interactions import (
    InteractionDeps,
    InteractionFailures,
    InteractionReaders,
    interaction_router,
)
from .knowledge import (
    DefinitionReaders as DefinitionReaders,
)
from .knowledge import (
    IgnoreMediaProposalBody as IgnoreMediaProposalBody,
)
from .knowledge import (
    KnowledgeDeps as KnowledgeDeps,
)
from .knowledge import (
    OntologyDiscoverers as OntologyDiscoverers,
)
from .knowledge import (
    OntologyTriggerBody as OntologyTriggerBody,
)
from .knowledge import (
    RejectMediaProposalBody as RejectMediaProposalBody,
)
from .knowledge import (
    knowledge_router as knowledge_router,
)
from .knowledge import (
    mount_knowledge_routes as mount_knowledge_routes,
)
from .projects import (
    JoinOptions as JoinOptions,
)
from .projects import (
    NewProject as NewProject,
)
from .projects import (
    ProjectDeps as ProjectDeps,
)
from .projects import (
    ReembedProject as ReembedProject,
)
from .projects import (
    mount_project_routes as mount_project_routes,
)
from .projects import (
    project_router as project_router,
)
from .projects import (
    require_project as require_project,
)
from .sessions import (
    AutonomyChoice as AutonomyChoice,
)
from .sessions import (
    ChecklistState as ChecklistState,
)
from .sessions import (
    Decision as Decision,
)
from .sessions import (
    NewFork as NewFork,
)
from .sessions import (
    NewTurn as NewTurn,
)
from .sessions import (
    SessionDeps as SessionDeps,
)
from .sessions import (
    mount_session_routes as mount_session_routes,
)
from .sessions import (
    session_router as session_router,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class _RevalidatedStatics(StaticFiles):
    """`StaticFiles`, plus the one response header its filenames now require.

    The console's chunks are emitted without a content hash in their names, so
    that rebuilding them is an edit rather than a rename and two branches can be
    merged without a conflict per chunk -- `frontend/vite.config.ts` carries
    that argument. The consequence is that a given URL no longer names fixed
    bytes, and a browser must be told to check.

    Starlette sends `ETag` and `Last-Modified` and no `Cache-Control` at all
    (measured against starlette 1.3.1, not assumed). With no explicit freshness,
    a browser is entitled to *heuristic* freshness -- conventionally a tenth of
    the file's age -- and applies it without asking the server. That is harmless
    for a hashed filename, which is never reused for different bytes. Here it is
    the whole bug: a chunk untouched for a month may be served from cache for
    days after it changes, beside an `index.html` that did change, and the pair
    do not run. The failure is a blank console, not an error.

    `no-cache` does not mean "do not store" -- it means "revalidate before
    reuse". The cost is one conditional request per asset per load, answered
    `304` with no body, against a server that is normally on the same machine.
    That is the right trade for a console whose whole job is showing the state
    of a running system.

    What a test would fail on: `test_web_static_caching.py` asserts the header
    is present on an asset. Delete this class and it goes red rather than
    quietly reopening the window above.
    """

    async def get_response(self, path: str, scope: Any) -> Response:
        response = await super().get_response(path, scope)
        # Set on 404s and 304s too, which costs nothing and avoids a rule about
        # which status codes carry it.
        response.headers["Cache-Control"] = "no-cache"
        return response


# `NewSession` was here, with `POST /api/sessions`. Both are gone: a session
# belongs to a project, so the only way to make one is
# `POST /api/projects/{id}/join`, which is where the project agrees to be
# joined. A body carrying a `project_id` would have been the same endpoint
# with the project as a parameter instead of as the route, and two ways in is
# how one of them ends up not enforcing the rule.
#
# `system_prompt` had no replacement and needed none: it was only ever set by
# tests, and `start_in_project` composes the default prompt with the knowledge
# prompt, which a caller-supplied override would have silently dropped.


INTERACTION_BODY_LIMIT_BYTES = 2_000_000
"""Most bytes one interaction POST may declare.

Comfortably above what a full legitimate batch can be -- 200 events, each
bounded by `QUERY_TEXT_MAX_LENGTH` plus an envelope of ids, is under a
megabyte -- so this never rejects a batch the client would actually build.
Deliberately loose for that reason: a cap tight enough to be interesting is a
cap that silently loses real batches, and the per-field bounds are what
actually make the data small. This one exists to stop a body that is large
before anything can be validated, which per-event checks cannot do.
"""


class _InteractionBodyCap:
    """Refuse an oversized interaction batch before its body is read.

    The design promised "200 events per batch, and a body-size cap" and only
    the first shipped. The per-field bounds now make a *well-formed* batch
    small, so this is not what stops the ordinary case -- it stops a body that
    is large before anything has looked at its contents, which is the one
    thing per-event validation structurally cannot do: FastAPI reads the whole
    body before the route function runs.

    **Raw ASGI rather than `@app.middleware("http")`, and that is a measured
    constraint rather than a style preference.** The decorator wraps every
    request in Starlette's `BaseHTTPMiddleware`, which runs the endpoint
    inside its own anyio task group; that broke four tests in
    `tests/interfaces/test_extraction_routes.py` -- queueing answered
    `queued: false` and cancelling reported `cancelled: 0`, because the
    extraction routes' fire-and-forget work no longer outlived the response.
    Those four passed with the decorator removed and nothing else changed. A
    plain ASGI callable adds no task group and leaves every other route's
    execution exactly as it was.

    `Content-Length` rather than counting the stream: both delivery paths send
    a `Blob` of known size, so the header is always present from our own
    client, and a chunked request without one falls through to the batch limit
    and the field bounds -- the same defence one layer in, which is enough on
    a local port and cheaper than buffering-while-counting here.

    Scoped to the one path: every other route has its own size story (document
    upload is the obvious one) and must not inherit a cap chosen for
    telemetry.
    """

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/api/interactions":
            declared = Headers(scope=scope).get("content-length")
            if (
                declared is not None
                and declared.isdigit()
                and int(declared) > INTERACTION_BODY_LIMIT_BYTES
            ):
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "the interaction batch is too large"},
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    corpus: CorpusRunner | None = None,
    blob_store: BlobStorePort | None = None,
    workers: WorkerRoster | None = None,
    extraction: ExtractionActivity | None = None,
    policy: AutonomyPolicy | None = None,
    topics: TopicReaders | None = None,
    topic_repository: AggregateRepository[Topic] | None = None,
    graphs: ProjectGraphs | None = None,
    topic_seeder: TopicSeeder | None = None,
    seeding: SeedingActivity | None = None,
    dispatcher: TopicDispatcher | None = None,
    dispatch: DispatchQueue | None = None,
    ask: AskService | None = None,
    asks: AskConversationRunner | None = None,
    dialogues: SocraticDialogueRunner | None = None,
    socratic: SocraticDialogueService | None = None,
    extractor: DocumentExtractor | None = None,
    extract_queue: ExtractionQueue | None = None,
    definitions: DefinitionReaders | None = None,
    ontology: OntologyRunner | None = None,
    ontology_discoverers: OntologyDiscoverers | None = None,
    editor: CorpusEditor | None = None,
    perception: PerceptionPort | None = None,
    perceiver: MediaPerceiver | None = None,
    media_proposals: MediaProposalRunner | None = None,
    media_proposal_repository: AggregateRepository[MediaProposals] | None = None,
    media_accept_worker: MediaAcceptWorker | None = None,
    curation_text: MediaCurationTextPort | None = None,
    curation_search: MediaSearchPort | None = None,
    interactions: EventStoreInteractionRecorder | None = None,
    interaction_reader: InteractionReaders | None = None,
    interaction_failures: InteractionFailures | None = None,
    curriculum: CurriculumService | None = None,
    course_author: CourseAuthor | None = None,
    authoring: AuthoringActivity | None = None,
    reembed: ReembedProject | None = None,
    catalog: CatalogService | None = None,
    catalog_features: CatalogFeatures | None = None,
    catalog_recorder: CatalogFeatureRecorders | None = None,
    course_service: CourseService | None = None,
    course_repository: AggregateRepository[Course] | None = None,
    blurb_sweep: BlurbSweep | None = None,
    blurb_writer: BlurbTextPort | None = None,
    outline_writer: OutlineTextPort | None = None,
    art_store: ArtStore | None = None,
    art_sweep: ArtSweep | None = None,
    art_reroll: ArtReroll | None = None,
    art_generator: ArtGeneratorPort | None = None,
    art_matcher: LibraryArtProvider | None = None,
    settings: SettingsDeps | None = None,
    project_summaries: ProjectSummaries | None = None,
    auth: AuthConfig | None = None,
) -> FastAPI:
    """Build the app around an already-wired service. Composition stays outside.

    `lifespan` is how the composition root gets a foot inside the server's
    event loop. Anything holding a connection bound to the loop that opened it
    -- the `/sessions` projection, in particular -- has to be started there
    rather than at construction time, and this is the only hook the server
    offers for that.
    """
    app = FastAPI(title="research-team", docs_url="/api/docs", lifespan=lifespan)

    app.add_middleware(_InteractionBodyCap)
    # Registered unconditionally, and inert unless `AGENT_AUTH` is on -- see
    # `AuthGate`, whose first branch forwards without reading a cookie when
    # auth is off. Registering it conditionally would mean the two states of
    # this app differ in their middleware stack as well as in their behaviour,
    # and the whole promise of the flag is that `off` is the build that
    # existed before identity did.
    app.add_middleware(AuthGate)
    # `AuthConfig` rather than a bare `enabled` flag, so that a test can point
    # the issuer at a fake ASGI app without setting an environment variable.
    # The default is an auth-off config rather than `None`: `app.state.auth`
    # being absent and being present-and-disabled would otherwise be two
    # distinguishable states with identical intent, and `principal_of` would
    # need to handle both.
    register_auth_routes(
        app,
        auth
        if auth is not None
        else AuthConfig(
            enabled=False,
            client=None,
            signer=SessionSigner.from_config(""),
            sessions=SessionStore(),
            public_url="",
        ),
    )

    async def _load(session_id: UUID):
        try:
            return await service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    async def _require_project(project_id: UUID) -> None:
        await require_project(service, project_id)

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        """This project's corpus, through the same port the agent's tools use.

        Built per request rather than held, because it is two attributes over
        a shared runner and binding the project is the entire point -- a
        long-lived one would have to take the project as an argument again,
        which is what the port refuses so that no caller can read another
        project's sources.

        503 rather than 404 when nothing was wired: an application assembled
        without a corpus read model is a valid thing to serve (as with
        `approvals` and `activity`), and the caller needs to know the server
        cannot answer rather than that the project has nothing.

        `blob_store` is checked alongside `corpus` rather than defaulted to
        something that opens on first use: `ProjectCorpusReader` now needs one
        for `read_media`, and a build that wired a corpus read model but no
        blob store is exactly as unable to answer as one that wired neither --
        the 503 is honest about that rather than pretending media reads are
        wired when only text ones are.
        """
        if corpus is None or blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(corpus, project_id, blob_store)

    async def _graph_reader(project_id: UUID) -> GraphReadPort:
        """This project's `GraphReadPort`, over the store `graphs` already owns.

        503 rather than 404 when `graphs` was not wired, for the reason
        `_reader` gives: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no graph.

        `async`, unlike `_reader` and `_topic_reader`: those wrap an
        already-open corpus and topic repository, but the store behind a
        `ProjectGraphReader` is opened on demand by `graphs.open`, which is
        itself a coroutine -- there is no synchronous constructor to call
        here. Building it per request rather than caching it is safe because
        `graphs` is the single owner of the store underneath (see
        `ProjectGraphs`): a second call today gets back the same store a
        first call already opened, not a stale second one.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        return ProjectGraphReader(project_id=project_id, store=store, ontology=ontology)

    async def _timeline_reader(project_id: UUID) -> TimelineReadPort:
        """This project's `TimelineReadPort`, over the store `graphs` owns.

        503 rather than 404 when `graphs` was not wired, matching
        `_graph_reader`: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no timeline.

        Opens through `graphs` rather than holding its own store, so the
        timeline and the graph read the *same* store rather than two folds of
        one log that could drift apart between tabs.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        return ProjectTimelineReader(project_id=project_id, store=store)

    projects_router = project_router(
        ProjectDeps(
            service=service,
            turns=turns,
            curriculum=curriculum,
            extraction=extraction,
            reembed=reembed,
            project_summaries=project_summaries,
            require_project=_require_project,
        )
    )
    app.include_router(projects_router)

    app.include_router(
        source_router(
            SourceDeps(
                require_project=_require_project,
                corpus=corpus,
                blob_store=blob_store,
                editor=editor,
                extractor=extractor,
                extract_queue=extract_queue,
                ontology=ontology,
                perception=perception,
                perceiver=perceiver,
                extraction=extraction,
                reader_of=_reader,
            )
        )
    )

    app.include_router(
        topic_router(
            TopicDeps(
                require_project=_require_project,
                topics=topics,
                topic_repository=topic_repository,
                service=service,
                topic_seeder=topic_seeder,
                seeding=seeding,
                dispatcher=dispatcher,
                dispatch=dispatch,
                workers=workers,
                media_proposal_repository=media_proposal_repository,
                curation_text=curation_text,
                curation_search=curation_search,
            )
        )
    )

    app.include_router(
        interaction_router(
            InteractionDeps(
                interactions=interactions,
                interaction_reader=interaction_reader,
                interaction_failures=interaction_failures,
            )
        )
    )

    app.include_router(
        knowledge_router(
            KnowledgeDeps(
                require_project=_require_project,
                media_proposals=media_proposals,
                media_proposal_repository=media_proposal_repository,
                media_accept_worker=media_accept_worker,
                graphs=graphs,
                ontology=ontology,
                ontology_discoverers=ontology_discoverers,
                definitions=definitions,
                corpus=corpus,
                blob_store=blob_store,
                reader_of=_reader,
                graph_reader=_graph_reader,
                timeline_reader=_timeline_reader,
            )
        )
    )

    async def _co_mentions(project_id: UUID) -> RecordedCoMentions:
        """This project's `CoMentionPort`, over the co-mention index `graphs` owns.

        **`graphs.co_mentions`, not `graphs.chunks`.** The retrieval corpus is
        filled by `index_documents`, which has no entity knowledge and writes
        every chunk with an empty `entity_ids` -- so this route answered 200
        with nothing in it for the whole life of the feature. The index holds
        the *extraction* chunking's links, folded from the same log.

        The graph store goes in as well, because recorded links are
        pre-consolidation ids; see `RecordedCoMentions`.

        `graphs.open` first and the store lookups second, in that order, which
        is not stylistic: `CLAUDE.md` records a defect where a call site
        fetched chunks before opening and every first request for a
        newly-touched project answered 503 while every later one succeeded --
        once per project, and indistinguishable from flakiness.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        index = graphs.co_mentions(project_id)
        if index is None:
            raise HTTPException(status_code=503, detail="no co-mention index is configured")
        return RecordedCoMentions(index, project_id, store)

    async def _semantic(project_id: UUID) -> VectorNeighbours | None:
        """This project's `SemanticPort`, or None when there is nothing to read.

        `graphs.open` first, for `_co_mentions`' reason -- the card vector
        store is folded during `open`, so asking before it has run gets `None`
        from a project whose vectors are merely not loaded yet, which is the
        once-per-project failure that reads as flakiness.

        Unlike `_co_mentions` this returns `None` rather than raising a 503
        when the store is absent. The corpus is a hard requirement for area
        projection and its absence is a misconfiguration; embeddings are an
        optional signal, and a build with `AGENT_VECTOR_STORE=none` must serve
        a curriculum rather than an error.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        await graphs.open(project_id)
        vectors = graphs.card_vectors(project_id)
        if vectors is None:
            return None
        return VectorNeighbours(vectors, tenant_id=project_id)

    async def _curriculum(project_id: UUID):
        """This project's areas and the path through them.

        503 rather than 404 when unwired, matching `_graph_reader`: a build
        without a graph read model is a valid thing to serve, and the caller
        needs to know the *server* cannot answer rather than that the project
        has nothing to learn.
        """
        if curriculum is None:
            raise HTTPException(
                status_code=503, detail="curriculum projection is not configured"
            )
        reader = await _graph_reader(project_id)
        try:
            return await curriculum.build(
                project_id,
                reader,
                await _co_mentions(project_id),
                await _semantic(project_id),
            )
        except GraphTooLarge as error:
            # 422 rather than 500: the project is fine and the server is fine;
            # the question is one this projection will not answer at this size.
            # The detail names the cap so the answer is actionable.
            raise HTTPException(status_code=422, detail=str(error)) from error

    app.include_router(
        catalog_router(
            CatalogDeps(
                require_project=_require_project,
                curriculum_of=_curriculum,
                service=service,
                turns=turns,
                curriculum=curriculum,
                graph_reader=_graph_reader,
                co_mentions=_co_mentions,
                semantic=_semantic,
                catalog=catalog,
                catalog_features=catalog_features,
                catalog_recorder=catalog_recorder,
                course_service=course_service,
                course_repository=course_repository,
                course_author=course_author,
                authoring=authoring,
                blurb_sweep=blurb_sweep,
                blurb_writer=blurb_writer,
                outline_writer=outline_writer,
                art_sweep=art_sweep,
                art_reroll=art_reroll,
                art_generator=art_generator,
                art_matcher=art_matcher,
            )
        )
    )

    @app.get("/api/art/{art_id}.svg")
    async def read_art(art_id: UUID):
        """Serve one piece of art from the global library.

        Deliberately **not** under `/api/projects/{id}/` -- the increment-3
        spec's "Reuse across projects" section is the point of the library
        existing at all: a picture drawn for one project's course is
        findable and servable from any other, and nesting this under a
        project id would make that reuse a lie the URL itself contradicts.

        Re-sanitises on the way out rather than trusting `ArtStore.put`'s
        write-time check alone. `ArtStore.put`'s own docstring gives the
        cost side of that trade -- every read pays a parse it does not
        strictly need if nothing has gone wrong -- but the alternative is a
        route whose safety depends entirely on every past and future writer
        of this table having called the sanitiser correctly, including any
        row written by a version of this codebase that predates it, or by a
        bug in the sibling generator task this route cannot see. A refusal
        here degrades to 404 rather than serving anything, and an SVG cheap
        enough to regenerate is a better failure than trusting a write path
        this route does not control.
        """
        if art_store is None:
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        row = await art_store.get(art_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        safe = SvgSanitiser().sanitise(row.svg)
        if safe is None:
            # A row that fails re-sanitisation is treated the same as a
            # missing one -- 404, not 500 -- because the failure is "this
            # is not safe to serve", which is exactly what a missing row
            # also means to a caller of this route. Logged as a real
            # anomaly, since it means a stored row disagrees with the
            # sanitiser that is supposed to have already passed it once.
            logging.getLogger(__name__).warning(
                "stored art %s failed re-sanitisation on read", art_id
            )
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        return Response(
            content=safe,
            media_type="image/svg+xml",
            headers={
                # Immutable: `art_id` is `uuid4`, minted once, and the bytes
                # under it never change (see `ArtRow`'s docstring) -- so a
                # browser that has fetched one id never needs to ask again.
                "Cache-Control": "public, max-age=31536000, immutable",
                # Belt over the sanitiser's suspenders, per the increment-3
                # spec: an `<img src>` will not execute script in any
                # current browser, but this route is general enough that a
                # future caller may inline the response, and this header is
                # what still holds the line if one does.
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            },
        )

    app.include_router(
        dialogue_router(
            DialogueDeps(
                require_project=_require_project,
                service=service,
                ask=ask,
                asks=asks,
                socratic=socratic,
                dialogues=dialogues,
                turns=turns,
            )
        )
    )

    app.include_router(system_router(SystemDeps(service=service, corpus=corpus)))

    sessions_router = session_router(
        SessionDeps(
            service=service,
            turns=turns,
            approvals=approvals,
            activity=activity,
            policy=policy,
            load=_load,
        )
    )
    app.include_router(sessions_router)

    app.include_router(
        stream_router(
            StreamDeps(
                feed=feed,
                approvals=approvals,
                activity=activity,
                extraction=extraction,
                seeding=seeding,
                dispatch=dispatch,
            )
        )
    )

    # The download routes, which live in their own module rather than inline
    # here. They need three of the closures above rather than the collaborators
    # underneath them -- `_require_project`, `_graph_reader` and `_curriculum`
    # already encode what a 404 and a 503 mean on this surface, and a second
    # derivation of that would be free to disagree with this one about whether
    # an unwired graph store is a missing project. See `export.py`.
    app.include_router(
        export_router(
            ExportDeps(
                service=service,
                require_project=_require_project,
                graph_reader=_graph_reader,
                curriculum_of=_curriculum,
                authoring=authoring,
                # Three more closures, for `format=html` only. Same reasoning
                # as the three above: each already encodes what a 503 means
                # here, and re-deriving them in `export.py` would be a second
                # opinion about whether an unwired corpus is a missing project.
                corpus_reader=_reader,
                definitions=definitions,
                timeline_reader=_timeline_reader,
            )
        )
    )

    # The settings and provider routes. Registered unconditionally, with an
    # empty `SettingsDeps` when composition supplied none: the schema and the
    # provider catalogue are static data and answer either way, and a 404 for
    # the whole surface because one collaborator is unwired is the shape of
    # failure CLAUDE.md's "silent defaults" note is about -- it makes "never
    # wired" and "no such feature" identical to a caller.
    app.include_router(settings_router(settings or SettingsDeps()))

    if STATIC_DIR.is_dir():
        app.mount("/static", _RevalidatedStatics(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            # The same `no-cache` as the assets, and for a sharper reason: this
            # is the file naming them. A cached index.html paired with rebuilt
            # assets is the mismatch that paints nothing.
            return FileResponse(
                STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"}
            )
    else:
        # The console is a build artefact and is no longer committed, so a
        # fresh clone has no `static/` at all. Answering that with the router's
        # bare 404 makes a missing build look like a missing route -- the same
        # blank page a broken one gives, with nothing naming the cause. What a
        # test would fail on: `test_web_missing_console.py` asserts the 503 and
        # the command in its body.
        @app.get("/")
        async def console_not_built() -> PlainTextResponse:
            return PlainTextResponse(
                "The web console has not been built.\n"
                "Run `npm run build` in `frontend/`, then restart.\n",
                status_code=503,
            )

    return app
