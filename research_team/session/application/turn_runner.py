"""Turn execution types and persistence helpers."""

from dataclasses import dataclass

from eventsource import OptimisticLockError

from research_team.session.domain import (
    FILE_EVENT_TYPES as FILE_EVENT_TYPES,
)
from research_team.session.domain import (
    INHERITED_EVENT_FIELDS as INHERITED_EVENT_FIELDS,
)
from research_team.tenancy.application.project_sessions import (
    project_context as project_context,
)

_FILE_EVENT_TYPES = FILE_EVENT_TYPES
_INHERITED_EVENT_FIELDS = INHERITED_EVENT_FIELDS

__all__ = [
    "FILE_EVENT_TYPES",
    "INHERITED_EVENT_FIELDS",
    "_FILE_EVENT_TYPES",
    "_INHERITED_EVENT_FIELDS",
    "TurnOutcome",
    "_TurnConflict",
    "project_context",
]


@dataclass(frozen=True)
class TurnOutcome:
    """What one turn produced: the reply, and where it landed in the log.

    `from_index`/`to_index` are inclusive 1-based event numbers, matching the
    numbering the REPL prints and the web timeline shows.
    """

    reply: str
    turn_index: int
    from_index: int
    to_index: int

    @property
    def event_count(self) -> int:
        return self.to_index - self.from_index + 1


class _TurnConflict(Exception):
    """Private: "do not retry this turn, and raise `cause` instead".

    Exists only to get a decision out of `with_retry`'s `attempt`, which
    retries every `OptimisticLockError` it sees and has no vocabulary for "this
    one is real". Never escapes `_save_turn`, which unwraps it -- callers see
    the `OptimisticLockError` they would have seen without any retrying.
    """

    def __init__(self, cause: OptimisticLockError) -> None:
        super().__init__(str(cause))
        self.cause = cause
