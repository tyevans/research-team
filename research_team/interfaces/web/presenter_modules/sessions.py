"""Session, project, and file history presenters for the web interface."""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent

from research_team.application import ForkNode, SessionSummary
from research_team.application.tenancy.project_summaries import ProjectSummary
from research_team.domain import FileEdited, ProjectState, Session
from research_team.interfaces.web.presenter_modules.events import (
    FILE_EVENTS,
    _revision_counts,
    message_view,
)


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


def reading_head(state: ProjectState) -> UUID | None:
    """Which session to read this project's files through, right now.

    **This is not the holder, and the difference is the whole point.**
    *Holding* is about where the next write goes; *reading the head state* has
    an answer whether or not anybody is holding, and the console spent a long
    time conflating the two -- a project between sessions showed no files, no
    workspace and no documents, because the only session id on the wire was
    `active_session_id` and it was `null`.

    A holder is asked first because it has work the tip does not yet know
    about: the tip only advances on release. With nobody holding it, the tip
    *session* is the truth -- the same two cases `SessionService.project_files`
    resolves, reported rather than applied, so a client folds files out of the
    same stream the server folded them from.

    **The point to read at is HEAD, always, and it is deliberately not
    returned.** This resolution used to hand back a pair, `(session_id, at)`,
    with `at = state.tip_at_event` whenever nobody held the project. Measured
    2026-08-27 (see `topic_documents_view`, which carries the reproduction):
    that offset made one response contradict itself, listing a file written
    after a release and then 404ing it through the very reader route the
    offset was sent to feed. The tip offset is never a statement about what a
    project *has* -- it is a fork point (`ProjectSessionJoined.inherited_at`),
    which is a different question, and `_catch_up_tip` exists to drag it
    forward precisely because work past it is a bug rather than a boundary.
    So this returns a session and nothing else, and a caller that wants a
    scrub point uses HEAD.

    `None` for a project that has never been joined. That is a real state, not
    an error: it reads as "nothing has been written here yet", which is also
    the state in which there are no files to ask about.

    **`tip_at_event` is deliberately not read here.** It is stale between a
    release and the next join -- `_catch_up_tip` only runs on join -- and any
    reader of it inherits that. This is the resolution every surface shares,
    so it is the one place that must not become that reader.
    """
    if state.active_session_id is not None:
        return state.active_session_id
    if state.tip_session_id is not None and state.tip_at_event >= 1:
        return state.tip_session_id
    return None


def project_detail_view(
    project_id: UUID,
    name: str,
    *,
    active_session_id: UUID | None = None,
    tip_at_event: int = 0,
    reading_head_session_id: UUID | None = None,
) -> dict[str, Any]:
    """One project, as `GET /api/projects/{id}` answers it.

    Identity, holder, and the reading head. It exists because the only
    single-project read this API had was `/course` -- so four surfaces that
    wanted a project's name were reading a workflow run's progress to get one.
    That route is gone now; this is what they read instead.

    **`reading_head_session_id` is the column the detail has and the listing
    does not**, and it is why `project_view` below is a function again rather
    than the alias it was for two slices. The alias's own docstring named this
    day: "the day a listing earns a column a detail does not is the day this
    becomes a function again". It happened in the other direction, which
    changes nothing about the shape.

    The listing does not carry it because `GET /api/projects` folds one
    aggregate per row already, and `domain/project/landing.ts` defers a
    feature on exactly that cost. The reading head is what a project *page*
    needs -- a session to read files, documents and a workspace through -- and
    a page is reached one at a time.

    It is a session id and no offset: see `reading_head`, which carries the
    measurement that settled the offset to HEAD in every branch.
    """
    return {
        "id": str(project_id),
        "name": name,
        "active_session_id": str(active_session_id) if active_session_id else None,
        "tip_at_event": tip_at_event,
        "reading_head_session_id": (
            str(reading_head_session_id) if reading_head_session_id else None
        ),
    }


def project_view(
    project_id: UUID,
    name: str,
    *,
    active_session_id: UUID | None = None,
    tip_at_event: int = 0,
    summary: ProjectSummary | None = None,
) -> dict[str, Any]:
    """One row of `/api/projects`: enough to list, join, and see who holds it.

    **`summary` is the column the listing has and the detail does not**, which
    inverts the split this function's own history is about: it was folded into
    `project_detail_view` when the detail grew `reading_head_session_id`, and
    it comes apart the other way now. The asymmetry is the same shape both
    times — a field belongs on the route that has a reader for it. A project
    *page* has the project in front of it and needs no summary of itself; an
    index has six rows and nothing else to tell them apart.

    It defaults to `None` rather than being required so that the two callers
    that mint a row for a project which cannot yet have any history — the
    create endpoint, and the tests that build one by hand — do not have to
    manufacture an empty summary to say "nothing". `project_summary_view`
    turns that into zeros; see its docstring for why the zeros are written
    there and not in the reader.

    The holder is part of the row because it decides what the row can offer. A
    list that cannot see it has only one button to show -- join -- and no way
    to know that pressing it will fail, or that ending the holding session is
    what the user actually wants.

    **A function again, not the alias it was.** The two answers came apart the
    moment the detail grew a reading head, and the cost of keeping them one
    was the wrong one to pay: it is a field a listing has no reader for, on
    the one route that folds an aggregate per row.

    Delegates rather than repeating the dict, so a field added for both still
    cannot reach one route and miss the other -- the property the alias was
    protecting, kept without the column it forced.
    """
    row = project_detail_view(
        project_id,
        name,
        active_session_id=active_session_id,
        tip_at_event=tip_at_event,
    )
    del row["reading_head_session_id"]
    row["summary"] = project_summary_view(summary)
    return row


def project_summary_view(summary: ProjectSummary | None) -> dict[str, Any]:
    """A project's pipeline position, as a listing row carries it.

    **The zeros are supplied here rather than by the reader**, which is the
    one decision in this function. `ProjectSummaries.all` answers only the
    projects that have something to summarise, so a project created a minute
    ago is simply absent from it — and `None` here means exactly that. Filling
    it with zeros is correct *for a listing* and would be wrong for a caller
    that needed to tell "nothing yet" from "not measured"; putting the fill
    in the presenter keeps that judgement in the one place the response shape
    is decided, instead of hiding it in a SQL adapter three layers down.

    Always present on the row, never omitted when empty. An optional object
    would make every consumer write the same `?? 0` fallback, and the console
    has shipped a silently-absent field read as a zero before.
    """
    if summary is None:
        return {
            "topics": 0,
            "topics_open": 0,
            "sources": 0,
            "extracted": 0,
            "courses": 0,
            "sessions": 0,
            "last_activity": None,
        }
    return {
        "topics": summary.topics,
        "topics_open": summary.topics_open,
        "sources": summary.sources,
        "extracted": summary.extracted,
        "courses": summary.courses,
        "sessions": summary.sessions,
        "last_activity": summary.last_activity,
    }
