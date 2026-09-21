"""The leading YAML block of a markdown file, separated from its prose.

Utility for separating markdown frontmatter from content, usable across
all bounded contexts and platform rendering components without cyclic
or reverse layer dependencies.
"""

import re
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


_H1_HEADING = re.compile(r"^\s*#\s+(.+)$", re.MULTILINE)


def extract_title(text: str) -> str | None:
    """Extract a title from YAML frontmatter (`title` key) or the leading markdown `# Heading`.

    Returns None if neither contains a non-empty title string (B139).
    """
    meta, body = parse_frontmatter(text)
    if meta and isinstance(meta.get("title"), str) and meta["title"].strip():
        return meta["title"].strip()
    target_text = body if meta is not None else text
    match = _H1_HEADING.search(target_text)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    return None
