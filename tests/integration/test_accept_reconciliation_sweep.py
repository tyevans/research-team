"""The *periodic* half of accept reconciliation -- `BACKLOG.md` B99, closed
by the change these tests cover, so the entry is gone and the reasoning lives
in `docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md`.

`test_accept_reconciliation.py` covers the startup pass, which fixes a process
that died and came back. This file covers the case that pass cannot reach: a
process that never dies, where an accept's `asyncio.create_task` raised, hung,
or was dropped, and the proposal stays `accepted` for as long as the process
stays up because nothing after startup looks at it again.

Every test here would pass trivially against a build with no sweep at all if
it asserted only that `start()` returned or that nothing threw -- a sweep that
never runs and one that finds nothing to do render identically, which is the
same trap the startup pass's spec names. So each assertion is on an observed
effect: the reconciler's read actually happening again, or a stranded proposal
actually reaching `stored`.

**Driven by a very short interval, not by real seconds.** The interval comes
from the environment through `config.media_reconcile_interval_seconds()`, and
the loop's sleep is a full-jitter draw from `[0, interval]`, so a 20ms setting
makes several sweeps happen inside a poll budget of a fifth of a second. The
polls have a bounded budget and fail loudly rather than hanging.

The seeding helpers are imported from `test_accept_reconciliation` rather than
copied: they are ~100 lines of fixture (a mock transport, a fake vision port,
and an append-then-close "crash") whose second copy would drift.
"""

import asyncio
from uuid import uuid4

import pytest

from tests.integration.test_accept_reconciliation import _build, _crash_after_accepting

pytestmark = pytest.mark.asyncio

SWEEP_INTERVAL = "0.02"
"""Upper bound of each jittered sleep, in seconds. Small enough that a handful
of sweeps fit in a poll budget a person would not notice, large enough that
the loop is not a busy-wait pinning a core for the length of the test."""

POLL_BUDGET = 400
"""Iterations of a 5ms poll -- two seconds. Generous on purpose: this is the
timeout, not the expected duration, and a tight one is how a test that passes
here becomes a test that fails on a loaded CI box."""


async def _poll(predicate) -> bool:
    for _ in range(POLL_BUDGET):
        if await predicate():
            return True
        await asyncio.sleep(0.005)
    return False


def _build_sweeping(db_path, monkeypatch):
    """A composed application whose sweep interval is milliseconds.

    Through the environment rather than by setting the field afterwards:
    `Application` is `frozen=True`, and going through `AGENT_MEDIA_RECONCILE_
    INTERVAL` means this also fails if `build_application` stops reading the
    setting -- a wiring gap that is otherwise invisible, since the default
    interval makes an unwired build look merely slow.
    """
    monkeypatch.setenv("AGENT_MEDIA_RECONCILE_INTERVAL", SWEEP_INTERVAL)
    return _build(db_path)


async def test_the_sweep_reconciles_again_after_startup(db_path, monkeypatch):
    """Reconciliation happens more than once over the life of one process.

    Fails against the build before B99: with only the startup pass, the worker
    is called exactly once and this hangs out its poll budget at one call.

    The worker is stubbed to record and do nothing, so the proposal never
    leaves `accepted` and every sweep finds it again -- which is what makes
    "ran repeatedly" observable at all. Asserting on the recorded proposal id
    rather than on a bare count: a loop that woke up and read an empty set
    would also count, and it is the *work* that B99 is about.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=False)

    application = _build_sweeping(db_path, monkeypatch)
    calls: list[str] = []

    async def record(pid: str) -> None:
        calls.append(pid)

    application.media_accept_worker.run = record
    try:
        await application.start()
        assert await _poll(lambda: _at_least(calls, 3)), (
            f"the sweep did not reconcile repeatedly: {len(calls)} call(s) in the budget"
        )
        assert set(calls) == {proposal_id}
    finally:
        await application.close()


async def _at_least(calls: list[str], n: int) -> bool:
    return len(calls) >= n


async def test_a_sweep_that_raises_does_not_stop_the_ones_after_it(db_path, monkeypatch):
    """The timer outlives a failed sweep, and the sweep after it does work.

    Proved red against the mutation it exists to catch: with the loop's
    `except Exception` removed, this fails -- the raise ends the task and
    `calls` never reaches 2. Reconciliation would be dead for the life of the
    process, silently, which is precisely the shape of the defect B99 is
    about.

    The raise is aimed at the *second* read, which is the first sweep's --
    read one is the startup pass, and a version of this test that failed
    there proved nothing, because the startup task dying is not the loop
    dying. It passed with the guard removed, which is how the aim was found.

    The worker is stubbed to record and do nothing so the proposal stays
    `accepted` and remains findable by every later sweep; the assertion is
    that it was reached again *after* the failing read, not merely that
    reads kept happening.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=False)

    application = _build_sweeping(db_path, monkeypatch)
    real_reads = application.media_proposals.accepted_proposal_ids
    reads = 0
    calls: list[str] = []

    async def failing_on_the_first_sweep() -> list[str]:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("projection briefly unreadable")
        return await real_reads()

    async def record(pid: str) -> None:
        calls.append(pid)

    application.media_proposals.accepted_proposal_ids = failing_on_the_first_sweep
    application.media_accept_worker.run = record
    try:
        await application.start()
        assert await _poll(lambda: _at_least(calls, 2)), (
            f"no sweep after the failing one reached the worker (reads={reads}, "
            f"calls={len(calls)}); the timer died with it"
        )
        assert reads > 2, "the failing read never happened; the test proved nothing"
        assert set(calls) == {proposal_id}
    finally:
        await application.close()


async def test_the_sweep_stops_when_the_application_closes(db_path, monkeypatch):
    """A sweep that outlived `close()` would read through a stopped projection
    and a closed store for the life of the event loop.

    Two assertions, and the second is the one with teeth: the task object is
    cancelled, *and* no further reconciliation happens over a window several
    intervals wide. The first alone would pass against a loop that caught
    `CancelledError` and carried on, because the task is marked cancelled
    either way at the moment `cancel()` is called.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=False)

    application = _build_sweeping(db_path, monkeypatch)
    calls: list[str] = []

    async def record(pid: str) -> None:
        calls.append(pid)

    application.media_accept_worker.run = record
    await application.start()
    assert await _poll(lambda: _at_least(calls, 2)), "the sweep never ran; nothing to stop"
    (task,) = application._sweep

    await application.close()

    assert task.cancelled() or task.done()
    assert application._sweep == []
    settled = len(calls)
    # Twenty intervals' worth. A sweep still alive would land several times.
    await asyncio.sleep(0.4)
    assert len(calls) == settled, "reconciliation kept running after close()"


async def test_the_default_interval_is_used_when_the_environment_says_nothing(
    db_path, monkeypatch
):
    """The wiring, asserted where it is cheap.

    Would pass with `build_application`'s `media_reconcile_interval=` argument
    deleted -- the field's default is the same constant -- so this is a check
    on the constant reaching the object, not on the argument existing. The
    argument's presence is what
    `test_the_sweep_reconciles_again_after_startup` proves, by setting the
    environment variable and observing the faster loop.
    """
    from research_team.infrastructure import config

    monkeypatch.delenv("AGENT_MEDIA_RECONCILE_INTERVAL", raising=False)
    application = _build(db_path)
    try:
        assert application.media_reconcile_interval == (
            config.DEFAULT_MEDIA_RECONCILE_INTERVAL_SECONDS
        )
    finally:
        await application.close()
