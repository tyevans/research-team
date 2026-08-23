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

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from research_team.application.components import (
    REGISTRY,
    Block,
    ComponentBlock,
    Document,
    MarkdownBlock,
    parse_document,
)
from research_team.application.entity_definitions import Citation
from research_team.application.graph_export import ExportGraph, build_export
from research_team.application.timeline_read import TimelineBand, TimelineInterval
from research_team.interfaces.web.graph_html import color_for_type

#: How much of a cited range is quoted into the page. Generous next to the
#: passages this system actually produces -- a grounding chunk is a few
#: hundred characters -- and it is a typo guard rather than an editorial
#: judgement: `evidence` accepts offsets up to 100,000,000 (see the
#: registry), so a mistyped `end` would otherwise inline a whole document.
#: The cut is marked in the page with an ellipsis, never silent.
MAX_QUOTE_CHARS = 1_200

#: How many nodes a lesson figure draws. A `graph` component is one entity's
#: neighbourhood and the registry already caps its depth at
#: `MAX_NEIGHBORHOOD_DEPTH`, so this bites only on a hub entity -- where the
#: honest outcome is a truncated figure that says so, rather than a page of
#: overlapping dots. `build_export` carries the flag; `_svg_graph` prints it.
MAX_FIGURE_NODES = 60

#: How many bands a `timeline` figure draws, for `MAX_FIGURE_NODES`' reason.
#: The registry lets an author ask for up to `MAX_TIMELINE_BANDS` (1,000),
#: which is a legible request in a scrolling console pane and is not one in a
#: fixed-height figure inside a lesson.
MAX_FIGURE_BANDS = 40


# --- what a course is, once it has been read ------------------------------


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


def _project_href(book: CourseBook, facet: str, ident: str | None = None) -> str:
    """The console's own hash grammar (`routes.ts`'s `projectHref`), built
    against the origin this export was requested from.

    A fourth copy of that grammar and it is unavoidable: this file is opened
    where the console is not, so it cannot import the builder, and a link
    that dropped the `#/p/<id>` prefix would land a reader on the project
    list instead of on the thing they clicked. `routes.ts` is the authority;
    a change there needs a change here, which is why the shape is written out
    rather than assembled from parts.
    """
    tail = f"/{facet}/{_quote(ident)}" if ident else f"/{facet}"
    return f"{book.origin}/#/p/{_quote(str(book.project_id))}{tail}"


def _doc_href(book: CourseBook, source_id: str, at_seconds: int | float | None) -> str:
    href = _project_href(book, "doc", source_id)
    return f"{href}?t={int(at_seconds)}" if at_seconds else href


def _quote(value: str) -> str:
    """`encodeURIComponent`, near enough, for a path segment in a hash."""
    safe = "-_.!~*'()"
    return "".join(
        ch
        if (ch.isalnum() and ch.isascii()) or ch in safe
        else "".join(f"%{byte:02X}" for byte in ch.encode())
        for ch in value
    )


