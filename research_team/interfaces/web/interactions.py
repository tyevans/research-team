"""The interaction log HTTP routes.

Its own module and its own router, following `export.py`, `settings.py`,
`catalog.py`, `dialogues.py`, and `sources.py`: `create_app` is a large
set of closures over optional collaborators, and extracting these routes
eliminates ~350 lines of interaction route closures from `app.py`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from eventsource.ports.dlq import DLQEntry
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from research_team.domain.interaction import INTERACTION_EVENTS, InteractionEvent
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.persistence.interaction_log import (
    ENVELOPE_FIELDS,
    BrowserSessionPage,
    InteractionEventPage,
    InteractionEventRow,
    InteractionLogReader,
    InteractionSummary,
)

InteractionReaders = Callable[[], InteractionLogReader | None]
"""A factory returning an `InteractionLogReader`, or `None` when unconfigured.

Callable rather than the reader itself, because `InteractionLogRunner.reader`
*raises* until `start()` has run, and `start()` runs during lifespan startup --
after `create_app` returns. The spec says `create_app` gains
`interaction_reader: InteractionLogReader | None`, but a reader passed by value
there is either `None` forever (lifespan has not started) or bound to a runner
whose lifespan has not yet set its reader up.
"""

InteractionFailures = Callable[[], Awaitable[list[DLQEntry]]]
"""A factory returning the runner's DLQ entries, newest first.

`InteractionLogRunner.failures` bound, rather than the runner: the health
route is the only caller and only reads the failure list, so narrowing the seam
to a single awaitable callable keeps the web layer from depending on the runner
itself.
"""

INTERACTION_BATCH_LIMIT = 200
"""Most events one POST may carry.

The client flushes at 50, so this leaves room for a page-hide flush racing a
timer flush without rejecting a batch that is merely unlucky.
"""

_INTERACTION_KINDS = {event_type.__name__: event_type for event_type in INTERACTION_EVENTS}

_INTERACTION_ENVELOPE_KEYS = ENVELOPE_FIELDS
"""Every field the event envelopes own, imported rather than listed.

`envelope.payload` is splatted onto the constructor alongside the keyword
arguments the route supplies, so a payload key that names an envelope
field is either a `TypeError` ("got multiple values for keyword
argument") for the eight the route passes explicitly, or -- far worse --
a silent write for the nine it does not. `actor_id`, `tenant_id`,
`causation_id` and `metadata` are free-form on `DomainEvent`, so a
payload carrying one wrote arbitrary user text into the store, *outside*
`TEXT_BEARING_FIELDS`, and `row_for` then stripped it back out of the
row -- leaving it only in the `events` blob, the one place someone
inspecting the log by hand would not look. `aggregate_type` could also be
set to disagree with the `StreamId` the recorder appends under.

Derived from the models rather than hand-picked because the hand-picked
version is exactly the defect above: this branch shipped with eight of
the seventeen named. `ENVELOPE_FIELDS` is the same expression the
projection uses to strip these keys out of a stored payload, so the two
directions cannot drift apart. Nothing legitimate collides -- payload
fields are kind-specific (`params`, `dwell_ms`, `query_text`, ...).
"""


class InteractionEnvelope(BaseModel):
    """One reported interaction, as the browser sends it.

    Deliberately loose about `payload`: the kind decides its shape, and the
    domain event validates it. Validating twice would mean two vocabularies to
    keep in step, and the second one would drift.
    """

    kind: str
    browser_session_id: UUID
    install_id: UUID
    seq: int
    view: str
    occurred_at: datetime
    project_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InteractionBatch(BaseModel):
    """One flush.

    Capped rather than unbounded because this route takes unauthenticated
    input on a local port and the body becomes rows.

    `events` is `list[dict]`, not `list[InteractionEnvelope]`, on purpose:
    FastAPI validates a typed body before the route runs, so a batch typed as
    `list[InteractionEnvelope]` would 422 in full the moment any one envelope
    failed schema validation -- the same whole-batch loss partial acceptance
    exists to avoid, just moved one layer earlier where the route's own
    try/except never gets a chance to run. Each dict is validated into an
    `InteractionEnvelope` by hand, per-event, inside the route.
    """

    events: list[dict[str, Any]] = Field(
        default_factory=list, max_length=INTERACTION_BATCH_LIMIT
    )


@dataclass(frozen=True)
class InteractionDeps:
    """What the interaction routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    interactions: EventStoreInteractionRecorder | None = None
    interaction_reader: InteractionReaders | None = None
    interaction_failures: InteractionFailures | None = None
    settings: Any = None

    # Aliases for flexibility across callers
    interaction_log: EventStoreInteractionRecorder | None = None
    interaction_readers: InteractionReaders | None = None
    recorder: EventStoreInteractionRecorder | None = None
    reader: InteractionReaders | None = None
    failures: InteractionFailures | None = None

    def __post_init__(self) -> None:
        if self.interactions is None:
            if self.interaction_log is not None:
                object.__setattr__(self, "interactions", self.interaction_log)
            elif self.recorder is not None:
                object.__setattr__(self, "interactions", self.recorder)
        if self.interaction_reader is None:
            if self.interaction_readers is not None:
                object.__setattr__(self, "interaction_reader", self.interaction_readers)
            elif self.reader is not None:
                object.__setattr__(self, "interaction_reader", self.reader)
        if self.interaction_failures is None and self.failures is not None:
            object.__setattr__(self, "interaction_failures", self.failures)


def _instant(name: str, raw: str | None) -> datetime | None:
    """One ISO query parameter as a datetime, 422 if it will not parse.

    `fromisoformat` and not `dateutil`: the client this serves is the
    browser, which produces `toISOString()` output, and accepting looser
    spellings would make the set of dates that work depend on which parser
    happened to be installed.
    """
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{name}={raw!r} is not an ISO instant"
        ) from None


