"""Appending, and the publish that has to accompany it."""

from datetime import UTC, datetime
from uuid import uuid4

from eventsource import InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import BROWSER_SESSION_AGGREGATE_TYPE, ViewEntered
from research_team.infrastructure.interaction.recorder import (
    EventStoreInteractionRecorder,
)


def _event(browser_session, seq):
    return ViewEntered(
        aggregate_id=browser_session,
        install_id=uuid4(),
        seq=seq,
        view="home",
        occurred_at=datetime.now(UTC),
        params={},
    )


async def test_a_batch_lands_in_the_store(tmp_path):
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    bus = InMemoryEventBus()
    recorder = EventStoreInteractionRecorder(store, bus)
    browser_session = uuid4()

    written = await recorder.record([_event(browser_session, 1), _event(browser_session, 2)])

    assert written == 2


async def test_recording_publishes_every_event(tmp_path):
    """Appending is not delivering, and the difference is silent: a running
    projection sees an unpublished append only after a restart.

    Fails with the publish removed -- nothing else does, which is why this
    test exists rather than relying on the store assertion above.
    """
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    bus = InMemoryEventBus()
    published: list = []
    bus.subscribe(ViewEntered, lambda event: published.append(event))
    recorder = EventStoreInteractionRecorder(store, bus)
    browser_session = uuid4()

    await recorder.record([_event(browser_session, 1)])

    assert len(published) == 1


async def test_two_browser_sessions_go_to_two_streams(tmp_path):
    """One append per stream, because append takes one StreamId. A single
    call with events from two sessions would put one session's events in the
    other's stream.

    Asserting only `written == 2` would pass even if both events landed in
    one stream -- the count is the same either way. So this reads each
    session's stream back individually and checks it holds exactly its own
    event, which is the only way to catch a grouping bug (by a constant, or
    by aggregate *type* instead of aggregate *id*) that still writes two
    events total.
    """
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    recorder = EventStoreInteractionRecorder(store, InMemoryEventBus())
    first, second = uuid4(), uuid4()

    written = await recorder.record([_event(first, 1), _event(second, 1)])

    assert written == 2
    first_stream = [
        envelope.event
        async for envelope in store.read_stream(
            StreamId(first, BROWSER_SESSION_AGGREGATE_TYPE)
        )
    ]
    second_stream = [
        envelope.event
        async for envelope in store.read_stream(
            StreamId(second, BROWSER_SESSION_AGGREGATE_TYPE)
        )
    ]
    assert [event.aggregate_id for event in first_stream] == [first]
    assert [event.aggregate_id for event in second_stream] == [second]


async def test_an_empty_batch_writes_nothing_and_does_not_raise(tmp_path):
    """The store raises on an empty batch, and a flush can legitimately carry
    nothing once the client drops malformed events."""
    recorder = EventStoreInteractionRecorder(
        SQLiteEventStore(str(tmp_path / "interactions.db")), InMemoryEventBus()
    )

    assert await recorder.record([]) == 0
