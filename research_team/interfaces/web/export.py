"""Getting work out of the system, as files somebody can send to a friend.

Two exports that had no route at all before this module: the authored course
as an archive, and the knowledge graph as a drawing plus its machine-readable
forms. Both are *downloads* rather than JSON APIs -- what leaves here is
meant to be saved, mailed and opened somewhere this server is not running,
which is why every route sets `Content-Disposition` and none of them returns
a body a browser would render in place.

**Its own module, and it registers a router rather than adding to `app.py`.**
`create_app` is five thousand lines of closures over a few dozen optional
collaborators, and two more features inside it would be four hundred lines
nobody can find. The cost of the split is the small dependency record below:
these routes need three of `create_app`'s *closures* -- not just its
parameters -- because `_require_project`, `_graph_reader` and the curriculum
read each already encode what a 404 and a 503 mean here, and re-deriving them
would be two implementations free to disagree about whether an unwired graph
store is a missing project.
"""

import io
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

#: Where the authoring turns write, and the third copy of these two strings --
#: `course_authoring.AREAS_DIR`/`PATHS_DIR` on the server and
#: `frontend/src/presentation/curriculum/course-paths.ts` in the console.
#: Imported from the first rather than repeated, because unlike the console
#: this module *can* import it: they are in the same process, and a rename
#: that missed here would produce an empty archive rather than a dead link.
from research_team.application.course_authoring import AREAS_DIR, PATHS_DIR
from research_team.application.curriculum import Curriculum
from research_team.application.graph_export import (
    MAX_EXPORT_NODES,
    build_export,
    to_graphml,
    to_json,
)
from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    GraphReadPort,
)
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.graph_html import render_html


