"""Deterministic placeholder art. Increment 3 replaces the implementation."""

from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider


def test_the_same_slug_gets_the_same_art_every_time():
    """Stable across runs, because a catalog whose illustrations reshuffle on
    every request is a catalog nobody can recognise a card in."""
    provider = SeededArtProvider()

    assert provider.for_candidate("warp", "work") == provider.for_candidate("warp", "work")


def test_different_slugs_get_different_art():
    provider = SeededArtProvider()

    assert provider.for_candidate("warp", "work") != provider.for_candidate("vulcan", "work")


def test_the_alt_text_names_the_candidate_rather_than_describing_decoration():
    """A browsing surface where every image is "decorative" is a surface a
    screen reader cannot tell one card from another in."""
    art = SeededArtProvider().for_candidate("warp-drive", "work")

    assert "warp-drive" in art.alt.lower()


def test_the_art_is_stable_across_processes_not_just_within_one():
    """`hash()` is salted per process in Python, so an implementation built on
    it would pass every same-process test and still reshuffle every card
    between server restarts. This pins the actual bytes."""
    import subprocess
    import sys

    code = (
        "from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider;"
        "print(SeededArtProvider().for_candidate('warp', 'work').url)"
    )
    first = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert first.stdout == second.stdout
    assert first.stdout.strip() == SeededArtProvider().for_candidate("warp", "work").url
