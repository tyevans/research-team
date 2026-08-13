"""What a turn is doing, before the log has anything to say about it.

A turn is atomic: every event appends in one write at the end, so the live
feed -- which reads the log -- has nothing to show while a turn runs. This is
the other channel. It carries provisional content, holds it for exactly as
long as the turn lasts, and is never the source of anything durable.

The buffer is not an optimisation. These frames carry no feed position, so
`Last-Event-ID` cannot replay them, and an SSE connection drops routinely --
sleep, a network change, a proxy closing an idle socket. Log events already
survive that. Without somewhere to catch up from, provisional content would
not, and a lossy reconnect would look exactly like a slow model: a frozen
pane either way.

Shaped deliberately like `approvals.py`, which solves the same problem for the
same reason.
"""

import asyncio
from typing import Any
from uuid import UUID

from research_team.application.ports import (
    ActivityMessage,
    ActivityNote,
    ActivityRemark,
    ActivityReporter,
)

ACTIVITY = "TurnActivity"
"""The frame type on the live feed.

PascalCase like the event names beside it, because the browser switches on one
`type` field for everything it receives. It is *not* a domain event and must
never become one -- the log has no such entry, and that is the point.
"""


REMARK = "remark"
"""The `kind` a remark carries on the wire.

Outside `MessageKind`, which names what a message is, because a remark is not
one. The browser types `kind` as a plain string and uses it only for a CSS
class, so an unstyled bubble is what an unrecognised kind renders as -- which
is the right failure for commentary and the reason this needed no frontend
change to stop being a 500.
"""

REMARK_ID_PREFIX = "remark:"
"""Namespaces a synthesised id away from every id a model produces.

The buffer keys on `message_id`, so a remark needs one to be stored, caught up
on, or rendered at all -- the browser's DTO requires the field and drops a
frame without it. A collision would splice a remark and a real message into one
bubble, so the prefix is load-bearing rather than decorative.
"""


class TurnActivity:
    """Provisional turn content, keyed by session, plus the feed that carries it."""

    def __init__(self) -> None:
        self._running: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._discarded: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._listeners: set[asyncio.Queue] = set()
        self._remarks: dict[UUID, int] = {}

    # ---------------- what the turn drives ----------------

    def begin(self, session_id: UUID) -> None:
        """Start a turn's buffer, dropping whatever the last one left behind."""
        self._running[session_id] = {}
        self._discarded.pop(session_id, None)
        self._remarks[session_id] = 0

    def reporter(self, session_id: UUID) -> ActivityReporter:
        """An `ActivityReporter` that buffers and broadcasts for one session."""

        def report(note: ActivityNote) -> None:
            self._record(session_id, note)

        return report

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        """End the turn's buffer.

        A committed turn's content is now on the log, which is authoritative --
        so the provisional copy is dropped rather than reconciled. A turn that
        failed or was cancelled recorded nothing, so what streamed is the only
        trace of it that exists; it moves aside rather than vanishing, and the
        UI offers it as explicitly discarded.
        """
        buffered = self._running.pop(session_id, None)
        self._remarks.pop(session_id, None)
        if committed or not buffered:
            self._discarded.pop(session_id, None)
            return
        self._discarded[session_id] = buffered

    # ---------------- what the HTTP layer drives ----------------

    def current(self, session_id: UUID) -> list[dict[str, Any]]:
        """The running turn's content so far, for a tab that arrived mid-turn."""
        return list(self._running.get(session_id, {}).values())

    def discarded(self, session_id: UUID) -> list[dict[str, Any]]:
        """What the last failed turn streamed before it was thrown away."""
        return list(self._discarded.get(session_id, {}).values())

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to activity frames.

        Unbounded, matching the approvals feed: a dropped frame leaves a gap in
        rendered prose with nothing to reconcile it.

        Not seeded with the running buffer, unlike approvals -- a subscriber
        gets that from the catch-up route, which it must call anyway to learn
        about a turn that started before it connected.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    # ---------------- internals ----------------

    def _record(self, session_id: UUID, note: ActivityNote) -> None:
        entries = self._running.setdefault(session_id, {})
        if isinstance(note, ActivityRemark):
            # Buffered like everything else rather than only broadcast. A
            # remark is provisional, not ephemeral, and this module exists
            # because an SSE connection drops routinely -- a tab that
            # reconnects mid-turn would otherwise be told less about the turn
            # than one that never dropped.
            count = self._remarks.get(session_id, 0) + 1
            self._remarks[session_id] = count
            entry = {
                "message_id": f"{REMARK_ID_PREFIX}{count}",
                "kind": REMARK,
                "payload": {},
                "is_error": False,
                "text": note.text,
            }
            entries[entry["message_id"]] = entry
        elif isinstance(note, ActivityMessage):
            entry = {
                "message_id": note.message_id,
                "kind": note.kind,
                "payload": note.payload,
                "is_error": note.is_error,
                "text": "",
            }
            # Replaces any accumulated deltas: the whole message is what the
            # log will record, so it wins over the pieces that preceded it.
            entries[note.message_id] = entry
        else:
            entry = entries.get(note.message_id)
            if entry is None:
                entry = {
                    "message_id": note.message_id,
                    "kind": "assistant",
                    "payload": {},
                    "is_error": False,
                    "text": "",
                }
                entries[note.message_id] = entry
            entry["text"] = entry["text"] + note.text
        self._announce({"type": ACTIVITY, "session_id": str(session_id), **entry})

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
