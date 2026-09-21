"""Dialogue read models, projections, stores, and runners.

Houses read-side state and projections for Ask conversations and Socratic dialogues.
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
from research_team.dialogue.domain.socratic import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticProgressObserved,
    SocraticTurnRecorded,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "ASK_NAMESPACE",
    "SOCRATIC_NAMESPACE",
    "AskConversationProjection",
    "AskConversationRow",
    "AskConversationRunner",
    "AskConversationStore",
    "AskTurnRow",
    "SocraticDialogueProjection",
    "SocraticDialogueRow",
    "SocraticDialogueRunner",
    "SocraticDialogueStore",
    "SocraticTurnRow",
]


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


SOCRATIC_NAMESPACE = UUID("e1c7a9d2-4b0f-4a6e-9c31-2f58d7b6e410")
"""Namespace for derived socratic row ids. A fresh uuid5 namespace rather than
reusing `ASK_NAMESPACE`: the two id spaces would otherwise collide on a
dialogue and a conversation that happened to share an id and a position, which
is astronomically unlikely and free to prevent."""


class SocraticDialogueRow(ReadModel):
    """One dialogue. `id` is the dialogue id.

    The aggregate id itself with no `uuid5` over it, for `AskConversationRow`'s
    reason: the id is minted by the server and handed to the client, so
    deriving a second one would give every read route a key nothing returned.

    **`goal` and `stopping_condition` are the resumption path's source of
    truth.** When the live registry has dropped a dialogue, this row is what it
    is rebuilt from -- so a projection that stored the topic and dropped these
    two would resume a dialogue aimed at nothing, and every request would still
    answer 200.

    `observations` is a JSON list for `AskTurnRow.citations`' reason. A third
    table was the alternative and buys a query nothing issues; the spec asks
    for the two-table pattern and this is what keeps it.
    """

    __table_name__ = "socratic_dialogues"

    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    pending_prompt: str = ""
    """The question the reader is currently looking at.

    **Derived, not a second copy.** It is the last turn's `prompt`, or
    `opening_prompt` when there are no turns -- the projection writes it on
    start and overwrites it on each turn, so the log still holds each utterance
    once and this column is the precomputation a read model exists to do. A
    client asking "what am I answering?" would otherwise have to fetch every
    turn to find out.

    `rebuild()` reproduces it, because it is written in log order from event
    payloads like every other column here."""

    opened_at: datetime
    status: str = "started"
    concluded_reason: str = ""
    turn_count: int = 0
    observations: list[dict] = Field(default_factory=list)

    @field_validator("observations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class SocraticTurnRow(ReadModel):
    """One exchange: what the reader said, and what the dialogue said back.

    **`position` is stored, not inferred**, for `AskTurnRow`'s reason: a read
    leaning on insertion order is correct until `rebuild()` truncates and
    replays, which is supported here and free to insert in a different physical
    order.

    `prompt` is the dialogue's utterance and `reply` is the reader's -- the
    inverse of `AskTurnRow`, because this surface runs in the opposite
    direction. See `test_the_speakers_are_not_swapped_on_the_way_into_the_table`
    for what a swap would look like: a transcript that still reads as a
    conversation, just one where the reader asks all the questions.

    **A row is one exchange, reader first.** The question this row's `reply`
    answers is the *previous* row's `prompt` -- or `opening_prompt` on the
    dialogue, for row 0. So a client rendering only this table draws a
    transcript that starts with the reader; the dialogue's `opening_prompt` is
    the missing first utterance.
    """

    __table_name__ = "socratic_turns"

    dialogue_id: UUID
    project_id: UUID
    position: int
    prompt: str
    reply: str
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(dialogue_id: UUID, position: int) -> UUID:
        """Derived from the pair, so replaying one event twice rewrites a row
        rather than appending a second copy of the same turn."""
        return uuid5(SOCRATIC_NAMESPACE, f"{dialogue_id}:{position}")


class SocraticDialogueStore(BaseReadModelStore):
    """The two dialogue tables and the connection they share.

    One store rather than one per table, for `AskConversationStore`'s reason: a
    turn and its dialogue's `turn_count` and `pending_prompt` are written
    together, and two stores over two connections would leave a window in which
    a dialogue claims a turn that cannot be read yet.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        dialogues: ReadModelRepository[SocraticDialogueRow],
        turns: ReadModelRepository[SocraticTurnRow],
    ) -> None:
        super().__init__(connection)
        self._dialogues = dialogues
        self._turns = turns

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> SocraticDialogueStore:
        connection = await open_readmodel_connection(
            db_path,
            SocraticDialogueRow,
            SocraticTurnRow,
        )
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `AskConversationStore.open`. Both reads here are scoped: the
        # history list by project and one dialogue's turns by dialogue, so
        # without these every read scans every dialogue anyone ever had.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_socratic_dialogues_project "
            f"ON {SocraticDialogueRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_socratic_turns_dialogue "
            f"ON {SocraticTurnRow.table_name()}(dialogue_id, position)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, SocraticDialogueRow, tracer),
            SQLiteReadModelRepository(connection, SocraticTurnRow, tracer),
        )

    async def start(
        self,
        dialogue_id: UUID,
        project_id: UUID,
        *,
        topic: str,
        goal: str,
        stopping_condition: str,
        opening_prompt: str,
        opened_at: datetime,
    ) -> None:
        await self._dialogues.save(
            SocraticDialogueRow(
                id=dialogue_id,
                project_id=project_id,
                topic=topic,
                goal=goal,
                stopping_condition=stopping_condition,
                opening_prompt=opening_prompt,
                # With no turns yet, the opening question is the outstanding
                # one. `record` overwrites this on every turn.
                pending_prompt=opening_prompt,
                opened_at=opened_at,
            )
        )

    async def record(
        self,
        dialogue_id: UUID,
        *,
        reply: str,
        prompt: str,
        citations: list[dict],
        recorded_at: datetime,
    ) -> None:
        """Store one exchange at the next position, and move the dialogue on.

        A turn against a dialogue with no row is dropped rather than raised on,
        for `AskConversationStore.record`'s reason: `decide` refuses a turn
        before a start, so the only way to arrive here is a log whose head this
        projection never saw, and a DLQ entry per turn would bury a real
        failure under a stream that cannot be repaired anyway.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        position = dialogue.turn_count
        await self._turns.save(
            SocraticTurnRow(
                id=SocraticTurnRow.row_id(dialogue_id, position),
                dialogue_id=dialogue_id,
                project_id=dialogue.project_id,
                position=position,
                reply=reply,
                prompt=prompt,
                citations=citations,
                recorded_at=recorded_at,
            )
        )
        dialogue.turn_count = position + 1
        # Precomputed, not a second copy: this turn's `prompt` is the newest
        # thing the dialogue said, so it is what the reader is now answering.
        # Derivable from the turns table; kept here so a client does not have
        # to fetch every turn to learn it.
        dialogue.pending_prompt = prompt
        await self._dialogues.save(dialogue)

    async def observe(
        self, dialogue_id: UUID, *, observation: str, evidence: str, detail: str
    ) -> None:
        """Append one observation to the dialogue's list.

        Read-modify-write on a JSON column, which is only safe because this
        projection is the single writer of these tables and processes one event
        at a time -- the same assumption `record`'s position counter already
        makes.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.observations = [
            *dialogue.observations,
            {"observation": observation, "evidence": evidence, "detail": detail},
        ]
        await self._dialogues.save(dialogue)

    async def conclude(self, dialogue_id: UUID, *, reason: str) -> None:
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.status = "concluded"
        dialogue.concluded_reason = reason
        await self._dialogues.save(dialogue)

    async def get(self, dialogue_id: UUID) -> SocraticDialogueRow | None:
        return await self._dialogues.get(dialogue_id)

    async def for_project(self, project_id: UUID) -> list[SocraticDialogueRow]:
        """A project's dialogues, most recently opened first."""
        return await self._dialogues.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="opened_at",
                order_direction="desc",
            )
        )

    async def turns_for(self, dialogue_id: UUID) -> list[SocraticTurnRow]:
        """One dialogue's exchanges, in the order they happened -- by the
        stored `position`, never by arrival. See `SocraticTurnRow`."""
        return await self._turns.find(
            Query(
                filters=[Filter(field="dialogue_id", operator="eq", value=str(dialogue_id))],
                order_by="position",
                order_direction="asc",
            )
        )

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again -- a hard delete for
        `SessionSummaryStore.truncate`'s reason."""
        await self._truncate_tables(SocraticDialogueRow, SocraticTurnRow)


