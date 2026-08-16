"""The media-proposal table: what it stores, and the trap it exists to avoid.

An event no projection handles counts as APPLIED, not rejected --
`eventsource.replay`'s own docstring says so, and `strict=True` has no
opinion about an event nothing subscribed to. So a build with
`MediaProposalProjection` never constructed replays perfectly cleanly and
serves an empty pane: nothing raises, nothing logs, the request answers 200.
That is precisely how `EntityDefinitionRunner` shipped missing from
`composition.py` behind a full green suite.

Every assertion below is on a *row* -- that it exists, and what it carries --
never on "the request succeeded" or "the projection did not throw". Either of
those passes with the projection deleted entirely and would be worthless as a
test of it.
"""

from uuid import uuid4

import pytest
from eventsource import ExpectedVersion, StreamId

from research_team.domain.media_proposals import (
    MediaAssetIgnored,
    MediaAssetUnignored,
    MediaHostIgnored,
    MediaHostUnignored,
    MediaNeedsIdentified,
    MediaProposalAccepted,
    MediaProposalFailed,
    MediaProposalRejected,
    MediaProposalStored,
    MediaProposed,
)
from research_team.infrastructure.persistence.read_models import (
    MediaProposalRunner,
    MediaProposalStore,
)


def _needs_identified(project_id, topic_id="t1") -> MediaNeedsIdentified:
    return MediaNeedsIdentified(
        aggregate_id=project_id,
        project_id=str(project_id),
        topic_id=topic_id,
        needs=(
            '[{"need_id": "n1", "medium": "image", '
            '"description": "Shows the gradient", "why": "visual aid"}]'
        ),
        model_version="test-model",
    )


def _proposed(project_id, *, proposal_id="p1", need_id="n1", topic_id="t1") -> MediaProposed:
    return MediaProposed(
        aggregate_id=project_id,
        project_id=str(project_id),
        proposal_id=proposal_id,
        need_id=need_id,
        topic_id=topic_id,
        page_url="https://example.com/page",
        asset_url="https://example.com/asset.png",
        thumbnail_url="https://example.com/thumb.png",
        kind="image",
        title="An asset",
        reason="Shows the gradient",
        query="gradient diagram",
    )


@pytest.fixture
async def proposals(db_path):
    """The table alone, with no projection following the log."""
    opened = await MediaProposalStore.open(db_path)
    yield opened
    await opened.close()


async def test_a_proposal_lands_as_a_row_carrying_the_reason_the_chain_wrote(
    proposals, project_id
):
    """The trap's own reproduction, run against the projection method directly
    rather than through a store's log. Would pass with the projection
    deleted only if it also asserted nothing -- it asserts the row's `reason`,
    which no other code path can supply.
    """
    await proposals.projection.handle(_proposed(project_id))

    rows = await proposals.for_project(project_id)

    assert [row.reason for row in rows] == ["Shows the gradient"]


async def test_the_row_denormalizes_the_need_description_from_the_needs_event(
    proposals, project_id
):
    """`MediaProposalRow` carries `need_description`, not just `need_id`, so
    the pane can label a group of proposals without joining a JSON column.
    Only `MediaNeedsIdentified` carries the description; `MediaProposed`
    carries only the id. A projection that skipped the denormalization would
    leave this field empty, and no assertion on `need_id` alone would catch
    it.
    """
    await proposals.projection.handle(_needs_identified(project_id))
    await proposals.projection.handle(_proposed(project_id))

    (row,) = await proposals.for_project(project_id)

    assert row.need_id == "n1"
    assert row.need_description == "Shows the gradient"


async def test_a_proposal_with_no_matching_need_has_no_description(proposals, project_id):
    """The needs event may not have arrived yet, or may name a different need
    -- the denormalization must not raise or invent a value it does not have.
    """
    await proposals.projection.handle(_proposed(project_id, need_id="unknown"))

    (row,) = await proposals.for_project(project_id)

    assert row.need_description == ""


