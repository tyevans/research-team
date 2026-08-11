"""The topic table and the queue computed over it.

The table is a projection, so the property that matters is that it agrees with
the fold: a queue built from rows must say what a queue built by replaying every
topic stream would have said. The tightest test here is exactly that comparison.

The second property is that attention is *computed*. A row is a snapshot of the
fold and nothing more, so a change in the corpus -- which touches no topic
stream at all -- has to move the queue. That is the whole reason there is no
stored needs-attention flag, and `test_dropping_a_source_moves_the_queue_without
_touching_a_topic` is what would fail if someone added one.
"""

from uuid import uuid4

import pytest

from research_team.application.topic_attention import attention_for
from research_team.domain.corpus import DropSourceDocument, StoreSourceDocument
from research_team.domain.topic import (
    AddSubQuestion,
    LinkSource,
    OpenTopic,
    RecordFinding,
    RecordGap,
    RecordInvestigation,
    SetTopicStatus,
    Topic,
)
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.topics import TopicRow, TopicRunner, TopicStore


@pytest.fixture
async def running(db_path, store, publisher, snapshot_store):
    """A started topic runner over a real store, stopped on teardown."""
    runner = TopicRunner(store, db_path, publisher)
    await runner.start()
    yield runner
    await runner.stop()


@pytest.fixture
def topics(store, publisher, snapshot_store):
    return build_topic_repository(store, publisher, snapshot_store=snapshot_store)


@pytest.fixture
def corpus(store, publisher, snapshot_store):
    return build_corpus_repository(store, publisher, snapshot_store=snapshot_store)


async def open_topic(topics, project_id, *commands, question="q?") -> Topic:
    topic = topics.create_new(uuid4())
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=project_id,
            question=question,
            rationale="it matters",
        )
    )
    for command in commands:
        topic.execute(command)
    await topics.save(topic)
    return topic


async def store_source(corpus, project_id, source_id, text="body"):
    aggregate = await corpus.load_or_create(project_id)
    aggregate.execute(
        StoreSourceDocument(corpus_id=project_id, source_id=source_id, text=text)
    )
    await corpus.save(aggregate)


# ---------------- the table follows the fold ----------------


async def test_a_topic_reaches_the_table_with_its_question_and_status(running, topics):
    project_id = uuid4()
    topic = await open_topic(topics, project_id, question="what is the threshold?")
    await running.caught_up()

    row = await running.get(topic.aggregate_id)

    assert row is not None
    assert row.question == "what is the threshold?"
    assert row.status == "open"
    assert row.project_id == project_id


async def test_the_row_matches_the_aggregate_fold(running, topics):
    """The property a rebuild depends on: the table says what the fold says.

    Built by driving the aggregate, so the events the projection sees are the
    ones `decide` actually produced -- not hand-written ones that might differ.
    """
    project_id = uuid4()
    topic = await open_topic(
        topics,
        project_id,
        AddSubQuestion(key="a", question="sub?"),
        LinkSource(source_id="s1"),
        RecordInvestigation(at_position="000000000003"),
        RecordFinding(summary="learned"),
    )
    await running.caught_up()

    row = await running.get(topic.aggregate_id)
    folded = topic.state

    assert row.to_state().model_dump() == folded.model_dump()


async def test_the_queue_agrees_with_a_queue_computed_from_the_fold(running, topics, corpus):
    """The table is an optimisation, not a second opinion."""
    project_id = uuid4()
    await store_source(corpus, project_id, "s1")
    topic = await open_topic(topics, project_id, LinkSource(source_id="s1"))
    await running.caught_up()

    from_table = await running.queue.evaluate(project_id)

    facts = await running.queue._store.corpus_facts(project_id)
    from_fold = attention_for(topic.state, facts)

    assert [a.topic_id for a in from_table] == [topic.aggregate_id]
    assert from_table[0].triggers == from_fold.triggers


