"""The web view models, as pure functions over domain objects."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.application import SessionSummary
from research_team.application.corpus_read import SourceListing
from research_team.application.course_catalog import CachedOutline, Catalog
from research_team.application.course_realization import CourseDetail, RealizedCourse
from research_team.domain import (
    AssistantMessageAdded,
    AutonomyChanged,
    FileDeleted,
    FileEdited,
    FileWritten,
    MediaRecord,
    SessionForkedFrom,
    SessionPurpose,
    SessionStarted,
    TextRecord,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.domain.course import CourseFit
from research_team.domain.course_catalog import ArtRef, CatalogSections, CourseCandidate
from research_team.domain.learning_area import AreaMember
from research_team.domain.project import ProjectState
from research_team.interfaces.web.presenters import (
    SUMMARY_LIMIT,
    catalog_view,
    course_detail_view,
    course_fit_view,
    event_row,
    event_rows,
    event_summary,
    file_history,
    message_view,
    project_detail_view,
    project_view,
    reading_head,
    source_view,
    summary_view,
    topic_documents_view,
)

AGGREGATE = uuid4()


def _member(entity_id: str, name: str) -> AreaMember:
    return AreaMember(entity_id=entity_id, name=name, entity_type="person", centrality=1.0)


def _candidate(
    slug: str = "warp-drive", membership_hash: str = "candidate-hash"
) -> CourseCandidate:
    return CourseCandidate(
        slug=slug,
        title="Warp Drive",
        category="unclassified",
        prominence=1.0,
        size=1,
        membership_hash=membership_hash,
        anchors=(_member("e1", "Warp Core"),),
        art=ArtRef(url="x", alt="x"),
    )


def _catalog(*, unplaceable: tuple[str, ...] = ()) -> Catalog:
    return Catalog(
        sections=CatalogSections(hero=(), highlights=(), filed=()),
        categories={},
        unplaceable_featured=unplaceable,
        derived_from=(0, 0),
    )


def make(event_class, **fields):
    return event_class(
        aggregate_id=AGGREGATE,
        aggregate_version=1,
        occurred_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        **fields,
    )


def text_message(kind: str, content: str) -> dict:
    return {"type": kind, "data": {"content": content}}


# ---------------- summaries ----------------


def test_a_started_session_is_summarised_by_its_model():
    event = make(
        SessionStarted,
        system_prompt="p",
        model_name="qwen3.6-27b",
        project_id=uuid4(),
        purpose=SessionPurpose.CHAT,
    )
    assert event_summary(event) == "qwen3.6-27b"


def test_a_written_file_is_summarised_by_its_path():
    event = make(FileWritten, path="/a.py", file_data={"content": "x"})
    assert event_summary(event) == "/a.py"


def test_an_edited_file_summary_carries_the_intent_not_just_the_path():
    """The log records why the file changed; a timeline row should show it."""
    event = make(
        FileEdited,
        path="/a.py",
        file_data={"content": "new"},
        old_string="print(i)",
        new_string="print(i * 2)",
        replace_all=False,
    )
    summary = event_summary(event)
    assert summary.startswith("/a.py")
    assert "print(i)" in summary
    assert "print(i * 2)" in summary


def test_an_edit_summary_stays_short_enough_for_one_row():
    event = make(
        FileEdited,
        path="/a.py",
        file_data={"content": "x"},
        old_string="a" * 200,
        new_string="b" * 200,
        replace_all=False,
    )
    assert len(event_summary(event)) < 100


def test_a_deleted_file_is_summarised_by_its_path():
    assert event_summary(make(FileDeleted, path="/gone.py")) == "/gone.py"


def test_a_failed_turn_reports_the_error():
    event = make(
        TurnFailed,
        turn_index=2,
        error_type="RuntimeError",
        error_message="model exploded",
    )
    summary = event_summary(event)
    assert "RuntimeError" in summary
    assert "model exploded" in summary


def test_a_completed_turn_reports_its_number():
    assert event_summary(make(TurnCompleted, turn_index=3)) == "turn 3"


def test_a_fork_reports_where_it_came_from():
    source = uuid4()
    event = make(SessionForkedFrom, source_session_id=source, at_event=7)
    summary = event_summary(event)
    assert str(source)[:8] in summary
    assert "7" in summary


def test_a_message_is_summarised_by_its_text():
    event = make(UserMessageSent, message=text_message("human", "hello   there\n"))
    assert event_summary(event) == "hello there"


def test_a_tool_calling_message_is_summarised_by_the_calls():
    event = make(
        AssistantMessageAdded,
        message={
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [{"name": "write_file"}, {"name": "edit_file"}],
            },
        },
    )
    assert event_summary(event) == "→ write_file, edit_file"


def test_a_tool_call_summary_says_what_the_call_acted_on():
    """A row naming only the tool says a file was written, not which file.

    Passes with the argument preview reverted only if the assertion is cut back
    to the names, which is the whole point of the row.
    """
    event = make(
        AssistantMessageAdded,
        message={
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [
                    {"name": "write_file", "args": {"file_path": "/a.py", "content": "x"}},
                    {"name": "search", "args": {"query": "kettles"}},
                ],
            },
        },
    )
    assert event_summary(event) == "→ write_file(file_path=/a.py  +1), search(query=kettles)"


def test_an_enormous_argument_cannot_widen_a_timeline_row():
    """`remember` takes 20,000 characters of `text`; a row is one line.

    The cap is on the whole summary rather than on each value, because a
    message can carry many calls and ten short ones overflow a row as surely as
    one long one. Fails on a preview that truncates per value only.
    """
    event = make(
        AssistantMessageAdded,
        message={
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [{"name": "remember", "args": {"text": "x" * 20_000}}] * 12,
            },
        },
    )
    summary = event_summary(event)
    assert len(summary) <= SUMMARY_LIMIT
    assert summary.endswith("…")


def test_a_call_with_no_arguments_is_still_named():
    event = make(
        AssistantMessageAdded,
        message={
            "type": "ai",
            "data": {"content": "", "tool_calls": [{"name": "ls", "args": {}}]},
        },
    )
    assert event_summary(event) == "→ ls"


# ---------------- rows ----------------


def test_rows_are_numbered_from_one():
    events = [
        make(
            SessionStarted,
            system_prompt="p",
            model_name="m",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        ),
        make(UserMessageSent, message=text_message("human", "hi")),
    ]
    assert [row["index"] for row in event_rows(events)] == [1, 2]


def test_a_row_exposes_the_path_for_file_events():
    row = event_row(4, make(FileWritten, path="/a.py", file_data={"content": "x"}))
    assert row["path"] == "/a.py"
    assert row["type"] == "FileWritten"
    assert row["occurred_at"].startswith("2026-08-02T12:00")


def test_a_row_flags_an_errored_tool_result():
    event = make(
        ToolResultRecorded,
        message={"type": "tool", "data": {"content": "boom"}},
        is_error=True,
    )
    assert event_row(1, event)["is_error"] is True


# ---------------- messages ----------------


def test_message_roles_are_translated_for_the_browser():
    assert message_view(text_message("human", "x"))["role"] == "user"
    assert message_view(text_message("ai", "x"))["role"] == "assistant"
    assert message_view(text_message("tool", "x"))["role"] == "tool"


def test_a_message_view_carries_its_tool_calls():
    view = message_view(
        {
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [{"name": "write_file", "args": {"file_path": "/a.py"}}],
            },
        }
    )
    assert view["tool_calls"] == [{"name": "write_file", "args": {"file_path": "/a.py"}}]


def test_an_errored_tool_message_is_marked():
    view = message_view({"type": "tool", "data": {"content": "boom", "status": "error"}})
    assert view["is_error"] is True


# ---------------- file history ----------------


def test_file_history_only_covers_the_asked_for_path():
    events = [
        make(FileWritten, path="/a.py", file_data={"content": "a"}),
        make(FileWritten, path="/b.py", file_data={"content": "b"}),
    ]
    rows = file_history(events, "/a.py")
    assert [row["index"] for row in rows] == [1]
    assert rows[0]["content"] == "a"


def test_file_history_exposes_the_edit_strings_for_diffing():
    events = [
        make(FileWritten, path="/a.py", file_data={"content": "old"}),
        make(
            FileEdited,
            path="/a.py",
            file_data={"content": "new"},
            old_string="old",
            new_string="new",
            replace_all=True,
        ),
    ]
    rows = file_history(events, "/a.py")
    assert rows[0]["old_string"] is None
    assert rows[1]["old_string"] == "old"
    assert rows[1]["new_string"] == "new"
    assert rows[1]["replace_all"] is True


def test_file_history_of_an_untouched_path_is_empty():
    assert file_history([], "/nothing.py") == []


# ---------------- the live feed payload ----------------


def test_a_feed_event_carries_everything_a_timeline_row_does():
    """A live-appended event must render identically to a fetched one, so the
    browser never needs a follow-up request just to colour it."""
    from research_team.interfaces.web.presenters import feed_event

    session = uuid4()
    event = make(FileWritten, path="/a.py", file_data={"content": "x"})

    payload = feed_event(session, event, 4)
    row = event_row(4, event)

    assert payload["session_id"] == str(session)
    for key, value in row.items():
        assert payload[key] == value


def test_a_feed_event_marks_an_errored_tool_result():
    from research_team.interfaces.web.presenters import feed_event

    event = make(
        ToolResultRecorded,
        message={"type": "tool", "data": {"content": "boom"}},
        is_error=True,
    )
    assert feed_event(uuid4(), event, 2)["is_error"] is True


def test_a_feed_event_always_has_a_summary_string():
    """The browser dedupes path against summary, so summary is never null."""
    from research_team.interfaces.web.presenters import feed_event

    for event in (
        make(FileWritten, path="/a.py", file_data={"content": "x"}),
        make(
            SessionStarted,
            system_prompt="p",
            model_name="m",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        ),
        make(TurnCompleted, turn_index=1),
    ):
        payload = feed_event(uuid4(), event, 1)
        assert isinstance(payload["summary"], str)


# ---------------- project events ----------------


# Two cases stood here: `ProjectWorkflowSelected` summarised by its preset, and
# `ProjectStageAdvanced` summarised by both ends of the move. Both events are
# gone with the workflow system, and so are their branches in `event_summary`.
# No surviving project event carries a summary of its own -- they fall through
# to the "" fallback, which is correct for a fact whose whole content is its
# name.


def test_a_changed_autonomy_is_summarised_by_the_tool_and_its_new_level():
    """The tool alone or the level alone doesn't say what changed; both do."""
    event = make(AutonomyChanged, tool_name="fetch", level="auto")
    summary = event_summary(event)
    assert "fetch" in summary
    assert "auto" in summary


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


