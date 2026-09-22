"""Global art-serving routes."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from research_team.infrastructure.knowledge.svg_sanitiser import SvgSanitiser
from research_team.infrastructure.persistence.read_models import ArtStore

logger = logging.getLogger(__name__)


def art_router(art_store: ArtStore | None) -> APIRouter:
    """Build the router serving global art SVGs."""
    router = APIRouter()

    @router.get("/api/art/{art_id}.svg")
    async def read_art(art_id: UUID) -> Response:
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
            logger.warning("stored art %s failed re-sanitisation on read", art_id)
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

    return router
