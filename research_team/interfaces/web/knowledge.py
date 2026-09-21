"""The Knowledge Graph, Ontology, and Media Proposal HTTP surface.

Its own module and its own router, following `topics.py`, `sources.py`,
`catalog.py`, and `dialogues.py`: `create_app` is thousands of lines of
closures and modularizing these routes extracts ~500 lines from `app.py`.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from eventsource import AggregateRepository, CommandRejectedError
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from research_team.application.knowledge.entity_definitions import (
    DefinitionService,
    serve_citations,
)
from research_team.application.knowledge.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    MAX_USAGES,
    GraphReadPort,
)
from research_team.application.knowledge.ontology_discovery import OntologyDiscoveryService
from research_team.application.knowledge.project_graphs import ProjectGraphs
from research_team.application.knowledge.timeline_read import (
    MAX_TIMELINE_BANDS,
    TimelineInterval,
    TimelineReadPort,
)
from research_team.application.research.media_acquisition import MediaAcceptWorker
from research_team.application.shared.blobs import BlobStorePort
from research_team.domain.research.media_proposals import (
    AcceptMediaProposal,
    IgnoreMediaAsset,
    IgnoreMediaHost,
    MediaProposals,
    RejectMediaProposal,
    UnignoreMediaAsset,
    UnignoreMediaHost,
)
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import (
    MediaProposalRow,
    MediaProposalRunner,
    OntologyRunner,
)
from research_team.interfaces.web.presenters import (
    definition_view,
    entity_page_view,
    graph_view,
    neighborhood_view,
    timeline_view,
    usages_view,
)

logger = logging.getLogger(__name__)

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


class RejectMediaProposalBody(BaseModel):
    note: str = ""


class IgnoreMediaProposalBody(BaseModel):
    grain: Literal["asset", "host"]


class OntologyTriggerBody(BaseModel):
    strict: bool = True


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

    media_accept_tasks: set[asyncio.Task] = (
        deps.media_accept_tasks if deps.media_accept_tasks is not None else set()
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

    @router.get("/api/projects/{project_id}/media-proposals")
    async def list_media_proposals(project_id: UUID):
        """Every proposal in the project, grouped by the need that produced it.

        Empty rather than 503 when `media_proposals` was not wired: a build
        with no proposal read model has no proposals to show, which is a
        legitimate state for a project that has never run the chain, matching
        `get_dispatch`'s reasoning for its own optional dependency above.
        """
        await _check_project(project_id)
        if deps.media_proposals is None:
            return []
        return _media_proposal_groups(await deps.media_proposals.for_project(project_id))

    @router.post("/api/projects/{project_id}/media-proposals/{proposal_id}/accept")
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
        await _check_project(project_id)
        if deps.media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await deps.media_proposal_repository.load_or_create(project_id)
        try:
            aggregate.execute(
                AcceptMediaProposal(project_id=str(project_id), proposal_id=proposal_id)
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await deps.media_proposal_repository.save(aggregate)

        if deps.media_accept_worker is not None:

            async def _run_accept_worker() -> None:
                try:
                    await deps.media_accept_worker.run(proposal_id)
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

    @router.post("/api/projects/{project_id}/media-proposals/{proposal_id}/reject")
    async def reject_media_proposal(
        project_id: UUID, proposal_id: str, body: RejectMediaProposalBody | None = None
    ):
        """Close the record without touching `ignored_assets`/`ignored_hosts`
        -- see the module docstring's "Rejecting is not blacklisting". The
        note is optional because most rejections are obvious, matching
        `MediaProposalRejected`'s own reasoning.
        """
        await _check_project(project_id)
        if deps.media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await deps.media_proposal_repository.load_or_create(project_id)
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
        await deps.media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "status": "rejected"}

    @router.post("/api/projects/{project_id}/media-proposals/{proposal_id}/ignore")
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
        await _check_project(project_id)
        if deps.media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await deps.media_proposal_repository.load_or_create(project_id)
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
        await deps.media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "grain": body.grain}

    @router.delete("/api/projects/{project_id}/ignored/{grain}/{key:path}")
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
        await _check_project(project_id)
        if deps.media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await deps.media_proposal_repository.load_or_create(project_id)
        command = (
            UnignoreMediaAsset(project_id=str(project_id), asset_key=key)
            if grain == "asset"
            else UnignoreMediaHost(project_id=str(project_id), host=key)
        )
        try:
            aggregate.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await deps.media_proposal_repository.save(aggregate)
        return {"grain": grain, "key": key}

    @router.get("/api/projects/{project_id}/ignored")
    async def get_ignored(project_id: UUID):
        """Both ignore lists at once -- the pane that shows one shows both.

        Empty rather than 503 when unwired, matching `list_media_proposals`.
        """
        await _check_project(project_id)
        if deps.media_proposals is None:
            return {"assets": [], "hosts": []}
        return {
            "assets": sorted(await deps.media_proposals.ignored_assets(project_id)),
            "hosts": sorted(await deps.media_proposals.ignored_hosts(project_id)),
        }

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

    @router.post("/api/projects/{project_id}/sources/{source_id}/ontology")
    async def discover_ontology(
        project_id: UUID,
        source_id: str,
        strict: bool = True,
        body: OntologyTriggerBody | None = None,
    ):
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
        await _check_project(project_id)
        if deps.ontology_discoverers is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        actual_strict = (
            body.strict if body is not None and "strict" in body.model_fields_set else strict
        )
        found = await deps.ontology_discoverers(project_id).discover(
            source_id, strict=actual_strict
        )
        return {"sourceId": source_id, "found": found}

    @router.get("/api/projects/{project_id}/ontology")
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
        await _check_project(project_id)
        if deps.ontology is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        classes = []
        for row in await deps.ontology.classes_for(project_id):
            members = await deps.ontology.members_for(row.id)
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

    @router.get("/api/projects/{project_id}/timeline")
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
