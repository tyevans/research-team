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

ASK_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze", "flashcards")
"""What the ask agent may author.

`checklist` is absent and that is a ruling, not an omission. A checklist is a
record of a procedure someone performed, and its only interesting mode is
`persist: true` -- which needs a learner identity the ask path deliberately
does not have. A checklist that cannot remember a tick is a list of bullets
with worse affordances than a list of bullets.
"""


def answer_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One ask answer, parsed and projected.

    `path=""` because an answer has no file. `Document.path` is a label used in
    error messages and derived ids -- `derive_id` hashes it with the block's
    index -- so an empty one is stable and honest rather than a fabricated
    filename that would look like something a reader could open.
    """
    return project(parse_document(text, path=""), view=view)
