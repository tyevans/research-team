"""What `/` serves, built and unbuilt.

The built console lives in `research_team/interfaces/web/static` and is no
longer committed (`.gitignore` carries why), so a fresh clone reaches this path
before it reaches the UI. The value here is the *message*: with the `else`
branch in `create_app` reverted, `/` answers a bare 404, which reads as a
broken route rather than an unbuilt frontend -- a blank page either way. Run
red against that revert rather than trusted green.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from research_team.interfaces.web import app as web_app


@pytest.fixture
def unbuilt(monkeypatch, tmp_path) -> TestClient:
    # A directory that does not exist, rather than an empty one: an empty
    # `static/` is what a half-finished build leaves, and mounting it would
    # serve an index.html that is not there. `is_dir()` is the check under
    # test, and this is the state a clone actually starts in.
    monkeypatch.setattr(web_app, "STATIC_DIR", tmp_path / "never-built")
    return TestClient(
        web_app.create_app(service=Mock(), feed=Mock(), turns=Mock()),
        raise_server_exceptions=False,
    )


def test_a_clone_with_no_built_console_is_told_how_to_build_it(
    unbuilt: TestClient,
) -> None:
    response = unbuilt.get("/")

    # 503 rather than 404: the route exists and the dependency it serves does
    # not, which is the same shape as every other unwired-feature answer here.
    assert response.status_code == 503
    assert "npm run build" in response.text


@pytest.fixture
def built(monkeypatch, tmp_path) -> TestClient:
    """A console that exists, without requiring anyone to have run a build.

    This case used to live in `test_web.py` as `test_index_is_served`, mounting
    the real `STATIC_DIR`. That worked only while the built console was
    committed; once untracked it asserted 200 and got the 503 below, in a job
    that has no Node toolchain and so cannot produce the thing it was waiting
    for. What it actually tests is the route -- that `/` returns the console's
    HTML as HTML -- and a one-line `index.html` exercises that as well as a
    real build does, in every clone.
    """
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>console</title>")
    monkeypatch.setattr(web_app, "STATIC_DIR", static)
    return TestClient(
        web_app.create_app(service=Mock(), feed=Mock(), turns=Mock()),
        raise_server_exceptions=False,
    )


def test_a_built_console_is_served_at_the_root(built: TestClient) -> None:
    response = built.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
