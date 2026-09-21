"""System and maintenance HTTP routes.

Its own module and router, decomposing `app.py`: health reporting, summary and
corpus rebuilding, and fork tree views.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from research_team.infrastructure.persistence import CorpusRunner
from research_team.interfaces.web.presenters import tree_view
from research_team.session.application.session_service import SessionService
from research_team.session.application.summaries import build_fork_tree


@dataclass(frozen=True)
class SystemDeps:
    """Dependencies for system routes."""

    service: SessionService
    corpus: CorpusRunner | None = None


def system_router(deps: SystemDeps) -> APIRouter:
    """System and maintenance routes, ready for `app.include_router`."""
    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, Any]:
        """Whether the derived views behind this API can be trusted.

        `/sessions` is answered from a projection, so unlike a fold it can be
        wrong -- and a wrong row looks exactly like a right one. This is where
        a UI finds out to say so.
        """
        summaries = await deps.service.summaries_health()
        return {
            "summaries": {
                "healthy": summaries.healthy,
                "failed_events": summaries.failed_events,
                "following": summaries.following,
                "behind": summaries.behind,
            }
        }

    @router.post("/api/summaries/rebuild")
    async def rebuild_summaries() -> dict[str, Any]:
        """Derive the session list from the log again, and report the result.

        Exposed over HTTP because the browser is the primary surface and a
        problem you can see but not fix is only half-reported. Safe to call at
        any time: it discards derived data and recomputes it, so the worst case
        is wasted work, and the log it derives from is never touched.
        """
        await deps.service.rebuild_summaries()
        health = await deps.service.summaries_health()
        return {"healthy": health.healthy, "failed_events": health.failed_events}

    @router.post("/api/corpus/rebuild")
    async def rebuild_corpus() -> dict[str, Any]:
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
        if deps.corpus is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        await deps.corpus.rebuild()
        return {"rebuilt": True}

    @router.get("/api/tree")
    async def fork_tree() -> list[dict[str, Any]]:
        return tree_view(build_fork_tree(await deps.service.list_sessions()))

    return router
