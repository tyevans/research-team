"""The interfaces the application layer needs the outside world to satisfy.

Ports are declared here, next to the code that calls them, and implemented in
`research_team.infrastructure`. Nothing in this module knows about SQLite,
langchain, or deepagents; those are details chosen at composition time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from eventsource import DomainEvent

from research_team.domain import Session

if TYPE_CHECKING:
    # Imported for typing only: `summaries` imports nothing from here, and
    # keeping it that way is what stops the ports module from depending on a
    # use case that depends on it.
    from research_team.application.summaries import SessionSummary

# ActivityReporter is defined below after ActivityNote


class SessionRepository(Protocol):
    """Loads and stores `Session` aggregates, and reads raw event streams.

    The raw reads exist because this is an event-sourced application: the log
    itself is a first-class read model (`/log`, `/history`, `/diff`, forking),
    not just the aggregate's private bookkeeping.
    """

    def create(self, session_id: UUID) -> Session:
        """A new, unsaved aggregate. Does not touch storage."""
        ...

    async def load(self, session_id: UUID) -> Session: ...

    async def save(self, session: Session) -> None:
        """Append the aggregate's pending events atomically."""
        ...

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        ...

    async def close(self) -> None: ...

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, from the creation events.

        Declared on this port -- rather than reached into as a concrete
        attribute -- so a caller that only has a `SessionService` (the REPL)
        can list projects through it instead of a private hop past the
        service into its repository (BACKLOG B8).
        """
        ...


@dataclass(frozen=True)
class SummaryHealth:
    """Whether the `/sessions` list can be trusted right now.

    Worth reporting because a stale or drifted row is indistinguishable from a
    correct one by looking at it. The old per-request fold could not be wrong
    -- it was recomputed every time -- so nothing needed to say it was right.
    A projection does.
    """

    failed_events: int
    """Events the projection gave up on. Each one is a row that is now wrong."""

    following: bool
    """Whether the projection is running and applying new events."""

    behind: bool
    """Whether the log has moved on past what the projection has applied.

    Ordinary and momentary -- the projection follows the log rather than
    sharing its transaction. Only interesting if it stays true.
    """

    @property
    def healthy(self) -> bool:
        """False when the table needs rebuilding, or is not being maintained.

        Deliberately does not include `behind`: being briefly behind is the
        normal condition of a read model, and a health flag that blinks during
        routine operation is one nobody looks at.
        """
        return self.failed_events == 0 and self.following


class SessionSummaries(Protocol):
    """The `/sessions` list, as a thing that is stored rather than computed.

    Separate from `SessionRepository` because it is the query side: it answers
    from a view maintained by a projection, and knows nothing about aggregates
    or streams. There is deliberately no method here for reading every event --
    that was the full scan this port exists to replace.
    """

    async def list(self) -> list["SessionSummary"]:
        """Every session, newest first."""
        ...

    async def health(self) -> SummaryHealth:
        """Whether the list is currently trustworthy."""
        ...

    async def rebuild(self) -> None:
        """Discard the stored list and derive it from the log again.

        The repair for drift, and safe to run at any time: the log is the only
        source of truth, so anything computed from it can be thrown away.
        """
        ...


@dataclass(frozen=True)
class FeedEntry:
    """One event from the global feed, with the cursor that follows it.

    `aggregate_id` rather than `session_id`, and `aggregate_type` beside it,
    because the feed no longer carries only sessions: a topic is its own
    aggregate with its own stream, and calling its id a session id is how a
    subscriber ends up looking for a session that does not exist. The two
    fields together are what let `_sse` decide which kind of frame to write
    without re-deriving it from the event class.
    """

    aggregate_id: UUID
    aggregate_type: str
    event: DomainEvent
    position: object
    """Opaque to us: compared and persisted, never inspected or arithmetic'd."""