def test_the_listing_row_is_the_detail_without_the_reading_head():
    """The one column the detail has and the listing does not, pinned.

    `project_view` was an *alias* of `project_detail_view` for two slices, and
    the alias's docstring named the condition for undoing it: "the day a
    listing earns a column a detail does not". It happened in the other
    direction -- the detail earned one -- and the reason it is not on the
    listing is `GET /api/projects`, which folds one aggregate per row.

    The alias was protecting a real property: a field added for both must not
    reach one route and miss the other. `project_view` therefore delegates and
    deletes one key, and this test is that key and nothing else. It would fail
    if either function grew a field the other did not.
    """
    session_id = uuid4()
    kwargs = {"active_session_id": session_id, "tip_at_event": 7}

    detail = project_detail_view(AGGREGATE, "atlas", **kwargs)
    row = project_view(AGGREGATE, "atlas", **kwargs)

    assert set(detail) - set(row) == {"reading_head_session_id"}
    assert row == {key: value for key, value in detail.items() if key in row}


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


def test_a_media_source_view_reports_its_mimetype_and_size_and_no_char_count():
    """A pure function over a `SourceListing`, tested as one -- no route and no
    fixture, the same way `format_listing` is tested in
    `test_corpus_tools.py`.

    Fails if the `kind == "media"` branch in `_record_view` is deleted: every
    record would then be rendered through `char_count`, which a `MediaRecord`
    does not have. It is worth an assertion rather than a deferral to the
    task that routes media, because the branch is the API contract -- a client
    reading `char_count` off a video would be reading a field the server
    cannot honestly supply, and `0` there would read as an empty document
    rather than as the absence it is.

    The `kind` assertion is the other half: it is what lets a client
    discriminate at all, and without it the two shapes would be told apart
    only by which keys happen to be present.
    """
    view = source_view(
        SourceListing(
            record=MediaRecord(
                source_id="v1",
                sha256="0" * 64,
                media_type="video/mp4",
                byte_count=2048,
                title="A talk",
            ),
            extracted=False,
        )
    )

    assert view["kind"] == "media"
    assert view["media_type"] == "video/mp4"
    assert view["byte_count"] == 2048
    assert "char_count" not in view
    assert view["sha256"] == "0" * 64
    assert view["title"] == "A talk"
    # Nothing extracts media yet, so the honest answer is False rather than a
    # missing key -- the Documents page decides whether to offer extraction
    # from this, and an absent field would read as "unknown".
    assert view["extracted"] is False


