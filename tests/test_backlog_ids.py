"""`BACKLOG.md`'s ids have to be unique, because `git log` is a design record.

B116 filed ten duplicated ids. There were fifteen. Every commit message,
design document and CLAUDE.md entry citing one of them had been ambiguous for
as long as the second entry existed, and nothing anywhere would have said so
-- a duplicate heading renders fine, greps fine, and reads fine.

A test rather than a script under `scripts/`: this repository has no
`scripts/` directory and four CI gates, one of which is `pytest`. A check that
runs in a gate people already run beats a check that has to be remembered.
"""

import re
from collections import Counter
from pathlib import Path

BACKLOG = Path(__file__).resolve().parent.parent / "BACKLOG.md"
HEADING = re.compile(r"^### B(\d+)\.", re.MULTILINE)


def _ids() -> list[int]:
    return [int(match) for match in HEADING.findall(BACKLOG.read_text())]


def test_no_two_backlog_entries_share_an_id() -> None:
    """The whole contract. Red on 2026-08-29 against fifteen collisions:
    B36, B54, B58, B59, B60, B62, B63, B79, B80, B81, B110, B122, B153, B154
    and B155 -- the ten B116 enumerated, plus five it did not."""
    duplicated = sorted(id_ for id_, count in Counter(_ids()).items() if count > 1)
    assert not duplicated, (
        f"BACKLOG.md ids used more than once: {duplicated}. Renumber the *later* "
        "entry -- an older commit is likelier to be citing the older one -- and "
        "leave a line under the new heading saying what it used to be."
    )


def test_the_backlog_has_entries_to_check() -> None:
    """Guards the test above against its own success mode.

    `HEADING` is a regex over a file this test does not own. Change the
    heading level or the id prefix and `_ids()` returns an empty list, at
    which point the uniqueness assertion passes over nothing and reads exactly
    like a clean backlog. This is the tell.
    """
    assert len(_ids()) > 100
