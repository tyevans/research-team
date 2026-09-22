"""HTTP middleware for web interface endpoints."""

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

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
