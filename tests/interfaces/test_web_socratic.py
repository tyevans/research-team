"""Tests for Socratic dialogue web routes: framing, replies, attempts, conclusions, reads."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness
from fastapi.testclient import TestClient

from research_team.dialogue.application.socratic import (
    DialogueRegistry,
    SocraticDialogueService,
    SocraticFraming,
    SocraticPrompt,
)
from research_team.dialogue.domain.socratic import SocraticDialogue
from research_team.interfaces.web.app import create_app
from research_team.platform.shared.ports import ActivityDelta, ActivityRemark


class StubDialogueRow:
    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        topic: str = "the Nicene settlement",
        goal: str = "understand it",
        stopping_condition: str = "state it clearly",
        opening_prompt: str = "What do you think?",
        pending_prompt: str = "Why do you think that?",
        opened_at: datetime | None = None,
        status: str = "started",
        concluded_reason: str | None = None,
        turn_count: int = 0,
        observations: list[str] | None = None,
    ):
        self.id = id
        self.project_id = project_id
        self.topic = topic
        self.goal = goal
        self.stopping_condition = stopping_condition
        self.opening_prompt = opening_prompt
        self.pending_prompt = pending_prompt
        self.opened_at = opened_at or datetime(2026, 8, 17, tzinfo=UTC)
        self.status = status
        self.concluded_reason = concluded_reason
        self.turn_count = turn_count
        self.observations = observations or []


class StubDialogueRunner:
    def __init__(self):
        self.rows: dict[UUID, StubDialogueRow] = {}
        self.turns: dict[UUID, list] = {}

    async def get(self, dialogue_id: UUID):
        return self.rows.get(dialogue_id)

    async def caught_up(self):
        pass

    async def turns_for(self, dialogue_id: UUID):
        return self.turns.get(dialogue_id, [])

    async def for_project(self, project_id: UUID):
        return [r for r in self.rows.values() if r.project_id == project_id]


class StubExecutor:
    def __init__(self, framing=None, prompts=None, fail_frame=None, fail_respond=None):
        self.framing = framing or SocraticFraming(
            goal="understand the Nicene settlement",
            stopping_condition="explain it plainly",
            opening_prompt="Where would you begin?",
        )
        self.prompts = list(prompts or [SocraticPrompt(prompt="Why do you say that?")])
        self.fail_frame = fail_frame
        self.fail_respond = fail_respond

    async def frame(self, *, project_id, topic):
        if self.fail_frame is not None:
            raise self.fail_frame
        return self.framing

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        if self.fail_respond is not None:
            raise self.fail_respond
        for note in [
            ActivityDelta(message_id="m1", text="composing"),
            ActivityRemark(text="checking source"),
        ]:
            on_activity(note)
        return self.prompts.pop(0)


def socratic_service(executor, runner) -> SocraticDialogueService:
    transcripts = AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)
    return SocraticDialogueService(
        executor=executor,
        dialogues=DialogueRegistry(now=lambda: 0.0),
        read_model=runner,
        now=lambda: 0.0,
        transcripts=transcripts,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    )


def client(service: SocraticDialogueService, runner: StubDialogueRunner) -> TestClient:
    return TestClient(
        create_app(service=None, feed=None, turns=None, socratic=service, dialogues=runner)
    )


def frames(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_start_dialogue_returns_framing_and_blocks():
    runner = StubDialogueRunner()
    executor = StubExecutor()
    service = socratic_service(executor, runner)

    # Pre-seed what runner would have once projection catches up
    async def fake_caught_up():
        for d_id in service._dialogues.active_ids():
            held = service._dialogues._held[d_id]
            runner.rows[d_id] = StubDialogueRow(
                id=d_id,
                project_id=held.project_id,
                topic=held.topic,
                goal=held.goal,
                stopping_condition=held.stopping_condition,
                opening_prompt="Where would you begin?",
                pending_prompt="Where would you begin?",
            )

    runner.caught_up = fake_caught_up

    proj = uuid4()
    http = client(service, runner)
    resp = http.post(
        f"/api/projects/{proj}/dialogues", json={"topic": "the Nicene settlement"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["topic"] == "the Nicene settlement"
    assert data["goal"] == "understand the Nicene settlement"
    assert data["stoppingCondition"] == "explain it plainly"
    assert data["openingBlocks"] == [{"kind": "markdown", "text": "Where would you begin?"}]
    assert data["pendingBlocks"] == [{"kind": "markdown", "text": "Where would you begin?"}]
    assert data["status"] == "started"


def test_start_dialogue_handles_bad_framing_as_502():
    runner = StubDialogueRunner()
    executor = StubExecutor(fail_frame=ValueError("bad format"))
    service = socratic_service(executor, runner)
    http = client(service, runner)

    resp = http.post(f"/api/projects/{uuid4()}/dialogues", json={"topic": "broken"})
    assert resp.status_code == 502
    assert "could not be framed" in resp.json()["detail"]


def test_start_dialogue_unconfigured_answers_503():
    http = TestClient(create_app(service=None, feed=None, turns=None))
    resp = http.post(f"/api/projects/{uuid4()}/dialogues", json={"topic": "t"})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_reply_streams_sse_frames_with_topic_and_blocks():
    runner = StubDialogueRunner()
    executor = StubExecutor(
        prompts=[
            SocraticPrompt(
                prompt=(
                    "```component:mcq\n"
                    "id: q1\n"
                    "prompt: Which year?\n"
                    "options:\n"
                    "  - text: '325'\n"
                    "    correct: true\n"
                    "  - text: '451'\n"
                    "    correct: false\n"
                    "```"
                ),
                position=0,
            )
        ]
    )
    service = socratic_service(executor, runner)
    proj = uuid4()
    dialogue_id = await service.begin(project_id=proj, topic="Nicaea")

    http = client(service, runner)
    resp = http.post(
        f"/api/projects/{proj}/dialogues/{dialogue_id}/reply",
        json={"reply": "The council happened in 325."},
    )

    assert resp.status_code == 200
    parsed = frames(resp)
    # First frame is dialogue opened with topic
    assert parsed[0]["type"] == "dialogue"
    assert parsed[0]["topic"] == "Nicaea"
    assert parsed[0]["dialogue_id"] == str(dialogue_id)

    # Last frame is prompt with projected blocks (learner view strips 'correct: true')
    last = parsed[-1]
    assert last["type"] == "prompt"
    assert last["position"] == 0
    assert last["concluded"] is False
    assert last["blocks"][0]["kind"] == "component"
    assert last["blocks"][0]["type"] == "mcq"
    assert "correct" not in str(last["blocks"][0]["data"])


def test_reply_to_unknown_dialogue_answers_404():
    runner = StubDialogueRunner()
    service = socratic_service(StubExecutor(), runner)
    http = client(service, runner)

    resp = http.post(
        f"/api/projects/{uuid4()}/dialogues/{uuid4()}/reply",
        json={"reply": "hello"},
    )
    assert resp.status_code == 404


def test_read_dialogue_detail():
    runner = StubDialogueRunner()
    service = socratic_service(StubExecutor(), runner)
    proj = uuid4()
    d_id = uuid4()
    runner.rows[d_id] = StubDialogueRow(
        id=d_id, project_id=proj, topic="Council", turn_count=1
    )

    http = client(service, runner)
    resp = http.get(f"/api/projects/{proj}/dialogues/{d_id}")

    assert resp.status_code == 200
    assert resp.json()["dialogueId"] == str(d_id)
    assert resp.json()["topic"] == "Council"
    assert resp.json()["turnCount"] == 1


def test_read_unknown_dialogue_answers_404():
    runner = StubDialogueRunner()
    service = socratic_service(StubExecutor(), runner)
    http = client(service, runner)

    resp = http.get(f"/api/projects/{uuid4()}/dialogues/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_end_dialogue_marks_concluded():
    runner = StubDialogueRunner()
    service = socratic_service(StubExecutor(), runner)
    proj = uuid4()
    d_id = await service.begin(project_id=proj, topic="Council")
    runner.rows[d_id] = StubDialogueRow(id=d_id, project_id=proj, topic="Council")

    http = client(service, runner)
    resp = http.post(f"/api/projects/{proj}/dialogues/{d_id}/end")

    assert resp.status_code == 200
    assert resp.json() == {"status": "concluded"}
    # Cache entry dropped
    assert service._dialogues.get(d_id, proj) is None
