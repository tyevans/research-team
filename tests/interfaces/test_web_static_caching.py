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

**They serve a synthetic asset rather than a built one.** They used to mount
the real `STATIC_DIR` and pick whichever chunk sorted first; that stopped
working when the built console was untracked, because the fixture raised
`RuntimeError: Directory ... does not exist` in a fresh clone -- before the
`pytest.skip` that was meant to cover exactly this. Reading a real build was
never the point: what is under test is the header `_RevalidatedStatics` adds
and the 304 it must still answer, neither of which cares what the bytes are.
The one assertion that did need the real output -- that no filename carries a
content hash -- now lives in `frontend/scripts/build-config.test.ts`, checked
against `vite.config.ts`, which is the source of truth a build can only follow.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_team.interfaces.web.app import _RevalidatedStatics

ASSET = "app.js"


@pytest.fixture
def client(tmp_path) -> TestClient:
    assets = tmp_path / "assets"
    assets.mkdir()
    # Content is arbitrary but must be non-empty: starlette derives the ETag
    # these tests turn on from size and mtime, and a zero-length file makes the
    # 304 assertion pass for a reason that has nothing to do with revalidation.
    (assets / ASSET).write_text("console.log('built')\n")

    app = FastAPI()
    app.mount("/static", _RevalidatedStatics(directory=tmp_path), name="static")
    return TestClient(app)


def test_an_asset_is_served_with_no_cache(client: TestClient) -> None:
    response = client.get(f"/static/assets/{ASSET}")
    assert response.status_code == 200
    # `no-cache` rather than `no-store`: storing is fine and revalidating is
    # cheap. `no-store` would re-download every chunk on every load.
    assert response.headers["cache-control"] == "no-cache"


def test_revalidation_still_answers_304(client: TestClient) -> None:
    """`no-cache` must not have cost us the conditional request it exists for.

    If this returned 200 the header would be a pure download tax: the browser
    would ask every time and be sent the whole file every time.
    """
    first = client.get(f"/static/assets/{ASSET}")
    again = client.get(
        f"/static/assets/{ASSET}", headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