async def test_accepting_a_proposal_moves_its_status(proposals, project_id):
    await proposals.projection.handle(_proposed(project_id))

    await proposals.projection.handle(
        MediaProposalAccepted(aggregate_id=project_id, proposal_id="p1")
    )

    (row,) = await proposals.for_project(project_id)
    assert row.status == "accepted"


async def test_rejecting_a_proposal_keeps_its_note(proposals, project_id):
    await proposals.projection.handle(_proposed(project_id))

    await proposals.projection.handle(
        MediaProposalRejected(aggregate_id=project_id, proposal_id="p1", note="too blurry")
    )

    (row,) = await proposals.for_project(project_id)
    assert row.status == "rejected"
    assert row.note == "too blurry"


async def test_storing_a_proposal_carries_the_source_id_it_landed_under(proposals, project_id):
    await proposals.projection.handle(_proposed(project_id))

    await proposals.projection.handle(
        MediaProposalStored(aggregate_id=project_id, proposal_id="p1", source_id="s1")
    )

    (row,) = await proposals.for_project(project_id)
    assert row.status == "stored"
    assert row.source_id == "s1"


async def test_a_failed_proposal_carries_the_error_and_stays_visible(proposals, project_id):
    """The design doc's own point: a failure is not a disappearance. The
    proposal stays in the table so the pane can show why it did not become a
    source.
    """
    await proposals.projection.handle(_proposed(project_id))

    await proposals.projection.handle(
        MediaProposalFailed(aggregate_id=project_id, proposal_id="p1", error="404")
    )

    (row,) = await proposals.for_project(project_id)
    assert row.status == "failed"
    assert row.error == "404"


async def test_ignoring_and_unignoring_an_asset_round_trips(proposals, project_id):
    await proposals.projection.handle(
        MediaAssetIgnored(aggregate_id=project_id, project_id=str(project_id), asset_key="a1")
    )
    assert await proposals.ignored_assets(project_id) == {"a1"}

    await proposals.projection.handle(
        MediaAssetUnignored(
            aggregate_id=project_id, project_id=str(project_id), asset_key="a1"
        )
    )
    assert await proposals.ignored_assets(project_id) == set()


async def test_ignoring_and_unignoring_a_host_round_trips(proposals, project_id):
    await proposals.projection.handle(
        MediaHostIgnored(
            aggregate_id=project_id, project_id=str(project_id), host="example.com"
        )
    )
    assert await proposals.ignored_hosts(project_id) == {"example.com"}

    await proposals.projection.handle(
        MediaHostUnignored(
            aggregate_id=project_id, project_id=str(project_id), host="example.com"
        )
    )
    assert await proposals.ignored_hosts(project_id) == set()


async def test_one_projects_proposals_are_invisible_to_another(proposals, project_id):
    other = uuid4()
    await proposals.projection.handle(_proposed(project_id))
    await proposals.projection.handle(_proposed(other, proposal_id="p2"))

    assert len(await proposals.for_project(project_id)) == 1
    assert len(await proposals.for_project(other)) == 1


# --- the runner ---------------------------------------------------------
#
# Mirrors the ontology runner tests: every assertion is on a row the log
# actually produced, through the real subscription, never on "the projection
# started" or "caught_up returned".


async def _append(store, publisher, project_id, event):
    await store.append(StreamId(project_id, "MediaProposals"), [event], ExpectedVersion.any_())
    if publisher is not None:
        await publisher.publish([event])


@pytest.fixture
async def runner(db_path, store, publisher):
    started = MediaProposalRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


async def test_the_runner_projects_a_proposal_appended_to_the_log(
    runner, store, publisher, project_id
):
    await _append(store, publisher, project_id, _needs_identified(project_id))
    await _append(store, publisher, project_id, _proposed(project_id))
    await runner.caught_up()

    (row,) = await runner.for_project(project_id)

    assert row.reason == "Shows the gradient"
    assert row.need_description == "Shows the gradient"


async def test_a_rebuild_reproduces_the_table_from_the_log(
    runner, store, publisher, project_id
):
    await _append(store, publisher, project_id, _proposed(project_id))
    await runner.caught_up()

    await runner.rebuild()

    (row,) = await runner.for_project(project_id)
    assert row.proposal_id == "p1"
