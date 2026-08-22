"""That a composed application actually indexes entity cards.

**This file exists because the feature is silent when unwired.** `index_cards`
is optional on `ProjectGraphs`, so omitting it from `composition.py` leaves
`cards()` answering `None`, every card query returning nothing, and every
other test in the tree green -- the module's own tests pass because they call
it directly. `CLAUDE.md` records this shape twice under "the helper works,
nobody calls it", and once under an event no projection handles: a missing
wiring produces an empty read model rather than a refusal.

So the assertion here is on *data* -- a card exists and names a neighbour --
never that opening a project returned without raising.
"""

from uuid import uuid4

import pytest
from redstring import rank_chunks, tokenize

from research_team.application.knowledge import SourceRef
from research_team.composition import build_application
from tests.conftest import fake_provider


@pytest.mark.asyncio
async def test_a_composed_app_cards_an_ingested_entity(db_path, monkeypatch):
    """Ingest a document, reopen the project, and find an entity by its neighbour.

    The reopen is the point: cards are built during `ProjectGraphs.open` from
    the folded graph, so a test that only ingested would pass against a build
    that never indexed anything.

    Fails with `index_cards=` deleted from `composition.py`'s `ProjectGraphs`
    call -- which is the single edit this file exists to catch, and the one
    every other test in the tree is blind to.
    """
    monkeypatch.setenv("AGENT_DB", db_path)
    monkeypatch.setenv("AGENT_CHUNK_STORE", "memory")
    monkeypatch.setenv("AGENT_VECTOR_STORE", "none")

    application = build_application(db_path=db_path)
    await application.start()
    try:
        project_id = uuid4()
        await application.attach_project(project_id)
        knowledge = application.knowledge
        assert knowledge is not None
        # The real provider is replaced rather than the whole adapter: what is
        # under test is composition's wiring, so everything but the model call
        # must stay the object `build_application` made.
        knowledge._provider = fake_provider()
        await knowledge.ingest(
            SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
        )

        # The reopen is the point: cards are built during `open` from the
        # folded graph, so a test that only ingested would pass against a
        # build that never indexed anything.
        await application.graphs.close(project_id)
        await application.graphs.open(project_id)

        cards = application.graphs.cards(project_id)
        assert cards is not None, "a composed build must index cards"

        terms = tokenize("Charles Babbage")
        found = await cards.lexical_candidates(terms, project_id, 10)
        ranked = list(rank_chunks(terms, found, 10))

        assert ranked, "the card corpus must hold something naming Babbage"
        assert any("Ada Lovelace" in candidate.chunk.text for candidate in ranked), (
            "Ada's card must name her neighbour -- that edge is the whole feature"
        )
    finally:
        await application.close()
