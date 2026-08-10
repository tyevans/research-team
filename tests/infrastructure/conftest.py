"""Fixtures shared by the tests that build a `RedstringKnowledge` for real.

`build_adapter` lived in `test_redstring_adapter.py` until a second module
needed it. Moved rather than copied: it owns the teardown that closes two
`aiosqlite` connections, and a second copy of that is a second place for a
non-daemon worker thread to be forgotten and resurface as an unrelated test's
"Event loop is closed".
"""

import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import InMemoryGraphStore

from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import build_corpus_repository
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
            ),
            store,
            snapshot_store,
        )

    yield _build

    for snapshot_store in opened_snapshot_stores:
        await snapshot_store.close()
    for store in opened_event_stores:
        await store.close()
