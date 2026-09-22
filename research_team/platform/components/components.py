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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import yaml

from research_team.platform.components.component_definitions import (
    CLOZE_BLANK as CLOZE_BLANK,
)
from research_team.platform.components.component_definitions import (
    EXPLORER_AXES as EXPLORER_AXES,
)
from research_team.platform.components.component_definitions import (
    EXPLORER_BACKING_READS as EXPLORER_BACKING_READS,
)
from research_team.platform.components.component_definitions import (
    BodyHook as BodyHook,
)
from research_team.platform.components.component_definitions import (
    _all_of as _all_of,
)
from research_team.platform.components.component_definitions import (
    _cloze_segments as _cloze_segments,
)
from research_team.platform.components.component_definitions import (
    _cloze_strip as _cloze_strip,
)
from research_team.platform.components.component_definitions import (
    _cloze_text_has_a_blank as _cloze_text_has_a_blank,
)
from research_team.platform.components.component_definitions import (
    _compare_collisions as _compare_collisions,
)
from research_team.platform.components.component_definitions import (
    _duplicates as _duplicates,
)
from research_team.platform.components.component_definitions import (
    _entity_ids_where_names_go as _entity_ids_where_names_go,
)
from research_team.platform.components.component_definitions import (
    _explorer_over as _explorer_over,
)
from research_team.platform.components.component_definitions import (
    _looks_like_id as _looks_like_id,
)
from research_team.platform.components.component_definitions import (
    _mcq_strip as _mcq_strip,
)
from research_team.platform.components.component_definitions import (
    build_registry as build_registry,
)
from research_team.platform.components.component_definitions import (
    get_registry as get_registry,
)
from research_team.platform.components.component_spec import (
    _UNIVERSAL as _UNIVERSAL,
)
from research_team.platform.components.component_spec import (
    Checker as Checker,
)
from research_team.platform.components.component_spec import (
    ComponentType as ComponentType,
)
from research_team.platform.components.component_spec import (
    Note as Note,
)
from research_team.platform.components.component_spec import (
    Spec as Spec,
)
from research_team.platform.components.component_spec import (
    _blank_required as _blank_required,
)
from research_team.platform.components.component_spec import (
    _check_fields as _check_fields,
)
from research_team.platform.components.component_spec import (
    _typename as _typename,
)
from research_team.platform.components.component_spec import (
    _unknown_keys as _unknown_keys,
)
from research_team.platform.components.component_spec import (
    flag as flag,
)
from research_team.platform.components.component_spec import (
    integer_between as integer_between,
)
from research_team.platform.components.component_spec import (
    listing as listing,
)
from research_team.platform.components.component_spec import (
    one_of as one_of,
)
from research_team.platform.components.component_spec import (
    string_list as string_list,
)
from research_team.platform.components.component_spec import (
    string_subset as string_subset,
)
from research_team.platform.components.component_spec import (
    text as text,
)
from research_team.platform.shared.frontmatter import parse_frontmatter

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


REGISTRY: dict[str, ComponentType] = get_registry()


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
