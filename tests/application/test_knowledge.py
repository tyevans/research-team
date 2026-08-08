from research_team.application.knowledge import (
    IngestReport,
    KnowledgePort,
    Match,
    MergeRecord,
    SourceRef,
)


def test_source_ref_carries_an_optional_note():
    assert SourceRef(source_id="s", text="t").note is None
    assert SourceRef(source_id="s", text="t", note="why").note == "why"


def test_ingest_report_defaults_to_no_merges():
    report = IngestReport(
        source_id="s",
        entity_count=3,
        relationship_count=2,
        domain="encyclopedia_wiki",
        domain_confidence=0.0,
    )

    assert report.merges == ()
    assert report.consolidation_failures == 0


def test_a_stub_satisfies_the_port():
    """The Protocol is structural; this pins the exact signatures."""

    class Stub:
        async def ingest(self, source: SourceRef) -> IngestReport:
            return IngestReport(
                source_id=source.source_id,
                entity_count=0,
                relationship_count=0,
                domain=None,
                domain_confidence=None,
            )

        async def search(self, query: str, *, limit: int = 10) -> list[Match]:
            return []

        async def undo_merge(self, merge_id):
            return MergeRecord(
                merge_id=merge_id,
                canonical_name="c",
                absorbed_names=(),
                reason=None,
            )

    port: KnowledgePort = Stub()
    assert port is not None


def test_an_extraction_note_defaults_everything_it_does_not_know():
    """A note carries only what its stage actually established.

    Counts default to None rather than 0 because the difference matters: a
    `storing` note has no entity count, and reporting one as `0` would say
    extraction found nothing.
    """
    from research_team.application.knowledge import ExtractionNote

    note = ExtractionNote(source_id="notes", stage="storing")

    assert note.entities is None
    assert note.relationships is None
    assert note.domain_confidence is None
    assert note.index is None
    assert note.detail == ""


def test_a_note_keeps_a_zero_confidence_distinct_from_an_absent_one():
    """`0.0` means the classifier gave up; `None` means none ran.

    Collapsing them would report a fallback as a confident choice, which is
    the one thing `IngestReport.domain_confidence` exists to prevent.
    """
    from research_team.application.knowledge import ExtractionNote

    gave_up = ExtractionNote(
        source_id="n", stage="extracted", domain="x", domain_confidence=0.0
    )
    never_ran = ExtractionNote(source_id="n", stage="extracted", domain="x")

    assert gave_up.domain_confidence == 0.0
    assert never_ran.domain_confidence is None