class SocraticDialogueProjection(DeclarativeProjection):
    """Writes dialogues into the two tables above.

    Nothing else writes them: every column comes from an event payload, which
    is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        dialogues: SocraticDialogueStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._dialogues = dialogues
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(SocraticDialogueStarted)
    async def _on_started(self, event: SocraticDialogueStarted) -> None:
        await self._dialogues.start(
            event.aggregate_id,
            event.project_id,
            topic=event.topic,
            goal=event.goal,
            stopping_condition=event.stopping_condition,
            opening_prompt=event.opening_prompt,
            opened_at=event.opened_at,
        )

    @handles(SocraticTurnRecorded)
    async def _on_turn(self, event: SocraticTurnRecorded) -> None:
        """`event.occurred_at` rather than a clock read, for the reason
        `AskConversationProjection._on_turn` gives: a rebuild has to reproduce
        the timestamps it produced the first time, not today's."""
        await self._dialogues.record(
            event.aggregate_id,
            reply=event.reply,
            prompt=event.prompt,
            citations=[{"kind": kind, "id": cited} for kind, cited in event.citations],
            recorded_at=event.occurred_at,
        )

    @handles(SocraticProgressObserved)
    async def _on_observed(self, event: SocraticProgressObserved) -> None:
        await self._dialogues.observe(
            event.aggregate_id,
            observation=event.observation,
            evidence=event.evidence,
            detail=event.detail,
        )

    @handles(SocraticDialogueConcluded)
    async def _on_concluded(self, event: SocraticDialogueConcluded) -> None:
        await self._dialogues.conclude(event.aggregate_id, reason=event.reason)


