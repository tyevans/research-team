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


NEXT_ID = re.compile(r"^<!-- next id: (\d+) -->$", re.MULTILINE)


def _next_id() -> int:
    found = NEXT_ID.findall(BACKLOG.read_text())
    assert len(found) == 1, (
        f"BACKLOG.md holds {len(found)} `next id` lines, and the allocation needs "
        "exactly one. Two of them is two counters, which is the race back again "
        "with a second place to look for it."
    )
    return int(found[0])


def test_the_next_id_is_above_every_id_in_use() -> None:
    """The allocation, not a second uniqueness check.

    The test above catches a collision after both entries exist, which is too
    late: it turns `main` red for everyone, and it happened on 2026-08-29 when
    #325 and #328 allocated B161 three minutes apart. Neither branch could see
    the other, neither conflicted -- each had written into a different half of
    the file -- and both were green.

    So the id is taken from one line that every filing branch rewrites, rather
    than from a grep of the branch's own copy. Two branches rewriting one line
    to different values is a conflict git cannot resolve, which puts the
    disagreement in front of a person at the merge instead of in CI on `main`.
    The property secured is the one a per-branch gate cannot secure: two
    branches that cannot see each other cannot pick the same id, because
    neither can merge without reading what the other allocated.

    This assertion is the branch-local half. A branch that files an entry and
    does not bump the counter is red here, on its own PR, where the fix is its
    author's and costs nobody else -- and, more to the point, a branch that
    does not bump the counter has not conflicted with anything, so the
    merge-time half never runs for it.

    Red on 2026-08-29 with the counter left at 181 against B181 in the file.
    """
    ids = _ids()
    assert _next_id() > max(ids), (
        f"BACKLOG.md's `next id` line says {_next_id()}, and B{max(ids)} is already "
        "in use. Set the line above every id in the file and take your own from "
        "it -- an id below the counter is one another branch may have taken while "
        "you could not see it."
    )


def test_the_next_id_line_is_documented_where_it_is_read() -> None:
    """Guards the counter against the failure the file's own header describes.

    A bare HTML comment near the top of a 5,000-line document is invisible: the
    obvious way to allocate an id is to grep for the largest one, which is
    exactly the read that allocated B161 twice. The counter only works if the
    header tells a reader to take the number from it, so the instruction is
    part of the mechanism rather than commentary on it.

    Red if the paragraph is deleted while the comment stays -- which is the
    likelier direction, the comment being the part that looks load-bearing.
    """
    header = BACKLOG.read_text().split("## ", 1)[0]
    assert "next id" in header and "increment" in header, (
        "BACKLOG.md's header no longer tells a reader to take an id from the "
        "`next id` line and increment it. Without that sentence the counter is "
        "a comment, and the next person greps for the largest number instead."
    )
