"""Read models for the topic table and corpus facts."""

import json
from uuid import UUID, uuid5

from eventsource import ReadModel
from pydantic import Field, field_validator

from research_team.research.domain.topic import (
    Acknowledgement,
    Contest,
    SubQuestion,
    TopicState,
)

__all__ = [
    "TOPIC_NAMESPACE",
    "CorpusFactsRow",
    "TopicRow",
]

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
    gaps: int = 0
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
            gaps=self.gaps,
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
