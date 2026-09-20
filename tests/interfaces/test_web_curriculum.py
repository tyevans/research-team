"""Curriculum parsed view, interactive component, learner attempt, and progress routes.

The parsed route and the attempt route are two halves of one decision: the
learner projection strips the answer key, so the browser cannot grade and has
to ask. Both halves are tested here rather than only the parse, because a
projection that withholds and an endpoint that hands the key back would each
pass on their own.
"""

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application import SummaryProjects, WorkerRoster
from research_team.composition import build_application as _build_application
from research_team.domain import DeleteFile, WriteFile
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from tests.conftest import start_session


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
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
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


# ---------------- components ----------------
#
# The parsed route and the attempt route are two halves of one decision: the
# learner projection strips the answer key, so the browser cannot grade and has
# to ask. Both halves are tested here rather than only the parse, because a
# projection that withholds and an endpoint that hands the key back would each
# pass on their own.

LESSON = """\
---
type: lesson
---

# Declaring severity

```component:mcq
id: sev-1
prompt: What severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: |
  Severity is a communication decision.
```

```component:from-the-future
shape: unknowable
```
"""

LESSON_PATH = "/course/01-lesson.md"


async def _with_lesson(service, content=LESSON, path=LESSON_PATH) -> str:
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path=path, file_data={"content": content}))
    await service._repository.save(session)
    return str(session_id)


async def test_the_parsed_view_returns_frontmatter_and_blocks_in_order(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["frontmatter"] == {"type": "lesson"}
    assert [b["kind"] for b in body["blocks"]] == ["markdown", "component", "component"]
    assert body["blocks"][2]["unknown"] is True


async def test_the_author_view_is_the_default_and_carries_the_key(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["view"] == "author"
    assert body["blocks"][1]["data"]["options"][1]["correct"] is True


async def test_the_learner_view_does_not_ship_the_answer(client, service):
    """Asserted over the response text, because the failure that matters is a
    secret reaching the wire by any route, not one particular field surviving."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learner"},
    )

    assert "Textbook SEV-2" not in response.text
    assert "communication decision" not in response.text
    assert "What severity?" in response.text


async def test_an_unrecognised_view_is_refused_rather_than_defaulted(client, service):
    """Defaulting a typo to the author view would leak the key on `view=learnr`."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learnr"},
    )

    assert response.status_code == 422


async def test_a_parsed_file_can_be_read_in_the_past(client, service):
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    session.execute(DeleteFile(path="/c.md"))
    await service._repository.save(session)

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    written_at = next(r["index"] for r in events if r["type"] == "FileWritten")

    gone = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/c.md"}
    )
    past = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": "/c.md", "at": written_at},
    )

    assert gone.status_code == 404
    assert len(past.json()["blocks"]) == 3


async def test_a_missing_file_is_a_404_from_the_parsed_route_too(client, service):
    session_id = await _with_lesson(service)
    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/nope.md"}
    )
    assert response.status_code == 404


async def test_a_right_answer_is_graded_and_the_rationale_returned(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": 1},
        )
    ).json()

    assert body["correct"] is True
    assert body["feedback"] == ["Textbook SEV-2."]
    assert "communication decision" in body["rationale"]


async def test_a_wrong_answer_is_graded_rather_than_refused(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": 0},
    )

    assert response.status_code == 200
    assert response.json()["correct"] is False
    assert response.json()["correct_options"] == [1]


async def test_an_attempt_at_a_component_that_is_not_there_is_a_404(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "nope", "response": 1},
    )

    assert response.status_code == 404


async def test_a_response_of_the_wrong_shape_is_a_400_not_a_500(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": {"a": 1}},
    )

    assert response.status_code == 400


async def test_an_attempt_is_graded_against_the_file_as_it_was(client, service):
    """Grading at HEAD would mark yesterday's attempt against today's key."""
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    await service._repository.save(session)
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    original = next(r["index"] for r in events if r["type"] == "FileWritten")

    # The revision moves the answer rather than adding one: a second `correct`
    # option would make the item multiple-response and change what "0" means.
    revised = (
        LESSON.replace("correct: false", "correct: WAS_FALSE")
        .replace("correct: true", "correct: false")
        .replace("correct: WAS_FALSE", "correct: true")
    )
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": revised}))
    await service._repository.save(session)

    now = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0},
    )
    then = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0, "at": original},
    )

    assert now.json()["correct"] is True
    assert then.json()["correct"] is False


