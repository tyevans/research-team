"""The topic table, and the queue computed over it.

A third projection, in its own module rather than alongside the other two.
`read_models.py` is already two tables and nine hundred lines, and the split
here is by *subject* rather than by size: the `/sessions` and corpus tables
answer "what happened" and "what do we hold", and this one exists to answer
"what should be looked at next", which is a question with its own vocabulary.

**The table stores folded topic state. It does not store attention.** Every
field here comes straight off the `Topic` fold; the needs-attention judgement is
computed on read by `application.topic_attention`, from a row plus a corpus
snapshot. Storing the judgement instead would make the queue a cache with no
invalidation -- a source dropped in one project would leave every topic resting
on it looking supported until something thought to re-evaluate.

Why a table at all, then, if attention is computed anyway: answering "which
topics need attention" by replaying every topic stream costs the whole log per
question, which is the same argument that put `/sessions` in a table. The fold
is written down; the judgement over it is not.
"""

from uuid import UUID

import aiosqlite
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Query, ReadModelRepository
from eventsource.ports.readmodels.query import Filter

from research_team.infrastructure.persistence.read_models import (
    apply_schema,
)
from research_team.infrastructure.persistence.store_base import BaseProjectionRunner
from research_team.infrastructure.persistence.topic_models import (
    TOPIC_NAMESPACE,
    CorpusFactsRow,
    TopicRow,
)
from research_team.infrastructure.persistence.topic_projection import (
    TopicProjection,
    _position_text,
)
from research_team.research.application.topic_attention import (
    CorpusFacts,
    TopicAttention,
    attention_for,
    corpus_position,
)

__all__ = [
    "TOPIC_NAMESPACE",
    "CorpusFactsRow",
    "TopicProjection",
    "TopicQueue",
    "TopicRow",
    "TopicRunner",
    "TopicStore",
    "_high_water",
    "_position_text",
]


