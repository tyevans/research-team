"""Inbound ports required by the Knowledge bounded context.

Defines the contracts that external providers (such as corpus readers)
must satisfy from Knowledge's perspective, avoiding direct dependencies
on the Research bounded context.
"""

from typing import Any, Protocol


class CorpusReadPort(Protocol):
    """Source reading contract needed for ontology discovery and entity definitions."""

    async def read_document(self, source_id: str, *, include_dropped: bool = False) -> Any: ...


__all__ = ["CorpusReadPort"]
