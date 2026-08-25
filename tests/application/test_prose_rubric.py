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

import pytest

from research_team.application import prose_rubric
from research_team.application.prose_rubric import (
    critic_reporting_contract,
    prose_rules,
)


def test_the_rubric_resolves_through_the_accessor():
    assert prose_rules().strip()


def test_the_rubric_states_six_numbered_rules():
    """Six, because the critic cites them by number and a dropped rule would
    silently stop being checked while every other rule still passed."""
    text = prose_rules()
    for n in range(1, 7):
        assert f"{n}." in text, f"rule {n} is missing"


def test_the_critics_contract_is_not_in_the_rules():
    """The split is what keeps the drafter from being handed the critic's
    instructions. If a future edit moved the separator or dropped it, the two
    accessors would return overlapping text and the drafter would silently be
    told to judge rather than write -- which no other test here would see,
    since both halves would still be non-empty and the six rules would still
    resolve."""
    assert "Report nothing else" not in prose_rules()
    assert "Report nothing else" in critic_reporting_contract()


def test_a_rubric_with_no_separator_raises(tmp_path, monkeypatch):
    """Rather than defaulting to 'it is all rules'. That default hands the
    critic an empty reporting contract, and a critic with no contract still
    answers -- in whatever shape it likes, with rule numbers that may not be
    there. Loud is the only way anyone finds out.

    Monkeypatched onto a copy rather than editing the real rubric in place: a
    test that rewrites a source file leaves the tree broken if it is
    interrupted, and this one would break every other test in the run.
    """
    stand_in = tmp_path / "prose_rubric.md"
    stand_in.write_text("1. A rule, and no separator anywhere.\n")
    monkeypatch.setattr(prose_rubric, "_RUBRIC_PATH", stand_in)
    with pytest.raises(ValueError, match="separator"):
        prose_rules()
