"""`/api/projects/{id}/export/...`: the two ways work leaves this system.

What can only break here is the wiring -- which run's sessions a course
archive gathers from, which entities a scoped graph export contains, and
whether the refusals are refusals rather than quietly empty files. The layout
arithmetic and the three serialisations belong to
`tests/application/test_graph_export.py`.

The fixture is `test_curriculum_routes.py`'s, duplicated module-locally for
that module's stated reason. It is duplicated with one addition: this module
writes real files into real sessions, because a course archive assembled from
a stubbed workspace could not detect the export reading the wrong session.
"""

import asyncio
import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, Relationship

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


def _entity(tenant_id: UUID, name: str) -> Entity:
    return Entity(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type="concept",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


async def _seed_two_clusters(application, project_id: str) -> dict[str, list[Entity]]:
    """Two four-cliques joined by nothing: an unambiguous two-area graph.

    Returned rather than discarded, so a scoped export can be checked against
    the entities that are actually in each cluster instead of against a count.
    """
    tenant_id = UUID(project_id)
    store = await application.graphs.open(tenant_id)
    groups = {
        "alpha": [_entity(tenant_id, f"Alpha {i}") for i in range(4)],
        "beta": [_entity(tenant_id, f"Beta {i}") for i in range(4)],
    }
    await store.upsert_entities([e for group in groups.values() for e in group])
    edges = []
    for group in groups.values():
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                edges.append(
                    Relationship(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        source_entity_id=left.id,
                        target_entity_id=right.id,
                        relationship_type="relates_to",
                        confidence=1.0,
                    )
                )
    await store.upsert_relationships(edges)
    return groups


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


# ---- A. the course archive ------------------------------------------------


async def test_the_archive_holds_every_file_the_run_wrote(app_and_client):
    """Not merely that the response was a zip.

    A 200 with a valid but empty archive is what this route returns when the
    session lookup finds nothing, and it is indistinguishable from success
    without opening it -- the failure `CLAUDE.md` records under *Events*.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {
                "/course/areas/alpha/unit.md": "# Alpha unit",
                "/course/areas/alpha/lesson-01.md": "# Alpha lesson one",
                "/course/areas/alpha/lesson-02.md": "# Alpha lesson two",
            },
            "complete": {"/course/paths/complete.md": "# The path"},
        },
    )

    response = await client.get(f"/api/projects/{project_id}/export/course")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert ".zip" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    inside = {name.split("/", 1)[1] for name in archive.namelist()}
    assert inside == {
        "areas/alpha/unit.md",
        "areas/alpha/lesson-01.md",
        "areas/alpha/lesson-02.md",
        "paths/complete.md",
        "README.md",
    }
    assert archive.read(next(n for n in archive.namelist() if n.endswith("unit.md"))) == (
        b"# Alpha unit"
    )


async def test_each_target_is_read_from_its_own_run_s_session(app_and_client):
    """The whole point of the `completed`/`sessions` pairing.

    Each authoring target writes into its *own* session's workspace, so an
    export that read every target out of the first session would produce an
    archive of real files about the wrong area -- which nobody would suspect,
    because every file in it opens. Would pass against an implementation that
    ignored the pairing if both sessions held the same paths, which is why the
    two areas here hold different ones.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {"/course/areas/alpha/unit.md": "# Alpha"},
            "beta": {"/course/areas/beta/unit.md": "# Beta"},
        },
    )

    archive = zipfile.ZipFile(
        io.BytesIO((await client.get(f"/api/projects/{project_id}/export/course")).content)
    )

    assert archive.read(next(n for n in archive.namelist() if "alpha" in n)) == b"# Alpha"
    assert archive.read(next(n for n in archive.namelist() if "beta" in n)) == b"# Beta"


async def test_one_area_can_be_exported_on_its_own(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {"/course/areas/alpha/unit.md": "# Alpha"},
            "beta": {"/course/areas/beta/unit.md": "# Beta"},
        },
    )

    response = await client.get(f"/api/projects/{project_id}/export/course?area=beta")

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    inside = {name.split("/", 1)[1] for name in archive.namelist()}
    assert inside == {"areas/beta/unit.md", "README.md"}


async def test_an_area_the_run_did_not_write_is_a_404_naming_what_it_did(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {"alpha": {"/course/areas/alpha/unit.md": "# Alpha"}},
    )

    response = await client.get(f"/api/projects/{project_id}/export/course?area=gamma")

    assert response.status_code == 404
    assert "alpha" in response.json()["detail"]


