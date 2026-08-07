"""Retrying a write that lost a compare-and-swap.

The contract has three parts and each has a test: the attempt is re-run from
the top (so it reloads and re-decides rather than replaying a stale decision),
the retrying is bounded, and anything that is not a lock error is not this
module's business and passes straight through.
"""

import asyncio

import pytest
from eventsource import OptimisticLockError
from hypothesis import given
from hypothesis import strategies as st

from research_team.infrastructure.persistence.retry import MAX_ATTEMPTS, with_retry


def _lock_error() -> OptimisticLockError:
    return OptimisticLockError("aggregate", 1, 2)


async def test_a_write_that_lands_first_time_is_not_retried():
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        return "landed"

    assert await with_retry(attempt, what="test") == "landed"
    assert calls == 1


async def test_a_write_that_loses_once_is_run_again():
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _lock_error()
        return "landed on the second go"

    assert await with_retry(attempt, what="test") == "landed on the second go"
    assert calls == 2


async def test_the_retrying_is_bounded_and_the_last_error_propagates():
    """An unbounded retry against a conflict that will not clear is a hang.

    The original error is what escapes, not a wrapper: a caller that handles
    `OptimisticLockError` must not have that handling depend on whether
    something retried first.
    """
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        raise _lock_error()

    with pytest.raises(OptimisticLockError):
        await with_retry(attempt, what="test")
    assert calls == MAX_ATTEMPTS


async def test_any_other_failure_is_not_retried():
    """Only a lost compare-and-swap is retryable. Re-running a write that
    failed because it was wrong just makes it wrong repeatedly."""
    calls = 0

    async def attempt():
        nonlocal calls
        calls += 1
        raise ValueError("this write was malformed")

    with pytest.raises(ValueError):
        await with_retry(attempt, what="test")
    assert calls == 1


@given(writers=st.integers(min_value=2, max_value=MAX_ATTEMPTS))
async def test_every_concurrent_writer_eventually_lands(writers):
    """The property the bug was a violation of: with `n` writers contending for
    one aggregate, all `n` writes land and none raises.

    Models the store's compare-and-swap directly rather than through SQLite, so
    the interleaving is exercised rather than hoped for. `MAX_ATTEMPTS` is the
    upper bound on writers precisely because the unluckiest of `n` writers is
    displaced up to `n - 1` times -- this pins that the bound and the fan-out
    it must cover are the same number.
    """
    version = 0
    landed = []

    async def write(name):
        async def attempt():
            nonlocal version
            # Read the version, yield to every other writer, then try to
            # commit against what we read -- which is exactly the window the
            # real repository has between `load` and `save`.
            seen = version
            await asyncio.sleep(0)
            if seen != version:
                raise _lock_error()
            version += 1
            landed.append(name)

        await with_retry(attempt, what=f"writer {name}")

    await asyncio.gather(*(write(i) for i in range(writers)))

    assert sorted(landed) == list(range(writers))
    assert version == writers
