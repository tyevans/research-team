"""Topic, worker, and autonomy presenters for the web interface."""

from typing import Any

from research_team.application import (
    GATED_TOOLS,
    AutonomyPolicy,
    Roster,
    Worker,
)
from research_team.application.research.topic_read import TopicDetail, TopicView
from research_team.domain import ProjectState
from research_team.interfaces.web.presenter_modules.sessions import reading_head


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


def seeding_view(frame: dict[str, Any] | None) -> dict[str, Any] | None:
    """A `SeedingActivity` frame, passed through as-is.

    There is no folding to do: `SeedingActivity` already keeps its frames in
    the shape a browser wants, because nothing durable backs them for a
    presenter to reduce. This function exists anyway, for
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

    **The resolution itself is `reading_head`, not written here.** It was
    written here first, and this was the only surface that needed it; the
    project detail needs the same answer now, and two surfaces computing it
    separately is two answers that will eventually disagree about which
    session was newer -- which is the argument `project_files` already makes
    one layer down.

    **There is no `at` on this response, and its absence is not an
    oversight.** It used to be `state.tip_at_event` whenever nobody held the
    project, on the argument that a released session may have run on past the
    tip and reading it at HEAD "would show files the project does not have".
    That argument is wrong, and it made this one response contradict itself:
    the
    `documents` list is built from `project_files`, which folds the tip
    session to HEAD deliberately (see its docstring, and
    `test_the_project_shows_files_written_after_its_release`), so a file
    written after a release was listed here and then 404'd by the very reader
    routes this `at` is sent to feed.

    Measured 2026-08-27, against `~/.research-team/sessions.db` copied through
    `infrastructure.persistence.local_copy`, and reproduced synthetically
    because the real data cannot separate the two: every live project in that
    database had `tip_at_event` exactly equal to its tip session's stream
    length, because `_catch_up_tip` runs on every join. The one project whose
    tip session had run on past its release -- a deleted "One Piece",
    `cd7c1b44`, tip at 4 of 5 -- ran on by a single `TurnFailed`, which
    touches no file. The synthetic case, one `write_file` after
    `release_project`: HEAD listed `/topics/00-a/after.md` and
    `/topics/00-a/before.md`, the offset listed only `/topics/00-a/before.md`,
    and this view reported both documents alongside `at: 7` -- a scrub point
    at which the first of them does not exist.

    The criterion that settles it is the domain's, not this layer's:
    `session_service._catch_up_tip` exists precisely to move a stale tip
    forward to `len(history)`, and its docstring calls work stranded past a
    release "unreachable from the project the moment they were written" -- a
    bug, not a boundary. So the offset below HEAD is never a decision about
    what the project has; it is a pointer the next join will move. Its real
    job is as a *fork point* (`ProjectSessionJoined.inherited_at`,
    `_fork_files_from`), which is a different question.

    The key was kept for one slice, `null` in every branch, because the
    client's DTO already accepted `null` and mapped it to HEAD. It is gone
    now, on both sides: a field that carries no information is a field the
    next reader has to work out is constant, and `ScrubPoint.head()` says the
    same thing at the point of use without a round trip to say it.

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
    session_id = reading_head(state)
    return {
        "directory": directory,
        "session_id": str(session_id) if session_id else None,
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
    """Every gated tool's level, plus the tool list a client would otherwise
    have to hardcode.

    `gated` is sent because it is the only place the browser can learn it
    without copying `GATED_TOOLS` into JavaScript, and a copy drifts the moment
    a tool is added -- leaving a UI that offers no switch for a tool the server
    is gating, which reads to the user as a tool that cannot be relaxed rather
    than one nobody wired up. `levels` already covers every gated tool, but
    `gated` says so explicitly.

    `stage_gates` was a third key marking the subset "allow all" left alone.
    It named exactly one tool, `advance_stage`, which the workflow removal
    deleted -- so the key had nothing left to name, and the console had
    stopped reading it. Removed rather than left to answer an empty list,
    which would read as a subset that happens to be empty rather than one that
    no longer exists.
    """
    return {
        "levels": policy.levels(),
        "gated": list(GATED_TOOLS),
    }
