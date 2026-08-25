"""The rubric is a file, read at import time, not a string literal.

It matters that this is a file: the `prose-critic` cites the rule it failed by
number, and a rule you can edit without touching Python is a rule you will
actually iterate on after reading a bad lesson.

It lives beside the module that reads it (`research_team/application/`)
rather than under `prompts/`, because `prompts/` is loaded wholesale by
`load_prompts` and checked for files no preset names
(`test_no_prompt_file_is_orphaned` in `test_ubd_prompts.py`) -- this rubric
is cited by two subagents' system prompts, not resolved as a stage's prompt,
so it would fail that check for a reason that has nothing to do with it being
broken. Moving it out is the fix the check is meant to force: a real orphan
(a renamed stage) still fails it, and this file no longer competes with that
signal.

This test would pass with the rubric's *content* replaced by anything at all.
It checks resolvability and the rule count, which is what a later rename or a
truncated file would break; it cannot check that the rules are good ones.
"""

from pathlib import Path

RUBRIC_PATH = (
    Path(__file__).resolve().parents[2] / "research_team" / "application" / "prose_rubric.md"
)


def test_the_rubric_file_exists_beside_the_module_that_reads_it():
    assert RUBRIC_PATH.is_file()


def test_the_rubric_states_six_numbered_rules():
    """Six, because the critic cites them by number and a dropped rule would
    silently stop being checked while every other rule still passed."""
    text = RUBRIC_PATH.read_text()
    for n in range(1, 7):
        assert f"{n}." in text, f"rule {n} is missing"
