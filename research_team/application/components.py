"""Interactive components in a markdown document, and the two views of them.

A course artifact is a markdown file written by a model. This module is what
lets one of those files carry a flashcard deck or a multiple-choice question
without ceasing to be a markdown file that a person can read, diff, and edit.

**The syntax is a fenced code block whose info string names a component.**

    ```component:mcq
    id: sev-classification-1
    prompt: |
      What severity should the Incident Commander declare?
    options:
      - text: "SEV-2"
        correct: true
    ```

Everything about that choice is in service of one constraint: *a model has to
author it reliably*. Fenced YAML is the single most practised shape in a
model's output distribution, which is why it beats `:::directives`, MyST
options blocks, and MDX -- all of which are more expressive and all of which
models get wrong more often. Expressiveness we can add later; a format the
author cannot hit is worthless at any level of expressiveness. The one real
cost is that fences do not nest, so components reference each other by `id`
rather than containing each other.

The `component:` prefix costs nine characters and buys a namespace. A bare
`mcq` info string could plausibly become a language tag in some highlighter,
and then a lesson's meaning would depend on which of the two shipped first.

**Parsing happens here, on the server, and not in the browser.** Four reasons,
and the first is the one that matters: validation exists to produce *authoring
feedback for the agent*, and the agent runs here. A browser-side parser cannot
tell the model it wrote bad YAML. Beyond that, withholding answers is only a
real boundary if the projection happens before the bytes leave; the client
currently ships zero third-party JavaScript and a YAML library would end that;
and files are immutable per event, so `(session, path, at)` is a perfect cache
key for a server-side parse.

**Degradation is per block and never per document.** Three outcomes, and only
the middle one is a failure:

1. *Valid* -- a component node.
2. *Known type, bad body* -- a component node carrying `errors`. The renderer
   shows the raw block and an error panel. **The rest of the document renders.**
3. *Unknown type* -- not an error at all. A code node with its info string
   preserved, which is exactly what the client does with an unrecognised fence
   today. This is the mermaid pattern's contract, and keeping it literally is
   what lets the registry grow without older readers calling newer lessons
   broken.

A lesson that renders eleven components and one error panel is enormously more
useful than a stack trace, so nothing in this module raises on bad input.

**Validation is hand-written rather than JSON Schema.** The errors here are
read by a language model and are the entire feedback loop for authoring, so
they say `options[1].text: expected text, got mapping` -- a path and a
diagnosis. JSON Schema's draft-2020-12 output is a tree of `anyOf` failures
that is famously poor at exactly that, and the library is not in this project's
lockfile. Neither cost is worth paying for four schemas.

**The learner projection is structural, not a field blacklist.** For `mcq` it
drops `correct` and `feedback` per option and the trailing `rationale`. For
`cloze` there is no field to drop -- the answers are inline in the prose -- so
the parser normalises `text` into segments at parse time and the projection
drops the `answer` from each blank. Doing this by walking a normalised tree,
rather than by deleting dotted paths out of raw YAML, is what makes the
guarantee testable: the property test asserts no answer survives projection for
*any* generated document, which is a claim a path list cannot support.

The honest caveat, which the UI states too: the raw file remains readable at
`GET /api/sessions/{id}/files?path=`, and the source toggle shows it. Until
file reads are permissioned by role, withholding is a ceremony that keeps
answers off the learner's screen, not a control that keeps them from a
determined reader. It is worth doing for the first reason and worth describing
honestly because of the second.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import yaml

from research_team.application.frontmatter import parse_frontmatter
from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH
from research_team.application.timeline_read import MAX_TIMELINE_BANDS

_YAML_LOADER: type = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""The fastest *safe* loader this PyYAML has.

`yaml.safe_load` binds the pure-Python scanner unconditionally, even when the
libyaml extension is installed -- which it is here. Measured on a component
body of the size these actually are, the C loader is about nine times faster,
which is the whole of what B29 was reaching for a cache to get.

`CSafeLoader`, not `CLoader`. The fast unsafe loader would also have been a
speedup and would let a lesson written by a model construct arbitrary Python;
the safety is the reason `safe_load` was here in the first place.
"""

COMPONENT_PREFIX = "component:"
"""What makes an info string a component rather than a language tag."""

View = Literal["author", "learner"]


@dataclass(frozen=True)
class Note:
    """One thing to say about one field, addressed by path.

    Used for both errors and warnings because they differ in consequence, not
    in shape: an error means the component will not render as itself, a warning
    means it will render but something will bite later. Both are written for a
    model to read and act on, so `path` is a subscript expression into the
    body -- `options[1].feedback`, not "the second option".
    """

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


@dataclass(frozen=True)
class MarkdownBlock:
    """A run of ordinary markdown, handed to the client's existing renderer."""

    text: str
    kind: ClassVar[str] = "markdown"


@dataclass(frozen=True)
class ComponentBlock:
    """One fenced component, valid or otherwise.

    `raw` is always the body as written, including when parsing succeeded. It
    costs a copy of the text and it is what the error panel and the source
    toggle display, so an author is never told a block is wrong without being
    shown the block.
    """

    type: str
    id: str
    raw: str
    lang: str
    data: dict[str, Any]
    v: int = 1
    unknown: bool = False
    errors: tuple[Note, ...] = ()
    warnings: tuple[Note, ...] = ()
    kind: ClassVar[str] = "component"

    @property
    def ok(self) -> bool:
        return not self.unknown and not self.errors


Block = MarkdownBlock | ComponentBlock


@dataclass(frozen=True)
class Document:
    """A parsed artifact: its frontmatter, and its blocks in source order."""

    path: str
    frontmatter: dict[str, Any] | None
    blocks: tuple[Block, ...]

    @property
    def components(self) -> tuple[ComponentBlock, ...]:
        return tuple(b for b in self.blocks if isinstance(b, ComponentBlock))

    def component(self, component_id: str) -> ComponentBlock | None:
        return next((c for c in self.components if c.id == component_id), None)


# --- field checking -------------------------------------------------------
#
# A checker takes a value and the path it was found at, and returns the notes
# it has to make about it. Returning notes rather than raising is what lets a
# single pass collect every problem in a body instead of only the first -- a
# model that gets one error back fixes one thing and writes again.

Checker = Callable[[Any, str], list[Note]]


@dataclass(frozen=True)
class Spec:
    """One field: how to check it, whether it must be there, what it defaults to."""

    check: Checker
    required: bool = False
    default: Any = None


def _typename(value: Any) -> str:
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, str):
        return "text"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, Sequence):
        return "list"
    if value is None:
        return "nothing"
    return type(value).__name__


