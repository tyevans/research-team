"""The global art-serving route. Global, not project-scoped -- the
increment-3 spec's "Reuse across projects" is the whole reason
`/api/art/{art_id}.svg` lives outside `/api/projects/{id}/`."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from research_team.infrastructure.persistence.read_models import ArtStore
from research_team.interfaces.web.app import create_app

_VALID_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" fill="#123"/></svg>'
)


@pytest.fixture
async def art_store(db_path):
    opened = await ArtStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


def _client(art_store: ArtStore) -> TestClient:
    return TestClient(create_app(service=None, feed=None, turns=None, art_store=art_store))


async def test_a_stored_piece_of_art_is_served_with_the_right_headers(art_store):
    art_id = uuid4()
    await art_store.put(
        art_id,
        svg=_VALID_SVG,
        description="a rotated square",
        tags=[],
        palette="",
        created_at=datetime.now(UTC),
        source="generated",
    )

    response = _client(art_store).get(f"/api/art/{art_id}.svg")

    assert response.status_code == 200
    assert response.text == _VALID_SVG
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert (
        response.headers["content-security-policy"]
        == "default-src 'none'; style-src 'unsafe-inline'"
    )


async def test_an_unknown_id_is_404(art_store):
    response = _client(art_store).get(f"/api/art/{uuid4()}.svg")
    assert response.status_code == 404


async def test_no_art_store_configured_is_404_not_500(art_store):
    """`art_store=None` is the default `create_app` argument -- a running
    server that has not wired the art library yet must refuse cleanly
    rather than raise, matching every other optional-dependency route in
    this module."""
    client = TestClient(create_app(service=None, feed=None, turns=None))
    response = client.get(f"/api/art/{uuid4()}.svg")
    assert response.status_code == 404


async def test_a_row_that_fails_resanitisation_is_served_as_missing(art_store):
    """Belt over suspenders: a row written some other way, or by a version
    of this codebase that predates the sanitiser, must not be served just
    because it made it into the table. Written directly through `put`,
    bypassing whatever validation a real writer would have applied, to
    prove the route -- not the writer -- is what refuses it."""
    art_id = uuid4()
    await art_store.put(
        art_id,
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        "<script>alert(1)</script></svg>",
        description="a hostile row",
        tags=[],
        palette="",
        created_at=datetime.now(UTC),
        source="generated",
    )

    response = _client(art_store).get(f"/api/art/{art_id}.svg")

    assert response.status_code == 404
