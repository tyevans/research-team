"""A session inherits its project's filesystem, not its conversation.

Inheritance reuses `_fork_files_from` -- the same replay `fork()` uses,
narrowed to file events -- so these tests exercise `start_in_project` and
`release_project` end to end rather than the replay mechanics on their own
(those are already covered by `test_fork_tree.py`).
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from research_team.application.topics import SELF_CONTAINED_QUESTION
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


async def test_release_project_is_a_no_op_for_a_session_that_holds_nothing(service):
    """Releasing what you do not hold is not an error.

    The REPL calls `release_project` unconditionally on exit -- it does not
    know whether the session it is closing still holds its project -- so this
    has to be safe on a session that does not.

    Reached by releasing twice. It used to be reached with a session that had
    no `project_id` at all, which cannot be built now; a session that has
    already given its project back is the same "holds nothing" state by the
    only route left to it.
    """
    session_id = await start_session(service)
    await service.release_project(session_id)

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


# `test_a_plain_session_does_not_mention_the_knowledge_graph` was here. It
# checked that a session with no project was not told about tools it did not
# have. There is no such session now -- every one belongs to a project and so
# every one has the graph -- which makes the guarantee unconditional rather
# than gone: the test above it, that a joined session *is* told, is now the
# whole of the claim.


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


# `test_a_plain_session_is_not_told_about_topic_tools` was here, and went for
# the same reason as its knowledge-graph twin above: the session it described
# cannot be built.


async def test_a_session_started_in_a_project_is_told_the_project_it_is_in(
    service, project_id
):
    """An agent joined to a project could not name the project it was joined to.

    Every project-scoped prompt in this build describes *tools* -- the graph,
    the corpus, the topic queue -- and none of them says what the project is
    about. That is what makes a topic question like "typical physical traits"
    unrecoverable downstream: the subject is implicit in the project and the
    project was never named, so there is nothing to disambiguate against.

    Would pass with the change reverted only if `CreateProject`'s name
    happened to appear in the default prompt, which it does not: the fixture
    names this project `research` and no default text contains it.
    """
    session_id = await service.start_in_project(project_id)

    session = await service.load(session_id)

    assert "research" in session.state.system_prompt


async def test_a_second_session_in_a_project_is_told_it_too(service, project_id, fake_model):
    """The forking path builds its own `SessionStarted`, so it needs the name
    threaded separately -- a second join that inherited files but not the
    project's name would be the same defect, visible only on the second
    session of a project and therefore never in a fresh-database test."""
    first = await service.start_in_project(project_id)
    await _write_file(service, first, "/notes.md", "something", fake_model)
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    session = await service.load(second)
    assert "research" in session.state.system_prompt


async def test_a_joined_session_is_told_what_a_self_contained_question_is(service, project_id):
    """The rule travels with `open_topic`, not with the seeding turn.

    Seeding is where the defect was *seen* -- a list written under a
    "Subject:" heading elides the heading -- but an autonomous round opening a
    topic mid-run elides just as readily and never sees `seeding_prompt`.
    `TOPICS_PROMPT` is appended exactly where `build_topic_tools` binds the
    tool, so the rule is present whenever the tool is and absent whenever it
    is not -- the scoping `component_guidance` argues for.

    Asserts the failure *example* survives, not just the phrase
    "self-contained": the vague version of this instruction is the one the
    model was already given and already believed it had followed.
    """
    session_id = await service.start_in_project(project_id)

    session = await service.load(session_id)

    assert SELF_CONTAINED_QUESTION in session.state.system_prompt
    assert "typical physical traits" in SELF_CONTAINED_QUESTION


# --- work done after a release ------------------------------------------------
#
# The failure these pin was found in a real database, not reasoned about:
# project "Tollers" (`9d6bd8d4`) has a session (`08f37266`) holding four
# `/course/*.md` artifacts at events 34-37, and the session that succeeded it
# (`588102a5`) forked at event 31 and has none of them. An auto-research run
# had started that session and released it in its `after` hook when the run
# stopped; the person kept working in it, and every file they wrote after that
# release was invisible to the project from the moment it was written.


async def test_a_release_does_not_freeze_the_project_at_the_moment_it_happened(
    service, project_id, fake_model
):
    """Work done after a release still belongs to the project.

    `release_project` records `at_event=session.version` -- a snapshot of where
    the session was when it was released, not a live pointer. Nothing stops the
    session from continuing, and until this it kept its later work to itself:
    the tip named the right session and the wrong point in it.

    Fails with the change reverted on the last assertion, and the value it
    reports is the whole bug -- `/after.md` is absent while `/before.md` is
    there, so the next session inherits a prefix of a stream rather than a
    filesystem.
    """
    first = await service.start_in_project(project_id)
    await _write_file(service, first, "/before.md", "early", fake_model)
    await service.release_project(first)
    await _write_file(service, first, "/after.md", "late", fake_model)

    second = await service.start_in_project(project_id)

    session = await service.load(second)
    assert session.state.files["/before.md"]["content"] == "early"
    assert session.state.files["/after.md"]["content"] == "late"


async def test_the_project_shows_files_written_after_its_release(
    service, project_id, fake_model
):
    """The same defect on the read side, which is the half the owner saw.

    `project_files` asks the holder first and falls back to the tip pointer.
    With the session released there is no holder, so the fallback is the whole
    answer -- and it was reading the tip session at the frozen `at_event`. The
    project's own file listing went blank of work that was sitting in the
    stream it was pointing at.
    """
    first = await service.start_in_project(project_id)
    await service.release_project(first)
    await _write_file(service, first, "/after.md", "late", fake_model)

    assert "/after.md" in await service.project_files(project_id)


async def test_the_fork_point_recorded_is_the_one_actually_taken(
    service, project_id, fake_model
):
    """`SessionForkedFrom.at_event` must name where the fork really happened.

    Catching the tip up is a write, and the reason to do it rather than
    quietly fork further along than the pointer says is this: `inherited_at`
    on `SessionJoinedProject` and `at_event` on `SessionForkedFrom` are the
    two records of where a session's filesystem came from, and a fork that
    outran the pointer would leave both of them describing a point that is not
    where anything was copied from.
    """
    first = await service.start_in_project(project_id)
    await service.release_project(first)
    await _write_file(service, first, "/after.md", "late", fake_model)

    second = await service.start_in_project(project_id)

    at = len(await service.history(first))
    forked = [
        event
        for event in await service.history(second)
        if event.__class__.__name__ == "SessionForkedFrom"
    ]
    assert [event.at_event for event in forked] == [at]
    assert (await service.projects.load(project_id)).state.tip_at_event == at
