"""Tests for TopicService, coordinating topic aggregate lifecycle."""

from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError, InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore

from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.research.application.topics import TopicService


@pytest.fixture
def repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus,
    snapshot_store: SQLiteSnapshotStore,
):
    return build_topic_repository(store, publisher, snapshot_store=snapshot_store)


@pytest.fixture
def topic_service(repository):
    return TopicService(repository)


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


async def test_topic_service_open_and_restate_question(topic_service, repository, project_id):
    topic_id = await topic_service.open_topic(
        project_id=project_id,
        question="Initial question?",
        rationale="Testing topic service",
        scope="Verify lifecycle",
    )
    topic = await repository.load(topic_id)
    assert topic.state.status == "open"
    assert topic.state.question == "Initial question?"
    assert topic.state.rationale == "Testing topic service"

    await topic_service.restate_question(
        topic_id=topic_id,
        question="Refined self-contained question?",
        rationale="Clarification per B39",
    )
    reloaded = await repository.load(topic_id)
    assert reloaded.state.question == "Refined self-contained question?"
    assert reloaded.state.previous_questions == ["Initial question?"]


async def test_topic_service_sub_questions_and_findings(topic_service, repository, project_id):
    topic_id = await topic_service.open_topic(
        project_id=project_id,
        question="Main question?",
        rationale="Investigating something",
    )
    await topic_service.add_sub_question(topic_id, "sq1", "Sub question 1?")
    topic = await repository.load(topic_id)
    assert "sq1" in topic.state.sub_questions
    assert topic.state.open_sub_questions == ["sq1"]

    await topic_service.resolve_sub_question(topic_id, "sq1", "Answer to sub question 1")
    topic = await repository.load(topic_id)
    assert topic.state.sub_questions["sq1"].answer == "Answer to sub question 1"
    assert topic.state.open_sub_questions == []

    await topic_service.record_finding(topic_id, "Discovered valuable finding", ["src1"])
    topic = await repository.load(topic_id)
    assert topic.state.findings == 1


async def test_topic_service_links_and_gaps(topic_service, repository, project_id):
    topic_id = await topic_service.open_topic(
        project_id=project_id,
        question="Main question?",
        rationale="Investigating something",
    )
    await topic_service.link_source(topic_id, "src-1", relation="supports", note="good source")
    topic = await repository.load(topic_id)
    assert "src-1" in topic.state.source_ids

    await topic_service.unlink_source(topic_id, "src-1", reason="superseded")
    topic = await repository.load(topic_id)
    assert "src-1" not in topic.state.source_ids

    await topic_service.record_gap(topic_id, looking_for="Missing data", tried=["searxng"])
    topic = await repository.load(topic_id)
    assert topic.state.gaps == 1


async def test_topic_service_status_change(topic_service, repository, project_id):
    topic_id = await topic_service.open_topic(
        project_id=project_id,
        question="Main question?",
        rationale="Investigating something",
    )
    await topic_service.set_status(
        topic_id, "answered", justification="All sub-questions resolved"
    )
    topic = await repository.load(topic_id)
    assert topic.state.status == "answered"

    with pytest.raises(CommandRejectedError):
        # Blank justification refused
        await topic_service.set_status(topic_id, "open", justification="")
