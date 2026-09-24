"""Service construction builders for the composition root.

Constructs SessionService, supervisor roster, and project-scoped service factories,
and re-exports dialogue and content pipeline builders.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer
from langchain_core.language_models import BaseChatModel

from research_team.curriculum.application.course_authoring import CourseAuthor
from research_team.curriculum.domain.learner import LearnerProgress
from research_team.infrastructure import config
from research_team.infrastructure.agent.chat_adapters import (
    ChatModelDefinitionText,
    ChatModelOntologyText,
)
from research_team.infrastructure.agent.corpus_tools import CORPUS_PROMPT
from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT
from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT
from research_team.infrastructure.knowledge.catalog_recorder import (
    EventStoreCatalogFeatureRecorder,
)
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.ontology_chunker import (
    MarkdownAwareDocumentChunker,
)
from research_team.infrastructure.knowledge.ontology_recorder import (
    EventStoreOntologyRecorder,
)
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import (
    CorpusRunner,
    EventStoreSessionRepository,
    SessionSummaryRunner,
    TopicRunner,
    build_learner_progress_repository,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.definition_cache import ProjectDefinitionCache
from research_team.infrastructure.persistence.read_models import (
    EntityDefinitionRunner,
    OntologyRunner,
)
from research_team.infrastructure.persistence.topic_reader import ProjectTopicReader
from research_team.knowledge.application.entity_definitions import DefinitionService
from research_team.knowledge.application.knowledge_attachment import (
    KnowledgeAttachment,
)
from research_team.knowledge.application.ontology_discovery import (
    DISCOVERY_CHUNK_OVERLAP_CHARS,
    MAX_DISCOVERY_CHUNK_CHARS,
    OntologyDiscoveryService,
)
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.research_round import TopicRoundRunner
from research_team.research.application.research_run import ResearchRunDriver
from research_team.research.application.research_supervisor import ResearchSupervisor
from research_team.research.application.topic_dispatch import TopicDispatcher
from research_team.research.application.topic_read import TopicReadPort
from research_team.research.application.topic_seeding import TopicSeeder
from research_team.research.application.topics import TOPICS_PROMPT
from research_team.research.domain.run import Budget, ResearchRun
from research_team.research.domain.topic import Topic
from research_team.session.application.autonomy import FETCH_TOOL, AutonomyPolicy
from research_team.session.application.context import ContextStrategy
from research_team.session.application.ports import TurnActivityBuffer, TurnExecutor
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor
from research_team.session.application.workers import (
    DispatchesInFlight,
    ExtractionChannel,
    SummaryProjects,
    WorkerRoster,
)
from research_team.tenancy.application.grants import GrantRegistry
from research_team.wiring.content_wiring import (
    ContentPipeline,
    MediaAcquisitionWiring,
    build_content_pipeline,
    build_corpus_editor,
    build_document_extractor,
    build_media_acquisition,
    build_media_perceiver,
)
from research_team.wiring.dialogue_wiring import (
    build_ask_service,
    build_socratic_service,
)


@dataclass(frozen=True)
class SessionWiring:
    """Session service and turn supervisor."""

    service: SessionService
    turns: TurnSupervisor


def build_session_service(
    *,
    repository: EventStoreSessionRepository,
    executor: TurnExecutor,
    summaries: SessionSummaryRunner,
    system_prompt: str,
    prompt_suffix: str = "",
    context: ContextStrategy | None = None,
    tracer: Tracer | None = None,
    attachment: KnowledgeAttachment,
    graphs: ProjectGraphs | None = None,
    activity: TurnActivityBuffer | None = None,
    progress: AggregateRepository[LearnerProgress] | None = None,
) -> SessionWiring:
    """Construct SessionService and TurnSupervisor with full tool prompt support."""
    resolved_progress = (
        progress
        if progress is not None
        else build_learner_progress_repository(
            repository.store,
            repository.publisher,
            snapshot_store=repository.snapshot_store,
        )
    )
    service = SessionService(
        repository,
        executor,
        summaries,
        repository.projects,
        default_system_prompt=system_prompt + prompt_suffix,
        context=context,
        tracer=tracer,
        knowledge_prompt=(
            KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT
        ),
        attachment=attachment,
        progress=resolved_progress,
        graphs=graphs,
    )
    turns = TurnSupervisor(service, activity=activity)
    return SessionWiring(service=service, turns=turns)


@dataclass(frozen=True)
class SupervisorWiring:
    """Supervisors, dispatchers, and worker roster for autonomous execution."""

    research: ResearchSupervisor
    topic_seeder: TopicSeeder
    course_author: CourseAuthor
    dispatcher: TopicDispatcher
    workers: WorkerRoster


def build_supervisor_roster(
    *,
    service: SessionService,
    turns: TurnSupervisor,
    runs: AggregateRepository[ResearchRun],
    topics: TopicRunner,
    topic_repository: AggregateRepository[Topic],
    topic_reader: Callable[[UUID], TopicReadPort],
    policy: AutonomyPolicy,
    grants: GrantRegistry,
    summaries: SessionSummaryRunner,
    extractions: ExtractionChannel | None = None,
    dispatches: DispatchesInFlight | None = None,
    worker_roster_cls: type[WorkerRoster] | Callable[..., WorkerRoster] = WorkerRoster,
) -> SupervisorWiring:
    """Construct autonomous run driver, supervisors, dispatchers, and worker roster."""

    async def start_run(
        run_id: UUID,
        run_project_id: UUID,
        session_id: UUID,
        budget: Budget | None,
        fetch_hosts: list[str],
        fetch_budget: int,
        cancelled,
    ):
        """One autonomous run: a driver, bound to one session's turns."""
        return await ResearchRunDriver(
            runs,
            topic_repository,
            topics.queue,
            run_round=TopicRoundRunner(
                topic_repository,
                lambda prompt: turns.run(session_id, prompt),
            ),
            settle=topics.caught_up,
            grants=grants,
        ).run(
            run_project_id,
            session_id,
            budget=budget,
            fetch_hosts=fetch_hosts,
            fetch_budget=fetch_budget,
            run_id=run_id,
            cancelled=cancelled,
            autonomy_snapshot=policy.levels(),
            read_only=policy.level_for(FETCH_TOOL) != "auto",
        )

    research_supervisor = ResearchSupervisor(start_run, runs)
    topic_seeder = TopicSeeder(service, turns)
    course_author = CourseAuthor(service, turns)
    dispatcher = TopicDispatcher(service, turns, topic_reader)
    worker_roster = worker_roster_cls(
        service,
        turns=turns,
        runs=research_supervisor,
        extractions=extractions,
        dispatches=dispatches,
        summaries=SummaryProjects(summaries),
    )
    return SupervisorWiring(
        research=research_supervisor,
        topic_seeder=topic_seeder,
        course_author=course_author,
        dispatcher=dispatcher,
        workers=worker_roster,
    )


