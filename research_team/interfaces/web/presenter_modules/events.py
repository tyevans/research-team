"""Event, feed, and change presenters for the web interface."""

import json
from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.domain import (
    AutonomyChanged,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    TurnFailed,
)

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

_ROLE_FOR_TYPE = {"human": "user", "ai": "assistant", "tool": "tool"}


def event_summary(event: DomainEvent) -> str:
    """One line describing an event, for the timeline."""
    if isinstance(event, SessionStarted):
        return event.model_name
    if isinstance(event, FileEdited):
        # The path alone says less than the log already knows: the edit intent
        # is recorded, so show what actually changed.
        return f"{event.path}  {_snippet(event.old_string)} → {_snippet(event.new_string)}"
    if isinstance(event, FILE_EVENTS):
        return event.path
    if isinstance(event, ConversationCompacted):
        saved = (
            f", ~{event.tokens_before:,} → {event.tokens_after:,} tokens"
            if event.tokens_before
            else ""
        )
        return (
            f"first {event.through_index} messages now behind a summary "
            f"({event.strategy}{saved})"
        )
    if isinstance(event, AutonomyChanged):
        # The level alone doesn't say what changed, and the tool alone
        # doesn't say what changed to; a reviewer needs both to know what
        # the agent could do differently after this event than before it.
        return f"{event.tool_name} → {event.level}"
    if isinstance(event, SessionForkedFrom):
        return f"from {str(event.source_session_id)[:8]} at event {event.at_event}"
    if isinstance(event, TurnFailed):
        if event.cancelled:
            return f"turn {event.turn_index}: cancelled"
        return f"turn {event.turn_index}: {event.error_type}: {event.error_message[:80]}"
    if hasattr(event, "turn_index"):
        return f"turn {event.turn_index}"
    if hasattr(event, "message"):
        data = event.message.get("data", {})
        calls = data.get("tool_calls") or []
        if calls:
            summaries = ", ".join(_call_summary(call) for call in calls)
            return _truncate(f"→ {summaries}", SUMMARY_LIMIT)
        return " ".join(str(data.get("content", "")).split())[:120]
    return ""


SUMMARY_LIMIT = 160
"""How wide a tool-call summary may get, in characters.

Matches the truncation the timeline row applies to every summary it renders, so
the cap lands here -- where the argument that overflowed it is still
identifiable -- rather than mid-word in the browser. The row is the only reader
that has a width at all; the SSE frame carries the same string, and a client
wanting the full arguments reads the message rather than the row.
"""

_ARG_VALUE_LIMIT = 60

_PREFERRED_ARGS = ("path", "file_path", "filename", "pattern", "command", "query")
"""Argument names that say *what* a call acted on, best first.

Kept in step with `summariseArgs` in `frontend/src/domain/conversation/message.ts`,
which makes the same choice for the provisional bubble that previews the row
this builds. The two are separate because one runs before the turn commits and
the other after; they are worth reading together when either changes.
"""


def _call_summary(call: dict[str, Any]) -> str:
    """One call as `name(arg=value  +n)`, or bare `name` when it took nothing.

    Both caps matter and neither subsumes the other. The per-value one keeps a
    single argument from crowding out the calls after it -- `remember` accepts
    20,000 characters of `text` -- and `SUMMARY_LIMIT` above keeps a dozen
    well-behaved calls from doing the same thing collectively.
    """
    name = call.get("name") or "?"
    args = call.get("args") or {}
    if not isinstance(args, dict) or not args:
        return str(name)
    keys = list(args)
    key = next((candidate for candidate in _PREFERRED_ARGS if candidate in args), keys[0])
    value = args[key]
    shown = value if isinstance(value, str) else json.dumps(value, default=str)
    # The count of what is not shown, so a reader can tell a one-argument call
    # from a preview of a call that took eight.
    extra = f"  +{len(keys) - 1}" if len(keys) > 1 else ""
    return f"{name}({key}={_truncate(shown, _ARG_VALUE_LIMIT)}{extra})"


def _truncate(text: str, limit: int) -> str:
    return text[: limit - 1] + "…" if len(text) > limit else text


def _snippet(text: str, limit: int = 30) -> str:
    """One line of an edit string, short enough to sit in a timeline row."""
    first = " ".join(text.split())
    return first[:limit] + "…" if len(first) > limit else first or "(nothing)"


