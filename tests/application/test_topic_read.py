"""`TopicReadPort`, over a real topic aggregate and a real projection.

The port's whole point is that a caller never has to make a second call to
learn why a topic was flagged, and that an unknown or foreign id reads as
absence rather than an exception. Both properties are only real if they hold
against the actual store, not a stub of it -- so these tests build a `Topic`
through `OpenTopic` the way the tools do, and start a real `TopicRunner`
against it.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore

from research_team.domain.topic import OpenTopic, Topic
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.infrastructure.persistence.topic_reader import ProjectTopicReader
from research_team.infrastructure.persistence.topics import TopicRunner


@pytest.fixture
async def running(db_path: str, store: SQLiteEventStore, publisher: InMemoryEventBus):
    """A started topic runner over a real store, stopped on teardown."""
    runner = TopicRunner(store, db_path, publisher)
    await runner.start()
    yield runner
    await runner.stop()


@pytest.fixture
def repository(
    store: SQLiteEventStore, publisher: InMemoryEventBus, snapshot_store: SQLiteSnapshotStore
):
    return build_topic_repository(store, publisher, snapshot_store=snapshot_store)


@pytest.fixture
def project_id():
    return uuid4()


@pytest.fixture
async def opened_topic(repository, running, project_id) -> UUID:
    """A live topic, opened through the aggregate, visible to the projection."""
    topic = repository.create_new(uuid4())
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=project_id,
            question="Does spacing help?",
            rationale="the syllabus asserts it without a citation",
        )
    )
    await repository.save(topic)
    await running.caught_up()
    return topic.aggregate_id


@pytest.fixture
def topic_reader(running, repository, project_id) -> ProjectTopicReader:
    return ProjectTopicReader(running, repository, running.corpus_facts, project_id)


@pytest.fixture
def reader_for_other_project(running, repository) -> ProjectTopicReader:
    return ProjectTopicReader(running, repository, running.corpus_facts, uuid4())


async def test_a_view_carries_both_the_summary_and_why_it_needs_attention(
    topic_reader, opened_topic
):
    """The list is ranked on attention, so the thing that ranks it travels with the row.

    Never investigated is a real trigger on a freshly opened topic, so this
    is the flag arriving through the port rather than a contrived one.
    """
    views = await topic_reader.list_topics()

    assert [view.summary.question for view in views] == ["Does spacing help?"]
    assert "topic.never_investigated" in views[0].attention.triggers
    assert views[0].needs_attention is True


async def test_an_unknown_topic_reads_as_none_rather_than_raising(topic_reader):
    """Absence is the expected case for a hand-edited URL, not a failure."""
    assert await topic_reader.read_topic(uuid4()) is None


async def test_a_topic_belonging_to_another_project_reads_as_none(
    reader_for_other_project, opened_topic
):
    """Project scoping is the reader's job, not the caller's.

    Every port here is bound to one project at construction precisely so a
    caller cannot pass a different id; reading by topic id is the one call
    that could sidestep that, so it checks.
    """
    assert await reader_for_other_project.read_topic(opened_topic) is None
