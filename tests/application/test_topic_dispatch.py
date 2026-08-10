"""Dispatching one agent at one topic, to write down what we understand of it.

Driven end to end through `build_applications` exactly as
`test_topic_seeding.py` drives the seeder, for the same reason: a fake model
stands in for the agent, and what is asserted is what actually reached the
session's filesystem rather than what the dispatcher claims it did. The
distinction matters more here than for seeding -- a dispatch's whole output
*is* a file, so a test that trusted the return value would pass against a
dispatcher that never wrote one.
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from research_team.application import TurnSupervisor
from research_team.application.topic_dispatch import (
    UNDERSTANDING_PROMPT,
    TopicDispatcher,
    UnknownTopic,
    understanding_path,
)
from research_team.domain import CreateProject


@pytest.fixture
async def application(build_applications, fake_model):
    return await build_applications(model=fake_model)


@pytest.fixture
async def service(application):
    return application.service


@pytest.fixture
async def project_id(service):
    aggregate = service.projects.create_new(uuid4())
    aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name="research"))
    await service.projects.save(aggregate)
    return aggregate.aggregate_id


@pytest.fixture
def topic_reader(application, project_id):
    return application.topic_readers(project_id)


@pytest.fixture
def dispatcher(service, application):
    return TopicDispatcher(service, TurnSupervisor(service), application.topic_readers)


def _opens_topic(question: str, rationale: str = "core") -> AIMessage:
    return AIMessage(
        content="",
        id=f"open-{question}",
        tool_calls=[
            {
                "name": "open_topic",
                "args": {"question": question, "rationale": rationale},
                "id": f"t-{question}",
            }
        ],
    )


def _writes(path: str, text: str, call_id: str = "w1") -> AIMessage:
    """A model turn that writes one file and stops -- what a dispatch does."""
    return AIMessage(
        content="",
        id=f"write-{call_id}",
        tool_calls=[
            {"name": "write_file", "args": {"file_path": path, "content": text}, "id": call_id}
        ],
    )


async def _seed_topic(service, dispatcher, fake_model, project_id, question: str):
    """Open one topic through a real turn, so it exists in the read model."""
    from research_team.application.topic_seeding import TopicSeeder

    seeder = TopicSeeder(service, TurnSupervisor(service))
    fake_model.responses = [_opens_topic(question), AIMessage(content="opened", id="done")]
    await seeder.seed(project_id, "spaced repetition", max_topics=8)


# ---------------- the path convention ----------------


def test_the_understanding_path_numbers_the_topic_and_slugs_its_question():
    """`<nn>` and the slug are the whole ordering the file viewer has, so the
    convention is asserted directly rather than only through a dispatch --
    a dispatch test would fail on this *and* on twenty other things."""
    assert (
        understanding_path(0, "How does spacing interval affect retention?")
        == "/topics/00-how-does-spacing-interval-affect-retention/understanding.md"
    )


def test_a_long_question_is_cut_to_a_readable_slug_on_a_word_boundary():
    """Questions are free text and some are a paragraph. A path is read by a
    person in a file list, and an unbounded slug makes that list unreadable
    -- and on some filesystems, unwritable. Cut on a hyphen so the last word
    is whole rather than a fragment."""
    path = understanding_path(3, "What " + "considerations " * 20 + "apply?")
    directory = path.rsplit("/", 1)[0].rsplit("/", 1)[-1]
    assert len(directory) <= 63  # two digits, a hyphen, and the capped slug
    assert not directory.endswith("-")
    assert directory.startswith("03-what-considerations")


def test_a_question_with_no_usable_characters_still_gets_a_directory():
    """`????` slugifies to nothing, and a path of `/topics/00-/understanding.md`
    is a directory with no name. Falls back to the topic's number, which is
    always there."""
    assert understanding_path(7, "???") == "/topics/07-topic/understanding.md"


# ---------------- what a dispatch does ----------------


async def test_dispatching_understanding_writes_the_file_at_the_topic_s_path(
    dispatcher, service, fake_model, project_id, topic_reader
):
    """The one assertion this whole feature exists for: the file lands, on the
    session's own filesystem, at the path the convention names."""
    await _seed_topic(service, dispatcher, fake_model, project_id, "How does spacing work?")
    [view] = await topic_reader.list_topics()
    path = understanding_path(0, "How does spacing work?")

    fake_model.responses = [
        _writes(path, "---\ntopic_id: x\n---\n\nSpacing works."),
        AIMessage(content="written", id="a2"),
    ]
    run = await dispatcher.dispatch(project_id, view.summary.topic_id)

    files = await service.project_files(project_id)
    assert path in files
    assert run.path == path


