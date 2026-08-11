"""Topics, as five tools the agent can call.

Four read-or-record and one that creates. None is gated, and the asymmetry is
deliberate: `autonomy.py` argues that an approval which fires on something
nobody would refuse makes every other approval mean less, and recording what you
learned about a question this project already tracks is not a decision anyone
would stop. That includes `record_gap`: a record of failure is not a hazard, and
gating it would discourage the honesty it collects.

`open_topic` is the one that grows the queue, and it is capped rather than
gated -- see `MAX_OPEN_TOPICS`. A cap works unattended; a gate does not, and the
failure being guarded against is precisely a run with nobody watching it.
"""

from uuid import UUID, uuid4

from langchain_core.tools import BaseTool, tool

from research_team.application.retry import with_retry
from research_team.application.topics import (
    LINK_SOURCE_TOOL,
    LIST_TOPICS_TOOL,
    MAX_OPEN_TOPICS,
    OPEN_TOPIC_TOOL,
    RECORD_FINDING_TOOL,
    RECORD_GAP_TOOL,
    TopicError,
    TopicPort,
    TopicSummary,
    format_topics,
)
from research_team.domain.topic import (
    LinkSource,
    OpenTopic,
    RecordFinding,
    RecordGap,
    Topic,
)


class RepositoryTopics(TopicPort):
    """The topic port over the aggregate repository and the queue projection.

    Reads come from the projection because answering "what wants attention"
    from streams would replay every topic per call. Writes go through the
    aggregate, because the rules -- a rationale is required, a source cannot be
    unlinked twice -- live there and must not be restated here.
    """

    def __init__(self, topics, queue, project_id: UUID) -> None:
        self._topics = topics
        self._queue = queue
        self._project_id = project_id

    async def list_topics(self, project_id: UUID) -> list[TopicSummary]:
        rows = await self._queue.list(project_id)
        attention = {
            a.topic_id: a.triggers for a in await self._queue.queue.evaluate(project_id)
        }
        summaries = []
        for row in rows:
            state = row.to_state()
            summaries.append(
                TopicSummary(
                    topic_id=row.id,
                    question=row.question,
                    status=row.status,
                    sources=len(state.source_ids),
                    findings=state.findings,
                    open_sub_questions=len(state.open_sub_questions),
                    triggers=attention.get(row.id, ()),
                )
            )
        return summaries

    async def open_topic(
        self, project_id: UUID, question: str, rationale: str, scope: str = ""
    ) -> UUID:
        live = [
            row
            for row in await self._queue.list(project_id)
            if row.status in ("open", "investigating")
        ]
        if len(live) >= MAX_OPEN_TOPICS:
            # The runaway-loop backstop. Phrased as a limit rather than a
            # refusal to act, so an agent that hits it knows the remedy is to
            # answer something rather than to try again.
            raise TopicError(
                f"this project already tracks {len(live)} live topics, which is the "
                f"limit ({MAX_OPEN_TOPICS}). Answer or close some before opening more."
            )
        topic = self._topics.create_new(uuid4())
        topic.execute(
            OpenTopic(
                topic_id=topic.aggregate_id,
                project_id=project_id,
                question=question,
                rationale=rationale,
                scope=scope,
            )
        )
        await self._topics.save(topic)
        return topic.aggregate_id

    async def record_finding(
        self, topic_id: UUID, summary: str, source_ids: list[str]
    ) -> None:
        async def record() -> None:
            topic = await self._load(topic_id)
            topic.execute(RecordFinding(summary=summary, source_ids=list(source_ids)))
            await self._topics.save(topic)

        await with_retry(record, what=f"recording a finding on {topic_id}")

    async def record_gap(self, topic_id: UUID, looking_for: str, tried: list[str]) -> None:
        async def record() -> None:
            topic = await self._load(topic_id)
            topic.execute(RecordGap(looking_for=looking_for, tried=list(tried)))
            await self._topics.save(topic)

        await with_retry(record, what=f"recording a gap on {topic_id}")

    async def link_source(self, topic_id: UUID, source_id: str, note: str = "") -> None:
        """Link a source, retrying if a concurrent write to this topic wins.

        The reload is inside the retry, which matters more here than it looks:
        `decide` refuses a source already linked, so the second attempt has to
        see the winner's link to refuse correctly. A retry that replayed the
        command against the state loaded the first time would link twice.
        """

        async def link() -> None:
            topic = await self._load(topic_id)
            topic.execute(LinkSource(source_id=source_id, note=note))
            await self._topics.save(topic)

        await with_retry(link, what=f"linking {source_id!r} to {topic_id}")

    async def _load(self, topic_id: UUID) -> Topic:
        """The topic, or an error the agent can act on.

        An unknown id is an ordinary mistake for a model to make -- it may have
        invented one, or carried one across projects -- so it answers with the
        remedy rather than a traceback.
        """
        try:
            topic = await self._topics.load(topic_id)
        except Exception as error:
            raise TopicError(
                f"no topic {topic_id} in this project. Use `list_topics` to see what "
                "is tracked."
            ) from error
        if topic.state.topic_id is None:
            raise TopicError(
                f"no topic {topic_id} in this project. Use `list_topics` to see what "
                "is tracked."
            )
        return topic


