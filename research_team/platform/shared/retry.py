"""Retrying a write that lost a compare-and-swap to a concurrent one.

The model puts several tool calls in one assistant message, and the executor
runs them concurrently. Two of them writing the same aggregate is therefore an
ordinary event, not an exotic one: two `remember` calls share a project's
corpus, and two `record_finding` calls share a topic. Both load at the same
version, and the second `save` loses.

**Why a retry and not a lock.** An `asyncio.Lock` would serialise the writers
inside one process and do nothing about the REPL, a second uvicorn worker, or
a script -- all of which write the same SQLite file. The compare-and-swap is
the real concurrency control and it is doing its job; what was missing is that
nobody answered it. Retrying is also what the loser *should* do, because the
log is append-only: the winner's events are durable, the loser's were discarded
whole, and re-deciding against the winner's state is exactly the semantics an
event-sourced write wants.

**Why the whole operation re-runs, and what that requires of it.** `attempt` is
re-invoked from scratch, so it must reload the aggregate and re-derive its
decision. That is the point rather than an inconvenience: a retry that replayed
a decision made against stale state would reintroduce the lost update the lock
error just prevented. The corollary is the one rule for callers -- `attempt`
has to be safe to run more than once, which for both current callers it is,
because each re-reads the state its own precondition is checked against.

Bounded, and the bound is small. Contention here comes from the handful of tool
calls in one assistant message, so a write that cannot land in a few tries is
not contended, it is wrong -- and an unbounded retry against a genuine conflict
is a hang rather than an error. The last failure propagates unchanged, so
whatever the caller would have seen without this, it still sees.
"""

import logging
from collections.abc import Awaitable, Callable

from eventsource import OptimisticLockError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6
"""Enough for every tool call in one assistant message to take its turn.

Six rather than three because the writers are serialised by the retry itself:
with `n` callers contending, the unluckiest is displaced up to `n - 1` times,
so the bound has to cover a plausible fan-out rather than a plausible number of
*collisions*. Six covers the widest parallel tool batch we have seen and still
fails fast against a conflict that is not going to clear.
"""


async def with_retry[T](
    attempt: Callable[[], Awaitable[T]],
    *,
    what: str,
    max_attempts: int = MAX_ATTEMPTS,
) -> T:
    """Run `attempt`, re-running it if it loses a concurrent write.

    `attempt` must reload whatever it writes: it is called again from the top,
    and its job on the second call is to decide afresh against the state the
    winner left behind.

    `what` names the operation in the log line, so a run that is quietly
    retrying is visible without being noisy -- this is `debug`, because losing
    a compare-and-swap is expected here rather than remarkable.
    """
    for remaining in range(max_attempts - 1, -1, -1):
        try:
            return await attempt()
        except OptimisticLockError:
            if remaining == 0:
                # Out of tries. The original error propagates rather than
                # something wrapped: the caller's handling of a lock error, if
                # it has any, should not depend on whether we retried first.
                raise
            logger.debug("%s lost a concurrent write; retrying (%d left)", what, remaining)
    raise AssertionError("unreachable: the loop either returns or raises")