class TopicStore:
    """The topic and corpus-facts tables, and the connection they share.

    Mirrors `CorpusStore`: opening it applies both models' DDL, so there is no
    migration step to run and forget.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        topics: ReadModelRepository[TopicRow],
        facts: ReadModelRepository[CorpusFactsRow],
        projection: TopicProjection,
    ) -> None:
        self._connection = connection
        self._topics = topics
        self._facts = facts
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None, retry_policy=None
    ) -> "TopicStore":
        connection = await aiosqlite.connect(db_path)
        # `apply_schema`, not a bare `executescript` -- `CREATE TABLE IF NOT
        # EXISTS` does nothing to a table that already exists, so a field
        # added to either row type would be silently missing from every
        # database opened before the change. See its docstring for the
        # `SessionSummaryRow` incident that made this the required path for a
        # read model's DDL.
        await apply_schema(connection, TopicRow)
        await apply_schema(connection, CorpusFactsRow)
        # Every read here is by project, and the generated schema indexes only
        # `deleted_at`.
        for model in (TopicRow, CorpusFactsRow):
            await connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{model.table_name()}_project "
                f"ON {model.table_name()}(project_id)"
            )
        await connection.commit()
        topics = SQLiteReadModelRepository(connection, TopicRow, tracer)
        facts = SQLiteReadModelRepository(connection, CorpusFactsRow, tracer)
        return cls(
            connection,
            topics,
            facts,
            TopicProjection(topics, facts, checkpoint_repo, dlq_repo, tracer, retry_policy),
        )

    async def get(self, topic_id: UUID) -> TopicRow | None:
        return await self._topics.get(topic_id)

    async def list(self, project_id: UUID) -> list[TopicRow]:
        """Every topic in a project, oldest first.

        Ordered by creation so a queue built from this is stable: two
        evaluations that find the same topics equally urgent offer them in the
        same order, and an unstable order makes an idle run look like progress.
        """
        rows = await self._topics.find(
            Query(filters=[Filter(field="project_id", operator="eq", value=str(project_id))])
        )
        return sorted(rows, key=lambda row: (row.created_at, str(row.id)))

    async def corpus_facts(self, project_id: UUID) -> CorpusFacts:
        """The corpus as the attention registry wants to see it.

        One read per evaluation, shared by every trigger and every topic, so a
        whole queue is judged against a single consistent snapshot rather than
        a sequence of slightly different worlds.
        """
        rows = await self._facts.find(
            Query(filters=[Filter(field="project_id", operator="eq", value=str(project_id))])
        )
        return CorpusFacts(
            live_source_ids=frozenset(row.source_id for row in rows if not row.dropped),
            dropped_source_ids=frozenset(row.source_id for row in rows if row.dropped),
            stored_at={row.source_id: row.stored_at for row in rows},
        )

    async def truncate(self) -> None:
        for model in (TopicRow, CorpusFactsRow):
            await self._connection.execute(f"DELETE FROM {model.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class TopicQueue:
    """What to look at next, and why.

    The queue is computed, never stored. Every call re-evaluates the registry
    over the current rows, which is what makes it impossible for the queue to
    disagree with the log: there is no cached verdict to go stale.

    Ordering is by severity and then by how long a topic has waited. There is
    deliberately no priority score -- a number here would be one nobody could
    re-derive, and everyone would end up thresholding on it.
    """

    def __init__(self, store: TopicStore) -> None:
        self._store = store

    async def evaluate(self, project_id: UUID) -> list[TopicAttention]:
        """Every topic in the project that wants attention, most urgent first.

        Topics that are answered, set aside or superseded produce nothing --
        `attention_for` refuses to evaluate them, so work somebody has already
        decided not to do cannot reappear here.
        """
        rows = await self._store.list(project_id)
        facts = await self._store.corpus_facts(project_id)
        at_position = _high_water(facts)

        ranked: list[tuple[int, int, TopicAttention]] = []
        for index, row in enumerate(rows):
            attention = attention_for(row.to_state(), facts, at_position=at_position)
            if not attention.needs_attention:
                continue
            # Blocking first; then oldest first, which is the aging rule that
            # stops a steady trickle of urgent topics from starving the tail.
            ranked.append((0 if attention.is_blocked else 1, index, attention))

        ranked.sort(key=lambda item: (item[0], item[1]))
        return [attention for _, _, attention in ranked]

    async def next_topic(self, project_id: UUID) -> TopicAttention | None:
        """The single most urgent topic, or None when the queue is empty.

        An empty queue is the good ending for an autonomous run, and is the one
        stop condition that means the work is actually finished rather than
        merely stopped.
        """
        queue = await self.evaluate(project_id)
        return queue[0] if queue else None

    async def high_water(self, project_id: UUID) -> str:
        """Where this project's corpus stands, in the shared position space.

        What a caller stamps onto a look it is about to record, and what an
        acknowledgement's expiry is measured against.
        """
        return _high_water(await self._store.corpus_facts(project_id)) or corpus_position(0)


def _high_water(facts: CorpusFacts) -> str | None:
    """The furthest any source in this corpus has reached, or None if empty.

    This is "where the log stands" for acknowledgement expiry. An empty corpus
    answers None, which leaves every acknowledgement in force -- the
    conservative reading, since silencing something that should speak is a
    smaller failure than a queue nobody can quiet.
    """
    return max(facts.stored_at.values(), default=None)


class TopicRunner(BaseProjectionRunner[TopicStore]):
    """Keeps the topic tables following the log, and answers the queue from them.

    A third runner, for the reason `CorpusRunner` gives at length for being the
    second: `rebuild()` is a manual repair that stops a manager, truncates a
    table and resets a checkpoint, and two tables that can fail independently
    have to be repairable independently. Repairing the queue must not stop
    corpus reads.

    Its one projection writes *two* tables, which is the case that argument
    does not cover: the queue joins topics against a corpus snapshot on every
    evaluation, so repairing one without the other would produce a queue that
    is confidently wrong. They share a checkpoint because they share a truth --
    see `TopicProjection` for the mechanical half of that reasoning.
    """

    _label = "topic"
    _store_class = TopicStore
    _projection_class = TopicProjection

    @property
    def _topics(self) -> TopicStore | None:
        return self._store_instance

    @property
    def queue(self) -> TopicQueue:
        return TopicQueue(self.store)

    async def get(self, topic_id: UUID) -> TopicRow | None:
        return await self.store.get(topic_id)

    async def list(self, project_id: UUID) -> list[TopicRow]:
        return await self.store.list(project_id)

    async def corpus_facts(self, project_id: UUID) -> CorpusFacts:
        """The corpus snapshot `attention_for` needs, delegated to the table.

        `TopicQueue.evaluate` already reads this to judge a whole queue; a
        single-topic read needs the same snapshot to judge one topic the same
        way, and this is that read exposed rather than a second one built from
        the corpus projection -- two paths to the same `CorpusFacts` are two
        chances for them to disagree about what "live" means.
        """
        return await self.store.corpus_facts(project_id)
