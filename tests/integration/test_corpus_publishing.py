"""A stored document reaches the table the Documents pane reads.

The corpus read model follows the log through the in-memory bus, and an
aggregate repository only announces on that bus if it was handed one. The
corpus repository was the one repository in `composition.py` built without it,
so `CorpusDocumentStored` was appended and nothing woke: the events were in the
log, `topic_corpus_facts` had them (its repository does publish), and
`corpus_documents` stayed empty for the life of the process. On screen that is
"Documents" listing nothing while research is visibly fetching pages.

Both tests fail with the publisher argument removed again.
"""

from uuid import uuid4

from research_team.domain.corpus import StoreSourceDocument


async def test_a_stored_document_appears_in_the_corpus_read_model(build_application):
    """Store through the application's own corpus repository; list it back.

    Reaches for `application.knowledge._corpus` rather than calling `ingest`
    because `ingest` runs extraction against a model endpoint, and the store
    happens before that on purpose (see `_store_document`). The private
    attribute is the point: it is the repository production writes documents
    through, and a repository built in the test would prove nothing about
    composition.
    """
    project = uuid4()
    application = await build_application(project_id=project)

    corpus = await application.knowledge._corpus.load_or_create(project)
    corpus.execute(
        StoreSourceDocument(
            corpus_id=project,
            source_id="s1",
            text="Tollers were bred in Yarmouth County.",
            uri="https://example.invalid/toller",
            title="The breed",
        )
    )
    await application.knowledge._corpus.save(corpus)

    await application.corpus_caught_up()
    listings = await application.corpus.list(project)
    assert [listing.record.source_id for listing in listings] == ["s1"]
    # Stored but never extracted, which is now a state the listing can express
    # -- and the one every `store_source` from an unattended run leaves behind.
    assert [listing.extracted for listing in listings] == [False]


async def test_every_repository_composition_builds_announces_its_writes(build_application):
    """No aggregate repository is built without the bus the projections follow.

    The class, not just the corpus instance. Every read model here is fed by
    `InMemoryEventBus`, so a repository without a publisher is a silent write
    as far as every table is concerned -- and nothing in the signature says
    so, because `event_publisher` is optional and defaults to None. This is
    the check that would have caught the corpus one on the day it was written.
    """
    import sys

    from eventsource.application.aggregates.repository import AggregateRepository

    built: list[tuple[str, bool]] = []
    original = AggregateRepository.__init__

    def recording(self, event_store, aggregate_factory, *args, **kwargs):
        original(self, event_store, aggregate_factory, *args, **kwargs)
        # Only the ones this project builds. redstring constructs its own
        # `ConsolidationLog` repository internally and takes no publisher
        # argument, so holding it to this rule would be asserting against a
        # dependency's wiring rather than ours.
        caller = sys._getframe(1).f_globals.get("__name__", "")
        if caller.startswith("research_team"):
            built.append((aggregate_factory.__name__, self.event_publisher is not None))

    AggregateRepository.__init__ = recording
    try:
        # A project, so `open_graph` runs and the repositories only built on
        # the attached path are built too -- the corpus one is in there.
        await build_application(project_id=uuid4())
    finally:
        AggregateRepository.__init__ = original

    assert built, "composition built no repositories; this test is not checking anything"
    assert [name for name, publishes in built if not publishes] == []
