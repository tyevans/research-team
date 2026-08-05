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
