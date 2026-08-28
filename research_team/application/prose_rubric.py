"""The one way to read the prose rubric, and the reason it has two halves.

The rubric is a Markdown file rather than a string literal because the
`prose-critic` subagent cites the rule it failed *by number*, and a rule you can
edit without touching Python is a rule you will actually iterate on after
reading a bad lesson. Editing a rule should not be a code change.

It sits beside this module rather than in a shared prompt directory, and that
placement is now the only thing keeping the two apart. There was a `prompts/`
tree, loaded wholesale, whose every file had to be named by something that
resolved prompts; a rubric quoted *inside* two subagents' system prompts rather
than resolved as one would have read there as an orphan. That tree is gone with
the workflow system, so nothing enforces the separation any more -- the file
stays here because a rule the critic cites by number belongs next to the code
that reads it, which was the better half of the reason all along.

**Two readers, two accessors.** The file's tail is the critic's reporting
contract: judge only these, report nothing else, do not rewrite the lesson. Read
by a drafter, those are three instructions that fight the only instruction a
drafter has, plus an OUTPUT contract competing with the real one further down
its prompt -- the likely result being a critique where a lesson should be. So
`prose_rules()` returns the rules alone and `critic_reporting_contract()`
returns the tail, and only `prose-critic` is given both. The rules above the
separator are worded to read correctly to a writer and a judge alike; that is a
property of the prose, which nothing can check, so it has to be maintained by
whoever edits the file.

These accessors exist so that no caller reads the file by a path of its own. A
second literal path in a second package is a rename waiting to break one of the
two silently, since a subagent given an empty rubric still runs and still
answers.
"""

import re
from pathlib import Path

_RUBRIC_PATH = Path(__file__).resolve().parent / "prose_rubric.md"

SEPARATOR = "--- CRITIC ONLY:"

_EDITOR_NOTE = re.compile(r"<!--.*?-->", re.DOTALL)


def _halves() -> tuple[str, str]:
    """The file, minus its editor's note, split once on the separator.

    The HTML comment at the top of the file is addressed to whoever edits the
    rubric, not to either subagent, and it names both of them -- a drafter told
    what the critic is given has been told something it can only act on wrongly.
    Stripping it here means the note can be as long as it needs to be.

    A missing separator raises rather than defaulting to "it is all rules",
    because that default hands the critic an empty reporting contract and it
    still answers, in whatever shape it likes.
    """
    text = _EDITOR_NOTE.sub("", _RUBRIC_PATH.read_text())
    if SEPARATOR not in text:
        raise ValueError(f"{_RUBRIC_PATH} has no {SEPARATOR!r} separator")
    rules, _, tail = text.partition(SEPARATOR)
    return rules.strip(), tail.partition("\n")[2].strip()


def prose_rules() -> str:
    """What good prose is. Given to `lesson-drafter` and to `prose-critic`.

    Read from disk on every call, not cached: it is read at import of the
    subagent roster and nowhere in a hot path, and a cache would mean an edit to
    the Markdown needs a process restart to take effect -- exactly the iteration
    this file's format was chosen for. The roster is the exception that eats
    that benefit anyway: `authoring_subagents.py` binds the result to a module
    constant at import, so both prompts freeze at process start regardless.
    """
    return _halves()[0]


def critic_reporting_contract() -> str:
    """How to report a failure. Given to `prose-critic` alone.

    Not to the drafter -- see this module's docstring for what happens when it
    is.
    """
    return _halves()[1]
