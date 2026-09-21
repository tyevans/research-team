"""Turning free text into something safe to put in a filename or a key.

One function, kept out of its two callers so that `knowledge.py` and
`topic_dispatch.py` slug the same string the same way. It was in
`artifacts.py`, which is gone.
"""

import re

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """`SourceClaim` and `source claim` and `source_claim` all become one name.

    Both CamelCase and free prose reach this, and both have to land on a name
    that is stable across those spellings.
    """
    spaced = _CAMEL_BOUNDARY.sub("-", text)
    return _NON_SLUG.sub("-", spaced.lower()).strip("-")
