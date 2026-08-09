"""A session inherits its project's filesystem, not its conversation.

Inheritance reuses `_fork_files_from` -- the same replay `fork()` uses,
narrowed to file events -- so these tests exercise `start_in_project` and
`release_project` end to end rather than the replay mechanics on their own
(those are already covered by `test_fork_tree.py`).
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from research_team.domain import CreateProject
from tests.conftest import start_session


@pytest.fixture
async def service(build_service, fake_model):
    """Same fixture `test_session_service.py` defines -- there is no shared
    `conftest.py` in this directory to extend, so this mirrors it exactly
    rather than reaching across test modules for a fixture."""
    return await build_service(model=fake_model)


@pytest.fixture
async def project_id(service):
    """A freshly created `Project`, via the service's own accessor.

    Goes through `service.projects` rather than a private repository hop --
    the same accessor `/project new` uses at the REPL.
    """
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="research"))
    await service.projects.save(aggregate)
    return aggregate.aggregate_id


async def _write_file(service, session_id, path: str, content: str, fake_model) -> None:
    """Write a file the way a real turn would: through the tool, not a shortcut.

    Drives `run_turn` with the fake model's next response set to a
    `write_file` tool call -- the same pattern
    `test_tool_call_writes_file_and_records_events` uses -- so the file
    events on the session's stream are exactly what a real turn produces.
    """
    fake_model.responses = [
        AIMessage(
            content="",
            id=f"a-{path}",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": path, "content": content},
                    "id": f"t-{path}",
                }
            ],
        ),
        AIMessage(content="wrote it", id=f"a2-{path}"),
    ]
    await service.run_turn(session_id, f"write {path}")


async def test_the_first_session_in_a_project_starts_empty(service, project_id):
    session_id = await service.start_in_project(project_id)

    session = await service.load(session_id)
    assert session.state.files == {}
    assert session.state.project_id == project_id


async def test_a_later_session_inherits_the_previous_one_s_files(
    service, project_id, fake_model
):
    first = await service.start_in_project(project_id)
    await _write_file(service, first, "/notes.md", "hello", fake_model)
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    session = await service.load(second)
    assert session.state.files["/notes.md"]["content"] == "hello"
    assert session.state.forked_from == first


async def test_inheriting_does_not_copy_the_conversation(service, project_id, fake_model):
    """A project shares a filesystem, not a chat history."""
    first = await service.start_in_project(project_id)
    await _write_file(service, first, "/notes.md", "hello", fake_model)
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    session = await service.load(second)
    assert session.state.messages == []


async def test_a_second_session_cannot_start_while_one_holds_the_project(service, project_id):
    from eventsource import CommandRejectedError

    first = await service.start_in_project(project_id)

    with pytest.raises(CommandRejectedError, match=str(first)):
        await service.start_in_project(project_id)


async def test_release_project_is_a_no_op_for_a_plain_session(service):
    """A session with no `project_id` releasing nothing is not an error.

    The REPL calls `release_project` unconditionally on exit -- it does not
    know whether the session it is closing ever joined a project -- so this
    has to be safe to call on an ordinary session too.
    """
    session_id = await start_session(service)

    await service.release_project(session_id)


async def test_releasing_lets_a_second_session_take_the_project(
    service, project_id, fake_model
):
    """`second != first` alone proves nothing -- two `uuid4()`s can't collide.
    What matters: the second call does not raise, it actually joined the
    project, and it inherited the tip the first session left behind.
    """
    first = await service.start_in_project(project_id)
    await _write_file(service, first, "/notes.md", "hello", fake_model)
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    session = await service.load(second)
    assert session.state.project_id == project_id
    assert session.state.files["/notes.md"]["content"] == "hello"


async def test_release_project_is_a_no_op_for_a_session_that_is_not_the_holder(
    service, project_id
):
    """Releasing something you do not hold is nothing, not an error.

    Reachable in the REPL: session `first` holds the project and releases it
    normally, `second` then takes it -- and later something resumes `first`
    (an old session whose `project_id` is still set to this project) and
    tries to release it again on exit. Before this behaviour,
    `AdvanceTip` rejected that as "you do not hold this", and the rejection
    escaped the REPL's cleanup `finally`. This pins the fix: releasing a
    non-holding session must not raise, and must not disturb whoever
    actually holds it.
    """
    first = await service.start_in_project(project_id)
    await service.release_project(first)
    second = await service.start_in_project(project_id)

    await service.release_project(first)

    project = await service.projects.load(project_id)
    assert project.state.active_session_id == second


async def test_a_session_started_in_a_project_records_the_knowledge_prompt(
    service, project_id
):
    """The system prompt a session ran under is recorded in its own
    `SessionStarted` event -- the right home for it in an event-sourced
    system, since a session resumed later must run under the prompt it
    actually started with, not whatever the process's default happens to be
    today.
    """
    session_id = await service.start_in_project(project_id)

    session = await service.load(session_id)

    assert "knowledge graph" in session.state.system_prompt.lower()


async def test_a_plain_session_does_not_mention_the_knowledge_graph(service):
    """No project, no knowledge tools -- so the prompt must not describe
    tools the session was never given.
    """
    session_id = await start_session(service)

    session = await service.load(session_id)

    assert "knowledge graph" not in session.state.system_prompt.lower()


async def test_a_session_started_in_a_project_is_told_about_its_topic_tools(
    service, project_id
):
    """The topic tools ride the project attachment, so a joined session *has*
    `open_topic`, `list_topics`, `record_finding` and `link_source`. It was not
    told, which is the failure mode the comment beside the build-time prompt
    already names: the tool is on the executor and the model has no idea it
    exists.

    Visible from the outside as an autonomous run that stops on its first round
    with "queue_empty" forever, because the only thing that can put a topic on
    the queue is the agent calling `open_topic`, and nothing ever told it to.
    """
    session_id = await service.start_in_project(project_id)

    session = await service.load(session_id)

    prompt = session.state.system_prompt
    assert "open_topic" in prompt
    assert "list_topics" in prompt
    assert "record_finding" in prompt


async def test_a_plain_session_is_not_told_about_topic_tools(service):
    """No project, no topic tools -- so the prompt must not describe them, for
    the same reason it must not describe the graph."""
    session_id = await start_session(service)

    session = await service.load(session_id)

    assert "open_topic" not in session.state.system_prompt
