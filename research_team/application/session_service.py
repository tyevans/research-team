"""The use cases: everything you can do to a coding session.

This layer orchestrates. It owns transaction boundaries (a turn is all-or-
nothing) and the ordering rules between commands, but no domain invariants
(those live on the aggregate) and no I/O details (those live behind the ports).

Every operation names the session it acts on. The service holds no "current
session": that is a property of whoever is driving -- one terminal has exactly
one, and a web server has one per request -- so it belongs to the caller.
"""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from eventsource import DomainEvent

from research_team.application.ports import (
    ActivityReporter,
    SessionRepository,
    TurnAccountingError,
    TurnExecutor,
)
from research_team.application.summaries import SessionSummary, summarize_sessions
from research_team.domain import CodingSession

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell and no network."
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


class SessionService:
    """The application's whole surface, over one event store."""

    def __init__(
        self,
        repository: SessionRepository,
        executor: TurnExecutor,
        *,
        default_system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._default_system_prompt = default_system_prompt

    @property
    def default_system_prompt(self) -> str:
        """The prompt new sessions are started with. Existing ones keep their own."""
        return self._default_system_prompt

    async def close(self) -> None:
        await self._repository.close()

    # ---------------- reads ----------------

    async def load(self, session_id: UUID) -> CodingSession:
        """One session's aggregate, folded from its events."""
        return await self._repository.load(session_id)

    async def history(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        return await self._repository.events_for(session_id)

    async def state_at(self, session_id: UUID, at: int) -> CodingSession:
        """The session as it stood after its first `at` events.

        A pure fold of a prefix -- nothing is written, nothing is forked. This
        is what makes scrubbing a timeline cheap: the log is the state, so any
        point in it can be reconstituted just by stopping the fold early.
        """
        events = await self.history(session_id)
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fold at {at}: session has {len(events)} events")
        aggregate = self._repository.create(session_id)
        aggregate.load_from_history(events[:at])
        return aggregate

    async def list_sessions(self) -> list[SessionSummary]:
        """Every session in the store, newest first."""
        return summarize_sessions(await self._repository.all_events())

    # ---------------- lifecycle ----------------

    async def create_session(self, system_prompt: str | None = None) -> UUID:
        """Start a new session and return its id."""
        session_id = uuid4()
        aggregate = self._repository.create(session_id)
        aggregate.start(
            system_prompt if system_prompt is not None else self._default_system_prompt,
            self._executor.model_name,
        )
        await self._repository.save(aggregate)
        return session_id

    # ---------------- turns ----------------

    async def run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        """One user turn. All events append atomically at the end, or not at all.

        The prompt comes from the session's own `SessionStarted` event, so a
        session resumed in a differently-configured process still runs under
        the prompt it was started with.

        Reports the span of events the turn produced. A caller showing the log
        would otherwise have to diff it against a snapshot taken beforehand to
        answer "which of these did my turn write?" -- a question the aggregate
        can answer exactly, because an aggregate's version *is* its event count.
        """
        aggregate = await self._repository.load(session_id)
        first_index = aggregate.version + 1
        aggregate.send_user_message(self._executor.encode_user_message(user_input))

        try:
            result = await self._executor.execute(
                aggregate,
                system_prompt=aggregate.state.system_prompt
                or self._default_system_prompt,
                on_activity=on_activity,
            )
        except TurnAccountingError:
            # Not an ordinary failure: our accounting of what the agent added
            # has drifted, so even a marker would be a claim we cannot stand
            # behind. Leave the log untouched and let it surface.
            raise
        except BaseException as error:
            # The aggregate above is discarded with all of the failed turn's
            # events, so the turn stays all-or-nothing. What gets appended is a
            # single marker on a freshly loaded aggregate -- the log records
            # that an attempt happened without a half-applied turn.
            await self._record_failure(session_id, error)
            raise

        for message in result.messages:
            if message.kind == "tool":
                aggregate.record_tool_result(message.payload, is_error=message.is_error)
            else:
                aggregate.record_assistant_message(message.payload)

        aggregate.complete_turn()
        last_index = aggregate.version
        await self._repository.save(aggregate)
        return TurnOutcome(
            reply=result.reply_text,
            turn_index=aggregate.state.turn_index,
            from_index=first_index,
            to_index=last_index,
        )

    async def _record_failure(self, session_id: UUID, error: BaseException) -> None:
        """Append a TurnFailed marker. Never masks the original error.

        Shielded, because the most common reason to be here is cancellation --
        and a cancelled coroutine's next await would be cancelled too, which
        would lose the very marker that records the attempt.
        """
        writing = asyncio.ensure_future(self._append_failure(session_id, error))
        try:
            await asyncio.shield(writing)
        except asyncio.CancelledError:
            # We are being cancelled; the write is not. Wait for it anyway, so
            # the marker is on disk before the cancellation carries on -- a
            # fire-and-forget write can be lost if the process is shutting down.
            await writing
            raise

    async def _append_failure(self, session_id: UUID, error: BaseException) -> None:
        try:
            clean = await self._repository.load(session_id)
            # Whether this was a deliberate stop is an asyncio fact, which the
            # aggregate has no business knowing -- so it is decided here.
            clean.fail_turn(error, cancelled=isinstance(error, asyncio.CancelledError))
            await self._repository.save(clean)
        except Exception:  # noqa: BLE001 -- the original failure is what matters
            logger.exception("could not record TurnFailed for %s", session_id)

    # ---------------- time travel ----------------

    async def fork(self, session_id: UUID, at: int) -> UUID:
        """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
        events = await self.history(session_id)
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

        new_id = uuid4()
        forked = self._repository.create(new_id)
        for event in events[:at]:
            forked.create_event(
                type(event), **event.model_dump(exclude=set(_INHERITED_EVENT_FIELDS))
            )
        forked.record_fork_source(session_id, at)
        await self._repository.save(forked)
        return new_id