def test_a_text_source_view_still_reports_a_character_count_and_no_mimetype():
    """The other side of the same branch, and the reason it is a branch.

    Fails if the discrimination is dropped in favour of emitting every field
    for every kind, which would put `media_type: null` on a document -- a
    client could not then tell a text source from a media one whose mimetype
    went missing.
    """
    view = source_view(
        SourceListing(
            record=TextRecord(source_id="s1", sha256="1" * 64, char_count=5),
            extracted=True,
        )
    )

    assert view["kind"] == "text"
    assert view["char_count"] == 5
    assert "media_type" not in view
    assert "byte_count" not in view
    assert view["extracted"] is True


def test_a_dropped_entity_is_reported_as_its_id_when_the_cluster_no_longer_names_it():
    """Not a placeholder and not a lookup elsewhere. The name is genuinely gone
    and inventing one would claim knowledge the current cluster does not have."""
    fit = CourseFit(kept=("e1",), added=(), dropped=("e2",), orphaned=False)
    members = (_member("e1", "Warp Core"),)  # e2 is gone from the cluster

    view = course_fit_view(fit, members)

    assert view["dropped"] == ["e2"]
    # The kept side resolves against the members it was handed, so this is
    # not merely "dropped is unresolved" -- kept is resolved and dropped is
    # not, on the same call.
    assert view["kept"] == [{"entity_id": "e1", "name": "Warp Core"}]


