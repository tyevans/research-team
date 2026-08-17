"""The web view models, as pure functions over domain objects."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.application import SessionSummary
from research_team.application.corpus_read import SourceListing
from research_team.domain import (
    AssistantMessageAdded,
    AutonomyChanged,
    FileDeleted,
    FileEdited,
    FileWritten,
    MediaRecord,
    ProjectStageAdvanced,
    ProjectWorkflowSelected,
    SessionForkedFrom,
    SessionPurpose,
    SessionStarted,
    TextRecord,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.interfaces.web.presenters import (
    SUMMARY_LIMIT,
    event_row,
    event_rows,
    event_summary,
    file_history,
    message_view,
    preset_view,
    project_view,
    source_view,
    stage_view,
    summary_view,
)
from research_team.workflows import hybrid_default, ubd_pure

AGGREGATE = uuid4()


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


# ---------------- workflows ----------------


def test_a_selected_workflow_is_summarised_by_the_preset_it_chose():
    """The fallback returns "" for these, which loses the entire content.

    `ProjectWorkflowSelected` carries no `turn_index` and no `message`, so before
    this branch a timeline row said `ProjectWorkflowSelected` and nothing else --
    the one fact worth recording, which preset the run is now bound to, was
    the fact that went missing.
    """
    event = make(ProjectWorkflowSelected, preset_id="hybrid.default", preset_version="1")
    summary = event_summary(event)
    assert "hybrid.default" in summary
    assert "1" in summary


def test_an_advanced_stage_is_summarised_by_both_ends_of_the_move():
    """From *and* to: a stage list is long and "now at X" does not say what moved."""
    event = make(
        ProjectStageAdvanced,
        from_stage="tyler.step0.intake",
        to_stage="hybrid.step1.framing",
        decided_by="agent",
        gate_decision="the intake is cited",
    )
    summary = event_summary(event)
    assert "tyler.step0.intake" in summary
    assert "hybrid.step1.framing" in summary
    assert "the intake is cited" in summary


def test_a_changed_autonomy_is_summarised_by_the_tool_and_its_new_level():
    """The tool alone or the level alone doesn't say what changed; both do."""
    event = make(AutonomyChanged, tool_name="fetch", level="auto")
    summary = event_summary(event)
    assert "fetch" in summary
    assert "auto" in summary


def test_a_preset_is_described_by_what_it_produces_and_where_it_stops():
    view = preset_view(ubd_pure)

    assert view["id"] == "ubd.pure"
    assert view["produces"] == "design"
    assert view["stage_count"] == len(ubd_pure.stages)
    assert view["terminates_at"]["id"] == ubd_pure.stages[-1].id
    assert view["terminates_at"]["spine"] == ubd_pure.terminal_spine
    assert view["has_value_filter"] is False


def test_a_presets_label_says_what_it_produces_and_where_it_ends():
    """The label is the `<select>` option text, so it carries the whole choice.

    A dropdown of three methodology names is only meaningful to someone who
    has read the research; what a preset produces and where it stops is
    meaningful to everyone.
    """
    label = preset_view(ubd_pure)["label"]
    assert ubd_pure.name in label
    assert "design" in label
    assert ubd_pure.stages[-1].name in label


def test_a_preset_producing_only_a_design_says_so_against_one_producing_materials():
    assert preset_view(hybrid_default)["produces"] == "materials"
    assert "materials" in preset_view(hybrid_default)["label"]


def test_a_stage_is_placed_in_its_preset_rather_than_merely_named():
    """ "Stage 4 of 15" is the fact a chip needs; the id alone is not readable."""
    view = stage_view(hybrid_default, hybrid_default.stages[3])

    assert view["id"] == hybrid_default.stages[3].id
    assert view["name"] == hybrid_default.stages[3].name
    assert view["index"] == 4
    assert view["of"] == len(hybrid_default.stages)


def test_a_project_without_a_workflow_reports_both_fields_as_null():
    """Every project written before workflows existed is this case."""
    view = project_view(AGGREGATE, "atlas")
    assert view["workflow"] is None
    assert view["stage"] is None


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