class EventFeed(Protocol):
    """Reads the store's global feed, in append order.

    Separate from `SessionRepository` because it answers a different question:
    not "what does this session look like" but "what has happened lately",
    which is what a live view needs -- and "lately" spans aggregates, because
    a reader watching a project cares about its topics moving as much as a
    reader watching a session cares about its turns.
    """

    async def latest_position(self) -> object | None:
        """The cursor at the end of the feed right now, or None if it is empty."""
        ...

    async def read_since(self, position: object | None) -> list[FeedEntry]:
        """Everything appended after `position`. Exclusive; None means from the start."""
        ...

    def encode_position(self, position: object) -> str:
        """A position as text, for handing to a client that may hand it back."""
        ...

    def decode_position(self, raw: str) -> object | None:
        """A position from text, or None if it is not one this store can place.

        Returning None rather than raising is the contract: the text comes from
        outside, so "unusable" is an ordinary answer and the caller is expected
        to have somewhere else to start.
        """
        ...

    async def wait_for_append(self, timeout: float) -> None:
        """Return once something has been appended, or after `timeout`.

        A hint, not a guarantee, and deliberately carries no events: the reader
        still asks the store what is new, so ordering and completeness stay the
        store's business. All this saves is the wait -- an implementation that
        cannot tell when a write happened may simply sleep, and the only cost
        is latency the caller had already agreed to.
        """
        ...


class TurnAccountingError(Exception):
    """The agent returned something the log cannot faithfully record.

    Distinct from a turn that merely failed. A failed turn is an ordinary
    event -- the model timed out, the endpoint refused -- and gets a
    `TurnFailed` marker. This means our own accounting of what the agent
    added has drifted, so recording *anything* would be recording a lie.
    It propagates without touching the log.
    """


MessageKind = Literal["assistant", "tool"]


@dataclass(frozen=True)
class ActivityMessage:
    """A whole message the agent produced, reported before the turn commits.

    Provisional by construction: the turn may still fail, in which case none of
    these becomes an event. `payload` is opaque here for the same reason
    `RecordedMessage.payload` is -- only the executor that produced it knows
    its shape, and this layer may not name langchain.
    """

    message_id: str
    """The message's own id, so a delta and the whole message that supersedes
    it can be matched without inventing a correlation scheme."""

    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class ActivityDelta:
    """A chunk of assistant prose, to append to `message_id`.

    Only ever prose. Tool call arguments are never streamed in pieces: partial
    JSON renders as garbage and would have to be buffered whole anyway.
    """

    message_id: str
    text: str


@dataclass(frozen=True)
class ActivityRemark:
    """A line about the turn itself, not about anything the log will hold.

    Deliberately without a `message_id`, unlike the other two: there is no
    message for it to belong to, and inventing an id here would put a key the
    application layer made up into a buffer that reconciles on exactly that
    key. Whoever renders it names it, if their medium needs a name.

    The one producer today is context preparation, which says what it left out
    of the model's view. That is commentary, and it is why the contract below
    had to be widened rather than the note being squeezed into a message.
    """

    text: str


ActivityNote = ActivityMessage | ActivityDelta | ActivityRemark

ActivityReporter = Callable[[ActivityNote], None]
"""Called with progress as a turn runs, before anything is appended to the log.

Widened from a one-line string: the web UI renders the content itself, so a
formatted line is not enough. The terminal formats these back down to a line
(`research_team.interfaces.cli.repl`).

A message or a delta previews the turn: it is content the log will contain if
the turn commits. A remark is the exception and is marked as one -- the log
never holds it, and nothing downstream may assume otherwise. The rule this
replaces ("never called for anything the log will not contain") was narrower
than the callers, and a caller that disagreed with it answered 500 instead:
`session_service` passed a preparation note as a bare string, because there was
no note type it could honestly be.
"""


class TurnActivityBuffer(Protocol):
    """Holds a turn's provisional content for as long as the turn lasts.

    Three methods rather than the whole of `TurnActivity`, and the omission is
    the point: the application drives a buffer and never reads one back.
    `current` and `discarded` are answered to an HTTP caller catching up, so
    declaring them here would describe a coupling that does not exist.

    Implemented by `interfaces/web/activity.py`. The supervisor owns the
    lifecycle because a turn's buffer lives exactly as long as the turn, and
    the supervisor is the only thing that knows that span -- an HTTP request
    awaiting a turn can go away while the turn runs on.
    """

    def begin(self, session_id: UUID) -> None:
        """Open a buffer for a turn about to start, dropping the last one's."""

    def reporter(self, session_id: UUID) -> ActivityReporter:
        """The reporter this turn's notes should be sent to."""

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        """Close the buffer. A committed turn's content is on the log and is
        dropped; an uncommitted turn's is all that survives it, and is kept
        aside as discarded."""


