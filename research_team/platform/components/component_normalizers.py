"""Component body normalizers, validators, and warn hooks.

Extracted from `component_definitions.py` to keep component schema definitions
and craft guidelines cleanly separated from their normalization and validation logic.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from research_team.platform.components.component_spec import (
    Note,
    text,
)

# Constants aligned with graph_read.MAX_NEIGHBORHOOD_DEPTH and
# timeline_read.MAX_TIMELINE_BANDS.
# Defined here so platform components do not form a circular import dependency on knowledge BC.
MAX_NEIGHBORHOOD_DEPTH = 2
MAX_TIMELINE_BANDS = 1_000

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


__all__ = [
    "CLOZE_BLANK",
    "EXPLORER_AXES",
    "EXPLORER_BACKING_READS",
    "MAX_NEIGHBORHOOD_DEPTH",
    "MAX_TIMELINE_BANDS",
    "BodyHook",
    "_all_of",
    "_cloze_segments",
    "_cloze_strip",
    "_cloze_text_has_a_blank",
    "_compare_collisions",
    "_duplicates",
    "_entity_ids_where_names_go",
    "_explorer_over",
    "_looks_like_id",
    "_mcq_strip",
]
