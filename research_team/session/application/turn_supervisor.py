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
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from research_team.platform.shared.ports import ActivityReporter, TurnActivityBuffer
from research_team.session.application.session_service import SessionService, TurnOutcome

logger = logging.getLogger(__name__)


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


class TurnTimeout(Exception):
    """The in-flight turn timed out before finishing."""

    def __init__(self, session_id: UUID, timeout_seconds: float) -> None:
        super().__init__(
            f"the turn on session {session_id} timed out after {timeout_seconds}s"
        )
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds


class TurnLifecycleHook(Protocol):
    """Hooks for observing turn lifecycle events."""

    def on_turn_started(self, session_id: UUID, turn_index: int, user_input: str) -> None: ...
    def on_turn_completed(
        self, session_id: UUID, turn_index: int, outcome: TurnOutcome
    ) -> None: ...
    def on_turn_failed(
        self, session_id: UUID, turn_index: int, error: BaseException
    ) -> None: ...
    def on_turn_cancelled(self, session_id: UUID, turn_index: int) -> None: ...


CANCEL_SETTLE_TIMEOUT = 10.0
"""How long `cancel` waits for a turn to unwind before answering anyway."""


@dataclass(frozen=True)
class RunningTurn:
    """What is currently in flight on a session."""

    session_id: UUID
    turn_index: int
    """The number this turn will take if it completes."""
    started_at: datetime
    user_input_preview: str = ""

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
        activity: TurnActivityBuffer | None = None,
        settle_timeout: float = CANCEL_SETTLE_TIMEOUT,
        default_turn_timeout: float | None = None,
        hooks: Sequence[TurnLifecycleHook] | None = None,
    ) -> None:
        self._service = service
        self._activity = activity
        self._settle_timeout = settle_timeout
        self._default_turn_timeout = default_turn_timeout
        self._hooks: list[TurnLifecycleHook] = list(hooks) if hooks else []
        self._running: dict[UUID, asyncio.Task[TurnOutcome]] = {}
        self._started: dict[UUID, RunningTurn] = {}

    def add_hook(self, hook: TurnLifecycleHook) -> None:
        """Register a turn lifecycle hook."""
        self._hooks.append(hook)

    def _notify_started(self, session_id: UUID, turn_index: int, user_input: str) -> None:
        for hook in self._hooks:
            try:
                hook.on_turn_started(session_id, turn_index, user_input)
            except Exception:
                logger.exception("hook on_turn_started failed")

    def _notify_completed(
        self, session_id: UUID, turn_index: int, outcome: TurnOutcome
    ) -> None:
        for hook in self._hooks:
            try:
                hook.on_turn_completed(session_id, turn_index, outcome)
            except Exception:
                logger.exception("hook on_turn_completed failed")

    def _notify_failed(self, session_id: UUID, turn_index: int, error: BaseException) -> None:
        for hook in self._hooks:
            try:
                hook.on_turn_failed(session_id, turn_index, error)
            except Exception:
                logger.exception("hook on_turn_failed failed")

    def _notify_cancelled(self, session_id: UUID, turn_index: int) -> None:
        for hook in self._hooks:
            try:
                hook.on_turn_cancelled(session_id, turn_index)
            except Exception:
                logger.exception("hook on_turn_cancelled failed")

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

    def diagnostics(self) -> dict[str, Any]:
        """Diagnostic summary of active supervisor state and hooks."""
        now = datetime.now(UTC)
        running = self.running_sessions()
        return {
            "active_turns_count": len(running),
            "settle_timeout": self._settle_timeout,
            "default_turn_timeout": self._default_turn_timeout,
            "hooks_count": len(self._hooks),
            "running": [
                {
                    "session_id": str(t.session_id),
                    "turn_index": t.turn_index,
                    "started_at": t.started_at.isoformat(),
                    "elapsed_seconds": t.elapsed_seconds(now),
                    "user_input_preview": t.user_input_preview,
                }
                for t in running.values()
            ],
        }

    async def run(
        self,
        session_id: UUID,
        user_input: str,
        *,
        timeout: float | None = None,
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
        turn_index = session.state.turn_index + 1
        reporter: ActivityReporter | None = None
        if self._activity is not None:
            self._activity.begin(session_id)
            reporter = self._activity.reporter(session_id)
        task = asyncio.ensure_future(self._service.run_turn(session_id, user_input, reporter))
        if self._activity is not None:
            task.add_done_callback(self._settle(session_id))
        self._running[session_id] = task
        preview = user_input[:100] + "…" if len(user_input) > 100 else user_input
        self._started[session_id] = RunningTurn(
            session_id=session_id,
            turn_index=turn_index,
            started_at=datetime.now(UTC),
            user_input_preview=preview,
        )
        self._notify_started(session_id, turn_index, user_input)
        effective_timeout = timeout if timeout is not None else self._default_turn_timeout

        try:
            if effective_timeout is not None:
                try:
                    outcome = await asyncio.wait_for(
                        asyncio.shield(task), timeout=effective_timeout
                    )
                except TimeoutError:
                    task.cancel()
                    with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
                        await asyncio.wait_for(
                            asyncio.shield(task), timeout=self._settle_timeout
                        )
                    self._notify_cancelled(session_id, turn_index)
                    raise TurnTimeout(session_id, effective_timeout) from None
            else:
                outcome = await asyncio.shield(task)

            self._notify_completed(session_id, turn_index, outcome)
            return outcome
        except asyncio.CancelledError:
            if task.cancelled():
                self._notify_cancelled(session_id, turn_index)
                raise TurnCancelled(session_id) from None
            raise
        except (TurnCancelled, TurnTimeout):
            raise
        except BaseException as error:
            self._notify_failed(session_id, turn_index, error)
            raise
        finally:
            if self._running.get(session_id) is task and task.done():
                del self._running[session_id]
                self._started.pop(session_id, None)

    def _settle(self, session_id: UUID) -> Callable[[asyncio.Task[TurnOutcome]], None]:
        """A done-callback that closes the buffer from the turn's own fate.

        `cancelled()` is checked before `exception()` because asking a
        cancelled task for its exception raises rather than answers.
        """

        def settled(task: asyncio.Task[TurnOutcome]) -> None:
            if self._activity is None:  # pragma: no cover -- only registered when set
                return
            committed = not task.cancelled() and task.exception() is None
            self._activity.settle(session_id, committed=committed)

        return settled

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
