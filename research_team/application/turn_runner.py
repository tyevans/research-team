"""Turn execution types and persistence helpers."""

from dataclasses import dataclass

from eventsource import OptimisticLockError

from research_team.domain import (
    FileDeleted,
    FileEdited,
    FileWritten,
)

__all__ = [
    "_FILE_EVENT_TYPES",
    "_INHERITED_EVENT_FIELDS",
    "TurnOutcome",
    "_TurnConflict",
    "project_context",
]


def project_context(name: str) -> str:
    """What project this session is in, for a session that is in one.

    Every other project-scoped clause in this build describes a *tool* -- the
    graph, the corpus, the topic queue -- and none of them said what the
    project is about. An agent joined to a project could not name it, which is
    the second half of why a topic question like "typical physical traits"
    goes unnoticed: even an agent that wanted to disambiguate had nothing to
    disambiguate against.

    Built per session rather than folded into the static `knowledge_prompt`,
    because the name is per project and that string is one constant shared by
    every project in the process. It lands in `SessionStarted.system_prompt`
    like the rest of the prompt, so a session resumed after a project is
    renamed still runs under the name it started with -- deliberate: replaying
    a session under a prompt it never saw is the failure that field exists to
    prevent, and a stale project name is a much smaller cost than that.

    Empty string for a project created without one. `ProjectState.name`
    defaults to `""` and nothing forbids it, and "This project is called ``."
    is worse than silence -- it reads as a bug in the prompt builder rather
    than as a project nobody named.
    """
    if not name.strip():
        return ""
    return (
        f"\n\nThis session is working in a project called {name!r}. That is the "
        "subject everything here is about. It is context for you, not a "
        "substitute for saying so: anything you write down -- a topic "
        "question, a finding, a file -- is read later by someone who does not "
        "have it."
    )


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


_INHERITED_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "occurred_at",
        "aggregate_id",
        "aggregate_type",
        "aggregate_version",
    }
)


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


_FILE_EVENT_TYPES = (FileWritten, FileEdited, FileDeleted)
"""What "inheriting a project's filesystem" copies. Deliberately narrower
than `fork()`'s replay: a project shares a workspace, not a chat history, so
`UserMessageSent` and friends never cross into the new stream."""