def text(value: Any, path: str) -> list[Note]:
    """Numbers and dates are accepted and stringified.

    An unquoted `front: 1` or `text: 2024-01-01` is YAML doing exactly what it
    is specified to do, and rejecting it would be telling the author their
    flashcard is broken when it is merely untyped. Only genuinely structural
    values -- a list where prose belongs -- are errors.
    """
    if isinstance(value, (Mapping, list, tuple)) or value is None:
        return [Note(path, f"expected text, got {_typename(value)}")]
    return []


def flag(value: Any, path: str) -> list[Note]:
    if not isinstance(value, bool):
        return [Note(path, f"expected true or false, got {_typename(value)}")]
    return []


def one_of(*allowed: str) -> Checker:
    def check(value: Any, path: str) -> list[Note]:
        if value not in allowed:
            return [Note(path, f"expected one of {', '.join(allowed)}, got {value!r}")]
        return []

    return check


def integer_between(low: int, high: int) -> Checker:
    """A whole number inside a bound the *server* already enforces.

    Both bounds this is used for -- `MAX_NEIGHBORHOOD_DEPTH` and
    `MAX_TIMELINE_BANDS` -- are refused by the route with a 422. Checking here
    turns a fetch-time failure the reader sees into an authoring-time note the
    model can act on, which is the whole reason validation feedback exists.

    `bool` is excluded explicitly: `isinstance(True, int)` is true in Python,
    so without that line `depth: true` validates and then travels to a route
    as `1`, having silently become a number the author never wrote.
    """

    def check(value: Any, path: str) -> list[Note]:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            return [Note(path, f"expected a whole number from {low} to {high}, got {value!r}")]
        return []

    return check


def string_list(minimum: int = 1) -> Checker:
    """A list of bare strings, each checked at its own subscript path.

    Distinct from `listing`, which takes a list of *mappings*. `compare`'s
    `entities:` is a plain sequence of names, and wrapping each in a mapping to
    reuse `listing` would be schema noise a model has to get right for nothing.
    """

    def check(value: Any, path: str) -> list[Note]:
        if not isinstance(value, list):
            return [Note(path, f"expected a list, got {_typename(value)}")]
        if len(value) < minimum:
            plural = "entry" if minimum == 1 else "entries"
            return [Note(path, f"expected at least {minimum} {plural}, got {len(value)}")]
        notes: list[Note] = []
        for index, entry in enumerate(value):
            notes.extend(text(entry, f"{path}[{index}]"))
        return notes

    return check


def string_subset(*allowed: str) -> Checker:
    """A list of bare strings drawn from a closed vocabulary.

    `string_list` plus `one_of`, and neither alone will do: `string_list` has
    no vocabulary and `one_of` checks a scalar, so composing them by hand at
    the one call site would put the subscript arithmetic in a registry entry --
    which is where a path like `vary[1]` stops being maintained.

    Shape before vocabulary, deliberately. A mapping where a string belongs is
    reported by `text` as a mapping, not as "not one of entity_type, window":
    an author who wrote the wrong *kind* of thing is not helped by a list of
    the right values.
    """

    def check(value: Any, path: str) -> list[Note]:
        if not isinstance(value, list):
            return [Note(path, f"expected a list, got {_typename(value)}")]
        if not value:
            return [Note(path, "expected at least 1 entry, got 0")]
        notes: list[Note] = []
        for index, entry in enumerate(value):
            at = f"{path}[{index}]"
            shape = text(entry, at)
            if shape:
                notes.extend(shape)
            elif entry not in allowed:
                notes.append(Note(at, f"expected one of {', '.join(allowed)}, got {entry!r}"))
        return notes

    return check


def listing(item: Mapping[str, Spec], minimum: int = 1) -> Checker:
    """A list of mappings, each checked against `item`, with paths that subscript.

    The minimum is not pedantry. A `cards:` list with nothing in it renders as
    a deck with no cards, which looks to a reader exactly like a bug in the
    renderer rather than a gap in the lesson.
    """

    def check(value: Any, path: str) -> list[Note]:
        if not isinstance(value, list):
            return [Note(path, f"expected a list, got {_typename(value)}")]
        if len(value) < minimum:
            plural = "entry" if minimum == 1 else "entries"
            return [Note(path, f"expected at least {minimum} {plural}, got {len(value)}")]
        notes: list[Note] = []
        for index, entry in enumerate(value):
            at = f"{path}[{index}]"
            if not isinstance(entry, Mapping):
                notes.append(Note(at, f"expected a mapping, got {_typename(entry)}"))
                continue
            notes.extend(_check_fields(entry, item, prefix=f"{at}."))
        return notes

    # The item schema, hung on the closure so a whole-body pass can see it.
    # `_blank_required` has to descend into `options[i].text` and
    # `cards[i].front`, and a bare `Checker` is opaque -- the alternative was
    # a second registry of "which fields are listings", which is the kind of
    # parallel list that goes stale the first time a type is added.
    check.item = dict(item)  # type: ignore[attr-defined]
    return check


def _check_fields(
    body: Mapping[str, Any], fields: Mapping[str, Spec], prefix: str = ""
) -> list[Note]:
    notes: list[Note] = []
    for name, spec in fields.items():
        path = f"{prefix}{name}"
        if name not in body or body[name] is None:
            if spec.required:
                notes.append(Note(path, "required field missing"))
            continue
        notes.extend(spec.check(body[name], path))
    return notes


def _unknown_keys(
    body: Mapping[str, Any], fields: Mapping[str, Spec], prefix: str = ""
) -> list[Note]:
    """Warned about, never rejected.

    A typo like `feedbck:` is silently dropped otherwise, and silently dropped
    feedback is the failure mode an author is least likely to notice, because
    the component renders perfectly.
    """
    known = set(fields) | _UNIVERSAL
    return [
        Note(f"{prefix}{key}", "unrecognised field, ignored")
        for key in body
        if key not in known
    ]


