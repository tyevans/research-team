"""`tenant_id` means two things in this tree, and this is the mechanical guard.

Redstring's `tenant_id` is a *project* id -- `domain/project.py` says so, and
the name appears dozens of times inside `infrastructure/knowledge/` and in the
projection handlers that read `event.tenant_id` off a redstring event. Ours,
from `domain/tenant.py`, is a Zitadel organisation. Renaming redstring's is not
available; it is a library parameter name.

What makes that survivable rather than merely tolerable is that the two never
appear in the same function. The mitigation is a spelling: **at every call into
redstring the argument is written `tenant_id=project_id`** -- never
`tenant_id=tenant_id`, never positionally -- so the seam is visible at the call
site rather than in this docstring.

`tenant_id=tenant_id` is the one spelling that hides it: it is the form a
`**kwargs` forward or an IDE completion produces, it type-checks, it lints, and
at that call site there is no way to tell which of the two concepts is being
passed. This test is a grep, and a grep is the right instrument -- there is no
type to check, because both concepts would be a `str` or a `UUID` and the
compiler has never been able to tell them apart.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research_team"

COLLAPSED = re.compile(r"\btenant_id\s*=\s*tenant_id\b")
"""The forbidden spelling. Whitespace-tolerant, because
`tenant_id = tenant_id` in a call is the same hazard formatted differently."""

DEFERRED_TO_THE_B2_SWEEP: dict[str, int] = {
    "research_team/composition.py": 1,
    "research_team/infrastructure/knowledge/entity_cards.py": 2,
    "research_team/infrastructure/knowledge/entity_embeddings.py": 9,
}
"""The sites that already carried the spelling before the tenant concept existed.

**Counted on 2026-08-29 by running this test, not estimated.** Every one of them
is a redstring call where `tenant_id` is a project, forwarded from a parameter of
the same name -- so each is a genuine instance of the hazard and each needs the
argument rewritten as `tenant_id=project_id`, with the enclosing parameter
renamed. That rewrite is the seam sweep, and the design puts it in slice B2
(`docs/design/tenancy-and-authorization.md`, section 8), with this slice touching
no redstring-facing code at all.

An **exact count** rather than a file-level exemption, because a file-level one
would let a new offender in behind an old one -- which is the shape of stale
exemption this file's other test exists to catch. The count going *down* fails
too: an entry that outlives its offenders is an exemption for whatever is written
next, and clearing a file means deleting its line here.
"""


QUOTED = re.compile(r"`[^`]*`")
"""Prose quoting the forbidden spelling, which every doc that warns about it
must be able to do.

Stripped before the search rather than the search being narrowed, because the
convention in this tree is that a code fragment in prose is written in
backticks -- so "inside backticks" and "not code" coincide, and nothing this
test is for is ever written that way.
"""


def searchable(line: str) -> str:
    return QUOTED.sub("", line)


def python_files() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def test_there_are_python_files_to_search():
    """The direction that is always forgotten: a grep over nothing passes.

    Without this, moving the package or mistyping `SOURCE` would turn the test
    below into a permanent green that checks no code at all -- which is the
    same failure mode as a stale entry in a `PUBLIC_PATHS` set.
    """
    assert len(python_files()) > 100


@pytest.mark.parametrize("path", python_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_call_site_collapses_the_two_meanings_of_tenant_id(path: Path):
    """Parametrised per file so a failure names the offending path, not a count.

    If this fails on a genuine assignment rather than a call -- rebinding a
    tenant id to itself -- the fix is still to rename one side. The spelling is
    what the reader has to go on.
    """
    relative = str(path.relative_to(ROOT))
    offenders = [
        f"{relative}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if COLLAPSED.search(searchable(line))
    ]
    allowed = DEFERRED_TO_THE_B2_SWEEP.get(relative, 0)
    assert len(offenders) == allowed, (
        "write `tenant_id=project_id` at a redstring call site, or rename the "
        f"enclosing parameter; see `domain/tenant.py`. Expected {allowed} "
        f"pre-existing, found {len(offenders)}:\n" + "\n".join(offenders)
    )


def test_no_file_is_exempted_that_no_longer_needs_it():
    """The direction that is always forgotten.

    Without this, clearing a file during the B2 sweep would leave a stale entry
    in `DEFERRED_TO_THE_B2_SWEEP`, and the next `tenant_id=tenant_id` written in
    that file would be exempt by accident. A deleted file exempts everything at
    its path, which is worse.
    """
    stale = [
        name
        for name in DEFERRED_TO_THE_B2_SWEEP
        if not (ROOT / name).exists()
        or not any(
            COLLAPSED.search(searchable(line))
            for line in (ROOT / name).read_text().splitlines()
        )
    ]
    assert not stale, f"remove these from DEFERRED_TO_THE_B2_SWEEP: {stale}"


def test_the_grep_would_find_the_spelling_if_it_were_there():
    """Proves the pattern red without breaking a real file.

    A test whose only evidence is that a regex found nothing is a test that
    passes when the regex is wrong. These are the three forms the mitigation is
    written against, and the negative case is the one the docstring promises.
    """
    assert COLLAPSED.search("graph.open(tenant_id=tenant_id)")
    assert COLLAPSED.search("    tenant_id = tenant_id")
    assert COLLAPSED.search("f(a=1, tenant_id=tenant_id, b=2)")
    assert not COLLAPSED.search("graph.open(tenant_id=project_id)")
    assert not COLLAPSED.search("row.tenant_id = tenant_row.tenant_id")
    # And prose quoting the spelling is not an offender, or no document could
    # warn about it -- including this one.
    assert not COLLAPSED.search(searchable("never `tenant_id=tenant_id`"))
