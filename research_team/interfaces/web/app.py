"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from eventsource import CommandRejectedError, OptimisticLockError
from eventsource.application.aggregates.repository import AggregateRepository
from fastapi import (
    FastAPI,
    HTTPException,
    Query,
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
from pydantic import BaseModel, Field
from starlette.datastructures import Headers

from research_team.application import (
    ApprovalDecision,
    AutonomyPolicy,
    LiveFeed,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
    WorkerRoster,
    build_fork_tree,
)
from research_team.application.area_projection import GraphTooLarge
from research_team.application.ask import AskService
from research_team.application.blobs import BlobStorePort
from research_team.application.components import View, parse_document, project
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
from research_team.application.entity_definitions import DefinitionService, serve_citations
from research_team.application.grading import GradingError, grade
from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    MAX_USAGES,
    GraphReadPort,
)
from research_team.application.knowledge import KnowledgeError
from research_team.application.media_acquisition import MAX_UPLOAD_BYTES as MAX_UPLOAD_BYTES
from research_team.application.media_acquisition import MediaAcceptWorker
from research_team.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.application.ontology_discovery import OntologyDiscoveryService
from research_team.application.perception import (
    MediaPerceiver,
    PerceptionPort,
)
from research_team.application.project_graphs import ProjectGraphs
from research_team.application.project_summaries import ProjectSummaries
from research_team.application.socratic import SocraticDialogueService
from research_team.application.timeline_read import (
    MAX_TIMELINE_BANDS,
    TimelineInterval,
    TimelineReadPort,
)
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
from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    IgnoreMediaAsset,
    IgnoreMediaHost,
    MediaProposals,
    RejectMediaProposal,
    UnignoreMediaAsset,
    UnignoreMediaHost,
)
from research_team.domain.topic import Topic
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours
from research_team.infrastructure.knowledge.svg_sanitiser import SvgSanitiser
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.event_store import KNOWLEDGE_CATEGORIES
from research_team.infrastructure.persistence.read_models import (
    ArtStore,
    AskConversationRunner,
    MediaProposalRow,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import UnknownApproval, WebApprovals
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
    Attempt,
    DialogueDeps,
    dialogue_router,
)
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.export import ExportDeps, export_router
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.interfaces.web.presenters import (
    autonomy_view,
    corpus_change,
    definition_view,
    entity_page_view,
    event_rows,
    feed_event,
    file_history,
    graph_change,
    graph_view,
    item_view,
    media_change,
    neighborhood_view,
    progress_view,
    project_change,
    project_detail_view,
    project_view,
    reading_head,
    session_view,
    summary_view,
    timeline_view,
    topic_change,
    tree_view,
    usages_view,
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

OntologyDiscoverers = Callable[[UUID], OntologyDiscoveryService]
"""One project's `OntologyDiscoveryService`, built on demand.

A callable for `TopicReaders`' reason -- the project is bound at construction,
so no caller can run a pass against a project it was not handed.

Synchronous and never `None`, unlike `DefinitionReaders` below, and the
difference is what each needs. A definition is assembled from a project's graph
store and chunk store, so building one is asynchronous and can fail when
chunking is off. Discovery needs the document text and a model; neither can be
absent, so there is no `None` for a route to render as 503.
"""


DefinitionReaders = Callable[[UUID], Awaitable["DefinitionService | None"]]
"""One project's `DefinitionService`, built on demand, or `None` when this
build cannot make one.

A callable for `TopicReaders`' reason, awaitable for one more: a
`DefinitionService` is assembled from that project's graph store, that
project's chunk store and a project-bound view of the definition cache, and
opening the graph store is asynchronous. `project_id` is in the route's path
and has to reach all three -- a single shared `DefinitionService` would
answer every project out of whichever one it was built for, and because the
cache port takes no project argument (deliberately; see
`application/entity_definitions.py`) it would write those answers into that
project's rows too."""

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


class NewTurn(BaseModel):
    input: str


class NewFork(BaseModel):
    at: int


class NewProject(BaseModel):
    name: str


class JoinOptions(BaseModel):
    """Whether a join may end the session currently holding the project."""

    take_over: bool = False


class ChecklistState(BaseModel):
    """Which boxes are ticked on one checklist, addressed like an `Attempt`.

    Absolute rather than a toggle: the client sends the full set every time, so
    a dropped request costs one stale render rather than a box that is ticked
    in the log and clear on the screen forever.
    """

    path: str
    component_id: str
    checked: list[int] = Field(default_factory=list)
    at: int | None = None


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


class Decision(BaseModel):
    """A human's answer to a parked approval. `type` is langchain's vocabulary."""

    type: str
    edited_args: dict | None = None
    message: str | None = None


class AutonomyChoice(BaseModel):
    """One tool's new autonomy level.

    Both fields are plain `str` rather than the `Level` literal and a tool
    enum, so that a bad value reaches `AutonomyPolicy.set` and comes back as
    that method's own complaint -- which names the offending value and says
    whether the problem was the level or the tool. FastAPI's 422 for a
    `Literal` mismatch is machine-readable and says neither, and this is a
    message a person reads off a switch they just flipped.
    """

    tool: str
    level: str


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

    # Strong references for `accept_media_proposal`'s fire-and-forget worker
    # runs (Task 11b). `asyncio.create_task` only *weakly* holds its task --
    # nothing else in this closure keeps one alive -- and the event loop is
    # free to garbage-collect a task nobody references, mid-download, with no
    # warning beyond a `Task was destroyed but it is pending` log line. Kept
    # here rather than on `app.state` because nothing outside this module
    # needs to see it; discarded from its own completion callback so the set
    # does not grow for the life of the process.
    media_accept_tasks: set[asyncio.Task] = set()

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

    def _media_proposal_view(row: MediaProposalRow) -> dict[str, Any]:
        return {
            "proposal_id": row.proposal_id,
            "need_id": row.need_id,
            "topic_id": row.topic_id,
            "page_url": row.page_url,
            "asset_url": row.asset_url,
            "thumbnail_url": row.thumbnail_url or None,
            "kind": row.kind,
            "title": row.title,
            "reason": row.reason,
            "query": row.query,
            "status": row.status,
            "note": row.note or None,
            "source_id": row.source_id,
            "error": row.error,
        }

    def _media_proposal_groups(rows: list[MediaProposalRow]) -> list[dict[str, Any]]:
        """Rows grouped by need, each group labelled with `need_description`.

        A `dict` keyed by `need_id` rather than a `groupby` over a sorted
        list: `for_project`'s rows already arrive in one project's insertion
        order, and a `dict`'s insertion-order iteration preserves that --
        "the order proposals were found in" -- without a sort that would
        reorder them by an id nobody chose for display.
        """
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            group = groups.setdefault(
                row.need_id,
                {
                    "need_id": row.need_id,
                    "need_description": row.need_description,
                    "proposals": [],
                },
            )
            group["proposals"].append(_media_proposal_view(row))
        return list(groups.values())

    def _host_of(url: str) -> str:
        """Duplicated from `domain/media_proposals.py`'s own `_host_of`
        rather than imported: that function is private to the aggregate
        module, for the same reason `application/media_curation.py` gives its
        own copy -- this must agree with `decide`'s key derivation or an
        asset ignored here by host could still be proposed there.
        """
        return (urlsplit(url).hostname or "").lower()

    @app.get("/api/projects/{project_id}/media-proposals")
    async def list_media_proposals(project_id: UUID):
        """Every proposal in the project, grouped by the need that produced it.

        Empty rather than 503 when `media_proposals` was not wired: a build
        with no proposal read model has no proposals to show, which is a
        legitimate state for a project that has never run the chain, matching
        `get_dispatch`'s reasoning for its own optional dependency above.
        """
        await _require_project(project_id)
        if media_proposals is None:
            return []
        return _media_proposal_groups(await media_proposals.for_project(project_id))

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/accept")
    async def accept_media_proposal(project_id: UUID, proposal_id: str):
        """Record the decision, then hand the download off to `MediaAcceptWorker`.

        Still 202, and still answered before anything is fetched: the append
        below is the only part this request waits on. `MediaAcceptWorker.run`
        is scheduled with `asyncio.create_task` rather than awaited, because it
        downloads and perceives -- an hour of audio is minutes of transcription
        -- and a route that waited on that would be a route that times out.
        `media_accept_tasks` is what keeps the scheduled task alive; see its
        comment above `create_app`'s body for why a bare `create_task` is not
        enough on its own.

        No queue, unlike `ExtractionQueue`/`DispatchQueue`: those serialize
        because running two of a kind at once means racing writes to a shared
        resource (one extraction pass per project) or asking twice for the same
        research. An accept has neither problem -- each proposal downloads and
        stores into its own corpus row, `source_id=proposal_id`, so two accepts
        for two different proposals racing costs nothing a queue would have
        saved. `MediaAcceptWorker`'s own docstring is what makes even the
        crash-and-retry case safe without one.

        A logged exception, not a crashed task, is where a bug in the worker
        that is *not* one of its four named refusals ends up: nothing awaits
        this task, so nothing else would ever see it raise.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        try:
            aggregate.execute(
                AcceptMediaProposal(project_id=str(project_id), proposal_id=proposal_id)
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)

        if media_accept_worker is not None:

            async def _run_accept_worker() -> None:
                try:
                    await media_accept_worker.run(proposal_id)
                except Exception:
                    logger.exception(
                        "media accept worker failed for proposal %s in project %s",
                        proposal_id,
                        project_id,
                    )

            task = asyncio.create_task(_run_accept_worker())
            media_accept_tasks.add(task)
            task.add_done_callback(media_accept_tasks.discard)

        return JSONResponse(
            status_code=202, content={"proposal_id": proposal_id, "status": "accepted"}
        )

    class RejectMediaProposalBody(BaseModel):
        note: str = ""

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/reject")
    async def reject_media_proposal(
        project_id: UUID, proposal_id: str, body: RejectMediaProposalBody | None = None
    ):
        """Close the record without touching `ignored_assets`/`ignored_hosts`
        -- see the module docstring's "Rejecting is not blacklisting". The
        note is optional because most rejections are obvious, matching
        `MediaProposalRejected`'s own reasoning.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        try:
            aggregate.execute(
                RejectMediaProposal(
                    project_id=str(project_id),
                    proposal_id=proposal_id,
                    note=(body.note if body is not None else ""),
                )
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "status": "rejected"}

    class IgnoreMediaProposalBody(BaseModel):
        grain: Literal["asset", "host"]

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/ignore")
    async def ignore_media_proposal(
        project_id: UUID, proposal_id: str, body: IgnoreMediaProposalBody
    ):
        """Ignore the asset or host behind one proposal, keyed off the
        proposal's own recorded `asset_url` -- not a second identifier the
        caller has to already know, unlike `DELETE .../ignored/{grain}/{key}`
        below, which exists precisely for the case where they do (the ignore
        lists, with no proposal attached).

        404 for an unknown `proposal_id`: `decide`'s `IgnoreMediaAsset` and
        `IgnoreMediaHost` cases carry no unknown-id guard of their own (the
        module's transition table only guards commands that name a proposal
        directly), so this route checks existence itself before deriving a
        key from a record that is not there -- a `CommandRejectedError`
        never gets the chance to fire, so there is nothing to map to 409.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        record = aggregate.state.proposals.get(proposal_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"no proposal {proposal_id!r} in project {project_id}"
            )
        command = (
            IgnoreMediaAsset(project_id=str(project_id), asset_key=record.asset_url)
            if body.grain == "asset"
            else IgnoreMediaHost(project_id=str(project_id), host=_host_of(record.asset_url))
        )
        try:
            aggregate.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "grain": body.grain}

    @app.delete("/api/projects/{project_id}/ignored/{grain}/{key:path}")
    async def unignore_media(project_id: UUID, grain: Literal["asset", "host"], key: str):
        """Reverse an ignore at either grain, by the same key `GET .../ignored`
        reports -- see the module docstring's "both are reversible".

        `{key:path}` rather than the default converter: an asset key is a
        whole URL (`normalize_url`'s output), which contains `/`, and the
        default converter stops at the first one -- `example.com/pic.jpg`
        would 404 as an unmatched route rather than reach this handler. A
        host key never contains `/`, but the same converter serves both
        grains rather than branching the route in two.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        command = (
            UnignoreMediaAsset(project_id=str(project_id), asset_key=key)
            if grain == "asset"
            else UnignoreMediaHost(project_id=str(project_id), host=key)
        )
        try:
            aggregate.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"grain": grain, "key": key}

    @app.get("/api/projects/{project_id}/ignored")
    async def get_ignored(project_id: UUID):
        """Both ignore lists at once -- the pane that shows one shows both.

        Empty rather than 503 when unwired, matching `list_media_proposals`.
        """
        await _require_project(project_id)
        if media_proposals is None:
            return {"assets": [], "hosts": []}
        return {
            "assets": sorted(await media_proposals.ignored_assets(project_id)),
            "hosts": sorted(await media_proposals.ignored_hosts(project_id)),
        }

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

    @app.get("/api/projects/{project_id}/graph")
    async def read_graph(project_id: UUID, limit: int = MAX_GRAPH_NODES):
        """This project's whole graph, so a browser has something to draw
        before the reader knows what to search for.

        `limit` is clamped by the port rather than refused here, which is the
        opposite of what `neighborhood` does with `depth` -- the two asks are
        different. A depth past the bound is a request for a *shape* of answer
        the server will not produce, and the caller needs to know its question
        was the wrong one. A limit past the bound is a request for as much as
        possible, and "as much as possible" is precisely what the clamp
        returns; `truncated` in the body already says the graph did not fit,
        so there is nothing a 422 would tell the caller that the answer does
        not.
        """
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        return graph_view(await reader.whole(limit=limit))

    @app.get("/api/projects/{project_id}/graph/entities")
    async def list_graph_entities(
        project_id: UUID,
        name: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        after: UUID | None = None,
    ):
        """Entry points into this project's graph: entities matching every filter given.

        `after` is typed as `UUID | None` rather than `str | None` so FastAPI
        rejects a malformed cursor with a 422 before it ever reaches the
        reader -- `neighborhood`'s `entity_id` handles the identical problem
        with a try/except because it takes a path segment FastAPI cannot
        type-check for it; a query parameter does not need that fallback.
        """
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        page = await reader.find_entities(
            name=name,
            entity_type=entity_type,
            limit=limit,
            after=str(after) if after is not None else None,
        )
        return entity_page_view(page)

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/neighborhood")
    async def read_graph_neighborhood(project_id: UUID, entity_id: str, depth: int = 1):
        """`entity_id` and what lies within `depth` hops of it, fully wired.

        A `depth` above `MAX_NEIGHBORHOOD_DEPTH` is refused with a 422 here,
        even though `GraphReadPort.neighborhood` clamps the same bound on its
        own -- see that port's docstring. The two are not redundant: the
        port's clamp protects every present and future in-process caller from
        an oversized traversal regardless of what sits above it, while this
        check exists for the one caller that can be told it made a mistake.
        Clamping silently here would spend the request answering a question
        nobody asked instead of saying which question was too big.
        """
        if depth > MAX_NEIGHBORHOOD_DEPTH:
            raise HTTPException(
                status_code=422,
                detail=f"depth {depth} exceeds the maximum of {MAX_NEIGHBORHOOD_DEPTH}",
            )
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        hood = await reader.neighborhood(entity_id, depth=depth)
        if hood is None:
            raise HTTPException(
                status_code=404, detail=f"no such entity in project {project_id}"
            )
        return neighborhood_view(hood)

    async def _usage_reader(project_id: UUID) -> UsageReader:
        """This project's `UsageReadPort`, over the graph and chunk stores
        `graphs` already owns.

        503 rather than 404 when either store is unwired, matching
        `_graph_reader`: a build with chunking off (`AGENT_CHUNK_STORE=none`)
        is a valid thing to serve, and the caller needs to know the server
        cannot answer rather than that the entity has no usages.

        `open` first, the same call `_graph_reader` makes: it is what builds
        this project's chunk store on first use (see `ProjectGraphs.open`),
        and it is idempotent, so a usages request that lands before any graph
        route has still opened the project gets a store rather than a 503
        that only means "nobody happened to ask for the graph yet".
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        chunk_store = graphs.chunks(project_id)
        if chunk_store is None:
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        return UsageReader(store, chunk_store, project_id)

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/usages")
    async def read_graph_usages(project_id: UUID, entity_id: UUID, limit: int = MAX_USAGES):
        """Passages naming `entity_id`, best matches first.

        A separate endpoint from the entity definition that follows in a
        later task, not a field folded into the same response: a definition
        may cost an LLM call, usages are a cheap deterministic BM25 lookup
        over an already-open chunk store, and a combined endpoint would make
        every caller wait for the slow half to get the fast one.

        `limit` above `MAX_USAGES` is refused with 422 rather than clamped,
        unlike `whole`'s `limit` -- see `MAX_USAGES`'s docstring for why the
        two asks are different.
        """
        if limit > MAX_USAGES:
            raise HTTPException(
                status_code=422,
                detail=f"limit {limit} exceeds the maximum of {MAX_USAGES}",
            )
        await _require_project(project_id)
        reader = await _usage_reader(project_id)
        return usages_view(await reader.usages(entity_id, limit=limit))

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/definition")
    async def read_graph_definition(project_id: UUID, entity_id: UUID):
        """`entity_id`'s grounded definition, generated on first ask and
        cached from then on -- see `DefinitionService.define`.

        **503 only when nothing is wired.** `definitions` is now supplied by
        the composition root (`Application.definition_readers`), so the
        503 below means a caller built this app without it -- a test fixture,
        or a build with no chunk store, which is the second 503 further down.
        It is a factory rather than one service because the cache, the graph
        and the chunk store behind it are all bound to `project_id`; see
        `DefinitionReaders`.

        **200 with a null `text`, not 404, when `define` returns `None`.**
        `entity_id` is a real node in the graph; it is merely undefinable
        today because nothing was found to ground a definition in (no
        passages, no edges -- see `DefinitionService.define`'s docstring). A
        404 would tell the caller the entity itself does not exist, which is
        a different and wrong statement, and one the browser would act on by
        treating the node as gone rather than merely lacking a summary. Do
        not "fix" this to a 404 without re-reading that reasoning -- it is
        the deliberate case a later reader is likely to trip on, which is why
        it is spelled out here as well as in the service.

        No `force=True` here -- this route only reads. Regeneration is a
        separate concern (Task 12's retrigger), not something a GET should
        cause as a side effect the caller did not ask for.

        **Synchronous, deliberately, unlike extraction.** `ExtractionQueue`
        exists because extraction is long-running and a request that loses a
        queued extraction loses an intention the caller cannot easily
        re-express (BACKLOG B62). A definition is seconds of work, produces
        the same answer from the same inputs, and a failed or interrupted
        request costs the caller nothing but a second click -- so the entire
        retry story is "click again", and a durable queue here would be
        machinery bought for a payoff nobody would notice.
        """
        await _require_project(project_id)
        if definitions is None:
            raise HTTPException(status_code=503, detail="no definition service is configured")
        service = await definitions(project_id)
        if service is None:
            # A build with no chunk store cannot ground a definition in
            # passages, and a definition citing nothing is refused anyway --
            # see `definition_reader` in `composition.py`. The same 503 the
            # usages route above answers for the same absence.
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        definition = await service.define(entity_id)
        served = None
        if definition is not None and corpus is not None and blob_store is not None:
            # Resolved here rather than inside `DefinitionService`, so a
            # `Definition` fetched from cache is never the thing that goes
            # stale -- see `ServedCitation`'s docstring. `corpus`/`blob_store`
            # are checked rather than routed through `_reader` (which 503s):
            # a build with a definition service but no corpus read model
            # should still answer with a definition, just without moments,
            # not lose the whole route over a field it only decorates.
            served = await serve_citations(_reader(project_id), definition.citations)
        return definition_view(definition, served)

    @app.post("/api/projects/{project_id}/sources/{source_id}/ontology")
    async def discover_ontology(project_id: UUID, source_id: str, strict: bool = True):
        """Read one document for the classes it states. 200, because it has run.

        **Synchronous, unlike extraction, and for `read_graph_definition`'s
        reason.** `ExtractionQueue` exists because extraction is long-running
        and a request that loses a queued extraction loses an intention the
        caller cannot easily re-express. A discovery pass is one model call over
        one document, produces the same answer from the same inputs, and a
        failed request costs the caller a second click -- so the whole retry
        story is "click again".

        It also *could not* reuse that queue as it stands. `ExtractionQueue`
        deduplicates on `(project_id, source_id)` and reads
        `report.entity_count` off whatever it awaited, so queuing a pass for a
        document already queued for extraction would be silently dropped and
        answered `queued: false` -- which the client reads as "this is going to
        happen", when what is going to happen is the extraction, not the pass.
        Making it fit means changing a component another lane owns.

        **`strict=false` reads the document under the weaker rule** that
        `verify_classes` documents: a class whose quoted sentence is not in the
        text survives if all its members are, cited to the first member's
        occurrence and flagged `evidenceQuoted: false` on the way back out.
        Default true, because a reader who has not asked for it must not be
        handed classes the document may never have grouped.

        A query parameter and not a body field, on a POST, which is the odd
        choice here. The body is `{}` and stays that way: this route already
        carries its subject in the path, and a caller reading the URL sees the
        whole request -- which matters more than usual for a lever whose two
        settings answer different questions about the same document.

        **`found: null` rather than 404 when the pass declines.** The three
        declines -- an unreadable reply, a document over
        `MAX_DISCOVERY_CHARS`, and a source that is not there -- are told apart
        above by the 404 and below by nothing, deliberately: see
        `OntologyDiscoveryService.discover`. `found: 0` is a different answer
        again, and the important one to keep distinct: it means the document was
        read and states no classes.
        """
        await _require_project(project_id)
        if ontology_discoverers is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        found = await ontology_discoverers(project_id).discover(source_id, strict=strict)
        return {"sourceId": source_id, "found": found}

    @app.get("/api/projects/{project_id}/ontology")
    async def read_ontology(project_id: UUID):
        """Every class discovered in this project, with what it was derived from.

        **503 when the runner is unwired, not an empty 200.** An empty list is
        the correct answer for a project nobody has run a pass on, so a
        misconfigured build answering the same thing would be indistinguishable
        from a working one with nothing to show -- which is the whole failure
        this feature is arranged against, arriving at the last layer.

        Every field a reader needs to judge a class travels with it. `evidence`
        is offsets into the source document, not a quotation: the view opens the
        document there, and quoted text proves only that the model wrote a
        sentence, where opening the document proves the sentence is in it.
        `declaredCount` beside `memberCount` is the checksum, and
        `rejectedMembers` is what explains a gap between them -- a class short
        one member with no explanation cannot be judged, because an invented
        member and a document genuinely missing one look identical.
        """
        await _require_project(project_id)
        if ontology is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        classes = []
        for row in await ontology.classes_for(project_id):
            members = await ontology.members_for(row.id)
            classes.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "kind": row.kind,
                    "declaredCount": row.declared_count,
                    "memberCount": row.member_count,
                    "parentClassId": str(row.parent_class_id) if row.parent_class_id else None,
                    "evidence": {
                        "sourceId": row.source_id,
                        "start": row.evidence_start,
                        "end": row.evidence_end,
                    },
                    "rejectedMembers": json.loads(row.rejected_members),
                    # Travels beside `evidence` rather than being inferred from
                    # it, because nothing about the offsets says which they are
                    # -- a member fallback and a located sentence are both a
                    # pair of integers into the same document.
                    "evidenceQuoted": row.evidence_quoted,
                    "stale": row.stale,
                    "members": [
                        {"name": member.member_name, "ordinal": member.ordinal}
                        for member in members
                    ],
                }
            )
        return {"classes": classes}

    def _timeline_interval(from_: str | None, to: str | None) -> TimelineInterval | None:
        """`from`/`to` as an interval, or `None` when neither was given.

        `None` rather than `TimelineInterval(None, None)` for the empty case so
        the adapter passes `interval=None` to redstring and takes its
        no-window path, instead of an all-`None` `Bounds` whose behaviour is
        the library's to decide rather than ours.
        """
        if from_ is None and to is None:
            return None
        return TimelineInterval(start=_instant("from", from_), end=_instant("to", to))

    def _instant(name: str, raw: str | None) -> datetime | None:
        """One ISO query parameter as a datetime, 422 if it will not parse.

        `fromisoformat` and not `dateutil`: the client this serves is the
        browser, which produces `toISOString()` output, and accepting looser
        spellings would make the set of dates that work depend on which parser
        happened to be installed.
        """
        if raw is None:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"{name}={raw!r} is not an ISO instant"
            ) from None

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

    @app.get("/api/projects/{project_id}/timeline")
    async def read_timeline(
        project_id: UUID,
        entity_type: str | None = None,
        # `from` is a Python keyword, so the parameter is named `from_` and
        # aliased back. FastAPI's `Query` alias is the only way to spell a
        # reserved word in a signature; renaming the *wire* parameter to
        # something legal was rejected because the spec names `from`/`to` and a
        # query string is a contract with anyone holding a bookmark.
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ):
        """This project's dated entities, ordered, for drawing on an axis.

        `from`/`to` are ISO instants bounding a half-open `[from, to)` window;
        either may be omitted for an open end, and omitting both is the whole
        timeline. Strings rather than a `datetime` annotation so an
        unparseable value is *this* route's 422 with a message naming which
        parameter was wrong -- FastAPI would otherwise answer its own 422
        naming a validation error the caller has to decode. It is a 422 and
        not a silent fall-back to "no window", because a client that mistyped
        a date and got the entire timeline back has been answered a different
        question than it asked and has no way to tell.

        Project-level rather than under `/graph/` because it is not a graph
        shape: nothing in the response has a source, a target or an edge type,
        and nesting it there would suggest a client could ask for one and be
        given the other.

        `limit` is clamped by the port rather than refused here, the same call
        `read_graph` makes and for the same reason -- "as much as possible" is
        precisely what the clamp returns, and `truncated` in the body already
        says it did not all fit.
        """
        await _require_project(project_id)
        interval = _timeline_interval(from_, to)
        reader = await _timeline_reader(project_id)
        return timeline_view(
            await reader.timeline(entity_type=entity_type, interval=interval, limit=limit)
        )

    @app.post("/api/sessions/{session_id}/release")
    async def release_session(session_id: UUID):
        """Finish with this session, handing its work back to its project.

        The counterpart the web app never had. Releasing is not tidying up
        after yourself: `release_project` is what advances the project's tip
        to this session's latest event, so it is also the *only* way work
        done here reaches the next session in the project. Without it a
        project stays held by a session nobody is driving, and its filesystem
        stays frozen at whatever the previous release left behind.

        Detaching is conditional on this being the attached project, because
        one process serves many browser sessions: releasing session A must
        not pull the graph out from under a turn running in session B.
        """
        session = await _load(session_id)
        project_id = session.state.project_id
        if project_id is None:
            return {"released": False, "project_id": None}
        if turns.is_running(session_id):
            raise HTTPException(
                status_code=409,
                detail="a turn is still running on this session; cancel it first",
            )
        await service.release_project(session_id)
        if service.attached_project_id == project_id:
            await service.detach_project()
        return {"released": True, "project_id": str(project_id)}

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

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID):
        session = await _load(session_id)
        project_id = session.state.project_id
        holds = None
        if project_id is not None:
            state = await service.project_state(project_id)
            holds = state.active_session_id == session_id
        return session_view(
            session,
            await service.history(session_id),
            holds_project=holds,
            knowledge_attached=(
                None if project_id is None else service.attached_project_id == project_id
            ),
        )

    @app.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID):
        await _load(session_id)
        return event_rows(await service.history(session_id))

    @app.get("/api/sessions/{session_id}/at/{at}")
    async def get_session_at(session_id: UUID, at: int):
        """Time travel: the workspace as of event `at`. Folds, never writes."""
        try:
            session = await service.state_at(session_id, at)
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return session_view(session, await service.history(session_id), at=at)

    @app.get("/api/sessions/{session_id}/files")
    async def get_file(session_id: UUID, path: str, at: int | None = None):
        """A file's contents, at HEAD or as of event `at`.

        Scrubbing has to be able to read a file that no longer exists at HEAD --
        seeing a deleted file again is the point of time travel, not an error.
        """
        return {"path": path, "content": await _read_file(session_id, path, at), "at": at}

    @app.get("/api/sessions/{session_id}/files/history")
    async def get_file_history(session_id: UUID, path: str):
        await _load(session_id)
        return file_history(await service.history(session_id), path)

    async def _read_file(session_id: UUID, path: str, at: int | None) -> str:
        """One file's contents at HEAD or as of `at`, or a 404 saying which.

        Shared by the raw, parsed and attempt routes so the three cannot drift
        apart on what "not found at this point in the log" means. Time travel
        is not optional on any of them: a learner reading a lesson at a scrub
        point has to be graded against the lesson that was there, and an author
        diffing two revisions of a question needs both of them to parse.
        """
        if at is None:
            session = await _load(session_id)
        else:
            try:
                session = await service.state_at(session_id, at)
            except (ValueError, CommandRejectedError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        entry = session.state.files.get(path)
        if entry is None:
            moment = "at HEAD" if at is None else f"as of event {at}"
            raise HTTPException(status_code=404, detail=f"{path}: not found {moment}")
        return entry.get("content", "")

    @app.get("/api/sessions/{session_id}/files/parsed")
    async def get_file_parsed(
        session_id: UUID,
        path: str,
        at: int | None = None,
        view: View = "author",
    ):
        """A markdown file as blocks, with interactive components resolved.

        `view` is a `Literal`, so FastAPI rejects `learnr` with a 422 rather
        than falling back to a default. A typo that quietly returned the author
        view would hand back the answer key on exactly the request that meant
        to ask for it to be withheld -- the one failure mode of this route that
        is worth a hard edge.
        """
        content = await _read_file(session_id, path, at)
        return project(parse_document(content, path=path), view=view) | {"at": at}

    @app.post("/api/sessions/{session_id}/attempts")
    async def post_attempt(session_id: UUID, body: Attempt):
        """Mark one attempt. The server holds the key; the browser was not given it.

        A wrong answer is a 200 with `correct: false` -- it is a result, not an
        error. The 400s here are all malformed *requests*: a response shape the
        item cannot interpret, or an item that has no answer to mark.
        """
        content = await _read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        # Recorded after grading and before answering, so a verdict the learner
        # was shown is never one the log has no record of. The digest is of the
        # body as it stood, which is what lets a later reader see that an item
        # was rewritten under someone mid-course.
        progress = await service.record_attempt(
            session_id,
            path=body.path,
            component_id=body.component_id,
            component_type=component.type,
            digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
            response=body.response,
            correct=verdict.correct,
            score=verdict.score,
            at=body.at,
        )
        item = item_view(progress, body.path, body.component_id)
        return verdict.as_json() | {"progress": item}

    @app.get("/api/sessions/{session_id}/progress")
    async def get_progress(session_id: UUID, path: str | None = None):
        """What this learner has done, for the whole session or one file.

        `path` narrows it, because the browser asks on opening a document and
        has no use for the other twelve. Answers an empty mapping for a session
        nobody has answered anything in -- that is the ordinary case for every
        course before its first learner, not a 404.
        """
        await _load(session_id)
        state = await service.learner_progress(session_id)
        return progress_view(state, path=path)

    @app.post("/api/sessions/{session_id}/progress/checklist")
    async def post_checklist(session_id: UUID, body: ChecklistState):
        """Remember which boxes are ticked on a `persist: true` checklist.

        A separate route from `/attempts` rather than a shape of it, because a
        checklist has no answer key: there is no verdict, nothing to be right
        about, and `grade` refuses it by design. Folding the two together would
        mean an endpoint that sometimes marks and sometimes just remembers.

        `persist` is honoured rather than assumed: a checklist that did not ask
        to be remembered is a 400, so a client cannot quietly accumulate state
        the author never opted into.
        """
        content = await _read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        if component.type != "checklist":
            raise HTTPException(
                status_code=400,
                detail=f"{body.component_id!r} is a {component.type}, not a checklist",
            )
        if component.data.get("persist") is not True:
            raise HTTPException(
                status_code=400,
                detail=f"checklist {body.component_id!r} does not set `persist: true`",
            )
        items = component.data.get("items", [])
        for index in body.checked:
            if not 0 <= index < len(items):
                raise HTTPException(
                    status_code=400,
                    detail=f"there is no item {index}; this checklist has {len(items)}",
                )
        progress = await service.record_checklist(
            session_id,
            path=body.path,
            component_id=body.component_id,
            checked=list(body.checked),
        )
        return item_view(progress, body.path, body.component_id)

    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        # Re-attach per turn rather than only at join. One process serves
        # every browser session, so by the time this session takes a turn the
        # attached graph may belong to a project joined in another tab -- or,
        # after a restart, to nothing at all. A session whose recorded prompt
        # promises knowledge tools has to get them on every turn, not just the
        # request that happened to join. A no-op for a session in no project,
        # and for a graph that will not open: knowledge is degraded then, and
        # the turn is still worth running.
        try:
            await service.ensure_project_attached(session_id)
        # No `noqa` needed: ruff accepts a bare `except Exception` whose handler
        # logs it with `exc_info=True`, which is what the warning below does.
        except Exception:
            logger.warning(
                "could not attach knowledge graph for %s", session_id, exc_info=True
            )
        try:
            outcome = await turns.run(session_id, body.input)
        except TurnAlreadyRunning as error:
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        return {
            "reply": outcome.reply,
            "turn_index": outcome.turn_index,
            "from_index": outcome.from_index,
            "to_index": outcome.to_index,
        }

    @app.post("/api/sessions/{session_id}/turns/cancel")
    async def cancel_turn(session_id: UUID):
        """Stop the in-flight turn on this session, if there is one.

        Returns once the turn has actually unwound, so a caller that hears
        "cancelled" can trust the log already reflects it.
        """
        await _load(session_id)
        cancellation = await turns.cancel(session_id)
        return {
            "cancelled": cancellation.cancelled,
            "settled": cancellation.settled,
        }

    @app.get("/api/sessions/{session_id}/turns/current")
    async def current_turn(session_id: UUID):
        """What is in flight -- so a tab that arrived mid-turn can say so."""
        await _load(session_id)
        running = turns.running(session_id)
        if running is None:
            return {
                "running": False,
                "turn_index": None,
                "started_at": None,
                "elapsed_seconds": None,
            }
        return {
            "running": True,
            "turn_index": running.turn_index,
            "started_at": running.started_at.isoformat(),
            "elapsed_seconds": running.elapsed_seconds(datetime.now(UTC)),
        }

    @app.get("/api/sessions/{session_id}/turns/current/activity")
    async def current_activity(session_id: UUID):
        """What the running turn has produced so far, and what the last failed
        one threw away.

        The live feed announces each note as it arrives, but a tab that opened
        mid-turn never saw those frames -- and unlike log events they carry no
        position, so `Last-Event-ID` cannot replay them. This is how it
        catches up, exactly as `/approvals` is for a parked approval.
        """
        await _load(session_id)
        if activity is None:
            return {"running": [], "discarded": []}
        return {
            "running": activity.current(session_id),
            "discarded": activity.discarded(session_id),
        }

    @app.get("/api/sessions/{session_id}/approvals")
    async def pending_approvals(session_id: UUID):
        """Gated calls this session is waiting on.

        The live feed announces each one as it is parked, but a tab that opened
        mid-turn never saw that frame -- this is how it catches up.
        """
        await _load(session_id)
        return [] if approvals is None else approvals.pending(session_id)

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def decide_approval(session_id: UUID, approval_id: str, body: Decision):
        """Answer one parked approval, unblocking the turn waiting on it."""
        if approvals is None:
            raise HTTPException(status_code=404, detail="approvals are not wired up")
        await _load(session_id)
        try:
            approvals.resolve(
                session_id,
                approval_id,
                ApprovalDecision(
                    type=body.type,
                    edited_args=body.edited_args,
                    message=body.message,
                ),
            )
        except UnknownApproval as error:
            # Already answered, or the turn behind it was cancelled. Both are
            # races a second tab can lose honestly.
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"decided": True}

    def _policy() -> AutonomyPolicy:
        """The instance's policy, or a 404 saying this build has none.

        404 rather than a permissive default, matching `/workers`: "this build
        cannot tell you what the agent may do without asking" is a different
        claim from "everything is automatic", and a UI that read the second off
        the first would show a row of green switches for a policy it has no
        handle on.
        """
        if policy is None:
            raise HTTPException(status_code=404, detail="the autonomy policy is not wired up")
        return policy

    @app.get("/api/autonomy")
    async def get_autonomy():
        """What the agent may currently do without asking.

        No session in the path, because there is no per-session answer to give:
        one `AutonomyPolicy` serves the whole process, so this is a read of
        instance state. See the POST routes for why the *writes* name a session
        even though the state they change does not belong to one.
        """
        return autonomy_view(_policy())

    @app.post("/api/sessions/{session_id}/autonomy")
    async def set_autonomy(session_id: UUID, body: AutonomyChoice):
        """Set one tool's level, and record that it was set.

        Two steps, both required, exactly as `/autonomy` in the REPL does them.
        The policy is what the executor consults, so mutating it is what
        changes behaviour -- but a level that changed mid-session and left no
        trace makes every surrounding decision unreadable afterwards, in a
        system whose whole point is a complete audit trail. See
        `SessionService.record_autonomy_change`.

        The asymmetry is real and worth stating plainly rather than leaving to
        be discovered: **the policy is instance-wide and the record is
        per-session.** One object answers for every session in this process, so
        this call changes what the agent may do in all of them, while the
        `AutonomyChanged` event lands on this session's stream alone. That is
        what the REPL does, and it is the right trade for a local single-user
        tool -- the same trade `join_project` documents for graph attachment.
        The session in the path is therefore "who is answering for this
        change", not "where it applies". A per-session policy map would make the
        two agree, but nothing has asked for concurrent untrusted users, and
        splitting the policy would silently change what the executor consults
        for every other caller.

        A bad tool or level is a 400 carrying the policy's own message, and
        nothing is recorded: a rejected `set` changed nothing, so a log entry
        would describe a change that did not happen.
        """
        instance = _policy()
        await _load(session_id)
        try:
            instance.set(body.tool, body.level)  # type: ignore[arg-type]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await service.record_autonomy_change(session_id, body.tool, body.level)
        # The full map, so a client that just flipped one switch does not need a
        # second request to redraw the rest -- and cannot drift from the server
        # by assuming its own change was the only one.
        return autonomy_view(instance)

    @app.post("/api/sessions/{session_id}/autonomy/allow-all")
    async def allow_all_autonomy(session_id: UUID):
        """Stop asking about every hazard. No body, because there is nothing
        left to ask for.

        It used to take `include_stage_gates`, which crossed the workflow
        review gate as well. The console stopped sending it a slice before
        this and the gate itself is deleted a slice after, so the flag would
        be a switch over a tool that is on its way out. `relax_all`'s own
        parameter goes with that tool; this call takes its default until then,
        which is the behaviour a client omitting the flag already got.

        The instance-wide/per-session asymmetry described on `set_autonomy`
        applies here too, and more loudly: this relaxes every hazard for every
        session in the process, and records it on one.

        `changed` is only what actually moved, and one `AutonomyChanged` is
        recorded per entry -- never one per gated tool. A log that claimed eight
        decisions where a person made one is as unreadable as a log that
        omitted them, and it is `changed` the UI should report back so it says
        what it did rather than claiming more.
        """
        instance = _policy()
        await _load(session_id)
        changed = instance.relax_all()
        # One append, not one per tool. Each append is a chance for a turn
        # running on this session to lose its version, and this route issues
        # its writes back to back -- see `record_autonomy_changes`.
        await service.record_autonomy_changes(session_id, changed)
        return {"changed": changed} | autonomy_view(instance)

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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
