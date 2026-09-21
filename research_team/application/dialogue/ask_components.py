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
    "explorer",
)
"""What the ask agent may author.

`checklist` is absent and that is a ruling, not an omission. A checklist is a
record of a procedure someone performed, and its only interesting mode is
`persist: true` -- which needs a learner identity the ask path deliberately
does not have. A checklist that cannot remember a tick is a list of bullets
with worse affordances than a list of bullets.

All six resolved types are here, and for the opposite reason. An ask is
precisely where a reader asks about the corpus, and a resolved component is
the only thing in this registry that can answer with what the project actually
holds rather than with what the model can describe. A widget whose reference
misses renders as prose, so the cost of offering one that does not land is a
word rather than an error -- which is what makes offering all six at once
reasonable rather than reckless.

Written out rather than derived from `REGISTRY`, deliberately. A derived tuple
is how the old stage-prompt guidance came to advertise five widgets that could
not resolve where its prompt was used: a registry entry joined a prompt by
existing. That guidance is deleted; the way it went wrong is not.
The cost of this list is that a new type has to be added in two places; the
benefit is that adding it is a decision somebody made. Measured on 2026-08-17:
this reference is 3,040 characters with the three original types, 7,947 with
eight, and 9,600 with all nine -- paid on every ask turn.

`explorer` is the ninth and the first that is not a view but an invitation: the
reader re-runs the author's query rather than reading the one the author chose.
It belongs here for the same reason the other resolved types do -- an ask is
where a reader asks about the corpus -- and it is the type an ask suits best,
because an ask reader arrived with a question rather than with a curriculum.

It is also the most expensive entry in this tuple: re-measured on 2026-08-17
when it was added, `explorer` alone costs 1,653 of those characters -- six
craft notes where `timeline` has four -- and `ASK_PROMPT` went from 11,302 to
12,955. That is the price of the ninth type, and it is charged on every turn
whether or not the model writes one.
"""


def answer_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One ask answer, parsed and projected.

    `path=""` because an answer has no file. `Document.path` is a label used in
    error messages and derived ids -- `derive_id` hashes it with the block's
    index -- so an empty one is stable and honest rather than a fabricated
    filename that would look like something a reader could open.
    """
    return project(parse_document(text, path=""), view=view)
