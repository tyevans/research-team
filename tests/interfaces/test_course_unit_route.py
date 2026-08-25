"""`GET /api/projects/{id}/catalog/{slug}/unit`: the authored course, as text.

What can only break here is the join between three things that already worked
separately -- which session a run recorded against a slug, which of that
session's files are the course, and which of the three states a reader is in.
The markdown itself belongs to `tests/application/test_course_authoring.py`,
and the rendering to the console's own suite.

**Every assertion here is on the markdown that comes back, never on the status
code.** CLAUDE.md's Events section is explicit about why: an event no
projection handles counts as applied, so a build with the authoring projection
unwired serves this route as a cheerful `unauthored` with a 200 on it. A test
asserting the request succeeded would pass against the feature deleted.

The fixture is `test_export_routes.py`'s, duplicated module-locally for that
module's stated reason, and with its `_authored` helper carried over unchanged
-- real sessions holding real files, because a stubbed workspace could not
detect the route reading the wrong session.
"""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application import SummaryProjects, WorkerRoster
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.domain import SessionPurpose
from research_team.interfaces.web import create_app
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.extraction import ExtractionActivity

pytestmark = pytest.mark.asyncio

UNIT = "# Roman Law\n\n## Stage 1 - Desired results\n\nLearners will grasp *ius civile*.\n"
LESSON = "# Lesson 1 - The Twelve Tables\n\nThe first written code.\n"


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    extraction = ExtractionActivity()
    authoring = AuthoringActivity(application.authoring_runs, application.authoring)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        workers=WorkerRoster(
            application.service,
            turns=application.turns,
            runs=application.research,
            extractions=extraction,
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
        policy=application.policy,
        topics=application.topic_readers,
        topic_repository=application.topic_repository,
        graphs=application.graphs,
        curriculum=CurriculumService(),
        course_author=SimpleNamespace(),
        authoring=authoring,
        reembed=application.reembed,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(application=application, client=client, authoring=authoring)
    await application.close()


async def _new_project(client) -> str:
    created = await client.post("/api/projects", json={"name": f"unit-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _authored(application, authoring, project_id: str, files: dict[str, dict[str, str]]):
    """Drive a real authoring run whose targets wrote real files.

    `test_export_routes.py`'s helper, carried over rather than imported: these
    two modules build their own app, and a shared fixture module would make
    either one's app wiring the other's problem. The reason it writes real
    files is the same one -- a stubbed workspace cannot detect a reader
    resolving the wrong session, which is the whole of what this route does.
    """
    written: dict[str, UUID] = {}
    for target, contents in files.items():
        session_id = await application.service.start_in_project(
            UUID(project_id), SessionPurpose.CHAT
        )
        for path, content in contents.items():
            await application.service.write_file(session_id, path, content)
        # Released before the next one starts: a project holds one active
        # session at a time, and `start_in_project` joins.
        await application.service.release_project(session_id)
        written[target] = session_id

    async def _one(run_id, target):
        return SimpleNamespace(session_id=written[target])

    await authoring.start(UUID(project_id), list(files), _one, kind="path")
    await authoring.wait(UUID(project_id))
    return written


async def test_a_recorded_unit_file_comes_back_as_text_after_a_real_run(app_and_client):
    """The increment, in one assertion: the bytes the authoring turn wrote are
    the bytes the reader gets.

    Not `state == "authored"`, and not a 200 -- both of those survive the
    route resolving the wrong session, and a course page showing another
    area's unit is worse than one showing nothing. The markdown is compared
    whole, so a route that returned the lesson where the unit belongs fails
    here rather than looking plausible.
    """
    ctx = app_and_client
    project_id = await _new_project(ctx.client)
    written = await _authored(
        ctx.application,
        ctx.authoring,
        project_id,
        {
            "roman-law": {
                "/course/areas/roman-law/unit.md": UNIT,
                "/course/areas/roman-law/lesson-01.md": LESSON,
            },
            # A second target with its own session and its own unit. Without
            # it, a route that ignored `authored_session_for` and simply read
            # the newest session would pass.
            "roman-army": {
                "/course/areas/roman-army/unit.md": "# Roman Army\n\nNot this one.\n"
            },
        },
    )

    response = await ctx.client.get(f"/api/projects/{project_id}/catalog/roman-law/unit")
    body = response.json()

    assert body["unit"] == UNIT
    assert [lesson["markdown"] for lesson in body["lessons"]] == [LESSON]
    assert body["lessons"][0]["path"] == "/course/areas/roman-law/lesson-01.md"
    assert body["state"] == "authored"
    assert body["sessionId"] == str(written["roman-law"])
    # The unit's *path*, not just its text. The console asks
    # `/api/sessions/{id}/files/parsed` for each course file so its widgets
    # render as widgets rather than as their own yaml, and that route is keyed
    # on session plus path. A payload that carried the unit's markdown and not
    # its path left the unit's widgets unrenderable while every lesson's
    # worked -- measured on the `resolution` course, 10 of its 19 component
    # blocks are in the unit. Asserting the value, not merely the key: a
    # `None` here would put the console back on the prose fallback silently.
    assert body["unitPath"] == "/course/areas/roman-law/unit.md"


async def test_a_slug_no_run_ever_wrote_is_unauthored_rather_than_empty(app_and_client):
    """`unauthored` is a state a page can act on; an empty `unit` is not.

    Fails if the route ever answers `authored` with nothing in it -- which is
    the failure this whole increment is about, wearing the word that means the
    opposite.
    """
    ctx = app_and_client
    project_id = await _new_project(ctx.client)
    await _authored(
        ctx.application,
        ctx.authoring,
        project_id,
        {"roman-law": {"/course/areas/roman-law/unit.md": UNIT}},
    )

    response = await ctx.client.get(f"/api/projects/{project_id}/catalog/roman-army/unit")
    body = response.json()

    assert body["state"] == "unauthored"
    assert body["unit"] is None
    assert body["sessionId"] is None


async def test_a_target_a_live_run_is_still_writing_reads_as_authoring(app_and_client):
    """The state the outline's `None` could not express.

    A run is held open on `first` and never allowed to reach `second`, so the
    request lands while `second` is genuinely queued and unwritten -- the case
    a reader must be able to tell from "nobody has written this", because one
    is a button and the other is a reason to wait.

    Would pass trivially against a route that returned `authoring` whenever
    any run was live, which is why the third assertion is here: `elsewhere` is
    not among this run's targets and must not borrow its progress.
    """
    ctx = app_and_client
    project_id = await _new_project(ctx.client)

    release = asyncio.Event()

    async def _one(run_id, target):
        # Only the first target blocks. The run is therefore live, with
        # `second` queued behind a turn that has not returned.
        await release.wait()
        session_id = await ctx.application.service.start_in_project(
            UUID(project_id), SessionPurpose.CHAT
        )
        await ctx.application.service.release_project(session_id)
        return SimpleNamespace(session_id=session_id)

    await ctx.authoring.start(UUID(project_id), ["first", "second"], _one, kind="path")
    try:
        queued = await ctx.client.get(f"/api/projects/{project_id}/catalog/second/unit")
        stranger = await ctx.client.get(f"/api/projects/{project_id}/catalog/elsewhere/unit")

        assert queued.json()["state"] == "authoring"
        assert queued.json()["unit"] is None
        assert stranger.json()["state"] == "unauthored"
    finally:
        release.set()
        await ctx.authoring.wait(UUID(project_id))


async def test_a_path_overview_comes_back_as_the_unit_with_no_lessons(app_and_client):
    """A run's last target writes `/course/paths/<slug>.md` rather than an
    area directory, and nothing on the frame says which is which.

    Fails against a route that assumed every target is an area: that one finds
    no files under `/course/areas/the-path/` and reports `unauthored` over a
    file that exists.
    """
    ctx = app_and_client
    project_id = await _new_project(ctx.client)
    overview = "# The path\n\nStart with Roman law.\n"
    await _authored(
        ctx.application,
        ctx.authoring,
        project_id,
        {"the-path": {"/course/paths/the-path.md": overview}},
    )

    body = (await ctx.client.get(f"/api/projects/{project_id}/catalog/the-path/unit")).json()

    assert body["unit"] == overview
    assert body["lessons"] == []
    assert body["state"] == "authored"


async def test_lessons_come_back_in_path_order_not_in_the_order_they_were_written(
    app_and_client,
):
    """A workspace dict is in the order the turns happened, and a retried turn
    reorders it.

    Two readers of one course seeing its lessons in different orders is the
    kind of defect nobody reports and everybody notices. Written deliberately
    out of order here; fails if `files_under` ever stops sorting.
    """
    ctx = app_and_client
    project_id = await _new_project(ctx.client)
    await _authored(
        ctx.application,
        ctx.authoring,
        project_id,
        {
            "roman-law": {
                "/course/areas/roman-law/lesson-03.md": "three",
                "/course/areas/roman-law/unit.md": UNIT,
                "/course/areas/roman-law/lesson-01.md": "one",
                "/course/areas/roman-law/lesson-02.md": "two",
            }
        },
    )

    body = (await ctx.client.get(f"/api/projects/{project_id}/catalog/roman-law/unit")).json()

    assert [lesson["markdown"] for lesson in body["lessons"]] == ["one", "two", "three"]