class SocraticDialogueRunner(BaseProjectionRunner[SocraticDialogueStore]):
    """Keeps the dialogue tables following the log.

    A ninth runner, for `AskConversationRunner`'s reason: a
    `rebuild()`/`failures()`-shaped surface for these tables alone, and a
    `rebuild()` that cannot truncate tables it does not own.

    **This is also the read side of resumption.** `get` and `turns_for` are
    what `SocraticDialogueService` reads through when the live registry has
    dropped a dialogue, so a build that never constructs this does not merely
    serve an empty history list -- it makes every resumed dialogue start over
    while telling the reader it continued.
    """

    _label = "socratic"
    _store_class = SocraticDialogueStore
    _projection_class = SocraticDialogueProjection
    _caught_up_aggregate_types = (SocraticDialogue.aggregate_type,)

    @property
    def _dialogues(self) -> SocraticDialogueStore | None:
        return self._store_instance

    async def get(self, dialogue_id: UUID) -> SocraticDialogueRow | None:
        return await self._started().get(dialogue_id)

    async def for_project(self, project_id: UUID) -> list[SocraticDialogueRow]:
        return await self._started().for_project(project_id)

    async def turns_for(self, dialogue_id: UUID) -> list[SocraticTurnRow]:
        return await self._started().turns_for(dialogue_id)
