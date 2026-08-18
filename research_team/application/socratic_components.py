"""Components inside a dialogue's question, and the one projection of them.

The sibling of `ask_components.py`, and thin for the same reason: a dialogue's
question is a string and `parse_document` takes a string. It exists so that the
surfaces which render a dialogue -- the live SSE frame and the stored turn --
cannot disagree about what a component in a question means.

**The default view is `learner`, and here that is not a close call.** A
dialogue's whole method is asking rather than telling; shipping the answer key
on the frame that was meant to make the reader think would defeat the surface
rather than merely leak from it. `ask_components.py` argues the same default at
length and the argument only gets stronger here.
"""

from typing import Any

from research_team.application.components import View, parse_document, project

SOCRATIC_COMPONENT_TYPES: tuple[str, ...] = ("mcq", "cloze")
"""What a socratic dialogue may author.

Two types, and the list is a ruling rather than an inheritance -- the same
defect `COMPONENTS_FOR[BUILD]` was fixed to avoid, where a registry entry joined
a prompt by existing. The cost is that a third type has to be added in two
places; the benefit is that adding it is a decision somebody made.

**Gradeable only, because grading is what feeds the stopping condition.** A
dialogue that asks an `mcq` and marks the answer has evidence that the reader
demonstrated something (`EvidenceKind.attempt`); a dialogue that asks for prose
has the model's opinion of it (`EvidenceKind.assessment`). A stopping condition
met entirely by the second is a dialogue that graded its own homework, and these
two types are the only way this build can produce the first -- measured on
2026-08-17, `mcq` and `cloze` are the *only* entries in `REGISTRY` with
`gradeable=True`, so this tuple is currently every gradeable type there is. It
is still written out rather than filtered, because the next gradeable type to be
registered should have to be admitted here on purpose.

`flashcards` is out despite being in the ask's list, and the registry agrees:
its `gradeable` is False. It has no verdict, so nothing about it can be evidence
of anything.

The six resolved types are out for a *different* reason than the ask's, and the
difference is worth stating because the obvious argument does not apply. They
would resolve perfectly well here -- a dialogue has a project in scope where a
course file does not. They are out because nothing in a dialogue yet uses what
they draw, and offering a model six ways to answer with a picture, on a surface
whose entire method is questioning, is how this becomes a slideshow. Revisit
this entry first when the surface grows; `explorer` in particular is a plausible
second release, since inviting a reader to look is close to what a dialogue is
already doing.

`tests/application/test_socratic_components.py` fails on both halves of that
ruling: a type with `gradeable=False` or `resolved=True` entering this tuple is
caught there rather than discovered in a transcript.
"""


def dialogue_document(text: str, view: View = "learner") -> dict[str, Any]:
    """One dialogue utterance, parsed and projected.

    `path=""` because a dialogue has no file -- `Document.path` is a label used
    in error messages and derived ids, so an empty one is stable and honest
    rather than a fabricated filename a reader could try to open. Identical to
    `answer_document` in body, and deliberately not shared with it: the two
    surfaces will not keep the same default forever, and a shared helper is
    where that divergence becomes a change to both.
    """
    return project(parse_document(text, path=""), view=view)
