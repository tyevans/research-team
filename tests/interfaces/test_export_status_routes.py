"""`/api/projects/{id}/export/course`: interrupted and cancelled export route tests.

What can only break here is how the export surfaces partial or interrupted runs
-- that an interrupted or cancelled authoring run still exports the sessions
completed so far, and that the archive filename, README, and HTML export clearly
signal the incomplete status rather than presenting as a complete course.
"""

import asyncio
import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application import SummaryProjects, WorkerRoster
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.domain import SessionPurpose
from research_team.domain.course_authoring_run import (
    RecordAuthoredCourse,
    StartCourseAuthoringRun,
)
from research_team.interfaces.web import create_app
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.extraction import ExtractionActivity

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    extraction = ExtractionActivity()
    authoring = AuthoringActivity(application.authoring_runs, application.authoring)
    curriculum = CurriculumService()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        # The corpus's *write* side, so a test can store a source to be cited.
        # The export itself only reads -- but a citation test that stubbed the
        # store would be testing the renderer again rather than the reader, and
        # the reader is the half with no other coverage.
        editor=application.editor,
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
        curriculum=curriculum,
        course_author=SimpleNamespace(),
        authoring=authoring,
        reembed=application.reembed,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(application=application, client=client, authoring=authoring)
    await application.close()


