from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    FailMediaProposal,
    MediaAssetIgnored,
    MediaAssetUnignored,
    MediaHostIgnored,
    MediaHostUnignored,
    MediaProposalAccepted,
    MediaProposalRejected,
    MediaProposalState,
    MediaProposalStored,
    MediaProposed,
    ProposeMedia,
    StoreMediaProposal,
    decide,
    evolve,
    initial_state,
)

PROJECT_ID = str(uuid4())


def _proposed(
    proposal_id: str = "p1", asset_url: str = "https://a.example/x.jpg"
) -> MediaProposed:
    return MediaProposed(
        aggregate_id=uuid4(),
        project_id=PROJECT_ID,
        proposal_id=proposal_id,
        need_id="n1",
        topic_id="t1",
        page_url="https://a.example/page",
        asset_url=asset_url,
        thumbnail_url=None,
        kind="image",
        title="a thing",
        reason="on topic",
        query="a query",
    )


def _with(*events: DomainEvent) -> MediaProposalState:
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_accepting_a_proposal_twice_is_refused():
    state = _with(_proposed(), MediaProposalAccepted(aggregate_id=uuid4(), proposal_id="p1"))
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(project_id=PROJECT_ID, proposal_id="p1"), state)


def test_accepting_a_rejected_proposal_is_refused():
    """A closed decision is closed. Distinct from
    `test_a_previously_rejected_asset_may_be_proposed_again` below, which is
    about the *asset*, not this record: this test would still pass if
    rejection blacklisted the asset, so it does not cover that behaviour."""
    state = _with(
        _proposed(),
        MediaProposalRejected(aggregate_id=uuid4(), proposal_id="p1", note=""),
    )
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(project_id=PROJECT_ID, proposal_id="p1"), state)


def test_a_command_naming_an_unknown_proposal_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(project_id=PROJECT_ID, proposal_id="nope"), initial_state())


def test_a_previously_rejected_asset_may_be_proposed_again():
    """Rejecting closes one proposal; it does not blacklist the asset.
    Ignoring is the explicit forever, and is a different command.

    This test fails if `decide` grows a guard against re-proposing a
    rejected asset -- which reads like a sensible addition and is the bug
    this spec exists to prevent. See "Rejecting is not blacklisting" in
    docs/superpowers/specs/2026-08-16-media-acquisition-design.md.
    """
    state = _with(
        _proposed(proposal_id="p1", asset_url="https://a.example/x.jpg"),
        MediaProposalRejected(aggregate_id=uuid4(), proposal_id="p1", note=""),
    )
    events = decide(
        ProposeMedia(
            project_id=PROJECT_ID,
            proposal_id="p2",
            need_id="n1",
            topic_id="t1",
            page_url="https://a.example/page",
            asset_url="https://a.example/x.jpg",
            thumbnail_url=None,
            kind="image",
            title="a thing",
            reason="on topic",
            query="a query",
        ),
        state,
    )
    assert isinstance(events[0], MediaProposed)


def test_an_ignored_asset_is_refused_a_new_proposal():
    state = _with(
        MediaAssetIgnored(
            aggregate_id=uuid4(), project_id=PROJECT_ID, asset_key="https://a.example/x.jpg"
        )
    )
    with pytest.raises(CommandRejectedError):
        decide(
            ProposeMedia(
                project_id=PROJECT_ID,
                proposal_id="p1",
                need_id="n1",
                topic_id="t1",
                page_url="https://a.example/page",
                asset_url="https://a.example/x.jpg",
                thumbnail_url=None,
                kind="image",
                title="a thing",
                reason="on topic",
                query="a query",
            ),
            state,
        )


def test_unignoring_lets_it_be_proposed_again():
    state = _with(
        MediaAssetIgnored(
            aggregate_id=uuid4(), project_id=PROJECT_ID, asset_key="https://a.example/x.jpg"
        ),
        MediaAssetUnignored(
            aggregate_id=uuid4(), project_id=PROJECT_ID, asset_key="https://a.example/x.jpg"
        ),
    )
    events = decide(
        ProposeMedia(
            project_id=PROJECT_ID,
            proposal_id="p1",
            need_id="n1",
            topic_id="t1",
            page_url="https://a.example/page",
            asset_url="https://a.example/x.jpg",
            thumbnail_url=None,
            kind="image",
            title="a thing",
            reason="on topic",
            query="a query",
        ),
        state,
    )
    assert events


