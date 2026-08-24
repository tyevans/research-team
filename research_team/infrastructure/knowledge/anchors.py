"""The anchor listing shared by the blurb and outline writers.

This module used to also hold `ungrounded_runs`, a check that refused any
capitalised run in a reply that was not a substring of an anchor's name --
the intent being to stop the model asserting entities the cluster does not
hold. It was dropped 2026-08-23, not weakened further, because the mechanism
did not match the intent: capitalisation marks a sentence's opening word as
often as it marks a proper noun. Measured against the live model over real
Star Trek clusters, the refusals it produced were `Students`, `Survey`,
`Trace`, `Examine`, `Building`, `Rating`, `You`, `American` -- ordinary
English opening a sentence, every one a false positive. A sweep over real
data put the refusal rate at roughly 80%, almost all of it this kind of
false positive: Star Trek, 71 candidates, 14 written, 57 refused; Skilljar,
22 candidates, 2 written, 20 refused.

It was also the wrong shape of check to begin with. "Nothing here is off the
anchor list" is a negative test, easy to trip by accident on ordinary prose,
and weak at what actually matters: a blurb can pass it while being wholly
generic and saying nothing in particular about the cluster. The eleven-word
`SENTENCE_OPENERS` exemption list this module used to carry was the previous
attempt to patch the false-positive rate, and its own comments already
warned that growing it toward "any ordinary word" would undo the fix -- which
was correct, and is exactly why the list could not be the actual answer.

A positive check -- require the copy to *name* at least two anchors -- was
considered as a replacement and is the better instrument for the stated
intent: it is a positive test, and it does not fire on capitalisation alone.
It was not built here; the decision on this pass was to drop the check
outright rather than replace it, so whoever revisits this should treat that
as the option still on the table, not a path already tried and rejected.

What is left is `anchor_lines`, needed by both writers to render the same
"these entities, which a knowledge graph clustered together" block into
their prompts.
"""

from collections.abc import Sequence

from research_team.application.course_authoring import PROMPT_ANCHORS
from research_team.domain.learning_area import AreaMember

__all__ = [
    "PROMPT_ANCHORS",
    "anchor_lines",
]

#: How many of an area's anchors are named in the prompt.
#:
#: `course_authoring.PROMPT_ANCHORS` itself rather than a second constant
#: equal to it: an area with sixty members does not become a better course by
#: having all sixty listed in two sentences of copy, it becomes copy with no
#: focus. The anchors are ranked by centrality within the area, so the first
#: twelve are the twelve the graph says the area is actually about. This
#: module previously carried its own copy of the number with a comment saying
#: it matched -- a comment is not a check, and the import is.


def anchor_lines(anchors: Sequence[AreaMember]) -> str:
    return "\n".join(f"- {m.name} ({m.entity_type})" for m in anchors[:PROMPT_ANCHORS])
