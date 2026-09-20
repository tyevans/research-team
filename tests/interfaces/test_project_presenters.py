"""The project and session web view models, as pure functions over domain objects."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.application import SessionSummary
from research_team.application.project_summaries import ProjectSummary
from research_team.domain import SessionPurpose
from research_team.domain.project import ProjectState
from research_team.interfaces.web.presenters import (
    project_detail_view,
    project_view,
    reading_head,
    summary_view,
    topic_documents_view,
)

AGGREGATE = uuid4()


def test_the_project_detail_carries_identity_holder_and_reading_head():
    """What `GET /api/projects/{id}` owes its consumers, and no more.

    The holder decides what the page can *do*; the reading head decides what
    it can *show*. They are different questions and the detail answers both --
    the project page's Workspace tab reads files through the reading head,
    which has an answer whether or not anybody is holding, while the delete
    and take-over verbs still need to know who holds it.

    Asserted as a whole dict rather than key by key, because the point of this
    presenter is what it does *not* carry.
    """
    session_id = uuid4()
    tip = uuid4()

    view = project_detail_view(
        AGGREGATE,
        "atlas",
        active_session_id=session_id,
        tip_at_event=7,
        reading_head_session_id=tip,
    )

    assert view == {
        "id": str(AGGREGATE),
        "name": "atlas",
        "active_session_id": str(session_id),
        "tip_at_event": 7,
        "reading_head_session_id": str(tip),
    }


def test_the_listing_and_the_detail_differ_by_exactly_one_column_each():
    """The two routes' asymmetry, pinned in both directions.

    `project_view` was an *alias* of `project_detail_view` for two slices, and
    the alias's docstring named the condition for undoing it: "the day a
    listing earns a column a detail does not". **That day arrived**, and this
    test is the half that had to change: it used to assert the row was a strict
    subset of the detail, which was true only while the asymmetry ran one way.

    It now runs both ways, and each direction has its own reason:

    - `reading_head_session_id` is the detail's, because it is what a project
      *page* reads files through and `GET /api/projects` folds one aggregate
      per row already.
    - `summary` is the listing's, because a project page has the project in
      front of it and needs no summary of itself, where an index has six rows
      and nothing else to tell them apart.

    The property the alias was protecting is unchanged and is the last
    assertion: a field added for *both* must not reach one route and miss the
    other. Everything outside the two named keys still has to agree, value for
    value.
    """
    session_id = uuid4()
    kwargs = {"active_session_id": session_id, "tip_at_event": 7}

    detail = project_detail_view(AGGREGATE, "atlas", **kwargs)
    row = project_view(AGGREGATE, "atlas", **kwargs)

    assert set(detail) - set(row) == {"reading_head_session_id"}
    assert set(row) - set(detail) == {"summary"}

    shared = set(row) & set(detail)
    assert {key: row[key] for key in shared} == {key: detail[key] for key in shared}


def test_a_listing_row_carries_a_summary_even_with_nothing_to_summarise():
    """The zeros are always present, never an absent object.

    `ProjectSummaries.all` answers only the projects that have something to
    summarise, so a project created a minute ago is simply missing from it and
    `project_view` is handed `None`. An optional object on the wire would make
    every consumer write the same `?? 0` fallback, and this console has shipped
    a silently-absent field read as a zero before.
    """
    row = project_view(AGGREGATE, "atlas")

    assert row["summary"] == {
        "topics": 0,
        "topics_open": 0,
        "sources": 0,
        "extracted": 0,
        "courses": 0,
        "sessions": 0,
        "last_activity": None,
    }


def test_a_listing_row_carries_the_summary_it_was_given():
    """And the counts reach the wire under the names the console reads.

    Paired with the test above rather than folded into it: that one is about
    the *shape* being unconditional, this one is about the mapping being right.
    A single test over a filled summary would pass with `project_summary_view`
    returning its zeros regardless of the argument.
    """
    summary = ProjectSummary(
        topics=14,
        topics_open=3,
        sources=11,
        extracted=9,
        courses=2,
        sessions=6,
        last_activity="2026-08-29T07:30:28.688146+00:00",
    )

    row = project_view(AGGREGATE, "atlas", summary=summary)

    assert row["summary"] == {
        "topics": 14,
        "topics_open": 3,
        "sources": 11,
        "extracted": 9,
        "courses": 2,
        "sessions": 6,
        "last_activity": "2026-08-29T07:30:28.688146+00:00",
    }


@pytest.mark.parametrize(
    ("state", "expected", "why"),
    [
        (
            lambda holder, tip: ProjectState(
                active_session_id=holder, tip_session_id=tip, tip_at_event=3
            ),
            lambda holder, tip: holder,
            "a holder has work the tip does not know about yet",
        ),
        (
            lambda holder, tip: ProjectState(
                active_session_id=None, tip_session_id=tip, tip_at_event=3
            ),
            lambda holder, tip: tip,
            "with nobody holding it, the tip session is the truth",
        ),
        (
            lambda holder, tip: ProjectState(
                active_session_id=None, tip_session_id=tip, tip_at_event=0
            ),
            lambda holder, tip: None,
            "a tip at zero is a project nothing has been written in",
        ),
        (
            lambda holder, tip: ProjectState(
                active_session_id=None, tip_session_id=None, tip_at_event=0
            ),
            lambda holder, tip: None,
            "a project that has never been joined has no stream to read",
        ),
    ],
)
def test_the_reading_head_resolves_a_session_whether_or_not_anybody_holds(
    state, expected, why
):
    """The four branches, parametrised over the fact that distinguishes them.

    The middle two are the whole reason this function exists: they are the
    states in which `active_session_id` is `null` and the project still has
    files, and a console that only knew the holder showed a reader nothing in
    both. A test over one held project would pass against a function that
    returned `state.active_session_id` unchanged.
    """
    holder, tip = uuid4(), uuid4()
    assert reading_head(state(holder, tip)) == expected(holder, tip), why


def test_the_reading_head_never_reports_a_scrub_offset():
    """HEAD in every branch, and the signature is what enforces it.

    `topic_documents_view` used to hand back `(session_id, tip_at_event)`, and
    that pair made one response contradict itself: it listed a file written
    after a release -- `project_files` folds to HEAD -- and then 404'd it
    through the very reader route the offset was sent to feed (measured
    2026-08-27). The offset is a fork point, not a statement about what a
    project has.

    Asserted on the *return type* rather than on a value, because a value test
    would pass against a function that returned an offset nobody looked at.
    A `UUID | None` cannot carry one.
    """
    head = reading_head(
        ProjectState(active_session_id=None, tip_session_id=AGGREGATE, tip_at_event=7)
    )

    assert head == AGGREGATE
    assert not isinstance(head, tuple)


def test_a_session_summary_carries_its_project_so_rows_can_be_grouped():
    """The landing page groups sessions under projects; the key has to be here.

    Without it `/sessions` and `/tree` answer a flat pile of ids that cannot be
    related to the project list beside them -- which is the defect this field
    exists to fix, not a convenience.
    """
    project_id = uuid4()
    summary = SessionSummary(
        session_id=AGGREGATE,
        started_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        turns=2,
        files=1,
        first_message="hello",
        project_id=project_id,
        purpose=SessionPurpose.CHAT,
    )

    assert summary_view(summary)["project_id"] == str(project_id)


def test_a_summary_cannot_be_built_without_a_project():
    """The state the old test rendered is now one this type refuses to hold.

    This replaces `test_a_session_belonging_to_no_project_reports_null_rather_
    than_omitting_it`, which asserted that a loose session reported `null`
    rather than omitting the key. That was right while a session could exist
    outside a project. It cannot now, so the interesting claim moved one layer
    down: the summary cannot be constructed at all, and `summary_view` never
    gets the chance to decide what to render.

    Asserted through the constructor rather than through `summary_view`
    because that is where the refusal now lives -- a test that called the
    presenter would be testing the dataclass through a function that never
    sees the failure.
    """
    with pytest.raises(TypeError):
        SessionSummary(
            session_id=AGGREGATE,
            started_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            turns=0,
            files=0,
            first_message="",
        )


def test_a_released_projects_documents_are_reported_at_head_not_the_tip_offset():
    """The file list and the scrub point sent beside it must name one moment.

    `documents` is built from `SessionService.project_files`, which folds the
    tip session to HEAD on purpose -- a session goes on accepting turns after
    a release, and work written afterwards is the project's
    (`_catch_up_tip`, and
    `test_a_release_does_not_freeze_the_project_at_the_moment_it_happened`).
    This view used to send `state.tip_at_event` alongside that HEAD list, so
    one response listed a file and then handed the reader routes a point at
    which it does not exist.

    Fails with the change reverted, on `at`: it reported `7` -- the offset the
    synthetic reproduction recorded on 2026-08-27, where `/topics/00-a/after.md`
    was listed by HEAD and absent at 7 -- and then reported `None` for a slice.
    The key is gone from the response entirely now, on both sides of the wire,
    so the assertion is its absence rather than its value.
    """
    tip = uuid4()
    state = ProjectState(
        project_id=uuid4(),
        status="created",
        name="research",
        active_session_id=None,
        tip_session_id=tip,
        tip_at_event=7,
    )
    files = {"/topics/00-a/before.md": {}, "/topics/00-a/after.md": {}}

    view = topic_documents_view("/topics/00-a", files, state)

    assert view["session_id"] == str(tip)
    assert "at" not in view
    assert [document["name"] for document in view["documents"]] == [
        "after.md",
        "before.md",
    ]


def test_a_held_project_still_reports_head():
    """Unchanged by the fix, and here so the two branches are pinned together:
    a live holder was always HEAD, and now the released branch agrees with it.

    Passes with the change reverted -- it is the control, not the finding.
    """
    holder = uuid4()
    state = ProjectState(
        project_id=uuid4(),
        status="created",
        name="research",
        active_session_id=holder,
        tip_session_id=uuid4(),
        tip_at_event=3,
    )

    view = topic_documents_view("/topics/00-a", {"/topics/00-a/x.md": {}}, state)

    assert view["session_id"] == str(holder)
    assert "at" not in view


def test_a_project_nobody_has_joined_names_no_session():
    """No stream to read from, reported as no session rather than an error.

    Passes with the change reverted; it guards the branch the fix reshaped.
    """
    state = ProjectState(project_id=uuid4(), status="created", name="research")

    view = topic_documents_view("/topics/00-a", {}, state)

    assert view["session_id"] is None
    assert "at" not in view
    assert view["documents"] == []