def _blank_required(
    body: Mapping[str, Any], fields: Mapping[str, Spec], prefix: str = ""
) -> list[Note]:
    """A required text field that is present and empty, warned about.

    `required=True` only asks whether a key is there, and `text()` accepts
    `""` on purpose -- it rejects structure, not emptiness. So `prompt: ""`
    validates as present, and until this hook nothing anywhere said otherwise.

    Warned rather than rejected, following `_unknown_keys` and
    `_compare_collisions`: the block still draws, and refusing would cost an
    author the whole component over a field they can fill in. The reason it
    has to say *something* is the other half of this fix -- `Prose` now
    renders blank text as nothing at all, so an empty `mcq.prompt` used to be
    a loud wrong state on the page and is now a silent absence. This is where
    the complaint moved to, and `ComponentFeedback` puts it in front of the
    model that wrote it.

    Descends into `listing` fields through the item schema `listing` hangs on
    its checker, so `options[1].text` is named by its own path.
    """
    notes: list[Note] = []
    for name, spec in fields.items():
        value = body.get(name)
        path = f"{prefix}{name}"
        item = getattr(spec.check, "item", None)
        if item is not None and isinstance(value, list):
            for index, entry in enumerate(value):
                if isinstance(entry, Mapping):
                    notes.extend(_blank_required(entry, item, prefix=f"{path}[{index}]."))
            continue
        if not spec.required or not isinstance(value, str) or value.strip():
            continue
        notes.append(Note(path, "required, and present but empty; it renders as nothing"))
    return notes


_UNIVERSAL = {"id", "type", "v", "objective"}
"""Accepted on every component. `type` restates the info string for robustness,
`objective` names the learning objective an item aligns to, which is what makes
backward-design coverage checkable over a whole course."""


# --- the registry ---------------------------------------------------------


@dataclass(frozen=True)
class ComponentType:
    """A registered component: its shape, its secrets, and how to teach it.

    `summary` and `example` exist so the reference handed to the authoring
    model is *generated from the registry* rather than maintained beside it.
    A hand-written prompt describing these schemas would drift from them within
    two edits, and the drift would be invisible until a model authored to the
    stale description.
    """

    name: str
    version: int
    fields: Mapping[str, Spec]
    summary: str
    example: str
    withheld: tuple[str, ...] = ()
    craft: tuple[str, ...] = ()
    """How to write a *good* one of these, not how to write a valid one.

    Registry-resident for `summary` and `example`'s reason: guidance kept
    beside a schema drifts from it within two edits, and the drift is invisible
    until a model authors faithfully to a description that stopped being true.
    Both the stage prompt and the ask prompt render this, so there is one copy.

    What belongs here is the failure mode this format actually produces -- the
    fourth distractor nobody picks, the blank the sentence gives away -- and
    not a course in assessment design. A model reads this every time it writes
    one; length is a cost paid per authoring turn.
    """
    resolved: bool = False
    """This component carries a reference and fetches its data in the browser.

    Structurally it is the inverse of `gradeable`: nothing is withheld (there
    is no answer key -- the data is the project's own), nothing is graded, and
    the YAML body is a *query*, not content. The flag exists so the projection,
    the prompt and the client can all tell the two classes apart without a name
    list, which is the shape that rots the moment a sixth type is added.

    Validation of a resolved body stays pure and shape-only. The registry
    cannot check that a referenced entity exists -- `validation_report` runs
    here at parse time with no graph handle -- so a name matching nothing is a
    *render* state, not a parse error. See
    `tests/application/test_resolved_components.py` for the assertion that
    keeps it that way.
    """
    gradeable: bool = False
    normalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    strip: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    warn: Callable[[dict[str, Any]], list[Note]] | None = None
    """Whole-body notes a per-field `Checker` cannot make, because they are
    about the relationship between two fields' entries rather than one value.

    Warnings and never errors, which is the whole reason this is separate from
    `fields`: what it catches renders *correctly* and misbehaves elsewhere --
    the duplicate-`id` warning's shape exactly, and `_unknown_keys`' policy.

    Runs only on a body that already validated, so an implementation may
    assume the shapes `fields` declared. Nothing else in this module offers
    that guarantee, and without it a hook indexing into a field a model wrote
    as a string would raise inside a parser that promises never to.
    """


CLOZE_BLANK = re.compile(r"\{\{(.+?)\}\}", re.DOTALL)
"""`{{answer}}` or `{{answer::hint}}`, borrowed from Anki and Obsidian because
it is the cloze syntax best represented in training data. `==highlight==` is
deliberately not supported: overloading a formatting mark with semantics is the
ambiguity that has cost the Obsidian plugin its bug reports."""


def _cloze_segments(body: dict[str, Any]) -> dict[str, Any]:
    """Split `text` into literal runs and blanks, once, at parse time.

    The alternative -- shipping the raw text and splitting it in the browser --
    would put the answers in the learner's payload no matter what the
    projection did, because the answers *are* the text. Normalising here is
    what makes withholding possible at all for this type.
    """
    source = str(body.get("text", ""))
    segments: list[dict[str, Any]] = []
    index = 0
    cursor = 0
    for match in CLOZE_BLANK.finditer(source):
        if match.start() > cursor:
            segments.append({"text": source[cursor : match.start()]})
        answer, _, hint = match.group(1).partition("::")
        segments.append(
            {
                "blank": index,
                "answer": answer.strip(),
                "hint": hint.strip() or None,
            }
        )
        index += 1
        cursor = match.end()
    if cursor < len(source):
        segments.append({"text": source[cursor:]})
    return {**body, "segments": segments, "blanks": index}


def _cloze_strip(data: dict[str, Any]) -> dict[str, Any]:
    """Drop every answer, and the source text that would give them all back."""
    segments = [
        {k: v for k, v in segment.items() if k != "answer"}
        for segment in data.get("segments", [])
    ]
    return {k: v for k, v in data.items() if k != "text"} | {"segments": segments}


def _mcq_strip(data: dict[str, Any]) -> dict[str, Any]:
    options = [
        {k: v for k, v in option.items() if k not in ("correct", "feedback")}
        for option in data.get("options", [])
        if isinstance(option, Mapping)
    ]
    kept = {k: v for k, v in data.items() if k != "rationale"}
    return kept | {"options": options}


def _cloze_text_has_a_blank(value: Any, path: str) -> list[Note]:
    notes = text(value, path)
    if notes:
        return notes
    if not CLOZE_BLANK.search(str(value)):
        return [Note(path, "no {{blanks}} found -- wrap each answer in {{ }}")]
    return []


def _duplicates(entries: Sequence[tuple[str, Any]], noun: str, keyed: str) -> list[Note]:
    """One note per repeat, addressed at the *later* entry.

    The later one because that is the one to edit: the first occurrence is
    presumably the row the author meant, and a note on it would read as an
    instruction to change the wrong line.
    """
    seen: set[str] = set()
    notes: list[Note] = []
    for path, value in entries:
        key = str(value)
        if key in seen:
            notes.append(
                Note(
                    path,
                    f"duplicate {noun} {key!r}; the table keys {keyed} on it "
                    "and the two will collide",
                )
            )
        seen.add(key)
    return notes


