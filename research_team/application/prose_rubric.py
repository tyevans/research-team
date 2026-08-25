"""The one way to read the prose rubric.

The rubric is a Markdown file rather than a string literal because the
`prose-critic` subagent cites the rule it failed *by number*, and a rule you can
edit without touching Python is a rule you will actually iterate on after
reading a bad lesson. Editing a rule should not be a code change.

It sits here, beside this module, rather than under `prompts/`, because
`prompts/` is loaded wholesale by `load_prompts` and every file in it must be
named by some workflow preset -- `test_no_prompt_file_is_orphaned` in
`tests/application/test_ubd_prompts.py` fails otherwise. This rubric is quoted
inside two subagents' system prompts; it is never resolved as a stage's prompt,
so it would have failed that check for a reason that has nothing to do with it
being broken. Moving it out is what the check is *for*: a real orphan -- a
renamed stage whose prompt file was left behind -- still fails it, and no longer
competes with a false positive.

The accessor exists so that no caller reads the file by a path of its own.
`infrastructure/agent/authoring_subagents.py` imports `prose_rules()`; a second
literal path in a second package is a rename waiting to break one of the two
silently, since a subagent given an empty rubric still runs and still answers.
"""

from pathlib import Path

_RUBRIC_PATH = Path(__file__).resolve().parent / "prose_rubric.md"


def prose_rules() -> str:
    """The rubric's text, read from disk on every call.

    Not cached: it is read at import of the roster and nowhere in a hot path,
    and a cache would mean an edit to the Markdown needs a process restart to
    take effect -- exactly the iteration this file's format was chosen for.
    """
    return _RUBRIC_PATH.read_text()
