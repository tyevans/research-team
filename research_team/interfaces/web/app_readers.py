"""Project and session readers wired over domain services and persistence models."""

from uuid import UUID

from fastapi import HTTPException

from research_team.curriculum.application import CurriculumService
from research_team.curriculum.application.area_projection import GraphTooLarge
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import OntologyRunner
from research_team.interfaces.web.projects import require_project
from research_team.knowledge.application.graph_read import GraphReadPort
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.knowledge.application.timeline_read import TimelineReadPort
from research_team.platform.shared.blobs import BlobStorePort
from research_team.session.application.session_service import SessionService
from research_team.tenancy.application.project_sessions import ProjectSessions


class WebReaders:
    """Project and session readers wired over domain services and persistence models."""

    def __init__(
        self,
        service: SessionService | None = None,
        corpus: CorpusRunner | None = None,
        blob_store: BlobStorePort | None = None,
        graphs: ProjectGraphs | None = None,
        ontology: OntologyRunner | None = None,
        curriculum: CurriculumService | None = None,
        projects: ProjectSessions | None = None,
    ) -> None:
        self._service = service
        self._corpus = corpus
        self._blob_store = blob_store
        self._graphs = graphs
        self._ontology = ontology
        self._curriculum_service = curriculum
        self._projects = (
            projects
            if projects is not None
            else (
                service.project_sessions
                if service is not None and hasattr(service, "project_sessions")
                else None
            )
        )

    async def load(self, session_id: UUID):
        if self._service is None:
            raise HTTPException(status_code=404, detail=f"no session {session_id}")
        try:
            return await self._service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    async def require_project(self, project_id: UUID) -> None:
        target = self._projects if self._projects is not None else self._service
        if target is None:
            raise HTTPException(status_code=404, detail=f"no project {project_id}")
        await require_project(target, project_id)

    def reader(self, project_id: UUID) -> ProjectCorpusReader:
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
        if self._corpus is None or self._blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(self._corpus, project_id, self._blob_store)

    async def graph_reader(self, project_id: UUID) -> GraphReadPort:
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
        if self._graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await self._graphs.open(project_id)
        return ProjectGraphReader(project_id=project_id, store=store, ontology=self._ontology)

    async def timeline_reader(self, project_id: UUID) -> TimelineReadPort:
        """This project's `TimelineReadPort`, over the store `graphs` owns.

        503 rather than 404 when `graphs` was not wired, matching
        `_graph_reader`: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no timeline.

        Opens through `graphs` rather than holding its own store, so the
        timeline and the graph read the *same* store rather than two folds of
        one log that could drift apart between tabs.
        """
        if self._graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await self._graphs.open(project_id)
        return ProjectTimelineReader(project_id=project_id, store=store)

    async def co_mentions(self, project_id: UUID) -> RecordedCoMentions:
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
        if self._graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await self._graphs.open(project_id)
        index = self._graphs.co_mentions(project_id)
        if index is None:
            raise HTTPException(status_code=503, detail="no co-mention index is configured")
        return RecordedCoMentions(index, project_id, store)

    async def semantic(self, project_id: UUID) -> VectorNeighbours | None:
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
        if self._graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        await self._graphs.open(project_id)
        vectors = self._graphs.card_vectors(project_id)
        if vectors is None:
            return None
        return VectorNeighbours(vectors, tenant_id=project_id)

    async def curriculum(self, project_id: UUID):
        """This project's areas and the path through them.

        503 rather than 404 when unwired, matching `_graph_reader`: a build
        without a graph read model is a valid thing to serve, and the caller
        needs to know the *server* cannot answer rather than that the project
        has nothing to learn.
        """
        if self._curriculum_service is None:
            raise HTTPException(
                status_code=503, detail="curriculum projection is not configured"
            )
        reader = await self.graph_reader(project_id)
        try:
            return await self._curriculum_service.build(
                project_id,
                reader,
                await self.co_mentions(project_id),
                await self.semantic(project_id),
            )
        except GraphTooLarge as error:
            # 422 rather than 500: the project is fine and the server is fine;
            # the question is one this projection will not answer at this size.
            # The detail names the cap so the answer is actionable.
            raise HTTPException(status_code=422, detail=str(error)) from error