def event_row(index: int, event: DomainEvent) -> dict[str, Any]:
    """One timeline row. `index` is 1-based, matching the REPL's numbering."""
    return {
        "index": index,
        "type": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
        "summary": event_summary(event),
        "path": getattr(event, "path", None),
        "turn_index": getattr(event, "turn_index", None),
        "is_error": getattr(event, "is_error", None),
        # None on everything that is not a failed turn, so a client can tell
        # "stopped on purpose" from "broke" without reading prose.
        "cancelled": getattr(event, "cancelled", None),
    }


def event_rows(events: list[DomainEvent]) -> list[dict[str, Any]]:
    return [event_row(i, event) for i, event in enumerate(events, start=1)]


def message_view(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    return {
        "role": _ROLE_FOR_TYPE.get(payload.get("type", ""), payload.get("type", "")),
        "content": data.get("content", ""),
        # Both already sit in the stored payload -- `message_to_dict` keeps
        # every field of a `ToolMessage` -- and both were being dropped here.
        # `name` is what lets the console pair a result with its call; the
        # artifact is what lets it draw anything but the model's own string.
        # Absent on every message written before this feature and on every
        # unconverted tool -- `None` in both cases, which is the permanent
        # fallback path, not an error case.
        "name": data.get("name"),
        "artifact": data.get("artifact"),
        "tool_calls": [
            {"name": call.get("name", "?"), "args": call.get("args", {})}
            for call in (data.get("tool_calls") or [])
        ],
        "is_error": data.get("status") == "error",
    }


def _revision_counts(events: list[DomainEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if isinstance(event, FILE_EVENTS):
            counts[event.path] = counts.get(event.path, 0) + 1
    return counts


def feed_event(session_id: UUID, event: DomainEvent, index: int | None) -> dict[str, Any]:
    """One live event, as pushed over SSE.

    Carries the same fields as a timeline row, so a live-appended event renders
    identically to a fetched one and the browser needs no follow-up request to
    colour it correctly.
    """
    return {
        "session_id": str(session_id),
        **event_row(index if index is not None else 0, event),
    }


def topic_change(topic_id: UUID, event: DomainEvent) -> dict[str, Any]:
    """One topic event, as pushed over SSE.

    Its own frame type rather than a `feed_event` row, because a topic is not
    a session: the session tree and the session views key everything they hold
    off `session_id`, and a topic's aggregate id under that name would have
    them looking for a session that does not exist. `Topic` sits beside
    `Seeding` and `Extraction` in being project-shaped rather than
    session-shaped -- but unlike those two it *is* a log entry, so it keeps
    its feed position as an SSE id and a reconnect replays it.

    **No project id, deliberately.** Only `TopicOpened` carries one; every
    later event addresses the topic alone, and answering "which project?" for
    those would mean a read-model lookup per frame on the connection every
    browser holds open. A client scopes instead by the project it is already
    showing -- at worst it re-reads one topic list when another project's
    topic moves, which is one request against a query per frame here.

    `change` is the event class name, the same field `event_row` puts under
    `type` -- so a client that wants to tell an opened topic from a status
    change has it without a follow-up read.
    """
    return {
        "type": "Topic",
        "topic_id": str(topic_id),
        "change": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
    }


def graph_change(project_id: UUID, event: DomainEvent) -> dict[str, Any]:
    """One knowledge-graph event, as pushed over SSE.

    Its own frame type for the reason `topic_change` is: neither is a session,
    and a document stream's `uuid5` aggregate id under `session_id` would have
    the session tree refetching something that is not a session at all. Unlike
    a topic, a document is not even an aggregate this application has a name
    for -- the id identifies one document's extraction history inside
    redstring, which nothing above this layer can do anything with. So it is
    not on the frame.

    **The project id is, and it comes free.** Every redstring event is a
    `TenantDomainEvent` and a project *is* the tenant, so answering "whose
    graph moved?" is a field read rather than the read-model lookup per frame
    that made `topic_change` give up on the question. Which is what lets a
    subscriber ignore another project's extraction outright instead of
    re-reading its own graph to find nothing changed -- worth more here than
    it would be for a topic list, because the read this saves is a whole
    graph.

    `change` is the event class name, matching `topic_change` and `event_row`.
    A client that wants to tell an extraction from a merge has it without a
    follow-up read; today nothing does, and both mean the same thing to the
    pane -- redraw.

    What this frame deliberately does not carry: the entities themselves.
    `DocumentExtracted` has all of them, and passing them through would make
    the pane's drawing a fold over the wire instead of a read of the graph --
    which would have to agree with what `whole` returns after consolidation
    has moved things, and would not. The frame is a nudge; the route stays the
    single answer to what the graph is.
    """
    return {
        "type": "Graph",
        "project_id": str(project_id),
        "change": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
    }


def corpus_change(project_id: UUID, event: DomainEvent) -> dict[str, Any]:
    """One corpus event, as pushed over SSE.

    Separate from `graph_change` even though a single ingest emits both, and
    the separation is the point rather than tidiness: `_store_document` runs
    *before* extraction and says why -- a document without a graph is
    repairable, a graph without its document is not -- so an extraction that
    fails leaves a stored source and no redstring event at all. A documents
    pane refreshed on graph frames would therefore go quiet on exactly the
    ingests a reader most needs to see the source of.

    `project_id` is the corpus's own aggregate id: a corpus shares its
    project's UUID (see `build_corpus_repository`), so this frame is
    project-addressed for free, the same way a graph frame is by `tenant_id`.

    Carries no document, only that one moved. The pane re-reads
    `/api/projects/{id}/sources`, which is one query against a read model and
    the same answer a reload would give -- against putting a source's metadata
    on a frame that every browser holding a connection receives, and then
    having two descriptions of one document that can disagree.
    """
    return {
        "type": "Corpus",
        "project_id": str(project_id),
        "change": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
    }


def media_change(project_id: UUID, event: DomainEvent) -> dict[str, Any]:
    """One media-proposal event, as pushed over SSE.

    Mirrors `corpus_change`'s shape and its reasoning: `MediaProposals` is
    keyed on `project_id` alone (see the aggregate's own module docstring), so
    `project_id` here is the aggregate id with no lookup, the same free
    addressing `corpus_change` gets from a corpus sharing its project's UUID.

    Before this presenter existed, `MediaProposals` events fell through to the
    generic `feed_event` branch in `app.py`'s SSE generator -- which sends
    `{"session_id": <this same project id>, "index": 0, ...}`. That is not a
    missing feature, it is actively wrong twice over: the frontend's
    `decodeFrame` requires `isEventIndex(index) >= 1` for the default "log"
    branch, so every one of those frames was silently dropped, and the ones
    that were not would have addressed a project id into the session tree.
    `MediaProposalPane` polled every 3s while a proposal was `accepted`
    instead, because accepting answers 202 and the terminal state (stored or
    failed) arrives minutes later after a download and a perception pass with
    nothing in the tab to prompt a re-read.

    Carries no proposal, only that one moved -- `corpus_change`'s argument
    about a document applies here to a proposal row: the pane re-reads
    `/api/projects/{id}/media-proposals`, which is the one description of
    a proposal's status, against a wire payload that could disagree with it.
    """
    return {
        "type": "Media",
        "project_id": str(project_id),
        "change": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
    }


def project_change(project_id: UUID, event: DomainEvent) -> dict[str, Any]:
    """One project event, as pushed over SSE.

    Its own frame type for the reason `topic_change` and `corpus_change` are:
    a project is not a session, and its aggregate id under `session_id` would
    send the session tree after a session that does not exist. And it is a
    *log* frame rather than a `Seeding`-family one -- a project event is
    appended to the store, so it carries a feed position, is addressed by an
    SSE id, and replays on `Last-Event-ID` after a reconnect. That is the test
    `Dispatch` failed and why `Dispatch` got a catch-up route instead.

    `project_id` is the project's own aggregate id, free the way a corpus's
    is -- a corpus shares this same UUID, which is the identity both frames
    lean on.

    One frame type for the whole aggregate, and `change` is what tells its
    events apart. The lifecycle events (`ProjectSessionJoined`,
    `ProjectTipAdvanced`, `ProjectDeleted`) move the holding-session link and
    the project list, so a frame per event class would be several frame types
    where the client wants one invalidation.

    Carries no state beyond the change's name. Anything more would be a second
    description of the project that can disagree with the read -- the same
    argument `corpus_change` makes about a document. The frame is a nudge;
    `GET /api/projects/{id}` stays the single answer to where the project
    stands.

    It used to carry `decision`, read off `ProjectStageAdvanced` through
    `getattr`. That event is gone with the workflow system and no surviving
    project event has a verdict, so the key could only ever have been null --
    which is a silent default rather than a field. Removed rather than left to
    answer null forever; the console's decoder already treats its absence as
    valid.
    """
    return {
        "type": "Project",
        "project_id": str(project_id),
        "change": type(event).__name__,
        "occurred_at": event.occurred_at.isoformat(),
    }