def test_an_ignored_host_does_not_cover_a_sibling_subdomain():
    """No suffix matching, for `FetchGrant`'s stated reason: public-suffix
    knowledge this project does not have. A blacklist that quietly covers
    more than it says is invisible from every direction, so this is pinned.
    """
    state = _with(
        MediaHostIgnored(aggregate_id=uuid4(), project_id=PROJECT_ID, host="example.com")
    )
    events = decide(
        ProposeMedia(
            project_id=PROJECT_ID,
            proposal_id="p1",
            need_id="n1",
            topic_id="t1",
            page_url="https://cdn.example.com/page",
            asset_url="https://cdn.example.com/x.jpg",
            thumbnail_url=None,
            kind="image",
            title="a thing",
            reason="on topic",
            query="a query",
        ),
        state,
    )
    assert events


def test_an_ignored_host_is_refused_a_new_proposal():
    """The positive case for the host guard, since the sibling-subdomain test
    above only pins what it does *not* cover."""
    state = _with(
        MediaHostIgnored(aggregate_id=uuid4(), project_id=PROJECT_ID, host="example.com")
    )
    with pytest.raises(CommandRejectedError):
        decide(
            ProposeMedia(
                project_id=PROJECT_ID,
                proposal_id="p1",
                need_id="n1",
                topic_id="t1",
                page_url="https://example.com/page",
                asset_url="https://example.com/x.jpg",
                thumbnail_url=None,
                kind="image",
                title="a thing",
                reason="on topic",
                query="a query",
            ),
            state,
        )


def test_unignoring_a_host_lets_it_be_proposed_again():
    state = _with(
        MediaHostIgnored(aggregate_id=uuid4(), project_id=PROJECT_ID, host="example.com"),
        MediaHostUnignored(aggregate_id=uuid4(), project_id=PROJECT_ID, host="example.com"),
    )
    events = decide(
        ProposeMedia(
            project_id=PROJECT_ID,
            proposal_id="p1",
            need_id="n1",
            topic_id="t1",
            page_url="https://example.com/page",
            asset_url="https://example.com/x.jpg",
            thumbnail_url=None,
            kind="image",
            title="a thing",
            reason="on topic",
            query="a query",
        ),
        state,
    )
    assert events


def test_storing_a_proposal_that_was_never_accepted_is_refused():
    """Task 11's worker downloads the asset and stores it through the corpus
    only after `AcceptMediaProposal` succeeds -- this guard is the whole gate
    that keeps a download from happening on nobody's approval. A stored
    proposal that skipped acceptance means bytes were fetched and kept
    without anyone having said yes.
    """
    state = _with(_proposed())
    with pytest.raises(CommandRejectedError):
        decide(
            StoreMediaProposal(project_id=PROJECT_ID, proposal_id="p1", source_id="s1"),
            state,
        )


def test_failing_a_proposal_that_was_never_accepted_is_refused():
    """Same gate as the store guard, for the same reason: a proposal that was
    never accepted has nothing running against it that could fail.
    """
    state = _with(_proposed())
    with pytest.raises(CommandRejectedError):
        decide(
            FailMediaProposal(project_id=PROJECT_ID, proposal_id="p1", error="boom"),
            state,
        )


def test_storing_an_already_stored_proposal_is_refused_not_idempotent():
    """Deliberately not idempotent: `decide` requires status "accepted", and
    a stored proposal's status is "stored", so a second `StoreMediaProposal`
    for the same id is refused rather than silently accepted again.

    This matters for Task 11's worker, which may retry after a crash. A
    retry that reaches this command a second time (for example, because the
    worker crashed after storing but before recording success elsewhere)
    gets a refusal, not a duplicate `MediaProposalStored` event -- the worker
    has to treat "already stored" as success on retry rather than resubmit
    the command and expect it to be silently accepted. Idempotence was
    considered and rejected here because a silently-accepted second store
    could carry a different `source_id` than the first, which would mean two
    different corpus records both claiming to be what this one proposal
    became -- a fact `decide` has no way to arbitrate between, so refusing is
    the only answer that does not require guessing which one is right.
    """
    state = _with(
        _proposed(),
        MediaProposalAccepted(aggregate_id=uuid4(), proposal_id="p1"),
        MediaProposalStored(aggregate_id=uuid4(), proposal_id="p1", source_id="s1"),
    )
    with pytest.raises(CommandRejectedError):
        decide(
            StoreMediaProposal(project_id=PROJECT_ID, proposal_id="p1", source_id="s1"),
            state,
        )
