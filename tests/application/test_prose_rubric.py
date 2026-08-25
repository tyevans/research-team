"""The rubric, read through the accessor production reads it through.

An earlier version of this test opened `prose_rubric.md` by a path it built
itself. That path is not the one production uses, so an accessor that returned
an empty string -- or that pointed at a file that had been moved -- would have
left this test green while every subagent quoting the rubric judged nothing.
CLAUDE.md records the general shape under fixtures that arrange through a
different call than the one under test: a test that does not go through the
production seam cannot see that seam break.

What this still cannot do is judge whether the rules are good ones. It checks
that the rubric resolves and that six numbered rules are in it, which is what a
rename or a truncated file would break.
"""

from research_team.application.prose_rubric import prose_rules


def test_the_rubric_resolves_through_the_accessor():
    assert prose_rules().strip()


def test_the_rubric_states_six_numbered_rules():
    """Six, because the critic cites them by number and a dropped rule would
    silently stop being checked while every other rule still passed."""
    text = prose_rules()
    for n in range(1, 7):
        assert f"{n}." in text, f"rule {n} is missing"
