"""Where a seeding run has got to, while it is getting there.

`TopicSeeder.seed` runs one `TurnSupervisor` turn -- a model call, a handful
of `open_topic` calls, a reply -- and until it returns says nothing. Short
compared to an extraction or an autonomous run, but not instant: it is still
a model turn, and a browser that posted the seed and then reloaded, or that
never saw the response because the request raced a navigation, has no other
way to find out whether one is running or how the last one went.

Keyed by **project**, matching `ExtractionActivity`: seeding acts on a
project's topic queue, not a session, and the object that runs it
(`TopicSeeder`) is scoped the same way.

**Provisional, and never durable.** Running / done / failed is not a fact the
log records -- the log has `open_topic` calls and nothing that says "a
seeding run started" or "a seeding run finished". These frames carry no feed
position, so `Last-Event-ID` cannot replay them, which is exactly why the
catch-up route exists rather than being an optimisation: an SSE connection
that drops mid-run would otherwise leave a reconnecting browser unable to
tell "still running" from "finished before I got here" from "never started".

**The topics a run opens need no channel here.** `open_topic` already
appends to the log, so a page that invalidates its topic list on those log
frames sees the new topics arrive without this module's help. What this
module answers is narrower and cheaper: is a run in flight, and how did the
last one go.

Shaped like `extraction.py`, which is shaped like `activity.py`, which is
shaped like `approvals.py` -- the same problem each time: content that
matters now, leaves no event behind, and has to survive a reconnect.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from research_team.application import RunAlreadyActive
from research_team.application.topic_seeding import SeedingRun

SEEDING = "Seeding"
"""The frame type on the live feed, PascalCase like `EXTRACTION` beside it.

Not wired to the live feed yet -- nothing in `app.py` pumps it -- because
nothing there needs pushing: the catch-up route below is enough to answer
"what happened" from a cold reconnect, and the topics a run opens already
arrive over the log. The constant exists so a frame this module hands out is
self-describing the moment a channel does want it, the same way `EXTRACTION`
would be if extraction had been built before its frames needed a feed.
"""


class SeedingActivity:
    """One seeding run's status, per project, plus the catch-up read of it."""

    def __init__(self) -> None:
        self._running: dict[UUID, dict[str, Any]] = {}
        self._finished: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}

    # ---------------- what the route drives ----------------

    def start(
        self, project_id: UUID, run: Callable[[], Awaitable[SeedingRun]]
    ) -> dict[str, Any]:
        """Begin a seeding run in the background and record it as running.

        Raises `RunAlreadyActive` when this project already has one in
        flight, the same exception `ResearchSupervisor.start` raises for the
        same reason: one run at a time, refused up front rather than
        discovered when two runs open the same topic twice.

        `run` is a factory, not a coroutine already in hand -- a caller
        refused by the check below has not been handed a live coroutine to
        leave unawaited, which is exactly what constructing one ahead of the
        check would do.

        A locally minted id, not `TopicSeeder`'s -- `seed` only mints its
        `run_id` once the turn has actually started inside the task, and the
        409 this guards against has to be raised before that coroutine has
        run at all.
        """
        existing = self.active(project_id)
        if existing is not None:
            raise RunAlreadyActive(project_id, UUID(existing["run_id"]))

        placeholder_id = uuid4()
        frame = {
            "type": SEEDING,
            "project_id": str(project_id),
            "run_id": str(placeholder_id),
            "status": "running",
        }
        self._running[project_id] = frame

        async def _drive() -> None:
            try:
                outcome = await run()
            except Exception as error:  # noqa: BLE001 -- reported, not raised, from a task
                self._finished[project_id] = {
                    "type": SEEDING,
                    "project_id": str(project_id),
                    "run_id": str(placeholder_id),
                    "status": "failed",
                    "detail": str(error),
                }
            else:
                self._finished[project_id] = {
                    "type": SEEDING,
                    "project_id": str(project_id),
                    "run_id": str(outcome.run_id),
                    "session_id": str(outcome.session_id),
                    "status": "done",
                    "subject": outcome.subject,
                    "reply": outcome.reply,
                }
            self._running.pop(project_id, None)

        task = asyncio.ensure_future(_drive())
        self._tasks[project_id] = task
        return frame

    # ---------------- what the route reads ----------------

    def active(self, project_id: UUID) -> dict[str, Any] | None:
        """The running frame if a task is still in flight, else None."""
        task = self._tasks.get(project_id)
        if task is None or task.done():
            return None
        return self._running.get(project_id)

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        """The in-flight run's frame, for a tab that arrived mid-run."""
        return self._running.get(project_id)

    def last(self, project_id: UUID) -> dict[str, Any] | None:
        """The most recently finished run's frame, kept rather than dropped.

        Nothing durable records a seeding run's outcome -- no event, no
        aggregate -- so this is the only account of what the last one did,
        for the same reason `ExtractionActivity.last` keeps a finished
        extraction's frames around instead of clearing them on completion.
        """
        return self._finished.get(project_id)

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's run settles. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            await task