def _compare_collisions(data: dict[str, Any]) -> list[Note]:
    """Both of `compare`'s author-supplied key sets, warned about, never rejected.

    Three sites, not two, and all three come from these two key sets:
    `CompareWidget.tsx` keys its `<th>` column heads on the entity name, its
    `<tr>` rows on the author's `label`, and every row's `<td>` cells on the
    entity name again (the cells are mapped over `entities`, so a duplicate
    name collides once per row). A repeat in either set is a React key
    collision: the table draws correctly and logs a warning into a console no
    reader of the lesson will open.

    Warned rather than rejected, deliberately, and the choice is the registry's
    rather than the renderer's -- the renderer cannot dedupe without inventing
    which of the two rows the author meant. Refusing would cost the whole table
    over a defect that is cosmetic in the rendered output, which is the wrong
    trade in a module whose first principle is that degradation costs one block
    and never a document. This follows `_unknown_keys` and the duplicate-`id`
    warning, the two existing cases of "renders fine, bites later".
    """
    entities = data.get("entities")
    rows = data.get("rows")
    notes: list[Note] = []
    if isinstance(entities, list):
        notes += _duplicates(
            [(f"entities[{i}]", name) for i, name in enumerate(entities)],
            "entity",
            "columns",
        )
    if isinstance(rows, list):
        # Indices come from `enumerate` over every row rather than from a
        # filtered list, so a path still names the row a reader can count to
        # if a non-mapping row ever reaches here.
        notes += _duplicates(
            [
                (f"rows[{i}].label", row["label"])
                for i, row in enumerate(rows)
                if isinstance(row, Mapping) and row.get("label") is not None
            ],
            "label",
            "rows",
        )
    return notes


EXPLORER_AXES: tuple[str, ...] = ("entity_type", "window")
"""Which parameters a reader may be given control of.

`limit` is deliberately absent and the omission is a ruling. `limit` bounds the
response and not the server's work -- it never reaches the store
(`graph_reader.py:294-299`) -- so a reader dragging it would change the picture
without changing what it cost, and would learn, wrongly, that the
cheap-looking control is the one that governs cost. Every axis here does
govern the answer honestly.

Named as a constant so the registry entry, the validator and the craft note
cannot come to list three different sets of axes.
"""

EXPLORER_BACKING_READS: tuple[str, ...] = ("timeline",)
"""What `over:` may name today.

A tuple with one entry, and that is the design's section 3 in a line: the field
exists so that a second backing read is a registry change rather than a new
component type. `GET /topics` and `GET /sources` take nothing worth varying,
and a graph explorer needs an entity-type vocabulary route this build does not
have -- so this stays at one until such a route exists.
"""


def _explorer_over(data: dict[str, Any]) -> list[Note]:
    """An unsupported `over:` is warned about, never rejected.

    The choice mirrors `_compare_collisions` and `_unknown_keys`: this is a
    "renders fine, does less than it says" defect, and refusing would cost the
    author the whole block plus the prose they wrote in `prompt`. The widget
    renders the refusal as a sentence naming what is supported, which is what
    every other failure in these widgets does -- and an error would route the
    block to the error panel where there is no widget left to say it.

    Runs only on a body that already validated, so `over` is present and is
    text (`ComponentType.warn`'s guarantee).
    """
    over = data.get("over")
    if over in EXPLORER_BACKING_READS:
        return []
    supported = ", ".join(repr(name) for name in EXPLORER_BACKING_READS)
    return [Note("over", f"only {supported} is supported today, got {over!r}")]


_ID_SHAPED = re.compile(r"\A[0-9a-fA-F]+(?:-[0-9a-fA-F]+)+\Z")
"""Hex groups joined by hyphens -- a UUID, and the near-UUID shapes beside it.

Deliberately loose about grouping and tight about length (see `_looks_like_id`).
The ids this catches are written by a model copying from a prompt, and a model
that miscounts a group still produces something no reader wants as a heading.
"""


def _looks_like_id(value: Any) -> bool:
    text_value = str(value).strip()
    if not _ID_SHAPED.match(text_value):
        return False
    # 32 hex digits is a UUID's worth. Below it the false-positive risk is
    # real: `284-305` is a reign, `AD 64-68` is a date range, and both are
    # things an author writes into a compare cell or an entity name.
    return len(text_value.replace("-", "")) >= 32


def _entity_ids_where_names_go(data: dict[str, Any]) -> list[Note]:
    """An entity *id* written into a field that renders as a *label*.

    The authoring prompt hands the model entity ids and tells it to copy them
    exactly; two of the types that take an entity have an `entity_id` to put
    one in, and `compare` has nowhere at all. So the id lands in `entity:` or
    in `entities[i]:`, which is a valid string, which validates, and which the
    browser then searches for by name -- finding nothing, because no entity is
    named by its own id -- and prints raw beside "not in this project's graph".

    Warned and never rejected, following `_compare_collisions` and
    `_explorer_over`: the block draws, the table is intact, and only the label
    is wrong. Refusing would cost the reader a whole widget over a heading.

    *Cost, stated:* a project whose entities are genuinely named by long hex
    strings gets a warning it cannot act on. That is a line of noise in a tool
    result, against a defect that otherwise reaches a reader's screen.
    """
    notes: list[Note] = []
    entity = data.get("entity")
    if entity is not None and _looks_like_id(entity):
        notes.append(
            Note(
                "entity",
                "looks like an entity id, not a name; `entity` is the name as "
                "the sources spell it, and the id goes in `entity_id`",
            )
        )
    entities = data.get("entities")
    if isinstance(entities, list):
        notes += [
            Note(
                f"entities[{index}]",
                "looks like an entity id, not a name; this field takes names "
                "as the sources spell them, and there is nowhere here to put "
                "an id",
            )
            for index, value in enumerate(entities)
            if _looks_like_id(value)
        ]
    return notes


BodyHook = Callable[[dict[str, Any]], list[Note]]


def _all_of(*hooks: BodyHook) -> BodyHook:
    """Run several whole-body hooks and keep every note.

    `ComponentType.warn` is one slot and `compare` now has two things to say
    about `entities:` -- duplicates and ids. Composing here rather than folding
    the id check into `_compare_collisions` keeps each hook about one thing,
    and lets `definition` and `graph` take the id check alone.
    """

    def run(data: dict[str, Any]) -> list[Note]:
        notes: list[Note] = []
        for hook in hooks:
            notes.extend(hook(data))
        return notes

    return run


