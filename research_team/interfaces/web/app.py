"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import logging

from eventsource.application.aggregates.repository import AggregateRepository
from fastapi import FastAPI

from research_team.curriculum.application import CurriculumService
from research_team.curriculum.application.course_authoring import CourseAuthor
from research_team.curriculum.application.course_catalog import (
    ArtGeneratorPort,
    BlurbTextPort,
    CatalogService,
    OutlineTextPort,
)
from research_team.curriculum.application.course_realization import CourseService
from research_team.curriculum.application.learner_progress import LearnerProgressService
from research_team.curriculum.domain.course import Course
from research_team.dialogue.application.ask import AskService
from research_team.dialogue.application.socratic import SocraticDialogueService
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.read_models import (
    ArtStore,
    AskConversationRunner,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.app_readers import WebReaders as WebReaders
from research_team.interfaces.web.approvals import WebApprovals
from research_team.interfaces.web.art import art_router as art_router
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
from research_team.interfaces.web.grading import grading_router
from research_team.interfaces.web.middleware import (
    INTERACTION_BODY_LIMIT_BYTES as INTERACTION_BODY_LIMIT_BYTES,
)
from research_team.interfaces.web.middleware import (
    _InteractionBodyCap as _InteractionBodyCap,
)
from research_team.interfaces.web.presenters import summary_view
from research_team.interfaces.web.seeding import SeedingActivity
from research_team.interfaces.web.settings import SettingsDeps, settings_router
from research_team.interfaces.web.sources import SourceDeps, source_router
from research_team.interfaces.web.statics import (
    STATIC_DIR as STATIC_DIR,
)
from research_team.interfaces.web.statics import (
    _RevalidatedStatics as _RevalidatedStatics,
)
from research_team.interfaces.web.statics import (
    mount_static_routes as mount_static_routes,
)
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
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.blobs import BlobStorePort
from research_team.platform.shared.live_feed import LiveFeed
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.document_extraction import DocumentExtractor
from research_team.research.application.media_acquisition import (
    MAX_UPLOAD_BYTES as MAX_UPLOAD_BYTES,
)
from research_team.research.application.media_acquisition import MediaAcceptWorker
from research_team.research.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.research.application.perception import (
    MediaPerceiver,
    PerceptionPort,
)
from research_team.research.application.topic_dispatch import (
    TopicDispatcher,
)
from research_team.research.application.topic_seeding import TopicSeeder
from research_team.research.domain.media_proposals import MediaProposals
from research_team.research.domain.topic import Topic
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor
from research_team.session.application.workers import WorkerRoster
from research_team.tenancy.application.project_sessions import ProjectSessions
from research_team.tenancy.application.project_summaries import ProjectSummaries

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
    projects: ProjectSessions | None = None,
    learner_progress: LearnerProgressService | None = None,
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

    resolved_projects = (
        projects
        if projects is not None
        else (
            service.project_sessions
            if service is not None and hasattr(service, "project_sessions")
            else None
        )
    )
    resolved_progress = (
        learner_progress
        if learner_progress is not None
        else (
            service.learner_progress_service
            if service is not None and hasattr(service, "learner_progress_service")
            else None
        )
    )

    readers = WebReaders(
        service=service,
        corpus=corpus,
        blob_store=blob_store,
        graphs=graphs,
        ontology=ontology,
        curriculum=curriculum,
        projects=resolved_projects,
    )

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    projects_router = project_router(
        ProjectDeps(
            projects=resolved_projects,
            service=service,
            turns=turns,
            curriculum=curriculum,
            extraction=extraction,
            reembed=reembed,
            project_summaries=project_summaries,
            require_project=readers.require_project,
        )
    )
    app.include_router(projects_router)

    app.include_router(
        source_router(
            SourceDeps(
                require_project=readers.require_project,
                corpus=corpus,
                blob_store=blob_store,
                editor=editor,
                extractor=extractor,
                extract_queue=extract_queue,
                ontology=ontology,
                perception=perception,
                perceiver=perceiver,
                extraction=extraction,
                reader_of=readers.reader,
            )
        )
    )

    app.include_router(
        topic_router(
            TopicDeps(
                require_project=readers.require_project,
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
                require_project=readers.require_project,
                media_proposals=media_proposals,
                media_proposal_repository=media_proposal_repository,
                media_accept_worker=media_accept_worker,
                graphs=graphs,
                ontology=ontology,
                ontology_discoverers=ontology_discoverers,
                definitions=definitions,
                corpus=corpus,
                blob_store=blob_store,
                reader_of=readers.reader,
                graph_reader=readers.graph_reader,
                timeline_reader=readers.timeline_reader,
            )
        )
    )

    app.include_router(
        catalog_router(
            CatalogDeps(
                require_project=readers.require_project,
                curriculum_of=readers.curriculum,
                service=service,
                turns=turns,
                curriculum=curriculum,
                graph_reader=readers.graph_reader,
                co_mentions=readers.co_mentions,
                semantic=readers.semantic,
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

    app.include_router(art_router(art_store))

    app.include_router(
        dialogue_router(
            DialogueDeps(
                require_project=readers.require_project,
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
            load=readers.load,
            progress=resolved_progress,
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
                require_project=readers.require_project,
                graph_reader=readers.graph_reader,
                curriculum_of=readers.curriculum,
                authoring=authoring,
                # Three more closures, for `format=html` only. Same reasoning
                # as the three above: each already encodes what a 503 means
                # here, and re-deriving them in `export.py` would be a second
                # opinion about whether an unwired corpus is a missing project.
                corpus_reader=readers.reader,
                definitions=definitions,
                timeline_reader=readers.timeline_reader,
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
    app.include_router(grading_router)

    mount_static_routes(app, static_dir=STATIC_DIR)

    return app
