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

import asyncio
import json
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    create_async_engine,
    handles,
)
from eventsource.adapters.sql.readmodel_schema import generate_full_schema
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import Query, ReadModelRepository
from eventsource.ports.readmodels.query import Filter
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.application.topic_attention import (
    CorpusFacts,
    TopicAttention,
    attention_for,
    corpus_position,
)
from research_team.domain.corpus import SourceDocumentDropped, SourceDocumentStored
from research_team.domain.topic import (
    Acknowledgement,
    Contest,
    SubQuestion,
    TopicContested,
    TopicContestResolved,
    TopicEntityLinked,
    TopicFindingRecorded,
    TopicInvestigated,
    TopicOpened,
    TopicSourceLinked,
    TopicSourceUnlinked,
    TopicState,
    TopicStatusChanged,
    TopicSubQuestionAdded,
    TopicSubQuestionResolved,
    TopicTriggerAcknowledged,
)
from research_team.infrastructure.persistence.read_models import LOCAL_RETRY_POLICY

TOPIC_NAMESPACE = UUID("2b7c1f4a-9d3e-5a71-8c62-4e0b9f1d7a35")
"""Namespace for deriving a corpus-facts row id. See `CORPUS_NAMESPACE`.

Unused for topic rows themselves, whose id *is* the topic's aggregate id -- a
topic has its own stream, so unlike a corpus document it needs no composite key.
"""


class TopicRow(ReadModel):
    """One topic's folded state. `id` is the topic's aggregate id.

    Collections are stored as JSON columns, which the SQLite read-model adapter
    serialises on the way in and hands back as text. `to_state` is the one place
    that converts, so the asymmetry does not leak into the queue.

    Deliberately absent: any finding text, any attention flag, any score. The
    findings live in the log; attention is computed; and a score would be a
    number nobody could re-derive.
    """

    __table_name__ = "topics"

    project_id: UUID
    question: str
    status: str
    rationale: str = ""
    scope: str = ""
    source_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sub_questions: dict = Field(default_factory=dict)
    contests: dict = Field(default_factory=dict)
    acknowledgements: dict = Field(default_factory=dict)
    investigations: int = 0
    findings: int = 0
    last_investigated_at: str | None = None
    findings_at_last_investigation: int = 0

    @field_validator(
        "source_ids",
        "entity_ids",
        "sub_questions",
        "contests",
        "acknowledgements",
        mode="before",
    )
    @classmethod
    def _decode_json(cls, value: object) -> object:
        """Accept the JSON text SQLite hands back for a list or dict column.

        The read-model adapter serialises collections to TEXT on the way in but
        converts only ids and its own timestamps on the way out, so every
        collection here returns as the JSON string it was stored as. Decoding
        at the boundary keeps that asymmetry out of the queue, which has no
        reason to know which backend it is reading.
        """
        if isinstance(value, str):
            return json.loads(value)
        return value

    def to_state(self) -> TopicState:
        """The row as the domain's own shape, so the triggers see one type.

        The registry takes a `TopicState` rather than a row, which is what lets
        every trigger be tested with no database at all -- and what stops the
        table's storage decisions (JSON columns, text positions) from reaching
        the rules.
        """
        return TopicState(
            topic_id=self.id,
            project_id=self.project_id,
            status=self.status,
            question=self.question,
            rationale=self.rationale,
            scope=self.scope,
            source_ids=list(self.source_ids),
            entity_ids=list(self.entity_ids),
            sub_questions={
                key: SubQuestion(**value) for key, value in dict(self.sub_questions).items()
            },
            contests={key: Contest(**value) for key, value in dict(self.contests).items()},
            acknowledgements={
                key: Acknowledgement(**value)
                for key, value in dict(self.acknowledgements).items()
            },
            investigations=self.investigations,
            findings=self.findings,
            last_investigated_at=self.last_investigated_at,
            findings_at_last_investigation=self.findings_at_last_investigation,
        )


class CorpusFactsRow(ReadModel):
    """What the attention registry needs to know about one corpus document.

    A separate, deliberately tiny table rather than a join against
    `corpus_documents`, whose rows carry whole documents: evaluating a queue
    reads every source in the project, and doing that against a table holding
    the text would pull entire corpora through memory to answer a question
    about ids and positions.

    `stored_at` is the corpus version at the most recent store, as sortable
    text -- see `corpus_position` for why that scale and not the global feed's.
    It is what makes "arrived since the last look" and "changed since the last
    look" computable without a timestamp anybody has to trust.
    """

    __table_name__ = "topic_corpus_facts"

    project_id: UUID
    source_id: str
    stored_at: str
    dropped: bool = False

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        return uuid5(TOPIC_NAMESPACE, f"{project_id}:{source_id}")