# ---------------- attention is computed, not stored ----------------


async def test_dropping_a_source_moves_the_queue_without_touching_a_topic(
    running, topics, corpus
):
    """The test that fails the moment someone caches a needs-attention flag.

    Nothing here appends a single topic event. The corpus changes underneath,
    and the queue has to notice -- which it can only do if the judgement is
    computed on read.
    """
    project_id = uuid4()
    await store_source(corpus, project_id, "s1")
    await store_source(corpus, project_id, "s2")
    topic = await open_topic(
        topics,
        project_id,
        LinkSource(source_id="s1"),
        LinkSource(source_id="s2"),
        RecordInvestigation(at_position="000000000099"),
        RecordFinding(summary="answered from both"),
    )
    await running.caught_up()

    assert await running.queue.evaluate(project_id) == []

    aggregate = await corpus.load_or_create(project_id)
    aggregate.execute(DropSourceDocument(source_id="s1", reason="retracted by the publisher"))
    await corpus.save(aggregate)
    await running.caught_up()

    [attention] = await running.queue.evaluate(project_id)
    assert attention.topic_id == topic.aggregate_id
    assert "topic.source_dropped" in attention.triggers


async def test_new_material_raises_a_topic_that_has_not_seen_it(running, topics, corpus):
    project_id = uuid4()
    await store_source(corpus, project_id, "s1")
    await store_source(corpus, project_id, "s0")
    # Two sources so coverage is satisfied and the topic can actually go quiet;
    # this test is about `new_material`, and a standing coverage finding would
    # mask the transition it is checking.
    topic = await open_topic(
        topics, project_id, LinkSource(source_id="s1"), LinkSource(source_id="s0")
    )
    await running.caught_up()

    # Look at it now, so the topic's cursor sits at the current corpus.
    aggregate = await topics.load(topic.aggregate_id)
    aggregate.execute(
        RecordInvestigation(at_position=await running.queue.high_water(project_id))
    )
    aggregate.execute(RecordFinding(summary="covered"))
    await topics.save(aggregate)
    await running.caught_up()
    assert await running.queue.evaluate(project_id) == []

    await store_source(corpus, project_id, "s2")
    await running.caught_up()

    [attention] = await running.queue.evaluate(project_id)
    assert "topic.new_material" in attention.triggers
    assert "s2" in attention.evidence


# ---------------- ordering and scoping ----------------


async def test_blocking_topics_come_before_advisory_ones(running, topics, corpus):
    project_id = uuid4()
    await store_source(corpus, project_id, "s1")
    await store_source(corpus, project_id, "s2")

    # Settled except for thin coverage -- advisory only.
    advisory = await open_topic(topics, project_id, LinkSource(source_id="s1"))
    aggregate = await topics.load(advisory.aggregate_id)
    aggregate.execute(
        RecordInvestigation(at_position=await running.queue.high_water(project_id))
    )
    aggregate.execute(RecordFinding(summary="mostly answered"))
    await topics.save(aggregate)

    # Never investigated -- blocking.
    blocking = await open_topic(topics, project_id, question="untouched?")
    await running.caught_up()

    queue = await running.queue.evaluate(project_id)

    assert next(a.topic_id for a in queue) == blocking.aggregate_id
    assert queue[0].is_blocked
    assert advisory.aggregate_id in [a.topic_id for a in queue]


async def test_the_queue_is_scoped_to_one_project(running, topics):
    mine, theirs = uuid4(), uuid4()
    await open_topic(topics, mine, question="mine?")
    await open_topic(topics, theirs, question="theirs?")
    await running.caught_up()

    queue = await running.queue.evaluate(mine)

    assert len(queue) == 1


