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
from contextlib import suppress
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


class TurnSupervisor:
    """Owns the in-flight turn for each session."""

    def __init__(self, service: SessionService) -> None:
        self._service = service
        self._running: dict[UUID, asyncio.Task[TurnOutcome]] = {}

    def is_running(self, session_id: UUID) -> bool:
        task = self._running.get(session_id)
        return task is not None and not task.done()

    def running_sessions(self) -> list[UUID]:
        return [session_id for session_id in self._running if self.is_running(session_id)]

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

        task = asyncio.ensure_future(
            self._service.run_turn(session_id, user_input, on_activity)
        )
        self._running[session_id] = task
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

    async def cancel(self, session_id: UUID) -> bool:
        """Stop the in-flight turn. Returns False if there was nothing to stop.

        Waits for the turn to actually unwind before returning, so that by the
        time a caller hears "cancelled" the log already records the attempt as
        a failed turn and no events from it survive.
        """
        task = self._running.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
        self._running.pop(session_id, None)
        return True

    async def cancel_all(self) -> None:
        """Stop every in-flight turn. For shutting down without stranding work."""
        for session_id in list(self._running):
            await self.cancel(session_id)
