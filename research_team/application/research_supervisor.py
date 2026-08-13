"""Owning an autonomous run while it is in flight.

`ResearchRunDriver.run` is a coroutine that takes as long as the work takes --
which is right for the REPL, where somebody is watching it, and useless over
HTTP, where the request has to return long before round two. This is the piece
that bridges those: it starts a run as a task, hands back its id immediately,
and answers "how is it going" and "stop" from that moment on.

Shaped after `TurnSupervisor`, which solves the same problem one level down,
and for the same reasons: one run per project at a time, refused up front
rather than discovered when two runs start handing each other the same topic;
and cancellation that a caller can ask for without holding the task.

**Nothing here is state the log does not already have.** The task handle and
the cancel flag are process-local by necessity -- a task cannot be persisted --
but every question about what a run *did* is answered by folding its stream, so
a restart loses the ability to cancel a run that is no longer running anyway.
The one thing this deliberately does not do is resume: a process that dies
mid-run leaves a stream with no stop event, and inventing one at startup would
be this module claiming to know why a run it never saw ended.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from research_team.application.research_run import RunReport
from research_team.domain.research_run import Budget, ResearchRunState

logger = logging.getLogger(__name__)


class RunAlreadyActive(Exception):
    """A run is already in flight on this project."""

    def __init__(self, project_id: UUID, run_id: UUID) -> None:
        super().__init__(f"run {run_id} is already active on project {project_id}")
        self.project_id = project_id
        self.run_id = run_id


@dataclass(frozen=True)
class ActiveRun:
    """The handle a caller gets back the moment a run starts.

    Carries the session as well as the run because the two are separate
    streams and a caller watching one wants the other: the rounds are turns on
    `session_id`, and everything the agent said while working is there rather
    than on the run.
    """

    run_id: UUID
    project_id: UUID
    session_id: UUID


#: Starts one run. Given the ids, the budget, the fetch pre-authorization (as
#: the domain carries it -- a host list and a count, not a `FetchGrant`; the
#: driver is what turns those into one and registers it) and how to know it
#: has been cancelled, it works the queue and reports. Injected so this
#: module names no driver, no repository and no executor -- the composition
#: root supplies all three.
#:
#: Widened to carry `fetch_hosts`/`fetch_budget` for the pre-authorization
#: feature: a run's grant has to reach the driver the same way its budget
#: does, and this is the one seam every caller already goes through.
StartRun = Callable[
    [UUID, UUID, UUID, Budget | None, list[str], int, Callable[[], bool]],
    Awaitable[RunReport],
]


class ResearchSupervisor:
    """Starts, tracks, and stops autonomous runs. One per project at a time."""

    def __init__(self, start: StartRun, runs) -> None:
        self._start = start
        self._runs = runs
        self._tasks: dict[UUID, asyncio.Task[RunReport]] = {}
        self._active: dict[UUID, ActiveRun] = {}
        self._cancelled: set[UUID] = set()

    def active(self, project_id: UUID) -> ActiveRun | None:
        """The run in flight on this project, or None."""
        task = self._tasks.get(project_id)
        if task is None or task.done():
            return None
        return self._active.get(project_id)

    def active_projects(self) -> tuple[UUID, ...]:
        """Every project with a run going.

        Already keyed by project, so this is the dict's own keys filtered
        through `active` -- the cross-project roster's cheapest candidate
        source, and the reason a build with only a run going never touches the
        session read model.
        """
        return tuple(project_id for project_id in self._tasks if self.active(project_id))

    def start(
        self,
        project_id: UUID,
        session_id: UUID,
        *,
        budget: Budget | None = None,
        fetch_hosts: Sequence[str] = (),
        fetch_budget: int = 0,
        after: Callable[[], Awaitable[None]] | None = None,
    ) -> ActiveRun:
        """Begin a run in the background and name it.

        Synchronous on purpose: everything that could fail slowly happens
        inside the task, so a caller gets an id or an exception without
        waiting on a model. The id is minted here rather than by the driver
        precisely so it can be returned now -- see `ResearchRunDriver.run`'s
        `run_id`.

        `after` is for a caller that made the session this run works in and has
        to put it away again. It belongs to the caller rather than here because
        the two front ends differ on exactly this point: the web route starts a
        session for the run and nothing else will ever release it, while the
        REPL runs in the session the person is already sitting in and must not
        have it released underneath them.

        `fetch_hosts`/`fetch_budget` default to nothing granted, so the REPL
        caller (which never passes them) starts exactly the run it always
        did. They are handed straight through to `_start` -- this class does
        not decide what a grant means, only carries the two numbers a caller
        gave it to whoever does.
        """
        existing = self.active(project_id)
        if existing is not None:
            raise RunAlreadyActive(project_id, existing.run_id)

        handle = ActiveRun(run_id=uuid4(), project_id=project_id, session_id=session_id)
        self._cancelled.discard(handle.run_id)
        task = asyncio.ensure_future(
            self._run(
                handle,
                budget,
                list(fetch_hosts),
                fetch_budget,
                after,
            )
        )
        # Failures reach nobody otherwise: this task is not awaited by whoever
        # started it, so an exception would sit in the task and surface as an
        # "exception was never retrieved" warning at garbage-collection time,
        # long after the context that would explain it is gone.
        task.add_done_callback(lambda finished: self._finished(handle, finished))
        self._tasks[project_id] = task
        self._active[project_id] = handle
        return handle

    async def _run(
        self,
        handle: ActiveRun,
        budget: Budget | None,
        fetch_hosts: list[str],
        fetch_budget: int,
        after: Callable[[], Awaitable[None]] | None,
    ) -> RunReport:
        """The run, and whatever the caller has to do once it is over.

        `after` runs in a `finally` and inside the task rather than in the
        done-callback, because the thing it is for -- releasing the project --
        is itself a write to the log, and a done-callback is not a place from
        which anything may be awaited. A failure there is logged rather than
        raised: the run's own outcome is the answer this returns, and losing it
        to a failed release would report the work as broken when it is only
        untidied.
        """
        try:
            return await self._start(
                handle.run_id,
                handle.project_id,
                handle.session_id,
                budget,
                fetch_hosts,
                fetch_budget,
                lambda: handle.run_id in self._cancelled,
            )
        finally:
            if after is not None:
                try:
                    await after()
                except Exception:
                    logger.exception(
                        "could not put away the session for run %s", handle.run_id
                    )

    def _finished(self, handle: ActiveRun, task: asyncio.Task) -> None:
        self._cancelled.discard(handle.run_id)
        if task.cancelled():
            logger.warning("auto-research run %s was abandoned", handle.run_id)
            return
        error = task.exception()
        if error is not None:
            logger.exception("auto-research run %s failed", handle.run_id, exc_info=error)

    def cancel(self, project_id: UUID) -> ActiveRun | None:
        """Ask this project's run to stop after the round it is in.

        A flag rather than `task.cancel()`, and the difference is the whole
        point: cancelling the task would abandon the run mid-round, leaving its
        stream with no stop event and its turn half-recorded. The flag is read
        between rounds, so the run ends the way every other run ends -- with a
        `StopRun` a later reader can see, giving `cancelled` its only producer.

        Returns the run it asked to stop, or None when there was nothing
        running. The run is still in flight when this returns; `active` goes
        None once the round it was in has finished.
        """
        handle = self.active(project_id)
        if handle is None:
            return None
        self._cancelled.add(handle.run_id)
        return handle

    async def state(self, run_id: UUID) -> ResearchRunState | None:
        """Fold one run's stream. None when there is no such run.

        The only status source. A run in flight and a run that ended last week
        are answered the same way, because the answer is the log either way --
        and a status read from `self._tasks` would disagree with it the moment
        a process restarts.
        """
        try:
            return (await self._runs.load(run_id)).state
        except Exception:  # noqa: BLE001 -- an unknown id is a 404, not a crash
            return None

    async def wait(self, project_id: UUID) -> RunReport | None:
        """Wait for this project's run to finish. For tests and for shutdown."""
        task = self._tasks.get(project_id)
        if task is None:
            return None
        return await task

    async def stop_all(self) -> None:
        """Ask every run to stop, and wait for them to unwind.

        Called on shutdown. Runs are asked rather than cancelled for the reason
        `cancel` gives; the wait is what turns "asked" into a stop event
        actually being in the log by the time the store closes underneath it.
        """
        for project_id in list(self._tasks):
            self.cancel(project_id)
        for project_id in list(self._tasks):
            task = self._tasks.get(project_id)
            if task is None or task.done():
                continue
            try:
                await task
            except Exception:  # shutdown reports failures, it does not raise them
                logger.exception("auto-research run on %s failed while stopping", project_id)