def _clock(seconds: int) -> str:
    """`252` as `4:12`. The model is told to write seconds precisely because a
    clock is ambiguous to parse; a reader wants the clock back."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


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


def _absent(what: str, detail: str, href: str | None = None) -> str:
    """A named absence: what is missing, why, and where to see it live.

    `presentation/lesson/ExplorerWidget.tsx:81`'s convention, kept
    deliberately -- name the missing thing, never quote it as empty. An empty
    box in an exported lesson is indistinguishable from an authoring mistake,
    and the reader has no way to ask which it was.
    """
    link = f' <a href="{esc(href)}">See it on the live project.</a>' if href else ""
    return f'<p class="absent"><strong>{esc(what)}</strong> — {esc(detail)}{link}</p>'


def _head(label: str, title: object = None) -> str:
    """A widget's kind, and its own title where it has one.

    The kind is always printed. In the console a widget is recognisable by
    its chrome; here every one of the ten sits in the same panel, so a reader
    who cannot see the word "Question" has no way to tell an mcq from a
    checklist until they have read it.
    """
    kind = f'<p class="w-kind">{esc(label)}</p>'
    if not title:
        return kind
    return f'{kind}<p class="w-title">{esc(title)}</p>'


def _mcq(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
    options = [o for o in block.data.get("options", []) if isinstance(o, Mapping)]
    multiple = bool(block.data.get("multiple"))
    kind = "checkbox" if multiple else "radio"
    name = f"q-{esc(block.id)}"
    rows = []
    for index, option in enumerate(options):
        feedback = option.get("feedback")
        rows.append(
            f'<li><label><input type="{kind}" name="{name}" value="{index}">'
            f"<span>{esc(option.get('text'))}</span></label>"
            # A `<div>`, not a `<p>`. `_markdown` returns block markup, and a
            # `<p>` wrapping a `<p>` is closed by the parser at the inner
            # one's start tag -- which puts the feedback *outside* the hidden
            # element and prints the answer beside the options. Found by
            # opening the file: the `hidden` attribute is in the markup
            # exactly as a test asserted, on an element the feedback is no
            # longer inside.
            + (
                f'<div class="fb" hidden>{_markdown(str(feedback), book)}</div>'
                if feedback
                else ""
            )
            + "</li>"
        )
    # The key travels as JSON in a data attribute rather than as a `correct`
    # flag per option, so the grading code below is one comparison rather than
    # a DOM walk -- and so that the attribute is the one obvious place a
    # reader who goes looking will find it, instead of it being spread over
    # every option where it might be mistaken for a rendering detail.
    key = json.dumps([i for i, o in enumerate(options) if o.get("correct") is True])
    rationale = block.data.get("rationale")
    return (
        f'<div class="w w-mcq" data-key=\'{esc(key)}\' data-multiple="{int(multiple)}">'
        f"{_head('Question')}"
        f"{_markdown(str(block.data.get('prompt', '')), book)}"
        f'<ol class="opts">{"".join(rows)}</ol>'
        f'<button type="button" class="check">Check</button>'
        f'<p class="verdict" hidden></p>'
        + (
            f'<div class="rationale" hidden><p class="w-kind">Why</p>'
            f"{_markdown(str(rationale), book)}</div>"
            if rationale
            else ""
        )
        + "</div>"
    )


def _cloze(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
    pieces = []
    for segment in block.data.get("segments", []):
        if "blank" in segment:
            hint = segment.get("hint")
            pieces.append(
                f'<input class="blank" type="text" size="14" autocomplete="off"'
                f' aria-label="Blank {int(segment["blank"]) + 1}"'
                f' data-answer="{esc(segment.get("answer"))}"'
                + (f' placeholder="{esc(hint)}"' if hint else "")
                + ">"
            )
        else:
            pieces.append(esc(segment.get("text", "")).replace("\n", "<br>"))
    return (
        '<div class="w w-cloze">'
        f"{_head('Fill the blanks')}"
        f'<p class="cloze-text">{"".join(pieces)}</p>'
        '<button type="button" class="check">Check</button>'
        '<p class="verdict" hidden></p>'
        "</div>"
    )


def _flashcards(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
    cards = []
    for card in block.data.get("cards", []):
        if not isinstance(card, Mapping):
            continue
        cards.append(
            '<li class="card"><button type="button" class="flip" aria-expanded="false">'
            f"{esc(card.get('front'))}</button>"
            f'<div class="back" hidden>{_markdown(str(card.get("back", "")), book)}</div></li>'
        )
    return (
        '<div class="w w-cards">'
        f"{_head('Flashcards', block.data.get('title'))}"
        f'<ul class="cards">{"".join(cards)}</ul>'
        "</div>"
    )


def _checklist(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
    items = []
    for item in block.data.get("items", []):
        if not isinstance(item, Mapping):
            continue
        note = item.get("note")
        required = ' <span class="req">required</span>' if item.get("required") else ""
        items.append(
            f'<li><label><input type="checkbox"><span>{esc(item.get("text"))}'
            f"{required}</span></label>"
            + (f'<p class="note">{esc(note)}</p>' if note else "")
            + "</li>"
        )
    return (
        '<div class="w w-check">'
        f"{_head('Checklist', block.data.get('title'))}"
        f'<ul class="checks">{"".join(items)}</ul>'
        '<p class="quiet">Ticks are not saved; this file has nowhere to keep them.</p>'
        "</div>"
    )


def _compare(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
    names = [str(n) for n in block.data.get("entities", [])]
    found = dict(resolved.columns)
    heads = []
    for name in names:
        entity_id = found.get(name)
        heads.append(
            "<th>"
            + (
                f'<a href="{esc(_project_href(book, "entity", entity_id))}">{esc(name)}</a>'
                if entity_id
                else esc(name)
            )
            + "</th>"
        )
    rows = []
    for row in block.data.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        cells = [str(c) for c in row.get("cells", [])]
        # Padded to the column count, matching the registry's promise that a
        # short row is fine and that the blank is itself the comparison.
        cells += [""] * (len(names) - len(cells))
        body = "".join(f"<td>{esc(cell)}</td>" for cell in cells[: len(names)])
        rows.append(f'<tr><th scope="row">{esc(row.get("label"))}</th>{body}</tr>')
    return (
        '<div class="w w-compare">'
        f"{_head('Compare')}"
        f'<div class="scroll"><table><thead><tr><td></td>{"".join(heads)}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        "</div>"
    )


def _definition(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
    name = str(block.data.get("entity", ""))
    if resolved.absent is not None:
        return (
            '<div class="w w-def">'
            f"{_head('Definition', name)}"
            + _absent(
                name,
                resolved.absent,
                _project_href(book, "entity", resolved.entity_id)
                if resolved.entity_id
                else None,
            )
            + "</div>"
        )
    href = _project_href(book, "entity", resolved.entity_id) if resolved.entity_id else None
    link = f'<p class="live"><a href="{esc(href)}">This entity, live</a></p>' if href else ""
    return (
        '<div class="w w-def">'
        f"{_head('Definition', name)}"
        f'<div class="def-text">{_markdown(resolved.definition or "", book)}</div>'
        f"{_passages(resolved.passages, book)}"
        f"{link}"
        "</div>"
    )


def _evidence(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
    claim = _markdown(str(block.data.get("claim", "")), book)
    body = (
        _absent("The cited passages", resolved.absent)
        if resolved.absent is not None
        else _passages(resolved.passages, book)
    )
    return (
        '<div class="w w-evidence">'
        f"{_head('Evidence')}"
        f'<div class="claim">{claim}</div>{body}</div>'
    )


def _passages(passages: Sequence[Passage], book: CourseBook) -> str:
    """Quoted source text, attributed and linked. The whole of provenance
    offline: the reader compares the claim against the bytes without leaving
    the file, and follows the link only if they want the rest."""
    if not passages:
        return _absent("No passage", "the export found nothing quotable behind this citation.")
    items = []
    for passage in passages:
        moment = f" · {_clock(int(passage.at_seconds))}" if passage.at_seconds else ""
        href = _doc_href(book, passage.source_id, passage.at_seconds)
        ellipsis = "…" if passage.truncated else ""
        items.append(
            "<figure><blockquote>"
            f"{esc(passage.text)}{ellipsis}</blockquote>"
            f'<figcaption><a href="{esc(href)}">{esc(passage.title)}</a>'
            f"{esc(moment)}</figcaption></figure>"
        )
    return f'<div class="quotes">{"".join(items)}</div>'


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


def _explorer(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
    """The one type that cannot be frozen, rendered as what it was.

    An explorer is an invitation to re-run a query with the controls moved,
    and there is no server here to re-run it against. Rendering the *last*
    result would be the tempting freeze and it is the dishonest one: it turns
    an invitation to look into a figure the author never chose, indexed under
    a prompt that asks the reader to change parameters they cannot see.

    So it renders the author's prompt (which is the part worth keeping -- the
    registry's craft note says the prompt is the whole difference between
    this and a timeline), the parameters that were fixed, the axes the reader
    was invited to move, and a link to where the controls exist.
    """
    fixed = [
        f"<li><code>{esc(key)}</code>: {esc(block.data.get(key))}</li>"
        for key in ("over", "entity_type", "from", "to", "limit")
        if block.data.get(key) not in (None, "")
    ]
    axes = ", ".join(str(a) for a in block.data.get("vary", []))
    return (
        '<div class="w w-explorer">'
        f"{_head('Explorer')}"
        f"{_markdown(str(block.data.get('prompt', '')), book)}"
        + _absent(
            "The controls",
            "an explorer is a query the reader re-runs, and this file has no server "
            f"to run it against. It was set to vary {axes or 'nothing'}.",
            _project_href(book, "timeline"),
        )
        + (f'<ul class="params">{"".join(fixed)}</ul>' if fixed else "")
        + "</div>"
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


def _svg_graph(graph: ExportGraph) -> str:
    """A neighbourhood, drawn from `compute_layout`'s coordinates.

    No JavaScript: the positions are decided on the server, so the figure is
    markup. That is what makes it print, survive a mail client's HTML
    sanitiser, and keep its labels as text a reader can select and a browser
    can find with ctrl-F.
    """
    nodes = graph.nodes
    if not nodes:
        return '<p class="absent">Nothing to draw.</p>'
    xs = [n.x for n in nodes]
    ys = [n.y for n in nodes]
    pad = 90.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    # `or 1`: a single node, or several at one point, spans zero -- and a
    # zero-width viewBox renders as nothing at all, which reads as a broken
    # export rather than as a small graph. The same guard `graph_html`'s
    # `fit` makes, for the same reason.
    width = (max_x - min_x) or 1.0
    height = (max_y - min_y) or 1.0
    at = {n.entity_id: (n.x, n.y) for n in nodes}

    edges = []
    for rel in graph.edges:
        a, b = at.get(rel.source_id), at.get(rel.target_id)
        if a is None or b is None:
            continue
        dash = ' stroke-dasharray="6 6"' if rel.inferred else ""
        edges.append(
            f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}"'
            f' stroke="var(--edge)" stroke-width="2"{dash}></line>'
        )

    marks = []
    for node in nodes:
        color = color_for_type(node.entity_type)
        # Hollow means synthesised rather than extracted, exactly as
        # `graph_html` draws it -- a class node that drew like an extracted
        # entity would assert a document said something no document said.
        fill = "none" if node.inferred else color
        label = node.name if len(node.name) <= 28 else node.name[:27] + "…"
        marks.append(
            f'<g><circle cx="{node.x:.1f}" cy="{node.y:.1f}" r="9" fill="{fill}"'
            f' stroke="{color}" stroke-width="3"></circle>'
            f'<text x="{node.x:.1f}" y="{node.y + 30:.1f}" text-anchor="middle"'
            f' font-size="20" fill="var(--fg)">{esc(label)}</text>'
            f"<title>{esc(node.name)} ({esc(node.entity_type)})</title></g>"
        )

    note = (
        '<p class="quiet">Truncated: part of a larger neighbourhood, not all of it.</p>'
        if graph.truncated
        else ""
    )
    return (
        '<div class="figure"><svg role="img" '
        f'aria-label="{esc(graph.title)} neighbourhood" '
        f'viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        'preserveAspectRatio="xMidYMid meet">'
        f"{''.join(edges)}{''.join(marks)}</svg></div>{note}"
    )


def _svg_timeline(bands: Sequence[TimelineBand], undated: int, truncated: bool) -> str:
    """Dated entities on a shared axis, as bars.

    Open ends run to the edge of the drawing rather than being clamped to the
    axis minimum, which is what `TimelineBand.start`'s docstring asks for: a
    `BEFORE` marker is a positive claim about an unbounded earlier time, and
    a bar that started at the leftmost dated thing would be a claim the
    extraction never made.
    """
    points: list[float] = []
    for band in bands:
        for value in (band.start, band.end):
            moment = _instant(value)
            if moment is not None:
                points.append(moment)
    if not points:
        return '<p class="absent">These bands carry no drawable dates.</p>'
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    row = 34.0
    left = 260.0
    inner = 700.0
    height = row * len(bands) + 30

    rows = []
    for index, band in enumerate(bands):
        start = _instant(band.start)
        end = _instant(band.end)
        x1 = left if start is None else left + (start - low) / span * inner
        x2 = left + inner if end is None else left + (end - low) / span * inner
        # A point-in-time band (a day-precision date, or one whose start and
        # end coincide) would otherwise be a zero-width rectangle, which
        # draws nothing. Three pixels is a tick, and reads as an instant.
        x2 = max(x2, x1 + 3.0)
        y = 8 + index * row
        color = color_for_type(band.entity_type)
        faint = ' opacity="0.55"' if band.uncertainty not in ("EXACT", "") else ""
        label = band.name if len(band.name) <= 30 else band.name[:29] + "…"
        rows.append(
            f'<text x="{left - 12:.0f}" y="{y + 15:.0f}" text-anchor="end" font-size="15"'
            f' fill="var(--fg)">{esc(label)}</text>'
            f'<rect x="{x1:.1f}" y="{y:.0f}" width="{x2 - x1:.1f}" height="18" rx="4"'
            f' fill="{color}"{faint}><title>{esc(band.name)} — {esc(band.extent)}'
            f" ({esc(band.uncertainty.lower())})</title></rect>"
            f'<text x="{x2 + 8:.1f}" y="{y + 14:.0f}" font-size="13"'
            f' fill="var(--fg-dim)">{esc(band.extent)}</text>'
        )

    notes = []
    if undated:
        notes.append(f"{undated} dated nothing, so they are not drawn.")
    if truncated:
        notes.append("Truncated: more bands fell in this window than are drawn.")
    tail = f'<p class="quiet">{esc(" ".join(notes))}</p>' if notes else ""
    return (
        '<div class="figure"><svg role="img" aria-label="Timeline" '
        f'viewBox="0 0 1060 {height:.0f}" preserveAspectRatio="xMidYMid meet">'
        f"{''.join(rows)}</svg></div>{tail}"
    )


def _instant(value: str | None) -> float | None:
    """An ISO instant as a sortable number, or `None` for an open end.

    Swallows a parse failure into `None` rather than raising: the band came
    from a projection over model-extracted dates, and an export that died on
    one malformed instant would lose a whole course to a single bad date.
    The band still renders -- with that end open, which is the honest reading
    of "we do not know where this edge is".
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, OSError, OverflowError):
        return None


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


def figure_graph(
    root: Any, entities: Sequence[Any], relationships: Sequence[Any]
) -> ExportGraph:
    """A neighbourhood laid out for a lesson figure.

    `build_export` does the capping, the orphan-edge drop and the `truncated`
    flag; all this adds is the root, which `Neighborhood` deliberately does
    not include in `entities` -- a figure that dropped the entity it is named
    after would be a drawing of everything around a hole. The same correction
    `export_graph` makes for `scope=entity`.
    """
    return build_export(
        (root, *entities),
        relationships,
        title=root.name,
        scope="lesson",
        limit=MAX_FIGURE_NODES,
    )


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


async def build_course_book(
    *,
    name: str,
    project_id: UUID,
    origin: str,
    run: Mapping[str, Any],
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
