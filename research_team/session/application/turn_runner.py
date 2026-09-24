"""Turn execution types and persistence helpers."""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from eventsource import OptimisticLockError
from eventsource.observability import Tracer, create_tracer
from eventsource.observability.attributes import (
    ATTR_AGGREGATE_ID,
    ATTR_AGGREGATE_TYPE,
)

from research_team.platform.shared.retry import with_retry
from research_team.session.application.context import ContextStrategy, FullHistory
from research_team.session.application.ports import (
    ActivityRemark,
    ActivityReporter,
    SessionRepository,
    TurnAccountingError,
    TurnExecutor,
)
from research_team.session.domain import (
    FILE_EVENT_TYPES as FILE_EVENT_TYPES,
)
from research_team.session.domain import (
    INHERITED_EVENT_FIELDS as INHERITED_EVENT_FIELDS,
)
from research_team.session.domain import (
    AutonomyChanged,
    CompactConversation,
    CompleteTurn,
    FailTurn,
    RecordAssistantMessage,
    RecordForkSource,
    RecordToolResult,
    SendUserMessage,
    Session,
    SessionPurpose,
    SessionStarted,
)

logger = logging.getLogger(__name__)

_FILE_EVENT_TYPES = FILE_EVENT_TYPES
_INHERITED_EVENT_FIELDS = INHERITED_EVENT_FIELDS

