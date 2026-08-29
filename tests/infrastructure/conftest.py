"""Fixtures shared by the tests that build a `RedstringKnowledge` for real.

`build_adapter` lived in `test_redstring_adapter.py` until a second module
needed it. Moved rather than copied: it owns the teardown that closes two
`aiosqlite` connections, and a second copy of that is a second place for a
non-daemon worker thread to be forgotten and resurface as an unrelated test's
"Event loop is closed".
"""

from uuid import uuid4

import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import InMemoryGraphStore

from research_team.application.corpus_read import (
    CorpusReadError,
    SourceListing,
    StoredDocument,
)
from research_team.domain.corpus import Corpus, StoreSourceDocument
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
    build_judgements_repository,
)
from research_team.infrastructure.persistence.read_models import CorpusStore, to_record
from tests.conftest import fake_provider


@pytest.fixture
async def build_adapter():
    """Factory fixture for a `RedstringKnowledge` over a real `SQLiteEventStore`.

    Both stores hold a long-lived `aiosqlite` connection with a non-daemon
    worker thread, and both must be closed or that thread lingers past the
    test and surfaces later as an unrelated test's "Event loop is closed".
    Some tests call this factory only once, but it is shaped to support more --
    everything it opens is tracked and closed in teardown, so nothing here can
    be forgotten by a future test that calls it twice.

    `SQLiteSnapshotStore` used to open a connection per operation and need no
    closing. That stopped being true in eventsource 0.12, which gave it one
    connection for its lifetime and a `close()` to match.

    `embeddings` and `vector_store` default to None -- **two features, not
    three** -- even though the application now defaults to three. That is
    deliberate: most tests here are about the adapter's bookkeeping and would
    pay an embedding call per entity to assert nothing about it. The tests that
    are about *scoring* pass both, and `test_embedded_consolidation.py` is
    where the difference between two features and three is pinned.
    """
    opened_event_stores = []
    opened_snapshot_stores = []

    def _build(
        tmp_path,
        project_id,
        *,
        provider=None,
        adjudicate=False,
        embeddings=None,
        vector_store=None,
        card_vector_store=None,
        cards=None,
        judgements=False,
        **knowledge_kwargs,
    ):
        db_path = str(tmp_path / "sessions.db")
        store = SQLiteEventStore(db_path)
        snapshot_store = SQLiteSnapshotStore(db_path)
        opened_event_stores.append(store)
        opened_snapshot_stores.append(snapshot_store)
        return (
            RedstringKnowledge(
                project_id,
                store=InMemoryGraphStore(),
                event_store=store,
                snapshot_store=snapshot_store,
                provider=provider if provider is not None else fake_provider(),
                corpus=build_corpus_repository(store, snapshot_store=snapshot_store),
                domain="encyclopedia_wiki",
                # Off by default: most tests here are about the adapter's own
                # bookkeeping and an adjudicator would put a second, unrelated
                # schema in every fake provider's way. Tests about *whether two
                # things merge* must turn it on -- with it off the ambiguous
                # band is rejected, which is redstring's stated behaviour and
                # not something this adapter can work around.
                adjudicate=adjudicate,
                embeddings=embeddings,
                vector_store=vector_store,
                card_vector_store=card_vector_store,
                cards=cards,
                # A flag rather than a repository, because the repository has
                # to be built over the store this factory creates and a caller
                # cannot reach it until after the call returns. Off by default
                # for the same reason `embeddings` is: a test about the
                # adapter's bookkeeping should not pay an event-store read per
                # consolidation to load an empty judgement set.
                judgements=(
                    build_judgements_repository(store, snapshot_store=snapshot_store)
                    if judgements
                    else None
                ),
                # `concurrency` and `chunker` reach `RedstringKnowledge`
                # through here rather than as named parameters. Both default
                # to redstring's serial behaviour, so every test that does not
                # name one is unaffected by their existence -- which is the
                # property worth keeping as more knobs arrive.
                **knowledge_kwargs,
            ),
            store,
            snapshot_store,
        )

    yield _build

    for snapshot_store in opened_snapshot_stores:
        await snapshot_store.close()
    for store in opened_event_stores:
        await store.close()


class _CorpusStoreReadPort:
    """`CorpusReadPort` over a real `CorpusStore`, for `test_corpus_tool_artifacts.py`.

    Deliberately not `ProjectCorpusReader` (`infrastructure/persistence/corpus_reader.py`):
    that class reads through a `CorpusRunner`, whose `list_all`/`get` are the
    very calls the artifact tests exist to exercise -- a fixture built on them
    would seed the corpus through the same path the tool reads it back on, and
    CLAUDE.md's "Read models" section is explicit that such a fixture cannot
    see that path go missing. This wraps `CorpusStore` directly instead, which
    the seeding fixtures below never touch except through `projection.handle`.
    """

    def __init__(self, store: CorpusStore, project_id) -> None:
        self._store = store
        self._project_id = project_id

    async def list_sources(self) -> list[SourceListing]:
        try:
            rows = await self._store.list_all(self._project_id)
        except RuntimeError as error:
            raise CorpusReadError(str(error)) from error
        return [SourceListing(record=to_record(row), extracted=False) for row in rows]

    async def read_document(self, source_id: str) -> StoredDocument | None:
        row = await self._store.get(self._project_id, source_id)
        if row is None:
            return None
        return StoredDocument(
            record=to_record(row), text=row.text, locator_map=row.locator_map
        )


async def _seed(store: CorpusStore, project_id, *documents: StoreSourceDocument) -> None:
    """Write documents by driving the aggregate, then folding its events into
    `store.projection` -- the writer's path, not the reader's. Mirrors
    `test_corpus_read_model.py`'s `_events`/`_project` helpers.
    """
    corpus = Corpus(project_id)
    for command in documents:
        corpus.execute(command)
    for event in corpus.uncommitted_events:
        await store.projection.handle(event)


@pytest.fixture
async def seeded_corpus(db_path):
    """A corpus holding two real documents, for the artifact tests to search
    and read. Seeded through `Corpus`/`CorpusProjection` -- the writer -- and
    never through `list_sources`/`read_document`, which are the calls under
    test.
    """
    store = await CorpusStore.open(db_path)
    project_id = uuid4()
    await _seed(
        store,
        project_id,
        StoreSourceDocument(
            corpus_id=project_id,
            source_id="seed-one",
            text="A study of magic squares and their properties. " * 20,
            title="Magic Squares",
        ),
        StoreSourceDocument(
            corpus_id=project_id,
            source_id="seed-two",
            text="The history of stage magic and illusion. " * 5,
            title="Stage Magic",
        ),
    )
    try:
        yield _CorpusStoreReadPort(store, project_id)
    finally:
        await store.close()


@pytest.fixture
async def empty_corpus(db_path):
    """A corpus with no sources -- the miss path, `Acknowledgement`/empty
    shapes rather than a `None` artifact."""
    store = await CorpusStore.open(db_path)
    try:
        yield _CorpusStoreReadPort(store, uuid4())
    finally:
        await store.close()