@dataclass(frozen=True)
class ExportDeps:
    """What the export routes need from `create_app`'s closure.

    A record rather than a long parameter list, so adding a fourth thing does
    not re-order anybody's call. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    #: `service.load` and `service.project_state`, narrowed to the two calls
    #: this module makes. Typed as `Any` because `SessionService` lives behind
    #: an application-layer import `app.py` already has and re-declaring its
    #: shape here would be a second protocol for one collaborator.
    service: Any
    require_project: Callable[[UUID], Awaitable[Any]]
    graph_reader: Callable[[UUID], Awaitable[GraphReadPort]]
    curriculum_of: Callable[[UUID], Awaitable[Curriculum]]
    authoring: AuthoringActivity | None


def export_router(deps: ExportDeps) -> APIRouter:
    """The `/export` routes, ready for `app.include_router`."""
    router = APIRouter()

    # ---- A. the authored course -------------------------------------------

    @router.get("/api/projects/{project_id}/export/course")
    async def export_course(project_id: UUID, area: str | None = None):
        """Every file the last settled authoring run wrote, as one zip.

        **The rule is that a partial archive must never look complete.** It is
        not that a partial archive must never exist -- that was the earlier
        reading, and it was only ever right by accident: back when the
        area-to-session mapping lived in process memory, the partial cases were
        unreachable anyway, so refusing them cost nothing. Since #242 the
        mapping is a table, those runs come back with their session ids intact,
        and refusing them would mean recovering the work and then declining to
        hand it over.

        So `done`, `failed`, `cancelled` and `interrupted` all export, and each
        archive says which it is -- in a README naming what completed, what
        failed and what was never started, and in the filename for every
        non-`done` run, which is the only place a reader sees it before opening
        anything. `_run_of` and `_course_readme` hold the argument in full.

        **409 while a run is in flight**, and that one is unchanged. A run that
        is moving would give a different archive a second later, so there is no
        snapshot to describe accurately -- which is the difference between it
        and a settled partial run, where there is.
        """
        await deps.require_project(project_id)
        run = await _run_of(project_id, deps.authoring)

        links = _course_links(run)
        if area is not None:
            links = [pair for pair in links if pair[0] == area]
            if not links:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"no authored course for {area!r} in the last run; "
                        f"it wrote {_wrote(run)}"
                    ),
                )

        state = await deps.service.project_state(project_id)
        name = state.name or str(project_id)

        buffer = io.BytesIO()
        written = 0
        # `ZIP_DEFLATED`: the payload is markdown, which compresses to roughly
        # a fifth. The archive is going in an email.
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for target, session_id in links:
                session = await deps.service.load(UUID(session_id))
                # A run's targets are area slugs plus, last, the path's own
                # slug, and nothing on the frame says which is which -- so the
                # workspace is asked rather than the slug parsed. See
                # `_is_path_file`.
                prefix = (
                    f"{PATHS_DIR}/{target}.md"
                    if _is_path_file(session, target)
                    else f"{AREAS_DIR}/{target}/"
                )
                for path, entry in sorted(session.state.files.items()):
                    if not path.startswith(prefix):
                        continue
                    # Rooted under the project's name so an archive unzipped
                    # beside another does not merge into it. `/course` is
                    # dropped from the stored path: it is a workspace
                    # convention, and a reader opening the zip wants
                    # `areas/roman-law/unit.md`, not a directory that only
                    # means something inside this system.
                    inside = path.removeprefix("/course/")
                    archive.writestr(f"{_safe(name)}/{inside}", entry.get("content", ""))
                    written += 1
            archive.writestr(
                f"{_safe(name)}/README.md", _course_readme(name, project_id, run, area)
            )

        if written == 0:
            # Distinguished from the 409 above: the run is known and it wrote
            # nothing this archive could carry. A zip holding only a README
            # reads as a feature that ran and produced an empty course.
            # The status is named, because "wrote nothing" reads as a defect
            # for a `done` run and as an explanation for an interrupted one --
            # and the reader cannot tell which without being told.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"the last authoring run ({run.get('status')}) wrote no course "
                    f"files to export"
                ),
            )

        stem = _safe(name) if area is None else f"{_safe(name)}-{_safe(area)}"
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={
                "content-disposition": (
                    f'attachment; filename="{stem}-course{_status_suffix(run)}.zip"'
                )
            },
        )

    # ---- B. the graph ------------------------------------------------------

    @router.get("/api/projects/{project_id}/export/graph")
    async def export_graph(
        project_id: UUID,
        format: Literal["html", "json", "graphml"] = "html",
        scope: Literal["project", "area", "entity"] = "project",
        area: str | None = None,
        entity: str | None = None,
        depth: int = 1,
        limit: int = Query(default=MAX_EXPORT_NODES, le=MAX_GRAPH_NODES),
    ):
        """The graph, or a cut of it, as a file.

        **Produced here rather than in the browser**, from the graph the log
        already folds to. The console has settled positions on screen and
        capturing them would be free, and it was rejected because it makes the
        export a property of an open tab: nothing scriptable, nothing without
        a console, and nothing for the two thirds of this feature (JSON and
        GraphML) that have no reason to involve a browser at all. What it
        costs is `graph_layout` -- a force-directed pass in numpy, which is
        seconds rather than milliseconds; see `MAX_EXPORT_NODES`.

        `format` and `scope` are `Literal`s, so a typo is a 422 naming the
        allowed values rather than a silent fallback to the default. An
        export that quietly handed back the whole project when asked for one
        area is the failure worth a hard edge here: the file looks right and
        is about the wrong thing.
        """
        await deps.require_project(project_id)
        reader = await deps.graph_reader(project_id)

        if scope == "area":
            if area is None:
                raise HTTPException(status_code=422, detail="scope=area needs an `area` slug")
            entities, relationships, title, truncated = await _area_cut(
                deps, project_id, reader, area
            )
        elif scope == "entity":
            if entity is None:
                raise HTTPException(
                    status_code=422, detail="scope=entity needs an `entity` id"
                )
            if depth > MAX_NEIGHBORHOOD_DEPTH:
                raise HTTPException(
                    status_code=422,
                    detail=f"depth {depth} exceeds the maximum of {MAX_NEIGHBORHOOD_DEPTH}",
                )
            hood = await reader.neighborhood(entity, depth=depth)
            if hood is None:
                raise HTTPException(
                    status_code=404, detail=f"no such entity in project {project_id}"
                )
            # The root is not in `hood.entities` -- see `Neighborhood` -- and
            # an export that dropped the entity it is named after would be a
            # drawing of everything around a hole.
            entities = (hood.root, *hood.entities)
            relationships = hood.relationships
            title = f"{hood.root.name} — {depth} hop{'s' if depth != 1 else ''}"
            truncated = False
        else:
            whole = await reader.whole(limit=MAX_GRAPH_NODES)
            entities, relationships = whole.entities, whole.relationships
            state = await deps.service.project_state(project_id)
            title = state.name or str(project_id)
            truncated = whole.truncated

        graph = build_export(
            entities,
            relationships,
            title=title,
            scope=scope if area is None else f"{scope}: {area}",
            limit=limit,
            truncated=truncated,
        )

        body, media, suffix = (
            (render_html(graph), "text/html; charset=utf-8", "html")
            if format == "html"
            else (to_json(graph), "application/json", "json")
            if format == "json"
            else (to_graphml(graph), "application/xml", "graphml")
        )
        return Response(
            content=body,
            media_type=media,
            # `attachment` even for the HTML. Served inline it would render in
            # the console's own tab, which is a page that looks like part of
            # the app and is not -- and the whole point is a file on disk that
            # can be attached to a mail.
            headers={
                "content-disposition": f'attachment; filename="{_safe(title)}-graph.{suffix}"'
            },
        )

    return router


async def _area_cut(
    deps: ExportDeps, project_id: UUID, reader: GraphReadPort, area: str
) -> tuple[tuple, tuple, str, bool]:
    """One learning area's members, and the edges among them.

    The membership comes from the curriculum projection and the *edges* come
    from the graph, filtered to that membership -- rather than from the
    projection, which holds prerequisite edges between areas and nothing
    inside one. Drawing an area with the area-level edges would be a picture
    of a single node.
    """
    built = await deps.curriculum_of(project_id)
    found = built.area(area)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no learning area {area!r}")

    members = {member.entity_id for member in found.anchors}
    whole = await reader.whole(limit=MAX_GRAPH_NODES)
    entities = tuple(e for e in whole.entities if e.entity_id in members)
    relationships = tuple(
        r for r in whole.relationships if r.source_id in members and r.target_id in members
    )
    # A member the whole-graph read did not return is a member this drawing
    # cannot place. It happens when the graph is above `MAX_GRAPH_NODES` and
    # the cap dropped part of the area, which is exactly the case a reader
    # must not mistake for a small area.
    return entities, relationships, found.display_name(), len(entities) < len(members)


async def _run_of(project_id: UUID, authoring: AuthoringActivity | None) -> dict:
    """The most recent settled authoring run, or a 409 saying why there is none.

    **Only two refusals now, and the one that went away is the interesting
    one.** The build having no authoring wired is a 503; a run *in flight* is a
    409, because it is moving and a snapshot of it would be a different archive
    a second later. Everything else exports.

    **A settled run is exported whatever it settled as** -- `done`, `failed`,
    `cancelled` or `interrupted`. Their courses are real files, their session
    ids are durable since #242, and the run's status is a fact about the run
    rather than a verdict on the work. `cancelled` is a person who *knows* the
    run is partial and stopped it deliberately, and refusing them their own
    courses would be patronising; `interrupted` is the case durability was
    built for, and refusing it would mean the feature recovered the mapping and
    then declined to use it.

    What the route docstring forbids is a partial archive that *looks*
    complete, and the answer to that is saying so rather than withholding:
    every archive carries a README stating the status, what completed, what
    failed and what was never started, and every non-`done` export names its
    status in the filename. See `_course_readme` and `_status_suffix`.

    Nothing here branches on the status vocabulary, deliberately. A fifth
    settled status added later exports like the other four and is described
    accurately by a README built from `targets`/`completed`/`failures` rather
    than from a table of known names.
    """
    if authoring is None:
        raise HTTPException(status_code=503, detail="course authoring is not configured")
    if authoring.active(project_id) is not None:
        raise HTTPException(
            status_code=409,
            detail="an authoring run is in flight; wait for it to finish and export then",
        )
    run = await authoring.last(project_id)
    if run is None:
        # No longer "the mapping was lost on restart" -- since #242 the mapping
        # is a table, and its silence means what silence usually means. A
        # message still blaming a restart would send somebody looking for a
        # server problem behind a project nobody has authored yet.
        raise HTTPException(
            status_code=409,
            detail=(
                "no authoring run has ever been recorded for this project. "
                "Write the courses first, then export them."
            ),
        )
    return run


def _status_suffix(run: dict) -> str:
    """`-interrupted`, `-cancelled`, `-failed`, or nothing for a completed run.

    **In the filename, because that is the only place the status is visible
    before anything is opened.** A README says it too, and a README is one
    unzip and one click away -- by which point the archive has already been
    saved, forwarded, or dropped into a folder next to two complete ones. The
    download bar, the mail attachment and the directory listing all show the
    name, and this is the version of "it says so" that reaches somebody who
    never opens it.

    What it costs: a filename is the one part a person can rename, so it is not
    sufficient on its own. That is why it is *both*, not either.

    Empty for `done` rather than `-done`: an ordinary export should not carry a
    qualifier, or the qualifiers stop reading as warnings.
    """
    status = str(run.get("status") or "")
    return "" if status in ("", "done") else f"-{_safe(status)}"


def _course_links(run: dict) -> list[tuple[str, str]]:
    """`completed` zipped with `sessions`, dropping any pair that does not match.

    The same refusal `courseLinks` makes in the console, for the same reason:
    a target paired with the wrong run's session names a real file about
    something else, and nobody would suspect it.
    """
    completed = run.get("completed") or []
    sessions = run.get("sessions") or []
    return [(target, sessions[i]) for i, target in enumerate(completed) if i < len(sessions)]


def _wrote(run: dict) -> str:
    """What the run's targets were, for a 404 that tells the caller what to ask
    for instead. `'nothing'` rather than an empty string: a message ending in
    "it wrote " reads as a bug in the message."""
    return ", ".join(target for target, _ in _course_links(run)) or "nothing"


def _is_path_file(session: Any, target: str) -> bool:
    """Whether this run's target wrote the path overview rather than an area.

    Asked of the workspace rather than inferred from the slug. A run's targets
    are area slugs plus, last, the path's own slug -- and nothing on the frame
    marks which is which, so the only honest test is whether the file exists.
    """
    return f"{PATHS_DIR}/{target}.md" in session.state.files


#: What each settled status means, in a sentence somebody who has never read
#: this code can act on. A lookup rather than prose built by branching, so the
#: README builder itself stays status-blind -- an unknown status falls back to
#: the generic line below instead of rendering a paragraph that is wrong.
_STATUS_SENTENCE = {
    "done": "This run finished. Every target below that is not listed as failed was written.",
    "failed": (
        "This run failed: every target it attempted broke. Anything under `areas/` "
        "is what survived, and the failures are listed below."
    ),
    "cancelled": (
        "**This run was cancelled part-way through.** Somebody stopped it deliberately, "
        "so the targets under *Never started* were abandoned rather than attempted. "
        "What is here is complete in itself; the course as a whole is not."
    ),
    "interrupted": (
        "**This run was interrupted -- the server stopped while it was still writing.** "
        "The targets under *Never started* were never reached. What is here was fully "
        "written before the interruption and is safe to read; the course as a whole is "
        "not finished."
    ),
}


def _never_started(run: dict) -> list[str]:
    """Targets the run neither wrote nor failed at.

    Computed from the three lists rather than from the status, so a cancelled
    run, an interrupted one and any status added later all describe themselves
    correctly. Empty for an ordinary completed run, which is what keeps the
    section out of the archives that do not need it.
    """
    accounted = {target for target, _ in _course_links(run)}
    accounted |= {failure["target"] for failure in (run.get("failures") or [])}
    return [target for target in (run.get("targets") or []) if target not in accounted]


def _course_readme(name: str, project_id: UUID, run: dict, area: str | None) -> str:
    """What this archive is, written into it.

    A zip of markdown with no provenance is one somebody deletes rather than
    asks about six months from now. It names the failures too: a run that
    wrote seven of eight areas is reported `done`, and an archive that carried
    seven courses and said nothing would hide the eighth.

    **Since the route began exporting unsettled-looking runs, this file is
    load-bearing rather than courteous.** A `cancelled` or `interrupted` run
    produces an archive that is genuinely partial, and the whole argument for
    handing it over rather than refusing it is that it says so -- here, and in
    the filename. If this section is ever dropped, the route goes back to
    producing the "silently partial" archive its own docstring forbids.
    """
    status = str(run.get("status") or "unknown")
    lines = [
        f"# {name} — course export",
        "",
        f"Exported {datetime.now(UTC).isoformat(timespec='seconds')}"
        f" from project `{project_id}`.",
        f"Authoring run `{run.get('run_id')}` ({run.get('kind')}), status `{status}`.",
        "",
        _STATUS_SENTENCE.get(
            status,
            f"This run settled as `{status}`. Compare the lists below against "
            f"what you expected before relying on this archive as complete.",
        ),
        "",
        "Understanding by Design units under `areas/`, one directory per learning",
        "area, each with a `unit.md` and its lessons. The path overview, if this",
        "run wrote one, is under `paths/`.",
        "",
    ]
    if area is not None:
        lines += [f"This archive holds **one area only**: `{area}`.", ""]
    completed = [target for target, _ in _course_links(run)]
    if completed:
        # Listed rather than counted. "7 of 9 written" tells a reader the
        # archive is short and not which two to go and write.
        lines += ["## Written", ""]
        lines += [f"- `{target}`" for target in completed]
        lines += [""]
    never = _never_started(run)
    if never:
        lines += ["## Never started", ""]
        lines += [f"- `{target}`" for target in never]
        lines += [""]
    failures = run.get("failures") or []
    if failures:
        lines += ["## Not written", ""]
        lines += [f"- `{f['target']}`: {f['detail']}" for f in failures]
        lines += [""]
    return "\n".join(lines)


#: Anything that is not a plain filename character. Applied to project names
#: and area titles before they reach a `Content-Disposition` header or a path
#: inside a zip -- both of which are places a model-written or user-written
#: string with a quote, a slash or a newline in it does something other than
#: name a file.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(value: str) -> str:
    cleaned = _UNSAFE.sub("-", value).strip("-.")
    # A name that was entirely punctuation, or entirely non-ASCII, reduces to
    # nothing -- and `filename=""` is a header a browser saves as `download`.
    return cleaned[:80] or "export"
