"""`TopicReadPort`, behind the topic projection and the aggregate repository.

Two backing stores, not one, because the two calls need different things from
the log. `list_topics` reads the projection -- `TopicRunner` -- for the reason
`RepositoryTopics.list_topics` already does: answering it from streams would
replay every topic in the project per call. `read_topic` loads the aggregate
instead, through `AggregateRepository[Topic]`, because a single topic's page
needs the finding text the projection deliberately does not carry (see
`TopicRow` on why) -- so it goes to the one place that does, the event log for
that one stream.

Attention for both calls comes from `attention_for`, but never by building a
`CorpusFacts` here. `TopicQueue.evaluate` already builds one per call and
`TopicRunner.corpus_facts` is that same read exposed; taking it as a
constructor argument rather than reaching into the runner's queue keeps this
class testable against a fake without a running projection, and keeps there
being exactly one place a `CorpusFacts` gets assembled.

The project is bound once, at construction, for the reason `ProjectCorpusReader`
gives at length: a caller that could pass a different project id is a caller
that could read another project's topics, and `read_topic`'s guard against a
foreign topic id is what actually closes that gap for the one call where the
id alone cannot be trusted.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.domain.exceptions import AggregateNotFoundError

from research_team.application.topic_attention import CorpusFacts, attention_for
from research_team.application.topic_read import (
    SubQuestionView,
    TopicDetail,
    TopicView,
)
from research_team.application.topics import TopicSummary
from research_team.domain.topic import Topic, TopicFindingRecorded
from research_team.infrastructure.persistence.topics import TopicRunner


class ProjectTopicReader:
    """`TopicReadPort` over `TopicRunner` and `AggregateRepository[Topic]`, fixed to one
    project."""

    def __init__(
        self,
        queue: TopicRunner,
        repository: AggregateRepository[Topic],
        corpus_facts: Callable[[UUID], Awaitable[CorpusFacts]],
        project_id: UUID,
    ) -> None:
        self._queue = queue
        self._repository = repository
        self._corpus_facts = corpus_facts
        self._project_id = project_id

    async def list_topics(self) -> list[TopicView]:
        rows = await self._queue.list(self._project_id)
        facts = await self._corpus_facts(self._project_id)
        at_position = await self._queue.queue.high_water(self._project_id)
        views = []
        for row in rows:
            state = row.to_state()
            attention = attention_for(state, facts, at_position=at_position)
            views.append(TopicView(summary=_summary(state, attention), attention=attention))
        return views

    async def read_topic(self, topic_id: UUID) -> TopicDetail | None:
        # The repository raises for a stream with no events at all, which is
        # an ordinary "never opened" for this port, not a failure -- a model
        # or a browser guessing at an id is the expected case, and the answer
        # to it is the same `None` a foreign project id gets below.
        try:
            topic = await self._repository.load(topic_id)
        except AggregateNotFoundError:
            return None
        state = topic.state
        # Checking `project_id` alongside the fold's own "never opened" is the
        # guard this reader owns: an id that belongs to a different project
        # must read the same as one that does not exist at all, or a caller
        # could tell the two apart.
        if state.topic_id is None or state.project_id != self._project_id:
            return None

        facts = await self._corpus_facts(self._project_id)
        at_position = await self._queue.queue.high_water(self._project_id)
        attention = attention_for(state, facts, at_position=at_position)
        view = TopicView(summary=_summary(state, attention), attention=attention)

        sub_questions = tuple(
            SubQuestionView(key=key, question=sub.question, answer=sub.answer)
            for key, sub in state.sub_questions.items()
        )
        # `TopicState` folds finding *count*, never text -- see `TopicRow` on
        # why. Recovering the summaries a detail page shows means reading the
        # stream directly, the same way `events_for` does on the session
        # repository.
        stream = StreamId(topic_id, Topic.aggregate_type)
        envelopes = await collect(self._repository.event_store.read_stream(stream))
        events = [envelope.event for envelope in envelopes]
        findings = tuple(
            event.summary for event in events if isinstance(event, TopicFindingRecorded)
        )

        return TopicDetail(
            view=view,
            rationale=state.rationale,
            scope=state.scope,
            sub_questions=sub_questions,
            source_ids=tuple(state.source_ids),
            findings=findings,
            contested=bool(state.unresolved_contests),
        )


def _summary(state, attention) -> TopicSummary:
    """`TopicSummary` off a fold, the same shape `RepositoryTopics.list_topics` builds.

    A free function rather than a method: both call sites here build it from a
    `TopicState`, one folded by the projection and one folded by the
    aggregate, and the two must agree on what a summary is -- which a single
    function guarantees and two method bodies would only promise.
    """
    return TopicSummary(
        topic_id=state.topic_id,
        question=state.question,
        status=state.status,
        sources=len(state.source_ids),
        findings=state.findings,
        open_sub_questions=len(state.open_sub_questions),
        triggers=attention.triggers,
    )