REGISTRY: dict[str, ComponentType] = {
    "flashcards": ComponentType(
        name="flashcards",
        version=1,
        summary="A two-sided card deck for recall practice. Nothing is withheld.",
        example=(
            "```component:flashcards\n"
            "id: sev-vocabulary\n"
            "title: Severity Vocabulary\n"
            "cards:\n"
            '  - front: "SEV-1"\n'
            "    back: |\n"
            "      Complete loss of a customer-facing service, or confirmed\n"
            "      data loss. Pages the on-call director.\n"
            "```"
        ),
        fields={
            "title": Spec(text),
            "shuffle": Spec(flag, default=False),
            "cards": Spec(
                listing(
                    {"front": Spec(text, required=True), "back": Spec(text, required=True)}
                ),
                required=True,
            ),
        },
        craft=(
            "One fact per card. A card whose back is a paragraph is a passage that "
            "has been put in the wrong container -- split it or leave it as prose.",
            "Write the front as the question a reader would actually ask "
            "themselves, not as a heading.",
        ),
    ),
    "mcq": ComponentType(
        name="mcq",
        version=1,
        summary=(
            "A multiple-choice question. Answers, per-option feedback and the "
            "rationale are withheld from the learner and graded on the server."
        ),
        example=(
            "```component:mcq\n"
            "id: sev-classification-1\n"
            "prompt: |\n"
            "  Checkout returns 500s for 4% of requests; retries succeed.\n"
            "  What severity should the Incident Commander declare?\n"
            "options:\n"
            '  - text: "SEV-1"\n'
            "    correct: false\n"
            '    feedback: "No total loss and no data loss; over-declaring costs trust."\n'
            '  - text: "SEV-2"\n'
            "    correct: true\n"
            '    feedback: "Major degradation with a workaround is the textbook SEV-2."\n'
            "rationale: |\n"
            "  Severity is a communication decision, not a technical one.\n"
            'objective: "Classify an incident by severity"\n'
            "```"
        ),
        fields={
            "prompt": Spec(text, required=True),
            "multiple": Spec(flag, default=False),
            "shuffle": Spec(flag, default=False),
            "options": Spec(
                listing(
                    {
                        "text": Spec(text, required=True),
                        "correct": Spec(flag, required=True),
                        "feedback": Spec(text),
                    },
                    minimum=2,
                ),
                required=True,
            ),
            "rationale": Spec(text),
        },
        withheld=("options[].correct", "options[].feedback", "rationale"),
        craft=(
            "Every distractor should be something a reader who half-understands "
            "would actually pick. An option nobody chooses teaches nothing and "
            "costs a line -- three or four options beat five padded ones.",
            "Give each wrong option `feedback` naming the misunderstanding that "
            "makes it attractive. The moment after a wrong answer is the one "
            "moment the reader is most ready to read why.",
            "`rationale` explains the right answer's reasoning, which is not the "
            "same as restating it.",
        ),
        gradeable=True,
        strip=_mcq_strip,
    ),
    "cloze": ComponentType(
        name="cloze",
        version=1,
        summary=(
            "Fill-in-the-blank prose. Write each answer as {{answer}} or "
            "{{answer::hint}}; answers are withheld and graded on the server."
        ),
        example=(
            "```component:cloze\n"
            "id: comms-cadence\n"
            "text: |\n"
            "  A {{SEV-1}} requires a stakeholder update every\n"
            "  {{15 minutes::how often?}}, issued by the {{Comms Lead}}.\n"
            "mode: one-at-a-time\n"
            "```"
        ),
        fields={
            "text": Spec(_cloze_text_has_a_blank, required=True),
            "mode": Spec(one_of("one-at-a-time", "all-at-once"), default="one-at-a-time"),
        },
        withheld=("text", "segments[].answer"),
        craft=(
            "Blank the thing being learned, not the word that happens to be a "
            "noun. If the surrounding sentence gives the answer away, the blank "
            "tests reading rather than recall.",
            "Grading normalises case and spacing but not word choice, so use "
            "`{{answer::hint}}` where a term has several defensible spellings.",
            "Three or four blanks in a passage is plenty; a sentence that is more "
            "blank than prose is unreadable rather than difficult.",
        ),
        gradeable=True,
        normalize=_cloze_segments,
        strip=_cloze_strip,
    ),
    "checklist": ComponentType(
        name="checklist",
        version=1,
        summary=(
            "A procedural checklist for a task a learner performs. Not graded; "
            "ticking a box is a record, not an answer."
        ),
        example=(
            "```component:checklist\n"
            "id: ic-first-five\n"
            'title: "IC: First Five Minutes"\n'
            "items:\n"
            '  - text: "Assume the IC role out loud in the channel"\n'
            "    required: true\n"
            '  - text: "Assign a Comms Lead"\n'
            "    required: true\n"
            '    note: "Mandatory for SEV-1 and SEV-2."\n'
            "```"
        ),
        fields={
            "title": Spec(text),
            "persist": Spec(flag, default=False),
            "items": Spec(
                listing(
                    {
                        "text": Spec(text, required=True),
                        "required": Spec(flag),
                        "note": Spec(text),
                    }
                ),
                required=True,
            ),
        },
        craft=(
            "Steps someone performs, in the order they perform them -- not facts "
            "they should know. A checklist of facts is a flashcard deck with no "
            "second side.",
            "`note` carries the caveat that would otherwise bloat `text`.",
        ),
    ),
    "definition": ComponentType(
        name="definition",
        version=1,
        summary=(
            "This project's own grounded definition of an entity, with the "
            "passages it was drawn from. Reference by name; the browser looks "
            "it up."
        ),
        example=(
            "```component:definition\n"
            "id: nicene-christianity\n"
            "entity: Nicene Christianity\n"
            "```"
        ),
        fields={
            # `entity` is required and `entity_id` is optional beside it,
            # rather than "one of these two". `_check_fields` validates one
            # field at a time and has no disjunction; building one to serve
            # five fields is machinery for nothing. The name is wanted anyway:
            # `ResolvedFrame` degrades to the word the author wrote, never to
            # a candidate's, so a reference with only an id has nothing to
            # render in four of its five states.
            "entity": Spec(text, required=True),
            "entity_id": Spec(text),
        },
        resolved=True,
        warn=_entity_ids_where_names_go,
        craft=(
            "Write the entity name exactly as your prose does, and exactly as "
            "the sources spell it. The lookup is a name search over what "
            "extraction actually stored, so a tidier canonical name -- "
            "'Constantine I' for an entity stored as 'Constantine' -- finds "
            "nothing and the widget renders as the plain name.",
            "Use this where a reader needs the project's grounded account of a "
            "term, not where you would define it yourself in a clause. A "
            "definition widget beside a sentence that already defines the word "
            "is two definitions competing.",
            "`entity_id` is for pinning a name two entities share. You will not "
            "have one; leave it out.",
        ),
    ),
    "evidence": ComponentType(
        name="evidence",
        version=1,
        summary=(
            "A claim beside the passages it rests on, quoted from this "
            "project's sources. Takes source ids directly -- the same ids "
            "`[[src:...]]` uses."
        ),
        example=(
            "```component:evidence\n"
            "id: state-religion\n"
            "claim: |\n"
            "  Theodosius made Nicene Christianity the state religion in AD 380.\n"
            "sources:\n"
            "  - source: doc-4f2a\n"
            "    start: 4120\n"
            "    end: 4380\n"
            "```"
        ),
        fields={
            "claim": Spec(text, required=True),
            "sources": Spec(
                listing(
                    {
                        "source": Spec(text, required=True),
                        # Bounded rather than merely non-negative: the route
                        # clamps whatever it is given, so an offset typed with
                        # an extra digit returns the end of the document and
                        # nothing tells the reader the range was nonsense.
                        # The ceiling is generous on purpose -- it is a typo
                        # guard, not a document-length check, which this layer
                        # has no way to make.
                        "start": Spec(integer_between(0, 100_000_000)),
                        "end": Spec(integer_between(0, 100_000_000)),
                    }
                ),
                required=True,
            ),
        },
        resolved=True,
        craft=(
            "Quote the passage that actually carries the claim, not the "
            "paragraph around it. The reader is going to read both and compare "
            "them, which is the entire point of the widget -- a range that only "
            "nearly supports the claim is more damaging here than in prose, "
            "because you have invited the check.",
            "Use the source ids already in your context. A `source:` you cannot "
            "find in what you were given is one you invented, and the widget "
            "will show nothing.",
            "One claim per block. Two claims sharing a passage list leaves the "
            "reader unable to tell which range supports which.",
        ),
    ),
    "graph": ComponentType(
        name="graph",
        version=1,
        summary=(
            "The neighbourhood around one entity in this project's knowledge "
            "graph: what it connects to, and how. Reference by name."
        ),
        example=(
            "```component:graph\nid: constantine-around\nentity: Constantine\ndepth: 1\n```"
        ),
        fields={
            "entity": Spec(text, required=True),
            "entity_id": Spec(text),
            # Bounded here against the same constant the route refuses past,
            # so an over-deep request is an authoring note rather than a 422
            # the reader discovers. Default 1 because one hop is the readable
            # neighbourhood -- two is a hairball in a markdown column.
            "depth": Spec(integer_between(1, MAX_NEIGHBORHOOD_DEPTH), default=1),
        },
        resolved=True,
        warn=_entity_ids_where_names_go,
        craft=(
            "Write the entity name exactly as your prose does, and exactly as "
            "the sources spell it. The lookup is a name search over what "
            "extraction actually stored, so a tidier canonical name finds "
            "nothing and the widget renders as the plain name.",
            "Reach for this when the *shape* of the connections is the point. "
            "If what matters is one relationship, a sentence says it better "
            "than a drawing the reader has to find it in.",
            "Leave `depth` at 1 unless the second hop is the thing you are "
            "showing. Two hops on a well-extracted entity is a hairball.",
        ),
    ),
    "timeline": ComponentType(
        name="timeline",
        version=1,
        summary=(
            "This project's dated entities on an axis, filtered by type and "
            "date range. Not scoped to one entity -- there is no such filter."
        ),
        example=(
            "```component:timeline\n"
            "id: fourth-century-people\n"
            "entity_type: Person\n"
            'from: "0300-01-01"\n'
            'to: "0400-01-01"\n'
            "```"
        ),
        fields={
            "entity_type": Spec(text),
            # `from` and `to` are ISO instants bounding a half-open window;
            # either may be omitted for an open end. Checked as text rather
            # than parsed here: the route answers its own 422 naming which
            # parameter was wrong, and a second date parser in this module
            # would be a second thing to keep in step with it.
            "from": Spec(text),
            "to": Spec(text),
            "limit": Spec(integer_between(1, MAX_TIMELINE_BANDS)),
        },
        resolved=True,
        craft=(
            "Quote the dates. An unquoted `from: 0300-01-01` is a YAML date, "
            "not a string, and YAML will not give you back the leading zero.",
            "There is no entity filter, and `entity:` here does nothing -- the "
            "route filters by type and range only. If you want one entity's "
            "dates, say them in a sentence.",
            "Narrow the window to the span you are actually discussing. A "
            "timeline of everything is a bar chart of the corpus rather than "
            "an illustration of your point.",
            "`limit` shortens what is drawn; it does not make the read "
            "cheaper. Measured, not assumed: the server walks the project's "
            "entities twice and applies the limit to the result, and the read "
            "is deliberately uncached. So write the limit for readability -- "
            "a dozen bands a reader can take in -- and expect no saving from "
            "it.",
        ),
    ),
    "explorer": ComponentType(
        name="explorer",
        version=1,
        summary=(
            "A timeline the *reader* re-runs. The author fixes some "
            "parameters, names which ones the reader may change in `vary`, "
            "and writes a `prompt` inviting them to look."
        ),
        example=(
            "```component:explorer\n"
            "id: fourth-century-explorer\n"
            "over: timeline\n"
            "entity_type: Person\n"
            'from: "0300-01-01"\n'
            'to: "0400-01-01"\n'
            "vary: [entity_type, window]\n"
            "prompt: |\n"
            "  Narrow to Emperors and pull the window back to see how much of\n"
            "  the century the reigns actually cover.\n"
            "```"
        ),
        fields={
            # Required, and checked as plain text with the vocabulary enforced
            # by `warn` rather than by `one_of`. See `_explorer_over`: an
            # unsupported backing read has to reach the widget so the widget
            # can say so in prose.
            "over": Spec(text, required=True),
            "vary": Spec(string_subset(*EXPLORER_AXES), required=True),
            # Required, and the one field that makes an explorer worth more
            # than a timeline. Controls with no stated reason to touch them are
            # dressing, and a model left free to omit this will omit it.
            "prompt": Spec(text, required=True),
            # The same four the `timeline` entry takes, with the same
            # reasoning: quoted ISO instants bounding a half-open window,
            # either omittable for an open end, checked as text because the
            # route answers its own 422 naming which parameter was wrong and a
            # second date parser here would be a second thing to keep in step.
            "entity_type": Spec(text),
            "from": Spec(text),
            "to": Spec(text),
            "limit": Spec(integer_between(1, MAX_TIMELINE_BANDS)),
        },
        resolved=True,
        warn=_explorer_over,
        craft=(
            "Write this when you want the reader to look for something you did "
            "not name. If you are making a point with a particular window, "
            "write a `timeline` instead -- that is a view you chose, and this "
            "is an invitation to leave it.",
            "Quote the dates. An unquoted `from: 0300-01-01` is a YAML date, "
            "not a string, and YAML will not give you back the leading zero.",
            "`vary` is not a formality. Name only the axes you actually want "
            "moved: an author who set a window deliberately and one who did "
            "not are indistinguishable to a reader unless you say which.",
            "The `prompt` is the whole difference between this and a timeline. "
            "Say what you suspect is in there, not what the controls do -- a "
            "reader can see the controls.",
            "A reader cannot link to what they find. Nothing in this app puts "
            "filter state in the URL, so the only way to keep a view is a "
            "screenshot. Do not promise to share a result in your prompt.",
            "`limit` shortens what is drawn; it does not make the read "
            "cheaper. Measured, not assumed: the server walks the project's "
            "entities twice and applies the limit to the result, and the read "
            "is deliberately uncached. That bites harder here than in a "
            "`timeline`, because the reader re-runs it.",
        ),
    ),
    "compare": ComponentType(
        name="compare",
        version=1,
        summary=(
            "A side-by-side table over two or more named entities. You write "
            "the rows; the browser resolves each column head against this "
            "project's graph and links the ones it finds."
        ),
        example=(
            "```component:compare\n"
            "id: two-emperors\n"
            "entities: [Diocletian, Constantine]\n"
            "rows:\n"
            "  - label: Reign\n"
            "    cells:\n"
            '      - "284-305"\n'
            '      - "306-337"\n'
            "  - label: Religious policy\n"
            "    cells:\n"
            '      - "Persecution"\n'
            '      - "Toleration, then patronage"\n'
            "```"
        ),
        fields={
            "entities": Spec(string_list(minimum=2), required=True),
            "rows": Spec(
                listing(
                    {
                        "label": Spec(text, required=True),
                        # Optional, and short rows are fine: a label with
                        # nothing under it is a real thing to write, and the
                        # renderer pads to the column count rather than
                        # refusing. Requiring one cell per entity would make
                        # the commonest edit -- adding a third column --
                        # invalidate every row at once.
                        "cells": Spec(string_list(minimum=0)),
                    }
                ),
                required=True,
            ),
        },
        resolved=True,
        warn=_all_of(_compare_collisions, _entity_ids_where_names_go),
        craft=(
            "Write each entity name exactly as your prose does, and exactly as "
            "the sources spell it -- the column heads are looked up by name, "
            "and one this project does not hold renders as plain text with the "
            "rest of the table intact.",
            "You write the rows yourself: nothing in this project stores "
            "per-type attributes, so there is no schema to derive columns from. "
            "Pick the dimensions the comparison actually turns on.",
            "Give each row a distinct `label` and name each entity once. The "
            "table is keyed on both, so a repeat is a collision -- it still "
            "draws, and you get a warning rather than a broken block, but two "
            "rows called 'Reign' were almost certainly one row you meant to "
            "edit.",
            "Cells are in the same order as `entities`. A short row is padded, "
            "so a dimension one entity has and another does not is fine to "
            "leave blank -- that blank is itself the comparison.",
        ),
    ),
}


