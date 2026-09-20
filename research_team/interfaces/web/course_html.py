"""One HTML file holding a whole course, for somebody who has no server.

The zip beside this (`export.py`) is markdown, and markdown is for reading in
a repository. This is for handing to a person: one file, opened from a mail
attachment, on a phone in a waiting room, with the questions still answerable.

**Everything is decided here and nothing is fetched there.** The console's
lesson widgets are half data and half query -- a `definition` block carries an
entity *name* and the browser asks the server what this project knows about
it. A file that leaves the building has no server to ask, so every one of
those reads happens at export time and its answer is written into the page.
That is the whole shape of this module: `build_course_book` does the reading
and `render_course_html` does the writing, and the second is pure so the
per-widget decisions below can be tested without a graph store.

## What each of the ten component types becomes, and why

Each decision is "can this survive with no network", answered per type rather
than by a rule, because the answers genuinely differ:

* `mcq`, `cloze` -- **live**. Both are graded by comparing a reader's input
  to a key, and the key is a few hundred bytes. Offline does not mean inert:
  the whole point of an assessment item is answering it, and a rendered
  question with a printed answer beside it is a different artifact. The cost
  is stated below under "The answer key is in the file".
* `flashcards` -- **live**. A card that does not flip is a two-column table
  with the answers showing, which is the one thing a flashcard must not be.
* `checklist` -- **live**, and not persisted. Ticking is a record within the
  sitting; `localStorage` is unavailable or per-file-path on `file://`
  depending on the browser, so a box that remembered on one machine and
  forgot on another would be worse than one that never claimed to.
* `compare`, `definition`, `evidence` -- **static, carrying their content**.
  `compare`'s rows are the author's own text and were never a query; only its
  column heads were looked up, and the lookup result here is a link rather
  than a fetch. `definition` and `evidence` are *entirely* query, and they
  are the two that matter most: see "Provenance" below.
* `graph`, `timeline` -- **drawn, server-side, as inline SVG**. Discussed
  under "Why SVG here and canvas there".
* `explorer` -- **cannot survive, and says so by name.** It is a timeline the
  reader re-runs against a live project; there is no honest freeze of "run
  this query again". It renders the author's prompt, the parameters that were
  fixed, the axes the reader was invited to move, and a link to the live
  instance. Never an empty box -- the convention
  `presentation/lesson/ExplorerWidget.tsx:81` states in those words: named as
  missing rather than quoted as empty.

An unknown or unparsed component renders its source in a `<pre>` with the
parse errors above it. This export is taken from the author's view, so the
raw body is there to show; hiding a broken block would make an export of a
broken lesson look like an export of a working one.

## The answer key is in the file

`components.project(view="learner")` exists to keep answers off the wire, and
this file defeats it: an `mcq` that grades offline must carry `correct`, and
a reader who opens View Source can read it. That is not a leak this module
could close -- there is no server to ask, which is the entire premise -- so
it is a property of the artifact instead. What leaves here is a **teaching**
copy, not an exam paper, and the README-equivalent block at the top of the
page says so to the person holding it. If an ungraded copy is ever wanted the
honest form is a separate export that renders items without their keys, not a
flag on this one that a caller could forget.

## Provenance

A citation that degrades to a bare id is a failure, so nothing here renders
one. Three things carry provenance and all three are resolved at export:

* `evidence` names a source and a character range. The range is *quoted into
  the page* -- the actual bytes, from `read_document` -- so the reader can
  compare the claim against the passage without leaving the file, which is
  the entire reason the widget exists.
* `definition` is this project's grounded account of an entity, and its
  citations are quoted the same way.
* `[[src:<id>]]` in prose becomes a link whose visible text is the source's
  **title**, not its id, because an id is a string only this system can
  resolve and the page has left this system.

Every one of them also links back to the instance it was exported from, so a
reader who wants the whole source has somewhere to go. The base URL is the
one the export request arrived on -- honest about what it is, which is "the
address you reached this server at", and useless if that was `localhost`.
That is a real limit and it is stated on the page rather than hidden: a link
to `http://localhost:8000` in a mail is a link to the reader's own machine.

## Why SVG here and canvas there

`graph_html.py` chose canvas and gave its reasons: 900 nodes and 1,400 edges
is 2,300 DOM elements, laid out slowly and tripling the file. None of that
applies to a lesson graph, which is one entity's neighbourhood at depth 1 --
a couple of dozen nodes, several to a page, inside a document that scrolls.
Canvas here would cost a resize observer, a device-pixel-ratio dance and a
`<script>` per figure to draw something a browser can render from markup with
no JavaScript at all, and would print as a blank rectangle. SVG also keeps
the labels as selectable, searchable text, which in a *document* is worth
more than it was in a viewer.

What is reused is the part worth reusing: `compute_layout` through
`build_export`, the same force-directed pass the graph export runs, so a
lesson figure and the whole-graph file place the same neighbourhood the same
way. And the palette is `graph_html.py`'s copy of the console's `--k-*`
tokens, imported from there rather than copied a third time.

## No external anything, and no media

No CDN, no web font, no remote image, no `fetch`. The font stack is system
faces. **No stored medium is embedded at all**, which is a decision rather
than an omission: a citation into a video would need the video, and a
90-second clip at any watchable bitrate is several megabytes of base64 in a
file that is meant to survive a mail gateway.

What that costs, stated rather than discovered: a citation into a *media*
source resolves to a named absence. `CorpusReadPort.read_document` promises
text and a media source has none to give it, so the quote is empty and the
widget says which source it could not read. That is honest and it is not
good -- the reader is told a passage exists and cannot see it, where a
transcript excerpt would have served. Left undone deliberately; the shape of
the fix is to quote the *derived transcript* a perception pass stored beside
the medium, which is a text source and would need no bytes embedded at all.

The one size ceiling this module does enforce is on quoted text --
`MAX_QUOTE_CHARS` -- because a citation whose range was typed with an extra
digit would otherwise paste an entire document into a lesson.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from research_team.application.components import (
    REGISTRY,
    Block,
    ComponentBlock,
    Document,
    MarkdownBlock,
    parse_document,
)
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

# --- what a course is, once it has been read ------------------------------


@dataclass(frozen=True)
class CourseFile:
    """One authored markdown artifact, parsed.

    `title` is the first `# heading` or the frontmatter's, falling back to the
    filename -- a lesson with neither still needs something in the table of
    contents, and "lesson-03.md" is a worse label than nothing only if you
    have never had to find lesson three.
    """

    path: str
    title: str
    document: Document


@dataclass(frozen=True)
class CourseArea:
    """One learning area: its Understanding by Design unit and its lessons."""

    slug: str
    title: str
    unit: CourseFile | None
    lessons: tuple[CourseFile, ...] = ()


@dataclass(frozen=True)
class CourseBook:
    """Everything the page renders, with every live read already made.

    `resolutions` is keyed by `f"{file path}#{component id}"` rather than by
    component id alone. Ids are unique within a document and nothing enforces
    it across a course, so two lessons that both call a definition block
    `nicene-christianity` are a real and ordinary thing to write -- and would
    otherwise share one resolution, which is a wrong figure rather than a
    missing one.
    """

    name: str
    project_id: UUID
    origin: str
    exported_at: str
    run: Mapping[str, Any]
    #: One plain sentence about how this run settled, and the targets it never
    #: started. Passed in rather than derived here: `export.py` owns the
    #: status vocabulary for both formats, and a page that worked it out
    #: separately could describe the same run differently from the zip.
    status_sentence: str = ""
    never_started: tuple[str, ...] = ()
    overview: CourseFile | None = None
    areas: tuple[CourseArea, ...] = ()
    resolutions: Mapping[str, Resolution] = field(default_factory=dict)
    #: Source id to title, for expanding `[[src:...]]` in prose. Absent ids
    #: are not an error: the reference renders with the id as its own label,
    #: which is what the console does for a source it cannot name either.
    sources: Mapping[str, str] = field(default_factory=dict)


def resolution_key(path: str, component_id: str) -> str:
    """The `CourseBook.resolutions` key. One function so the builder and the
    renderer cannot disagree about it -- a mismatch here renders every
    resolved widget as an absence, which looks exactly like a project with no
    graph."""
    return f"{path}#{component_id}"


# --- markdown -------------------------------------------------------------
#
# Rendered here rather than in the browser, because the alternative is
# shipping a markdown library in every exported file: `marked` is around 40 kB
# minified, repeated in every course anyone ever exports, to parse text the
# server has already read. What this costs is that the subset below is *this
# module's* markdown rather than CommonMark, and the gap is stated in
# `_markdown`'s docstring rather than left for a reader to discover.

_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}

#: The same charset `references.ts` accepts, deliberately. A reference this
#: module expanded and the console did not (or the reverse) would mean one of
#: the two renderings of a lesson is quietly missing links.
_REFERENCE = re.compile(r"\[\[src:([A-Za-z0-9_.#:-]+)(?:@(\d+)(?:-(\d+))?)?\]\]")

_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(\S(?:[^*]*\S)?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(\S(?:[^*]*\S)?)\*(?!\w)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")


def esc(value: object) -> str:
    """HTML-escape anything, including the `None` a missing YAML field is."""
    return "".join(_ESCAPE.get(ch, ch) for ch in str("" if value is None else value))


class _Inline:
    """Inline markdown, one paragraph's worth.

    A placeholder pass rather than nested regex substitution. Each construct
    that produces markup is replaced by a `\\x00N\\x00` token holding the
    finished HTML, and the tokens are substituted back at the end -- so the
    `*` inside a generated `<a href="...">` can never be read as emphasis by
    the italic pass that follows it. Nesting regexes was the first draft and
    it turned a link whose URL contained an underscore into a link with an
    `<em>` in the href.
    """

    def __init__(self, book: "CourseBook") -> None:
        self._book = book
        self._parts: list[str] = []

    def _stash(self, markup: str) -> str:
        self._parts.append(markup)
        return f"\x00{len(self._parts) - 1}\x00"

    def render(self, source: str) -> str:
        self._parts = []
        text = _INLINE_CODE.sub(
            lambda m: self._stash(f"<code>{esc(m.group(1))}</code>"), source
        )
        text = _REFERENCE.sub(self._reference, text)
        text = _LINK.sub(self._link, text)
        text = esc(text)
        text = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
        text = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: self._parts[int(m.group(1))], text)

    def _reference(self, match: re.Match[str]) -> str:
        """`[[src:id@start-end]]`, as a titled link to the live instance.

        The visible text is the source's *title* where the export could find
        one. That is the whole requirement: a reader holding this file cannot
        resolve `wiki-trajan` into anything, and a citation they cannot read
        is a citation that is not there.
        """
        source_id, start, _end = match.group(1), match.group(2), match.group(3)
        title = self._book.sources.get(source_id, source_id)
        moment = f" @ {_clock(int(start))}" if start else ""
        href = _doc_href(self._book, source_id, int(start) if start else None)
        return self._stash(f'<a class="ref" href="{esc(href)}">{esc(title)}{esc(moment)}</a>')

    def _link(self, match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        # `http`, `https`, `#` and `mailto` only. A `javascript:` URL in a
        # model-written lesson is not a threat anyone has seen, and this file
        # is opened from `file://` where a page has more reach than one served
        # over http -- which is exactly where not having to think about it is
        # worth four lines.
        if not re.match(r"\A(?:https?://|mailto:|#|/)", href):
            return self._stash(esc(label or href))
        return self._stash(f'<a href="{esc(href)}">{esc(label) or esc(href)}</a>')


def _markdown(source: str, book: CourseBook) -> str:
    """A line-oriented subset of markdown: headings, paragraphs, both list
    kinds, blockquotes, fenced code, horizontal rules, and the inline set
    `_Inline` handles.

    **Tables, setext headings, nested lists, reference links, footnotes and
    HTML passthrough are not supported**, and are listed rather than hidden.
    A nested list renders flat; a table renders as its pipe characters. Both
    are things the authoring prompts do not ask for and neither is silent --
    what a reader sees is the source text, which is reportable.

    HTML in the source is escaped rather than passed through, which is the
    one deviation from markdown that is a decision and not a limitation:
    lesson prose is model output, and this file runs from `file://`.
    """
    inline = _Inline(book)
    out: list[str] = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]

        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            body: list[str] = []
            index += 1
            while index < len(lines) and not re.match(
                rf"^\s*{marker}{{3,}}\s*$", lines[index]
            ):
                body.append(lines[index])
                index += 1
            index += 1
            out.append(f"<pre><code>{esc(chr(10).join(body))}</code></pre>")
            continue

        if not line.strip():
            index += 1
            continue

        if _RULE.match(line):
            out.append("<hr>")
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            # Demoted by two: an area's own `<h2>` and a lesson's `<h3>` are
            # the page's structure, and a lesson whose body opens with `# `
            # would otherwise plant a second `<h1>` in the middle of the
            # document and break the outline for anyone reading with a screen
            # reader's heading list.
            tag = f"h{min(level + 2, 6)}"
            out.append(f"<{tag}>{inline.render(heading.group(2))}</{tag}>")
            index += 1
            continue

        if line.lstrip().startswith(">"):
            quoted: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quoted.append(lines[index].lstrip()[1:].lstrip())
                index += 1
            out.append(f"<blockquote><p>{inline.render(' '.join(quoted))}</p></blockquote>")
            continue

        matcher = (
            _BULLET if _BULLET.match(line) else _ORDERED if _ORDERED.match(line) else None
        )
        if matcher is not None:
            tag = "ul" if matcher is _BULLET else "ol"
            items: list[str] = []
            while index < len(lines) and (found := matcher.match(lines[index])):
                items.append(f"<li>{inline.render(found.group(1))}</li>")
                index += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        paragraph: list[str] = []
        while (
            index < len(lines) and lines[index].strip() and not _is_block_start(lines[index])
        ):
            paragraph.append(lines[index].strip())
            index += 1
        out.append(f"<p>{inline.render(' '.join(paragraph))}</p>")
    return "".join(out)


def _is_block_start(line: str) -> bool:
    """Whether a line inside a paragraph ends it. Without this a bullet list
    that follows a sentence with no blank line between them -- which is what
    a model writes about a third of the time -- is swallowed into the
    paragraph and renders as text beginning with a hyphen."""
    return bool(
        _HEADING.match(line)
        or _BULLET.match(line)
        or _ORDERED.match(line)
        or _FENCE.match(line)
        or _RULE.match(line)
        or line.lstrip().startswith(">")
    )


# --- links back to the instance -------------------------------------------

# Link generation and formatting helpers (_project_href, _doc_href, _clock, _quote)
# have been moved to `course_html_widgets.py` and re-exported at module top.


# --- components -----------------------------------------------------------


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


# Interactive course widget renderers (_head, _absent, _mcq, _cloze,
# _flashcards, _checklist, _compare, _definition, _evidence, _passages,
# _explorer) have been moved to `course_html_widgets.py` and re-exported at module top.


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


# --- figures --------------------------------------------------------------

# SVG figure generation (graph neighbourhoods and timeline bars) has been moved
# to `course_html_figures.py` and re-exported at module top for backward
# compatibility.


# --- the page -------------------------------------------------------------


def _blocks(course_file: CourseFile, book: CourseBook) -> str:
    """A file's blocks, with its own opening title heading dropped.

    `course_authoring`'s prompts ask for `# <title>` as the first line of
    every unit and lesson, and this page already prints that title as the
    section's own heading -- so rendering the body verbatim shows it twice,
    once as an `<h2>` and again as an `<h4>` immediately underneath. Found by
    opening a real export; it is invisible from a test that asserts the title
    is present, because it is present, twice.

    Dropped only when the heading *matches* the title, so a lesson whose first
    heading says something else keeps it.
    """
    out: list[str] = []
    for index, block in enumerate(course_file.document.blocks):
        if index == 0 and isinstance(block, MarkdownBlock):
            block = MarkdownBlock(_without_title(block.text, course_file.title))
            if not block.text.strip():
                continue
        out.append(_render_block(block, book, course_file.path))
    return "".join(out)


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


def _render_block(block: Block, book: CourseBook, path: str) -> str:
    if isinstance(block, MarkdownBlock):
        return _markdown(block.text, book)
    return _component(block, book, path)


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


def _anchor(slug: str, lesson: int | None = None) -> str:
    """Anchors built from the slug and an index, never from a title.

    A title is model output and would put arbitrary text in a fragment id;
    an index is a number. The cost is that a bookmark into lesson 3 points at
    whatever is third after a re-authoring run, which is the right trade for
    a document whose lessons are numbered in teaching order anyway.
    """
    stem = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") or "area"
    return stem if lesson is None else f"{stem}-l{lesson + 1}"


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

    # A partial course must not look complete, which is the rule the zip
    # already follows (`export.py:_status_suffix`). A single page is *more*
    # exposed to it, not less: there is nothing to unzip, so a reader who was
    # forwarded the file sees only what the page itself says.
    # Through `_Inline`, not `esc`: the sentence is the same string the zip's
    # README carries, and it is markdown -- `**This run was interrupted**`
    # escaped rather than rendered puts literal asterisks in front of the
    # reader on the one line that has to be read as written.
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


# --- reading the live system ----------------------------------------------


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
            # A corpus that cannot be listed costs every `[[src:...]]` its
            # title and nothing else; the reference still links, labelled
            # with its id. Losing the whole export over it would be worse.
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


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  /* The console's `tokens.css` values, copied -- `graph_html.py`'s reasoning
     applies unchanged: this file cannot read a stylesheet, and a reader who
     has learnt the console's colours should not learn a second scheme. */
  :root {
    --bg: #0b0e11; --panel: #111418; --line: #232a33;
    --fg: #d7dee7; --fg-dim: #a7b1bd; --accent: #e2a457;
    --edge: rgba(138,149,163,0.35); --ok: #5ec98a; --no: #e2705a;
    --measure: 42rem;
  }
  /* Light is the default a phone in daylight wants and dark is what a laptop
     at night wants, so the page follows the reader rather than choosing. Both
     palettes are declared; neither is a filter over the other. */
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #fbfaf8; --panel: #ffffff; --line: #e2ddd4;
      --fg: #22262b; --fg-dim: #5f6a75; --accent: #9a5f14;
      --edge: rgba(95,106,117,0.45);
      /* Darkened from the dark palette's #5ec98a/#e2705a, which are chosen
         to sit on #0b0e11 and are unreadable on white. A verdict a reader
         cannot read is a verdict that did not happen. */
      --ok: #17703f; --no: #a8321c;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 16px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
          Helvetica, Arial, sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  .wrap { max-width: var(--measure); margin: 0 auto; padding: 1.5rem 1.1rem 6rem; }
  h1 { font-size: 1.6rem; line-height: 1.25; margin: 0 0 .3rem; }
  h2 { font-size: 1.3rem; margin: 2.6rem 0 .6rem; padding-top: 1.4rem;
       border-top: 1px solid var(--line); }
  h3 { font-size: 1.1rem; margin: 2rem 0 .4rem; }
  h4, h5, h6 { font-size: 1rem; margin: 1.4rem 0 .3rem; }
  p, ul, ol, blockquote, table { margin: 0 0 .9rem; }
  a { color: var(--accent); }
  code { font: .88em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  pre { background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
        padding: .7rem .8rem; overflow-x: auto; }
  blockquote { border-left: 3px solid var(--line); margin-left: 0; padding-left: .9rem;
               color: var(--fg-dim); }
  hr { border: 0; border-top: 1px solid var(--line); margin: 1.6rem 0; }
  .settled { margin: .75rem 0 0; border-left: 3px solid var(--accent);
             padding-left: .6rem; font-size: .9rem; }
  .meta { color: var(--fg-dim); font-size: .85rem; margin: 0 0 .2rem; }
  .quiet { color: var(--fg-dim); font-size: .82rem; margin: .4rem 0 0; }
  nav { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
        padding: .8rem 1rem .8rem 1.6rem; margin: 1.4rem 0; }
  nav ol { margin: 0; padding-left: .6rem; }
  nav ul { margin: .2rem 0 .4rem; padding-left: 1rem; list-style: none; }
  nav ul a { color: var(--fg-dim); }
  section { scroll-margin-top: 1rem; }
  article { scroll-margin-top: 1rem; }
  .unit { color: var(--fg); }

  /* Widgets. One panel treatment for all ten, so a reader learns the frame
     once and the differences inside it read as differences of kind. */
  .w { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
       padding: .9rem 1rem; margin: 1.2rem 0; }
  .w-kind { text-transform: uppercase; letter-spacing: .08em; font-size: .68rem;
            color: var(--fg-dim); margin: 0 0 .35rem; }
  .w-title { font-weight: 600; margin: 0 0 .5rem; }
  .w p:last-child { margin-bottom: 0; }
  .absent { color: var(--fg-dim); border-left: 3px solid var(--accent);
            padding-left: .8rem; margin: .5rem 0 0; font-size: .92rem; }
  .live { margin: .7rem 0 0; font-size: .88rem; }
  button { font: inherit; color: var(--fg); background: transparent;
           border: 1px solid var(--line); border-radius: 6px; padding: .35rem .8rem;
           cursor: pointer; }
  button:hover { border-color: var(--accent); }
  input[type=text] { font: inherit; color: var(--fg); background: var(--bg);
    border: 1px solid var(--line); border-radius: 4px; padding: .1rem .35rem; }
  .opts, .cards, .checks { list-style: none; padding: 0; margin: .6rem 0; }
  .opts > li, .checks > li { margin: .3rem 0; }
  .opts label, .checks label { display: flex; gap: .55rem; align-items: baseline;
                               cursor: pointer; }
  .fb, .note { margin: .2rem 0 .4rem 1.7rem; font-size: .9rem; color: var(--fg-dim); }
  .verdict { margin: .6rem 0 0; font-weight: 600; }
  .verdict.right { color: var(--ok); }
  .verdict.wrong { color: var(--no); }
  .rationale { margin-top: .7rem; border-top: 1px solid var(--line); padding-top: .6rem; }
  .cloze-text { line-height: 2.2; }
  .blank.right { border-color: var(--ok); }
  .blank.wrong { border-color: var(--no); }
  .revealed { color: var(--ok); font-size: .85em; margin-left: .25rem; }
  .flip { width: 100%; text-align: left; }
  .flip[aria-expanded=true] { border-color: var(--accent); }
  .back { padding: .5rem .8rem; border-left: 3px solid var(--accent); margin: .3rem 0 .6rem; }
  .req { color: var(--fg-dim); font-size: .78rem; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: .93rem; }
  th, td { border: 1px solid var(--line); padding: .35rem .55rem; text-align: left;
           vertical-align: top; }
  thead th { background: var(--bg); }
  .quotes figure { margin: .7rem 0 0; }
  .quotes blockquote { border-left: 3px solid var(--accent); font-size: .95rem;
                       color: var(--fg); margin: 0; }
  figcaption { color: var(--fg-dim); font-size: .82rem; margin-top: .25rem; }
  .figure { overflow-x: auto; }
  /* `min-width` with the scrolling wrapper above it, and it is what makes
     these figures readable on a phone. A 1,000-unit viewBox scaled to a
     375px column puts the node labels at about four device pixels -- present,
     selectable, and unreadable. Below 30rem the figure scrolls sideways at a
     legible size instead; above it, `width: 100%` governs as before.
     Measured in Chromium at 390x844, not reasoned. */
  .figure svg { display: block; width: 100%; min-width: 30rem; height: auto;
    max-height: 70vh; }
  .params { color: var(--fg-dim); font-size: .88rem; }
  @media (max-width: 30rem) { .wrap { padding: 1rem .8rem 4rem; } h1 { font-size: 1.35rem; } }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>__TITLE__</h1>
  <p class="meta">Exported __EXPORTED__ from project __PROJECT__, authoring run __RUN__.</p>
  <p class="meta">This file needs no server and no network. Its links point back at
     <code>__ORIGIN__</code>, which is the address this export was requested from — they
     only work for someone who can reach it.</p>
  <p class="meta">A teaching copy: the questions grade themselves here, which means the
     answers are in the file. Do not use it as an exam paper.</p>
  __SETTLED__
  __NEVERSTARTED__
  __NOTWRITTEN__
</header>
__NAV__
__BODY__
</div>
<script>
(function () {
  'use strict';

  /* `grading.py`'s `normalize_answer`, in the browser. Case and spacing are
     typing; word choice is knowledge. It is not byte-identical: Python's
     `casefold` folds a handful of pairs (German sharp s, for one) that
     `toLowerCase` leaves alone, so a cloze answer separated from a reader's
     only by such a pair is marked wrong here and right on the server. Stated
     rather than fixed -- the fix is a case-folding table in every exported
     file. */
  function normalise(value) {
    return String(value == null ? '' : value).trim().replace(/\s+/g, ' ').toLowerCase();
  }

  document.querySelectorAll('.w-mcq').forEach(function (widget) {
    var key = JSON.parse(widget.getAttribute('data-key'));
    var verdict = widget.querySelector('.verdict');
    var rationale = widget.querySelector('.rationale');
    widget.querySelector('.check').addEventListener('click', function () {
      var picked = [];
      widget.querySelectorAll('input').forEach(function (input, index) {
        if (input.checked) picked.push(index);
      });
      /* Set equality, not overlap -- `_grade_mcq`'s reasoning, which is that
         anything looser marks a reader who ticked everything as correct. */
      var right = picked.length === key.length &&
        picked.every(function (i) { return key.indexOf(i) !== -1; });
      widget.querySelectorAll('.fb').forEach(function (note, index) {
        note.hidden = picked.indexOf(index) === -1;
      });
      verdict.textContent = right ? 'Correct.'
        : picked.length === 0 ? 'Nothing selected.' : 'Not quite.';
      verdict.className = 'verdict ' + (right ? 'right' : 'wrong');
      verdict.hidden = false;
      if (rationale) rationale.hidden = false;
    });
  });

  document.querySelectorAll('.w-cloze').forEach(function (widget) {
    var verdict = widget.querySelector('.verdict');
    widget.querySelector('.check').addEventListener('click', function () {
      var hits = 0, total = 0;
      widget.querySelectorAll('.blank').forEach(function (input) {
        var expected = input.getAttribute('data-answer');
        var right = input.value.trim() !== '' &&
          normalise(input.value) === normalise(expected);
        input.classList.remove('right', 'wrong');
        input.classList.add(right ? 'right' : 'wrong');
        total += 1;
        if (right) hits += 1;
        /* The answer is revealed per blank, having been attempted -- including
           a blank left empty, because the reader submitted and the item is
           spent. `_grade_cloze` makes the same call. */
        var after = input.nextElementSibling;
        if (!after || !after.classList.contains('revealed')) {
          var shown = document.createElement('span');
          shown.className = 'revealed';
          shown.textContent = expected;
          input.parentNode.insertBefore(shown, input.nextSibling);
        }
      });
      verdict.textContent = hits + ' of ' + total + ' correct.';
      verdict.className = 'verdict ' + (hits === total ? 'right' : 'wrong');
      verdict.hidden = false;
    });
  });

  document.querySelectorAll('.flip').forEach(function (button) {
    button.addEventListener('click', function () {
      var open = button.getAttribute('aria-expanded') === 'true';
      button.setAttribute('aria-expanded', open ? 'false' : 'true');
      button.nextElementSibling.hidden = open;
    });
  });
})();
</script>
</body>
</html>
"""