async def test_the_prompt_names_the_topic_the_path_and_the_rule(
    dispatcher, service, fake_model, project_id, topic_reader
):
    """Asserts the wording actually reaches the model rather than paraphrasing
    it here. The path in particular: a dispatch that told the model a
    different path than `DispatchRun.path` reports would write a file the
    viewer never looks for, and every other test here would still pass."""
    await _seed_topic(service, dispatcher, fake_model, project_id, "How does spacing work?")
    [view] = await topic_reader.list_topics()

    seen = []
    original = fake_model._agenerate

    async def capture(messages, *args, **kwargs):
        seen.append(messages)
        return await original(messages, *args, **kwargs)

    fake_model._agenerate = capture  # type: ignore[method-assign]
    fake_model.responses = [AIMessage(content="done", id="a1")]

    await dispatcher.dispatch(project_id, view.summary.topic_id)

    [messages] = seen
    sent = "\n".join(
        message.content
        for message in messages
        if isinstance(getattr(message, "content", None), str)
    )
    assert UNDERSTANDING_PROMPT in sent
    assert "How does spacing work?" in sent
    assert understanding_path(0, "How does spacing work?") in sent


async def test_a_second_dispatch_overwrites_rather_than_writing_a_second_file(
    dispatcher, service, fake_model, project_id, topic_reader
):
    """Decided deliberately: the filesystem is event-sourced, so every prior
    version is already recoverable by scrubbing, and `understanding-2.md`
    would be a second mechanism for history that already exists. Reversible
    if the owner disagrees -- this test is where it would be reversed."""
    await _seed_topic(service, dispatcher, fake_model, project_id, "How does spacing work?")
    [view] = await topic_reader.list_topics()
    path = understanding_path(0, "How does spacing work?")

    fake_model.responses = [_writes(path, "first"), AIMessage(content="ok", id="a2")]
    await dispatcher.dispatch(project_id, view.summary.topic_id)

    fake_model.responses = [
        _writes(path, "second", call_id="w2"),
        AIMessage(content="ok", id="a3"),
    ]
    await dispatcher.dispatch(project_id, view.summary.topic_id)

    files = await service.project_files(project_id)
    assert [name for name in files if name.startswith("/topics/")] == [path]
    assert files[path]["content"] == "second"


async def test_a_dispatch_releases_the_project_even_when_the_turn_fails(
    dispatcher, service, fake_model, project_id, topic_reader
):
    """A dispatch that died holding the project would lock out every later
    dispatch, turn and seed -- and unlike a seed, dispatches are queued
    behind each other, so the whole queue stalls with it."""
    await _seed_topic(service, dispatcher, fake_model, project_id, "How does spacing work?")
    [view] = await topic_reader.list_topics()

    def explode(*args, **kwargs):
        raise RuntimeError("the model is unreachable")

    fake_model._agenerate = explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await dispatcher.dispatch(project_id, view.summary.topic_id)

    state = await service.project_state(project_id)
    assert state.active_session_id is None


async def test_an_unknown_topic_is_refused_before_the_project_is_joined(
    dispatcher, service, fake_model, project_id
):
    """Refused rather than dispatched at nothing. Before joining, because a
    refusal that had already taken the project would leave it held for the
    duration of a turn that was never going to run -- the same failure the
    `finally` above prevents, arrived at from the other side."""
    with pytest.raises(UnknownTopic):
        await dispatcher.dispatch(project_id, uuid4())

    state = await service.project_state(project_id)
    assert state.active_session_id is None


async def test_the_number_follows_the_topic_s_position_in_the_project_s_list(
    dispatcher, service, fake_model, project_id, topic_reader
):
    """`<nn>` orders the directory listing, and the second topic opened must
    not land on `00-` beside the first. Would pass with a hardcoded `00` if
    only one topic were ever opened, which is why two are."""
    await _seed_topic(service, dispatcher, fake_model, project_id, "First question?")

    seeder_model_responses = [
        _opens_topic("Second question?"),
        AIMessage(content="opened", id="d2"),
    ]
    from research_team.application.topic_seeding import TopicSeeder

    fake_model.responses = seeder_model_responses
    await TopicSeeder(service, TurnSupervisor(service)).seed(project_id, "more", max_topics=8)

    views = await topic_reader.list_topics()
    second = next(view for view in views if view.summary.question == "Second question?")
    position = [view.summary.topic_id for view in views].index(second.summary.topic_id)

    fake_model.responses = [AIMessage(content="done", id="a9")]
    run = await dispatcher.dispatch(project_id, second.summary.topic_id)

    assert run.path == understanding_path(position, "Second question?")