@dataclass(frozen=True)
class ProjectServiceFactories:
    """Project-scoped service and port factory callables."""

    topic_reader: Callable[[UUID], TopicReadPort]
    definition_reader: Callable[[UUID], Awaitable[DefinitionService | None]]
    ontology_discoverer: Callable[[UUID], OntologyDiscoveryService]
    catalog_recorder: Callable[[UUID], EventStoreCatalogFeatureRecorder]


def build_project_services(
    *,
    topics: TopicRunner,
    topic_repository: AggregateRepository[Topic],
    graphs: ProjectGraphs,
    ontology: OntologyRunner,
    definition_invalidation: EntityDefinitionRunner,
    corpus: CorpusRunner,
    blob_store: BlobStorePort,
    extraction_model: BaseChatModel,
    repository: EventStoreSessionRepository,
) -> ProjectServiceFactories:
    """Build project-scoped service and port factory callables."""

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

    async def definition_reader(target_project_id: UUID) -> DefinitionService | None:
        """This project's `DefinitionService`, or `None` if it cannot be built.

        Async and per-call, unlike `topic_reader` above, because two of the
        three collaborators come from `graphs.open` -- which may open a store
        and replay into it -- and none of them can be bound before a project
        id exists. `ProjectGraphs` caches the stores, so the cost of building
        one of these per request is the three adapter objects, not the opens.

        **Two lifetimes meet here and they are deliberately different.** The
        graph and chunk stores are per-project and owned by `graphs`. The
        definition cache is one SQLite table for the whole process, keyed by
        `(project_id, entity_id)`, owned by `definition_invalidation`; what is
        per-project about it is only the id `ProjectDefinitionCache` binds, so
        that no caller can reach another project's rows. Building a cache per
        project would give each one its own connection to the same table --
        the drift described where the runner is constructed.

        `None` rather than a raise when there is no chunk store
        (`AGENT_CHUNK_STORE=none`), matching what the usages route does with
        the same absence: the caller renders it as 503 "not configured",
        which is the truth. It costs nothing in definitions: with no chunk
        store there are no passages, and `DefinitionService._generate`
        refuses a passage-less entity before the model call, because a
        definition assembled from edges alone cites nothing `_verified`
        could check. A null usage reader here would buy the same `None`
        one HTTP round trip later.
        """
        # `open` before `chunks`, and the order is the whole of a bug this
        # had: `ProjectGraphs.chunks` answers `None` for a project whose
        # store has not been opened yet -- it is built during `open`, in the
        # same replay pass as the graph -- so asking first made the *first*
        # request for any project 503 with "no chunk store is configured",
        # and only that one. A reviewer's probe caught it; `_usage_reader` in
        # `app.py` had the order right and this did not.
        store = await graphs.open(target_project_id)
        chunk_store = graphs.chunks(target_project_id)
        if chunk_store is None:
            return None
        return DefinitionService(
            graph=ProjectGraphReader(
                project_id=target_project_id, store=store, ontology=ontology
            ),
            usages=UsageReader(store, chunk_store, target_project_id),
            cache=ProjectDefinitionCache(definition_invalidation, target_project_id),
            # The extraction model, not a second client -- see
            # `ChatModelDefinitionText` for why, and for what that costs.
            model=ChatModelDefinitionText(extraction_model, model_name=config.model_name()),
        )

    def ontology_discoverer(target_project_id: UUID) -> OntologyDiscoveryService:
        """This project's `OntologyDiscoveryService`.

        Synchronous and never `None`, unlike `definition_reader` above, and the
        difference is what each one needs. A definition needs the graph and the
        chunk store, so it has to await `graphs.open` and can fail when
        chunking is off. Discovery needs the document text and a model: the
        corpus reader is constructed from a runner that is already open, and
        the recorder writes to the event store directly. Nothing here can be
        absent, so there is no `None` for a route to render as 503.

        That also means the `open`-before-`chunks` ordering bug documented on
        `definition_reader` cannot occur here -- this factory does not touch
        `graphs` at all. Checked rather than assumed.
        """
        return OntologyDiscoveryService(
            corpus=ProjectCorpusReader(corpus, target_project_id, blob_store),
            # The extraction model, not a second client -- see
            # `ChatModelOntologyText` for why, and for what that costs.
            model=ChatModelOntologyText(extraction_model, model_name=config.model_name()),
            recorder=EventStoreOntologyRecorder(
                repository.store, repository.publisher, target_project_id
            ),
            # The chunk size lives with the pass rather than with the chunker:
            # it is derived from the model's context window, which is the
            # application's constraint, and the chunker has no way to know it.
            chunker=MarkdownAwareDocumentChunker(
                chunk_chars=MAX_DISCOVERY_CHUNK_CHARS,
                overlap_chars=DISCOVERY_CHUNK_OVERLAP_CHARS,
            ),
        )

    def catalog_recorder(target_project_id: UUID) -> EventStoreCatalogFeatureRecorder:
        """This project's write side for course featuring, over this
        instance's own event store and publisher -- built the same way
        `ontology_discoverer` builds its recorder, for the same reason:
        catalog events have no aggregate to consult, so the factory closes
        over the store directly rather than going through
        `AggregateRepository`."""
        return EventStoreCatalogFeatureRecorder(
            repository.store, repository.publisher, target_project_id
        )

    return ProjectServiceFactories(
        topic_reader=topic_reader,
        definition_reader=definition_reader,
        ontology_discoverer=ontology_discoverer,
        catalog_recorder=catalog_recorder,
    )


__all__ = [
    "ContentPipeline",
    "MediaAcquisitionWiring",
    "ProjectServiceFactories",
    "SessionWiring",
    "SupervisorWiring",
    "build_ask_service",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_document_extractor",
    "build_media_acquisition",
    "build_media_perceiver",
    "build_project_services",
    "build_session_service",
    "build_socratic_service",
    "build_supervisor_roster",
]
