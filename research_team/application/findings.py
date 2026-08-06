"""What a check reports, in the one shape everything downstream reads.

This lives in its own module rather than in `checks.py` for a dependency
reason and no other. The check registry has to import the modules that
implement checks -- `coverage.py` implements `matrix_density` -- and those
modules have to return findings. With the type declared in `checks.py` that is
a cycle; with it here, the arrow runs one way from the registry to the
implementations, and both sides name one `Finding` instead of two that agree
until they quietly stop.

The definitions are `checks.py`'s, moved rather than rewritten.
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["Finding", "FindingSeverity"]

FindingSeverity = Literal["invariant", "blocking", "advisory", "human_gate", "critic_gate"]
"""Wider than the domain's `Severity`, by exactly three values.

`blocking` and `advisory` are what a preset may choose. `invariant` is what the
harness enforces regardless. The last two mark findings no run can clear by
itself, and they are distinct because who is owed the answer differs:
`human_gate` needs a person because no automated substitute exists at all,
while `critic_gate` needs a model call that the check library is deliberately
not allowed to make. Keeping all five in one vocabulary means a reviewer reads
one list; keeping the last three out of the domain's `Severity` means a preset
author cannot accidentally write one.
"""


@dataclass(frozen=True)
class Finding:
    """One thing wrong, addressed to whoever has to fix it.

    `suggested_edit` is prose, not a patch. A check knows what is missing and
    never what should fill the hole -- that judgement is the model's or the
    human's -- so anything more structured here would be a promise the library
    cannot keep.

    `affected_artifact_ids` is legitimately empty, and not as a degenerate
    case: a whole-matrix finding is about the grid rather than any cell of it,
    and an intrinsic matrix's empty row reports that *no artifact exists* for
    that axis value, which is precisely a finding with no id to name.
    """

    check: str
    severity: FindingSeverity
    message: str
    affected_artifact_ids: tuple[str, ...] = ()
    suggested_edit: str | None = None
