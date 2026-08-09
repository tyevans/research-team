"""A turn is long, and its stream is not private to it.

The turn loads the session, runs a model for as long as the model takes, then
saves at a version it read minutes ago. Anything appending to the same stream
in the meantime makes that save lose its compare-and-swap -- and the turn's
whole result is what gets discarded. Autonomy is the writer that actually did
it in production: the operator flips a switch while the agent is thinking.
"""

import pytest
from eventsource import OptimisticLockError

from research_team.domain import AutonomyChanged, TurnCompleted, UserMessageSent
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from tests.conftest import start_session


@pytest.fixture
async def service(build_service, fake_model):
    return await build_service(model=fake_model)


@pytest.fixture
async def session_id(service):
    return await start_session(service)


@pytest.fixture
def counted_saves(service):
    """How many times the session repository appended.

    Counting saves rather than events, because the thing under test is the
    number of round trips: `n` events in one append is the fix, and `n` events
    is what both the broken and the fixed version produce.
    """
    saves: list[int] = []
    original = service._repository.save

    async def counting(aggregate):
        saves.append(len(aggregate.uncommitted_events))
        return await original(aggregate)

    service._repository.save = counting
    return saves


@pytest.fixture
def change_autonomy_mid_turn(service, monkeypatch):
    """Append an `AutonomyChanged` to the session while its turn is in flight.

    Hooked at the executor's single seam, which is where a turn spends its
    time. The append lands after the turn loaded the aggregate and before it
    saves -- exactly the window the operator's switch lands in, and the one
    that costs the turn its version.
    """
    original = DeepAgentTurnExecutor._invoke

    async def interleaved(self, session, messages, system_prompt, on_activity):
        await service.record_autonomy_change(session.aggregate_id, "write_file", "deny")
        return await original(self, session, messages, system_prompt, on_activity)

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", interleaved)


async def test_a_turn_survives_a_write_landing_while_the_model_runs(
    service, session_id, change_autonomy_mid_turn
):
    """Fails without the retry: the save raises `OptimisticLockError` and the
    turn's events are lost whole.
    """
    outcome = await service.run_turn(session_id, "hello")

    assert outcome.reply == "done"
    events = await service.history(session_id)
    assert AutonomyChanged in [type(event) for event in events]
    assert type(events[-1]) is TurnCompleted


async def test_a_retried_turn_reports_the_span_it_actually_wrote(
    service, session_id, change_autonomy_mid_turn
):
    """The retry renumbers the turn's events onto the winner's version, so the
    span the caller is handed has to be renumbered with them. Reverting the
    renumbering leaves `from_index` pointing at the interloper's event.
    """
    outcome = await service.run_turn(session_id, "hello")

    events = await service.history(session_id)
    assert [event.aggregate_version for event in events] == list(range(1, len(events) + 1))
    assert type(events[outcome.from_index - 1]) is UserMessageSent
    assert type(events[outcome.to_index - 1]) is TurnCompleted


async def test_the_model_runs_once_however_many_times_the_save_is_retried(
    build_service, fake_model, session_id, service, change_autonomy_mid_turn, monkeypatch
):
    """The retry repeats the append, never the turn. Re-running the model would
    double every tool call the turn made -- a retry that charges for two turns
    and may write a file twice is worse than the error it is avoiding.
    """
    passes = 0
    original = DeepAgentTurnExecutor._invoke

    async def counting(self, *args, **kwargs):
        nonlocal passes
        passes += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", counting)
    await service.run_turn(session_id, "hello")

    assert passes == 1


async def test_a_bulk_autonomy_change_is_one_append(service, session_id, counted_saves):
    """`n` levels, one round trip. Recording them one at a time is what made
    the turn's save lose in the first place: each is an append to the same
    stream, arriving as fast as the loop can issue them.
    """
    await service.record_autonomy_changes(session_id, {"write_file": "deny", "fetch": "ask"})

    assert counted_saves == [2]
    changes = [
        (event.tool_name, event.level)
        for event in await service.history(session_id)
        if isinstance(event, AutonomyChanged)
    ]
    assert changes == [("write_file", "deny"), ("fetch", "ask")]


async def test_a_bulk_autonomy_change_of_nothing_appends_nothing(
    service, session_id, counted_saves
):
    """An empty map is a real caller: `relax_all` returns "what moved", and
    nothing moves when everything is already relaxed. Saving there would write
    an empty append and bump nothing.
    """
    await service.record_autonomy_changes(session_id, {})

    assert counted_saves == []


async def test_a_second_turn_is_a_conflict_rather_than_something_to_rebase_over(
    service, session_id, monkeypatch
):
    """The retry must not launder a real conflict into a success.

    Two turns read the same conversation and answer it independently; appending
    both interleaves two replies to one message. Only writes the turn does not
    contradict are rebased over, and a turn is not one of them -- so the loser
    still raises, exactly as it did before the retry existed.
    """
    original = DeepAgentTurnExecutor._invoke

    async def take_a_whole_turn_underneath(self, session, *args, **kwargs):
        result = await original(self, session, *args, **kwargs)
        monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", original)
        await service.run_turn(session.aggregate_id, "the other tab")
        return result

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", take_a_whole_turn_underneath)

    with pytest.raises(OptimisticLockError):
        await service.run_turn(session_id, "hello")

    events = await service.history(session_id)
    assert [type(event) for event in events].count(TurnCompleted) == 1


async def test_a_turn_whose_save_keeps_losing_still_raises(service, session_id):
    """The bound exists so a genuine conflict is an error rather than a hang.

    A writer that displaces the turn on *every* attempt is not contention that
    will clear, and the turn gives up with the same lock error the caller would
    have seen with no retry at all. Fails if the retry is ever made unbounded.
    """
    saving = service._repository.save

    async def steal_the_version(aggregate):
        # Only the turn's own save is displaced: the autonomy write below goes
        # through this same seam, and displacing it too would recurse.
        if any(isinstance(event, TurnCompleted) for event in aggregate.uncommitted_events):
            await service.record_autonomy_change(session_id, "write_file", "deny")
        return await saving(aggregate)

    service._repository.save = steal_the_version

    with pytest.raises(OptimisticLockError):
        await service.run_turn(session_id, "hello")
