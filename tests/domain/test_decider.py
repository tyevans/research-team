"""The session's rules, as three pure functions.

No aggregate, no repository, no event loop, no fixtures -- `decide` takes a
command and a state and returns events or raises, and `evolve` takes a state
and an event and returns the next state. A test is "fold these events, decide
this command, assert on the result", which is what the rules were always about
underneath the aggregate that used to carry them.

`decide` also doubles as the inventory of legal transitions: every case below
corresponds to one branch of it, and a transition with no test here is a
transition nobody has claimed is legal.
"""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError
from pydantic import ValidationError

from research_team.domain import (
    AutonomyChanged,
    ChangeAutonomy,
    CompactConversation,
    CompleteTurn,
    DeleteFile,
    EditFile,
    FailTurn,
    FileEdited,
    RecordAssistantMessage,
    RecordForkSource,
    RecordStageReview,
    RecordToolDecision,
    RecordToolResult,
    SendUserMessage,
    SessionStarted,
    StageChecksEvaluated,
    StartSession,
    ToolCallDecided,
    ToolResultRecorded,
    TurnFailed,
    WriteFile,
    decide,
    evolve,
    initial_state,
)

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"

FILE_DATA = {"content": "print(1)\n", "encoding": "utf-8"}


def run(state, *commands):
    """Fold a sequence of commands through decide/evolve. The whole harness."""
    for command in commands:
        for event in decide(command, state):
            state = evolve(state, event)
    return state


def started(session_id=None):
    """A session that has been started and nothing else."""
    return run(
        initial_state(),
        StartSession(
            session_id=session_id or uuid4(),
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
        ),
    )


def user(text: str) -> dict:
    return {"type": "human", "data": {"content": text}}


def calling(*call_ids: str) -> dict:
    """An assistant message that asked for the given tool calls."""
    return {
        "type": "ai",
        "data": {
            "content": "",
            "tool_calls": [
                {"id": call_id, "name": "write_file", "args": {}} for call_id in call_ids
            ],
        },
    }


def tool_result(call_id: str, content: str = "ok") -> dict:
    return {"type": "tool", "data": {"tool_call_id": call_id, "content": content}}


# ---------------- creation ----------------


def test_a_new_session_is_not_yet_started():
    """The decider has to encode "uncreated" as a fact about the domain.

    The aggregate used to answer this with `version > 0`, which is a statement
    about the event store rather than about a session. Here it is `status`,
    which is the thing `decide` matches on.
    """
    assert initial_state().status == "new"


def test_starting_a_session_emits_session_started():
    session_id = uuid4()
    state = initial_state()

    [event] = decide(
        StartSession(
            session_id=session_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
        ),
        state,
    )

    assert event.aggregate_id == session_id

    assert isinstance(event, SessionStarted)
    assert event.system_prompt == SYSTEM_PROMPT
    assert event.model_name == MODEL_NAME


def test_starting_twice_is_rejected():
    with pytest.raises(CommandRejectedError, match="already started"):
        decide(
            StartSession(
                session_id=uuid4(), system_prompt="x", model_name="y", project_id=uuid4()
            ),
            started(),
        )


def test_a_session_records_the_project_it_belongs_to():
    session_id, project_id = uuid4(), uuid4()
    state = initial_state()

    events = decide(
        StartSession(
            session_id=session_id, system_prompt="p", model_name="m", project_id=project_id
        ),
        state,
    )

    assert events[0].project_id == project_id
    assert evolve(state, events[0]).project_id == project_id


def test_a_session_outside_a_project_cannot_be_asked_for():
    """What `test_a_session_without_a_project_has_none` used to assert.

    That test built a `StartSession` with no `project_id` and checked the
    event and the state both came back `None`. `project_id` is required on
    the command now, so the request cannot be phrased -- which is the point:
    the rule is enforced by the type rather than by `decide` rejecting it, so
    there is no rejection to test and no caller left to remember the rule.
    The failure happens at construction, one layer before the decider.
    """
    with pytest.raises(ValidationError, match="project_id"):
        StartSession(session_id=uuid4(), system_prompt="p", model_name="m")


@pytest.mark.parametrize(
    "command",
    [
        SendUserMessage(message={"type": "human", "data": {"content": "hi"}}),
        CompleteTurn(),
        WriteFile(path="/a.py", file_data=FILE_DATA),
        DeleteFile(path="/a.py"),
        RecordForkSource(source_session_id=uuid4(), at_event=2),
    ],
    ids=lambda c: type(c).__name__,
)
def test_nothing_is_accepted_before_the_session_starts(command):
    """One case per command in `decide`, rather than a guard called everywhere."""
    with pytest.raises(CommandRejectedError, match="not started"):
        decide(command, initial_state())


# ---------------- conversation ----------------


def test_messages_accumulate_in_order():
    state = run(
        started(),
        SendUserMessage(message=user("first")),
        RecordAssistantMessage(message=calling("t1")),
        RecordToolResult(message=tool_result("t1")),
    )

    assert [m["type"] for m in state.messages] == ["human", "ai", "tool"]


