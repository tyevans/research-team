"""The topic tools, as the agent meets them.

Every tool answers in prose the model can act on, including when it fails: an
unknown id, a blank rationale and a full project all come back as sentences
naming the remedy, because a traceback teaches a model nothing and a bare
refusal teaches it to retry the same call.

The cap on `open_topic` gets its own test. It is the one operation that grows
the queue, and an autonomous run that can create its own work never terminates
-- so the limit is load-bearing rather than defensive.
"""

from uuid import UUID, uuid4

import pytest

from research_team.application.topics import (
    MAX_OPEN_TOPICS,
    TopicError,
    TopicSummary,
    format_topics,
)
from research_team.infrastructure.agent.topic_tools import build_topic_tools


class FakeTopics:
    """The port, with everything in memory."""

    def __init__(self, summaries=(), live=0):
        self.summaries = list(summaries)
        self.live = live
        self.opened: list[tuple[str, str]] = []
        self.findings: list[tuple[UUID, str, list[str]]] = []
        self.links: list[tuple[UUID, str]] = []
        self.known: set[UUID] = set()

    async def list_topics(self, project_id):
        return self.summaries

    async def open_topic(self, project_id, question, rationale, scope=""):
        if self.live >= MAX_OPEN_TOPICS:
            raise TopicError(
                f"this project already tracks {self.live} live topics, which is the "
                f"limit ({MAX_OPEN_TOPICS}). Answer or close some before opening more."
            )
        self.opened.append((question, rationale))
        topic_id = uuid4()
        self.known.add(topic_id)
        return topic_id

    async def record_finding(self, topic_id, summary, source_ids):
        if topic_id not in self.known:
            raise TopicError(f"no topic {topic_id} in this project. Use `list_topics`.")
        self.findings.append((topic_id, summary, list(source_ids)))

    async def link_source(self, topic_id, source_id, note=""):
        if topic_id not in self.known:
            raise TopicError(f"no topic {topic_id} in this project. Use `list_topics`.")
        self.links.append((topic_id, source_id))


def tools_for(port):
    return {tool.name: tool for tool in build_topic_tools(port, uuid4())}


# ---------------- listing ----------------


async def test_an_empty_project_says_so_and_names_the_next_step():
    tools = tools_for(FakeTopics())

    answer = await tools["list_topics"].ainvoke({})

    assert "No topics" in answer
    assert "open_topic" in answer


async def test_the_listing_leads_with_what_wants_attention_and_why():
    wanting = TopicSummary(
        topic_id=uuid4(),
        question="what is the threshold?",
        status="investigating",
        sources=1,
        findings=0,
        open_sub_questions=1,
        triggers=("topic.unanswered",),
    )
    quiet = TopicSummary(
        topic_id=uuid4(),
        question="settled?",
        status="answered",
        sources=3,
        findings=2,
        open_sub_questions=0,
    )

    answer = format_topics([quiet, wanting])

    assert answer.index("want attention") < answer.index("are quiet")
    assert "topic.unanswered" in answer


# ---------------- opening ----------------


async def test_opening_a_topic_records_the_question_and_rationale():
    port = FakeTopics()
    tools = tools_for(port)

    answer = await tools["open_topic"].ainvoke(
        {"question": "what is the threshold?", "rationale": "two SMEs disagreed"}
    )

    assert port.opened == [("what is the threshold?", "two SMEs disagreed")]
    assert "Tracking" in answer


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"question": "  ", "rationale": "r"}, "question"),
        ({"question": "q?", "rationale": "  "}, "rationale"),
    ],
    ids=["blank-question", "blank-rationale"],
)
async def test_an_incomplete_topic_is_refused_in_words_the_model_can_act_on(args, expected):
    port = FakeTopics()

    answer = await tools_for(port)["open_topic"].ainvoke(args)

    assert expected in answer
    assert "Nothing was opened" in answer
    assert port.opened == []


async def test_the_cap_stops_a_run_from_manufacturing_its_own_work():
    """The runaway backstop. A loop that can open topics forever never ends."""
    port = FakeTopics(live=MAX_OPEN_TOPICS)

    answer = await tools_for(port)["open_topic"].ainvoke(
        {"question": "another?", "rationale": "because"}
    )

    assert str(MAX_OPEN_TOPICS) in answer
    assert port.opened == []


# ---------------- recording ----------------


async def test_recording_a_finding_cites_its_sources():
    port = FakeTopics()
    tools = tools_for(port)
    topic_id = await port.open_topic(uuid4(), "q?", "r")

    answer = await tools["record_finding"].ainvoke(
        {
            "topic_id": str(topic_id),
            "summary": "the threshold is 24h for tier 1",
            "source_ids": ["s1", "s2"],
        }
    )

    assert port.findings == [(topic_id, "the threshold is 24h for tier 1", ["s1", "s2"])]
    assert "s1" in answer


async def test_a_finding_without_a_summary_is_refused():
    port = FakeTopics()
    topic_id = await port.open_topic(uuid4(), "q?", "r")

    answer = await tools_for(port)["record_finding"].ainvoke(
        {"topic_id": str(topic_id), "summary": "   ", "source_ids": []}
    )

    assert "summary" in answer
    assert port.findings == []


async def test_linking_a_source_attaches_it():
    port = FakeTopics()
    tools = tools_for(port)
    topic_id = await port.open_topic(uuid4(), "q?", "r")

    await tools["link_source"].ainvoke({"topic_id": str(topic_id), "source_id": "s1"})

    assert port.links == [(topic_id, "s1")]


# ---------------- bad input ----------------


def _args_for(tool_name: str, topic_id: str) -> dict:
    """The full argument set each tool requires, with `topic_id` varied.

    Spelled out per tool rather than filtered from a shared dict: the shared
    version silently dropped a required field and the tool refused on *that*
    instead of on the id, which is the failure these tests exist to catch.
    """
    if tool_name == "record_finding":
        return {"topic_id": topic_id, "summary": "x", "source_ids": []}
    return {"topic_id": topic_id, "source_id": "s1"}


@pytest.mark.parametrize("tool_name", ["record_finding", "link_source"])
async def test_something_that_is_not_an_id_is_answered_rather_than_raised(tool_name):
    """A model will sometimes hand back a question where an id belongs."""
    tools = tools_for(FakeTopics())

    answer = await tools[tool_name].ainvoke(_args_for(tool_name, "the threshold one"))

    assert "not a topic id" in answer
    assert "list_topics" in answer


@pytest.mark.parametrize("tool_name", ["record_finding", "link_source"])
async def test_an_unknown_topic_names_the_remedy(tool_name):
    tools = tools_for(FakeTopics())

    answer = await tools[tool_name].ainvoke(_args_for(tool_name, str(uuid4())))

    assert "list_topics" in answer


async def test_there_is_no_tool_for_closing_a_topic():
    """Deciding a question is answered is a judgement with a justification.

    A run that could close its own topics could empty its queue without
    answering anything, which is the confabulated ending the whole design
    exists to prevent.
    """
    names = set(tools_for(FakeTopics()))

    assert not {name for name in names if "close" in name or "status" in name}
