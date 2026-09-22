"""Static assets serving and root route mounting for the web console."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

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


def mount_static_routes(app: FastAPI, *, static_dir: Path | None = None) -> None:
    """Mount static files and index handler, or 503 fallback when not built."""
    directory = static_dir if static_dir is not None else STATIC_DIR
    if directory.is_dir():
        app.mount("/static", _RevalidatedStatics(directory=directory), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            # The same `no-cache` as the assets, and for a sharper reason: this
            # is the file naming them. A cached index.html paired with rebuilt
            # assets is the mismatch that paints nothing.
            return FileResponse(
                directory / "index.html", headers={"Cache-Control": "no-cache"}
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
