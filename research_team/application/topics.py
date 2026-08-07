"""Topics, as the application offers them to an agent.

The port and the tool names, in the layer that owns the vocabulary. The adapter
lives in `infrastructure/agent/topic_tools.py`; nothing here names langchain.

**Only `open_topic` is a gate candidate**, and the reason is worth stating where
someone deciding tool floors will read it: an autonomous run that can create its
own work never terminates. Every other operation here records something about a
topic that already exists, which is bounded by definition. Opening one is the
single operation that grows the queue, so it is the one where a cap or a gate
belongs -- see `MAX_OPEN_TOPICS`.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

LIST_TOPICS_TOOL = "list_topics"
OPEN_TOPIC_TOOL = "open_topic"
RECORD_FINDING_TOOL = "record_finding"
LINK_SOURCE_TOOL = "link_source"

MAX_OPEN_TOPICS = 50
"""How many live topics one project may hold before `open_topic` refuses.

A cap rather than a gate, because the failure it guards against is a runaway
loop rather than a bad judgement, and a gate cannot stop something running
unattended. Fifty is generous for a course and small enough that a run inventing
work hits it in minutes rather than days.
"""


class TopicError(Exception):
    """Something a topic operation could not do, phrased for the agent.

    Carries what the model should read: an agent that is told "unknown topic"
    can list topics and retry, where a traceback teaches it nothing.
    """


@dataclass(frozen=True)
class TopicSummary:
    """One topic as a caller sees it, with why it wants attention.

    `triggers` comes from the computed queue rather than from stored state, so
    this is a view of the judgement rather than a record of one.
    """

    topic_id: UUID
    question: str
    status: str
    sources: int
    findings: int
    open_sub_questions: int
    triggers: tuple[str, ...] = ()


class TopicPort(Protocol):
    """What the agent can do with topics.

    Deliberately narrow. There is no `close_topic` here: deciding that a
    question is answered or not worth pursuing is a judgement with a required
    justification, and an autonomous run that could close its own topics could
    empty its queue without answering anything -- which is the confabulated
    ending this whole design exists to prevent. Closing stays a human action.
    """

    async def list_topics(self, project_id: UUID) -> list[TopicSummary]: ...

    async def open_topic(
        self, project_id: UUID, question: str, rationale: str, scope: str = ""
    ) -> UUID: ...

    async def record_finding(
        self, topic_id: UUID, summary: str, source_ids: list[str]
    ) -> None: ...

    async def link_source(self, topic_id: UUID, source_id: str, note: str = "") -> None: ...


def format_topics(summaries: list[TopicSummary]) -> str:
    """The topic list as the agent reads it, needs-attention first.

    Leads with what wants attention and why, because the first question an agent
    asks a topic list is "what should I do next" -- a list ordered by anything
    else makes it read every line to find out.
    """
    if not summaries:
        return (
            "No topics are being tracked in this project yet. Use `open_topic` to "
            "start tracking a question worth answering."
        )
    wanting = [s for s in summaries if s.triggers]
    quiet = [s for s in summaries if not s.triggers]

    lines: list[str] = []
    if wanting:
        lines.append(f"{len(wanting)} topic(s) want attention:")
        for summary in wanting:
            lines.append(
                f"  {summary.topic_id} -- {summary.question} [{', '.join(summary.triggers)}]"
            )
    if quiet:
        lines.append(f"{len(quiet)} topic(s) are quiet:")
        for summary in quiet:
            lines.append(f"  {summary.topic_id} -- {summary.question} ({summary.status})")
    return "\n".join(lines)


TOPICS_PROMPT = (
    "\n\nThis project tracks **topics**: questions it is trying to answer, each "
    "with the sources that bear on it and what has been learned so far.\n\n"
    "`list_topics` shows what is tracked and which topics want attention, with "
    "the reason each was raised -- a dropped source, material arriving that the "
    "topic has not considered, an open sub-question. Work those reasons; they "
    "are computed from the log, not guessed.\n\n"
    "`record_finding` is how something learned becomes part of the record, and "
    "`link_source` attaches a corpus document to the topic it bears on. A round "
    "that reads a great deal and records nothing has produced nothing -- the "
    "system measures progress in findings and links, not in what was said "
    "about them.\n\n"
    "`open_topic` starts tracking a new question and requires a rationale. Open "
    "one when you find a question worth answering that nothing is tracking yet. "
    "Do not open topics to look busy: an unanswered question you invented is "
    "worse than none, because it makes the queue longer without making the "
    "project better understood."
)
