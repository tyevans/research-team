"""The ontology event's shape, which every later layer spells out by hand."""

from uuid import uuid4

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    OntologyDiscovered,
    RejectedMember,
)


def test_a_discovered_class_carries_members_evidence_and_the_count_it_claimed():
    project_id = uuid4()
    event = OntologyDiscovered(
        aggregate_id=project_id,
        project_id=project_id,
        source_id="sekaipedia-songs",
        model_version="test-model",
        classes=[
            DiscoveredClass(
                name="Difficulty",
                kind="ordered_scale",
                declared_count=6,
                evidence=EvidenceSpan(source_id="sekaipedia-songs", start=100, end=180),
                members=[
                    DiscoveredMember(name="EASY", ordinal=0),
                    DiscoveredMember(name="NORMAL", ordinal=1),
                ],
                rejected_members=[
                    RejectedMember(name="LEGEND", reason="not found in the document")
                ],
            )
        ],
    )

    assert event.aggregate_type == "Ontology"
    assert event.classes[0].members[1].name == "NORMAL"
    assert event.classes[0].declared_count == 6
    assert event.classes[0].rejected_members[0].reason == "not found in the document"


def test_a_class_may_state_no_count_and_no_parent():
    """The ordinary case. A table names its class without counting its rows,
    and most classes nest under nothing -- so both fields default rather than
    forcing every construction site to say `None` explicitly."""
    klass = DiscoveredClass(
        name="Rank",
        kind="ordered_scale",
        evidence=EvidenceSpan(source_id="s", start=0, end=10),
        members=[DiscoveredMember(name="S rank", ordinal=0)],
    )

    assert klass.declared_count is None
    assert klass.parent_name is None
    assert klass.rejected_members == []


def test_a_pass_that_found_nothing_is_still_a_recordable_event():
    """`classes=[]` records that this document was examined and states none.

    That is the difference between "grouped, nothing found" and "never
    grouped", and the whole `ungrouped` sweep is built on being able to tell
    them apart -- without it, every barren document is re-examined on every
    pass forever, at model cost.
    """
    project_id = uuid4()

    event = OntologyDiscovered(
        aggregate_id=project_id,
        project_id=project_id,
        source_id="songs",
        model_version="m",
    )

    assert event.classes == []