def test_a_tool_result_needs_an_outstanding_call():
    """The invariant that keeps the message log replayable by the model.

    A tool result answering nothing would leave a message the model cannot
    make sense of on replay, so it is refused rather than recorded.
    """
    with pytest.raises(CommandRejectedError, match="no outstanding tool call"):
        decide(RecordToolResult(message=tool_result("t1")), started())


def test_a_tool_result_is_accepted_once_its_call_is_outstanding():
    state = run(started(), RecordAssistantMessage(message=calling("t1")))

    [event] = decide(RecordToolResult(message=tool_result("t1")), state)

    assert isinstance(event, ToolResultRecorded)


def test_tool_results_may_answer_out_of_order():
    state = run(started(), RecordAssistantMessage(message=calling("t1", "t2")))

    state = run(
        state,
        RecordToolResult(message=tool_result("t2", "b")),
        RecordToolResult(message=tool_result("t1", "a")),
    )

    assert [m["type"] for m in state.messages][-2:] == ["tool", "tool"]


def test_the_same_tool_call_cannot_be_answered_twice():
    state = run(
        started(),
        RecordAssistantMessage(message=calling("t1")),
        RecordToolResult(message=tool_result("t1")),
    )

    with pytest.raises(CommandRejectedError, match="no outstanding tool call"):
        decide(RecordToolResult(message=tool_result("t1")), state)


# ---------------- turns ----------------


def test_completing_a_turn_advances_the_index():
    state = run(started(), CompleteTurn(), CompleteTurn())

    assert state.turn_index == 2


def test_a_failed_turn_counts_but_does_not_advance_the_index():
    """A turn that did not happen must not look like one that did."""
    state = run(started(), CompleteTurn(), FailTurn.from_error(RuntimeError("boom")))

    assert (state.turn_index, state.failed_turns) == (1, 1)


def test_a_failure_records_the_error_it_was_given():
    [event] = decide(FailTurn.from_error(RuntimeError("boom")), started())

    assert isinstance(event, TurnFailed)
    assert (event.error_type, event.error_message) == ("RuntimeError", "boom")
    assert event.cancelled is False


def test_a_cancellation_is_recorded_as_one():
    """Stopped on purpose and broke are different facts about the same hole."""
    [event] = decide(FailTurn.from_error(RuntimeError("stopped"), cancelled=True), started())

    assert event.cancelled is True
    assert event.error_type == "Cancelled"


def test_a_long_error_message_is_truncated():
    [event] = decide(FailTurn.from_error(RuntimeError("x" * 900)), started())

    assert len(event.error_message) == 500


# ---------------- compaction ----------------


def _with_messages(count: int):
    state = started()
    for index in range(count):
        state = run(state, SendUserMessage(message=user(str(index))))
    return state


def test_compaction_records_what_the_model_will_see():
    state = _with_messages(4)

    [event] = decide(
        CompactConversation(summary="they talked", through_index=3, strategy="s"),
        state,
    )

    assert event.through_index == 3
    state = evolve(state, event)
    # The messages themselves are untouched -- only the model's view narrows.
    assert len(state.messages) == 4
    assert state.compacted_through == 3


def test_compaction_cannot_go_backwards():
    """Uncovering messages an earlier summary covered would show the model
    both the summary and the messages it stands in for."""
    state = _with_messages(4)
    state = run(state, CompactConversation(summary="s", through_index=3, strategy="s"))

    with pytest.raises(CommandRejectedError, match="cannot compact"):
        decide(CompactConversation(summary="s", through_index=2, strategy="s"), state)


def test_compaction_cannot_run_past_the_end():
    state = _with_messages(2)

    with pytest.raises(CommandRejectedError, match="cannot compact"):
        decide(CompactConversation(summary="s", through_index=5, strategy="s"), state)


# ---------------- files ----------------


def test_writing_a_file_adds_it():
    state = run(started(), WriteFile(path="/a.py", file_data=FILE_DATA))

    assert state.files["/a.py"] == FILE_DATA


def test_editing_a_file_that_does_not_exist_is_rejected():
    with pytest.raises(CommandRejectedError, match="does not exist"):
        decide(
            EditFile(
                path="/nope.py",
                file_data=FILE_DATA,
                old_string="a",
                new_string="b",
                replace_all=False,
            ),
            started(),
        )


def test_deleting_a_file_that_does_not_exist_is_rejected():
    with pytest.raises(CommandRejectedError, match="does not exist"):
        decide(DeleteFile(path="/nope.py"), started())


def test_an_edit_carries_both_the_result_and_the_intent():
    """`file_data` keeps the fold O(1); the strings keep the log meaningful."""
    state = run(started(), WriteFile(path="/a.py", file_data=FILE_DATA))

    [event] = decide(
        EditFile(
            path="/a.py",
            file_data={"content": "print(2)\n"},
            old_string="1",
            new_string="2",
            replace_all=False,
        ),
        state,
    )

    assert isinstance(event, FileEdited)
    assert (event.old_string, event.new_string) == ("1", "2")


