"""Ask conversation read models, projections, store, and runner.

Houses read-side state and projections for Ask conversations.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import DeclarativeProjection, ReadModel, handles
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository
from pydantic import Field, field_validator

from research_team.dialogue.domain.ask import (
    AskConversation,
    AskConversationStarted,
    AskTurnRecorded,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

ASK_NAMESPACE = UUID("b0d4f1a7-52c6-5f38-9d1e-7a3c806b45e9")
"""Distinct from the other namespaces here, for the reason stated on
`ONTOLOGY_NAMESPACE`: tables keyed on unrelated things that are all just
strings by the time `uuid5` sees them must not be able to collide on `id`."""


class AskConversationRow(ReadModel):
    """One persisted conversation. `id` is the conversation id.

    The aggregate id itself, with no `uuid5` over it, unlike every other row
    in this module: the id is minted by the server and handed to the client on
    the ask stream, so deriving a second one would give the history route a
    key nothing ever returned.

    Carries `first_question` and `turn_count` so a history list can be drawn
    from this table alone. The alternative -- listing conversations and then
    reading every turn of each to find its opening line -- is a query per row
    on a page whose whole job is to be a cheap index.
    """

    __table_name__ = "ask_conversations"

    project_id: UUID
    opened_at: datetime
    first_question: str = ""
    turn_count: int = 0


class AskTurnRow(ReadModel):
    """One question and its answer, with the citations that answer rested on.

    **`position` is stored, not inferred.** A read that leaned on insertion
    order would be correct until `rebuild()` truncated and replayed, which is
    a supported operation here and free to insert rows in a different physical
    order. The column is assigned from the conversation's `turn_count` as the
    event is applied, so a replay of the same log reproduces the same numbers.

    `citations` is a JSON list for `SessionSummaryRow.file_paths`' reason, and
    is decoded on the way out for the same asymmetry that field documents.
    """

    __table_name__ = "ask_turns"

    conversation_id: UUID
    project_id: UUID
    position: int
    question: str
    answer: str
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(conversation_id: UUID, position: int) -> UUID:
        """Derived from the pair, so replaying one event twice rewrites a row
        rather than appending a second copy of the same turn."""
        return uuid5(ASK_NAMESPACE, f"{conversation_id}:{position}")


class AskConversationStore(BaseReadModelStore):
    """The two ask tables and the connection they share.

    One store rather than one per table, for `OntologyStore`'s reason: a turn
    and its conversation's `turn_count` are written together, and two stores
    over two connections would leave a window in which a conversation claims a
    turn that cannot be read yet.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        conversations: ReadModelRepository[AskConversationRow],
        turns: ReadModelRepository[AskTurnRow],
    ) -> None:
        super().__init__(connection)
        self._conversations = conversations
        self._turns = turns

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> AskConversationStore:
        connection = await open_readmodel_connection(
            db_path,
            AskConversationRow,
            AskTurnRow,
        )
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. Both reads here are scoped: the
        # history list by project and one conversation's turns by conversation,
        # so without these every read scans every ask anyone ever made.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_ask_conversations_project "
            f"ON {AskConversationRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ask_turns_conversation "
            f"ON {AskTurnRow.table_name()}(conversation_id, position)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, AskConversationRow, tracer),
            SQLiteReadModelRepository(connection, AskTurnRow, tracer),
        )

    async def start(
        self, conversation_id: UUID, project_id: UUID, opened_at: datetime
    ) -> None:
        await self._conversations.save(
            AskConversationRow(id=conversation_id, project_id=project_id, opened_at=opened_at)
        )

    async def record(
        self,
        conversation_id: UUID,
        *,
        question: str,
        answer: str,
        citations: list[dict],
        recorded_at: datetime,
    ) -> None:
        """Store one turn at the next position, and move the conversation on.

        A turn against a conversation with no row is dropped rather than
        raised on: `AskConversation.decide` refuses a turn before a start, so
        the only way to arrive here is a log whose first event this projection
        never saw, and a DLQ entry per turn would bury a real failure under a
        stream that cannot be repaired anyway.
        """
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            return
        position = conversation.turn_count
        await self._turns.save(
            AskTurnRow(
                id=AskTurnRow.row_id(conversation_id, position),
                conversation_id=conversation_id,
                project_id=conversation.project_id,
                position=position,
                question=question,
                answer=answer,
                citations=citations,
                recorded_at=recorded_at,
            )
        )
        conversation.turn_count = position + 1
        if position == 0:
            conversation.first_question = question
        await self._conversations.save(conversation)

    async def get(self, conversation_id: UUID) -> AskConversationRow | None:
        return await self._conversations.get(conversation_id)

    async def for_project(self, project_id: UUID) -> list[AskConversationRow]:
        """A project's conversations, most recently opened first."""
        return await self._conversations.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="opened_at",
                order_direction="desc",
            )
        )

    async def turns_for(self, conversation_id: UUID) -> list[AskTurnRow]:
        """One conversation's turns, in the order they were asked -- by the
        stored `position`, never by arrival. See `AskTurnRow`."""
        return await self._turns.find(
            Query(
                filters=[
                    Filter(field="conversation_id", operator="eq", value=str(conversation_id))
                ],
                order_by="position",
                order_direction="asc",
            )
        )

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again -- a hard delete for
        `SessionSummaryStore.truncate`'s reason."""
        await self._truncate_tables(AskConversationRow, AskTurnRow)


class AskConversationProjection(DeclarativeProjection):
    """Writes persisted asks into the two tables above.

    Nothing else writes them: unlike `EntityDefinitionStore`, every column
    here comes from an event payload, which is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        asks: AskConversationStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._asks = asks
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(AskConversationStarted)
    async def _on_started(self, event: AskConversationStarted) -> None:
        await self._asks.start(event.aggregate_id, event.project_id, event.opened_at)

    @handles(AskTurnRecorded)
    async def _on_turn(self, event: AskTurnRecorded) -> None:
        """`event.occurred_at` rather than a clock read, for the reason
        `OntologyProjection._on_discovered` gives: a rebuild has to reproduce
        the timestamps it produced the first time, not today's."""
        await self._asks.record(
            event.aggregate_id,
            question=event.question,
            answer=event.answer,
            citations=[{"kind": kind, "id": cited} for kind, cited in event.citations],
            recorded_at=event.occurred_at,
        )


class AskConversationRunner(BaseProjectionRunner[AskConversationStore]):
    """Keeps the ask tables following the log.

    A seventh runner, for the reasons `CorpusRunner`'s docstring gives for
    being a second: a `rebuild()`/`failures()`-shaped surface for these tables
    alone, and a `rebuild()` that cannot truncate tables it does not own.
    """

    _label = "ask"
    _store_class = AskConversationStore
    _projection_class = AskConversationProjection
    _caught_up_aggregate_types = (AskConversation.aggregate_type,)

    @property
    def _asks(self) -> AskConversationStore | None:
        return self._store_instance

    async def get(self, conversation_id: UUID) -> AskConversationRow | None:
        return await self._started().get(conversation_id)

    async def for_project(self, project_id: UUID) -> list[AskConversationRow]:
        return await self._started().for_project(project_id)

    async def turns_for(self, conversation_id: UUID) -> list[AskTurnRow]:
        return await self._started().turns_for(conversation_id)


__all__ = [
    "ASK_NAMESPACE",
    "AskConversationProjection",
    "AskConversationRow",
    "AskConversationRunner",
    "AskConversationStore",
    "AskTurnRow",
]
