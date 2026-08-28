"""The leading YAML block of a markdown file, separated from its prose.

A module of one function, because two unrelated callers need it and neither
should import the other: `components.py` renders a course file's body, and the
web layer reads a document's block to answer what it is. It was in
`artifacts.py`, whose other half was the workflow's file-naming conventions and
went with them.

**This parses. It does not judge.** `parse_frontmatter` reports what a file
contains and returns `None` where a validator would raise -- a caller that
wanted the prose still gets the prose from a malformed file, which is the
behaviour the docstring below was measured into.
"""

from typing import Any

import yaml

FRONTMATTER_FENCE = "---"


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """The leading YAML block as a mapping, and the body after it.

    `None` for a file with no block, an unparseable one, or one whose YAML is
    valid but is not a mapping -- a bare list parses cleanly and is still not
    frontmatter. None of the three is a reason to raise here: a run that produced one
    malformed file should still hand back the other twenty.

    **The two `None` cases return different bodies, and the difference is the
    whole point.** No delimited block at all: the body is the text unchanged,
    because there is nothing to have excluded. A delimited block that failed
    to parse: the body is still everything *after* the closing fence, not the
    fence and the block along with it. Structural identification (does the
    text open with `---` and close it on its own line) is separated from
    semantic validation (does the block between them parse as a mapping) on
    purpose, because the first question is answerable even when the second one
    fails.

    This was `text` in both cases until a real `builds_toward` field broke it:
    prose that names an assessment and states what it covers routinely
    contains a colon, which `yaml.safe_load` reads as a second mapping key
    (`mapping values are not allowed here`) rather than as punctuation in a
    string. That block is real frontmatter by every structural signal -- it is
    fenced, it opens the file, a human reading it calls it frontmatter -- and
    handing its caller "no block, body unchanged" put the whole block back in
    front of a markdown renderer, which reads `key: value` immediately
    followed by `---` as a setext heading. A caller that only wanted the prose
    now gets the prose, whether or not the block parsed; a caller that wants
    to know whether it parsed still gets `None` for that.
    """
    if not text.startswith(FRONTMATTER_FENCE):
        return None, text
    parts = text.split(f"\n{FRONTMATTER_FENCE}", 2)
    if len(parts) < 2:
        return None, text
    block = parts[0][len(FRONTMATTER_FENCE) :]
    body = parts[1].lstrip("-").lstrip("\n")
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:
        return None, body
    if not isinstance(loaded, dict):
        return None, body
    return loaded, body