def build_topic_tools(topics: TopicPort, project_id: UUID) -> tuple[BaseTool, ...]:
    """The five topic tools, bound to one project.

    Bound at construction rather than taking a project argument, for the reason
    the knowledge tools are: a project id the model can supply is a project id
    the model can get wrong, and getting it wrong here means recording a finding
    against somebody else's research.
    """

    @tool(LIST_TOPICS_TOOL)
    async def list_topics() -> str:
        """List the questions this project is tracking and which want attention."""
        return format_topics(await topics.list_topics(project_id))

    @tool(OPEN_TOPIC_TOOL)
    async def open_topic(question: str, rationale: str, scope: str = "") -> str:
        """Start tracking a question. `rationale` says why it is worth answering.

        `scope` is optional and says what would count as an answer.
        """
        if not question.strip():
            return "A topic needs a question. Nothing was opened."
        if not rationale.strip():
            return (
                "A topic needs a rationale -- why is this worth answering? Nothing was opened."
            )
        try:
            topic_id = await topics.open_topic(project_id, question, rationale, scope)
        except TopicError as error:
            return str(error)
        return f"Tracking {topic_id}: {question}"

    @tool(RECORD_FINDING_TOOL)
    async def record_finding(topic_id: str, summary: str, source_ids: list[str]) -> str:
        """Record something learned about a topic, citing the sources it came from."""
        if not summary.strip():
            return "A finding needs a summary. Nothing was recorded."
        parsed = _parse_id(topic_id)
        if parsed is None:
            return f"{topic_id!r} is not a topic id. Use `list_topics` to see them."
        try:
            await topics.record_finding(parsed, summary, source_ids or [])
        except TopicError as error:
            return str(error)
        cited = f" citing {', '.join(source_ids)}" if source_ids else ""
        return f"Recorded against {parsed}{cited}."

    @tool(RECORD_GAP_TOOL)
    async def record_gap(topic_id: str, looking_for: str, tried: list[str]) -> str:
        """Record that you looked for something and did not find it.

        `looking_for` says what an answer would have looked like; `tried` says
        what you actually searched. Does not close the topic and does not
        silence any trigger -- it only saves the next session from repeating
        your searches.
        """
        if not looking_for.strip():
            return "A gap needs to say what was looked for. Nothing was recorded."
        if not [item for item in tried if item.strip()]:
            return "A gap needs to say what was tried. Nothing was recorded."
        parsed = _parse_id(topic_id)
        if parsed is None:
            return f"{topic_id!r} is not a topic id. Use `list_topics` to see them."
        try:
            await topics.record_gap(parsed, looking_for, tried)
        except TopicError as error:
            return str(error)
        return f"Recorded a gap against {parsed}."

    @tool(LINK_SOURCE_TOOL)
    async def link_source(topic_id: str, source_id: str, note: str = "") -> str:
        """Attach a corpus document to the topic it bears on."""
        parsed = _parse_id(topic_id)
        if parsed is None:
            return f"{topic_id!r} is not a topic id. Use `list_topics` to see them."
        try:
            await topics.link_source(parsed, source_id, note)
        except TopicError as error:
            return str(error)
        return f"Linked {source_id} to {parsed}."

    return (list_topics, open_topic, record_finding, record_gap, link_source)


def _parse_id(raw: str) -> UUID | None:
    """A topic id from text, or None if it is not one.

    Returns rather than raises: the input comes from a model, which will
    sometimes hand back a question instead of an id, and that is a thing to
    answer rather than an exception to handle.
    """
    try:
        return UUID(str(raw).strip())
    except (ValueError, AttributeError, TypeError):
        return None
