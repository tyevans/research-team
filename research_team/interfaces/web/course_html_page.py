"""Page rendering and component dispatch for offline course HTML books.

Extracted from `course_html.py`: converts a resolved `CourseBook` into a single,
self-contained HTML page with navigation, sections, units, lessons, and widget markup.
"""

import re

from research_team.interfaces.web.course_html_figures import (
    _svg_graph,
    _svg_timeline,
    esc,
)
from research_team.interfaces.web.course_html_markdown import (
    _HEADING,
    _Inline,
    _markdown,
)
from research_team.interfaces.web.course_html_models import (
    CourseBook,
    CourseFile,
    resolution_key,
)
from research_team.interfaces.web.course_html_resolvers import Resolution
from research_team.interfaces.web.course_html_template import _TEMPLATE
from research_team.interfaces.web.course_html_widgets import (
    _absent,
    _checklist,
    _cloze,
    _compare,
    _definition,
    _evidence,
    _explorer,
    _flashcards,
    _head,
    _mcq,
    _project_href,
)
from research_team.platform.components import (
    REGISTRY,
    Block,
    ComponentBlock,
    MarkdownBlock,
)


def _anchor(slug: str, lesson: int | None = None) -> str:
    """Anchors built from the slug and an index, never from a title.

    A title is model output and would put arbitrary text in a fragment id;
    an index is a number. The cost is that a bookmark into lesson 3 points at
    whatever is third after a re-authoring run, which is the right trade for
    a document whose lessons are numbered in teaching order anyway.
    """
    stem = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") or "area"
    return stem if lesson is None else f"{stem}-l{lesson + 1}"


def _nav(book: CourseBook) -> str:
    items = []
    if book.overview is not None:
        items.append(f'<li><a href="#overview">{esc(book.overview.title)}</a></li>')
    for area in book.areas:
        lessons = "".join(
            f'<li><a href="#{esc(_anchor(area.slug, index))}">{esc(lesson.title)}</a></li>'
            for index, lesson in enumerate(area.lessons)
        )
        items.append(
            f'<li><a href="#{esc(_anchor(area.slug))}">{esc(area.title)}</a>'
            + (f"<ul>{lessons}</ul>" if lessons else "")
            + "</li>"
        )
    return f'<nav aria-label="Contents"><ol>{"".join(items)}</ol></nav>'


def _without_title(text: str, title: str) -> str:
    """`text` less a leading heading that repeats `title`.

    Only the *first* non-blank line is considered. A heading deeper in the
    file that happens to repeat the title is the author's own repetition and
    not this function's to remove.
    """
    lines = text.splitlines()
    for position, line in enumerate(lines):
        if not line.strip():
            continue
        found = _HEADING.match(line)
        if found and found.group(2).strip() == title:
            return "\n".join(lines[:position] + lines[position + 1 :])
        return text
    return text


def _broken(block: ComponentBlock) -> str:
    """A component this server could not build, shown rather than dropped.

    An export of a lesson with a broken block has to look different from an
    export of a lesson without one, or the export is a way of losing an
    authoring error.
    """
    notes = "".join(f"<li>{esc(note.path)}: {esc(note.message)}</li>" for note in block.errors)
    reason = (
        f"<code>{esc(block.type)}</code> is not a component this build knows"
        if block.unknown
        else "this block did not parse"
    )
    return (
        f'<div class="w w-broken"><p class="absent">{reason}, so it is shown as written.</p>'
        f"{f'<ul>{notes}</ul>' if notes else ''}"
        f"<pre><code>{esc(block.raw)}</code></pre></div>"
    )


