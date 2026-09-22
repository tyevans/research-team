"""Component definitions, normalizers, and the registry table.

Modularized from `research_team.platform.components` so that component
schemas, craft guidelines, and their normalizers live together beside the
registry table while keeping `components.py` as the public facade.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from research_team.platform.components.component_spec import (
    ComponentType,
    Note,
    Spec,
    flag,
    integer_between,
    listing,
    one_of,
    string_list,
    string_subset,
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


BodyHook = Callable[[dict[str, Any]], list["Note"]]


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


def build_registry() -> dict[str, ComponentType]:
    return {
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
                "```component:graph\n"
                "id: constantine-around\n"
                "entity: Constantine\n"
                "depth: 1\n"
                "```"
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


REGISTRY: dict[str, ComponentType] = {}


def get_registry() -> dict[str, ComponentType]:
    """Return the shared component registry dictionary."""
    if not REGISTRY:
        REGISTRY.update(build_registry())
    return REGISTRY


__all__ = [
    "CLOZE_BLANK",
    "EXPLORER_AXES",
    "EXPLORER_BACKING_READS",
    "REGISTRY",
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
    "build_registry",
    "get_registry",
]
