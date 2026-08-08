"""Where an extraction has got to, while it is getting there.

`remember` runs for minutes -- domain classification, a model call per chunk,
then a consolidation decision per entity -- and until now said nothing until
it finished. This is the channel that carries the middle.

Keyed by **project**, not session: extraction is a project-level fact, the
graph is tenant-scoped by project, and the adapter that produces these notes
is scoped to a project and knows nothing about sessions.

**Provisional, and never durable.** These frames carry no feed position, so
`Last-Event-ID` cannot replay them -- which is exactly why the buffer and the
catch-up route exist rather than being an optimisation. An SSE connection
drops routinely (sleep, a network change, a proxy closing an idle socket), and
without somewhere to catch up from a lossy reconnect would look identical to a
stalled extraction: a frozen pane either way.

Shaped deliberately like `activity.py`, which is itself shaped like
`approvals.py`. Three modules, one problem: content that matters now, leaves
no event behind, and has to survive a reconnect.
"""

import asyncio
from typing import Any
from uuid import UUID

from research_team.application.knowledge import ExtractionNote, ExtractionReporter
from research_team.application.workers import ExtractionSnapshot

EXTRACTION = "Extraction"
"""The frame type on the live feed.

PascalCase like the event names beside it, because the browser switches on one
`type` field for everything it receives. It is *not* a domain event and must
never become one -- the log has no such entry, and that is the point.
"""

#: Stages after which nothing more will arrive for that source.
_TERMINAL = ("consolidated", "failed")


class ExtractionActivity:
    """Extraction progress, keyed by project, plus the feed that carries it."""

    def __init__(self) -> None:
        self._running: dict[UUID, list[dict[str, Any]]] = {}
        self._finished: dict[UUID, list[dict[str, Any]]] = {}
        self._source: dict[UUID, str] = {}
        self._listeners: set[asyncio.Queue] = set()

    # ---------------- what the ingest drives ----------------

    def reporter(self, project_id: UUID) -> ExtractionReporter:
        """An `ExtractionReporter` that buffers and broadcasts for one project."""

        def report(note: ExtractionNote) -> None:
            self._record(project_id, note)

        return report

    # ---------------- what the roster and HTTP drive ----------------

    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None:
        """The running extraction as the roster wants it, or None.

        Satisfies `ExtractionsInFlight`. The latest note wins: a snapshot is
        "where it has got to", not a history.
        """
        frames = self._running.get(project_id)
        if not frames:
            return None
        latest = frames[-1]
        return ExtractionSnapshot(
            source_id=latest["source_id"],
            stage=latest["stage"],
            detail=latest.get("detail", ""),
            index=latest.get("index"),
            total=latest.get("total"),
        )

    def current(self, project_id: UUID) -> list[dict[str, Any]]:
        """The running extraction's frames, for a tab that arrived mid-ingest."""
        return list(self._running.get(project_id, []))

    def last(self, project_id: UUID) -> list[dict[str, Any]]:
        """The most recently finished extraction's frames.

        Kept rather than dropped for the reason `TurnActivity.discarded` keeps
        a failed turn's content: nothing durable records the stages, so these
        frames are the only account of what just happened, and a pane that
        emptied on completion would discard the summary a reader wants most.
        """
        return list(self._finished.get(project_id, []))

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to extraction frames.

        Unbounded, matching the approvals and activity feeds: a dropped frame
        leaves a gap in a progress account with nothing to reconcile it.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    # ---------------- internals ----------------

    def _record(self, project_id: UUID, note: ExtractionNote) -> None:
        if self._source.get(project_id) != note.source_id:
            # A different document: whatever the last one left running is over,
            # and keeping its frames under the new source would attribute one
            # document's stages to another.
            self._running[project_id] = []
            self._source[project_id] = note.source_id

        frame = {
            "type": EXTRACTION,
            "project_id": str(project_id),
            "source_id": note.source_id,
            "stage": note.stage,
            "detail": note.detail,
            "entities": note.entities,
            "relationships": note.relationships,
            "domain": note.domain,
            "domain_confidence": note.domain_confidence,
            "index": note.index,
            "total": note.total,
            "model_calls": note.model_calls,
        }
        self._running.setdefault(project_id, []).append(frame)

        if note.stage in _TERMINAL:
            self._finished[project_id] = self._running.pop(project_id, [])
            self._source.pop(project_id, None)

        self._announce(frame)

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
