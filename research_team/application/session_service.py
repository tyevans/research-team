"""The use cases: everything you can do to a coding session.

This layer orchestrates. It owns transaction boundaries (a turn is all-or-
nothing), the ordering rules between commands, and the currently-selected
session -- but no domain invariants (those live on the aggregate) and no I/O
details (those live behind the ports).
"""

import logging
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
    """Drives one selected session at a time, over a shared event store."""

    def __init__(
        self,
        repository: SessionRepository,
        executor: TurnExecutor,
        *,
        session_id: UUID,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._session_id = session_id
        self._system_prompt = system_prompt

    # ---------------- the current session ----------------

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    async def load(self) -> CodingSession:
        """The current session's aggregate, folded from its events."""
        return await self._repository.load(self._session_id)

    async def history(self) -> list[DomainEvent]:
        """Every event on the current session's stream, in order."""
        return await self._repository.events_for(self._session_id)

    async def close(self) -> None:
        await self._repository.close()

    # ---------------- session lifecycle ----------------

    async def start_session(self) -> UUID:
        """Begin a fresh session on the same store and switch to it."""
        self._session_id = await create_session(
            self._repository,
            system_prompt=self._system_prompt,
            model_name=self._executor.model_name,
        )
        return self._session_id

    async def resume(self, session_id: UUID) -> CodingSession:
        """Switch to a stored session, adopting the prompt it was started with.

        No `SessionStarted` is appended: the resumed stream stays a faithful
        continuation rather than a session with two beginnings.
        """
        aggregate = await self._repository.load(session_id)
        self._session_id = session_id
        self._system_prompt = aggregate.state.system_prompt or self._system_prompt
        return aggregate

    async def list_sessions(self) -> list[SessionSummary]:
        """Every session in the store, newest first."""
        return summarize_sessions(await self._repository.all_events())

    # ---------------- turns ----------------

    async def run_turn(
        self, user_input: str, on_activity: ActivityReporter | None = None
    ) -> str:
        """One user turn. All events append atomically at the end, or not at all."""
        aggregate = await self.load()
        aggregate.send_user_message(self._executor.encode_user_message(user_input))

        try:
            result = await self._executor.execute(
                aggregate,
                system_prompt=self._system_prompt,
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
            await self._record_failure(error)
            raise

        for message in result.messages:
            if message.kind == "tool":
                aggregate.record_tool_result(message.payload, is_error=message.is_error)
            else:
                aggregate.record_assistant_message(message.payload)

        aggregate.complete_turn()
        await self._repository.save(aggregate)
        return result.reply_text

    async def _record_failure(self, error: BaseException) -> None:
        """Append a TurnFailed marker. Never masks the original error."""
        try:
            clean = await self._repository.load(self._session_id)
            clean.fail_turn(error)
            await self._repository.save(clean)
        except Exception:  # noqa: BLE001 -- the original failure is what matters
            logger.exception("could not record TurnFailed for %s", self._session_id)

    # ---------------- time travel ----------------

    async def fork(self, at: int) -> UUID:
        """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
        events = await self.history()
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

        new_id = uuid4()
        forked = self._repository.create(new_id)
        for event in events[:at]:
            forked.create_event(
                type(event), **event.model_dump(exclude=set(_INHERITED_EVENT_FIELDS))
            )
        forked.record_fork_source(self._session_id, at)
        await self._repository.save(forked)
        return new_id

    async def switch_to_fork(self, at: int) -> UUID:
        """Fork at `at` and continue from the fork. The original stream remains."""
        self._session_id = await self.fork(at)
        return self._session_id


async def create_session(
    repository: SessionRepository, *, system_prompt: str, model_name: str
) -> UUID:
    """Append a new session's creation event and return its id."""
    session_id = uuid4()
    aggregate = repository.create(session_id)
    aggregate.start(system_prompt, model_name)
    await repository.save(aggregate)
    return session_id
