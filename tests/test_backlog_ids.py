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


MARKER = re.compile(
    r"^<!-- next id: (\d+); B(\d+) claimed by: ([a-z0-9-]+) -->$", re.MULTILINE
)


def _marker() -> tuple[int, int, str]:
    found = MARKER.findall(BACKLOG.read_text())
    assert len(found) == 1, (
        f"BACKLOG.md holds {len(found)} allocation markers, and the allocation "
        "needs exactly one. Two of them is two counters, which is the race back "
        "again with a second place to look for it. The shape is "
        "`<!-- next id: N; B<n> claimed by: <slug> -->`."
    )
    next_id, claimed, slug = found[0]
    return int(next_id), int(claimed), slug


def _slug(heading: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", heading.lower())).strip("-")


def test_the_next_id_is_above_every_id_in_use() -> None:
    """The allocation, not a second uniqueness check.

    `test_no_two_backlog_entries_share_an_id` catches a collision after both
    entries exist, which is too late: it turns `main` red for everyone, and it
    happened on 2026-08-29 when #325 and #328 allocated B161 three minutes
    apart. Neither branch could see the other, neither conflicted -- each had
    written into a different half of the file -- and both were green.

    So the id is taken from one line that every filing branch rewrites, rather
    than from a grep of the branch's own copy.

    This assertion is one branch-local half. A branch that files an entry and
    does not bump the counter is red here, on its own PR, where the fix is its
    author's and costs nobody else -- and, more to the point, a branch that
    does not rewrite the marker has not conflicted with anything, so the
    merge-time half never runs for it.

    Red on 2026-08-29 with the counter left at 181 against B181 in the file.
    """
    ids = _ids()
    next_id, _, _ = _marker()
    assert next_id > max(ids), (
        f"BACKLOG.md's allocation marker says {next_id}, and B{max(ids)} is already "
        "in use. Set the line above every id in the file and take your own from "
        "it -- an id below the counter is one another branch may have taken while "
        "you could not see it."
    )


def test_the_marker_records_the_id_it_last_handed_out() -> None:
    """The counter and the claim have to describe the same allocation.

    Without this the claim is decoration: a branch could bump the counter and
    leave the previous branch's slug in place, which writes a line identical to
    one another branch may also write -- the whole defect this field exists to
    remove.
    """
    next_id, claimed, _ = _marker()
    assert claimed == next_id - 1, (
        f"BACKLOG.md's marker hands out {next_id} next but claims B{claimed} was "
        f"the last taken. Rewrite the whole line when you file: the id you took, "
        "your entry's slug, and that id plus one."
    )


def test_the_claimed_slug_matches_the_heading_that_took_the_id() -> None:
    """Why the marker carries a slug at all, and it is not documentation.

    The counter alone did not work, and the reason is that a counter is a value
    both branches *read the same* and so both write the same. Measured on
    2026-08-29: #345 and #340 each took 182 and each wrote `<!-- next id: 183 -->`.
    Identical rewrites of one line merge cleanly -- git had nothing to conflict
    on -- and the duplicate surfaced from `test_no_two_backlog_entries_share_an_id`
    on `main`, which is exactly what the counter had been added to prevent.

    Two branches filing two *different* entries cannot write the same slug, so
    the line differs and the second merge stops in front of a person. That was
    proved by merging two branches off one base, both filing, in the commit
    that introduced this field -- not reasoned.

    The claim is checked only when its entry is still in the file. Closed
    entries are deleted, and requiring the slug to survive the entry would make
    every close rewrite the allocation marker -- churn on a line whose whole
    value is that a rewrite of it means something.
    """
    _, claimed, slug = _marker()
    headings = re.findall(rf"^### B{claimed}\. (.+)$", BACKLOG.read_text(), re.MULTILINE)
    if not headings:
        return
    assert any(_slug(heading) == slug for heading in headings), (
        f"BACKLOG.md's marker claims B{claimed} was taken by `{slug}`, and B{claimed} "
        f"is headed {[_slug(heading) for heading in headings]}. The slug is what "
        "makes two filing branches write different lines; a slug that is not your "
        "own entry's may be one another branch writes too."
    )


def test_the_marker_is_documented_where_it_is_read() -> None:
    """Guards the marker against the failure the file's own header describes.

    A bare HTML comment near the top of a 5,000-line document is invisible: the
    obvious way to allocate an id is to grep for the largest one, which is
    exactly the read that allocated B161 twice. The marker only works if the
    header tells a reader to take the number from it *and* to rewrite the claim,
    so the instruction is part of the mechanism rather than commentary on it.

    Red if the paragraph is deleted while the comment stays -- which is the
    likelier direction, the comment being the part that looks load-bearing.
    """
    header = BACKLOG.read_text().split("## ", 1)[0]
    for phrase in ("next id", "slug", "rewrite"):
        assert phrase in header.lower(), (
            f"BACKLOG.md's header no longer says `{phrase}`. Without the "
            "instruction to take an id from the marker and rewrite the line with "
            "your own slug, the marker is a comment -- and the next person greps "
            "for the largest number instead, or bumps the counter and leaves a "
            "claim that another branch writes identically."
        )
