"""Where a course-authoring run has got to, while it is getting there.

Shaped like `seeding.py`, which is shaped like `extraction.py`, which is
shaped like `activity.py` -- the same problem each time: content that matters
now, leaves no event behind, and has to survive a reconnect.

**One run per project, not one per area**, and that is a product decision
rather than a concurrency convenience. Authoring an area is three model turns;
authoring a path is three per area and can be thirty. Letting a person start
several at once means a browser tab can commit an unbounded amount of a local
model's time with no way to see the total, and the second run's turns would
interleave with the first's on the same project. Refused up front, the way
`ResearchSupervisor.start` refuses a second research run.

**Progress is per area, and that is the difference from `SeedingActivity`.** A
seeding run is one turn and is either running or not; an authoring run over
eight areas is up to twenty-four turns and can sit at "running" for a very
long time. A panel that could only say "running" for twenty minutes is
indistinguishable from one that has hung, so the frame carries which area is
in hand and how many are done.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID, uuid4

from research_team.application import RunAlreadyActive

AUTHORING = "Authoring"
"""The frame type on the live feed, PascalCase like `SEEDING` beside it.

Not a domain event and must never become one. What the log records is the
`write_file` calls each turn makes; "an authoring run started" is not a fact
the log holds, which is exactly why this module exists."""


class AuthoringActivity:
    """One course-authoring run's status per project, plus its catch-up read."""

    def __init__(self) -> None:
        self._running: dict[UUID, dict[str, Any]] = {}
        self._finished: dict[UUID, dict[str, Any]] = {}
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._listeners: set[asyncio.Queue] = set()

    def start(
        self,
        project_id: UUID,
        targets: Sequence[str],
        run: Callable[[UUID, str], Awaitable[Any]],
        *,
        kind: str,
    ) -> dict[str, Any]:
        """Author every slug in `targets`, in order, in the background.

        `run` is a factory taking the run id and one target slug, for
        `SeedingActivity.start`'s reason: a caller refused by the check below
        has not been handed a live coroutine to leave unawaited.

        Targets are authored **sequentially**, not gathered. Each is three
        model turns against one endpoint, and running eight areas concurrently
        against a local server is how you turn a slow feature into a failed
        one. Sequential also means the per-area progress below is meaningful
        rather than eight things all at 0%.
        """
        existing = self.active(project_id)
        if existing is not None:
            raise RunAlreadyActive(project_id, UUID(existing["run_id"]))

        run_id = uuid4()
        frame = {
            "type": AUTHORING,
            "project_id": str(project_id),
            "run_id": str(run_id),
            "status": "running",
            "kind": kind,
            "targets": list(targets),
            "completed": [],
            "current": targets[0] if targets else None,
        }
        self._running[project_id] = frame
        self._announce(frame)

        async def _drive() -> None:
            completed: list[str] = []
            failures: list[dict[str, str]] = []
            sessions: list[str] = []
            for target in targets:
                self._running[project_id] = {
                    **frame,
                    "current": target,
                    "completed": list(completed),
                }
                self._announce(self._running[project_id])
                try:
                    outcome = await run(run_id, target)
                except Exception as error:  # noqa: BLE001 -- reported from a task, not raised
                    # One area's failure does not abandon the rest. A run over
                    # eight areas that stops at the third because one model
                    # call timed out has thrown away five areas of work that
                    # would have succeeded, and the person watching cannot
                    # tell a refusal from a crash. Failures are collected and
                    # reported per target instead.
                    failures.append({"target": target, "detail": str(error)})
                else:
                    completed.append(target)
                    sessions.append(str(outcome.session_id))

            finished = {
                "type": AUTHORING,
                "project_id": str(project_id),
                "run_id": str(run_id),
                # "done" even with failures in it, and the failures are listed.
                # A run that authored seven of eight areas did not fail, and
                # calling it failed would hide seven courses that exist.
                "status": "failed" if failures and not completed else "done",
                "kind": kind,
                "targets": list(targets),
                "completed": completed,
                "failures": failures,
                "sessions": sessions,
                "current": None,
            }
            self._finished[project_id] = finished
            self._running.pop(project_id, None)
            self._announce(finished)

        self._tasks[project_id] = asyncio.ensure_future(_drive())
        return frame

    def active(self, project_id: UUID) -> dict[str, Any] | None:
        task = self._tasks.get(project_id)
        if task is None or task.done():
            return None
        return self._running.get(project_id)

    def current(self, project_id: UUID) -> dict[str, Any] | None:
        return self._running.get(project_id)

    def last(self, project_id: UUID) -> dict[str, Any] | None:
        """The most recently finished run's frame.

        Nothing durable records an authoring run's outcome -- the files it
        wrote are on the log, but which run wrote them and which target failed
        is not -- so this is the only account of it, matching
        `SeedingActivity.last`.
        """
        return self._finished.get(project_id)

    async def wait(self, project_id: UUID) -> None:
        """Block until this project's run settles. For tests, not routes."""
        task = self._tasks.get(project_id)
        if task is not None:
            await task

    def listen(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