async def _new_project(client) -> str:
    created = await client.post("/api/projects", json={"name": f"export-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _authored(application, authoring, project_id: str, files: dict[str, dict[str, str]]):
    """Drive a real authoring run whose targets wrote real files.

    `files` maps a target to the workspace paths and contents its session
    holds. A stubbed `AuthoringActivity` frame would have been shorter and
    could not detect the export reading the wrong session, which is the one
    thing the `completed`/`sessions` pairing exists to get right.
    """
    written: dict[str, UUID] = {}
    for target, contents in files.items():
        session_id = await application.service.start_in_project(
            UUID(project_id), SessionPurpose.CHAT
        )
        for path, content in contents.items():
            await application.service.write_file(session_id, path, content)
        # Released before the next one starts: a project holds one active
        # session at a time, and `start_in_project` joins. A real authoring run
        # forks per target through the same door.
        await application.service.release_project(session_id)
        written[target] = session_id

    async def _one(run_id, target):
        return SimpleNamespace(session_id=written[target])

    await authoring.start(UUID(project_id), list(files), _one, kind="path")
    await authoring.wait(UUID(project_id))
    return written


async def _interrupted(application, project_id: str, targets: list[str], written: dict):
    """The wreckage a process that died mid-run leaves behind.

    Start plus one `RecordAuthoredCourse` per finished target and **no settle**
    -- which is precisely the row `AuthoringActivity.last` reports as
    `interrupted`, since it derives that from a row saying `running` that no
    live task is driving. Built by appending the same commands the driver
    appends rather than by writing a row: a fixture that wrote the read model
    directly would keep passing if the projection stopped being fed, which is
    the failure `CLAUDE.md` records under *Events*.
    """
    run_id = uuid4()
    aggregate = application.authoring_runs.create_new(run_id)
    aggregate.execute(
        StartCourseAuthoringRun(
            run_id=run_id,
            project_id=UUID(project_id),
            kind="path",
            targets=tuple(targets),
            started_at=datetime.now(UTC),
        )
    )
    await application.authoring_runs.save(aggregate)
    for target, session_id in written.items():
        stored = await application.authoring_runs.load(run_id)
        stored.execute(
            RecordAuthoredCourse(run_id=run_id, target=target, session_id=session_id)
        )
        await application.authoring_runs.save(stored)
    return run_id


async def _sessions_holding(application, project_id: str, files: dict) -> dict:
    """Real sessions holding real course files, without driving a run.

    Split out of `_authored` so the interrupted and cancelled cases can put
    genuine workspaces behind a run this process did not complete.
    """
    written: dict[str, UUID] = {}
    for target, contents in files.items():
        session_id = await application.service.start_in_project(
            UUID(project_id), SessionPurpose.CHAT
        )
        for path, content in contents.items():
            await application.service.write_file(session_id, path, content)
        await application.service.release_project(session_id)
        written[target] = session_id
    return written


def _readme_of(response) -> str:
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return archive.read(
        next(name for name in archive.namelist() if name.endswith("README.md"))
    ).decode()


async def test_an_interrupted_run_is_exported_rather_than_refused(app_and_client):
    """The case durability was built for.

    A run that was still going when the server died comes back with its
    completed targets and their session ids intact. Refusing it would mean the
    feature recovered the mapping and then declined to use it -- so the archive
    is handed over, and the README and the filename are what stop it reading as
    complete.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    written = await _sessions_holding(
        application, project_id, {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}}
    )
    await _interrupted(application, project_id, ["alpha", "beta", "gamma"], written)

    response = await client.get(f"/api/projects/{project_id}/export/course")

    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert any(name.endswith("areas/alpha/unit.md") for name in archive.namelist())


async def test_an_interrupted_archive_says_so_before_it_is_opened(app_and_client):
    """The filename, which is the only place the status reaches somebody who
    saves the file and forwards it without unzipping it."""
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    written = await _sessions_holding(
        application, project_id, {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}}
    )
    await _interrupted(application, project_id, ["alpha", "beta"], written)

    response = await client.get(f"/api/projects/{project_id}/export/course")

    assert "-interrupted.zip" in response.headers["content-disposition"]


async def test_an_interrupted_readme_names_what_was_never_started(app_and_client):
    """The half of "it says so" that survives a rename.

    Names the missing targets rather than counting them: "1 of 3 written" tells
    a reader the archive is short and not which two to go and write.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    written = await _sessions_holding(
        application, project_id, {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}}
    )
    await _interrupted(application, project_id, ["alpha", "beta", "gamma"], written)

    readme = _readme_of(await client.get(f"/api/projects/{project_id}/export/course"))

    # A phrase out of the explanatory sentence, not the word "interrupted" --
    # which also appears in the terse `status ` + backtick line above it. Proved
    # by deleting `_STATUS_SENTENCE` from the builder: the word-only assertion
    # stayed green, so it was testing nothing. Pinning prose is brittle on
    # purpose here; the sentence is the product surface, and a rewrite that
    # loses "never reached" should have to look at this test.
    assert "were never reached" in readme
    assert "## Never started" in readme
    assert "`beta`" in readme and "`gamma`" in readme
    assert "## Written" in readme


async def test_a_completed_run_carries_no_status_qualifier(app_and_client):
    """The other side of the marker.

    A qualifier on every archive would stop the qualifiers reading as warnings,
    so `done` gets a plain name and no *Never started* section. Would pass with
    `_status_suffix` returning `-done`, which is why the filename is asserted
    literally.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}},
    )

    response = await client.get(f"/api/projects/{project_id}/export/course")

    disposition = response.headers["content-disposition"]
    assert disposition.endswith('-course.zip"')
    assert "interrupted" not in disposition and "-done" not in disposition
    assert "## Never started" not in _readme_of(response)


async def test_a_cancelled_run_is_exported_and_says_it_was_cancelled(app_and_client):
    """A person who stopped the run knows it is partial.

    Refusing them their own courses would be patronising, and they would have
    no route to files the console is already linking to.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    written = await _sessions_holding(
        application, project_id, {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}}
    )
    started = asyncio.Event()

    async def _one(run_id, target):
        if target == "alpha":
            return SimpleNamespace(session_id=written["alpha"])
        started.set()
        await asyncio.sleep(5)
        raise AssertionError("cancelled before this returns")

    await app_and_client.authoring.start(
        UUID(project_id), ["alpha", "beta"], _one, kind="path"
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    app_and_client.authoring.cancel(UUID(project_id))
    await app_and_client.authoring.wait(UUID(project_id))

    response = await client.get(f"/api/projects/{project_id}/export/course")

    assert response.status_code == 200
    assert "-cancelled.zip" in response.headers["content-disposition"]
    readme = _readme_of(response)
    assert "stopped it deliberately" in readme
    # Under that heading, not merely somewhere in the file: `beta` also appears
    # in a failures list and in a written list, and an assertion that could not
    # tell those apart would pass on an archive claiming it wrote beta.
    assert "`beta`" in readme.split("## Never started", 1)[1]


async def test_an_interrupted_page_says_so_in_the_file_and_in_its_name(app_and_client):
    """The HTML export's half of "a partial course must not look complete".

    Both halves, because a single page is *more* exposed to this than the zip,
    not less: there is nothing to unzip, so a reader who was forwarded the file
    sees the filename and then the page, and nothing else. The zip's own
    version of this is `test_an_interrupted_archive_says_so_before_it_is_opened`
    and `test_an_interrupted_readme_names_what_was_never_started`.

    Proved red before it was trusted green: against the build that merged the
    HTML export and the partial-archive rule together, the page carried neither
    the sentence nor the never-started list and the filename carried no status
    -- three assertions, all failing, on a route whose own tests were green.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    written = await _sessions_holding(
        application, project_id, {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}}
    )
    await _interrupted(application, project_id, ["alpha", "beta"], written)

    response = await client.get(f"/api/projects/{project_id}/export/course?format=html")

    assert response.status_code == 200
    assert "-interrupted.html" in response.headers["content-disposition"]
    body = response.text
    # The sentence, not merely the word: "interrupted" also appears in the
    # filename this same response carries, so matching the word alone would
    # pass with the sentence deleted.
    assert "the server stopped while it was still writing" in body
    # Rendered as markdown, not escaped: the sentence is the zip README's, and
    # its emphasis must not reach the reader as literal asterisks.
    assert "<strong>" in body and "**This run was interrupted" not in body
    # Named, not counted -- `beta` is what a reader would go and author.
    assert "Never started" in body
    assert "beta" in body
