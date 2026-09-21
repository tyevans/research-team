"""Async component resolution and live reader queries for course HTML exports.

Extracted from `course_html.py` to isolate dynamic data resolution
(evidence passages, entity definitions, graph neighborhoods, timelines, and comparisons)
from static document parsing and HTML rendering.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from research_team.application.components import ComponentBlock
from research_team.application.knowledge.entity_definitions import Citation
from research_team.application.knowledge.graph_export import ExportGraph
from research_team.application.knowledge.timeline_read import TimelineBand, TimelineInterval
from research_team.interfaces.web.course_html_figures import (
    MAX_FIGURE_BANDS,
    figure_graph,
)

#: How much of a cited range is quoted into the page. Generous next to the
#: passages this system actually produces -- a grounding chunk is a few
#: hundred characters -- and it is a typo guard rather than an editorial
#: judgement: `evidence` accepts offsets up to 100,000,000 (see the
#: registry), so a mistyped `end` would otherwise inline a whole document.
#: The cut is marked in the page with an ellipsis, never silent.
MAX_QUOTE_CHARS = 1_200


@dataclass(frozen=True)
class Passage:
    """One quoted stretch of one source, with enough to attribute it.

    `title` rather than only `source_id` because this record exists to be
    rendered somewhere the id means nothing. `at_seconds` is a moment inside
    a medium, `None` for the ordinary text case -- the same distinction
    `ServedCitation` draws, and for the same reason: a citation at the start
    of a video and a citation into an article are different answers.
    """

    source_id: str
    title: str
    text: str
    truncated: bool = False
    at_seconds: float | None = None


@dataclass(frozen=True)
class Resolution:
    """What one resolved component's live reads produced, frozen.

    One record for five component types rather than five records, because the
    renderer's job is to be handed an answer and every field it does not use
    is `None` or empty. The alternative -- a union -- would put a match
    statement in the renderer for a distinction the component's own `type`
    already makes.

    `absent` is the field that must not be forgotten. It carries the sentence
    a reader is shown when the read found nothing: an entity name that
    matches no entity, a source id that names no source, a build with no
    graph wired. Every one of those has to render as a named absence rather
    than as an empty widget, so `absent` being a *sentence* rather than a
    bool is deliberate -- there is nowhere else the reason could be written
    down by the time the renderer runs.
    """

    absent: str | None = None
    entity_id: str | None = None
    definition: str | None = None
    passages: tuple[Passage, ...] = ()
    graph: ExportGraph | None = None
    bands: tuple[TimelineBand, ...] = ()
    undated: int = 0
    truncated: bool = False
    #: `compare`'s column heads: the name the author wrote, and the entity id
    #: it resolved to, or `None`. A head that resolved becomes a link; one
    #: that did not renders as the author's plain text with the table intact,
    #: which is what the console does and what the registry's craft note
    #: promises an author.
    columns: tuple[tuple[str, str | None], ...] = ()


def quote_passage(text: str, start: int, end: int) -> tuple[str, bool]:
    """The cited range, clamped to the document and to `MAX_QUOTE_CHARS`.

    Clamped rather than refused: `evidence`'s offsets are model output and an
    `end` past the document is the ordinary near-miss, where the useful
    answer is the tail of the document rather than a widget that says the
    author made a mistake. A range that is entirely past the end yields the
    empty string, and the caller renders that as an absence.
    """
    low = max(0, min(start, len(text)))
    high = max(low, min(end, len(text)))
    span = text[low:high].strip()
    if len(span) > MAX_QUOTE_CHARS:
        return span[:MAX_QUOTE_CHARS].rstrip(), True
    return span, False


async def resolve_citations(
    reader: Any, citations: Sequence[Citation], titles: Mapping[str, str]
) -> tuple[Passage, ...]:
    """Citations as quoted passages, reading each source at most once.

    `Any` for the reader rather than `CorpusReadPort`: the caller holds a
    `ProjectCorpusReader`, which satisfies the port, and naming the port here
    would make this module import an application protocol for one method.
    """
    bodies: dict[str, str | None] = {}
    passages: list[Passage] = []
    for citation in citations:
        if citation.source_id not in bodies:
            document = await reader.read_document(citation.source_id, include_dropped=True)
            bodies[citation.source_id] = document.text if document else None
        body = bodies[citation.source_id]
        if body is None:
            continue
        text, truncated = quote_passage(body, citation.start, citation.end)
        if not text:
            continue
        passages.append(
            Passage(
                source_id=citation.source_id,
                title=titles.get(citation.source_id, citation.source_id),
                text=text,
                truncated=truncated,
            )
        )
    return tuple(passages)


@dataclass(frozen=True)
class CourseReads:
    """The live reads an export needs, each of which may be absent.

    Every field is optional and every one of them is *called inside a
    try* below, because a build assembled without a graph store, without a
    corpus read model or without a definition service is a valid thing to
    serve -- `create_app` says so for each of them separately -- and an
    export that 503'd because one lesson happened to contain a `graph` block
    would fail for a reason the person exporting a course cannot act on. What
    happens instead is that the widget renders a named absence saying which
    read was unavailable, and the other nine hundred lines of the course come
    out intact.

    Callables rather than the readers themselves: each is bound per project
    inside `create_app` and several of them open a store on first use.
    """

    graph_reader: Callable[[UUID], Awaitable[Any]] | None = None
    corpus_reader: Callable[[UUID], Any] | None = None
    definitions: Callable[[UUID], Awaitable[Any]] | None = None
    timeline_reader: Callable[[UUID], Awaitable[Any]] | None = None


async def _entity_by_name(reader: Any, name: str) -> Any | None:
    """The entity an author's `entity:` names, or `None`.

    Case-insensitive exact match first, then the search's own best result --
    the same order the console's resolver takes. Falling straight to the
    first result would make `Constantine` resolve to `Constantinople` when
    both exist and only one is meant, which is a wrong figure rather than a
    missing one and is the failure this ordering exists to avoid.
    """
    if not name.strip():
        return None
    page = await reader.find_entities(name=name, limit=10)
    for entity in page.entities:
        if entity.name.casefold() == name.casefold():
            return entity
    return page.entities[0] if page.entities else None


def _interval(body: Mapping[str, Any]) -> tuple[datetime | None, datetime | None]:
    """`from`/`to` as instants, with an unparseable end treated as open.

    The route refuses a bad date with a 422; this does not. An export is a
    whole course, and losing all of it because one `timeline` block quoted
    its date in a format YAML mangled would be the wrong trade -- the figure
    draws with that end open, which is visible in the drawing.
    """
    out: list[datetime | None] = []
    for key in ("from", "to"):
        raw = body.get(key)
        try:
            out.append(datetime.fromisoformat(str(raw)) if raw else None)
        except (TypeError, ValueError):
            out.append(None)
    return out[0], out[1]


async def _resolve_evidence(
    block: ComponentBlock, project_id: UUID, reads: CourseReads, titles: Mapping[str, str]
) -> Resolution:
    if reads.corpus_reader is None:
        return Resolution(
            absent="this build has no corpus read model, so nothing could be quoted."
        )
    reader = reads.corpus_reader(project_id)
    citations = [
        Citation(
            source_id=str(entry.get("source", "")),
            start=int(entry.get("start", 0) or 0),
            end=int(entry.get("end", 0) or 0),
        )
        for entry in block.data.get("sources", [])
        if isinstance(entry, Mapping) and entry.get("source")
    ]
    passages = await resolve_citations(reader, citations, titles)
    if not passages:
        named = ", ".join(sorted({c.source_id for c in citations})) or "nothing"
        return Resolution(absent=f"no readable passage was found behind {named}.")
    return Resolution(passages=passages)


async def _resolve_definition(
    block: ComponentBlock, project_id: UUID, reads: CourseReads, titles: Mapping[str, str]
) -> Resolution:
    if reads.graph_reader is None:
        return Resolution(
            absent="this build has no graph, so the entity could not be looked up."
        )
    name = str(block.data.get("entity", ""))
    pinned = block.data.get("entity_id")
    reader = await reads.graph_reader(project_id)
    entity = await _entity_by_name(reader, name)
    entity_id = str(pinned) if pinned else (entity.entity_id if entity else None)
    if entity_id is None:
        return Resolution(absent="this project's graph holds no entity by that name.")
    if reads.definitions is None:
        return Resolution(entity_id=entity_id, absent="no definition service was configured.")
    service = await reads.definitions(project_id)
    if service is None:
        return Resolution(
            entity_id=entity_id, absent="no chunk store was configured to ground a definition."
        )
    definition = await service.define(UUID(entity_id))
    if definition is None:
        return Resolution(
            entity_id=entity_id,
            absent="nothing in this project's sources grounds a definition of it.",
        )
    passages = ()
    if reads.corpus_reader is not None:
        passages = await resolve_citations(
            reads.corpus_reader(project_id), definition.citations, titles
        )
    return Resolution(entity_id=entity_id, definition=definition.text, passages=passages)


async def _resolve_graph(
    block: ComponentBlock, project_id: UUID, reads: CourseReads
) -> Resolution:
    if reads.graph_reader is None:
        return Resolution(absent="this build has no graph read model.")
    reader = await reads.graph_reader(project_id)
    name = str(block.data.get("entity", ""))
    pinned = block.data.get("entity_id")
    entity = await _entity_by_name(reader, name)
    entity_id = str(pinned) if pinned else (entity.entity_id if entity else None)
    if entity_id is None:
        return Resolution(absent="this project's graph holds no entity by that name.")
    hood = await reader.neighborhood(entity_id, depth=int(block.data.get("depth", 1) or 1))
    if hood is None:
        return Resolution(entity_id=entity_id, absent="that entity is no longer in the graph.")
    return Resolution(
        entity_id=entity_id,
        graph=figure_graph(hood.root, hood.entities, hood.relationships),
    )


async def _resolve_timeline(
    block: ComponentBlock, project_id: UUID, reads: CourseReads
) -> Resolution:
    if reads.timeline_reader is None:
        return Resolution(absent="this build has no timeline read model.")
    reader = await reads.timeline_reader(project_id)
    start, end = _interval(block.data)
    asked = int(block.data.get("limit") or MAX_FIGURE_BANDS)
    timeline = await reader.timeline(
        entity_type=block.data.get("entity_type"),
        interval=TimelineInterval(start=start, end=end),
        limit=min(asked, MAX_FIGURE_BANDS),
    )
    return Resolution(
        bands=tuple(timeline.bands),
        undated=timeline.undated_count,
        # Either cause counts: the port's own cap, or this module's tighter
        # figure cap having cut an author's larger `limit` down.
        truncated=timeline.truncated or asked > MAX_FIGURE_BANDS,
    )


async def _resolve_compare(
    block: ComponentBlock, project_id: UUID, reads: CourseReads
) -> Resolution:
    names = [str(n) for n in block.data.get("entities", [])]
    if reads.graph_reader is None:
        # Not an absence: a compare table's content is the author's own rows,
        # and they render whole. Only the column *links* are lost, which is
        # exactly what an unresolved head looks like in the console too.
        return Resolution(columns=tuple((name, None) for name in names))
    reader = await reads.graph_reader(project_id)
    found = []
    for name in names:
        entity = await _entity_by_name(reader, name)
        found.append((name, entity.entity_id if entity else None))
    return Resolution(columns=tuple(found))


async def _resolve(
    block: ComponentBlock,
    project_id: UUID,
    reads: CourseReads,
    titles: Mapping[str, str],
) -> Resolution:
    """One resolved component's live read, or a `Resolution` saying why not.

    Every branch is wrapped: `HTTPException` is what the `create_app`
    closures raise for an unwired collaborator, and anything else is a store
    that failed. Both become a sentence rather than a 500, for
    `CourseReads`' reason.
    """
    try:
        if block.type == "evidence":
            return await _resolve_evidence(block, project_id, reads, titles)
        if block.type == "definition":
            return await _resolve_definition(block, project_id, reads, titles)
        if block.type == "graph":
            return await _resolve_graph(block, project_id, reads)
        if block.type == "timeline":
            return await _resolve_timeline(block, project_id, reads)
        if block.type == "compare":
            return await _resolve_compare(block, project_id, reads)
    except HTTPException as refusal:
        return Resolution(absent=str(refusal.detail))
    except Exception as failure:  # noqa: BLE001 -- see the docstring
        return Resolution(absent=f"the export could not read this ({type(failure).__name__}).")
    return Resolution()


entity_by_name = _entity_by_name
interval = _interval
resolve = _resolve
resolve_evidence = _resolve_evidence
resolve_definition = _resolve_definition
resolve_graph = _resolve_graph
resolve_timeline = _resolve_timeline
resolve_compare = _resolve_compare

__all__ = [
    "MAX_QUOTE_CHARS",
    "CourseReads",
    "Passage",
    "Resolution",
    "_entity_by_name",
    "_interval",
    "_resolve",
    "_resolve_compare",
    "_resolve_definition",
    "_resolve_evidence",
    "_resolve_graph",
    "_resolve_timeline",
    "entity_by_name",
    "interval",
    "quote_passage",
    "resolve",
    "resolve_citations",
    "resolve_compare",
    "resolve_definition",
    "resolve_evidence",
    "resolve_graph",
    "resolve_timeline",
]
