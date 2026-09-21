"""Interactive course widget rendering for offline HTML exports.

Extracted from `course_html.py` to isolate widget DOM markup generation
(questions, flashcards, checklists, comparisons, definitions, evidence citations,
and explorer placeholders) from overall course page assembly and graph/timeline figures.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from research_team.interfaces.web.course_html_figures import esc
from research_team.platform.components import ComponentBlock

if TYPE_CHECKING:
    from research_team.interfaces.web.course_html import CourseBook, Passage, Resolution

_esc = esc


def _quote(value: str) -> str:
    """`encodeURIComponent`, near enough, for a path segment in a hash."""
    safe = "-_.!~*'()"
    return "".join(
        ch
        if (ch.isalnum() and ch.isascii()) or ch in safe
        else "".join(f"%{byte:02X}" for byte in ch.encode())
        for ch in value
    )


def project_href(book: CourseBook, facet: str, ident: str | None = None) -> str:
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


_project_href = project_href


def doc_href(book: CourseBook, source_id: str, at_seconds: int | float | None) -> str:
    href = project_href(book, "doc", source_id)
    return f"{href}?t={int(at_seconds)}" if at_seconds else href


_doc_href = doc_href


def format_clock(seconds: int) -> str:
    """`252` as `4:12`. The model is told to write seconds precisely because a
    clock is ambiguous to parse; a reader wants the clock back."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


_clock = format_clock


def render_absent(what: str, detail: str, href: str | None = None) -> str:
    """A named absence: what is missing, why, and where to see it live.

    `presentation/lesson/ExplorerWidget.tsx:81`'s convention, kept
    deliberately -- name the missing thing, never quote it as empty. An empty
    box in an exported lesson is indistinguishable from an authoring mistake,
    and the reader has no way to ask which it was.
    """
    link = f' <a href="{esc(href)}">See it on the live project.</a>' if href else ""
    return f'<p class="absent"><strong>{esc(what)}</strong> — {esc(detail)}{link}</p>'


_absent = render_absent


def render_head(label: str, title: object = None) -> str:
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


_head = render_head


def _markdown(source: str, book: Any) -> str:
    from research_team.interfaces.web.course_html import _markdown as render_md

    return render_md(source, book)


def render_mcq(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
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


_mcq = render_mcq


def render_cloze(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
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


_cloze = render_cloze


def render_flashcards(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
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


_flashcards = render_flashcards


def render_checklist(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
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


_checklist = render_checklist


def render_compare(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
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


_compare = render_compare


def render_definition(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
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


_definition = render_definition


def render_evidence(block: ComponentBlock, resolved: Resolution, book: CourseBook) -> str:
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


_evidence = render_evidence


def render_passages(passages: Sequence[Passage], book: CourseBook) -> str:
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


_passages = render_passages


def render_explorer(block: ComponentBlock, _resolved: Resolution, book: CourseBook) -> str:
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


_explorer = render_explorer

__all__ = [
    "_absent",
    "_checklist",
    "_clock",
    "_cloze",
    "_compare",
    "_definition",
    "_doc_href",
    "_evidence",
    "_explorer",
    "_flashcards",
    "_head",
    "_mcq",
    "_passages",
    "_project_href",
    "_quote",
    "doc_href",
    "esc",
    "format_clock",
    "project_href",
    "render_absent",
    "render_checklist",
    "render_cloze",
    "render_compare",
    "render_definition",
    "render_evidence",
    "render_explorer",
    "render_flashcards",
    "render_head",
    "render_mcq",
    "render_passages",
]
