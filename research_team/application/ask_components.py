"""Components inside an ask answer, and the one projection of them.

An ask answer is a string, and `parse_document` takes a string -- so this
module is thin on purpose. It exists so the two surfaces that render an answer
(the live SSE frame and the stored turn) cannot disagree about what a component
in an answer means, and so the learner default is written down once.

**The default view is `learner` here and `author` on a file, and the
asymmetry is deliberate.** The console's file reader is the person building the
course, so showing them their own key is right. Nobody reads an ask answer as
its author -- the model wrote it, and the reader is the one being asked. There
is no caller for whom `author` is the right default, so it is not the default.

What this does *not* claim is that the key is out of reach: the raw answer text
travels beside these blocks (see the route), so withholding here is the
affordance "don't show me the answer until I've tried" rather than a boundary.
The design's section 5 states this at length, and `BACKLOG.md` records it.
"""

from typing import Any

from research_team.application.components import View, parse_document, project

ASK_COMPONENT_TYPES: tuple[str, ...] = (
    "mcq",
    "cloze",
    "flashcards",
    "definition",
    "evidence",
    "graph",
    "timeline",
    "compare",
)
"""What the ask agent may author.

`checklist` is absent and that is a ruling, not an omission. A checklist is a
record of a procedure someone performed, and its only interesting mode is
`persist: true` -- which needs a learner identity the ask path deliberately
does not have. A checklist that cannot remember a tick is a list of bullets
with worse affordances than a list of bullets.

The five resolved types are all here, and for the opposite reason. An ask is
precisely where a reader asks about the corpus, and a resolved component is
the only thing in this registry that can answer with what the project actually
holds rather than with what the model can describe. A widget whose reference
misses renders as prose, so the cost of offering one that does not land is a
word rather than an error -- which is what makes offering all five at once
reasonable rather than reckless.

Written out rather than derived from `REGISTRY`, deliberately. A derived tuple
is how `COMPONENTS_FOR[BUILD]` came to advertise five widgets that cannot
resolve where its prompt is used: a registry entry joined a prompt by existing.
The cost of this list is that a sixth type has to be added in two places; the
benefit is that adding it is a decision somebody made. Measured on 2026-08-17:
this reference is 3,040 characters with the three original types and 7,947
with all eight, paid on every ask turn.
"""


def answer_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One ask answer, parsed and projected.

    `path=""` because an answer has no file. `Document.path` is a label used in
    error messages and derived ids -- `derive_id` hashes it with the block's
    index -- so an empty one is stable and honest rather than a fabricated
    filename that would look like something a reader could open.
    """
    return project(parse_document(text, path=""), view=view)
