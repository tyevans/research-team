"""Component specifications, field checkers, and registry entry schema.

Separated from `components.py` so that validation primitives, field schemas,
and `ComponentType` can be imported by `component_definitions.py` without
circular import workarounds or deferred function-level imports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


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


_UNIVERSAL = {"id", "type", "v", "objective"}
"""Accepted on every component. `type` restates the info string for robustness,
`objective` names the learning objective an item aligns to, which is what makes
backward-design coverage checkable over a whole course."""


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


# --- the registry schema --------------------------------------------------


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