# ---------------- learner progress (B28) ----------------
#
# An attempt used to be graded and then forgotten: a reload lost every answer,
# `persist: true` was accepted and ignored, and the sequence of attempts on one
# item existed nowhere. These pin the other half -- that the verdict the learner
# was shown is also a fact the log holds.

CHECKLIST_LESSON = """\
# Runbook

```component:checklist
id: triage
persist: true
items:
  - text: "Page the on-call"
  - text: "Open an incident channel"
  - text: "Declare a severity"
```

```component:checklist
id: ephemeral
items:
  - text: "Stretch"
```
"""


async def test_an_attempt_is_remembered(client, service):
    session_id = await _with_lesson(service)

    marked = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": 1},
    )
    assert marked.status_code == 200
    # The verdict still comes back unchanged; progress rides alongside it.
    assert marked.json()["correct"] is True
    assert marked.json()["progress"]["attempts"] == 1

    progress = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH}
    )
    assert progress.json()["items"]["sev-1"]["correct"] is True


async def test_three_attempts_are_three_attempts_and_the_best_one_is_kept(client, service):
    session_id = await _with_lesson(service)

    for response in (0, 0, 1):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": response},
        )

    item = (
        await client.get(f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH})
    ).json()["items"]["sev-1"]
    assert item["attempts"] == 3
    assert item["correct"] is True
    assert item["best_score"] == 1.0


async def test_being_wrong_after_being_right_does_not_lose_the_completion(client, service):
    session_id = await _with_lesson(service)

    for response in (1, 0):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": response},
        )

    item = (
        await client.get(f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH})
    ).json()["items"]["sev-1"]
    assert item["correct"] is True
    assert item["last_score"] == 0.0


async def test_a_session_nobody_has_answered_anything_in_reports_nothing(client, service):
    """The ordinary case for every course before its first learner, and not a
    404 -- a client that has to handle \"no progress stream yet\" as an error
    handles it wrong somewhere."""
    session_id = await _with_lesson(service)

    progress = await client.get(f"/api/sessions/{session_id}/progress")
    assert progress.status_code == 200
    assert progress.json()["items"] == {}


async def test_progress_for_the_whole_session_keys_by_path_and_id(client, service):
    """Ids are only unique within a document, so the unnarrowed shape has to
    carry the path or two lessons' `sev-1` would collide."""
    session_id = await _with_lesson(service)
    session = await service.load(UUID(session_id))
    session.execute(WriteFile(path="/other.md", file_data={"content": LESSON}))
    await service._repository.save(session)

    for path in (LESSON_PATH, "/other.md"):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": path, "component_id": "sev-1", "response": 1},
        )

    body = (await client.get(f"/api/sessions/{session_id}/progress")).json()
    assert body["scope"] == "session"
    assert set(body["items"]) == {f"{LESSON_PATH}#sev-1", "/other.md#sev-1"}


# --- checklists, which is what `persist: true` was promising ---------------


async def test_a_persisting_checklist_remembers_its_boxes(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    saved = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "triage", "checked": [2, 0]},
    )
    assert saved.status_code == 200
    assert saved.json()["checked"] == [0, 2]

    reloaded = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": "/r.md"}
    )
    assert reloaded.json()["items"]["triage"]["checked"] == [0, 2]


async def test_unticking_a_box_sticks(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    for checked in ([0, 1], [1]):
        await client.post(
            f"/api/sessions/{session_id}/progress/checklist",
            json={"path": "/r.md", "component_id": "triage", "checked": checked},
        )

    reloaded = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": "/r.md"}
    )
    assert reloaded.json()["items"]["triage"]["checked"] == [1]


async def test_a_checklist_that_did_not_ask_to_persist_is_refused(client, service):
    """`persist` is honoured rather than assumed, so a client cannot quietly
    accumulate state the author never opted into."""
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "ephemeral", "checked": [0]},
    )
    assert refused.status_code == 400
    assert "persist" in refused.json()["detail"]


async def test_a_box_that_is_not_on_the_checklist_is_refused(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "triage", "checked": [9]},
    )
    assert refused.status_code == 400
    assert "9" in refused.json()["detail"]


async def test_checklist_state_cannot_be_posted_to_an_mcq(client, service):
    session_id = await _with_lesson(service)

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": LESSON_PATH, "component_id": "sev-1", "checked": [0]},
    )
    assert refused.status_code == 400
    assert "mcq" in refused.json()["detail"]
