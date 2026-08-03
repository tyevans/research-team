"""One turn at a time per session, and the ability to stop one."""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from research_team.application import (
    RunningTurn,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
)
from research_team.domain import TurnCompleted, TurnFailed, UserMessageSent
from tests.conftest import ToolAwareFakeChatModel


class SlowModel(ToolAwareFakeChatModel):
    """A model that takes long enough to be interrupted on purpose."""

    delay: float = 5.0

    async def _agenerate(self, *args: Any, **kwargs: Any):
        await asyncio.sleep(self.delay)
        return await super()._agenerate(*args, **kwargs)


@pytest.fixture
def slow_model() -> SlowModel:
    return SlowModel(responses=[AIMessage(content="eventually", id="s1")])


@pytest.fixture
def fast_supervisor(build_service, fake_model):
    service = build_service(model=fake_model)
    return TurnSupervisor(service), service


@pytest.fixture
def slow_supervisor(build_service, slow_model):
    service = build_service(model=slow_model)
    return TurnSupervisor(service), service


# ---------------- one at a time ----------------


async def test_a_turn_runs_and_reports_where_it_landed(fast_supervisor):
    supervisor, service = fast_supervisor
    session_id = await service.create_session()

    outcome = await supervisor.run(session_id, "hello")

    assert outcome.reply == "done"
    assert outcome.turn_index == 1
    assert (outcome.from_index, outcome.to_index) == (2, 4)
    assert outcome.event_count == 3


async def test_a_second_turn_is_refused_while_one_is_running(slow_supervisor):
    """Refused up front, rather than after a minute of model time."""
    supervisor, service = slow_supervisor
    session_id = await service.create_session()

    first = asyncio.create_task(supervisor.run(session_id, "slow"))
    await asyncio.sleep(0.3)

    with pytest.raises(TurnAlreadyRunning):
        await supervisor.run(session_id, "second")

    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await first


async def test_turns_on_different_sessions_do_not_block_each_other(slow_supervisor):
    supervisor, service = slow_supervisor
    first_id = await service.create_session()
    second_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(first_id, "slow"))
    await asyncio.sleep(0.3)

    assert supervisor.is_running(first_id)
    assert not supervisor.is_running(second_id)
    # The other session is free to start immediately.
    second = asyncio.create_task(supervisor.run(second_id, "also slow"))
    await asyncio.sleep(0.3)
    assert supervisor.is_running(second_id)

    await supervisor.cancel_all()
    for task in (running, second):
        with pytest.raises(TurnCancelled):
            await task


async def test_a_finished_turn_frees_the_session(fast_supervisor):
    supervisor, service = fast_supervisor
    session_id = await service.create_session()

    await supervisor.run(session_id, "hello")

    assert not supervisor.is_running(session_id)
    assert supervisor.running_sessions() == []


# ---------------- cancelling ----------------


async def test_cancelling_stops_the_turn_and_records_the_attempt(slow_supervisor):
    """The log gains a marker and nothing else: the turn is discarded whole."""
    supervisor, service = slow_supervisor
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await asyncio.sleep(0.3)
    cancellation = await supervisor.cancel(session_id)

    assert cancellation.cancelled is True
    assert cancellation.settled is True
    with pytest.raises(TurnCancelled):
        await running

    types = [type(e) for e in await service.history(session_id)]
    assert TurnFailed in types
    assert UserMessageSent not in types
    assert TurnCompleted not in types


async def test_a_cancelled_turn_does_not_advance_the_turn_index(slow_supervisor):
    supervisor, service = slow_supervisor
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await asyncio.sleep(0.3)
    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await running

    session = await service.load(session_id)
    assert session.state.turn_index == 0
    assert session.state.failed_turns == 1
    assert session.state.messages == []


async def test_the_cancellation_is_named_in_the_log(slow_supervisor):
    supervisor, service = slow_supervisor
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await asyncio.sleep(0.3)
    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await running

    failure = next(
        e for e in await service.history(session_id) if isinstance(e, TurnFailed)
    )
    assert "Cancelled" in failure.error_type


async def test_cancelling_nothing_says_so(fast_supervisor):
    supervisor, service = fast_supervisor
    session_id = await service.create_session()

    assert (await supervisor.cancel(session_id)).cancelled is False


async def test_cancelling_a_finished_turn_says_so(fast_supervisor):
    supervisor, service = fast_supervisor
    session_id = await service.create_session()
    await supervisor.run(session_id, "hello")

    assert (await supervisor.cancel(session_id)).cancelled is False


async def test_the_session_is_usable_again_after_a_cancellation(build_service, slow_model):
    """Cancelling must not wedge the session: the next turn has to work."""
    service = build_service(model=slow_model)
    supervisor = TurnSupervisor(service)
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await asyncio.sleep(0.3)
    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await running

    slow_model.delay = 0.0
    outcome = await supervisor.run(session_id, "quick one")

    assert outcome.reply == "eventually"
    assert outcome.turn_index == 1  # the cancelled attempt never counted


# ---------------- what is running ----------------


async def test_a_running_turn_reports_its_number_and_age(slow_supervisor):
    """So a tab that arrives mid-turn can say more than "something is running"."""
    from datetime import UTC, datetime

    supervisor, service = slow_supervisor
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow"))
    await asyncio.sleep(0.3)

    turn = supervisor.running(session_id)
    assert isinstance(turn, RunningTurn)
    assert turn.turn_index == 1  # the number it will take if it completes
    assert 0 < turn.elapsed_seconds(datetime.now(UTC)) < 30

    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await running


async def test_the_running_turn_number_follows_the_completed_ones(
    build_service, slow_model
):
    service = build_service(model=slow_model)
    supervisor = TurnSupervisor(service)
    session_id = await service.create_session()
    slow_model.delay = 0.0
    await supervisor.run(session_id, "first")

    slow_model.delay = 5.0
    running = asyncio.create_task(supervisor.run(session_id, "second"))
    await asyncio.sleep(0.3)

    assert supervisor.running(session_id).turn_index == 2

    await supervisor.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await running


async def test_nothing_is_reported_running_when_nothing_is(fast_supervisor):
    supervisor, service = fast_supervisor
    session_id = await service.create_session()
    assert supervisor.running(session_id) is None

    await supervisor.run(session_id, "hello")
    assert supervisor.running(session_id) is None


class StubbornModel(ToolAwareFakeChatModel):
    """A client that does not stop promptly when asked.

    Not a contrivance: a model call wedged in a socket read is exactly the
    case where a cancel request must not wait for it.
    """

    async def _agenerate(self, *args: Any, **kwargs: Any):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(30)  # ignores the first cancellation
        return await super()._agenerate(*args, **kwargs)


async def test_a_cancel_that_will_not_settle_says_so_rather_than_hanging(
    build_service,
):
    """A turn wedged in a slow client must not wedge the cancel request too."""
    service = build_service(
        model=StubbornModel(responses=[AIMessage(content="never", id="n1")])
    )
    supervisor = TurnSupervisor(service, settle_timeout=0.1)
    session_id = await service.create_session()

    running = asyncio.create_task(supervisor.run(session_id, "slow"))
    await asyncio.sleep(0.3)

    cancellation = await supervisor.cancel(session_id)

    assert cancellation.cancelled is True
    assert cancellation.settled is False  # honest, rather than a hung request
    running.cancel()
