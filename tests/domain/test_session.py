"""The shell: what `Session` adds on top of the pure decider.

`test_decider.py` covers the rules. This covers the wiring -- that `execute`
runs `decide`, stamps and applies the events it returns, and that the state
those events fold into survives a round trip through the repository. Anything
here needs an aggregate or a store; anything that does not belongs next door.
"""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain import (
    SendUserMessage,
    Session,
    SessionPurpose,
    StartSession,
    WriteFile,
)
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT

FILE_DATA = {"content": "print(1)\n", "encoding": "utf-8"}


def test_execute_applies_the_events_decide_returns(session_id):
    session = Session(session_id)

    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )

    assert [type(e).__name__ for e in session.uncommitted_events] == ["SessionStarted"]
    assert session.state.system_prompt == SYSTEM_PROMPT


def test_execute_stamps_the_version_decide_cannot_know(session_id):
    """Pure functions have no business knowing about optimistic concurrency."""
    session = Session(session_id)

    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    session.execute(SendUserMessage(message={"type": "human", "data": {}}))

    assert [e.aggregate_version for e in session.uncommitted_events] == [1, 2]


def test_a_rejected_command_leaves_the_aggregate_untouched(session_id):
    """`decide` runs to completion before anything is applied, so a refusal
    cannot leave half a turn behind."""
    session = Session(session_id)

    with pytest.raises(CommandRejectedError):
        session.execute(WriteFile(path="/a.py", file_data=FILE_DATA))

    assert session.uncommitted_events == []
    assert session.version == 0


def test_state_is_real_before_the_first_event(session_id):
    """The gotcha `DeciderAggregate` exists to close.

    `AggregateRoot._state` is None until an event lands, but `decide` has to
    match against a session that does not exist yet. If this were None the
    very first `StartSession` would fall through to "already started".
    """
    assert Session(session_id).state.status == "new"


async def test_state_survives_save_and_reload(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    session.execute(WriteFile(path="/a.py", file_data=FILE_DATA))
    session.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await aggregates.save(session)

    reloaded = await aggregates.load(session_id)

    assert reloaded.state.files == {"/a.py": FILE_DATA}
    assert reloaded.state.messages[-1]["data"]["content"] == "hi"
    assert reloaded.version == 3
    # Replay reconstitutes the decider's own view, not just the payloads.
    assert reloaded.state.status == "started"


def test_a_session_remembers_what_kind_of_work_it_is_for(session_id):
    """The purpose reaches the state, which is the only place anything reads it.

    Would pass with `decide` returning a hard-coded CHAT, which is why the
    second half uses a non-default purpose: a build that ignored the command
    and folded the enum's first member would answer CHAT here and fail.
    """
    session = Session(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.RESEARCH_ROUND,
        )
    )
    assert session.state.purpose is SessionPurpose.RESEARCH_ROUND