class TopicProjection(DeclarativeProjection):
    """Applies topic and corpus events to the two tables the queue reads.

    Every handler loads, mutates and writes back, so replaying from a checkpoint
    that is slightly behind re-derives the same values rather than accumulating
    them -- the same idempotence `SessionSummaryProjection` relies on.

    **One projection over two tables, rather than two projections.** The queue
    joins topics against a corpus snapshot on every evaluation, so the two are
    meaningless apart: a checkpoint that advanced one and not the other would
    produce a queue that is confidently wrong -- topics judged against a corpus
    the log has moved past, with nothing to report the drift.

    There is a mechanical reason too, and it is the one that settles it. A
    subscription advances only on events its projection handles, so two
    subscriptions over a log carrying only topic events leave the corpus one at
    no position at all -- and anything waiting for both to catch up waits
    forever. One subscription has one position, which is a question with an
    answer.
    """

    def __init__(
        self,
        rows: ReadModelRepository[TopicRow],
        facts: ReadModelRepository[CorpusFactsRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
        retry_policy=None,
    ) -> None:
        self._rows = rows
        self._facts = facts
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=retry_policy,
            tracer=tracer,
        )

    @handles(TopicOpened)
    async def _on_opened(self, event: TopicOpened) -> None:
        await self._rows.save(
            TopicRow(
                id=event.aggregate_id,
                project_id=event.project_id,
                question=event.question,
                rationale=event.rationale,
                scope=event.scope,
                status="open",
            )
        )

    @handles(TopicSubQuestionAdded)
    async def _on_sub_added(self, event: TopicSubQuestionAdded) -> None:
        row = await self._require(event.aggregate_id)
        row.sub_questions = {
            **dict(row.sub_questions),
            event.key: {"question": event.question, "answer": None},
        }
        await self._rows.save(row)

    @handles(TopicSubQuestionResolved)
    async def _on_sub_resolved(self, event: TopicSubQuestionResolved) -> None:
        row = await self._require(event.aggregate_id)
        subs = dict(row.sub_questions)
        existing = dict(subs.get(event.key) or {"question": ""})
        existing["answer"] = event.answer
        row.sub_questions = {**subs, event.key: existing}
        await self._rows.save(row)

    @handles(TopicSourceLinked)
    async def _on_source_linked(self, event: TopicSourceLinked) -> None:
        row = await self._require(event.aggregate_id)
        if event.source_id not in row.source_ids:
            row.source_ids = [*row.source_ids, event.source_id]
            await self._rows.save(row)

    @handles(TopicSourceUnlinked)
    async def _on_source_unlinked(self, event: TopicSourceUnlinked) -> None:
        row = await self._require(event.aggregate_id)
        row.source_ids = [s for s in row.source_ids if s != event.source_id]
        await self._rows.save(row)

    @handles(TopicEntityLinked)
    async def _on_entity_linked(self, event: TopicEntityLinked) -> None:
        row = await self._require(event.aggregate_id)
        if event.entity_id not in row.entity_ids:
            row.entity_ids = [*row.entity_ids, event.entity_id]
            await self._rows.save(row)

    @handles(TopicInvestigated)
    async def _on_investigated(self, event: TopicInvestigated) -> None:
        row = await self._require(event.aggregate_id)
        row.investigations += 1
        row.last_investigated_at = event.at_position
        row.findings_at_last_investigation = row.findings
        if row.status == "open":
            row.status = "investigating"
        await self._rows.save(row)

    @handles(TopicFindingRecorded)
    async def _on_finding(self, event: TopicFindingRecorded) -> None:
        row = await self._require(event.aggregate_id)
        row.findings += 1
        await self._rows.save(row)

    @handles(TopicContested)
    async def _on_contested(self, event: TopicContested) -> None:
        row = await self._require(event.aggregate_id)
        row.contests = {
            **dict(row.contests),
            event.key: {
                "nature": event.nature,
                "source_ids": list(event.source_ids),
                "resolution": None,
            },
        }
        await self._rows.save(row)

    @handles(TopicContestResolved)
    async def _on_contest_resolved(self, event: TopicContestResolved) -> None:
        row = await self._require(event.aggregate_id)
        contests = dict(row.contests)
        existing = dict(contests.get(event.key) or {"nature": "", "source_ids": []})
        existing["resolution"] = event.resolution
        row.contests = {**contests, event.key: existing}
        await self._rows.save(row)

    @handles(TopicStatusChanged)
    async def _on_status(self, event: TopicStatusChanged) -> None:
        row = await self._require(event.aggregate_id)
        row.status = event.to_status
        await self._rows.save(row)

    @handles(TopicTriggerAcknowledged)
    async def _on_acknowledged(self, event: TopicTriggerAcknowledged) -> None:
        row = await self._require(event.aggregate_id)
        row.acknowledgements = {
            **dict(row.acknowledgements),
            event.trigger: {
                "reason": event.reason,
                "until_position": event.until_position,
            },
        }
        await self._rows.save(row)

    async def _require(self, topic_id: UUID) -> TopicRow:
        """The row for a topic, which must already exist.

        The aggregate rejects every command before `OpenTopic`, so a missing row
        cannot come from a legitimate stream: it means events arrived out of
        order, or the table was truncated under a checkpoint that survived.
        Inventing one would hide exactly the drift worth knowing about.
        """
        row = await self._rows.get(topic_id)
        if row is None:
            raise LookupError(f"no topic row for {topic_id}")
        return row

    @handles(SourceDocumentStored)
    async def _on_source_stored(self, event: SourceDocumentStored) -> None:
        """Record where in the log this source most recently landed.

        A re-store is a supersession, so `stored_at` moves forward and `dropped`
        is cleared -- storing asserts presence, and a live document explaining
        why it is absent is nonsense.
        """
        row_id = CorpusFactsRow.row_id(event.aggregate_id, event.source_id)
        position = _position_text(event)
        existing = await self._facts.get(row_id)
        if existing is None:
            await self._facts.save(
                CorpusFactsRow(
                    id=row_id,
                    project_id=event.aggregate_id,
                    source_id=event.source_id,
                    stored_at=position,
                    dropped=False,
                )
            )
            return
        existing.stored_at = position
        existing.dropped = False
        await self._facts.save(existing)

    @handles(SourceDocumentDropped)
    async def _on_source_dropped(self, event: SourceDocumentDropped) -> None:
        row_id = CorpusFactsRow.row_id(event.aggregate_id, event.source_id)
        existing = await self._facts.get(row_id)
        if existing is None:
            return
        existing.dropped = True
        await self._facts.save(existing)


