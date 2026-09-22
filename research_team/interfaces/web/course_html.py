"""One HTML file holding a whole course, for somebody who has no server.

The zip beside this (`export.py`) is markdown, and markdown is for reading in
a repository. This is for handing to a person: one file, opened from a mail
attachment, on a phone in a waiting room, with the questions still answerable.

`build_course_book` does the reading and `render_course_html` does the writing.
Modular subcomponents are isolated across:
- `course_html_models.py` (CourseFile, CourseArea, CourseBook, resolution_key)
- `course_html_page.py` (render_course_html, component dispatch, page sections)
- `course_html_widgets.py` (interactive DOM widget rendering)
- `course_html_figures.py` (server-side SVG graph & timeline figure generation)
- `course_html_markdown.py` (markdown & inline syntax parser)
- `course_html_resolvers.py` (grounded definition & evidence resolution)
- `course_html_template.py` (base HTML page template)
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from research_team.interfaces.web.course_html_figures import (
    MAX_FIGURE_BANDS as MAX_FIGURE_BANDS,
)
from research_team.interfaces.web.course_html_figures import (
    MAX_FIGURE_NODES as MAX_FIGURE_NODES,
)
from research_team.interfaces.web.course_html_figures import (
    _instant as _instant,
)
from research_team.interfaces.web.course_html_figures import (
    _svg_graph as _svg_graph,
)
from research_team.interfaces.web.course_html_figures import (
    _svg_timeline as _svg_timeline,
)
from research_team.interfaces.web.course_html_figures import (
    figure_graph as figure_graph,
)
from research_team.interfaces.web.course_html_figures import (
    parse_instant as parse_instant,
)
from research_team.interfaces.web.course_html_figures import (
    render_graph_svg as render_graph_svg,
)
from research_team.interfaces.web.course_html_figures import (
    render_timeline_svg as render_timeline_svg,
)
from research_team.interfaces.web.course_html_markdown import (
    _BOLD as _BOLD,
)
from research_team.interfaces.web.course_html_markdown import (
    _BULLET as _BULLET,
)
from research_team.interfaces.web.course_html_markdown import (
    _ESCAPE as _ESCAPE,
)
from research_team.interfaces.web.course_html_markdown import (
    _FENCE as _FENCE,
)
from research_team.interfaces.web.course_html_markdown import (
    _HEADING as _HEADING,
)
from research_team.interfaces.web.course_html_markdown import (
    _INLINE_CODE as _INLINE_CODE,
)
from research_team.interfaces.web.course_html_markdown import (
    _ITALIC as _ITALIC,
)
from research_team.interfaces.web.course_html_markdown import (
    _LINK as _LINK,
)
from research_team.interfaces.web.course_html_markdown import (
    _ORDERED as _ORDERED,
)
from research_team.interfaces.web.course_html_markdown import (
    _REFERENCE as _REFERENCE,
)
from research_team.interfaces.web.course_html_markdown import (
    _RULE as _RULE,
)
from research_team.interfaces.web.course_html_markdown import (
    _Inline as _Inline,
)
from research_team.interfaces.web.course_html_markdown import (
    _is_block_start as _is_block_start,
)
from research_team.interfaces.web.course_html_markdown import (
    _markdown as _markdown,
)
from research_team.interfaces.web.course_html_markdown import (
    esc as esc,
)
from research_team.interfaces.web.course_html_markdown import (
    is_block_start as is_block_start,
)
from research_team.interfaces.web.course_html_markdown import (
    render_markdown as render_markdown,
)
from research_team.interfaces.web.course_html_models import (
    CourseArea as CourseArea,
)
from research_team.interfaces.web.course_html_models import (
    CourseBook as CourseBook,
)
from research_team.interfaces.web.course_html_models import (
    CourseFile as CourseFile,
)
from research_team.interfaces.web.course_html_models import (
    resolution_key as resolution_key,
)
from research_team.interfaces.web.course_html_page import (
    _RENDERERS as _RENDERERS,
)
from research_team.interfaces.web.course_html_page import (
    _anchor as _anchor,
)
from research_team.interfaces.web.course_html_page import (
    _blocks as _blocks,
)
from research_team.interfaces.web.course_html_page import (
    _broken as _broken,
)
from research_team.interfaces.web.course_html_page import (
    _component as _component,
)
from research_team.interfaces.web.course_html_page import (
    _graph as _graph,
)
from research_team.interfaces.web.course_html_page import (
    _nav as _nav,
)
from research_team.interfaces.web.course_html_page import (
    _render_block as _render_block,
)
from research_team.interfaces.web.course_html_page import (
    _timeline as _timeline,
)
from research_team.interfaces.web.course_html_page import (
    _without_title as _without_title,
)
from research_team.interfaces.web.course_html_page import (
    render_course_html as render_course_html,
)
from research_team.interfaces.web.course_html_resolvers import (
    MAX_QUOTE_CHARS as MAX_QUOTE_CHARS,
)
from research_team.interfaces.web.course_html_resolvers import (
    CourseReads as CourseReads,
)
from research_team.interfaces.web.course_html_resolvers import (
    Passage as Passage,
)
from research_team.interfaces.web.course_html_resolvers import (
    Resolution as Resolution,
)
from research_team.interfaces.web.course_html_resolvers import (
    _entity_by_name as _entity_by_name,
)
from research_team.interfaces.web.course_html_resolvers import (
    _interval as _interval,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve as _resolve,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve_compare as _resolve_compare,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve_definition as _resolve_definition,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve_evidence as _resolve_evidence,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve_graph as _resolve_graph,
)
from research_team.interfaces.web.course_html_resolvers import (
    _resolve_timeline as _resolve_timeline,
)
from research_team.interfaces.web.course_html_resolvers import (
    entity_by_name as entity_by_name,
)
from research_team.interfaces.web.course_html_resolvers import (
    interval as interval,
)
from research_team.interfaces.web.course_html_resolvers import (
    quote_passage as quote_passage,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve as resolve,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_citations as resolve_citations,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_compare as resolve_compare,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_definition as resolve_definition,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_evidence as resolve_evidence,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_graph as resolve_graph,
)
from research_team.interfaces.web.course_html_resolvers import (
    resolve_timeline as resolve_timeline,
)
from research_team.interfaces.web.course_html_template import (
    _TEMPLATE as _TEMPLATE,
)
from research_team.interfaces.web.course_html_widgets import (
    _absent as _absent,
)
from research_team.interfaces.web.course_html_widgets import (
    _checklist as _checklist,
)
from research_team.interfaces.web.course_html_widgets import (
    _clock as _clock,
)
from research_team.interfaces.web.course_html_widgets import (
    _cloze as _cloze,
)
from research_team.interfaces.web.course_html_widgets import (
    _compare as _compare,
)
from research_team.interfaces.web.course_html_widgets import (
    _definition as _definition,
)
from research_team.interfaces.web.course_html_widgets import (
    _doc_href as _doc_href,
)
from research_team.interfaces.web.course_html_widgets import (
    _evidence as _evidence,
)
from research_team.interfaces.web.course_html_widgets import (
    _explorer as _explorer,
)
from research_team.interfaces.web.course_html_widgets import (
    _flashcards as _flashcards,
)
from research_team.interfaces.web.course_html_widgets import (
    _head as _head,
)
from research_team.interfaces.web.course_html_widgets import (
    _mcq as _mcq,
)
from research_team.interfaces.web.course_html_widgets import (
    _passages as _passages,
)
from research_team.interfaces.web.course_html_widgets import (
    _project_href as _project_href,
)
from research_team.interfaces.web.course_html_widgets import (
    _quote as _quote,
)
from research_team.interfaces.web.course_html_widgets import (
    doc_href as doc_href,
)
from research_team.interfaces.web.course_html_widgets import (
    format_clock as format_clock,
)
from research_team.interfaces.web.course_html_widgets import (
    project_href as project_href,
)
from research_team.interfaces.web.course_html_widgets import (
    render_absent as render_absent,
)
from research_team.interfaces.web.course_html_widgets import (
    render_checklist as render_checklist,
)
from research_team.interfaces.web.course_html_widgets import (
    render_cloze as render_cloze,
)
from research_team.interfaces.web.course_html_widgets import (
    render_compare as render_compare,
)
from research_team.interfaces.web.course_html_widgets import (
    render_definition as render_definition,
)
from research_team.interfaces.web.course_html_widgets import (
    render_evidence as render_evidence,
)
from research_team.interfaces.web.course_html_widgets import (
    render_explorer as render_explorer,
)
from research_team.interfaces.web.course_html_widgets import (
    render_flashcards as render_flashcards,
)
from research_team.interfaces.web.course_html_widgets import (
    render_head as render_head,
)
from research_team.interfaces.web.course_html_widgets import (
    render_mcq as render_mcq,
)
from research_team.interfaces.web.course_html_widgets import (
    render_passages as render_passages,
)
from research_team.platform.components import (
    REGISTRY,
    Document,
    MarkdownBlock,
    parse_document,
)


def title_of(path: str, document: Document) -> str:
    """A file's display title: its frontmatter `title`, else its first
    `# heading`, else the filename."""
    front = document.frontmatter or {}
    if isinstance(front.get("title"), str) and front["title"].strip():
        return front["title"].strip()
    for block in document.blocks:
        if not isinstance(block, MarkdownBlock):
            continue
        for line in block.text.splitlines():
            found = _HEADING.match(line)
            if found and found.group(2).strip():
                return found.group(2).strip()
    return path.rsplit("/", 1)[-1].removesuffix(".md")


def read_course_file(path: str, source: str) -> CourseFile:
    document = parse_document(source, path=path)
    return CourseFile(path=path, title=title_of(path, document), document=document)


async def build_course_book(
    *,
    name: str,
    project_id: UUID,
    origin: str,
    run: Mapping[str, Any],
    status_sentence: str = "",
    never_started: tuple[str, ...] = (),
    overview: CourseFile | None,
    areas: Sequence[CourseArea],
    reads: CourseReads,
) -> CourseBook:
    """A parsed course with every resolved component already read.

    The two halves are deliberately separate -- this one is `async` and
    talks to four collaborators, `render_course_html` is pure and talks to
    none -- so that the per-widget freeze decisions, which are the part worth
    testing, are testable by handing a `CourseBook` to a function.
    """
    titles: dict[str, str] = {}
    if reads.corpus_reader is not None:
        try:
            listings = await reads.corpus_reader(project_id).list_sources(include_dropped=True)
            titles = {
                listing.record.source_id: (listing.record.title or listing.record.source_id)
                for listing in listings
            }
        except Exception:  # noqa: BLE001 -- see the comment below
            titles = {}

    book = CourseBook(
        name=name,
        project_id=project_id,
        origin=origin,
        exported_at=datetime.now(UTC).isoformat(timespec="seconds"),
        run=run,
        status_sentence=status_sentence,
        never_started=never_started,
        overview=overview,
        areas=tuple(areas),
        sources=titles,
    )

    resolutions: dict[str, Resolution] = {}
    files = [f for f in (overview, *(a.unit for a in areas)) if f is not None]
    files += [lesson for area in areas for lesson in area.lessons]
    for course_file in files:
        for block in course_file.document.components:
            spec = REGISTRY.get(block.type)
            if spec is None or not spec.resolved or not block.ok:
                continue
            resolutions[resolution_key(course_file.path, block.id)] = await _resolve(
                block, project_id, reads, titles
            )

    return CourseBook(
        name=book.name,
        project_id=book.project_id,
        origin=book.origin,
        exported_at=book.exported_at,
        run=book.run,
        status_sentence=book.status_sentence,
        never_started=book.never_started,
        overview=book.overview,
        areas=book.areas,
        resolutions=resolutions,
        sources=titles,
    )


__all__ = [
    "MAX_FIGURE_BANDS",
    "MAX_FIGURE_NODES",
    "MAX_QUOTE_CHARS",
    "_BOLD",
    "_BULLET",
    "_ESCAPE",
    "_FENCE",
    "_HEADING",
    "_INLINE_CODE",
    "_ITALIC",
    "_LINK",
    "_ORDERED",
    "_REFERENCE",
    "_RENDERERS",
    "_RULE",
    "_TEMPLATE",
    "CourseArea",
    "CourseBook",
    "CourseFile",
    "CourseReads",
    "Passage",
    "Resolution",
    "_Inline",
    "_absent",
    "_anchor",
    "_blocks",
    "_broken",
    "_checklist",
    "_clock",
    "_cloze",
    "_compare",
    "_component",
    "_definition",
    "_doc_href",
    "_entity_by_name",
    "_evidence",
    "_explorer",
    "_flashcards",
    "_graph",
    "_head",
    "_instant",
    "_interval",
    "_is_block_start",
    "_markdown",
    "_mcq",
    "_nav",
    "_passages",
    "_project_href",
    "_quote",
    "_render_block",
    "_resolve",
    "_resolve_compare",
    "_resolve_definition",
    "_resolve_evidence",
    "_resolve_graph",
    "_resolve_timeline",
    "_svg_graph",
    "_svg_timeline",
    "_timeline",
    "_without_title",
    "build_course_book",
    "doc_href",
    "entity_by_name",
    "esc",
    "figure_graph",
    "format_clock",
    "interval",
    "is_block_start",
    "parse_instant",
    "project_href",
    "quote_passage",
    "read_course_file",
    "render_absent",
    "render_checklist",
    "render_cloze",
    "render_compare",
    "render_course_html",
    "render_definition",
    "render_evidence",
    "render_explorer",
    "render_flashcards",
    "render_graph_svg",
    "render_head",
    "render_markdown",
    "render_mcq",
    "render_passages",
    "render_timeline_svg",
    "resolution_key",
    "resolve",
    "resolve_citations",
    "resolve_compare",
    "resolve_definition",
    "resolve_evidence",
    "resolve_graph",
    "resolve_timeline",
    "title_of",
]
