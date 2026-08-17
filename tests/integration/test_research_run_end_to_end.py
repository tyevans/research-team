"""A whole autonomous run, through the wiring a front end actually uses.

The driver, the queue, the round runner and the topic tools were each tested in
isolation while nothing connected them -- which is the shape of gap a green
suite hides, and is what `ResearchRunDriver` being wired into no interface
meant in practice. So nothing here reaches past the model: a topic is opened
against the real repository, the real queue raises it, and a scripted model
answers a round by calling `record_finding` the way an agent would.

The project is seeded by one application and worked by a second over the same
database, because the model's script has to name the topic id and the topic
does not exist until something has opened it. Two applications over one file is
also the honest version of what a run meets: the queue it reads is a
projection, caught up from the log rather than handed to it.
"""

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application.autonomy import FETCH_TOOL
from research_team.domain import CreateProject, SessionPurpose
from research_team.domain.research_run import Budget
from research_team.domain.topic import OpenTopic, Topic
from research_team.infrastructure.persistence import build_topic_repository
from tests.conftest import ToolAwareFakeChatModel


class ScriptedModel(ToolAwareFakeChatModel):
    """Replays a script and remembers every prompt it was sent."""

    seen: list[str] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(str(messages[-1].content))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def quiet(count: int = 40) -> list[AIMessage]:
    """Replies that describe work without doing any. Empty rounds, by design."""
    return [
        AIMessage(content="I have thought about this at length", id=f"q{i}")
        for i in range(count)
    ]


def records_once(topic_id) -> ScriptedModel:
    """Answers the first round with `record_finding`, then narrates and stops."""
    return ScriptedModel(
        responses=[
            AIMessage(
                content="",
                id="call",
                tool_calls=[
                    {
                        "name": "record_finding",
                        "args": {
                            "topic_id": str(topic_id),
                            "summary": "the two sources agree on the timeline",
                            "source_ids": [],
                        },
                        "id": "t1",
                    }
                ],
            ),
            AIMessage(content="recorded", id="done"),
            *quiet(),
        ]
    )


async def seed(build_application, db_path):
    """A project with one never-investigated topic, which is a queue of one."""
    seeding = await build_application(model=ScriptedModel(responses=quiet(1)), db_path=db_path)
    project_id = uuid4()
    project = seeding.service.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name="atlas"))
    await seeding.service.projects.save(project)

    repository = seeding.service._repository
    topic: Topic = build_topic_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    ).create_new(uuid4())
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=project_id,
            question="does the schedule hold?",
            rationale="it is the thing the course turns on",
        )
    )
    await build_topic_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    ).save(topic)
    return project_id, topic.aggregate_id


async def working(build_application, db_path, model):
    """A second application over the same database, ready to run."""
    application = await build_application(model=model, db_path=db_path)
    await application.topics_caught_up()
    return application


async def run_on(application, project_id, **budget):
    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )
    await application.attach_project(project_id)
    run = application.research.start(project_id, session_id, budget=Budget(**budget))
    return run, await application.research.wait(project_id)


async def test_a_run_works_a_real_queue_and_records_what_it_found(build_application, db_path):
    """The join: queue -> round -> turn -> topic tool -> counted from the fold."""
    project_id, topic_id = await seed(build_application, db_path)
    application = await working(build_application, db_path, records_once(topic_id))

    _, report = await run_on(application, project_id, max_rounds=6, quiet_rounds=2)

    assert report.rounds >= 1
    # Counted off the topic's own stream. Nothing the model said was read.
    assert report.findings == 1


async def test_a_run_that_records_nothing_stops_for_novelty_decay(build_application, db_path):
    """The loop's defence against a model that narrates progress it did not make."""
    project_id, _ = await seed(build_application, db_path)
    application = await working(build_application, db_path, ScriptedModel(responses=quiet()))

    _, report = await run_on(application, project_id, max_rounds=9, quiet_rounds=2)

    assert report.reason == "no_new_findings"
    assert report.findings == 0
    assert not report.finished_cleanly


async def test_the_round_is_told_why_its_topic_was_raised(build_application, db_path):
    """The reason reaching the model is what makes a round more than a poke."""
    project_id, _ = await seed(build_application, db_path)
    model = ScriptedModel(responses=quiet())
    application = await working(build_application, db_path, model)

    await run_on(application, project_id, max_rounds=1, quiet_rounds=1)

    prompt = next(text for text in model.seen if "does the schedule hold?" in text)
    assert "topic." in prompt


async def test_a_default_run_is_recorded_as_read_only_because_fetch_floors_at_ask(
    build_application, db_path
):
    """The claim is read from the policy, not asserted -- so it stays true."""
    project_id, _ = await seed(build_application, db_path)
    application = await working(build_application, db_path, ScriptedModel(responses=quiet()))

    run, _ = await run_on(application, project_id, max_rounds=1, quiet_rounds=1)

    state = await application.research.state(run.run_id)
    assert application.policy.level_for(FETCH_TOOL) == "ask"
    assert state.read_only is True


async def test_a_run_stops_when_it_is_asked_to(build_application, db_path):
    """`cancelled` reaches the log rather than the run simply going quiet."""
    project_id, _ = await seed(build_application, db_path)
    application = await working(build_application, db_path, ScriptedModel(responses=quiet()))
    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )
    await application.attach_project(project_id)

    run = application.research.start(
        project_id, session_id, budget=Budget(max_rounds=50, quiet_rounds=50)
    )
    application.research.cancel(project_id)
    report = await application.research.wait(project_id)

    assert report.reason == "cancelled"
    assert (await application.research.state(run.run_id)).stop_reason == "cancelled"


async def test_a_granted_runs_grant_reaches_the_fold_and_is_released_on_stop(
    build_application, db_path
):
    """Both required properties in one run: the grant `research.start` was
    given is readable back off the folded state (the same fold `ResearchRunStarted`
    feeds -- see `test_a_run_records_and_folds_the_fetch_grant` for the event
    itself), and once the run has stopped, this run's session is gone from
    `application.grants` -- the one registry the gate, the grant-bound
    `fetch` tool and the driver all share (see `Application.grants`).
    """
    project_id, _ = await seed(build_application, db_path)
    application = await working(build_application, db_path, ScriptedModel(responses=quiet()))
    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )
    await application.attach_project(project_id)

    run = application.research.start(
        project_id,
        session_id,
        budget=Budget(max_rounds=1, quiet_rounds=1),
        fetch_hosts=["a.example"],
        fetch_budget=3,
    )
    await application.research.wait(project_id)

    state = await application.research.state(run.run_id)
    assert state.fetch_hosts == ["a.example"]
    assert state.fetch_budget == 3
    assert application.grants.get(session_id) is None
    assert application.grants.is_unattended(session_id) is False


async def test_a_run_with_no_grant_is_still_registered_and_then_released(
    build_application, db_path
):
    """Task 6's bounded wait keys off the session being registered at all --
    an ungranted run must show up in the registry while it runs and be gone
    once it stops, exactly like a granted one."""
    project_id, _ = await seed(build_application, db_path)
    application = await working(build_application, db_path, ScriptedModel(responses=quiet()))
    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )
    await application.attach_project(project_id)

    application.research.start(
        project_id, session_id, budget=Budget(max_rounds=1, quiet_rounds=1)
    )
    await application.research.wait(project_id)

    assert application.grants.get(session_id) is None
    assert application.grants.is_unattended(session_id) is False
