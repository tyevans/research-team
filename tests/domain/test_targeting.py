"""A mistargeted creation command is refused, by the library rather than by us.

`ChecksCommandTarget` used to reject the command before `decide` ran. eventsource
0.14.0 rejects the *event* instead, in `_reject_foreign_aggregate_id`, so the
mixin was deleted. That substitution is only sound where the aggregate's `decide`
stamps the creation event's `aggregate_id` from the **command** -- the library
never sees the command's target field, only what the event carries.

So there is one test per aggregate rather than one for the family. All five were
read and all five stamp from the command (each says so in a comment, because on a
fresh aggregate the state's id is still None), but "the library catches this for
`Corpus`" is not evidence about `Topic`: each has its own creation command and
its own `decide`. An aggregate that quietly stamped from `state` would lose the
check silently, which is the entire failure this file guards.

The assertions stop at the exception type, the foreign id and the command name.
The full wording is the library's to change.
"""

from uuid import uuid4

import pytest
from eventsource import AggregateIdMismatchError

from research_team.domain.auto_research import AutoResearchRun, StartRun
from research_team.domain.commands import StartSession
from research_team.domain.corpus import Corpus, StoreSourceDocument
from research_team.domain.project import CreateProject, Project
from research_team.domain.session import CodingSession
from research_team.domain.topic import OpenTopic, Topic


def test_a_project_refuses_a_command_naming_another_project() -> None:
    """`CreateProject.project_id` reaches `ProjectCreated.aggregate_id` (project.py:259)."""
    theirs = uuid4()
    project = Project(uuid4())

    with pytest.raises(AggregateIdMismatchError) as caught:
        project.execute(CreateProject(project_id=theirs, name="theirs"))

    assert str(theirs) in str(caught.value)
    assert "CreateProject" in str(caught.value)


def test_a_session_refuses_a_command_naming_another_session() -> None:
    """`StartSession.session_id` reaches `SessionStarted.aggregate_id` (session.py:138)."""
    theirs = uuid4()
    session = CodingSession(uuid4())

    with pytest.raises(AggregateIdMismatchError) as caught:
        session.execute(
            StartSession(
                session_id=theirs,
                system_prompt="p",
                model_name="m",
                project_id=uuid4(),
            )
        )

    assert str(theirs) in str(caught.value)
    assert "StartSession" in str(caught.value)


def test_an_auto_research_run_refuses_a_command_naming_another_run() -> None:
    """`StartRun.run_id` reaches `AutoRunStarted.aggregate_id` (auto_research.py:331)."""
    theirs = uuid4()
    run = AutoResearchRun(uuid4())

    with pytest.raises(AggregateIdMismatchError) as caught:
        run.execute(StartRun(run_id=theirs, project_id=uuid4(), session_id=uuid4()))

    assert str(theirs) in str(caught.value)
    assert "StartRun" in str(caught.value)


def test_a_corpus_refuses_a_command_naming_another_corpus() -> None:
    """`StoreSourceDocument.corpus_id` reaches `CorpusDocumentStored` (corpus.py:168)."""
    theirs = uuid4()
    corpus = Corpus(uuid4())

    with pytest.raises(AggregateIdMismatchError) as caught:
        corpus.execute(StoreSourceDocument(corpus_id=theirs, source_id="s1", text="hello"))

    assert str(theirs) in str(caught.value)
    assert "StoreSourceDocument" in str(caught.value)


def test_a_topic_refuses_a_command_naming_another_topic() -> None:
    """`OpenTopic.topic_id` reaches `TopicOpened.aggregate_id` (topic.py:477)."""
    theirs = uuid4()
    topic = Topic(uuid4())

    with pytest.raises(AggregateIdMismatchError) as caught:
        topic.execute(
            OpenTopic(topic_id=theirs, project_id=uuid4(), question="q?", rationale="r")
        )

    assert str(theirs) in str(caught.value)
    assert "OpenTopic" in str(caught.value)
