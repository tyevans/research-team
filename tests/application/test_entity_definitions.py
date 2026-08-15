"""`DefinitionService`: a grounded definition, generated once and cached.

No live model call anywhere here. `FakeDefinitionModel` returns canned text
and records every call, because the two behaviours that carry this feature --
the cache hit and the ungrounded-entity guard -- are both statements about
*calls not made*, which no assertion on returned text can distinguish from a
call that happened and returned the same thing.
"""

import json
from uuid import UUID, uuid4

import pytest

from research_team.application.entity_definitions import (
    Citation,
    Definition,
    DefinitionService,
)
from research_team.application.graph_read import (
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.application.usages import Usage

ACME = UUID("11111111-1111-1111-1111-111111111111")
BARE = UUID("22222222-2222-2222-2222-222222222222")


class FakeDefinitionModel:
    """Canned text, plus a count and the last prompt.

    `calls` is a count rather than a bool: "did it call the model" and "did it
    call the model *again*" are different questions, and the staleness test
    asks the second one.
    """

    def __init__(self, reply: str | None = None) -> None:
        self.calls = 0
        self.last_prompt: str | None = None
        self._reply = (
            reply
            if reply is not None
            else json.dumps(
                {
                    "text": "Acme is a supplier of widgets.",
                    "citations": [{"source_id": "doc-1", "start": 0, "end": 14}],
                }
            )
        )

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        self.last_prompt = prompt
        return self._reply


class FakeGraph:
    def __init__(self, neighborhoods: dict[str, Neighborhood]) -> None:
        self._neighborhoods = neighborhoods

    async def find_entities(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def whole(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def neighborhood(self, entity_id: str, *, depth: int = 1):
        return self._neighborhoods.get(entity_id)


class FakeUsages:
    def __init__(self, by_entity: dict[UUID, list[Usage]]) -> None:
        self._by_entity = by_entity

    async def usages(self, entity_id: UUID, *, limit: int = 20) -> list[Usage]:
        return self._by_entity.get(entity_id, [])[:limit]


class FakeCache:
    """An in-memory stand-in for `EntityDefinitionStore`, in the port's terms.

    Not the real store: this suite is about what the service decides, and a
    SQLite table would only re-test `test_definition_read_model.py`.
    """

    def __init__(self) -> None:
        self.rows: dict[UUID, Definition] = {}

    async def get(self, entity_id: UUID) -> Definition | None:
        return self.rows.get(entity_id)

    async def put(self, entity_id: UUID, definition: Definition) -> None:
        self.rows[entity_id] = definition


def _acme_neighborhood() -> Neighborhood:
    root = GraphEntity(entity_id=str(ACME), name="Acme", entity_type="Organization")
    other = GraphEntity(entity_id=str(uuid4()), name="Widget Co", entity_type="Organization")
    return Neighborhood(
        root=root,
        entities=(other,),
        relationships=(
            GraphRelationship(
                source_id=root.entity_id,
                target_id=other.entity_id,
                relationship_type="supplies",
            ),
        ),
    )


def _service(model: FakeDefinitionModel, cache: FakeCache) -> DefinitionService:
    graph = FakeGraph(
        {
            str(ACME): _acme_neighborhood(),
            str(BARE): Neighborhood(
                root=GraphEntity(entity_id=str(BARE), name="Nobody", entity_type="Person"),
                entities=(),
                relationships=(),
            ),
        }
    )
    usages = FakeUsages(
        {
            ACME: [
                Usage(
                    source_id="doc-1",
                    start=0,
                    end=40,
                    text="Acme supplies widgets to Widget Co.",
                    score=1.0,
                )
            ]
        }
    )
    return DefinitionService(graph=graph, usages=usages, cache=cache, model=model)


@pytest.mark.asyncio
async def test_a_fresh_cached_definition_is_returned_without_calling_the_model():
    """The cache is the entire point; a hit that still pays for a call is the
    defect this test exists to catch. Fails if the staleness check is dropped
    -- and would still pass on returned text alone, which is why it asserts on
    the call count instead."""
    model = FakeDefinitionModel()
    service = _service(model, FakeCache())

    first = await service.define(ACME)
    assert first is not None
    calls = model.calls
    assert calls == 1

    second = await service.define(ACME)
    assert second is not None
    assert model.calls == calls


@pytest.mark.asyncio
async def test_a_stale_definition_is_regenerated_on_the_next_call():
    model = FakeDefinitionModel()
    cache = FakeCache()
    service = _service(model, cache)

    await service.define(ACME)
    cache.rows[ACME] = Definition(
        text=cache.rows[ACME].text,
        citations=cache.rows[ACME].citations,
        model=cache.rows[ACME].model,
        generated_at=cache.rows[ACME].generated_at,
        stale=True,
    )

    regenerated = await service.define(ACME)
    assert model.calls == 2
    assert regenerated is not None
    assert regenerated.stale is False


@pytest.mark.asyncio
async def test_the_prompt_carries_the_passages_and_the_edges():
    model = FakeDefinitionModel()
    service = _service(model, FakeCache())

    await service.define(ACME)

    prompt = model.last_prompt
    assert prompt is not None
    assert "Acme supplies widgets to Widget Co." in prompt
    assert "supplies" in prompt
    assert "Widget Co" in prompt
    assert "doc-1" in prompt


@pytest.mark.asyncio
async def test_an_entity_with_no_passages_and_no_edges_is_not_sent_to_the_model():
    """There is nothing to ground a definition in, and a model asked to define
    a bare name will answer from what it already knows -- which is precisely
    the ungrounded gloss this feature exists to avoid. Fails if the guard is
    removed."""
    model = FakeDefinitionModel()
    service = _service(model, FakeCache())

    result = await service.define(BARE)

    assert result is None
    assert model.calls == 0


@pytest.mark.asyncio
async def test_a_definition_citing_nothing_is_refused_rather_than_stored():
    """An ungrounded definition is worse than none: it reads exactly like a
    correct one. Nothing is cached, so nothing gets served later as though it
    had been checked."""
    model = FakeDefinitionModel(json.dumps({"text": "Acme is a company.", "citations": []}))
    cache = FakeCache()
    service = _service(model, cache)

    assert await service.define(ACME) is None
    assert cache.rows == {}


@pytest.mark.asyncio
async def test_citations_outside_the_supplied_passages_are_dropped():
    """A citation the service cannot check against a passage it supplied is a
    span the model invented; keeping it would put an unverifiable offset in
    front of a reader who has no way to tell it apart from a real one."""
    model = FakeDefinitionModel(
        json.dumps(
            {
                "text": "Acme supplies widgets.",
                "citations": [
                    {"source_id": "doc-1", "start": 0, "end": 20},
                    {"source_id": "doc-9", "start": 5, "end": 9},
                ],
            }
        )
    )
    service = _service(model, FakeCache())

    definition = await service.define(ACME)

    assert definition is not None
    assert definition.citations == [Citation(source_id="doc-1", start=0, end=20)]


@pytest.mark.asyncio
async def test_force_regenerates_a_definition_that_is_not_stale():
    model = FakeDefinitionModel()
    service = _service(model, FakeCache())

    await service.define(ACME)
    await service.define(ACME, force=True)

    assert model.calls == 2