async def test_a_project_that_never_authored_is_told_that_and_not_about_a_restart(
    app_and_client,
):
    """`last` returning `None` changed meaning when the mapping became a table.

    Before #242 it meant "this process has forgotten"; now it means "nothing
    was ever recorded". The old message blamed a restart, which would send
    somebody hunting for a server fault behind a project nobody has authored.
    Asserts on the absence of the old wording as well as the presence of the
    new: a message that said both would pass a presence-only check.
    """
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/export/course")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "no authoring run has ever been recorded" in detail
    assert "restart" not in detail


async def test_an_export_taken_during_a_run_is_refused(app_and_client):
    """An archive of a run in flight holds whichever areas happened to be
    finished and looks exactly like a complete one."""
    client = app_and_client.client
    project_id = await _new_project(client)

    async def _slow(run_id, target):
        await asyncio.sleep(0.2)
        return SimpleNamespace(session_id=uuid4())

    await app_and_client.authoring.start(UUID(project_id), ["alpha"], _slow, kind="area")
    response = await client.get(f"/api/projects/{project_id}/export/course")
    await app_and_client.authoring.wait(UUID(project_id))

    assert response.status_code == 409
    assert "in flight" in response.json()["detail"]


# ---- A2. the course as one page -------------------------------------------
#
# The freeze decisions live in `test_course_html.py`, which drives the renderer
# directly. What can only break here is the wiring: which files the page is
# built from, and whether the format is a real choice rather than a fallback.


async def test_the_page_holds_every_area_and_lesson_the_run_wrote(app_and_client):
    """One file, no archive, and the lesson prose actually in it.

    A 200 of `text/html` is what this route returns when the page it built
    was empty, which is the same "valid but empty" failure the archive test
    above guards against -- so the assertion is on the rendered prose of each
    file, not on the response.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {
                "/course/areas/alpha/unit.md": "# Alpha unit\n\nStage 1 desired results.\n",
                "/course/areas/alpha/lesson-01.md": "# Alpha lesson one\n\nFirst.\n",
                "/course/areas/alpha/lesson-02.md": "# Alpha lesson two\n\nSecond.\n",
            },
            "complete": {"/course/paths/complete.md": "# The path\n\nOverview prose.\n"},
        },
    )

    response = await client.get(f"/api/projects/{project_id}/export/course?format=html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert ".html" in response.headers["content-disposition"]
    page = response.text
    for prose in ("Stage 1 desired results.", "First.", "Second.", "Overview prose."):
        assert prose in page
    # Teaching order, which is the order the lesson filenames give.
    assert page.index("Alpha lesson one") < page.index("Alpha lesson two")


async def test_the_page_pulls_in_nothing_from_outside_itself(app_and_client):
    """Asserted over a real export rather than a fixture-built one.

    `test_course_html.py` makes the same check against a hand-built book; this
    one is over the whole route, where a wrapper, a template change or a
    future banner could add a fetch that the pure test would never see.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {"alpha": {"/course/areas/alpha/unit.md": "# Alpha unit\n"}},
    )

    page = (await client.get(f"/api/projects/{project_id}/export/course?format=html")).text

    assert "<script src" not in page
    assert "<link" not in page
    assert "<img" not in page


async def test_a_widget_whose_entity_this_project_lacks_is_named_not_emptied(app_and_client):
    """The route's own resolution path, over a project whose graph is empty.

    This is the case a fixture cannot fake: `_resolve_definition` asks the
    real reader, gets nothing, and has to produce a sentence. A build where
    that path raised instead would fail the whole export, and one where it
    returned an empty `Resolution` would render a widget with nothing in it
    -- both look like "the export worked" from the status code.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {
                "/course/areas/alpha/lesson-01.md": (
                    "# Lesson\n\n"
                    "```component:definition\nid: nowhere\nentity: Nowhere At All\n```\n"
                )
            }
        },
    )

    response = await client.get(f"/api/projects/{project_id}/export/course?format=html")

    assert response.status_code == 200
    assert "Nowhere At All" in response.text
    assert "no entity by that name" in response.text


async def test_a_cited_passage_is_quoted_out_of_the_real_corpus(app_and_client):
    """The one test that drives both ends of the citation path over real data.

    `CLAUDE.md`'s rule about a port with one adapter: every other assertion
    about provenance in this feature hands `render_course_html` a `Passage`
    that a fixture built, which proves the renderer works and cannot prove
    that the reader produces what the renderer expects. So this one stores a
    real source through the real route, cites a real range of it, and asserts
    the *bytes between those offsets* come out in the page.

    The offsets are chosen to cut mid-document rather than to span the whole
    of it -- a widget that ignored `start`/`end` and quoted everything would
    pass a whole-document assertion and would be wrong about every citation.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    stored = await client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "source_id": "edict",
            "title": "Edict of Thessalonica",
            "text": "PREAMBLE. It is our will that all peoples follow that religion. THE END.",
        },
    )
    assert stored.status_code == 201
    await _authored(
        app_and_client.application,
        app_and_client.authoring,
        project_id,
        {
            "alpha": {
                "/course/areas/alpha/lesson-01.md": (
                    "# Lesson\n\n"
                    "```component:evidence\n"
                    "id: will\n"
                    "claim: The edict states an imperial will.\n"
                    "sources:\n"
                    "  - source: edict\n"
                    "    start: 10\n"
                    "    end: 63\n"
                    "```\n"
                )
            }
        },
    )

    page = (await client.get(f"/api/projects/{project_id}/export/course?format=html")).text

    assert "It is our will that all peoples follow that religion." in page
    # Attributed by title, not by id -- a citation that degraded to `edict`
    # is one the reader cannot resolve, having left this system.
    assert "Edict of Thessalonica" in page
    assert "PREAMBLE" not in page
    assert "THE END" not in page