def _interaction_window(
    since: str | None, until: str | None
) -> tuple[datetime | None, datetime | None]:
    """`since`/`until` as instants, naive spellings read as UTC.

    The reader calls `astimezone` on both bounds, which reads a naive
    datetime as *local* time -- so a bare `2026-08-25T00:00:00` would
    select a different window on a laptop in Berlin than on one in UTC,
    and neither would look wrong. Pinned here rather than in the reader
    because this is the seam where a string becomes a datetime.
    """
    bounds = []
    for name, raw in (("since", since), ("until", until)):
        moment = _instant(name, raw)
        if moment is not None and moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        bounds.append(moment)
    return bounds[0], bounds[1]


def interaction_router(deps: InteractionDeps) -> APIRouter:
    """The interaction log routes, ready for `app.include_router`."""
    router = APIRouter()

    def _interaction_log_reader() -> InteractionLogReader:
        """The reader, or 503 naming why there is none.

        Gated on the *reader*, never on `interactions`: `AGENT_INTERACTION_LOG=0`
        switches off the recorder while the runner still starts and the table
        still exists, and the honest answer there is an empty log with
        `collecting: false`. 503ing on the recorder's absence would make
        "switched off" and "broken" the same response, which is the one
        distinction this whole surface exists to draw.
        """
        reader = deps.interaction_reader() if deps.interaction_reader is not None else None
        if reader is None:
            raise HTTPException(
                status_code=503, detail="the interaction log reader is not configured"
            )
        return reader

    def _interaction_kind_filter(kinds: list[str] | None) -> list[str] | None:
        """The requested kinds, or 422 naming the one that is not a kind.

        422 rather than returning nothing, because on the server an
        unrecognised kind is a caller error and an empty page is what a
        *correct* filter over a quiet log looks like. Silence here would be
        indistinguishable from the instrument having stopped -- the exact
        confusion this surface is for.
        """
        if not kinds:
            return None
        unknown = [kind for kind in kinds if kind not in _INTERACTION_KINDS]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown interaction kind(s): {', '.join(sorted(unknown))}",
            )
        return kinds

    @router.post("/api/interactions")
    async def post_interactions(body: InteractionBatch):
        """Record what the console's user did. Capture only; nothing reads
        this back.

        Answers 202 with counts rather than rejecting a batch that contains
        one bad event. The client cannot see this response -- it is delivered
        by `sendBeacon` on page-hide, which reports nothing -- so a
        whole-batch rejection would silently discard the good events beside
        the bad one. Partial acceptance loses one event instead of fifty.

        The counts are returned anyway, for a human with curl.
        """
        if deps.interactions is None:
            raise HTTPException(
                status_code=503, detail="the interaction log is not collecting"
            )

        received = datetime.now(UTC)
        events: list[InteractionEvent] = []
        rejected = 0
        for raw in body.events:
            try:
                envelope = InteractionEnvelope.model_validate(raw)
            except ValidationError:
                # The envelope itself doesn't match the shape every kind
                # shares (a missing `view`, a bad UUID). Counted alongside a
                # bad `kind` and a bad `payload` below: see the docstring.
                rejected += 1
                continue
            event_type = _INTERACTION_KINDS.get(envelope.kind)
            if event_type is None:
                rejected += 1
                continue
            if not _INTERACTION_ENVELOPE_KEYS.isdisjoint(envelope.payload):
                # A payload carrying an envelope-owned key (e.g. `seq`)
                # would otherwise collide with the explicit keyword below
                # and raise `TypeError`, not `ValidationError` -- see
                # `_INTERACTION_ENVELOPE_KEYS`. The envelope is the
                # authority for these fields; payload content never
                # overrides them, so the event is rejected rather than
                # silently dropping either value.
                rejected += 1
                continue
            try:
                events.append(
                    event_type(
                        aggregate_id=envelope.browser_session_id,
                        install_id=envelope.install_id,
                        seq=envelope.seq,
                        view=envelope.view,
                        occurred_at=envelope.occurred_at,
                        project_id=envelope.project_id,
                        session_id=envelope.session_id,
                        received_at=received,
                        **envelope.payload,
                    )
                )
            except (ValidationError, TypeError):
                # One event's payload not matching its kind. Counted, not
                # raised: see the docstring. `TypeError` is belt-and-braces
                # here, not the primary defense -- the collision check above
                # is what actually stops an envelope-owned key from reaching
                # the constructor; this only catches whatever that check
                # didn't anticipate.
                rejected += 1
                continue

        accepted = await deps.interactions.record(events)
        return JSONResponse(
            status_code=202,
            content={"accepted": accepted, "rejected": rejected},
        )

    @router.get("/api/interactions/health")
    async def read_interaction_health():
        """Is the instrument working, and how much has it seen.

        Three sources, and the split is deliberate. `collecting` is whether the
        *recorder* was wired -- a fact about `AGENT_INTERACTION_LOG` that only
        this layer can see. `failures` is the projection's DLQ, which belongs
        to the runner. Everything else is a query over the table. A reader that
        reported all three would be guessing at two of them.

        `kinds` carries every name in `INTERACTION_EVENTS`, zeros included:
        that is the reader's doing, and the test derives the expected set from
        the tuple rather than listing it.
        """
        reader = _interaction_log_reader()
        health = await reader.health()
        failures = (
            await deps.interaction_failures() if deps.interaction_failures is not None else []
        )
        return {
            "collecting": deps.interactions is not None,
            "total": health.total,
            "first_at": health.first_at,
            "last_at": health.last_at,
            "kinds": health.kinds,
            "failures": [
                {
                    "id": str(entry.id),
                    "event_type": entry.event_type,
                    "error": entry.error_message,
                    "failed_at": entry.last_failed_at or entry.first_failed_at,
                }
                for entry in failures
            ],
            "install_count": health.install_count,
            "session_count": health.session_count,
        }

    @router.get("/api/interactions/sessions")
    async def read_interaction_sessions(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        install_id: UUID | None = None,
        project_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> BrowserSessionPage:
        """One row per browser session, newest first.

        `limit` over 500 is a 422 rather than a clamp, and the choice is not
        the one `read_timeline` made. There, `truncated` in the body tells the
        caller the clamp happened; here a clamped page and a complete one are
        the same JSON, so a caller asking for 800 and receiving 500 would read
        it as the whole answer.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.sessions(
            limit=limit,
            offset=offset,
            install_id=install_id,
            project_id=project_id,
            since=window_since,
            until=window_until,
        )

    @router.get("/api/interactions/sessions/{browser_session_id}")
    async def read_interaction_session(
        browser_session_id: UUID,
    ) -> dict[str, list[InteractionEventRow]]:
        """One browser session's whole stream, `seq` ascending.

        404 when no row carries that id -- the reader answers `None` rather
        than `[]` precisely so this route can tell an unknown session from a
        real one, and a bare empty list could not.

        Unpaged, per the spec: a browser session is bounded by a tab's life.
        There is still an `events` envelope rather than a bare JSON array,
        matching `/events` and `/sessions`: three collection routes under one
        prefix that disagree about their outermost shape is a decoder written
        twice, and the spec's own example bodies are objects throughout. It
        also leaves somewhere for a later `total` or a truncation flag to go
        without breaking a client, which a top-level array does not.
        """
        reader = _interaction_log_reader()
        events = await reader.session(browser_session_id)
        if events is None:
            raise HTTPException(
                status_code=404,
                detail=f"no interactions for browser session {browser_session_id}",
            )
        return {"events": events}

    @router.get("/api/interactions/events")
    async def read_interaction_events(
        kind: Annotated[list[str] | None, Query()] = None,
        view: Annotated[list[str] | None, Query()] = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        order: Literal["newest", "oldest"] = "newest",
    ) -> InteractionEventPage:
        """A page of events under the filters, with the count under the same
        filters beside it.

        `total` is not the page length: a reader who cannot tell 200-of-200
        from 200-of-9000 cannot tell a filter that found everything from one
        that hit the cap.

        `kind` and `view` repeat. An unknown `kind` is 422; an unknown `view`
        is not, because the view vocabulary is the console's route names rather
        than a closed tuple, and a view that no longer exists is a legitimate
        thing to ask an old log about.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.events(
            kinds=_interaction_kind_filter(kind),
            views=view or None,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=window_since,
            until=window_until,
            limit=limit,
            offset=offset,
            order=order,
        )

    @router.get("/api/interactions/summary")
    async def read_interaction_summary(
        kind: Annotated[list[str] | None, Query()] = None,
        view: Annotated[list[str] | None, Query()] = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> InteractionSummary:
        """Aggregates over the same window `/events` pages.

        No `limit`: the aggregate is over every matching row, and a paged
        aggregate would be a different number wearing the same name.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.summary(
            kinds=_interaction_kind_filter(kind),
            views=view or None,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=window_since,
            until=window_until,
        )

    return router
