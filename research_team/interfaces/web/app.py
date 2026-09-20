"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from eventsource import CommandRejectedError
from eventsource.application.aggregates.repository import AggregateRepository
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.datastructures import Headers

from research_team.application import (
    AutonomyPolicy,
    LiveFeed,
    SessionService,
    TurnSupervisor,
    WorkerRoster,
    build_fork_tree,
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
from research_team.application.knowledge import KnowledgeError
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
from research_team.domain import (
    Corpus,
    CreateProject,
    Project,
    SessionPurpose,
)
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
from research_team.infrastructure.persistence.event_store import KNOWLEDGE_CATEGORIES
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
from research_team.interfaces.web.presenters import (
    corpus_change,
    feed_event,
    graph_change,
    media_change,
    project_change,
    project_detail_view,
    project_view,
    reading_head,
    summary_view,
    topic_change,
    tree_view,
)
from research_team.interfaces.web.seeding import SeedingActivity
from research_team.interfaces.web.settings import SettingsDeps, settings_router
from research_team.interfaces.web.sources import SourceDeps, source_router
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
from .sessions import (
    sessions_router as sessions_router,
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


KEEPALIVE_SECONDS = 15.0

DISCONNECT_CHECK = 0.5
"""How long we may sit unaware that the browser has gone."""

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


class NewProject(BaseModel):
    name: str


class JoinOptions(BaseModel):
    """Whether a join may end the session currently holding the project."""

    take_over: bool = False


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


ReembedProject = Callable[[UUID], Awaitable[int]]
"""Re-embed one project's entities from its current graph. Returns how many.

A callable rather than the provider and the stores it needs, for the reason
every other port here is one: this module may not name redstring, and the
work reaches across the graph store, the embedding provider, the event log
and the per-project vector store. Composition owns all four.
"""


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

    @app.get("/api/projects")
    async def list_projects():
        """Every project, with the pipeline position the index draws it from.

        The summaries are read **once for the whole list**, outside the loop,
        which is the only thing worth knowing about this handler. The loop
        below already folds one aggregate per project to find the holder, and
        `domain/project/landing.ts` defers a feature by name on that cost —
        so a summary fetched inside the loop would have doubled the one thing
        this route was already too expensive at, in order to improve the page
        it serves.

        A build with no summaries wired answers zeros rather than 503, which
        is the opposite of what `_reader` and `_topic_reader` do and is
        deliberate: those guard routes that cannot mean anything without their
        collaborator, and this one is the index. A console that cannot count
        a project's sources should still list the project.
        """
        projects = await service.list_projects()
        summaries = await project_summaries.all() if project_summaries else {}
        rows = []
        for project_id, name in projects:
            state = await service.project_state(project_id)
            rows.append(
                project_view(
                    project_id,
                    name,
                    active_session_id=state.active_session_id,
                    tip_at_event=state.tip_at_event,
                    summary=summaries.get(project_id),
                )
            )
        return rows

    @app.post("/api/projects")
    async def create_project(body: NewProject):
        """Create a project by name. A name collision is a 409, not a second project.

        Mirrors `/project new` in the REPL: check-then-create over
        `list_projects` rather than letting the aggregate itself reject a
        duplicate name, because `Project` has no notion of "the project
        called X" -- names are only unique by convention of this list, and
        that convention is enforced here, the one place both front ends
        share through `SessionService`.
        """
        existing = await service.list_projects()
        collision = next((pid for pid, name in existing if name == body.name), None)
        if collision is not None:
            raise HTTPException(
                status_code=409,
                detail=f"project {body.name!r} already exists ({collision})",
            )
        aggregate = service.projects.create_new(uuid4())
        aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name=body.name))
        await service.projects.save(aggregate)
        return project_view(aggregate.aggregate_id, body.name)

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: UUID, release_holder: bool = False):
        """Retire a project. `release_holder` ends the session still driving it.

        The holder is not released implicitly: releasing advances the tip,
        which writes to that session, and a delete that quietly did so would
        make a destructive-sounding verb do an unrelated write. Asking for it
        explicitly keeps both halves visible -- and gives the UI something to
        put in its confirmation prompt rather than a bare 409 to relay.
        """
        # An id nothing was ever written under raises from the repository
        # rather than folding to an empty state, so "no such project" arrives
        # two different ways and both have to become the same 404.
        #
        # Deleted counts as absent here too, so deleting twice is a 404 rather
        # than the domain's 409 "project already deleted". The 409 was the more
        # informative answer and is deliberately given up: a caller who cannot
        # *see* the project through any other route has no way to act on being
        # told it is already gone, and one route treating a deleted project as
        # present -- to refuse it -- is the inconsistency this change exists to
        # remove.
        await _require_project(project_id)
        state = await service.project_state(project_id)
        holder = state.active_session_id
        if holder is not None:
            if not release_holder:
                raise HTTPException(
                    status_code=409,
                    detail=f"project is held by session {holder}; end that session first",
                )
            if turns.is_running(holder):
                raise HTTPException(
                    status_code=409,
                    detail="the holding session has a turn running; cancel it first",
                )
            await service.release_project(holder)
        try:
            await service.delete_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if service.attached_project_id == project_id:
            await service.detach_project()
        if curriculum is not None:
            # The projection is cached per project and keyed on graph counts,
            # so a project deleted and a new one created under a recycled id
            # would otherwise be answered from the first one's areas. Ids are
            # not recycled today, which is why this is cheap insurance rather
            # than a fix -- the cache holding a dead project's clusters for the
            # life of the process is reason enough on its own.
            curriculum.forget(project_id)
        return {"deleted": True, "project_id": str(project_id)}

    async def _require_project(project_id: UUID) -> None:
        """404 unless `project_id` names a project that exists and is not deleted.

        Checked before touching the corpus so that "no such project" and "that
        project has no sources" stay different answers. Without it an unknown
        id would list empty and read 404, which reads as a project that exists
        and happens to be bare -- and the caller's next move (store something)
        would be the wrong one.

        **A deleted project is a 404, not a 200 with its name in it**, and this
        function is the only place that can say so once: it guards
        seventy-odd project-scoped routes, and until 2026-08-27 it refused
        only the `new` state, so every one of them answered a deleted
        project's reads in full. The write half was never affected --
        `Project.decide` refuses every command against a deleted project
        ("a deleted project answers nothing but 'deleted'") -- which is
        exactly what made the read half hard to notice: nothing could be
        *changed* through those routes, so nothing broke, and a retired
        project simply kept answering questions about itself.

        The same rule already held one layer down and disagreed with this one.
        `event_store.list_projects` filters deleted ids out and its docstring
        says that filter is "what makes deleted mean gone to every caller that
        lists" -- so a deleted project was absent from `/api/projects` and
        present at `/api/projects/{id}`, which is the shape of a bug rather
        than of a convention.

        What it costs: a client holding a URL to a project deleted in another
        tab now gets 404 rather than a page. That is the point. The
        alternative considered was 410 Gone, which is more precise and which
        no client here distinguishes -- `_require_project`'s callers and the
        console both branch on 404 alone, so 410 would buy accuracy nobody
        reads at the price of a second not-found code to handle.
        """
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status in ("new", "deleted"):
            raise HTTPException(status_code=404, detail=f"no project {project_id}")

    @app.get("/api/projects/{project_id}")
    async def read_project(project_id: UUID):
        """One project: who it is, and which session holds it.

        Separate from the listing rather than "the row you already fetched",
        because the console reaches a project page by URL as often as by a
        click -- a reload, a bookmark, a link somebody sent -- and on that path
        no listing has been fetched. The alternative was for a project page to
        read `/api/projects` and filter, which is O(projects) of server-side
        fold to answer a question about one.
        """
        await _require_project(project_id)
        state = await service.project_state(project_id)
        return project_detail_view(
            project_id,
            state.name,
            active_session_id=state.active_session_id,
            tip_at_event=state.tip_at_event,
            # The one field the listing beside this does not carry. See
            # `project_detail_view`: a page is reached one at a time, and the
            # listing folds an aggregate per row already.
            reading_head_session_id=reading_head(state),
        )

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

    @app.post("/api/projects/{project_id}/embeddings", status_code=202)
    async def refresh_embeddings(project_id: UUID):
        """Re-embed every entity in this project, from the graph as it stands.

        **Why this exists rather than embeddings simply being current.** A
        vector is written when its entity is extracted, and it encodes the card
        the entity had *then*. Nothing re-embeds at project open, deliberately:
        `rebuild_graph` must not depend on a live endpoint, or a session
        refolded years from now would not open. So an entity that gained six
        relationships after it was first seen carries a vector that knows about
        none of them, and this is the button that fixes it.

        It is also the repair for the whole class of projects ingested before
        embeddings were durable at all, which is every project written before
        2026-08-22: their logs carry no `EntitiesEmbedded`, so they fold to an
        empty vector store and cluster on the graph alone until this runs.

        **202 and synchronous, which is a contradiction worth admitting.** The
        work is one embedding call per 64 entities and returns before the
        response does; the status is 202 because the *effect* a caller cares
        about -- a curriculum clustered with the new vectors -- lands on the
        next projection rather than in this response body. What it costs is a
        request held open proportional to the graph: about eight calls for a
        five-hundred-entity project, and a route that is no longer reasonable
        somewhere north of a few thousand. `BACKLOG.md` B131 has the
        background-run version; this is deliberately the small one.

        The cached curriculum is forgotten here rather than left to expire,
        because the cache is keyed on entity and relationship counts and
        re-embedding moves neither -- so without this, the run would succeed
        and change nothing anybody could see until the next extraction.
        """
        await _require_project(project_id)
        if reembed is None:
            raise HTTPException(status_code=503, detail="embeddings are not configured")
        try:
            embedded = await reembed(project_id)
        except KnowledgeError as error:
            # 502 rather than 500: the fault is upstream and the operator can
            # act on it. Distinct from the 503 above, which says this build was
            # never wired for embeddings, and from a 202 carrying `embedded: 0`,
            # which says the feature is off on purpose. Three different things
            # a browser would otherwise have to guess at from one status.
            raise HTTPException(status_code=502, detail=str(error)) from error
        if curriculum is not None:
            curriculum.forget(project_id)
        return {"embedded": embedded}

    @app.post("/api/projects/{project_id}/join")
    async def join_project(project_id: UUID, body: JoinOptions | None = None):
        """Start a session that inherits `project_id`'s filesystem, and attach its graph.

        Goes through `SessionService.start_in_project` -- the same use case
        the REPL's `/project use` calls -- so joining is decided in exactly
        one place: the `Project` aggregate. A project already held raises
        `CommandRejectedError` naming the holding session, which this maps to
        409 rather than letting it become an unhandled 500.

        Attachment design: unlike the REPL, this process serves many browser
        sessions at once through one `TurnSupervisor` and (if wired) one
        `KnowledgeAttachment`, so there is no single "current session" whose
        project should stay attached. A per-session attachment map would
        preserve REPL-like isolation between browser tabs, but this app is a
        local single-user tool -- the spec never asks it to serve concurrent
        untrusted users -- so the simpler answer is taken: attach here,
        accept that the most recent join wins process-wide, and say so
        plainly rather than build isolation nothing asked for. A second tab
        joining a different project will change the tools the first tab's
        turns run with; that is a known, accepted limitation of this design,
        not an oversight.

        Taking over: a project held by a session the user has finished with
        is the ordinary case, not an error -- "end this and start fresh" is
        the single most common thing to want from a project, and before
        `take_over` the web app could only report the 409 and offer no way
        out of it. It is spelled as an explicit flag rather than done
        silently because releasing the holder advances the tip, which is a
        write to somebody else's session; a plain join stays a plain join.
        """
        # Ahead of `take_over`, so that a deleted project is 404 rather than
        # reaching `release_project` and advancing a retired project's tip on
        # the way to the domain's refusal. Joining one used to answer the
        # domain's 409 "project has been deleted", which both refused the join
        # and confirmed the project existed; 404 is the same refusal without
        # the confirmation, and matches every other project-scoped route.
        await _require_project(project_id)
        if body is not None and body.take_over:
            state = await service.project_state(project_id)
            if state.active_session_id is not None:
                if turns.is_running(state.active_session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="the holding session has a turn running; cancel it first",
                    )
                await service.release_project(state.active_session_id)
        try:
            session_id = await service.start_in_project(project_id, SessionPurpose.CHAT)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            await service.attach_project(project_id)
        except Exception as error:  # noqa: BLE001 -- report, do not fail the join
            return {
                "id": str(session_id),
                "project_id": str(project_id),
                "warning": str(error),
            }
        return {"id": str(session_id), "project_id": str(project_id), "warning": None}

    @app.get("/api/projects/{project_id}/extraction")
    async def get_extraction(project_id: UUID):
        """What the running extraction has done so far, and the last one's account.

        A tab that arrived mid-ingest, or one whose connection dropped, has no
        other way back: these frames carry no feed position, so
        `Last-Event-ID` cannot replay them. 200 with two empty lists when
        nothing has run -- an absent extraction is a state, not a missing
        resource, and unlike `/workers` there is no claim being made about
        what is running elsewhere.
        """
        await _require_project(project_id)
        if extraction is None:
            return {"current": [], "last": []}
        return {
            "current": extraction.current(project_id),
            "last": extraction.last(project_id),
        }

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

    @app.get("/api/health")
    async def health():
        """Whether the derived views behind this API can be trusted.

        `/sessions` is answered from a projection, so unlike a fold it can be
        wrong -- and a wrong row looks exactly like a right one. This is where
        a UI finds out to say so.
        """
        summaries = await service.summaries_health()
        return {
            "summaries": {
                "healthy": summaries.healthy,
                "failed_events": summaries.failed_events,
                "following": summaries.following,
                "behind": summaries.behind,
            }
        }

    @app.post("/api/summaries/rebuild")
    async def rebuild_summaries():
        """Derive the session list from the log again, and report the result.

        Exposed over HTTP because the browser is the primary surface and a
        problem you can see but not fix is only half-reported. Safe to call at
        any time: it discards derived data and recomputes it, so the worst case
        is wasted work, and the log it derives from is never touched.
        """
        await service.rebuild_summaries()
        health = await service.summaries_health()
        return {"healthy": health.healthy, "failed_events": health.failed_events}

    @app.post("/api/corpus/rebuild")
    async def rebuild_corpus():
        """Derive the corpus table from the log again, and say what it holds.

        A sibling of `/api/summaries/rebuild` rather than part of it, for the
        reason `CorpusRunner` is a second runner: rebuilding is a manual repair
        that stops a manager, truncates a table and resets a checkpoint, and
        two tables that can fail independently have to be repairable
        independently. Repairing `/sessions` must not truncate the corpus.

        Goes through the runner rather than a `SessionService` method, unlike
        its sibling. `SessionSummaries` is a port the service already owns and
        answers for; the corpus runner reaches this layer directly, and adding
        a passthrough to the service would be a use case with nothing in it.

        Safe at any time, and the same argument as its sibling: every byte it
        discards is derivable from the event that put it there, so the worst
        case is wasted work. It is also the only way to correct `extracted` on
        a database written before that column existed -- see
        `CorpusDocumentRow.extracted_at`, where the measurement is recorded.
        """
        if corpus is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        await corpus.rebuild()
        return {"rebuilt": True}

    @app.get("/api/tree")
    async def fork_tree():
        return tree_view(build_fork_tree(await service.list_sessions()))

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

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Every event, as it is appended, to every listening browser.

        `Last-Event-ID` is the browser's own reconnect header -- EventSource
        sends it automatically with the id of the last frame it received, so
        resuming costs the client nothing and closes the window where events
        appended during a dropped connection would never be seen.
        """
        resume_from = request.headers.get("last-event-id")
        return StreamingResponse(
            _sse(
                request, feed, resume_from, approvals, activity, extraction, seeding, dispatch
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


async def _sse(
    request: Request,
    feed: LiveFeed,
    resume_from: str | None = None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    extraction: ExtractionActivity | None = None,
    seeding: SeedingActivity | None = None,
    dispatch: DispatchQueue | None = None,
) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.

    Every logged frame carries the position that follows it as its id, so a
    browser that drops can say where it got to. An id we cannot place --
    stale, or from a database since replaced -- is treated as no id at all:
    starting at the live end shows less than the client wanted, while
    replaying the entire log at it would be worse than the gap.

    Approval requests, turn activity notes, extraction progress, seeding
    status and dispatch status ride this same connection rather than one each
    of their own, for the same reason as each other: none is a log entry -- an
    approval that is never answered, provisional turn content, where an ingest
    has got to, whether a seeding run is still going, and what a project has
    queued at its topics all leave no event behind -- so none carries an id,
    and a reconnecting browser refetches what it missed (`/approvals`, the
    activity catch-up route, `/projects/{id}/extraction`,
    `/projects/{id}/topics/seed`, or `/projects/{id}/dispatch`) instead of
    replaying them. But a second
    channel per concern would multiply the ways a tab can be half-connected,
    and a turn that halts for a person, or is still streaming its reply, is
    exactly the moment when being half-connected is worst.
    """
    queue: asyncio.Queue = asyncio.Queue()
    start_at = feed.decode_position(resume_from) if resume_from else None
    # Taken here rather than left to `follow`, so that by the time this
    # generator yields anything the cursor is already fixed. `follow` would
    # take the same position on the first turn of the pump task below, which is
    # scheduled and not awaited -- so "the response has started" would not mean
    # "the subscriber is placed", and an event appended in between would be
    # missed by a client that had every reason to think it was listening.
    #
    # `from_beginning` is not a nicety. An empty log has no position, so
    # `position_now()` answers `None` -- which is the same value as "I am not
    # telling you where to start", and `follow` responds to that by taking the
    # position itself, later, on the pump's first turn. The window this exists
    # to close would have reopened for exactly the case where it is widest.
    # Replaying from the start is not a different behaviour here: the log was
    # empty when we looked, so everything from the start *is* everything since.
    from_beginning = False
    if start_at is None:
        start_at = await feed.position_now()
        from_beginning = start_at is None

    async def pump() -> None:
        async for entry in feed.follow(from_position=start_at, from_start=from_beginning):
            await queue.put(("event", entry))

    # The feed is drained by its own task rather than awaited inline, so waiting
    # for the next event never means being unable to notice anything else. What
    # this coroutine waits on is a queue, which is safe to cancel; cancelling a
    # database poll mid-flight is not.
    pumps = [asyncio.create_task(pump())]
    listening = None
    if approvals is not None:
        listening = approvals.listen()

        async def pump_approvals() -> None:
            while True:
                await queue.put(("approval", await listening.get()))

        pumps.append(asyncio.create_task(pump_approvals()))

    watching = None
    if activity is not None:
        watching = activity.listen()

        async def pump_activity() -> None:
            while True:
                await queue.put(("activity", await watching.get()))

        pumps.append(asyncio.create_task(pump_activity()))

    extracting = None
    if extraction is not None:
        extracting = extraction.listen()

        async def pump_extraction() -> None:
            while True:
                await queue.put(("extraction", await extracting.get()))

        pumps.append(asyncio.create_task(pump_extraction()))

    seeded = None
    if seeding is not None:
        seeded = seeding.listen()

        async def pump_seeding() -> None:
            while True:
                await queue.put(("seeding", await seeded.get()))

        pumps.append(asyncio.create_task(pump_seeding()))

    dispatching = None
    if dispatch is not None:
        dispatching = dispatch.listen()

        async def pump_dispatch() -> None:
            while True:
                await queue.put(("dispatch", await dispatching.get()))

        pumps.append(asyncio.create_task(pump_dispatch()))

    idle = 0.0
    try:
        # "You are subscribed, from a position already taken."
        #
        # A comment rather than an event: `EventSource` ignores `:` lines
        # entirely, so no browser needs to know this exists and no client code
        # changes. What it buys is a point in time that means something --
        # headers arrive when the route returns, which is before any of the
        # above has run, so `onopen` alone never told a client its cursor was
        # placed.
        #
        # Inside the `try`, not above it, and that placement is the whole
        # reason this is not a one-line addition: a yield is a suspension
        # point, and a client that hangs up exactly here would otherwise throw
        # `GeneratorExit` past the `finally` that stops the pump tasks and
        # releases the listeners.
        #
        # It also makes the tests in `test_web.py` and `test_turn_visibility.py`
        # honest. They established "the subscriber is listening" with sleeps of
        # 0.05 to 0.4 seconds -- the `BACKLOG.md` B4 shape, and the reason a
        # write racing a subscription looked like a broken feed on a loaded
        # machine.
        yield ": ready\n\n"

        while not await request.is_disconnected():
            try:
                kind, item = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK)
            except TimeoutError:
                idle += DISCONNECT_CHECK
                if idle >= KEEPALIVE_SECONDS:
                    # Long enough that an intermediary might give up on us --
                    # a turn can sit silent for a minute while the model thinks.
                    yield ": keepalive\n\n"
                    idle = 0.0
                continue
            idle = 0.0
            if kind in ("approval", "activity", "extraction", "seeding", "dispatch"):
                yield f"data: {json.dumps(item)}\n\n"
                continue
            if item.aggregate_type == Topic.aggregate_type:
                payload = topic_change(item.aggregate_id, item.event)
            elif item.aggregate_type in KNOWLEDGE_CATEGORIES:
                # `tenant_id`, not `aggregate_id`: see `graph_change`. Read
                # directly rather than through a `getattr` default -- every
                # event in these two categories is a `TenantDomainEvent`, and
                # one that was not would be a bug worth an `AttributeError`
                # naming it rather than a frame quietly addressed to nobody.
                payload = graph_change(item.event.tenant_id, item.event)
            elif item.aggregate_type == Project.aggregate_type:
                # Same free addressing as a corpus, and for the same reason:
                # a project's aggregate id *is* the project id, so the frame
                # names its project without a read model lookup.
                payload = project_change(item.aggregate_id, item.event)
            elif item.aggregate_type == Corpus.aggregate_type:
                # A corpus shares its project's UUID, so the aggregate id is
                # the project id with no lookup -- unlike a topic, which is why
                # a topic frame carries no project at all.
                payload = corpus_change(item.aggregate_id, item.event)
            elif item.aggregate_type == MediaProposals.aggregate_type:
                # A `MediaProposals` aggregate is keyed on `project_id` alone
                # (see the aggregate's module docstring), so the aggregate id
                # is the project id with no lookup -- the same free addressing
                # `corpus_change` gets from a corpus sharing its project's
                # UUID. Without this branch these events fell to the generic
                # `feed_event` below, which sent `index: 0` and was silently
                # dropped by the frontend's log-frame branch.
                payload = media_change(item.aggregate_id, item.event)
            else:
                payload = feed_event(
                    item.aggregate_id,
                    item.event,
                    getattr(item.event, "aggregate_version", None),
                )
            # One yield, not two: an id and its data are a single SSE frame,
            # and splitting them would let a cancellation land between the
            # cursor and the event it belongs to.
            cursor = feed.encode_position(item.position)
            yield f"id: {cursor}\ndata: {json.dumps(payload)}\n\n"
    finally:
        if approvals is not None and listening is not None:
            approvals.stop_listening(listening)
        if activity is not None and watching is not None:
            activity.stop_listening(watching)
        if extraction is not None and extracting is not None:
            extraction.stop_listening(extracting)
        if seeding is not None and seeded is not None:
            seeding.stop_listening(seeded)
        if dispatch is not None and dispatching is not None:
            dispatch.stop_listening(dispatching)
        for pumping in pumps:
            pumping.cancel()
            with suppress(asyncio.CancelledError):
                await pumping
