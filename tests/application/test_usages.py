"""`Usage`/`UsageReadPort`: the shape a usages read exposes above `infrastructure/knowledge/`.

No adapter under test here -- `test_usage_reader.py` covers the retrieval
behaviour. This file only pins the contract: a frozen, hashable-by-value
record and a `Protocol` any adapter can satisfy structurally, with no
redstring type reachable from either (`tests/test_architecture.py` enforces
the same thing at the module-import level; this asserts it at the value
level, which catches a stray redstring type hiding behind `Any`).
"""

import dataclasses
from typing import Protocol

from research_team.application.usages import Usage, UsageReadPort


def test_usage_is_a_frozen_dataclass_of_plain_types():
    usage = Usage(source_id="doc-1", start=0, end=4, text="Acme", score=1.5)

    assert dataclasses.is_dataclass(usage)
    assert dataclasses.replace(usage, score=2.0).score == 2.0
    with_frozen_error = None
    try:
        usage.score = 9.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError as error:
        with_frozen_error = error
    assert with_frozen_error is not None


def test_usage_read_port_is_a_plain_structural_protocol():
    """No other port in this codebase is `@runtime_checkable` (`KnowledgePort`,
    `CorpusReadPort`, etc. are all plain `Protocol`s satisfied by duck typing
    at the type-checker level, not by `isinstance`), so `UsageReadPort`
    matches that rather than introducing a new pattern here."""
    assert issubclass(UsageReadPort, Protocol)

    class FakeReader:
        async def usages(self, entity_id, *, limit: int = 20) -> list[Usage]:
            return []

    # No inheritance from UsageReadPort, and none is required: a type
    # checker accepts FakeReader wherever UsageReadPort is asked for, purely
    # from its shape. Calling it here is what the shape has to support.
    reader: UsageReadPort = FakeReader()
    assert reader.usages is not None