async def test_an_unknown_course_format_is_refused_rather_than_defaulted(app_and_client):
    """The two formats differ in media type, so a silent fallback would hand
    a browser an archive it was told to render."""
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/export/course?format=pdf")

    assert response.status_code == 422


# ---- B. the graph ---------------------------------------------------------


async def test_the_exported_html_is_one_file_that_names_the_entities(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(app_and_client.application, project_id)

    response = await client.get(f"/api/projects/{project_id}/export/graph")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert "Alpha 0" in body
    assert "Beta 3" in body
    assert "http://" not in body and "https://" not in body


async def test_the_json_export_carries_positions_for_the_whole_graph(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(app_and_client.application, project_id)

    body = (await client.get(f"/api/projects/{project_id}/export/graph?format=json")).json()

    assert len(body["nodes"]) == 8
    assert {node["name"] for node in body["nodes"]} == {
        f"{prefix} {i}" for prefix in ("Alpha", "Beta") for i in range(4)
    }
    assert all(isinstance(node["x"], (int, float)) for node in body["nodes"])
    # Twelve: two four-cliques, six edges each.
    assert len(body["edges"]) == 12


async def test_an_area_export_holds_that_area_and_not_the_other(app_and_client):
    """The assertion that a scope is a scope.

    An export that quietly returned the whole project when asked for one area
    is the failure worth testing: the file opens, draws, and is about the
    wrong thing. Compares against the *other* cluster's names rather than
    against a count, because two areas of four are the same count.
    """
    client = app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(app_and_client.application, project_id)

    areas = (await client.get(f"/api/projects/{project_id}/curriculum")).json()["areas"]
    slug = next(
        area["slug"]
        for area in areas
        if any(member["name"].startswith("Alpha") for member in area["members"])
    )

    body = (
        await client.get(
            f"/api/projects/{project_id}/export/graph?format=json&scope=area&area={slug}"
        )
    ).json()

    names = {node["name"] for node in body["nodes"]}
    assert names, "the area export is empty"
    assert all(name.startswith("Alpha") for name in names), names


async def test_an_entity_export_holds_the_entity_it_is_named_after(app_and_client):
    """`Neighborhood.root` is not in `entities`, so an export that forwarded
    only `entities` would draw everything around a hole."""
    client = app_and_client.client
    project_id = await _new_project(client)
    groups = await _seed_two_clusters(app_and_client.application, project_id)
    root = groups["alpha"][0]

    body = (
        await client.get(
            f"/api/projects/{project_id}/export/graph"
            f"?format=json&scope=entity&entity={root.id}&depth=1"
        )
    ).json()

    assert str(root.id) in {node["id"] for node in body["nodes"]}
    assert {node["name"] for node in body["nodes"]} == {f"Alpha {i}" for i in range(4)}


async def test_the_graphml_export_parses_and_is_offered_as_a_download(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(app_and_client.application, project_id)

    response = await client.get(f"/api/projects/{project_id}/export/graph?format=graphml")

    assert response.status_code == 200
    assert ".graphml" in response.headers["content-disposition"]
    document = ET.fromstring(response.text)
    namespace = "{http://graphml.graphdrawing.org/xmlns}"
    assert len(list(document.iter(f"{namespace}node"))) == 8


async def test_an_unknown_format_is_refused_rather_than_defaulted(app_and_client):
    """A typo that fell back to HTML would hand a browser a page when a script
    asked for data, and the script would parse it as JSON and fail somewhere
    else entirely."""
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/export/graph?format=gexf")

    assert response.status_code == 422


async def test_scope_area_without_an_area_is_refused(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/export/graph?scope=area")

    assert response.status_code == 422
    assert "area" in response.json()["detail"]


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
