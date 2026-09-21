"""What a trigger reports, in the one shape everything downstream reads.

A module for one dataclass, which is more separation than one consumer would
justify. It had two: the check library, whose registry could not declare this
without a cycle back to the modules implementing its checks, and
`topic_attention.py`. The check library is deleted and `topic_attention.py` is
what remains.

Kept as its own module rather than folded into `topic_attention.py`, because
that module briefly declared a `Finding` of its own -- written while the check
library was unmerged -- and the two spent a release agreeing until somebody
joined them. A type with one consumer and a history of being duplicated is
cheaper to leave where a second consumer can find it than to move back. What
the join cost is one field name: see `cites`.
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["Finding", "FindingSeverity"]

FindingSeverity = Literal["blocking", "advisory", "human_gate"]
"""How much a finding stops the work it is about.

`blocking` means the thing cannot be usefully worked until it is addressed;
`advisory` means it is worth a look. `human_gate` is neither: it marks a
finding no run can clear by itself, because no automated substitute for the
answer exists at all.

Two more values were here -- `invariant`, for what the check harness enforced
regardless of a preset, and `critic_gate`, for a finding needing a model call
the check library was not allowed to make. Both named machinery that no longer
exists, and no trigger produced either.
"""


@dataclass(frozen=True)
class Finding:
    """One thing wrong, addressed to whoever has to fix it.

    `suggested_edit` is prose, not a patch. A check knows what is missing and
    never what should fill the hole -- that judgement is the model's or the
    human's -- so anything more structured here would be a promise the library
    cannot keep.

    `cites` is legitimately empty rather than degenerate: a finding can be
    about the absence of the thing it would otherwise name.
    """

    check: str
    """The rule that produced this: a `topic.*` trigger name. Named `check`
    while a check library was the other producer, and left alone rather than
    renamed with it -- the field is a rule's name either way, and a rename
    costs every stored and rendered reference to buy a synonym."""

    severity: FindingSeverity
    message: str

    cites: tuple[str, ...] = ()
    """What to look at first. Named for what it is *for*, not what it holds.

    It was `affected_artifact_ids` while checks were the only producer, which
    was exact and stopped being true: a topic trigger cites source ids and
    sub-question keys, and neither is an artifact. The two candidate names each
    fit one side and lied about the other -- for a check the ids were the thing
    *at fault*, and for a trigger they are the thing that *raised it*.

    `cites` is the common ground both answered: "what should I look at", with
    nothing claimed about whether it is evidence or a defect. Kept now that the
    check half is gone, because the surviving producer is the one it was
    renamed *for*.
    """

    suggested_edit: str | None = None
