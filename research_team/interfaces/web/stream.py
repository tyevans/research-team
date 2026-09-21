"""Server-sent event streaming HTTP route and feed serializer.

Its own module and router, decomposing `app.py`: live updates, keepalives,
reconnection via `Last-Event-ID`, and multi-stream multiplexing across
approvals, turn activity, extraction, seeding, and dispatch.
"""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from research_team.application import LiveFeed
from research_team.domain.research.corpus import Corpus
from research_team.domain.research.media_proposals import MediaProposals
from research_team.domain.research.topic import Topic
from research_team.domain.tenancy.project import Project
from research_team.infrastructure.persistence.event_store import KNOWLEDGE_CATEGORIES
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import WebApprovals
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.presenters import (
    corpus_change,
    feed_event,
    graph_change,
    media_change,
    project_change,
    topic_change,
)
from research_team.interfaces.web.seeding import SeedingActivity

KEEPALIVE_SECONDS = 15.0

DISCONNECT_CHECK = 0.5
"""How long we may sit unaware that the browser has gone."""


def _effective_keepalive() -> float:
    app = sys.modules.get("research_team.interfaces.web.app")
    if (
        app is not None
        and app.__dict__.get("KEEPALIVE_SECONDS") is not None
        and app.__dict__.get("KEEPALIVE_SECONDS") != 15.0
    ):
        return float(app.__dict__["KEEPALIVE_SECONDS"])
    return KEEPALIVE_SECONDS


def _effective_disconnect_check() -> float:
    app = sys.modules.get("research_team.interfaces.web.app")
    if (
        app is not None
        and app.__dict__.get("DISCONNECT_CHECK") is not None
        and app.__dict__.get("DISCONNECT_CHECK") != 0.5
    ):
        return float(app.__dict__["DISCONNECT_CHECK"])
    return DISCONNECT_CHECK


def _is_event(kind: str) -> bool:
    """Whether a queue item is a live feed log event rather than auxiliary state."""
    return kind not in ("approval", "activity", "extraction", "seeding", "dispatch")


def _sse_frame(data: Any, id: str | None = None) -> str:
    """Format data as an SSE frame."""
    if id is not None:
        return f"id: {id}\ndata: {json.dumps(data)}\n\n"
    return f"data: {json.dumps(data)}\n\n"


@dataclass(frozen=True)
class StreamDeps:
    """What the SSE stream route needs from `create_app`'s closure."""

    feed: LiveFeed
    approvals: WebApprovals | None = None
    activity: TurnActivity | None = None
    extraction: ExtractionActivity | None = None
    seeding: SeedingActivity | None = None
    dispatch: DispatchQueue | None = None


