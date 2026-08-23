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

from fastapi import APIRouter, HTTPException, Query, Request, Response

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
from research_team.interfaces.web.course_html import (
    CourseArea,
    CourseReads,
    build_course_book,
    read_course_file,
    render_course_html,
)
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

    #: The three further reads `format=html` needs, and only it. All three
    #: default to `None` so every existing construction of this record --
    #: including the fixtures in `tests/interfaces/` -- keeps working and
    #: exports a course whose resolved widgets render named absences. That is
    #: the honest degradation: a build with no corpus genuinely cannot quote a
    #: passage, and a zip export never could either.
    corpus_reader: Callable[[UUID], Any] | None = None
    definitions: Callable[[UUID], Awaitable[Any]] | None = None
    timeline_reader: Callable[[UUID], Awaitable[Any]] | None = None


def export_router(deps: ExportDeps) -> APIRouter:
    """The `/export` routes, ready for `app.include_router`."""
    router = APIRouter()

    # ---- A. the authored course -------------------------------------------

    @router.get("/api/projects/{project_id}/export/course")
    async def export_course(
        request: Request,
        project_id: UUID,
        area: str | None = None,
        format: Literal["zip", "html"] = "zip",
    ):
        """Every file the last authoring run wrote, as one zip -- or as one page.

        **`format` is a `Literal`, so a typo is a 422 rather than a zip.** The
        same hard edge `export_graph` below takes, and here it matters more:
        the two formats differ in *media type*, so a silent fallback would
        hand a browser an archive it was told to render.

        `format=html` is the self-contained course -- see `course_html.py` for
        what each widget becomes and why. It costs several live reads per
        resolved component (an entity lookup, a definition, a neighbourhood
        layout) where the zip costs none, which is why it is a second format
        on a deliberate one-off action rather than the default.

        **Read out of `AuthoringActivity`, which is process memory that a
        restart loses.** That is not this route's bug to fix -- it is being
        fixed on `authoring-durable` -- but it is this route's problem to be
        honest about, because the failure is silent from every other angle:
        the files themselves are safely on the log, and only the *mapping*
        from an area slug to the session whose workspace holds it lives in
        RAM. Without that mapping the files are reachable only by walking the
        fork tree by hand. So a project whose server has restarted since its
        courses were written gets a 409 naming the reason, never an empty or
        partial archive.

        When durability lands this changes in exactly one place: `_run_of`
        below stops calling `authoring.last` and asks whatever durable read
        replaces it. Nothing else here knows where the mapping came from.

        **409 while a run is in flight**, rather than a snapshot of it. An
        archive taken mid-run contains whichever areas happened to be finished
        and looks exactly like a complete one -- which is precisely the
        "silently partial" outcome this route is required not to produce.
        """
        await deps.require_project(project_id)
        run = _run_of(project_id, deps.authoring)

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

        if format == "html":
            return await _course_page(deps, request, project_id, name, run, links, area)

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
            raise HTTPException(
                status_code=409,
                detail="the last authoring run wrote no course files to export",
            )

        stem = _safe(name) if area is None else f"{_safe(name)}-{_safe(area)}"
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"content-disposition": f'attachment; filename="{stem}-course.zip"'},
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