def _position_text(event) -> str:
    """This corpus event's position, in the one position space the feature uses.

    See `corpus_position`: every position here is a corpus version, and they
    are only ever compared with each other.
    """
    return corpus_position(event.aggregate_version or 0)


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
        await connection.executescript(generate_full_schema(TopicRow, dialect="sqlite"))
        await connection.executescript(generate_full_schema(CorpusFactsRow, dialect="sqlite"))
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


class TopicRunner:
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

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ):
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._topics: TopicStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return TopicProjection.__name__

    async def start(self) -> None:
        """Open the tables and start following the log.

        Touches the event store first for the reason the other two runners do:
        it creates `projection_checkpoints` on first connection rather than at
        construction, so reaching for checkpoints before anything has used the
        store finds no table at all.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._topics = await TopicStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer, LOCAL_RETRY_POLICY
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            self._topics.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the topic projection failed to start: {failures}")

    @property
    def queue(self) -> TopicQueue:
        if self._topics is None:
            raise RuntimeError("the topic projection has not been started")
        return TopicQueue(self._topics)

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events these projections could not process.

        A non-empty list means the queue is judging topics against a state the
        log has moved past -- which reads downstream as work silently not
        offered, rather than as an error anybody sees.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def get(self, topic_id: UUID) -> TopicRow | None:
        if self._topics is None:
            raise RuntimeError("the topic projection has not been started")
        return await self._topics.get(topic_id)

    async def list(self, project_id: UUID) -> list[TopicRow]:
        if self._topics is None:
            raise RuntimeError("the topic projection has not been started")
        return await self._topics.list(project_id)

    async def corpus_facts(self, project_id: UUID) -> CorpusFacts:
        """The corpus snapshot `attention_for` needs, delegated to the table.

        `TopicQueue.evaluate` already reads this to judge a whole queue; a
        single-topic read needs the same snapshot to judge one topic the same
        way, and this is that read exposed rather than a second one built from
        the corpus projection -- two paths to the same `CorpusFacts` are two
        chances for them to disagree about what "live" means.
        """
        if self._topics is None:
            raise RuntimeError("the topic projection has not been started")
        return await self._topics.corpus_facts(project_id)

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until both projections have seen everything appended so far.

        Load-bearing rather than a test affordance: an autonomous round records
        a look and then asks for the next topic, and the gap between the append
        and the row is exactly where it would be handed the topic it just
        finished.
        """
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            reached = self._subscription.last_processed_position
            if reached is not None and not reached < target:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(f"the topic projection did not reach {target} within {timeout}s")

    async def rebuild(self) -> None:
        """Throw both tables away and derive them again from the log.

        Safe because neither holds original information: every field comes from
        an event. Both go together, for the reason this class carries both --
        a queue built from a fresh topic table and a stale corpus snapshot is
        wrong in a way nothing would report.
        """
        if self._manager is None or self._topics is None:
            raise RuntimeError("the topic projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._topics.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._topics.close()
        self._topics = None
        await self.start()
        await self.caught_up()

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._topics is not None:
            await self._topics.close()
            self._topics = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
