"""Running turns as cancellable work, one at a time per session.

A turn against a local model can take a minute. Two things follow that the
service itself should not have to know about: someone may want to stop one
partway, and a second turn on the same session should be refused *before* it
spends a minute in the model rather than after, when the append would lose a
version check anyway.

Both are about the lifecycle of an in-flight turn rather than about what a turn
means, so they live here, beside the use cases and above the transport.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from research_team.application.ports import ActivityReporter
from research_team.application.session_service import SessionService, TurnOutcome


class TurnAlreadyRunning(Exception):
    """A turn is already in flight on this session."""

    def __init__(self, session_id: UUID) -> None:
        super().__init__(f"a turn is already running on session {session_id}")
        self.session_id = session_id


class TurnCancelled(Exception):
    """The in-flight turn was cancelled by someone else.

    A distinct type because the caller waiting on the turn needs to tell "you
    stopped this" apart from "this crashed" -- one is an outcome the user asked
    for, the other is a failure.
    """

    def __init__(self, session_id: UUID) -> None:
        super().__init__(f"the turn on session {session_id} was cancelled")
        self.session_id = session_id


CANCEL_SETTLE_TIMEOUT = 10.0
"""How long `cancel` waits for a turn to unwind before answering anyway."""


@dataclass(frozen=True)
class RunningTurn:
    """What is currently in flight on a session."""

    session_id: UUID
    turn_index: int
    """The number this turn will take if it completes."""
    started_at: datetime

    def elapsed_seconds(self, now: datetime) -> float:
        return (now - self.started_at).total_seconds()


@dataclass(frozen=True)
class Cancellation:
    """The result of asking for a turn to stop."""

    cancelled: bool
    """False when there was nothing to stop."""
    settled: bool
    """True when the turn finished unwinding before we answered.

    False means the cancel was delivered but the turn was still winding down --
    so the caller should not yet treat the log as final. It will be shortly.
    """


class TurnSupervisor:
    """Owns the in-flight turn for each session."""

    def __init__(
        self,
        service: SessionService,
        *,
        settle_timeout: float = CANCEL_SETTLE_TIMEOUT,
    ) -> None:
        self._service = service
        self._settle_timeout = settle_timeout
        self._running: dict[UUID, asyncio.Task[TurnOutcome]] = {}
        self._started: dict[UUID, RunningTurn] = {}

    def is_running(self, session_id: UUID) -> bool:
        task = self._running.get(session_id)
        return task is not None and not task.done()

    def running(self, session_id: UUID) -> RunningTurn | None:
        """Details of the in-flight turn, for a caller that arrived mid-turn."""
        return self._started.get(session_id) if self.is_running(session_id) else None

    def running_sessions(self) -> dict[UUID, RunningTurn]:
        """Every session mid-turn right now.

        For a caller with no session to ask about -- the cross-project roster,
        which would otherwise have to enumerate projects and fold each one just
        to learn which sessions to ask after. Filtered by `is_running` for the
        same reason `running` is: `_started` outlives the task by however long
        it takes the done-callback to fire.
        """
        return {
            session_id: turn
            for session_id, turn in self._started.items()
            if self.is_running(session_id)
        }

    async def run(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        """Run one turn, refusing to start a second on the same session.

        The turn runs as its own task so that cancelling it cancels the turn
        rather than whoever happens to be awaiting it -- an HTTP client that
        disconnects mid-turn must not silently abandon work the log will still
        record.
        """
        if self.is_running(session_id):
            raise TurnAlreadyRunning(session_id)

        session = await self._service.load(session_id)
        task = asyncio.ensure_future(
            self._service.run_turn(session_id, user_input, on_activity)
        )
        self._running[session_id] = task
        self._started[session_id] = RunningTurn(
            session_id=session_id,
            turn_index=session.state.turn_index + 1,
            started_at=datetime.now(UTC),
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                # Someone called cancel() on the turn itself.
                raise TurnCancelled(session_id) from None
            # We were cancelled, not the turn -- the caller went away. Let the
            # turn finish: it is atomic, and half a minute of model time is not
            # worth throwing away because a browser tab closed.
            raise
        finally:
            if self._running.get(session_id) is task and task.done():
                del self._running[session_id]
                self._started.pop(session_id, None)

    async def cancel(self, session_id: UUID) -> Cancellation:
        """Stop the in-flight turn.

        Waits for the turn to unwind, so that by the time a caller hears
        "cancelled" the log already records the attempt and no events from it
        survive. That wait is bounded: unwinding runs through the model client,
        which can be slow, and a cancel request that hangs behind it is worse
        than one that answers honestly that the turn is still settling.
        """
        task = self._running.get(session_id)
        if task is None or task.done():
            return Cancellation(cancelled=False, settled=True)

        task.cancel()
        settled = True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._settle_timeout)
        except TimeoutError:
            settled = False
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- how it ended
            pass  # is the awaiter's business

        if settled:
            self._running.pop(session_id, None)
            self._started.pop(session_id, None)
        return Cancellation(cancelled=True, settled=settled)

    async def cancel_all(self) -> None:
        """Stop every in-flight turn. For shutting down without stranding work."""
        for session_id in list(self._running):
            await self.cancel(session_id)
