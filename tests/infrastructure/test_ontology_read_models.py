"""The ontology tables: what they store and what they refuse to lose."""

import json
from uuid import uuid4

import pytest

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)
from research_team.infrastructure.persistence.read_models import OntologyStore


def _difficulty() -> DiscoveredClass:
    return DiscoveredClass(
        name="Difficulty",
        kind="ordered_scale",
        declared_count=6,
        evidence=EvidenceSpan(source_id="songs", start=10, end=90),
        members=[
            DiscoveredMember(name="EASY", ordinal=0),
            DiscoveredMember(name="NORMAL", ordinal=1),
        ],
        rejected_members=[RejectedMember(name="LEGEND", reason="not in the document")],
    )


@pytest.fixture
async def store(db_path):
    opened = await OntologyStore.open(db_path)
    yield opened
    await opened.close()


@pytest.fixture
def other_project_id():
    return uuid4()


async def test_a_stored_class_keeps_its_checksum_its_evidence_and_its_rejections(
    store, project_id
):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="2026-08-15T00:00:00Z"
    )

    (row,) = await store.classes_for(project_id)

    assert row.name == "Difficulty"
    assert row.kind == "ordered_scale"
    # The checksum and what was actually found, both stored. Storing only the
    # difference would make "5 of 6" indistinguishable from "5 of 5".
    assert (row.declared_count, row.member_count) == (6, 2)
    assert (row.evidence_start, row.evidence_end) == (10, 90)
    assert json.loads(row.rejected_members) == [
        {"name": "LEGEND", "reason": "not in the document"}
    ]


async def test_members_keep_the_order_the_text_gave_them(store, project_id):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    (row,) = await store.classes_for(project_id)

    members = await store.members_for(row.id)

    assert [(m.member_name, m.ordinal) for m in members] == [("EASY", 0), ("NORMAL", 1)]


async def test_re_running_replaces_a_source_rather_than_appending_to_it(store, project_id):
    """The pass is re-run whenever its prompt changes. Without replacement
    every re-run would double the classes and the graph would grow a duplicate
    hub per attempt. Would pass with `replace_for_source` implemented as an
    append only if this asserted a count of one, which is why it does."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m2", generated_at="t2"
    )

    rows = await store.classes_for(project_id)

    assert len(rows) == 1
    assert rows[0].model == "m2"


async def test_a_re_run_that_no_longer_finds_a_class_removes_it(store, project_id):
    """The half of replacement that an upsert would miss. A prompt that stops
    producing a class must not leave the old one on the canvas forever."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    await store.replace_for_source(project_id, "songs", [], model="m2", generated_at="t2")

    assert await store.classes_for(project_id) == []


async def test_replacing_one_source_leaves_another_sources_classes_alone(store, project_id):
    """A pass over one document must not clear a class discovered in another.
    Nothing else here would catch a DELETE missing its `source_id` predicate,
    because every other test in this file uses one source."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    other = _difficulty().model_copy(update={"name": "Rank"})
    await store.replace_for_source(project_id, "ranks", [other], model="m", generated_at="t")

    names = {row.name for row in await store.classes_for(project_id)}

    assert names == {"Difficulty", "Rank"}


async def test_one_projects_classes_are_invisible_to_another(
    store, project_id, other_project_id
):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    assert await store.classes_for(other_project_id) == []


async def test_a_source_that_stated_no_classes_is_still_recorded_as_examined(
    store, project_id
):
    """`replace_for_source` with an empty list is how "grouped, found nothing"
    is distinguished from "never grouped". The `ungrouped` sweep is built
    entirely on that distinction, so losing it would make the sweep re-run
    every barren document forever, at model cost."""
    await store.replace_for_source(project_id, "songs", [], model="m", generated_at="t")

    assert await store.classes_for(project_id) == []
    assert await store.sources_with_classes(project_id) == {"songs"}


async def test_staling_a_source_leaves_its_classes_readable(store, project_id):
    """Stale text is still shown, labelled, rather than disappearing out from
    under a reader -- the same contract `EntityDefinitionStore.mark_stale`
    keeps, and for the same reason."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    await store.mark_stale_for_source(project_id, "songs")

    (row,) = await store.classes_for(project_id)
    assert row.stale is True
    assert row.name == "Difficulty"


async def test_staling_a_source_nobody_has_grouped_is_not_an_error(store, project_id):
    """Called from a projection reacting to every extraction in the log, and
    most documents have no classes. Raising here would put routine extraction
    in the DLQ."""
    await store.mark_stale_for_source(project_id, "never-grouped")
