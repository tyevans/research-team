"""Project route tests exercised over ASGI with no network and no real model."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application as _build_application
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.research.domain import StoreSourceDocument
from research_team.session.application.workers import (
    SummaryProjects,
    WorkerRoster,
)
from research_team.session.domain import WriteFile


async def _started(**kwargs):
    """Build an application and start its projection.

    These tests construct their own applications rather than take the fixture,
    because they need the FastAPI app wired around the same instance. Starting
    is still not optional -- `/sessions` reads a projection that has to be
    following the log before it can answer.
    """
    application = _build_application(**kwargs)
    await application.start()
    return application


@pytest.fixture
def extraction():
    """The buffer the app and its roster share -- the reporter's other end.

    Its own fixture so both sides of `app_and_client` and any test that drives
    it get the one instance. Two would let the `/workers` answer and the
    `/extraction` answer disagree about the same ingest, which is the failure
    the single-channel design rules out.
    """
    return ExtractionActivity()


@pytest.fixture
async def app_and_client(db_path, fake_model, extraction):
    application = await _started(model=fake_model, db_path=db_path)
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
            # Wired as the composition root wires it, so `/api/workers` is
            # exercised in its real shape: without this a running turn has no
            # way back to its project and the cross-project route would answer
            # empty while looking correct.
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
        # The application's own policy, not a fresh one: the routes are only
        # able to change anything because they hold the object the executor
        # reads, and a test against a copy would pass while proving nothing.
        policy=application.policy,
        topics=application.topic_readers,
        topic_repository=application.topic_repository,
        graphs=application.graphs,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
def service(app_and_client):
    return app_and_client[0].service


# ---------------- projects ----------------


async def test_list_projects_starts_empty_then_shows_a_created_one(client):
    assert (await client.get("/api/projects")).json() == []

    response = await client.post("/api/projects", json={"name": "atlas"})
    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "atlas"
    assert created["id"]

    listed = (await client.get("/api/projects")).json()
    # A fresh project is held by nobody and has no tip: exactly the state a
    # row needs to offer "open" rather than a join that would be rejected.
    #
    # **The summary is all zeros rather than absent, and that is the claim.**
    # `ProjectSummaries.all` answers only the projects it has rows for, so a
    # project created a second ago is missing from it entirely and
    # `project_view` is handed `None`. This asserts the whole body, so it is
    # what would fail if that `None` ever started omitting the object instead
    # of filling it -- which would make every consumer write the same `?? 0`
    # fallback, and this console has shipped a silently-absent field read as a
    # zero before.
    assert listed == [
        {
            "id": created["id"],
            "name": "atlas",
            "active_session_id": None,
            "tip_at_event": 0,
            "summary": {
                "topics": 0,
                "topics_open": 0,
                "sources": 0,
                "extracted": 0,
                "courses": 0,
                "sessions": 0,
                "last_activity": None,
            },
        }
    ]


async def test_reading_one_project_answers_its_identity_holder_and_reading_head(client):
    """`GET /api/projects/{id}`, the console's only single-project read.

    Asserted against the whole body rather than field by field, so a key
    added here has to be added to this test's set as well -- which is what
    `set(body)` is for.

    The holder is what earned the route. A project page resolves its
    transcript, its composer and (until this slice) its Workspace tab off
    `active_session_id`, and joining is what sets it -- so the read has to
    reflect a join rather than a creation. While somebody holds the project
    the reading head is that same session; the test below is the one that can
    tell the two apart.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    response = await client.get(f"/api/projects/{project_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == project_id
    assert body["name"] == "atlas"
    assert body["active_session_id"] == session_id
    assert body["reading_head_session_id"] == session_id
    assert set(body) == {
        "id",
        "name",
        "active_session_id",
        "tip_at_event",
        "reading_head_session_id",
    }


async def test_a_released_project_still_names_a_session_to_read_it_through(client):
    """The state the whole reading head exists for, and the one a test over a
    held project cannot reach.

    A project between sessions has files and no holder. Until this slice the
    only session id on the wire was `active_session_id`, so the console's
    workspace, its documents and its file routes all went dark the moment
    somebody ended a session -- the tab was gated on exactly this and the gate
    was right, because there was nothing behind it.

    The test that distinguishes the candidate resolutions is this one, not the
    held case: `reading_head` returning `state.active_session_id` unchanged
    passes every assertion in the test above and fails here on `None`.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    await client.post(f"/api/sessions/{session_id}/message", json={"text": "hello"})
    await client.post(f"/api/sessions/{session_id}/release")

    body = (await client.get(f"/api/projects/{project_id}")).json()

    assert body["active_session_id"] is None
    assert body["reading_head_session_id"] == session_id


async def test_the_listing_does_not_carry_a_reading_head(client):
    """One aggregate fold per row is what this route costs already.

    `landing.ts` defers a feature on exactly that cost, and a reading head is
    a page's question rather than a row's: no listing surface reads a session
    to fold files through. Pinned rather than left implicit because the two
    presenters were one function until this slice and the cheap way to add
    the field would have put it on both.
    """
    await client.post("/api/projects", json={"name": "atlas"})

    (row,) = (await client.get("/api/projects")).json()

    assert "reading_head_session_id" not in row


async def test_reading_an_unknown_project_is_a_404(client):
    """Not an empty project: an id nothing was written under folds to a `new`
    state rather than raising, so without the `_require_project` check this
    route would answer 200 with a nameless project -- which reads to a caller
    as a project that exists and happens to be bare."""
    response = await client.get(f"/api/projects/{uuid4()}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", ""),
        ("GET", "/sources"),
        ("GET", "/topics"),
        ("DELETE", ""),
        ("POST", "/join"),
    ],
)
async def test_a_deleted_project_is_absent_from_every_route(client, method, path):
    """Deleted means gone, and `_require_project` is where that is said once.

    Until 2026-08-27 it refused only the `new` state, so a deleted project
    answered its reads in full on all seventy-odd project-scoped routes -- its
    name, its sources, its topics. Nothing could be *written* through them
    (`Project.decide` refuses every command against a deleted project), which
    is what kept it quiet: a retired project simply went on answering
    questions about itself.

    Parametrised over five routes rather than asserting on one, because the
    defect was never in a route -- it was in the one guard they share, and a
    single-route test would pass again the moment somebody added a sixth route
    that forgot to call it. `DELETE` and `/join` are in the list because they
    used to answer the domain's 409 instead; they now agree with the rest.

    Proved red before it was trusted green: with the `"deleted"` arm removed
    from `_require_project`, the three GETs return 200 and the other two 409.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    response = await client.request(method, f"/api/projects/{project_id}{path}")

    assert response.status_code == 404
    assert str(project_id) in response.json()["detail"]


async def test_a_deleted_projects_name_is_free_again(client):
    """The other half of "deleted means gone", and the reason 404 is safe here.

    `event_store.list_projects` already filtered deleted ids out, and the
    duplicate-name check reads that listing -- so the name was reusable while
    the project it belonged to still answered `GET /api/projects/{id}` with
    it. Those two facts could not both be right. This pins the one that was.
    """
    first = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{first}")

    second = await client.post("/api/projects", json={"name": "atlas"})

    assert second.status_code == 200
    assert second.json()["id"] != first


async def test_creating_a_project_with_a_taken_name_does_not_create_a_second(client):
    first = await client.post("/api/projects", json={"name": "atlas"})
    assert first.status_code == 200

    second = await client.post("/api/projects", json={"name": "atlas"})
    assert second.status_code == 409

    listed = (await client.get("/api/projects")).json()
    # The proof that matters: still exactly one project, not just an error
    # response for the second attempt.
    assert len(listed) == 1
    assert listed[0]["id"] == first.json()["id"]


async def test_joining_a_project_starts_a_session_that_inherits_its_files(client, service):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first_join = await client.post(f"/api/projects/{project_id}/join")
    assert first_join.status_code == 200
    first_session_id = first_join.json()["id"]
    assert first_join.json()["project_id"] == project_id

    # Put a known file on the first holder's stream directly -- deterministic,
    # unlike relying on the fake model to decide to write one -- then hand the
    # project's tip back so a second join has something to inherit.
    from uuid import UUID as _UUID

    session = await service.load(_UUID(first_session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)
    await service.release_project(_UUID(first_session_id))

    second_join = await client.post(f"/api/projects/{project_id}/join")
    assert second_join.status_code == 200
    second_session_id = second_join.json()["id"]
    assert second_session_id != first_session_id

    second_body = (await client.get(f"/api/sessions/{second_session_id}")).json()
    assert second_body["project_id"] == project_id
    assert any(f["path"] == "/atlas.py" for f in second_body["files"])

    file_body = (
        await client.get(
            f"/api/sessions/{second_session_id}/files", params={"path": "/atlas.py"}
        )
    ).json()
    # The assertion that actually proves inheritance: the byte content of the
    # file on the *second* session matches what was written on the first.
    assert file_body["content"] == "shared content\n"


async def test_joining_a_project_attaches_the_knowledge_tools(app_and_client):
    """The web-route counterpart of the REPL's `/project use` attach fix.

    `application.turns_tools()` is the surface the executor actually reads
    from on the next turn -- the same surface
    `test_project_use_attaches_the_knowledge_graph` asserts on for the REPL.
    Before `POST /api/projects/{id}/join`, no project is attached, so the
    knowledge tools must be absent; asserting that first is what lets this
    test fail if the join route stops calling `attach_project`.
    """
    application, client = app_and_client

    names_before = {tool.name for tool in application.turns_tools()}
    assert "remember" not in names_before
    assert "graph_search" not in names_before
    assert "unmerge" not in names_before

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    join = await client.post(f"/api/projects/{project_id}/join")
    assert join.status_code == 200

    names_after = {tool.name for tool in application.turns_tools()}
    assert "remember" in names_after
    assert "graph_search" in names_after
    assert "unmerge" in names_after


async def test_joining_an_already_held_project_names_the_holder(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first_join = await client.post(f"/api/projects/{project_id}/join")
    holder_session_id = first_join.json()["id"]

    second_join = await client.post(f"/api/projects/{project_id}/join")

    assert second_join.status_code == 409
    assert holder_session_id in second_join.json()["detail"]


async def test_releasing_a_session_frees_its_project_for_the_next_one(client):
    """The loop the web app could not close: finish here, start fresh there.

    Before `POST /api/sessions/{id}/release` this took a REPL, or a restart:
    the browser had no verb that gave a project back, so the second join in
    this test could only ever be the 409 above.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    release = await client.post(f"/api/sessions/{first}/release")
    assert release.status_code == 200
    assert release.json() == {"released": True, "project_id": project_id}

    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] is None

    second = await client.post(f"/api/projects/{project_id}/join")
    assert second.status_code == 200
    assert second.json()["id"] != first


async def test_releasing_a_session_twice_is_not_an_error(client):
    """Releasing what you no longer hold answers calmly rather than raising.

    This replaces a test that made a project-less session with
    `POST /api/sessions` and released that, asserting
    `{"released": False, "project_id": None}`. A session outside a project can
    no longer be built, so that response shape is unreachable and the branch in
    `release_session` that returns it is dead. The second release stands in as
    the reachable way to release something you do not hold, which is the case
    that has to stay quiet -- every REPL and browser exit path calls release
    unconditionally.

    Note what the second call answers: `released: True`, though nothing moved.
    `release_project` no-ops when the session is not the holder and the route
    reports success either way. Asserted as it stands rather than as it ought
    to be; changing the route is not this test's to do.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    assert (await client.post(f"/api/sessions/{session_id}/release")).status_code == 200

    response = await client.post(f"/api/sessions/{session_id}/release")

    assert response.status_code == 200
    assert response.json() == {"released": True, "project_id": project_id}


async def test_release_advances_the_tip_so_the_next_session_inherits(client, service):
    """Releasing is how work travels between sessions, not just cleanup.

    `release_project` advances the project's tip; a UI that only ever joined
    would fork every new session from a tip that never moved, silently losing
    everything the previous session wrote.
    """
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    session = await service.load(_UUID(first))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)

    assert (await client.post(f"/api/sessions/{first}/release")).status_code == 200

    second = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    body = (
        await client.get(f"/api/sessions/{second}/files", params={"path": "/atlas.py"})
    ).json()
    assert body["content"] == "shared content\n"


async def test_taking_over_a_held_project_ends_the_holder_and_starts_fresh(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    second = await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    assert second.status_code == 200
    assert second.json()["id"] != first
    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] == second.json()["id"]


async def test_a_session_reports_whether_it_still_holds_its_project(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is True

    await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    # The fact the UI needs to stop offering this session as the live one.
    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is False


async def test_deleting_a_project_removes_it_from_the_listing(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "project_id": project_id}
    assert (await client.get("/api/projects")).json() == []


async def test_a_deleted_project_cannot_be_joined(client):
    """404, and deliberately no longer the word "deleted" in the body.

    This asserted 409 with "deleted" in the detail, which refused the join and
    confirmed the project existed in the same breath. The refusal is what
    mattered; the confirmation was the half that disagreed with every other
    project-scoped route.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    join = await client.post(f"/api/projects/{project_id}/join")

    assert join.status_code == 404
    assert str(project_id) in join.json()["detail"]


async def test_deleting_a_held_project_needs_the_holder_released_first(client):
    """The 409 names the holder, so the UI can offer the thing that fixes it."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    holder = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    refused = await client.delete(f"/api/projects/{project_id}")
    assert refused.status_code == 409
    assert holder in refused.json()["detail"]
    assert len((await client.get("/api/projects")).json()) == 1

    accepted = await client.delete(f"/api/projects/{project_id}?release_holder=true")
    assert accepted.status_code == 200
    assert (await client.get("/api/projects")).json() == []


async def test_deleting_a_project_leaves_its_sessions_readable(client, service):
    """Deletion retires the project, not the work done inside it."""
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    session = await service.load(_UUID(session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "kept\n"}))
    await service._repository.save(session)

    await client.delete(f"/api/projects/{project_id}?release_holder=true")

    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["id"] == session_id
    assert any(f["path"] == "/atlas.py" for f in body["files"])
    file_body = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/atlas.py"})
    ).json()
    assert file_body["content"] == "kept\n"


async def test_a_deleted_projects_name_can_be_used_again(client):
    first = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{first}")

    again = await client.post("/api/projects", json={"name": "atlas"})

    assert again.status_code == 200
    assert again.json()["id"] != first


async def test_deleting_an_unknown_project_is_a_404(client):
    response = await client.delete(f"/api/projects/{uuid4()}")

    assert response.status_code == 404


async def test_a_turn_reattaches_the_sessions_own_knowledge_graph(app_and_client):
    """The bug behind "the agent says it has no knowledge graph".

    Attaching only at join meant any later turn ran with whatever graph was
    attached last -- or none, after a restart -- even though the session's
    recorded prompt promises `remember`/`graph_search`/`unmerge`. Detaching
    here stands in for that drift; the turn has to put it back.
    """
    application, client = app_and_client

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    await application.service.detach_project()
    assert "remember" not in {tool.name for tool in application.turns_tools()}

    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    assert response.status_code == 200

    assert "remember" in {tool.name for tool in application.turns_tools()}


# ---------------- corpus ----------------


async def _project_with_sources(application, client, *documents) -> str:
    """A project holding `documents`, with the corpus projection caught up.

    Takes document *specs* -- keyword dicts -- rather than built commands,
    because `StoreSourceDocument` names the corpus it targets and this helper
    is what decides which corpus that is. A caller cannot name an id the helper
    has not created yet.

    Stores through the `Corpus` aggregate rather than through `remember`,
    because `remember` runs an extraction and these tests are about the read
    path. The projection follows the log asynchronously, so the wait is what
    makes the assertions deterministic rather than timing-dependent.
    """
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    corpus = build_corpus_repository(
        application.service._repository.store,
        application.service._repository.publisher,
        snapshot_store=application.service._repository.snapshot_store,
    )
    aggregate = await corpus.load_or_create(UUID(project_id))
    for spec in documents:
        # A dict is a store spec this helper addresses; anything else is
        # already a command (a drop), which names no corpus and needs none.
        aggregate.execute(
            StoreSourceDocument(corpus_id=UUID(project_id), **spec)
            if isinstance(spec, dict)
            else spec
        )
    await corpus.save(aggregate)
    await application.corpus_caught_up()
    return project_id
