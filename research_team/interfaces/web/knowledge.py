"""The Knowledge Graph, Ontology, and Media Proposal HTTP surface.

Its own module and its own router, following `topics.py`, `sources.py`,
`catalog.py`, and `dialogues.py`: `create_app` is thousands of lines of
closures and modularizing these routes extracts ~500 lines from `app.py`.
Sub-surfaces for media proposals and ontology discovery are extracted to
`media_proposals.py` and `ontology.py`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsource import AggregateRepository
from fastapi import APIRouter, FastAPI, HTTPException, Query

from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import (
    MediaProposalRunner,
    OntologyRunner,
)
from research_team.interfaces.web.media_proposals import (
    IgnoreMediaProposalBody as IgnoreMediaProposalBody,
)
from research_team.interfaces.web.media_proposals import (
    MediaProposalDeps as MediaProposalDeps,
)
from research_team.interfaces.web.media_proposals import (
    RejectMediaProposalBody as RejectMediaProposalBody,
)
from research_team.interfaces.web.media_proposals import (
    _host_of as _host_of,
)
from research_team.interfaces.web.media_proposals import (
    _media_proposal_groups as _media_proposal_groups,
)
from research_team.interfaces.web.media_proposals import (
    _media_proposal_view as _media_proposal_view,
)
from research_team.interfaces.web.media_proposals import (
    media_proposals_router as media_proposals_router,
)
from research_team.interfaces.web.media_proposals import (
    mount_media_proposals_routes as mount_media_proposals_routes,
)
from research_team.interfaces.web.ontology import (
    OntologyDeps as OntologyDeps,
)
from research_team.interfaces.web.ontology import (
    OntologyDiscoverers as OntologyDiscoverers,
)
from research_team.interfaces.web.ontology import (
    OntologyTriggerBody as OntologyTriggerBody,
)
from research_team.interfaces.web.ontology import (
    mount_ontology_routes as mount_ontology_routes,
)
from research_team.interfaces.web.ontology import (
    ontology_router as ontology_router,
)
from research_team.interfaces.web.presenters import (
    definition_view,
    entity_page_view,
    graph_view,
    neighborhood_view,
    timeline_view,
    usages_view,
)
from research_team.knowledge.application.entity_definitions import (
    DefinitionService,
    serve_citations,
)
from research_team.knowledge.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    MAX_USAGES,
    GraphReadPort,
)
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.knowledge.application.timeline_read import (
    MAX_TIMELINE_BANDS,
    TimelineInterval,
    TimelineReadPort,
)
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.media_acquisition import MediaAcceptWorker
from research_team.research.domain.media_proposals import MediaProposals

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


@dataclass(frozen=True)
class KnowledgeDeps:
    """What the knowledge graph, ontology, and media proposal routes need
    from `create_app`'s closure.

    A record rather than a long parameter list, matching `TopicDeps`, `SourceDeps`,
    `ExportDeps`, `SettingsDeps`, and `CatalogDeps`.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    media_proposals: MediaProposalRunner | None = None
    media_proposal_repository: AggregateRepository[MediaProposals] | None = None
    media_accept_worker: MediaAcceptWorker | None = None
    media_accept_tasks: set[asyncio.Task] | None = None
    graphs: ProjectGraphs | None = None
    ontology: OntologyRunner | None = None
    ontology_discoverers: OntologyDiscoverers | None = None
    definitions: DefinitionReaders | None = None
    corpus: CorpusRunner | None = None
    blob_store: BlobStorePort | None = None
    reader_of: Callable[[UUID], ProjectCorpusReader] | None = None
    graph_reader: Callable[[UUID], Awaitable[GraphReadPort]] | None = None
    timeline_reader: Callable[[UUID], Awaitable[TimelineReadPort]] | None = None
    usage_reader: Callable[[UUID], Awaitable[UsageReader]] | None = None


