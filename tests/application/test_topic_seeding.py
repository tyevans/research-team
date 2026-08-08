"""Seeding: one turn that names a project's first topics, not a run.

Exercised end to end through `build_applications`, the same way
`test_session_service_project.py` drives `start_in_project` /
`release_project` -- a fake model stands in for the agent, and a real
`TopicReadPort` reads back what actually reached the log, not what the
seeder claims it did.
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from research_team.application import TurnSupervisor
from research_team.application.topic_seeding import SEEDING_PROMPT, TopicSeeder
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
def seeder(service):
    return TopicSeeder(service, TurnSupervisor(service))


def _opens_topic(question: str, rationale: str = "core") -> AIMessage:
    """A model turn that opens one topic and then stops, the way a real
    seeding turn ends: a tool call, then a plain reply with nothing left to
    do."""
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


async def test_seeding_opens_the_topics_the_model_named(
    seeder, fake_model, project_id, topic_reader
):
    fake_model.responses = [
        _opens_topic("How does spacing affect retention?"),
        AIMessage(content="opened it", id="a1"),
    ]

    await seeder.seed(project_id, "spaced repetition", max_topics=8)

    topics = await topic_reader.list_topics()
    assert [view.summary.question for view in topics] == [
        "How does spacing affect retention?"
    ]


async def test_seeding_prompts_the_agent_with_the_subject_and_the_search_rule(
    seeder, fake_model, project_id
):
    """The rule is stated as a decision procedure -- "if you cannot", not "if
    a tool is available" -- so the same instruction is correct whether or not
    `AGENT_SEARXNG_URL` is configured. This asserts the wording actually
    reaches the model rather than paraphrasing it in the seeder."""
    seen = []
    original = fake_model._agenerate

    async def capture(messages, *args, **kwargs):
        seen.append(messages)
        return await original(messages, *args, **kwargs)

    fake_model._agenerate = capture  # type: ignore[method-assign]
    fake_model.responses = [AIMessage(content="done", id="a1")]

    await seeder.seed(project_id, "spaced repetition", max_topics=8)

    [messages] = seen
    sent = "\n".join(message.content for message in messages if hasattr(message, "content"))
    assert SEEDING_PROMPT in sent
    assert "spaced repetition" in sent


async def test_seeding_releases_the_project_even_when_the_turn_fails(
    seeder, fake_model, service, project_id
):
    """A seeding run that died holding the project would lock out every later
    one, and the failure is seconds old with nothing to show for it."""

    def explode(*args, **kwargs):
        raise RuntimeError("the model is unreachable")

    fake_model._agenerate = explode  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await seeder.seed(project_id, "anything", max_topics=8)

    state = await service.project_state(project_id)
    assert state.active_session_id is None


async def test_seeding_lets_a_later_seed_join_the_same_project(
    seeder, fake_model, project_id, topic_reader
):
    """Release is unconditional, not just on the failure path: two seed calls
    in a row must not deadlock the second behind the first."""
    fake_model.responses = [AIMessage(content="done", id="a1")]
    await seeder.seed(project_id, "first pass", max_topics=8)

    fake_model.responses = [
        _opens_topic("second question"),
        AIMessage(content="opened it", id="a2"),
    ]
    await seeder.seed(project_id, "second pass", max_topics=8)

    topics = await topic_reader.list_topics()
    assert [view.summary.question for view in topics] == ["second question"]