__all__ = [
    "FILE_EVENT_TYPES",
    "INHERITED_EVENT_FIELDS",
    "_FILE_EVENT_TYPES",
    "_INHERITED_EVENT_FIELDS",
    "TurnOutcome",
    "TurnRunner",
    "_TurnConflict",
    "append_turn_failure",
    "fork_session",
    "record_turn_failure",
    "refuse_unrebasable",
    "save_turn_with_retry",
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


async def refuse_unrebasable(
    repository: SessionRepository,
    session_id: UUID,
    base_version: int,
    lost: OptimisticLockError | None,
) -> None:
    """Give up rather than rebase over a write the turn contradicts.

    The danger in retrying a turn is that a lock error means two different
    things. An autonomy switch flipped mid-turn is bookkeeping that
    happened *beside* the turn, and re-appending over it loses nothing. A
    second turn on the same session is the opposite: both turns read the
    same conversation and answered it independently, so appending both
    interleaves two replies to one message -- the all-or-nothing breakage
    the compare-and-swap exists to prevent, laundered into a success.
    `test_two_turns_at_once_on_one_session_conflict_rather_than_interleave`
    is what fails if this check goes.

    So the allowance is a named list of one, rather than "anything that is
    not a turn". The cost is that a new benign concurrent writer will make
    turns fail until someone adds it here -- which is the direction to be
    wrong in: a spurious 409 is visible and recoverable, a silently
    interleaved conversation is neither.
    """
    history = await repository.events_for(session_id)
    landed = history[base_version:]
    if all(isinstance(event, AutonomyChanged) for event in landed):
        return
    assert lost is not None, "only reached after a save has lost its version"
    raise _TurnConflict(lost)


async def save_turn_with_retry(
    repository: SessionRepository,
    session_id: UUID,
    aggregate: Session,
) -> Session:
    """Append the turn's events, re-appending them if the save loses.

    A turn holds a version for as long as the model runs, which can be
    minutes, so anything else appending to the session -- an autonomy
    switch flipped from the UI is the one that did it in production --
    makes the save fail and throws the whole turn away. That is the worst
    possible thing to discard: it has already been paid for.

    **Only the append repeats.** `with_retry`'s contract is that `attempt`
    reloads and re-*decides*, which is right for a short write and wrong
    here: re-deciding means re-running the model, so a retry would bill a
    second turn and could repeat every tool call the first one made --
    writing a file twice to avoid a lock error is not a trade worth making.
    So the retry re-applies the events the turn already produced onto a
    freshly loaded aggregate instead. `with_retry` is still what counts and
    bounds the attempts; the deviation is in what `attempt` does, and it is
    safe for the same reason a rebase is: none of the turn's events decide
    anything against the state the interloper changed. `AutonomyChanged`
    moves a policy the *executor* consulted while the turn ran, and the
    turn's own events are records of what already happened.

    The bound is `with_retry`'s. What it costs is that a session under
    genuinely continuous write pressure loses the turn with the lock error
    it would have raised anyway -- but that is a stream nobody could take a
    turn on, and an unbounded retry there is a hang instead of an error.
    """
    events = list(aggregate.uncommitted_events)
    base_version = aggregate.version - len(events)
    pending: Session | None = aggregate
    lost: OptimisticLockError | None = None

    async def attempt() -> Session:
        # The first attempt saves the aggregate the turn ran on; every
        # later one rebuilds it, because an aggregate that lost a save
        # still holds the version it lost at and would lose again.
        nonlocal pending, lost
        target = pending
        pending = None
        if target is None:
            await refuse_unrebasable(repository, session_id, base_version, lost)
            target = await repository.load(session_id)
            for event in events:
                target.apply_event(
                    event.model_copy(update={"aggregate_version": target.get_next_version()}),
                    is_new=True,
                )
        try:
            await repository.save(target)
        except OptimisticLockError as error:
            lost = error
            raise
        return target

    try:
        return await with_retry(attempt, what=f"the turn on session {session_id}")
    except _TurnConflict as conflict:
        # The lock error itself, unwrapped: a caller mapping it to a 409
        # should not have to learn that something tried to rebase first.
        raise conflict.cause from None


async def append_turn_failure(
    repository: SessionRepository, session_id: UUID, error: BaseException
) -> None:
    try:
        clean = await repository.load(session_id)
        # Whether this was a deliberate stop is an asyncio fact, which the
        # aggregate has no business knowing -- so it is decided here.
        clean.execute(
            FailTurn.from_error(error, cancelled=isinstance(error, asyncio.CancelledError))
        )
        await repository.save(clean)
    except Exception:
        logger.exception("could not record TurnFailed for %s", session_id)


async def record_turn_failure(
    repository: SessionRepository, session_id: UUID, error: BaseException
) -> None:
    """Append a TurnFailed marker. Never masks the original error.

    Shielded, because the most common reason to be here is cancellation --
    and a cancelled coroutine's next await would be cancelled too, which
    would lose the very marker that records the attempt.
    """
    writing = asyncio.ensure_future(append_turn_failure(repository, session_id, error))
    try:
        await asyncio.shield(writing)
    except asyncio.CancelledError:
        # We are being cancelled; the write is not. Wait for it anyway, so
        # the marker is on disk before the cancellation carries on -- a
        # fire-and-forget write can be lost if the process is shutting down.
        await writing
        raise


class TurnRunner:
    """Orchestrates one turn on a session with optimistic locking and tracing."""

    def __init__(
        self,
        repository: SessionRepository,
        executor: TurnExecutor,
        *,
        default_system_prompt: str = "",
        context: ContextStrategy | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._default_system_prompt = default_system_prompt
        self._context = context if context is not None else FullHistory()
        self._tracer = tracer if tracer is not None else create_tracer(__name__, False)

    async def run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        """One user turn. All events append atomically at the end, or not at all."""
        with self._tracer.span(
            "research_team.turn",
            {ATTR_AGGREGATE_ID: str(session_id), ATTR_AGGREGATE_TYPE: "Session"},
        ):
            return await self._run_turn(session_id, user_input, on_activity)

    async def _run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        aggregate = await self._repository.load(session_id)
        aggregate.execute(
            SendUserMessage(message=self._executor.encode_user_message(user_input))
        )

        prepared = await self._context.prepare(aggregate.state)
        if prepared.compaction is not None:
            aggregate.execute(
                CompactConversation(
                    summary=prepared.compaction.summary,
                    through_index=prepared.compaction.through_index,
                    strategy=self._context.name,
                    tokens_before=prepared.compaction.tokens_before,
                    tokens_after=prepared.compaction.tokens_after,
                )
            )
        if on_activity is not None:
            for note in prepared.notes:
                on_activity(ActivityRemark(text=note))

        try:
            result = await self._executor.execute(
                aggregate,
                messages=prepared.messages,
                system_prompt=aggregate.state.system_prompt or self._default_system_prompt,
                on_activity=on_activity,
            )
        except TurnAccountingError:
            raise
        except BaseException as error:
            await self._record_failure(session_id, error)
            raise

        for message in result.messages:
            if message.kind == "tool":
                aggregate.execute(
                    RecordToolResult(message=message.payload, is_error=message.is_error)
                )
            else:
                aggregate.execute(RecordAssistantMessage(message=message.payload))

        aggregate.execute(CompleteTurn())
        appended = len(aggregate.uncommitted_events)
        saved = await self._save_turn(session_id, aggregate)
        return TurnOutcome(
            reply=result.reply_text,
            turn_index=saved.state.turn_index,
            from_index=saved.version - appended + 1,
            to_index=saved.version,
        )

    async def _save_turn(self, session_id: UUID, aggregate: Session) -> Session:
        return await save_turn_with_retry(self._repository, session_id, aggregate)

    async def _refuse_unrebasable(
        self, session_id: UUID, base_version: int, lost: OptimisticLockError | None
    ) -> None:
        return await refuse_unrebasable(self._repository, session_id, base_version, lost)

    async def _record_failure(self, session_id: UUID, error: BaseException) -> None:
        await record_turn_failure(self._repository, session_id, error)

    async def _append_failure(self, session_id: UUID, error: BaseException) -> None:
        await append_turn_failure(self._repository, session_id, error)


async def fork_session(
    repository: SessionRepository,
    session_id: UUID,
    at: int,
    *,
    purpose: SessionPurpose | None = None,
) -> UUID:
    """Replay the first `at` events onto a fresh stream. Nothing is destroyed.

    If `purpose` is specified, the forked session is retargeted to that
    purpose (e.g. converting a RESEARCH_ROUND session to CHAT for an
    interactive human console session, resolving B101).
    """
    events = await repository.events_for(session_id)
    if not 1 <= at <= len(events):
        raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

    new_id = uuid4()
    forked = repository.create(new_id)
    for event in events[:at]:
        payload = event.model_dump(exclude=set(INHERITED_EVENT_FIELDS))
        if isinstance(event, SessionStarted) and purpose is not None:
            payload["purpose"] = purpose
        forked.create_event(type(event), **payload)
    forked.execute(
        RecordForkSource(source_session_id=session_id, at_event=at, purpose=purpose)
    )
    await repository.save(forked)
    return new_id
