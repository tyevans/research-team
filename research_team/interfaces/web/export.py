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

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from research_team.interfaces.web.authored_files import course_links
from research_team.interfaces.web.deps import ExportDeps
from research_team.interfaces.web.export_course import (
    _UNSAFE,
    _course_page,
    _course_readme,
    _course_zip,
    _never_started,
    _run_of,
    _safe,
    _status_sentence,
    _status_suffix,
    _wrote,
)
from research_team.interfaces.web.graph_html import render_html
from research_team.knowledge.application.graph_export import (
    MAX_EXPORT_NODES,
    build_export,
    to_csv_edges,
    to_csv_nodes,
    to_cytoscape_json,
    to_dot,
    to_graphml,
    to_json,
)
from research_team.knowledge.application.graph_layout import LayoutAlgorithm
from research_team.knowledge.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    GraphReadPort,
)


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
        """Every file the last settled authoring run wrote, as one zip -- or as
        one page.

        **`format` is a `Literal`, so a typo is a 422 rather than a zip.** The
        same hard edge `export_graph` below takes, and here it matters more:
        the two formats differ in *media type*, so a silent fallback would
        hand a browser an archive it was told to render.

        `format=html` is the self-contained course -- see `course_html.py` for
        what each widget becomes and why. It costs several live reads per
        resolved component (an entity lookup, a definition, a neighbourhood
        layout) where the zip costs none, which is why it is a second format
        on a deliberate one-off action rather than the default.

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

        links = course_links(run)
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

        return await _course_zip(deps, project_id, name, run, links, area)

    # ---- B. the graph ------------------------------------------------------

    @router.get("/api/projects/{project_id}/export/graph")
    async def export_graph(
        project_id: UUID,
        format: Literal[
            "html", "json", "graphml", "dot", "cytoscape", "csv_nodes", "csv_edges"
        ] = "html",
        scope: Literal["project", "area", "entity"] = "project",
        area: str | None = None,
        entity: str | None = None,
        depth: int = 1,
        limit: int = Query(default=MAX_EXPORT_NODES, le=MAX_GRAPH_NODES),
        entity_types: Annotated[list[str] | None, Query()] = None,
        relationship_types: Annotated[list[str] | None, Query()] = None,
        min_degree: int = Query(default=0, ge=0),
        include_inferred: bool = Query(default=True),
        search: str | None = Query(default=None),
        layout: LayoutAlgorithm = "force_directed",
    ):
        """The graph, or a cut of it, as a file.

        **Produced here rather than in the browser**, from the graph the log
        already folds to. Supports HTML, JSON, GraphML, Graphviz DOT,
        Cytoscape.js, and CSV formats, with optional type, degree, text,
        and inference filtering.
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
            entity_types=entity_types,
            relationship_types=relationship_types,
            min_degree=min_degree,
            include_inferred=include_inferred,
            search_query=search,
            layout_algorithm=layout,
        )

        match format:
            case "html":
                body, media, suffix = render_html(graph), "text/html; charset=utf-8", "html"
            case "json":
                body, media, suffix = to_json(graph), "application/json", "json"
            case "graphml":
                body, media, suffix = to_graphml(graph), "application/xml", "graphml"
            case "dot":
                body, media, suffix = to_dot(graph), "text/vnd.graphviz; charset=utf-8", "dot"
            case "cytoscape":
                body, media, suffix = (
                    to_cytoscape_json(graph),
                    "application/json",
                    "cytoscape.json",
                )
            case "csv_nodes":
                body, media, suffix = (
                    to_csv_nodes(graph),
                    "text/csv; charset=utf-8",
                    "nodes.csv",
                )
            case "csv_edges":
                body, media, suffix = (
                    to_csv_edges(graph),
                    "text/csv; charset=utf-8",
                    "edges.csv",
                )
            case _:
                raise HTTPException(status_code=422, detail=f"unsupported format: {format}")

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


__all__ = [
    "_UNSAFE",
    "ExportDeps",
    "_area_cut",
    "_course_page",
    "_course_readme",
    "_course_zip",
    "_never_started",
    "_run_of",
    "_safe",
    "_status_sentence",
    "_status_suffix",
    "_wrote",
    "export_router",
]