def test_deleting_a_file_removes_it_from_state():
    state = run(
        started(),
        WriteFile(path="/a.py", file_data=FILE_DATA),
        WriteFile(path="/b.py", file_data=FILE_DATA),
        DeleteFile(path="/a.py"),
    )

    assert list(state.files) == ["/b.py"]


# ---------------- lineage ----------------


def test_fork_lineage_is_recorded():
    source = uuid4()

    state = run(started(), RecordForkSource(source_session_id=source, at_event=7))

    assert (state.forked_from, state.forked_at) == (source, 7)


# ---------------- evolve's totality ----------------


def test_evolve_ignores_an_event_it_has_no_branch_for():
    """Total by construction, so a new event type cannot break replay of an
    old stream -- it simply does not move the state."""
    state = started()

    class Unrelated(SessionStarted):
        pass

    assert (
        evolve(
            state,
            Unrelated(
                aggregate_id=state.session_id,
                system_prompt="",
                model_name="",
                project_id=uuid4(),
            ),
        ).messages
        == state.messages
    )


# ---------------- supervision ----------------


def test_a_tool_decision_produces_an_audit_event():
    state = started()

    (event,) = decide(
        RecordToolDecision(
            tool_name="web_search",
            args={"query": "event sourcing"},
            decision="approve",
            decided_by="human",
        ),
        state,
    )

    assert isinstance(event, ToolCallDecided)
    assert (event.decision, event.decided_by, event.edited_args) == (
        "approve",
        "human",
        None,
    )


def test_an_edited_tool_call_carries_the_amended_args():
    state = started()

    (event,) = decide(
        RecordToolDecision(
            tool_name="web_search",
            args={"query": "a"},
            decision="edit",
            decided_by="human",
            edited_args={"query": "b"},
        ),
        state,
    )

    assert event.edited_args == {"query": "b"}


def test_an_autonomy_change_produces_an_audit_event():
    state = started()

    (event,) = decide(ChangeAutonomy(tool_name="web_search", level="ask"), state)

    assert isinstance(event, AutonomyChanged)
    assert (event.tool_name, event.level) == ("web_search", "ask")


def test_supervision_events_leave_the_state_alone():
    """Audit records, not facts SessionState tracks: `evolve` is a no-op for
    both, and the assertion is that nothing moved."""
    state = started()

    after = run(
        state,
        ChangeAutonomy(tool_name="web_search", level="ask"),
        RecordToolDecision(
            tool_name="web_search", args={}, decision="approve", decided_by="human"
        ),
    )

    assert after == state


def test_a_stage_review_is_recorded_as_an_audit_event():
    """`RecordStageReview` produces one event and touches no state.

    Fails if the command is unhandled, and fails differently if someone makes
    `evolve` fold it: `SessionState` tracks what the session *is*, and what a
    check found at a gate is not that.
    """
    state = started()
    review_id = uuid4()
    project_id = uuid4()

    (event,) = decide(
        RecordStageReview(
            review_id=review_id,
            project_id=project_id,
            stage="analysis",
            preset="hybrid.default",
            preset_version="1",
            evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 2}],
            unimplemented=[{"check": "ubd.uncoverage", "severity": "blocking"}],
            posed_by="runner",
        ),
        state,
    )

    assert isinstance(event, StageChecksEvaluated)
    assert event.aggregate_id == state.session_id
    assert event.review_id == review_id
    assert event.project_id == project_id
    assert (event.stage, event.preset, event.preset_version) == (
        "analysis",
        "hybrid.default",
        "1",
    )
    assert event.posed_by == "runner"
    assert event.evaluated == [
        {"check": "shared.coverage", "severity": "blocking", "findings": 2}
    ]
    assert event.unimplemented == [{"check": "ubd.uncoverage", "severity": "blocking"}]
    # The audit half: nothing about the session changed.
    assert evolve(state, event) == state


def test_a_tool_decision_can_name_the_review_it_answers():
    """`review_id` rides through `RecordToolDecision` onto the event.

    This is the only join between a finding and the decision that followed it;
    `ToolCallDecided` names no stage, and `ProjectStageAdvanced` -- which does -- is on
    the `Project` stream and is not written at all when a gate is rejected.
    """
    review_id = uuid4()

    (event,) = decide(
        RecordToolDecision(
            tool_name="advance_stage",
            args={"rationale": "3 findings"},
            decision="approve",
            decided_by="human",
            review_id=review_id,
        ),
        started(),
    )

    assert event.review_id == review_id


def test_a_tool_decision_that_answers_no_review_says_so():
    """The default is None, which is what every non-gate tool call means."""
    (event,) = decide(
        RecordToolDecision(
            tool_name="web_search",
            args={"query": "x"},
            decision="approve",
            decided_by="human",
        ),
        started(),
    )

    assert event.review_id is None
