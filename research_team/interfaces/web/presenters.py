"""Domain objects rendered as the JSON the browser consumes.

The web equivalent of the CLI's formatters: pure functions, no I/O, and the
only place that knows the wire shape. Keeping them here means the API can be
reshaped for the UI without anything below noticing.
"""

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
from research_team.application.corpus_read import StoredDocument
from research_team.application.corpus_spans import Span
from research_team.application.course import (
    ArtifactSlot,
    Course,
    ProvenanceSummary,
    StageProgress,
)
from research_team.application.findings import Finding
from research_team.application.graph_read import (
    EntityPage,
    Graph,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.application.research_supervisor import ActiveRun
from research_team.application.topic_read import TopicDetail, TopicView
from research_team.domain import (
    AutonomyChanged,
    CodingSession,
    ConversationCompacted,
    DocumentRecord,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    StageAdvanced,
    TurnFailed,
    WorkflowSelected,
)
from research_team.domain.auto_research import AutoRunState
from research_team.domain.learner import LearnerProgressState
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
    if isinstance(event, WorkflowSelected):
        return f"{event.preset_id} v{event.preset_version}"
    if isinstance(event, StageAdvanced):
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
            return "→ " + ", ".join(call.get("name", "?") for call in calls)
        return " ".join(str(data.get("content", "")).split())[:120]
    return ""


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
    session: CodingSession,
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
    return {
        "id": str(summary.session_id),
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


def source_view(summary: DocumentRecord) -> dict[str, Any]:
    """One row of `/api/projects/{id}/sources`: what a source is, not what it says.

    No `text` key, and that absence is the contract rather than an oversight.
    A corpus can hold hundreds of papers; a listing that inlined even a
    snippet of each would cost more to render than reading the one document
    the caller actually wanted.
    """
    return {
        "source_id": summary.source_id,
        "char_count": summary.char_count,
        # The digest is what lets a caller prove a quote came from the bytes
        # on record rather than from a document that has since been revised.
        "sha256": summary.sha256,
        "uri": summary.uri,
        "title": summary.title,
        "published_at": summary.published_at,
        "note": summary.note,
        # Null for a live document; set means excluded. Always present so a
        # caller can tell "not dropped" from "the field went missing".
        "dropped_reason": summary.dropped_reason,
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
        **source_view(document.record),
        "text": span.text,
        "start": span.start,
        "end": span.end,
    }


def entity_view(entity: GraphEntity) -> dict[str, Any]:
    """One node, in the shape a graph browser draws: id, label, kind."""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "entity_type": entity.entity_type,
    }


def relationship_view(relationship: GraphRelationship) -> dict[str, Any]:
    """One edge: the two ends a browser connects, and the label on the line."""
    return {
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "relationship_type": relationship.relationship_type,
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
    counting.
    """
    return {
        "entities": [entity_view(entity) for entity in graph.entities],
        "relationships": [
            relationship_view(relationship) for relationship in graph.relationships
        ],
        "truncated": graph.truncated,
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


def run_view(run: ActiveRun, state: AutoRunState | None = None) -> dict[str, Any]:
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
