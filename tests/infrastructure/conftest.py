"""Fixtures shared by the tests that build a `RedstringKnowledge` for real.

`build_adapter` lived in `test_redstring_adapter.py` until a second module
needed it. Moved rather than copied: it owns the teardown that closes two
`aiosqlite` connections, and a second copy of that is a second place for a
non-daemon worker thread to be forgotten and resurface as an unrelated test's
"Event loop is closed".
"""

from uuid import UUID, uuid4

import httpx
import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import FakeLlmProvider, InMemoryGraphStore

from research_team.application.corpus_read import (
    CorpusReadError,
    SourceListing,
    StoredDocument,
    TextSourceUri,
)
from research_team.application.knowledge import SourceRef
from research_team.application.topics import TopicError
from research_team.domain.corpus import Corpus, StoreSourceDocument
from research_team.infrastructure.agent.corpus_tools import build_corpus_tools
from research_team.infrastructure.agent.fetch import build_fetch_tool
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools
from research_team.infrastructure.agent.search import build_search_tool
from research_team.infrastructure.agent.topic_tools import build_topic_tools
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
    build_judgements_repository,
)
from research_team.infrastructure.persistence.read_models import CorpusStore, to_record
from tests.conftest import TWO_PEOPLE, fake_provider


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

    async def list_text_uris(self) -> list[TextSourceUri]:
        """The port's third method, and the one this fake first shipped without.

        `fetch.stored_page` calls it on every fetch to decide whether the page
        is already in the corpus, so a fake missing it raises `AttributeError`
        from inside production code rather than failing a protocol check -- the
        stack names `fetch.py`, which is the one file that is not wrong.

        A `Protocol` is structural, so nothing verifies a fake against it: the
        gap is invisible until a test happens to reach the method. Any method
        added to `CorpusReadPort` has to be added here by hand, and will
        announce itself the same way.
        """
        rows = await self._store.list_all(self._project_id)
        return [
            TextSourceUri(source_id=row.source_id, uri=row.uri)
            for row in rows
            if getattr(row, "uri", None) and getattr(row, "kind", "text") == "text"
        ]


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


_MAGIC_ANSWER = {
    "entities": [{"name": "Magic Square", "entity_type": "Concept"}],
    "relationships": [],
}
"""One entity, no relationships -- the orphan
`test_an_unlinked_entity_survives_to_the_artifact` needs to see a `0` in
`relationship_count` at all."""


@pytest.fixture
async def seeded_graph(tmp_path, build_adapter):
    """A `RedstringKnowledge` holding one linked pair and one orphan, for the
    artifact tests to search and describe.

    Seeded through `knowledge.ingest` -- the writer -- which is a different
    code path from `search`/`describe`, so this cannot hide a search that
    stopped reading what ingest wrote (CLAUDE.md's fixture rule is about a
    *read* path seeding through itself; ingest and search share no code here).

    Two documents rather than one, matched by substring on their text: the
    default answer (`TWO_PEOPLE`, imported from `tests.conftest`) links Ada
    Lovelace to Charles Babbage, and any text containing "Magic" gets
    `_MAGIC_ANSWER` instead -- one entity, no relationships, findable by
    `graph_search("magic")` and guaranteed to carry `relationship_count == 0`.
    """
    project_id = uuid4()
    provider = FakeLlmProvider(by_substring={"Magic": _MAGIC_ANSWER}, default=TWO_PEOPLE)
    knowledge, _store, _snapshots = build_adapter(tmp_path, project_id, provider=provider)
    await knowledge.ingest(
        SourceRef(source_id="pair", text="Ada Lovelace worked with Charles Babbage.")
    )
    await knowledge.ingest(
        SourceRef(source_id="orphan", text="A study of Magic squares and their properties.")
    )
    return knowledge


@pytest.fixture
async def empty_corpus(db_path):
    """A corpus with no sources -- the miss path, `Acknowledgement`/empty
    shapes rather than a `None` artifact."""
    store = await CorpusStore.open(db_path)
    try:
        yield _CorpusStoreReadPort(store, uuid4())
    finally:
        await store.close()


