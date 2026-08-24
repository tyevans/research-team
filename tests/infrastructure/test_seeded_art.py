"""Deterministic placeholder art. Increment 3 replaces the implementation."""

from uuid import uuid4

from research_team.domain.course_catalog import CourseCandidate
from research_team.infrastructure.knowledge.seeded_art import _PALETTES, SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import (
    CATEGORY_LABELS,
    UNCLASSIFIED,
)

_PROJECT = uuid4()


def _candidate(slug: str, category: str) -> CourseCandidate:
    return CourseCandidate(
        slug=slug,
        title=slug,
        category=category,
        prominence=1.0,
        size=1,
        membership_hash="h",
        anchors=(),
        art=None,  # type: ignore[arg-type]  # SeededArtProvider never reads this field
    )


async def test_the_same_slug_gets_the_same_art_every_time():
    """Stable across runs, because a catalog whose illustrations reshuffle on
    every request is a catalog nobody can recognise a card in."""
    provider = SeededArtProvider()

    first = await provider.for_candidate(_PROJECT, _candidate("warp", "work"))
    second = await provider.for_candidate(_PROJECT, _candidate("warp", "work"))

    assert first == second


async def test_different_slugs_get_different_art():
    provider = SeededArtProvider()

    a = await provider.for_candidate(_PROJECT, _candidate("warp", "work"))
    b = await provider.for_candidate(_PROJECT, _candidate("vulcan", "work"))

    assert a != b


async def test_the_alt_text_names_the_candidate_rather_than_describing_decoration():
    """A browsing surface where every image is "decorative" is a surface a
    screen reader cannot tell one card from another in."""
    art = await SeededArtProvider().for_candidate(_PROJECT, _candidate("warp-drive", "work"))

    assert "warp-drive" in art.alt.lower()


async def test_the_art_is_stable_across_processes_not_just_within_one():
    """`hash()` is salted per process in Python, so an implementation built on
    it would pass every same-process test and still reshuffle every card
    between server restarts. This pins the actual bytes."""
    import subprocess
    import sys

    code = (
        "import asyncio;"
        "from uuid import uuid4;"
        "from research_team.domain.course_catalog import CourseCandidate;"
        "from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider;"
        "c = CourseCandidate(slug='warp', title='warp', category='work', prominence=1.0,"
        " size=1, membership_hash='h', anchors=(), art=None);"
        "print(asyncio.run(SeededArtProvider().for_candidate(uuid4(), c)).url)"
    )
    first = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert first.stdout == second.stdout
    pinned = await SeededArtProvider().for_candidate(_PROJECT, _candidate("warp", "work"))
    assert first.stdout.strip() == pinned.url


def test_every_category_the_default_grouper_emits_has_its_own_palette():
    """The two tables live in different modules and nothing but this test makes
    them agree. Before it existed, `place` was a palette for a key no grouper
    emits, while `location`, `organization` and `category` all fell through to
    the uncategorised grey -- three of eight categories rendering as "we don't
    know what this is" on a surface whose whole job is grouping.

    `unclassified` is excluded on purpose, not to weaken this assertion: grey
    is the deliberate rendering for it (see `_UNCATEGORISED_BASE`'s docstring
    in `seeded_art.py`), so it is correctly absent from `_PALETTES` and would
    otherwise make this test fail for a choice, not a gap.
    """
    unpalettedkeys = [k for k in CATEGORY_LABELS if k not in _PALETTES and k != UNCLASSIFIED]

    assert unpalettedkeys == []