async def _course_page(
    deps: ExportDeps,
    request: Request,
    project_id: UUID,
    name: str,
    run: dict,
    links: list[tuple[str, str]],
    area: str | None,
) -> Response:
    """The whole course as one HTML file.

    Gathers the same workspace files the zip does -- through the same
    `_course_links`/`_is_path_file` pair, so the two formats can never
    disagree about which session holds which area -- and then hands them to
    `course_html`, which does the live reads and the rendering.

    `str(request.base_url).rstrip("/")` is what every link in the file points
    at. It is the address this request arrived on, which is the only origin
    this process actually knows: a server behind a proxy sees the proxy's
    forwarded host or its own bind address, and neither is guessable from
    configuration. The page says what it is rather than pretending, and
    `localhost` in an exported file is a limitation the header states.
    """
    overview = None
    areas: list[CourseArea] = []
    for target, session_id in links:
        session = await deps.service.load(UUID(session_id))
        files = session.state.files
        if _is_path_file(session, target):
            entry = files.get(f"{PATHS_DIR}/{target}.md") or {}
            overview = read_course_file(f"{PATHS_DIR}/{target}.md", entry.get("content", ""))
            continue
        prefix = f"{AREAS_DIR}/{target}/"
        unit = None
        lessons = []
        for path, entry in sorted(files.items()):
            if not path.startswith(prefix):
                continue
            parsed = read_course_file(path, entry.get("content", ""))
            # `unit.md` is Stages 1 and 2 and everything else is a lesson,
            # matched on the filename because that is what `course_authoring`
            # writes -- there is no marker inside the file. A run that wrote
            # only lessons produces an area with no unit rather than a
            # missing area, which is the state a reader can act on.
            if path == f"{prefix}unit.md":
                unit = parsed
            else:
                lessons.append(parsed)
        # An area whose session held no file under its prefix is skipped
        # rather than added empty. An empty `<section>` with a heading and
        # nothing under it reads as an area whose lessons were deleted; and
        # if *every* area is like that, the 409 below is the honest answer
        # rather than a page of headings.
        if unit is not None or lessons:
            areas.append(
                CourseArea(
                    slug=target,
                    title=unit.title if unit else target,
                    unit=unit,
                    lessons=tuple(lessons),
                )
            )

    if overview is None and not areas:
        raise HTTPException(
            status_code=409,
            detail="the last authoring run wrote no course files to export",
        )

    book = await build_course_book(
        name=name,
        project_id=project_id,
        origin=str(request.base_url).rstrip("/"),
        run=run,
        overview=overview,
        areas=areas,
        reads=CourseReads(
            graph_reader=deps.graph_reader,
            corpus_reader=deps.corpus_reader,
            definitions=deps.definitions,
            timeline_reader=deps.timeline_reader,
        ),
    )
    stem = _safe(name) if area is None else f"{_safe(name)}-{_safe(area)}"
    return Response(
        content=render_course_html(book),
        media_type="text/html; charset=utf-8",
        # `attachment`, for the reason the graph export gives: served inline
        # it renders in the console's own tab as a page that looks like part
        # of the app and is not, and the whole point is a file that can be
        # attached to a mail.
        headers={"content-disposition": f'attachment; filename="{stem}-course.html"'},
    )


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


def _run_of(project_id: UUID, authoring: AuthoringActivity | None) -> dict:
    """The finished authoring run whose files this export is of, or a 409.

    Three refusals rather than one, because they are three different things a
    person can act on: the build has no authoring wired at all, this server
    has no memory of a run (which for a restarted server means "the mapping
    is gone", not "nothing was ever written"), and a run is happening now.
    """
    if authoring is None:
        raise HTTPException(status_code=503, detail="course authoring is not configured")
    if authoring.active(project_id) is not None:
        raise HTTPException(
            status_code=409,
            detail="an authoring run is in flight; wait for it to finish and export then",
        )
    run = authoring.last(project_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "this server has no record of an authoring run for this project. "
                "Which session holds each area's course is kept in memory and is "
                "lost on restart, so courses written before the last restart "
                "cannot be gathered automatically -- re-run the authoring, or open "
                "the sessions directly."
            ),
        )
    return run


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


def _course_readme(name: str, project_id: UUID, run: dict, area: str | None) -> str:
    """What this archive is, written into it.

    A zip of markdown with no provenance is one somebody deletes rather than
    asks about six months from now. It names the failures too: a run that
    wrote seven of eight areas is reported `done`, and an archive that carried
    seven courses and said nothing would hide the eighth.
    """
    lines = [
        f"# {name} — course export",
        "",
        f"Exported {datetime.now(UTC).isoformat(timespec='seconds')}"
        f" from project `{project_id}`.",
        f"Authoring run `{run.get('run_id')}` ({run.get('kind')}),"
        f" status `{run.get('status')}`.",
        "",
        "Understanding by Design units under `areas/`, one directory per learning",
        "area, each with a `unit.md` and its lessons. The path overview, if this",
        "run wrote one, is under `paths/`.",
        "",
    ]
    if area is not None:
        lines += [f"This archive holds **one area only**: `{area}`.", ""]
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