class FakeTopics:
    """A minimal in-memory `TopicPort`, for the tools that touch topics.

    Copied in miniature from `test_topic_tools.py`'s fixture of the same
    name rather than imported from it: that class lives in a test module
    (deliberately so its own file needs no conftest indirection to read), and
    importing a test module from a fixture file would run its collection as
    an import side effect. This keeps only what `all_tools`/`live_tools` need
    to drive a real call through -- see that file for the fuller fake, which
    exercises the port's error paths directly.
    """

    def __init__(self) -> None:
        self.known: set[UUID] = set()

    async def list_topics(self, project_id):
        return []

    async def open_topic(self, project_id, question, rationale, scope=""):
        topic_id = uuid4()
        self.known.add(topic_id)
        return topic_id

    async def record_finding(self, topic_id, summary, source_ids):
        if topic_id not in self.known:
            raise TopicError(f"no topic {topic_id} in this project. Use `list_topics`.")

    async def record_gap(self, topic_id, looking_for, tried):
        if topic_id not in self.known:
            raise TopicError(f"no topic {topic_id} in this project. Use `list_topics`.")

    async def link_source(self, topic_id, source_id, note=""):
        if topic_id not in self.known:
            raise TopicError(f"no topic {topic_id} in this project. Use `list_topics`.")


@pytest.fixture
def topic_port() -> FakeTopics:
    return FakeTopics()


_SEARXNG_PAYLOAD = {
    "results": [
        {"title": "Magic squares", "url": "https://a.example", "content": "A grid of numbers."}
    ]
}


def _searxng_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_SEARXNG_PAYLOAD)


def _search_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_searxng_handler))


_FETCH_HTML = (
    "<html><head><title>Magic Squares</title></head><body>"
    "<article><p>A magic square is a grid where every row, column and "
    "diagonal sums to the same constant. " * 5 + "</p></article></body></html>"
)


def _fetch_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, html=_FETCH_HTML)


def _fetch_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_fetch_handler))


@pytest.fixture
def all_tools(seeded_corpus, seeded_graph, topic_port):
    """Every converted tool this feature touches, over real (or stubbed-transport)
    backends -- for `test_remaining_tool_artifacts.py`'s per-shape parametrize.

    `search`/`fetch` use a stubbed `httpx` transport rather than the network,
    the same convention `test_search.py`/`test_fetch.py` use elsewhere in this
    package; nothing here is a fixture built through the code path it is
    meant to test, so it does not fall under the CLAUDE.md fixture rule that
    rules out seeding through the reader under test.
    """
    tools: list = []
    tools.extend(build_corpus_tools(seeded_corpus))
    tools.extend(build_knowledge_tools(seeded_graph))
    tools.extend(build_topic_tools(topic_port, uuid4()))
    tools.append(build_search_tool("http://searx.local", client=_search_client()))
    tools.append(build_fetch_tool(client=_fetch_client(), corpus=seeded_corpus))
    return tools


@pytest.fixture
def live_tools(all_tools):
    """`(tool, args)` pairs covering every converted tool, for
    `test_tool_artifacts_from_real_tools.py`'s contract test -- the one that
    drives a real tool call into a real artifact rather than asserting a
    renderer can read a hand-written literal (CLAUDE.md's *port with one
    adapter* rule: a channel that shipped fully unit-tested from both sides
    and drove neither into the other produced nothing for a whole feature).

    Arguments are chosen to land in the tool's *successful* branch wherever
    one exists over this fixture set, because a shape only counts as
    "produced by a real tool call" here if some call actually produces it --
    an error-path Acknowledgement from every tool would leave `hit_list`,
    `entity_list`, `excerpt` and `inventory` all unproduced and the contract
    test would (correctly) fail.
    """
    by_name = {tool.name: tool for tool in all_tools}
    pairs = [
        (by_name["list_sources"], {}),
        (by_name["search_sources"], {"pattern": "magic"}),
        (by_name["read_source"], {"source_id": "seed-one"}),
        (by_name["graph_search"], {"query": "magic"}),
        (by_name["graph_describe"], {"query": "magic"}),
        (by_name["remember"], {"text": "A note.", "source_id": "live-tools-note"}),
        (by_name["unmerge"], {"merge_id": str(uuid4())}),
        (by_name["list_topics"], {}),
        (by_name["open_topic"], {"question": "Why?", "rationale": "Because."}),
        (by_name["web_search"], {"query": "magic squares"}),
        (by_name["fetch"], {"url": "https://example.test/magic"}),
    ]
    return pairs
