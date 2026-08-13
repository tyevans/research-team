"""The console's assets must be revalidated, because their names are stable.

`frontend/vite.config.ts` emits `app.js` rather than `app-Bjl3iwJ5.js`, so that
a rebuild is an edit to a file rather than the deletion of one and the creation
of another -- which is what made every merge of two frontend branches produce a
rename/rename conflict per chunk. The price of a stable name is that one URL no
longer means one set of bytes, and starlette sends no `Cache-Control` of its
own, which leaves a browser free to apply heuristic freshness and reuse a chunk
it was never told had changed.

These tests are what stop that being reopened. They fail if `_RevalidatedStatics`
is dropped back to a plain `StaticFiles` -- and they were run against exactly
that to confirm they go red, rather than trusted green.
"""

import pytest
from fastapi.testclient import TestClient

from research_team.interfaces.web.app import STATIC_DIR, _RevalidatedStatics


@pytest.fixture
def client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.mount("/static", _RevalidatedStatics(directory=STATIC_DIR), name="static")
    return TestClient(app)


def _an_asset() -> str:
    """Any built file, found rather than named.

    Naming one would tie this test to a chunk that a `manualChunks` change is
    free to rename -- and the failure would read as a caching regression when it
    was nothing of the kind.
    """
    assets = STATIC_DIR / "assets"
    for path in sorted(assets.iterdir()):
        if path.suffix in {".js", ".css"}:
            return path.name
    pytest.skip(f"no built console in {assets}; run `npm run build` in frontend/")


def test_an_asset_is_served_with_no_cache(client: TestClient) -> None:
    response = client.get(f"/static/assets/{_an_asset()}")
    assert response.status_code == 200
    # `no-cache` rather than `no-store`: storing is fine and revalidating is
    # cheap. `no-store` would re-download every chunk on every load.
    assert response.headers["cache-control"] == "no-cache"


def test_revalidation_still_answers_304(client: TestClient) -> None:
    """`no-cache` must not have cost us the conditional request it exists for.

    If this returned 200 the header would be a pure download tax: the browser
    would ask every time and be sent the whole file every time.
    """
    name = _an_asset()
    first = client.get(f"/static/assets/{name}")
    again = client.get(
        f"/static/assets/{name}", headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304


def test_the_built_console_carries_no_hashed_filenames() -> None:
    """The committed output matches the no-hash build config.

    Vite's hashes are base64-ish 8-character suffixes (`app-Bjl3iwJ5.js`). One
    reappearing means `entryFileNames` grew a `[hash]` back, which silently
    undoes both the merge fix in `.gitattributes` and the reason the header
    above exists -- and nothing else would notice, because a hashed build serves
    perfectly well.
    """
    import re

    hashed = re.compile(r"-[A-Za-z0-9_-]{8}\.(js|css)$")
    offenders = [p.name for p in (STATIC_DIR / "assets").iterdir() if hashed.search(p.name)]
    assert offenders == []
