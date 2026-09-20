"""Offline Markdown rendering and inline parsing for course HTML export.

Extracted from `course_html.py` to isolate the custom Markdown subset parsing,
HTML escaping, and inline token stashing logic for standalone course exports.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from research_team.interfaces.web.course_html_widgets import _clock, _doc_href

if TYPE_CHECKING:
    from research_team.interfaces.web.course_html import CourseBook

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


_esc = esc


class _Inline:
    """Inline markdown, one paragraph's worth.

    A placeholder pass rather than nested regex substitution. Each construct
    that produces markup is replaced by a `\x00N\x00` token holding the
    finished HTML, and the tokens are substituted back at the end -- so the
    `*` inside a generated `<a href="...">` can never be read as emphasis by
    the italic pass that follows it. Nesting regexes was the first draft and
    it turned a link whose URL contained an underscore into a link with an
    `<em>` in the href.
    """

    def __init__(self, book: CourseBook) -> None:
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


Inline = _Inline


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


is_block_start = _is_block_start


def render_markdown(source: str, book: CourseBook) -> str:
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


_markdown = render_markdown

__all__ = [
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
    "_RULE",
    "Inline",
    "_Inline",
    "_esc",
    "_is_block_start",
    "_markdown",
    "esc",
    "is_block_start",
    "render_markdown",
]