def stream_router(deps: StreamDeps) -> APIRouter:
    """The live event stream route, ready for `app.include_router`."""
    router = APIRouter()

    @router.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Every event, as it is appended, to every listening browser.

        `Last-Event-ID` is the browser's own reconnect header -- EventSource
        sends it automatically with the id of the last frame it received, so
        resuming costs the client nothing and closes the window where events
        appended during a dropped connection would never be seen.
        """
        resume_from = request.headers.get("last-event-id")
        return StreamingResponse(
            _sse(
                request,
                deps.feed,
                resume_from,
                deps.approvals,
                deps.activity,
                deps.extraction,
                deps.seeding,
                deps.dispatch,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def _sse(
    request: Request,
    feed: LiveFeed,
    resume_from: str | None = None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    extraction: ExtractionActivity | None = None,
    seeding: SeedingActivity | None = None,
    dispatch: DispatchQueue | None = None,
) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.

    Every logged frame carries the position that follows it as its id, so a
    browser that drops can say where it got to. An id we cannot place --
    stale, or from a database since replaced -- is treated as no id at all:
    starting at the live end shows less than the client wanted, while
    replaying the entire log at it would be worse than the gap.

    Approval requests, turn activity notes, extraction progress, seeding
    status and dispatch status ride this same connection rather than one each
    of their own, for the same reason as each other: none is a log entry -- an
    approval that is never answered, provisional turn content, where an ingest
    has got to, whether a seeding run is still going, and what a project has
    queued at its topics all leave no event behind -- so none carries an id,
    and a reconnecting browser refetches what it missed (`/approvals`, the
    activity catch-up route, `/projects/{id}/extraction`,
    `/projects/{id}/topics/seed`, or `/projects/{id}/dispatch`) instead of
    replaying them. But a second
    channel per concern would multiply the ways a tab can be half-connected,
    and a turn that halts for a person, or is still streaming its reply, is
    exactly the moment when being half-connected is worst.
    """
    queue: asyncio.Queue = asyncio.Queue()
    start_at = feed.decode_position(resume_from) if resume_from else None
    # Taken here rather than left to `follow`, so that by the time this
    # generator yields anything the cursor is already fixed. `follow` would
    # take the same position on the first turn of the pump task below, which is
    # scheduled and not awaited -- so "the response has started" would not mean
    # "the subscriber is placed", and an event appended in between would be
    # missed by a client that had every reason to think it was listening.
    #
    # `from_beginning` is not a nicety. An empty log has no position, so
    # `position_now()` answers `None` -- which is the same value as "I am not
    # telling you where to start", and `follow` responds to that by taking the
    # position itself, later, on the pump's first turn. The window this exists
    # to close would have reopened for exactly the case where it is widest.
    # Replaying from the start is not a different behaviour here: the log was
    # empty when we looked, so everything from the start *is* everything since.
    from_beginning = False
    if start_at is None:
        start_at = await feed.position_now()
        from_beginning = start_at is None

    async def pump() -> None:
        async for entry in feed.follow(from_position=start_at, from_start=from_beginning):
            await queue.put(("event", entry))

    # The feed is drained by its own task rather than awaited inline, so waiting
    # for the next event never means being unable to notice anything else. What
    # this coroutine waits on is a queue, which is safe to cancel; cancelling a
    # database poll mid-flight is not.
    pumps = [asyncio.create_task(pump())]
    listening = None
    if approvals is not None:
        listening = approvals.listen()

        async def pump_approvals() -> None:
            while True:
                await queue.put(("approval", await listening.get()))

        pumps.append(asyncio.create_task(pump_approvals()))

    watching = None
    if activity is not None:
        watching = activity.listen()

        async def pump_activity() -> None:
            while True:
                await queue.put(("activity", await watching.get()))

        pumps.append(asyncio.create_task(pump_activity()))

    extracting = None
    if extraction is not None:
        extracting = extraction.listen()

        async def pump_extraction() -> None:
            while True:
                await queue.put(("extraction", await extracting.get()))

        pumps.append(asyncio.create_task(pump_extraction()))

    seeded = None
    if seeding is not None:
        seeded = seeding.listen()

        async def pump_seeding() -> None:
            while True:
                await queue.put(("seeding", await seeded.get()))

        pumps.append(asyncio.create_task(pump_seeding()))

    dispatching = None
    if dispatch is not None:
        dispatching = dispatch.listen()

        async def pump_dispatch() -> None:
            while True:
                await queue.put(("dispatch", await dispatching.get()))

        pumps.append(asyncio.create_task(pump_dispatch()))

    idle = 0.0
    try:
        # "You are subscribed, from a position already taken."
        #
        # A comment rather than an event: `EventSource` ignores `:` lines
        # entirely, so no browser needs to know this exists and no client code
        # changes. What it buys is a point in time that means something --
        # headers arrive when the route returns, which is before any of the
        # above has run, so `onopen` alone never told a client its cursor was
        # placed.
        #
        # Inside the `try`, not above it, and that placement is the whole
        # reason this is not a one-line addition: a yield is a suspension
        # point, and a client that hangs up exactly here would otherwise throw
        # `GeneratorExit` past the `finally` that stops the pump tasks and
        # releases the listeners.
        #
        # It also makes the tests in `test_web.py` and `test_turn_visibility.py`
        # honest. They established "the subscriber is listening" with sleeps of
        # 0.05 to 0.4 seconds -- the `BACKLOG.md` B4 shape, and the reason a
        # write racing a subscription looked like a broken feed on a loaded
        # machine.
        yield ": ready\n\n"

        while not await request.is_disconnected():
            disconnect_check = _effective_disconnect_check()
            keepalive_seconds = _effective_keepalive()
            try:
                kind, item = await asyncio.wait_for(queue.get(), timeout=disconnect_check)
            except TimeoutError:
                idle += disconnect_check
                if idle >= keepalive_seconds:
                    # Long enough that an intermediary might give up on us --
                    # a turn can sit silent for a minute while the model thinks.
                    yield ": keepalive\n\n"
                    idle = 0.0
                continue
            idle = 0.0
            if kind in ("approval", "activity", "extraction", "seeding", "dispatch"):
                yield f"data: {json.dumps(item)}\n\n"
                continue
            if item.aggregate_type == Topic.aggregate_type:
                payload = topic_change(item.aggregate_id, item.event)
            elif item.aggregate_type in KNOWLEDGE_CATEGORIES:
                # `tenant_id`, not `aggregate_id`: see `graph_change`. Read
                # directly rather than through a `getattr` default -- every
                # event in these two categories is a `TenantDomainEvent`, and
                # one that was not would be a bug worth an `AttributeError`
                # naming it rather than a frame quietly addressed to nobody.
                payload = graph_change(item.event.tenant_id, item.event)
            elif item.aggregate_type == Project.aggregate_type:
                # Same free addressing as a corpus, and for the same reason:
                # a project's aggregate id *is* the project id, so the frame
                # names its project without a read model lookup.
                payload = project_change(item.aggregate_id, item.event)
            elif item.aggregate_type == Corpus.aggregate_type:
                # A corpus shares its project's UUID, so the aggregate id is
                # the project id with no lookup -- unlike a topic, which is why
                # a topic frame carries no project at all.
                payload = corpus_change(item.aggregate_id, item.event)
            elif item.aggregate_type == MediaProposals.aggregate_type:
                # A `MediaProposals` aggregate is keyed on `project_id` alone
                # (see the aggregate's module docstring), so the aggregate id
                # is the project id with no lookup -- the same free addressing
                # `corpus_change` gets from a corpus sharing its project's
                # UUID. Without this branch these events fell to the generic
                # `feed_event` below, which sent `index: 0` and was silently
                # dropped by the frontend's log-frame branch.
                payload = media_change(item.aggregate_id, item.event)
            else:
                payload = feed_event(
                    item.aggregate_id,
                    item.event,
                    getattr(item.event, "aggregate_version", None),
                )
            # One yield, not two: an id and its data are a single SSE frame,
            # and splitting them would let a cancellation land between the
            # cursor and the event it belongs to.
            cursor = feed.encode_position(item.position)
            yield f"id: {cursor}\ndata: {json.dumps(payload)}\n\n"
    finally:
        if approvals is not None and listening is not None:
            approvals.stop_listening(listening)
        if activity is not None and watching is not None:
            activity.stop_listening(watching)
        if extraction is not None and extracting is not None:
            extraction.stop_listening(extracting)
        if seeding is not None and seeded is not None:
            seeding.stop_listening(seeded)
        if dispatch is not None and dispatching is not None:
            dispatch.stop_listening(dispatching)
        for pumping in pumps:
            pumping.cancel()
            with suppress(asyncio.CancelledError):
                await pumping
