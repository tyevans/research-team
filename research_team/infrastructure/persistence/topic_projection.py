"""Declarative projection for topic and corpus-facts tables."""

from uuid import UUID

from eventsource import (
    DeclarativeProjection,
    handles,
)
from eventsource.ports.readmodels import ReadModelRepository

from research_team.infrastructure.persistence.topic_models import (
    CorpusFactsRow,
    TopicRow,
)
from research_team.research.application.topic_attention import (
    corpus_position,
)
from research_team.research.domain.corpus import CorpusDocumentDropped, CorpusDocumentStored
from research_team.research.domain.topic import (
    TopicContested,
    TopicContestResolved,
    TopicEntityLinked,
    TopicFindingRecorded,
    TopicGapRecorded,
    TopicInvestigated,
    TopicOpened,
    TopicQuestionRestated,
    TopicSourceLinked,
    TopicSourceUnlinked,
    TopicStatusChanged,
    TopicSubQuestionAdded,
    TopicSubQuestionResolved,
    TopicTriggerAcknowledged,
)

__all__ = [
    "TopicProjection",
    "_position_text",
]


def _position_text(event) -> str:
    """This corpus event's position, in the one position space the feature uses.

    See `corpus_position`: every position here is a corpus version, and they
    are only ever compared with each other.
    """
    return corpus_position(event.aggregate_version or 0)


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

    @handles(TopicQuestionRestated)
    async def _on_question_restated(self, event: TopicQuestionRestated) -> None:
        row = await self._require(event.aggregate_id)
        row.question = event.question
        await self._rows.save(row)

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

    @handles(TopicGapRecorded)
    async def _on_gap(self, event: TopicGapRecorded) -> None:
        row = await self._require(event.aggregate_id)
        row.gaps += 1
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

    @handles(CorpusDocumentStored)
    async def _on_source_stored(self, event: CorpusDocumentStored) -> None:
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

    @handles(CorpusDocumentDropped)
    async def _on_source_dropped(self, event: CorpusDocumentDropped) -> None:
        row_id = CorpusFactsRow.row_id(event.aggregate_id, event.source_id)
        existing = await self._facts.get(row_id)
        if existing is None:
            return
        existing.dropped = True
        await self._facts.save(existing)