def component_reference(only: Iterable[str] | None = None) -> str:
    """The authoring reference, generated from the registry for the prompt.

    Generated rather than written so it cannot drift from the schemas it
    describes -- the failure mode being a model authoring faithfully to a
    description that stopped being true two edits ago.

    `only` narrows it to the types a caller has just said are appropriate.
    Showing a stage the syntax for two components it was told to use, plus two
    it was told not to, invites exactly the choice the guidance was trying to
    make for it.
    """
    wanted = list(REGISTRY.values()) if only is None else [REGISTRY[n] for n in only]
    lines = [
        "Interactive components are fenced blocks with a YAML body. The info",
        "string is `component:<type>`. Rules that matter:",
        "",
        "- Always give an explicit `id`, kebab-case, unique within the file.",
        "- Use a `|` block scalar for any field containing prose. An unquoted",
        "  colon inside a value is the single most common way these fail.",
        "- Never nest one component inside another's fields.",
        "- Tag assessment items with `objective:` matching a frontmatter objective.",
        "",
        "An unrecognised type renders as a plain code block, so an unsupported",
        "component costs that block and nothing else.",
        "",
    ]
    for component in wanted:
        lines += [f"### {component.name}", "", component.summary, "", component.example, ""]
        if component.craft:
            lines += ["Writing a good one:", ""]
            lines += [f"- {note}" for note in component.craft]
            lines += [""]
    return "\n".join(lines)


