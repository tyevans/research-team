"""The route that turns a stored medium into a text source, and what it refuses.

Built over a real application -- real corpus, real blob store, real
`MediaPerceiver` -- with a fake `PerceptionPort` injected through
`build_application(perception=...)`, which is the parameter's whole reason for
existing. **Nothing here reaches a network or names a model host.** The
adapter that speaks to one is tested in
`tests/infrastructure/test_readeverything_adapter.py`.

The happy path asserts the *stored row*, never the 202. An event no projection
handles counts as APPLIED, so a test that stopped at the status code would pass
against a build whose derived-text projection was deleted -- and against one
whose queued job never ran at all, because the 202 is answered before any of it
happens.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
)
from research_team.composition import build_application
from research_team.domain.corpus import StoreSourceMedia
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue


class FakePerception:
    """`PerceptionPort` with the reading and the capabilities both dictated.

    Counts calls, because two of the tests below are about a call that must
    *not* be paid for: an unconfigured install refuses at the route, and every
    source-side refusal happens before the port is reached.
    """

    def __init__(
        self,
        capabilities: PerceptionCapabilities | None = None,
        degradations: tuple[str, ...] = (),
    ) -> None:
        self._capabilities = capabilities or PerceptionCapabilities(
            vision=True, asr=True, ffmpeg=True
        )
        self._degradations = degradations
        self.calls: list[str] = []

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        self.calls.append(sha256)
        return Perceived(
            text="A talk about otters.",
            locators=(LocatorSpan(0, 20, {"kind": "time", "start_s": 0.0, "end_s": 8.0}),),
            fingerprint="vision=v1,asr=w1",
            degradations=self._degradations,
        )

    def capabilities(self) -> PerceptionCapabilities:
        return self._capabilities


async def _client(db_path, fake_model, port: FakePerception):
    application = build_application(model=fake_model, db_path=db_path, perception=port)
    await application.start()
    queue = ExtractionQueue()
    activity = ExtractionActivity()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        editor=application.editor,
        extraction=activity,
        extract_queue=queue,
        perception=application.perception,
        perceiver=application.perceiver,
    )
    transport = ASGITransport(app=api)
    return (
        application,
        queue,
        activity,
        AsyncClient(transport=transport, base_url="http://test"),
    )


@pytest.fixture
async def build(db_path, fake_model):
    """A factory for a build with a dictated port, closed however the test ends.

    A fixture rather than a call in the test body, and the reason is a failure
    seen while mutation-testing this file: a test that built its own
    application and asserted before `close()` left the run hanging at teardown
    rather than reporting the assertion, which reads as an infrastructure
    problem rather than as the mutation being caught.
    """
    built = []

    async def make(port: FakePerception):
        application, queue, activity, client = await _client(db_path, fake_model, port)
        built.append((application, client))
        await client.__aenter__()
        return application, queue, activity, client

    yield make
    for application, client in built:
        await client.__aexit__(None, None, None)
        await application.close()


@pytest.fixture
async def wired(db_path, fake_model):
    """A build that can perceive, plus the queue the route enqueues into."""
    port = FakePerception()
    application, queue, activity, client = await _client(db_path, fake_model, port)
    async with client:
        yield application, client, queue, port, activity
    await application.close()


@pytest.fixture
async def unconfigured(db_path, fake_model):
    """A build with neither a vision model nor a transcriber."""
    port = FakePerception(
        capabilities=PerceptionCapabilities(vision=False, asr=False, ffmpeg=False)
    )
    application, _queue, _activity, client = await _client(db_path, fake_model, port)
    async with client:
        yield application, client, port
    await application.close()


async def _new_project(client: AsyncClient) -> str:
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _upload_media(client: AsyncClient, project: str, source_id: str) -> None:
    response = await client.post(
        f"/api/projects/{project}/sources/media",
        files={"file": ("talk.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        data={"source_id": source_id},
    )
    assert response.status_code == 201


async def _settle(application, queue: ExtractionQueue, project: str) -> None:
    await queue.wait(UUID(project))
    await application.corpus_caught_up()


async def _rows(client: AsyncClient, project: str) -> dict[str, dict]:
    listed = await client.get(f"/api/projects/{project}/sources")
    assert listed.status_code == 200
    return {row["source_id"]: row for row in listed.json()}


async def test_perceiving_a_medium_answers_202_and_stores_the_derived_row(wired):
    """The row, not the status code.

    Red three ways before the implementation: 405 with no route at all, and --
    measured -- still red with the enqueue removed from the route body, because
    the 202 arrives either way and only the stored row can tell them apart.
    """
    application, client, queue, port, _activity = wired
    project = await _new_project(client)
    await _upload_media(client, project, "vid")

    response = await client.post(f"/api/projects/{project}/sources/vid/perceive")

    assert response.status_code == 202
    await _settle(application, queue, project)
    rows = await _rows(client, project)
    assert rows["vid#perceived"]["derived_from"] == "vid"
    assert rows["vid#perceived"]["kind"] == "text"
    assert port.calls, "the port was never asked to read the blob"


async def test_the_listing_carries_degradations_so_the_page_can_say_what_was_missed(
    build,
):
    """A perception that could not do everything still lists, saying so.

    Its own build rather than the shared fixture: the degradations are the
    port's, and dictating them means dictating the port before the application
    is assembled.
    """
    port = FakePerception(degradations=("vision unavailable: frames were not described",))
    application, queue, _activity, client = await build(port)
    project = await _new_project(client)
    await _upload_media(client, project, "vid")

    await client.post(f"/api/projects/{project}/sources/vid/perceive")
    await _settle(application, queue, project)

    rows = await _rows(client, project)
    assert rows["vid#perceived"]["degradations"] == [
        "vision unavailable: frames were not described"
    ]
    # A media row reports neither field: it has no perception of its own, and
    # a `degradations: []` on the video would read as "this recording was
    # perceived and nothing was missed".
    assert rows["vid"].get("degradations") is None


async def test_the_progress_pane_hears_perceiving_then_perceived(wired):
    """The existing extraction channel, not a second one.

    Both halves matter. Without `perceiving` there is nothing on the pane for
    the minutes a transcription runs, which is the whole reason this is queued
    rather than inline. Without `perceived` on `_TERMINAL` the frames never
    leave `_running`, so `in_flight` reports a finished transcription to the
    roster forever -- which is what `last()` being non-empty here is checking.
    """
    application, client, queue, _port, activity = wired
    project = await _new_project(client)
    await _upload_media(client, project, "vid")

    await client.post(f"/api/projects/{project}/sources/vid/perceive")
    await _settle(application, queue, project)

    stages = [frame["stage"] for frame in activity.last(UUID(project))]
    assert stages == ["perceiving", "perceived"]
    assert activity.in_flight(UUID(project)) is None


async def test_an_unconfigured_install_answers_503_and_names_what_is_missing(unconfigured):
    """503 and not 501: the route exists, the install is short of something.

    Named rather than merely refused -- an operator told "not configured" has
    nowhere to go.
    """
    _application, client, port = unconfigured
    project = await _new_project(client)
    await _upload_media(client, project, "vid")

    response = await client.post(f"/api/projects/{project}/sources/vid/perceive")

    assert response.status_code == 503
    assert "AGENT_VISION_MODEL" in response.json()["detail"]
    assert "AGENT_TRANSCRIBER_URL" in response.json()["detail"]
    assert port.calls == [], "an install that cannot perceive must not pay for a reading"


async def test_perceiving_a_text_source_answers_409(wired):
    """Not 404. The id is real and holds prose; that is a different mistake
    from a typo, and an operator sent looking for a missing ingest wastes the
    trip."""
    _application, client, _queue, port, _activity = wired
    project = await _new_project(client)
    await client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "paper", "text": "otters, at length"},
    )

    response = await client.post(f"/api/projects/{project}/sources/paper/perceive")

    assert response.status_code == 409
    assert port.calls == []


async def test_perceiving_a_dropped_medium_answers_409_and_says_to_restore_it(wired):
    """The drop reason travels, and so does the operator's next move.

    "No such source" -- what a naive `read_media` answers here, because it
    hides dropped rows -- would send somebody looking for an ingest that did
    happen.
    """
    _application, client, _queue, _port, _activity = wired
    project = await _new_project(client)
    await _upload_media(client, project, "vid")
    dropped = await client.post(
        f"/api/projects/{project}/sources/vid/drop", json={"reason": "off topic"}
    )
    assert dropped.status_code == 200

    response = await client.post(f"/api/projects/{project}/sources/vid/perceive")

    assert response.status_code == 409
    assert "off topic" in response.json()["detail"]
    assert "restore" in response.json()["detail"]


async def test_perceiving_an_unknown_source_answers_404(wired):
    _application, client, _queue, _port, _activity = wired
    project = await _new_project(client)

    response = await client.post(f"/api/projects/{project}/sources/nope/perceive")

    assert response.status_code == 404


async def test_a_record_whose_bytes_are_gone_answers_410_from_a_project_untouched(wired):
    """410, matching what `/content` answers for the same dangling reference.

    Arranged from a project the fixture never uploaded to, and the event goes
    straight onto the corpus aggregate rather than through `store_media` -- so
    the blob store never hears about it and the bytes really are absent. The
    CLAUDE.md finding in this task's clothes: every other test here arranges
    its media through the upload route, which is the very call that puts the
    bytes where the route under test expects them.
    """
    application, client, _queue, _port, _activity = wired
    await _new_project(client)  # the project the other tests would have used
    untouched = UUID(await _new_project(client))

    corpus = await application.editor._corpus.load_or_create(untouched)
    corpus.execute(
        StoreSourceMedia(
            corpus_id=untouched,
            source_id="ghost",
            sha256="0" * 64,
            media_type="video/mp4",
            byte_count=7,
        )
    )
    await application.editor._corpus.save(corpus)
    await application.corpus_caught_up()

    response = await client.post(f"/api/projects/{untouched}/sources/ghost/perceive")

    assert response.status_code == 410


async def test_a_second_press_while_the_first_is_queued_does_not_perceive_twice(wired):
    """202 with `queued: false`, and one reading paid for rather than two.

    409 would be the other option and is wrong for `extract_source`'s reason:
    the medium *is* going to be perceived, which is what the caller wanted.
    """
    application, client, queue, port, _activity = wired
    project = await _new_project(client)
    await _upload_media(client, project, "vid")

    first = await client.post(f"/api/projects/{project}/sources/vid/perceive")
    second = await client.post(f"/api/projects/{project}/sources/vid/perceive")

    assert first.json()["queued"] is True
    assert second.status_code == 202
    assert second.json()["queued"] is False
    await _settle(application, queue, project)
    assert len(port.calls) == 1


async def test_an_unwired_build_answers_503(db_path, fake_model):
    """A build with no perceiver is a valid thing to serve, and says so."""
    application = build_application(
        model=fake_model, db_path=db_path, perception=FakePerception()
    )
    await application.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        editor=application.editor,
    )
    transport = ASGITransport(app=api)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            project = await _new_project(client)
            response = await client.post(f"/api/projects/{project}/sources/x/perceive")
            assert response.status_code == 503
    finally:
        # `finally`, for the reason the `build` fixture exists: an application
        # left open by a failing assertion hangs the run at teardown, and a
        # hang hides which assertion failed.
        await application.close()