def test_the_outline_carries_a_membership_hash_that_can_differ_from_the_candidates():
    """Increment 1's regression, one field over. A view that omits it makes
    every outline report stale forever; a view that copies the candidate's
    makes every outline report fresh forever. The stub returns a different
    hash so a copy fails.
    """
    detail = CourseDetail(
        candidate=_candidate(membership_hash="candidate-hash"),
        outline=CachedOutline(
            promise="Learn the basics",
            sections=(("A", "B"),),
            membership_hash="outline-hash",
            model="fake-outline-writer",
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        members=(_member("e1", "Warp Core"),),
    )

    view = course_detail_view(detail)

    assert view["outline"]["membershipHash"] == "outline-hash"
    assert view["outline"]["membershipHash"] != view["candidate"]["membershipHash"]


def test_a_catalog_with_no_orphans_carries_an_empty_list_not_a_missing_key():
    view = catalog_view(_catalog())

    assert view["orphanedCourses"] == []


def test_a_catalogs_orphaned_courses_carry_slug_title_and_realized_at():
    stranded = RealizedCourse(
        slug="ancient-rome",
        title="Ancient Rome",
        member_entity_ids=("e1",),
        membership_hash="hash-v1",
        realized_at=datetime(2026, 8, 20, tzinfo=UTC),
        authored_session_id=None,
    )

    view = catalog_view(_catalog(), orphaned_courses=(stranded,))

    assert view["orphanedCourses"] == [
        {
            "slug": "ancient-rome",
            "title": "Ancient Rome",
            "realizedAt": "2026-08-20T00:00:00+00:00",
        }
    ]


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