# --- parsing --------------------------------------------------------------

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^\s`]*)")
"""Deliberately the client's regex from `app.js`, character for character.

Unanchored at the end, so an info string carrying extra words -- ```` ```js
{1,3} ```` -- still opens a fence here. Anchoring it would leave this scanner
treating that line as prose while the browser treated it as a fence, and the
two disagreeing about where a code block starts is exactly how a `component:`
fence *inside* a code sample gets extracted as a real component.
"""


def derive_id(path: str, index: int) -> str:
    """A stable id for a component that did not name itself.

    Stable across re-renders of the same file, which is what stops learner
    state detaching every time the document is read. Deliberately *not* stable
    across edits that insert a component above this one -- nothing derivable
    from position could be -- which is why the parser warns whenever it has to
    reach for this.
    """
    digest = hashlib.sha256(f"{path}#{index}".encode()).hexdigest()
    return f"c-{digest[:12]}"


def _scan(text_body: str) -> Iterable[tuple[str, str, str]]:
    """Split into `("markdown", text, "")` and `("component", body, info)` runs.

    The fence rules mirror the client's renderer exactly, including that a
    longer fence swallows a shorter one -- which is what keeps a documentation
    block showing a component example from being parsed as one -- and that an
    unclosed fence runs to the end of the file rather than discarding it.
    """
    lines = text_body.splitlines(keepends=True)
    pending: list[str] = []
    index = 0
    while index < len(lines):
        opening = _FENCE.match(lines[index].rstrip("\n"))
        if not opening:
            pending.append(lines[index])
            index += 1
            continue
        marker, info = opening.groups()
        opener = lines[index]
        closer = re.compile(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$")
        body: list[str] = []
        index += 1
        while index < len(lines) and not closer.match(lines[index].rstrip("\n")):
            body.append(lines[index])
            index += 1
        closing = lines[index] if index < len(lines) else None
        index += 1  # step over the closing fence, or off the end, which is fine
        if info.startswith(COMPONENT_PREFIX):
            if pending:
                yield ("markdown", "".join(pending), "")
                pending = []
            yield ("component", "".join(body).rstrip("\n"), info)
            continue
        # Not a component: hand the lines back exactly as they were, so the
        # client renders the code block the way it always has. Reconstructing
        # the fence from its parts would quietly drop anything the info string
        # carried beyond the language.
        pending.append(opener)
        pending.extend(body)
        if closing is not None:
            pending.append(closing)
    if pending:
        yield ("markdown", "".join(pending), "")


def _build_component(
    body: str, info: str, path: str, index: int, seen: set[str]
) -> ComponentBlock:
    name = info[len(COMPONENT_PREFIX) :]
    spec = REGISTRY.get(name)
    if spec is None:
        # Unknown is not an error. The client shows a labelled code block.
        return ComponentBlock(
            type=name or "unknown",
            id=derive_id(path, index),
            raw=body,
            lang=info,
            data={},
            unknown=True,
        )

    errors: list[Note] = []
    warnings: list[Note] = []
    try:
        loaded = yaml.load(body, Loader=_YAML_LOADER) if body.strip() else {}
    except yaml.YAMLError as error:
        detail = str(getattr(error, "problem", None) or error).strip().splitlines()[0]
        return ComponentBlock(
            type=name,
            id=derive_id(path, index),
            raw=body,
            lang=info,
            data={},
            errors=(Note("", f"could not parse the YAML body -- {detail}"),),
        )

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, Mapping):
        return ComponentBlock(
            type=name,
            id=derive_id(path, index),
            raw=body,
            lang=info,
            data={},
            errors=(Note("", f"expected a mapping of fields, got {_typename(loaded)}"),),
        )

    data = dict(loaded)
    errors.extend(_check_fields(data, spec.fields))
    warnings.extend(_unknown_keys(data, spec.fields))
    warnings.extend(_blank_required(data, spec.fields))

    declared = data.get("type")
    if declared is not None and str(declared) != name:
        warnings.append(
            Note("type", f"says {declared!r} but the fence says {name!r}; the fence wins")
        )

    component_id = data.get("id")
    if component_id is None or not str(component_id).strip():
        component_id = derive_id(path, index)
        warnings.append(
            Note(
                "id",
                "no id given, so one was derived -- inserting a component "
                "above this one will move it",
            )
        )
    component_id = str(component_id).strip()
    if component_id in seen:
        warnings.append(
            Note(
                "id",
                f"duplicate id {component_id!r}; learner state keys on it and will collide",
            )
        )
    seen.add(component_id)

    for field_name, field_spec in spec.fields.items():
        if field_spec.default is not None and data.get(field_name) is None:
            data[field_name] = field_spec.default
    if spec.normalize and not errors:
        data = spec.normalize(data)
    # Only on a body that validated, which is what lets a hook assume the
    # shapes `fields` declared. See `ComponentType.warn`.
    if spec.warn and not errors:
        warnings.extend(spec.warn(data))

    try:
        version = int(data.get("v", spec.version))
    except (TypeError, ValueError):
        version = spec.version
        warnings.append(Note("v", "expected a version number; assuming 1"))

    return ComponentBlock(
        type=name,
        id=component_id,
        raw=body,
        lang=info,
        data=data,
        v=version,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def parse_document(source: str, path: str = "") -> Document:
    """A markdown artifact as frontmatter plus blocks. Never raises.

    `path` only feeds derived ids, so parsing a fragment with no path is fine
    and stays deterministic.
    """
    frontmatter, body = parse_frontmatter(source)
    blocks: list[Block] = []
    seen: set[str] = set()
    component_index = 0
    for kind, chunk, info in _scan(body):
        if kind == "markdown":
            if chunk.strip():
                blocks.append(MarkdownBlock(chunk))
            continue
        blocks.append(_build_component(chunk, info, path, component_index, seen))
        component_index += 1
    return Document(path=path, frontmatter=frontmatter, blocks=tuple(blocks))


# --- projection -----------------------------------------------------------


def _component_json(block: ComponentBlock, view: View) -> dict[str, Any]:
    spec = REGISTRY.get(block.type)
    learner = view == "learner"
    data = block.data
    if learner and spec is not None and spec.strip is not None and block.ok:
        data = spec.strip(data)
    out: dict[str, Any] = {
        "kind": "component",
        "type": block.type,
        "id": block.id,
        "v": block.v,
        "data": data,
        "errors": [{"path": n.path, "message": n.message} for n in block.errors],
        "withheld": list(spec.withheld) if (learner and spec) else [],
        "gradeable": bool(spec and spec.gradeable),
        # The client threads `projectId` into a renderer on this rather than
        # on a name list, so a build that adds a sixth resolved type needs no
        # client change to give it a project.
        "resolved": bool(spec and spec.resolved),
    }
    if block.unknown:
        out["unknown"] = True
    # The raw body is what an error panel shows and what an author reads back.
    # Withholding it from the learner view is the same ceremony as withholding
    # the fields -- the file itself is still fetchable -- but shipping the
    # answers to the page that is meant not to show them would be silly.
    if block.unknown or block.errors or not learner:
        out["raw"] = block.raw
        out["lang"] = block.lang
    if not learner:
        out["warnings"] = [{"path": n.path, "message": n.message} for n in block.warnings]
    return out


def project(document: Document, view: View = "author") -> dict[str, Any]:
    """The handoff the browser reads: blocks in order, secrets gone or not.

    `author` is everything, including warnings, because the author is the one
    who can act on them. `learner` drops the answer key structurally -- see the
    module docstring for why that is a real projection and what it does and
    does not guarantee.
    """
    return {
        "path": document.path,
        "view": view,
        "frontmatter": document.frontmatter,
        "blocks": [
            {"kind": "markdown", "text": b.text}
            if isinstance(b, MarkdownBlock)
            else _component_json(b, view)
            for b in document.blocks
        ],
    }


def validation_report(document: Document) -> str:
    """What the write path appends to a tool result, or "" when all is well.

    Terse on purpose: this is read by a model immediately after it wrote the
    file, in a context where it already has the source in front of it, so the
    id and the field path are the whole of what it needs.
    """
    lines: list[str] = []
    for component in document.components:
        for note in component.errors:
            lines.append(f"error: component {component.id!r} ({component.type}) -- {note}")
        for note in component.warnings:
            lines.append(f"warning: component {component.id!r} ({component.type}) -- {note}")
    return "\n".join(lines)
