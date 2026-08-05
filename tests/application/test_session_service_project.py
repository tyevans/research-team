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
    aggregate.execute(CreateProject(name="research"))
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
    session_id = await service.create_session()

    await service.release_project(session_id)


async def test_releasing_lets_a_second_session_take_the_project(service, project_id):
    first = await service.start_in_project(project_id)
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    assert second != first