@dataclass(frozen=True)
class RecordedMessage:
    """One message the agent produced, ready to become an event.

    `payload` is opaque to the application layer: it is stored and replayed
    verbatim, and only the executor that produced it knows its shape.
    """

    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class TurnResult:
    """What one agent pass produced, beyond the file events it already emitted."""

    messages: tuple[RecordedMessage, ...]
    reply_text: str


@dataclass(frozen=True)
class ApprovalRequest:
    """A request for a human to approve, edit, or reject a gated tool call.

    The application layer must not know whether the human is at a terminal or
    browsing in a web UI -- this port abstracts that choice away. Paired with
    ApprovalPort so the executor depends only on the interface, not on any UI
    framework or presentation layer.
    """

    session_id: UUID
    tool_name: str
    args: dict
    description: str
    allowed_decisions: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalDecision:
    """A human's response to an ApprovalRequest.

    The `type` field holds one of: approve, edit, reject, respond. When edit
    is chosen, `edited_args` replaces the original args. When respond is
    chosen, `message` carries the human's reply.
    """

    type: str
    edited_args: dict | None = None
    message: str | None = None


class ApprovalRefused(Exception):
    """Raised by an `ApprovalPort` instead of a decision, when there is no
    decision a human actually made.

    `ApprovalDecision` is a record of what a person chose, and every existing
    caller that receives one records `decided_by="human"` -- see
    `deep_agent.py`'s `_apply`. That is correct for every port that only ever
    returns a decision a person gave. A port can also *refuse to keep
    waiting* -- a bounded session's timeout expiring is the first case, but
    the shape is general -- and that refusal did not come from a person, so
    it must not be wearable as one. Raising rather than returning is what
    keeps `_apply`'s blanket `"human"` honest: a port that raises this is a
    port telling the executor "attribute this decision to policy, not to
    whoever the browser was waiting on."

    `message` is shown to the model, the same as `ApprovalDecision.message`
    would be -- the turn continues on a legible rejection, not an exception
    that unwinds the pass. It exists as an exception rather than a third
    `ApprovalDecision.type` because a value in that enum-like field is
    something `_apply` treats as `decided_by="human"` by construction; a new
    channel was needed, not a new value on the old one.
    """


class ApprovalPort(Protocol):
    """Asks a human to approve, edit, or reject a gated tool call.

    Decouples the executor from the medium of human interaction. The executor
    calls this port knowing only that a human will receive the request and
    return a decision -- whether they are at a terminal, in a web browser, or
    somewhere else is an infrastructure detail, not the executor's concern.

    May raise `ApprovalRefused` instead of returning, when the port itself
    -- not a human -- decided the call cannot proceed.
    """

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...


class TurnExecutor(Protocol):
    """Runs the agent for one turn.

    File mutations are recorded on the aggregate as they happen -- the agent's
    filesystem *is* the aggregate -- while conversation messages come back in
    the result for the caller to append. That split is deliberate: the caller
    decides whether the turn is committed at all, and a turn that raises is
    discarded whole, aggregate included.
    """

    @property
    def model_name(self) -> str: ...

    def encode_user_message(self, text: str) -> dict:
        """The stored payload for a user's message, in the executor's format."""
        ...

    async def execute(
        self,
        session: Session,
        *,
        messages: list[dict],
        system_prompt: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnResult:
        """Run one pass over `messages`, which is what the model will see.

        The caller chooses those, rather than the executor reading them off the
        session: what the model is shown is a use-case decision (see
        `research_team.application.context`), and the executor must not quietly
        disagree with what the caller counted as sent.
        """
        ...
