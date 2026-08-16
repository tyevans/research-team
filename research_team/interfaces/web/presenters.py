"""Domain objects rendered as the JSON the browser consumes.

The web equivalent of the CLI's formatters: pure functions, no I/O, and the
only place that knows the wire shape. Keeping them here means the API can be
reshaped for the UI without anything below noticing.
"""

import json
from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.application import (
    GATED_TOOLS,
    STAGE_GATE_TOOLS,
    AutonomyPolicy,
    ForkNode,
    Roster,
    SessionSummary,
    Worker,
)
from research_team.application.corpus_read import SourceListing, StoredDocument
from research_team.application.corpus_spans import Span
from research_team.application.course import (
    ArtifactSlot,
    Course,
    ProvenanceSummary,
    StageProgress,
)
from research_team.application.entity_definitions import Definition, ServedCitation
from research_team.application.findings import Finding
from research_team.application.graph_read import (
    EntityPage,
    Graph,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.application.research_supervisor import ActiveRun
from research_team.application.timeline_read import Timeline, TimelineBand
from research_team.application.topic_read import TopicDetail, TopicView
from research_team.application.usages import Usage
from research_team.domain import (
    AutonomyChanged,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    ProjectStageAdvanced,
    ProjectState,
    ProjectWorkflowSelected,
    Session,
    SessionForkedFrom,
    SessionStarted,
    SourceRecord,
    TurnFailed,
)
from research_team.domain.learner import LearnerProgressState
from research_team.domain.research_run import ResearchRunState
from research_team.domain.workflow import Preset, Stage

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
    if isinstance(event, ProjectWorkflowSelected):
        return f"{event.preset_id} v{event.preset_version}"
    if isinstance(event, ProjectStageAdvanced):
        # Both ends of the move, and the reason. A preset has up to fifteen
        # stages, so "now at X" does not say what was left; and the rationale
        # is what a reviewer scrolling the log is actually looking for, since
        # it is the only record of why the gate was crossed.
        return f"{event.from_stage} → {event.to_stage}: {event.gate_decision}"
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


def session_view(
    session: Session,
    events: list[DomainEvent],
    *,
    at: int | None = None,
    holds_project: bool | None = None,
    knowledge_attached: bool | None = None,
) -> dict[str, Any]:
    """A session's full state. `at` marks a scrubbed view rather than HEAD.

    `holds_project` and `knowledge_attached` are process facts, not log
    facts, so they are passed in rather than derived here. They are reported
    on the session because they are what the *user* needs to know before
    typing: whether this session still owns the project's filesystem, and
    whether the agent can actually reach the graph its prompt promises it.
    None means the caller did not ask.
    """
    state = session.state
    revisions = _revision_counts(events if at is None else events[:at])
    return {
        "id": str(state.session_id),
        # Still conditional, where `summary_view`'s is not, and the difference
        # is not an oversight. That one reads a `SessionSummary`, folded from a
        # stream that must open with `SessionStarted`, so its project is
        # required. This one reads `SessionState`, whose `project_id` is `None`
        # until that event folds -- the "new" state `initial_state()` has to be
        # able to express. No route reaches this with an unstarted session, so
        # the branch is unreachable in practice; it is kept because the
        # alternative renders the string "None" if it ever is reached.
        "project_id": str(state.project_id) if state.project_id else None,
        "holds_project": holds_project,
        "knowledge_attached": knowledge_attached,
        "system_prompt": state.system_prompt,
        "model_name": state.model_name,
        "turn_index": state.turn_index,
        "failed_turns": state.failed_turns,
        "forked_from": str(state.forked_from) if state.forked_from else None,
        "forked_at": state.forked_at,
        "event_count": len(events),
        "compacted_through": state.compacted_through,
        "compaction_summary": state.compaction_summary,
        "at": at,
        "files": [
            {
                "path": path,
                "size": len(data.get("content", "")),
                "revisions": revisions.get(path, 0),
            }
            for path, data in sorted(state.files.items())
        ],
        "messages": [message_view(payload) for payload in state.messages],
    }


def file_history(events: list[DomainEvent], path: str) -> list[dict[str, Any]]:
    """Every event that touched one path, with the edit intent where recorded."""
    rows = []
    for index, event in enumerate(events, start=1):
        if not isinstance(event, FILE_EVENTS) or event.path != path:
            continue
        row = {
            "index": index,
            "type": type(event).__name__,
            "occurred_at": event.occurred_at.isoformat(),
            "content": getattr(event, "file_data", {}).get("content"),
            "old_string": None,
            "new_string": None,
            "replace_all": None,
        }
        if isinstance(event, FileEdited):
            row["old_string"] = event.old_string
            row["new_string"] = event.new_string
            row["replace_all"] = event.replace_all
        rows.append(row)
    return rows


def summary_view(summary: SessionSummary) -> dict[str, Any]:
    """One row of `/sessions`, and -- with `children` -- one node of `/tree`.

    `project_id` is reported the way `session_view` reports it, and for the
    console's sake rather than the fold's: a list of sessions carrying no
    project key cannot be grouped under the projects they belong to, so the
    landing page could only ever show two unrelated piles.
    """
    return {
        "id": str(summary.session_id),
        "project_id": str(summary.project_id),
        "started_at": summary.started_at.isoformat(),
        "turns": summary.turns,
        "files": summary.files,
        "first_message": summary.first_message,
        "forked_from": str(summary.forked_from) if summary.forked_from else None,
        "forked_at": summary.forked_at,
        "failed_turns": summary.failed_turns,
    }


def tree_view(nodes: list[ForkNode]) -> list[dict[str, Any]]:
    return [
        {**summary_view(node.session), "children": tree_view(list(node.children))}
        for node in nodes
    ]


def preset_label(preset: Preset) -> str:
    """One line for a `<select>` option: what this preset makes, and where it stops.

    A dropdown of three methodology names is only meaningful to someone who
    has read three research reports; what a preset produces and which stage it
    ends on is meaningful to everyone, and it is the fact people are actually
    choosing between. The two are joined here rather than assembled in the
    browser so the wording has one home and can carry this reasoning with it.
    """
    return f"{preset.name} -- produces {preset.produces}, ending at {preset.stages[-1].name}"


def preset_view(preset: Preset) -> dict[str, Any]:
    """One row of `/api/workflows`, as a choice rather than as a name.

    `terminates_at` is the field that earns this endpoint. A preset stopping
    below spine position 8 has no production half, so it yields a design and
    not materials -- and someone who expected materials discovering that at
    the end of a long run is the exact failure surfacing it up front prevents.
    `has_value_filter` is reported for the same reason from the other
    direction: ADDIE never asks whether the thing should be taught at all,
    which is a defensible assumption and an indefensible surprise.
    """
    last = preset.stages[-1]
    return {
        "id": preset.id,
        "name": preset.name,
        "version": preset.version,
        "description": preset.description,
        "produces": preset.produces,
        "stage_count": len(preset.stages),
        "terminates_at": {"id": last.id, "name": last.name, "spine": preset.terminal_spine},
        "has_value_filter": preset.has_value_filter,
        "label": preset_label(preset),
    }


def stage_view(preset: Preset, stage: Stage) -> dict[str, Any]:
    """Where a project stands, placed in its preset rather than merely named.

    "4 of 15" is what a chip can show and a person can read; the namespaced id
    is precise and says nothing about progress. Both are carried because the
    id is what every other surface keys on.
    """
    ids = [each.id for each in preset.stages]
    return {
        "id": stage.id,
        "name": stage.name,
        "index": ids.index(stage.id) + 1,
        "of": len(ids),
    }


def provenance_view(provenance: ProvenanceSummary | None) -> dict[str, Any] | None:
    """What an artifact says it rests on, as the browser needs it.

    `empty` is computed here rather than left to the browser to derive from
    three other fields, because it is the one shape the artifact contract calls
    never right and a client rederiving it is a client that can get it wrong.
    """
    if provenance is None:
        return None
    return {
        "sources": [
            {"source_id": span.source_id, "start": span.start, "end": span.end}
            for span in provenance.sources
        ],
        "inferred": provenance.inferred,
        "unreadable": provenance.unreadable,
        "empty": provenance.is_empty,
    }


def artifact_slot_view(slot: ArtifactSlot) -> dict[str, Any]:
    """One declared artifact, present or not.

    The frontmatter is not sent. It is already on the file, the file is one
    click away through the existing file endpoint, and a listing that inlined
    every block would grow with the course while being read by a pane that
    shows a row per artifact. What is sent is what the row itself renders:
    whether it landed, what it claims, and what its block was missing.
    """
    return {
        "path": slot.path,
        "artifact_type": slot.artifact_type,
        "subtype": slot.subtype,
        "cardinality": slot.cardinality,
        "stage_id": slot.stage_id,
        "present": slot.present,
        "has_frontmatter": slot.frontmatter is not None,
        "missing_fields": list(slot.missing_fields),
        "provenance": provenance_view(slot.provenance),
        "body_chars": slot.body_chars,
    }


def finding_view(finding: Finding) -> dict[str, Any]:
    return {
        "check": finding.check,
        "severity": finding.severity,
        "message": finding.message,
        "cites": list(finding.cites),
        "suggested_edit": finding.suggested_edit,
    }


def stage_progress_view(stage: StageProgress) -> dict[str, Any]:
    return {
        "index": stage.index,
        "id": stage.id,
        "name": stage.name,
        "kind": stage.kind,
        "spine": stage.spine,
        "scope_level": stage.scope_level,
        "status": stage.status,
        "outputs": [artifact_slot_view(slot) for slot in stage.outputs],
        "gate_decisions": list(stage.gate_decisions),
        "reviewer_role": stage.reviewer_role,
        "findings_report": stage.findings_report,
    }


def course_view(
    course: Course,
    *,
    project_name: str = "",
    holding_session_id: UUID | None = None,
) -> dict[str, Any]:
    """A whole run: the rail, the artifacts, and what the current stage's checks say.

    One response rather than three endpoints, because the three are always
    rendered together and a rail that arrived before its artifacts would show
    every stage as empty for as long as the second request took -- which reads
    as a run that has produced nothing.

    `holding_session_id` is carried because an artifact is only readable
    through a session: the file viewer, its markdown rendering and its history
    all live there, and a course pane that grew its own reader would be a
    worse copy of one that already works. `None` says plainly that there is
    nothing to open the file in until somebody joins the project, which is a
    better answer than a link that 404s.
    """
    return {
        "project_name": project_name,
        "holding_session_id": str(holding_session_id) if holding_session_id else None,
        "preset": {
            "id": course.preset_id,
            "name": course.preset_name,
            "version": course.preset_version,
        },
        "position": course.position,
        "stage_count": course.stage_count,
        "stages": [stage_progress_view(stage) for stage in course.stages],
        "live_findings": [finding_view(finding) for finding in course.live_findings],
        "unimplemented_checks": list(course.unimplemented_checks),
    }


def project_view(
    project_id: UUID,
    name: str,
    *,
    active_session_id: UUID | None = None,
    tip_at_event: int = 0,
    workflow: dict[str, Any] | None = None,
    stage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One row of `/api/projects`: enough to list, join, and see who holds it.

    The holder is part of the row because it decides what the row can offer.
    A list that cannot see it has only one button to show -- join -- and no
    way to know that pressing it will fail, or that ending the holding
    session is what the user actually wants.

    `workflow` and `stage` are passed in rather than derived, because
    resolving a stage needs the preset and this module holds no registry --
    and a project can name a preset this build does not ship, which is the
    caller's problem to answer rather than a reason to fail a listing. Both
    are `None` for every project written before workflows existed.
    """
    return {
        "id": str(project_id),
        "name": name,
        "active_session_id": str(active_session_id) if active_session_id else None,
        "tip_at_event": tip_at_event,
        "workflow": workflow,
        "stage": stage,
    }


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
    events apart. `ProjectStageAdvanced` is what was reported, but `ProjectWorkflowSelected`
    turns the course page from a 409 into a rail and the lifecycle events move
    the holding-session link, so a frame per event class would be five frame
    types where the client wants one invalidation.

    Carries no stage. It would be `to_stage` off `ProjectStageAdvanced` and nothing at
    all off the other four, so a client would need the read anyway and would
    have two descriptions of the current stage that can disagree -- the same
    argument `corpus_change` makes about a document. The frame is a nudge;
    `/api/projects/{id}/course` stays the single answer to where the run is.

    **`decision` is the exception, and the distinction is worth being precise
    about.** It is not a description of current state, so it cannot disagree
    with the course read the way a stage name could -- it is a fact about the
    transition that just happened, and the course read does not report it at
    all. A tab told only that a stage advanced has to ask what happened; one
    told the reviewer chose `approve_with_edits` has been informed. That is the
    whole point of the field (#80), which added it because an audit of a driven
    run could otherwise say fifteen boundaries were crossed and nothing about
    how.

    Read through `getattr` with a `None` default rather than off the class,
    because this frame serves all six project events and only `ProjectStageAdvanced`
    has one. A client reads a null `decision` as "not that kind of change"
    rather than as a missing verdict. Nothing on the page renders it yet; it is
    on the frame so the live path does not have to be widened again the first
    time something wants it.
    """
    return {
        "type": "Project",
        "project_id": str(project_id),
        "change": type(event).__name__,
        "decision": getattr(event, "decision", None),
        "occurred_at": event.occurred_at.isoformat(),
    }


def _record_view(summary: SourceRecord) -> dict[str, Any]:
    """The fields every source view shares: everything the record itself knows.

    Split from `source_view` when `extracted` arrived, rather than letting
    `source_text_view` inherit it. Reading one document answers from the row
    and does not carry extraction state, so building on the full view would
    have meant `source_text_view` inventing a value for a field it cannot
    know -- and `False` there would read as "this has no graph" on a document
    that has one.

    `char_count` on a text record and `media_type`/`byte_count` on a media one
    -- discriminated on `kind` rather than `getattr(summary, "char_count",
    None)`. There is no type checker in CI or `pyproject.toml`, so nothing
    checks the cases are exhaustive at build time; what this form buys is the
    *runtime* failure being loud. A third `kind` added without a case here
    falls into the `else` and raises `AttributeError` on the first request
    that touches one -- where `getattr` with a default would have rendered
    `char_count: null` for it and shipped. A media row has no character count
    to report and a text row has no mimetype; putting one number under a name
    the other kind cannot give would read as data rather than as the absence
    it is. Covered by the pair of tests in `test_presenters.py`, each of which
    asserts the other kind's fields are *absent* rather than null.
    """
    fields: dict[str, Any] = {
        "source_id": summary.source_id,
        "kind": summary.kind,
        # The digest is what lets a caller prove a quote (or a download) came
        # from the bytes on record rather than from a source since revised.
        "sha256": summary.sha256,
        "uri": summary.uri,
        "title": summary.title,
        "published_at": summary.published_at,
        "note": summary.note,
        # Provenance for by-reference content the corpus did not create, not
        # a corpus fact -- see `TextRecord.fetched_at`. Exposed because
        # `revise` and `restore` both carry it through unconditionally, and a
        # console that could not read it back would have no way to show that
        # an edit had (or had not) disturbed it.
        "fetched_at": summary.fetched_at,
        # Null for a live document; set means excluded. Always present so a
        # caller can tell "not dropped" from "the field went missing".
        "dropped_reason": summary.dropped_reason,
    }
    if summary.kind == "media":
        fields["media_type"] = summary.media_type
        fields["byte_count"] = summary.byte_count
    else:
        fields["char_count"] = summary.char_count
        # Always present on a text row, `None`/`[]` for one nobody perceived.
        # Unconditional rather than emitted only for a transcript, because the
        # page's question is "was this derived, and what was missed" -- and a
        # key that appears only on derived rows would make "not derived" and
        # "an older server that did not send this" the same absence.
        fields["derived_from"] = summary.derived_from
        # A list, not the JSON string the event carries: the read model has
        # already decoded it (`_decode_degradations`), and re-encoding it here
        # would hand the browser a second thing to parse.
        fields["degradations"] = list(summary.degradations)
    return fields


def source_view(listing: SourceListing) -> dict[str, Any]:
    """One row of `/api/projects/{id}/sources`: what a source is, not what it says.

    No `text` key, and that absence is the contract rather than an oversight.
    A corpus can hold hundreds of papers; a listing that inlined even a
    snippet of each would cost more to render than reading the one document
    the caller actually wanted.

    Takes the listing rather than the record because `extracted` is not on the
    record and deliberately cannot be: extraction lives on another aggregate's
    stream. See `SourceListing`.
    """
    return {
        **_record_view(listing.record),
        # Whether this document's text has been folded into the graph. False
        # on every row of a database that predates the column until the corpus
        # projection is rebuilt -- see `CorpusDocumentRow.extracted_at` -- and
        # unconditionally False for media, which nothing extracts yet.
        "extracted": listing.extracted,
    }


def source_text_view(document: StoredDocument, span: Span) -> dict[str, Any]:
    """One source's text, with the offsets that make a quote from it checkable.

    `start` and `end` are read off `span` -- what was actually returned --
    rather than off the request, which is only a guess and may have asked for
    more than the document has. A citation built on requested offsets looks
    verifiable and is not, which is the failure this whole layer exists to
    prevent. `char_count` stays the whole document's, so a caller can tell a
    partial read from a complete one without a second request.
    """
    return {
        **_record_view(document.record),
        "text": span.text,
        "start": span.start,
        "end": span.end,
    }


def entity_view(entity: GraphEntity) -> dict[str, Any]:
    """One node, in the shape a graph browser draws: id, label, kind.

    `temporal` is passed through as the port already rendered it -- `None`
    for an entity with no extent, a string for one that has it -- rather
    than reshaped here, so there is one place, not two, that decides what a
    temporal edge is allowed to compare.

    `inferred` travels with every node, not only synthesised ones, for
    `relationship_view`'s reason: a client should never have to read an
    absent key as `false`. It matters more here than there, because it is not
    only a display flag -- a synthesised class node's id belongs to no stored
    entity, so a client that fetches `/neighborhood` or `/definition` on click
    must not fetch for one. See `GraphEntity.inferred`.
    """
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "inferred": entity.inferred,
        "temporal": entity.temporal,
    }


def relationship_view(relationship: GraphRelationship) -> dict[str, Any]:
    """One edge: the two ends a browser connects, and the label on the line.

    `inferred` and `derivation` travel with every edge, not only inferred
    ones, so a client never has to treat their absence as "false" -- see
    `GraphRelationship.derivation`'s docstring for why an inferred edge with
    no visible derivation would be indistinguishable from a stored one.
    """
    return {
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "relationship_type": relationship.relationship_type,
        "inferred": relationship.inferred,
        "derivation": relationship.derivation,
    }


def entity_page_view(page: EntityPage) -> dict[str, Any]:
    """One page of `/api/projects/{id}/graph/entities`.

    `next_after` is passed straight through -- `None` already means "no
    further page" on both `EntityPage` and the cursor contract the browser
    consumes it under, so there is no translation to do here.
    """
    return {
        "entities": [entity_view(entity) for entity in page.entities],
        "next_after": page.next_after,
    }


def graph_view(graph: Graph) -> dict[str, Any]:
    """A whole project graph, in the shape a browser draws it in one go.

    Flat `entities`/`relationships` with no root, unlike `neighborhood_view`:
    a whole graph has no entity the reader asked about, and inventing one to
    match the other response's shape would be inventing a fact. `truncated`
    is passed through rather than being left implicit in the entity count --
    a client cannot tell a complete graph of 500 from the first 500 of 900 by
    counting. `inferred_truncated` is the same guarantee for the inferred
    edges specifically: they are capped separately from the node limit (see
    `MAX_INFERRED_EDGES`), so a graph can be complete on `truncated` and still
    have dropped inferred edges.
    """
    return {
        "entities": [entity_view(entity) for entity in graph.entities],
        "relationships": [
            relationship_view(relationship) for relationship in graph.relationships
        ],
        "truncated": graph.truncated,
        "inferred_truncated": graph.inferred_truncated,
    }


def neighborhood_view(neighborhood: Neighborhood) -> dict[str, Any]:
    """A root plus what a graph browser can draw around it in one response.

    `root` is rendered through `entity_view` rather than repeated inline,
    the same reason `topic_detail_view` builds on `topic_view`: the root and
    an entry in `entities` describe a node the same way, and duplicating that
    shape here is a second place for it to drift.
    """
    return {
        "root": entity_view(neighborhood.root),
        "entities": [entity_view(entity) for entity in neighborhood.entities],
        "relationships": [
            relationship_view(relationship) for relationship in neighborhood.relationships
        ],
    }


def usages_view(usages: list[Usage]) -> dict[str, Any]:
    """`GET .../usages`, best matches first -- already the order `UsageReader`
    returns, so there is nothing to re-sort here.
    """
    return {
        "usages": [
            {
                "source_id": usage.source_id,
                "start": usage.start,
                "end": usage.end,
                "text": usage.text,
                "score": usage.score,
            }
            for usage in usages
        ]
    }


def definition_view(
    definition: Definition | None, served: list[ServedCitation] | None = None
) -> dict[str, Any]:
    """`GET .../definition`.

    `definition is None` renders as `text: None` with no citations, rather
    than the route raising a 404 -- see `read_graph_definition`'s docstring
    for why an undefinable entity is not a missing one. `model` and
    `generated_at` are `None` too in that case: there is no generation to
    report on, and a placeholder value here would read as though one had run.

    `served` is `definition.citations` run through `entity_definitions.
    serve_citations`, in the same order -- passed in rather than resolved
    here because this function is a pure presenter and resolving a citation's
    moment needs a corpus read (see `read_graph_definition`). `None` (the
    default) means the caller had no corpus read model to resolve against,
    which renders every citation's `at_seconds` as `None` -- indistinguishable
    from a source with no locator map, which is the correct behaviour for a
    build that cannot check: it is not this presenter's place to claim a
    moment it cannot verify.
    """
    if definition is None:
        return {
            "text": None,
            "citations": [],
            "model": None,
            "generated_at": None,
            "stale": False,
        }
    citations = (
        served
        if served is not None
        else [
            ServedCitation(source_id=c.source_id, start=c.start, end=c.end, at_seconds=None)
            for c in definition.citations
        ]
    )
    return {
        "text": definition.text,
        "citations": [
            {
                "source_id": citation.source_id,
                "start": citation.start,
                "end": citation.end,
                "at_seconds": citation.at_seconds,
            }
            for citation in citations
        ],
        "model": definition.model,
        "generated_at": definition.generated_at,
        "stale": definition.stale,
    }


def band_view(band: TimelineBand) -> dict[str, Any]:
    """One bar: what to draw, where to put it, and what the document said.

    `extent` and the `start`/`end` pair both travel, which looks redundant and
    is not -- see `TimelineBand.extent`. A browser given only the interval
    would label a bar "1815-01-01T00:00:00 - 1816-01-01T00:00:00" for a
    document that said "1815".

    `precision` and `uncertainty` travel on every band rather than only on
    uncertain ones, the same choice `relationship_view` makes with `inferred`:
    a client never has to read an absent field as a default it guessed at.
    """
    return {
        "entity_id": band.entity_id,
        "name": band.name,
        "entity_type": band.entity_type,
        "extent": band.extent,
        "start": band.start,
        "end": band.end,
        "precision": band.precision,
        "uncertainty": band.uncertainty,
    }


def timeline_view(timeline: Timeline) -> dict[str, Any]:
    """A project's dated entities in time order, and what is not in the drawing.

    `undated_count` is not decoration. Most entities in a real graph are not
    events, so a timeline is a view of a minority of the corpus by nature, and
    one showing forty bars with no denominator reads as "this project contains
    forty things". Same guarantee `truncated` gives on `graph_view`: data
    missing from a drawing is invisible precisely because it is missing.
    """
    return {
        "bands": [band_view(band) for band in timeline.bands],
        "undated_count": timeline.undated_count,
        "truncated": timeline.truncated,
    }


def topic_view(view: TopicView) -> dict[str, Any]:
    """One row of `/api/projects/{id}/topics`: what a queue entry ranks on.

    `needs_attention` and `is_blocked` are read off `view.attention` rather
    than left for the caller to derive from `triggers` -- a browser rendering
    a queue wants the verdict, not the raw findings, and `TopicAttention`
    already computed both from the same evaluation this row's triggers come
    from. Deriving them again client-side would risk disagreeing with the row
    that sits right next to them.
    """
    summary = view.summary
    return {
        "topic_id": str(summary.topic_id),
        "question": summary.question,
        "status": summary.status,
        "sources": summary.sources,
        "findings": summary.findings,
        "open_sub_questions": summary.open_sub_questions,
        "triggers": list(summary.triggers),
        "needs_attention": view.needs_attention,
        "is_blocked": view.attention.is_blocked,
    }


def topic_detail_view(detail: TopicDetail) -> dict[str, Any]:
    """One topic's own page: the row plus what a list would leave out.

    Built on `topic_view` rather than duplicating its fields, for the reason
    `source_text_view` builds on `source_view`: the row and the detail must
    describe the same topic the same way, and a single function computing the
    shared half is what keeps them from drifting apart as either grows.

    `detail.findings` -- the prose, one entry per recorded finding -- is
    exposed here as `finding_notes` rather than `findings`, because
    `topic_view` already spends `findings` on the *count* that both routes
    must agree on. Calling both of them `findings` would make the same key
    mean an int on one route and a list on the other, which is a collision a
    caller has no way to detect from the shape of a single response; the
    only way to keep the two spellings from drifting back together is to
    give them names that cannot collide in the first place.
    """
    return {
        **topic_view(detail.view),
        "rationale": detail.rationale,
        "scope": detail.scope,
        "sub_questions": [
            {
                "key": sub.key,
                "question": sub.question,
                "answer": sub.answer,
                "resolved": sub.resolved,
            }
            for sub in detail.sub_questions
        ],
        "source_ids": list(detail.source_ids),
        "finding_notes": list(detail.findings),
        "contested": detail.contested,
    }


def run_view(run: ActiveRun, state: ResearchRunState | None = None) -> dict[str, Any]:
    """One autonomous run: what it is, and -- if folded -- how it is going.

    Two arguments because the two halves come from different places and one of
    them is optional. The ids are process-local knowledge, available the
    instant a run starts; the counters are a fold of its stream, which the
    route that starts a run has no reason to pay for and the route that
    reports on one always does.

    `session_id` is here rather than left for the caller to look up because it
    is where the run's actual work is visible: the rounds are turns on that
    session, and a browser given only a run id would have nothing to open.
    """
    view: dict[str, Any] = {
        "run_id": str(run.run_id),
        "project_id": str(run.project_id),
        "session_id": str(run.session_id),
    }
    if state is None:
        return view
    return {
        **view,
        "status": state.status,
        "rounds": state.rounds,
        "turns": state.turns,
        "findings": state.findings,
        "stop_reason": state.stop_reason,
        # Named for what it is: a topic whose round began and has not ended,
        # which is the topic being worked right now.
        "working_on": str(state.in_flight_topic) if state.in_flight_topic else None,
        "quiet_rounds": state.consecutive_quiet_rounds,
        "failures": state.consecutive_failures,
        "budget": {
            "max_rounds": state.budget.max_rounds,
            "quiet_rounds": state.budget.quiet_rounds,
        },
        "read_only": state.read_only,
    }


def seeding_view(frame: dict[str, Any] | None) -> dict[str, Any] | None:
    """A `SeedingActivity` frame, passed through as-is.

    Unlike `run_view`, there is no folding to do: `SeedingActivity` already
    keeps its frames in the shape a browser wants, because nothing durable
    backs them for a presenter to reduce. This function exists anyway, for
    the same reason every other route reaches for `presenters.py` rather than
    building a dict inline -- the wire shape is decided in one place, not
    wherever a route happens to need it. `None` passes through unchanged: no
    run yet, or none finished, is a state this reports rather than an error.
    """
    return frame


def dispatch_view(frame: dict[str, Any] | None) -> dict[str, Any] | None:
    """A `DispatchQueue` frame, passed through as-is.

    Exists for `seeding_view`'s reason rather than because it transforms
    anything: the wire shape is decided in one place, not wherever a route
    happens to need it. That matters more here than for seeding, because the
    same frame goes out over three surfaces -- the 202, the catch-up read and
    the SSE channel -- and a browser reconciling a reconnect against a
    differently-shaped frame would render one dispatch two ways.

    `None` passes through unchanged: nothing running is a state this reports
    rather than an error.
    """
    return frame


def topic_documents_view(
    directory: str, files: dict[str, Any], state: ProjectState
) -> dict[str, Any]:
    """Everything written about one topic, and where to read it from.

    **The `session_id` is the reason this is not just a list of paths.** Every
    reader of a file in this API -- the raw route, the parsed route with its
    components, the attempt route that grades against it -- is keyed by
    `(session_id, path)`, and a dispatch writes on a session it creates and
    releases. Nothing on the research view knows which session that was. This
    resolves it once, so a viewer reuses those three routes unchanged instead
    of a fourth project-scoped copy of each growing beside them.

    `at` is the scrub point that goes with it, and the two must travel
    together. A project nobody is holding has its files at the *tip*, which is
    a position in a session that may have run on past it; reading that session
    at HEAD would show files the project does not have. `None` means HEAD and
    is correct only while a holder is live, because a holder's own uncommitted
    work is exactly what the tip does not yet know about -- the same two cases
    `project_files` resolves, reported rather than applied.

    Filtered on `directory + "/"` rather than `directory`: without the
    separator `/topics/0` would match `/topics/01-...` as well as
    `/topics/00-...`, and the numeric prefix is the only thing keeping two
    topics' documents apart.
    """
    prefix = f"{directory}/"
    documents = [
        {"path": path, "name": path[len(prefix) :]}
        for path in sorted(files)
        if path.startswith(prefix)
    ]
    if state.active_session_id is not None:
        session_id, at = state.active_session_id, None
    elif state.tip_session_id is not None and state.tip_at_event >= 1:
        session_id, at = state.tip_session_id, state.tip_at_event
    else:
        # A project that has never been joined has no stream to read from.
        # Reported as no session rather than an error: it is the same state as
        # "nothing has been dispatched here yet", which is the ordinary case.
        session_id, at = None, None
    return {
        "directory": directory,
        "session_id": str(session_id) if session_id else None,
        "at": at,
        "documents": documents,
    }


def worker_view(worker: Worker) -> dict[str, Any]:
    """One worker, in the browser's shape.

    `started_at` is ISO-8601 text rather than an epoch number, matching every
    other timestamp this layer emits.
    """
    return {
        "kind": worker.kind,
        "ref": worker.ref,
        "detail": worker.detail,
        "session_id": str(worker.session_id) if worker.session_id else None,
        "parent": worker.parent,
        "started_at": worker.started_at.isoformat() if worker.started_at else None,
    }


def roster_view(roster: Roster) -> dict[str, Any]:
    """Everything in flight on a project, plus who is attached and quiet."""
    return {
        "project_id": str(roster.project_id),
        "workers": [worker_view(worker) for worker in roster.workers],
        "idle_session_ids": [str(session) for session in roster.idle_session_ids],
    }


def autonomy_view(policy: AutonomyPolicy) -> dict[str, Any]:
    """Every gated tool's level, plus the two tool lists a client would
    otherwise have to hardcode.

    `gated` and `stage_gates` are sent because they are the only place the
    browser can learn them without copying `GATED_TOOLS` into JavaScript, and a
    copy drifts the moment a tool is added -- leaving a UI that offers no switch
    for a tool the server is gating, which reads to the user as a tool that
    cannot be relaxed rather than one nobody wired up. `levels` already covers
    every gated tool, but `gated` says so explicitly and `stage_gates` marks the
    subset that "allow all" deliberately leaves alone (see
    `AutonomyPolicy.relax_all`), so the UI can label that rather than look
    broken.
    """
    return {
        "levels": policy.levels(),
        "gated": list(GATED_TOOLS),
        "stage_gates": list(STAGE_GATE_TOOLS),
    }


def item_view(state: LearnerProgressState, path: str, component_id: str) -> dict[str, Any]:
    """One item's progress, or the zeroed shape for one nobody has touched.

    Never `None`. A client that has to branch on "no record yet" writes that
    branch once per renderer and gets it wrong in one of them; a zeroed record
    reads the same as an untouched one everywhere, which is what it is.
    """
    record = state.item(path, component_id)
    if record is None:
        return {
            "path": path,
            "component_id": component_id,
            "attempts": 0,
            "correct": False,
            "best_score": 0.0,
            "last_score": 0.0,
            "checked": [],
        }
    return {
        "path": record.path,
        "component_id": record.component_id,
        "attempts": record.attempts,
        "correct": record.correct,
        "best_score": record.best_score,
        "last_score": record.last_score,
        "checked": list(record.checked),
    }


def progress_view(state: LearnerProgressState, path: str | None = None) -> dict[str, Any]:
    """Everything this learner has done, optionally narrowed to one file.

    Keyed by component id when narrowed to a path, because that is what a
    renderer holds and it saves every call site re-deriving the composite key.
    Unnarrowed, the key has to carry the path too -- ids are only unique within
    a document -- so the two shapes differ deliberately rather than by neglect,
    and `scope` says which one this is.
    """
    records = [
        record for record in state.items.values() if path is None or record.path == path
    ]
    if path is not None:
        return {
            "scope": "file",
            "path": path,
            "items": {
                record.component_id: item_view(state, record.path, record.component_id)
                for record in records
            },
        }
    return {
        "scope": "session",
        "path": None,
        "items": {
            f"{record.path}#{record.component_id}": item_view(
                state, record.path, record.component_id
            )
            for record in records
        },
    }
