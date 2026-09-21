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
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.research.domain.topic import (
    AcknowledgeTrigger,
    AddSubQuestion,
    LinkEntity,
    LinkSource,
    OpenTopic,
    RecordContest,
    RecordFinding,
    RecordGap,
    RecordInvestigation,
    ResolveContest,
    ResolveSubQuestion,
    RestateTopicQuestion,
    SetTopicStatus,
    Topic,
    TopicStatus,
    UnlinkSource,
)

LIST_TOPICS_TOOL = "list_topics"
OPEN_TOPIC_TOOL = "open_topic"
RESTATE_QUESTION_TOOL = "restate_question"
RECORD_FINDING_TOOL = "record_finding"
RECORD_GAP_TOOL = "record_gap"
LINK_SOURCE_TOOL = "link_source"

MAX_OPEN_TOPICS = 50
"""How many live topics one project may hold before `open_topic` refuses.

A cap rather than a gate, because the failure it guards against is a runaway
loop rather than a bad judgement, and a gate cannot stop something running
unattended. Fifty is generous for a course and small enough that a run inventing
work hits it in minutes rather than days.
"""


SELF_CONTAINED_QUESTION = (
    "**A topic question must be self-contained.** It is read later by an agent "
    "that is handed the question and nothing else -- no project, no heading, no "
    "conversation it came from -- and by a person reading a file name. Write "
    "every question so it names its own subject.\n\n"
    "The failure looks like this. Asked to open topics for a project about the "
    "Nova Scotia Duck Tolling Retriever, a topic opened as `typical physical "
    "traits` is useless: physical traits of *what*? Opened as `What are the "
    "typical physical traits of a Nova Scotia Duck Tolling Retriever?` it is "
    "answerable by someone who has never seen this project. The subject is "
    "obvious to you right now and invisible to everyone downstream, which is "
    "exactly why it gets left out."
)
"""What `open_topic` requires of a question, stated as a failure rather than a virtue.

"Be specific" and "be descriptive" are what this prompt used to say by
implication, and a model satisfies them without naming the subject once: a list
written under a `Subject:` heading does not repeat the heading, because in the
context that produced it the heading is right there. The elision is a property
of the shape, not of any one model -- Gemma 4 exposed it where Qwen 3.6 happened
to hide it.

The cost of the example is roughly ninety tokens on every project-joined
session's system prompt, paid whether or not the session opens a topic. That is
the price of the instruction being *checkable* by the model against its own
output; the abstract version is not, which is how it was followed and violated
at the same time.

Lives here rather than in `topic_seeding.py` because seeding is not the only
caller of `open_topic` -- an autonomous round opens topics mid-run and never
sees the seeding prompt. `TOPICS_PROMPT` below is appended exactly where
`build_topic_tools` binds the tool, so this arrives with the tool and with
nothing else: an instruction reaches a prompt when the tool it governs does,
so a turn with no topic tool is not carrying rules for one.
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

    async def restate_question(
        self, topic_id: UUID, question: str, rationale: str = ""
    ) -> None: ...

    async def record_finding(
        self, topic_id: UUID, summary: str, source_ids: list[str]
    ) -> None: ...

    async def record_gap(self, topic_id: UUID, looking_for: str, tried: list[str]) -> None:
        """Record a search that came back empty.

        Must not change `TopicStatus` and must not emit `TopicTriggerAcknowledged`.
        A gap is a record of absence, not a verdict -- the only thing an agent may
        conclude from having looked and found nothing is that it looked and found
        nothing. Closing the topic or silencing the trigger that raised it would be
        `close_topic` arriving by a side door, which is the ending this whole
        design exists to prevent (see the class docstring above)."""
        ...

    async def link_source(self, topic_id: UUID, source_id: str, note: str = "") -> None: ...


class TopicService:
    """Application service managing the lifecycle of project topics.

    Coordinates command execution against the Topic aggregate repository and
    provides a unified domain interface for web routes, CLI, and internal services.
    """

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def open_topic(
        self,
        project_id: UUID,
        question: str,
        rationale: str,
        scope: str = "",
        *,
        topic_id: UUID | None = None,
    ) -> UUID:
        assigned_id = topic_id or uuid4()
        if hasattr(self._repository, "create_new"):
            topic = self._repository.create_new(assigned_id)
        else:
            topic = Topic(assigned_id)
        topic.execute(
            OpenTopic(
                topic_id=assigned_id,
                project_id=project_id,
                question=question,
                rationale=rationale,
                scope=scope,
            )
        )
        await self._repository.save(topic)
        return assigned_id

    async def restate_question(
        self, topic_id: UUID, question: str, rationale: str = ""
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(RestateTopicQuestion(question=question, rationale=rationale))
        await self._repository.save(topic)

    async def set_status(
        self, topic_id: UUID, to_status: TopicStatus, justification: str
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(SetTopicStatus(to_status=to_status, justification=justification))
        await self._repository.save(topic)

    async def add_sub_question(self, topic_id: UUID, key: str, question: str) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(AddSubQuestion(key=key, question=question))
        await self._repository.save(topic)

    async def resolve_sub_question(self, topic_id: UUID, key: str, answer: str) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(ResolveSubQuestion(key=key, answer=answer))
        await self._repository.save(topic)

    async def link_source(
        self, topic_id: UUID, source_id: str, relation: str = "supports", note: str = ""
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(LinkSource(source_id=source_id, relation=relation, note=note))
        await self._repository.save(topic)

    async def unlink_source(self, topic_id: UUID, source_id: str, reason: str) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(UnlinkSource(source_id=source_id, reason=reason))
        await self._repository.save(topic)

    async def link_entity(self, topic_id: UUID, entity_id: str, name: str = "") -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(LinkEntity(entity_id=entity_id, name=name))
        await self._repository.save(topic)

    async def record_finding(
        self, topic_id: UUID, summary: str, source_ids: list[str]
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(RecordFinding(summary=summary, source_ids=source_ids))
        await self._repository.save(topic)

    async def record_gap(self, topic_id: UUID, looking_for: str, tried: list[str]) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(RecordGap(looking_for=looking_for, tried=tried))
        await self._repository.save(topic)

    async def record_investigation(
        self,
        topic_id: UUID,
        at_position: str,
        summary: str = "",
        by_run_id: UUID | None = None,
        outcome: str | None = None,
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(
            RecordInvestigation(
                at_position=at_position,
                summary=summary,
                by_run_id=by_run_id,
                outcome=outcome,
            )
        )
        await self._repository.save(topic)

    async def record_contest(
        self, topic_id: UUID, key: str, nature: str, source_ids: list[str]
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(RecordContest(key=key, nature=nature, source_ids=source_ids))
        await self._repository.save(topic)

    async def resolve_contest(
        self, topic_id: UUID, key: str, resolution: str, justification: str
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(
            ResolveContest(key=key, resolution=resolution, justification=justification)
        )
        await self._repository.save(topic)

    async def acknowledge_trigger(
        self, topic_id: UUID, trigger: str, reason: str, until_position: str
    ) -> None:
        topic = await self._repository.load(topic_id)
        topic.execute(
            AcknowledgeTrigger(trigger=trigger, reason=reason, until_position=until_position)
        )
        await self._repository.save(topic)


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
    "project better understood.\n\n"
    "`restate_question` clarifies or re-frames a question whose current wording "
    "is too broad, too narrow, or misdirected. State the new self-contained "
    "question and provide a rationale explaining why the rephrasing is better.\n\n"
    "`record_gap` is for when you looked and found nothing: say what an answer "
    "would have looked like and what you actually tried. A gap is not a way to "
    "close a question -- the topic stays open and stays in the queue. What a "
    "gap does is stop the next session repeating your searches. Recording "
    "nothing when you found nothing is the thing that costs later work.\n\n"
    + SELF_CONTAINED_QUESTION
)