def knowledge_router(deps: KnowledgeDeps) -> APIRouter:
    """The knowledge graph, ontology, and media proposals router, ready for
    `app.include_router`.
    """
    router = APIRouter()

    # Mount extracted sub-routers
    router.include_router(
        media_proposals_router(
            MediaProposalDeps(
                require_project=deps.require_project,
                media_proposals=deps.media_proposals,
                media_proposal_repository=deps.media_proposal_repository,
                media_accept_worker=deps.media_accept_worker,
                media_accept_tasks=deps.media_accept_tasks,
            )
        )
    )
    router.include_router(
        ontology_router(
            OntologyDeps(
                require_project=deps.require_project,
                ontology=deps.ontology,
                ontology_discoverers=deps.ontology_discoverers,
                corpus=deps.corpus,
                blob_store=deps.blob_store,
                reader_of=deps.reader_of,
            )
        )
    )

    async def _check_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        """This project's `ProjectCorpusReader`, over the corpus and blob store.

        503 rather than 404 when `corpus`/`blob_store` was not wired, for the
        reason `catalog_of` gives: a build with no corpus read model is a
        valid thing to serve, and the caller needs to know the server cannot
        answer rather than that the project has no sources.
        """
        if deps.reader_of is not None:
            return deps.reader_of(project_id)
        if deps.corpus is None or deps.blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(deps.corpus, project_id, deps.blob_store)

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
        if deps.graph_reader is not None:
            return await deps.graph_reader(project_id)
        if deps.graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await deps.graphs.open(project_id)
        return ProjectGraphReader(project_id=project_id, store=store, ontology=deps.ontology)

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
        if deps.usage_reader is not None:
            return await deps.usage_reader(project_id)
        if deps.graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await deps.graphs.open(project_id)
        chunk_store = deps.graphs.chunks(project_id)
        if chunk_store is None:
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        return UsageReader(store, chunk_store, project_id)

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
        if deps.timeline_reader is not None:
            return await deps.timeline_reader(project_id)
        if deps.graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await deps.graphs.open(project_id)
        return ProjectTimelineReader(project_id=project_id, store=store)

    @router.get("/api/projects/{project_id}/graph")
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
        await _check_project(project_id)
        reader = await _graph_reader(project_id)
        return graph_view(await reader.whole(limit=limit))

    @router.get("/api/projects/{project_id}/graph/entities")
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
        await _check_project(project_id)
        reader = await _graph_reader(project_id)
        page = await reader.find_entities(
            name=name,
            entity_type=entity_type,
            limit=limit,
            after=str(after) if after is not None else None,
        )
        return entity_page_view(page)

    @router.get("/api/projects/{project_id}/graph/entities/{entity_id}/neighborhood")
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
        await _check_project(project_id)
        reader = await _graph_reader(project_id)
        hood = await reader.neighborhood(entity_id, depth=depth)
        if hood is None:
            raise HTTPException(
                status_code=404, detail=f"no such entity in project {project_id}"
            )
        return neighborhood_view(hood)

    @router.get("/api/projects/{project_id}/graph/entities/{entity_id}/usages")
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
        await _check_project(project_id)
        reader = await _usage_reader(project_id)
        return usages_view(await reader.usages(entity_id, limit=limit))

    @router.get("/api/projects/{project_id}/graph/entities/{entity_id}/definition")
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
        await _check_project(project_id)
        if deps.definitions is None:
            raise HTTPException(status_code=503, detail="no definition service is configured")
        service = await deps.definitions(project_id)
        if service is None:
            # A build with no chunk store cannot ground a definition in
            # passages, and a definition citing nothing is refused anyway --
            # see `definition_reader` in `composition.py`. The same 503 the
            # usages route above answers for the same absence.
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        definition = await service.define(entity_id)
        served = None
        if definition is not None and deps.corpus is not None and deps.blob_store is not None:
            # Resolved here rather than inside `DefinitionService`, so a
            # `Definition` fetched from cache is never the thing that goes
            # stale -- see `ServedCitation`'s docstring. `corpus`/`blob_store`
            # are checked rather than routed through `_reader` (which 503s):
            # a build with a definition service but no corpus read model
            # should still answer with a definition, just without moments,
            # not lose the whole route over a field it only decorates.
            served = await serve_citations(_reader(project_id), definition.citations)
        return definition_view(definition, served)

    @router.get("/api/projects/{project_id}/timeline")
    async def read_timeline(
        project_id: UUID,
        entity_type: str | None = None,
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
        await _check_project(project_id)
        interval = _timeline_interval(from_, to)
        reader = await _timeline_reader(project_id)
        return timeline_view(
            await reader.timeline(entity_type=entity_type, interval=interval, limit=limit)
        )

    return router


def mount_knowledge_routes(app: FastAPI, deps: KnowledgeDeps) -> None:
    """Mount the knowledge router on the given FastAPI app."""
    app.include_router(knowledge_router(deps))


__all__ = [
    "DefinitionReaders",
    "IgnoreMediaProposalBody",
    "KnowledgeDeps",
    "MediaProposalDeps",
    "OntologyDeps",
    "OntologyDiscoverers",
    "OntologyTriggerBody",
    "RejectMediaProposalBody",
    "_host_of",
    "_media_proposal_groups",
    "_media_proposal_view",
    "knowledge_router",
    "media_proposals_router",
    "mount_knowledge_routes",
    "mount_media_proposals_routes",
    "mount_ontology_routes",
    "ontology_router",
]
