"""The Media Proposal HTTP surface.

Extracted from `knowledge.py`: media proposal ingestion, curation decisions,
and ignore lists belong to research media curation rather than the knowledge
graph.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from eventsource import AggregateRepository, CommandRejectedError
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from research_team.infrastructure.persistence.read_models import (
    MediaProposalRow,
    MediaProposalRunner,
)
from research_team.research.application.media_acquisition import MediaAcceptWorker
from research_team.research.domain.media_proposals import (
    AcceptMediaProposal,
    IgnoreMediaAsset,
    IgnoreMediaHost,
    MediaProposals,
    RejectMediaProposal,
    UnignoreMediaAsset,
    UnignoreMediaHost,
)

logger = logging.getLogger(__name__)


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


class RejectMediaProposalBody(BaseModel):
    note: str = ""


class IgnoreMediaProposalBody(BaseModel):
    grain: Literal["asset", "host"]


@dataclass(frozen=True)
class MediaProposalDeps:
    """What media proposal routes need from the application closure."""

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    media_proposals: MediaProposalRunner | None = None
    media_proposal_repository: AggregateRepository[MediaProposals] | None = None
    media_accept_worker: MediaAcceptWorker | None = None
    media_accept_tasks: set[asyncio.Task] | None = None


def media_proposals_router(deps: MediaProposalDeps) -> APIRouter:
    """The media proposals router, ready for `app.include_router`."""
    router = APIRouter()

    media_accept_tasks: set[asyncio.Task] = (
        deps.media_accept_tasks if deps.media_accept_tasks is not None else set()
    )

    async def _check_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)

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

    return router


def mount_media_proposals_routes(app: FastAPI, deps: MediaProposalDeps) -> None:
    """Mount the media proposals router on the given FastAPI app."""
    app.include_router(media_proposals_router(deps))


__all__ = [
    "IgnoreMediaProposalBody",
    "MediaProposalDeps",
    "RejectMediaProposalBody",
    "_host_of",
    "_media_proposal_groups",
    "_media_proposal_view",
    "media_proposals_router",
    "mount_media_proposals_routes",
]