def _graph(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
    name = str(block.data.get("entity", ""))
    if resolved.graph is None:
        return (
            '<div class="w w-graph">'
            f"{_head('Neighbourhood', name)}"
            + _absent(
                name,
                resolved.absent or "this project's graph has no such entity.",
                _project_href(book, "graph"),
            )
            + "</div>"
        )
    href = _project_href(book, "entity", resolved.entity_id) if resolved.entity_id else None
    return (
        '<div class="w w-graph">'
        f"{_head('Neighbourhood', name)}"
        f"{_svg_graph(resolved.graph)}"
        + (f'<p class="live"><a href="{esc(href)}">Explore this live</a></p>' if href else "")
        + "</div>"
    )


def _timeline(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
    if not resolved.bands:
        return (
            '<div class="w w-time">'
            f"{_head('Timeline')}"
            + _absent(
                "This timeline",
                resolved.absent or "no dated entity in this project falls in the window.",
                _project_href(book, "timeline"),
            )
            + "</div>"
        )
    return (
        '<div class="w w-time">'
        f"{_head('Timeline')}"
        f"{_svg_timeline(resolved.bands, resolved.undated, resolved.truncated)}"
        f'<p class="live"><a href="{esc(_project_href(book, "timeline"))}">'
        "The timeline, live</a></p>"
        "</div>"
    )


_RENDERERS = {
    "mcq": _mcq,
    "cloze": _cloze,
    "flashcards": _flashcards,
    "checklist": _checklist,
    "compare": _compare,
    "definition": _definition,
    "evidence": _evidence,
    "graph": _graph,
    "timeline": _timeline,
    "explorer": _explorer,
}

#: Asserted at import: every registered component type has a renderer here.
#: An eleventh type added to `REGISTRY` with no entry above would otherwise
#: export as a `<pre>` of its own source, which is a legible failure and a
#: silent one -- nobody diffing two exports would know a widget had stopped
#: being a widget.
assert set(_RENDERERS) == set(REGISTRY), (
    f"course_html has no renderer for {sorted(set(REGISTRY) - set(_RENDERERS))}"
)


def _component(block: ComponentBlock, book: CourseBook, path: str) -> str:
    """One component block, frozen. Dispatch on `type` through a table rather
    than a chain, so a build that adds an eleventh type gets the "unknown"
    branch below -- a visible `<pre>` of the source -- instead of a page that
    silently drops it."""
    if block.unknown or block.errors:
        return _broken(block)
    renderer = _RENDERERS.get(block.type)
    if renderer is None:
        return _broken(block)
    resolved = book.resolutions.get(resolution_key(path, block.id), Resolution())
    return renderer(block, resolved, book)


def _render_block(block: Block, book: CourseBook, path: str) -> str:
    if isinstance(block, MarkdownBlock):
        return _markdown(block.text, book)
    return _component(block, book, path)


def _blocks(course_file: CourseFile, book: CourseBook) -> str:
    """A file's blocks, with its own opening title heading dropped."""
    out: list[str] = []
    for index, block in enumerate(course_file.document.blocks):
        if index == 0 and isinstance(block, MarkdownBlock):
            block = MarkdownBlock(_without_title(block.text, course_file.title))
            if not block.text.strip():
                continue
        out.append(_render_block(block, book, course_file.path))
    return "".join(out)


def render_course_html(book: CourseBook) -> str:
    """The whole file. Pure: every live read has already happened."""
    sections: list[str] = []
    if book.overview is not None:
        sections.append(
            f'<section id="overview"><h2>{esc(book.overview.title)}</h2>'
            f"{_blocks(book.overview, book)}</section>"
        )
    for area in book.areas:
        parts = [f'<section id="{esc(_anchor(area.slug))}"><h2>{esc(area.title)}</h2>']
        if area.unit is not None:
            parts.append(f'<div class="unit">{_blocks(area.unit, book)}</div>')
        for index, lesson in enumerate(area.lessons):
            parts.append(
                f'<article id="{esc(_anchor(area.slug, index))}">'
                f"<h3>{esc(lesson.title)}</h3>{_blocks(lesson, book)}</article>"
            )
        parts.append("</section>")
        sections.append("".join(parts))

    settled = (
        f'<p class="settled">{_Inline(book).render(book.status_sentence)}</p>'
        if book.status_sentence
        else ""
    )
    never = (
        "<h3>Never started</h3><ul>"
        + "".join(f"<li><code>{esc(t)}</code></li>" for t in book.never_started)
        + "</ul>"
        if book.never_started
        else ""
    )

    failures = book.run.get("failures") or []
    not_written = (
        "<h3>Not written</h3><ul>"
        + "".join(
            f"<li><code>{esc(f.get('target'))}</code>: {esc(f.get('detail'))}</li>"
            for f in failures
        )
        + "</ul>"
        if failures
        else ""
    )
    return (
        _TEMPLATE.replace("__TITLE__", esc(book.name))
        .replace("__ORIGIN__", esc(book.origin))
        .replace("__PROJECT__", esc(str(book.project_id)))
        .replace("__EXPORTED__", esc(book.exported_at))
        .replace("__RUN__", esc(str(book.run.get("run_id", "unknown"))))
        .replace("__SETTLED__", settled)
        .replace("__NEVERSTARTED__", never)
        .replace("__NOTWRITTEN__", not_written)
        .replace("__NAV__", _nav(book))
        .replace("__BODY__", "".join(sections))
    )


__all__ = [
    "_RENDERERS",
    "_anchor",
    "_blocks",
    "_broken",
    "_component",
    "_graph",
    "_nav",
    "_render_block",
    "_timeline",
    "_without_title",
    "render_course_html",
]
