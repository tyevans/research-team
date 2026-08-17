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

from research_team.application.artifacts import parse_frontmatter
from research_team.domain.workflow import ArtifactType

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


COMPONENT_PROMPT = "\n\n## Interactive components\n\n" + component_reference()
"""The reference as a prompt fragment, computed once from the registry.

Carried in the stage instructions rather than in every session's base prompt:
components are how a *course artifact* becomes something a learner can do
rather than only read, and a session driving no preset is not writing one. The
same reasoning puts `WORKFLOW_PROMPT` there.
"""


COMPONENTS_FOR: Mapping[ArtifactType, tuple[str, ...]] = {
    # UbD Stage 2 evidence, and ADDIE's assessment items: the components that
    # have a right answer. A deck is not evidence of anything.
    ArtifactType.EVIDENCE_SPEC: ("mcq", "cloze"),
    # UbD Stage 3's learning plan and ADDIE's treatment: practice, not
    # assessment. Recall and procedure, where being wrong costs nothing.
    ArtifactType.EXPERIENCE: ("flashcards", "cloze", "checklist"),
    # ADDIE Development. §3.8: "the whole catalog; this is where components get
    # authored." The one stage that should reach for anything.
    ArtifactType.BUILD: tuple(REGISTRY),
    # Organising experiences: a sequence a learner or facilitator works
    # through is a checklist, and `ordering` is not registered yet.
    ArtifactType.SEQUENCE: ("checklist",),
    # Implementation: the facilitator's run-of-show.
    ArtifactType.MONITORING_PLAN: ("checklist",),
}
"""Which components belong in which artifact, from the design's §3.8 table.

Keyed by artifact type rather than by framework stage, because a stage's
*outputs* are what this codebase actually declares -- so the guidance a stage
receives is derived from the preset, the same way its paths and its frontmatter
already are, and adding an output to a stage updates its component guidance
with it rather than leaving the two to drift.

Deliberately partial. `Rubric`, `Criteria` and `TaxonomySelection` all have a
natural component in §3.8 and none of it is registered yet, so they are absent
rather than mapped to an approximation: telling a model to express a rubric as
a checklist would get a rubric-shaped checklist, which is worse than prose.
"""


def component_guidance(outputs: Iterable[Any]) -> str:
    """What to tell a stage about components, or nothing at all.

    Nothing is the common case and it is the point. A stage writing source
    claims has no use for two kilobytes of widget syntax, and a prompt that
    carries it anyway teaches the model that most of its instructions do not
    apply to it -- which is a habit that costs far more than the tokens.

    When a stage *does* write a component-bearing artifact, the occasion and
    the syntax arrive together: knowing that an assessment item wants an `mcq`
    is useless without knowing how to write one, and knowing how to write one
    is useless without knowing when.
    """
    fits: dict[str, tuple[str, ...]] = {}
    for output in outputs:
        names = COMPONENTS_FOR.get(output.artifact_type)
        if not names:
            continue
        label = output.artifact_type.value
        if getattr(output, "subtype", None):
            label = f"{label} ({output.subtype})"
        fits[label] = names
    if not fits:
        return ""

    lines = [
        "",
        "",
        "## Interactive components in this stage's artifacts",
        "",
        "These outputs are read by a learner, not only by a reviewer. Where one",
        "of them would be better done than read, write the component rather than",
        "describing it in prose:",
        "",
    ]
    lines += [f"- **{label}** — {', '.join(names)}" for label, names in fits.items()]
    lines += [
        "",
        "Prose is still right for explanation. A component earns its place when",
        "the learner should *do* something -- recall it, decide it, work through",
        "it -- not when they should understand it.",
        "",
        "If you delegate any of this with `task`, put the component requirement",
        "in the task you write. A subagent cannot see this conversation or these",
        'instructions, so a task that says only "draft the assessment items"',
        "comes back as prose, and nothing will tell you why -- it reads like a",
        "model that ignored a requirement it was never given. Name the component",
        "types it should use and tell it to emit fenced `component:` blocks.",
        "",
        # Narrowed to what this stage was just told fits, in registry order so
        # the reference reads the same wherever it appears.
        component_reference(only=[n for n in REGISTRY if any(n in v for v in fits.values())]),
    ]
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