async def test_a_closed_topic_leaves_the_queue(running, topics):
    project_id = uuid4()
    topic = await open_topic(topics, project_id)
    await running.caught_up()
    assert await running.queue.evaluate(project_id)

    aggregate = await topics.load(topic.aggregate_id)
    aggregate.execute(SetTopicStatus(to_status="not_pursuing", justification="out of scope"))
    await topics.save(aggregate)
    await running.caught_up()

    assert await running.queue.evaluate(project_id) == []


async def test_next_topic_is_none_when_the_queue_empties(running, topics):
    project_id = uuid4()

    assert await running.queue.next_topic(project_id) is None


# ---------------- rebuild ----------------


async def test_a_rebuild_reproduces_the_queue_from_the_log(running, topics, corpus):
    """Both tables go together: a fresh topic table against a stale corpus
    snapshot would be a queue that is confidently wrong."""
    project_id = uuid4()
    await store_source(corpus, project_id, "s1")
    await open_topic(topics, project_id, LinkSource(source_id="s1"))
    await running.caught_up()
    before = [(a.topic_id, a.triggers) for a in await running.queue.evaluate(project_id)]

    await running.rebuild()

    after = [(a.topic_id, a.triggers) for a in await running.queue.evaluate(project_id)]
    assert after == before
    assert before, "the fixture should have produced a queue to compare"


async def test_the_runner_reports_no_failures_on_a_clean_log(running, topics):
    await open_topic(topics, uuid4())
    await running.caught_up()

    assert await running.failures() == []


# ---------------- gaps reach the queue ----------------


async def test_a_topic_with_recorded_gaps_still_appears_in_the_queue(running, topics):
    """The case the final review found missing: every existing test of thrash
    reporting built a bare `TopicState` by hand, so the projector never had a
    `TopicGapRecorded` handler and `gaps` was silently always `0` in
    production. This test goes through the real table `TopicQueue.evaluate`
    reads, which is the only path that would have caught it.

    Two looks with nothing recorded is `DEFAULT_THRASH_LOOKS`, so the topic is
    still in the queue for the reason `test_thrash_still_fires...` in
    `test_topic_attention.py` covers -- the gap is additional evidence on the
    same finding, not a separate reason to appear."""
    project_id = uuid4()
    topic = await open_topic(
        topics,
        project_id,
        RecordInvestigation(at_position="p1"),
        RecordGap(looking_for="pricing history", tried=["site search"]),
        RecordInvestigation(at_position="p2"),
    )
    await running.caught_up()

    row = await running.get(topic.aggregate_id)
    assert row.gaps == 1

    [attention] = await running.queue.evaluate(project_id)
    [finding] = [f for f in attention.findings if f.check == "topic.rework_thrash"]
    assert "1" in finding.message
    assert "gap" in finding.message.lower()


async def test_a_topics_database_written_before_gaps_existed_gains_the_column(db_path):
    """`gaps` postdates the table. A database opened before this change has a
    `topics` row with no such column, and `TopicStore.open` used to create the
    table with a bare `executescript` -- `CREATE TABLE IF NOT EXISTS`, which
    does nothing to a table that already exists. That left the column missing
    and every read of it silently defaulting to `0` forever, on top of the
    trigger already not firing at all (finding 1). `TopicStore.open` now goes
    through `apply_schema`, which is what this test pins.

    Simulated by dropping the column back off, matching
    `test_a_database_written_before_a_field_existed_gains_its_column` in
    `test_summary_store.py`.
    """
    import aiosqlite

    store = await TopicStore.open(db_path)
    await store._connection.close()

    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(f"ALTER TABLE {TopicRow.table_name()} DROP COLUMN gaps")
        await connection.commit()

    reopened = await TopicStore.open(db_path)
    try:
        columns = await reopened._connection.execute(
            f"PRAGMA table_info({TopicRow.table_name()})"
        )
        assert "gaps" in {row[1] for row in await columns.fetchall()}
        # And it still answers, which is the failure a schema check alone misses.
        assert await reopened.list(uuid4()) == []
    finally:
        await reopened._connection.close()
