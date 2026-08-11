"""The driver: one round is one turn, and the log decides when to stop.

Sits *above* `TurnSupervisor` and holds no state that is not in the log. Each
round reads the queue, claims the most urgent topic, runs one turn scoped to it,
records what that turn actually produced, and asks the run whether to continue.

**Why round-per-turn rather than one long looping turn.** A turn is atomic: a
failure discards the aggregate and appends a lone marker. All-or-nothing over an
hour of work is worthless, cancellation gets no granularity, and the context
grows without bound. Round-per-turn buys atomicity, cancellation, and
resumability for free, and pairs with the `delegate` context mode that
investigation wants anyway.

**Why the driver never decides it is finished.** Every stop reason is a fold of
the run's own stream or of the queue -- `state.exhausted()` and "the queue is
empty" are the only two sources. There is no path here by which the agent's
prose ends a run, because a model asked whether it has finished says yes
fluently, and a loop that trusts that terminates early and reports success.

**Why the default is read-only.** `fetch` floors at `ask`. An unattended loop
that reaches an approval either deadlocks on a future nobody will resolve or is
auto-rejected outright, and neither is a loop working. So the default run works
over the corpus and graph the project already holds -- which is most of the
value, since coverage, contradiction, linkage and staleness are all questions
about material already in hand. **The driver reads the autonomy policy and never
writes it**: a loop that could lower its own floors would make `TOOL_FLOORS`
advisory, and the structural guarantee is worth more than the convenience.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.application.grants import FetchGrant, GrantRegistry
from research_team.application.topic_attention import TopicAttention
from research_team.domain.auto_research import (
    BeginRound,
    Budget,
    CompleteRound,
    FailRound,
    StartRun,
    StopRun,
)
from research_team.domain.topic import RecordInvestigation

logger = logging.getLogger(__name__)


class TopicQueuePort(Protocol):
    """The slice of the topic projection a run needs.

    A protocol rather than the concrete runner so the driver can be tested with
    a list, and so `application` never names the projection that satisfies it.
    """

    async def evaluate(self, project_id: UUID) -> list[TopicAttention]: ...

    async def high_water(self, project_id: UUID) -> str: ...


class TopicWriter(Protocol):
    """How a round records what it learned against a topic."""

    async def load(self, topic_id: UUID): ...

    async def save(self, aggregate) -> None: ...


@dataclass(frozen=True)
class RoundOutcome:
    """What one round's turn actually appended to its topic.

    Counted from the topic's stream rather than taken from the agent's account
    of itself. That distinction is the whole defence against confabulated
    progress: a round that describes a breakthrough and appends nothing is
    empty, and `produced_nothing` is what the novelty-decay stop reads.
    """

    findings: int = 0
    sources_linked: int = 0
    sub_questions_opened: int = 0

    @property
    def produced_nothing(self) -> bool:
        return not (self.findings or self.sources_linked or self.sub_questions_opened)


#: Runs one round's turn. Given the topic and why it was raised, returns what
#: reached the log. Injected so the driver names no executor, and so a test can
#: drive a whole run with no model.
RunRound = Callable[[UUID, TopicAttention], Awaitable[RoundOutcome]]


@dataclass(frozen=True)
class RunReport:
    """How a run ended, in the shape a caller wants to print.

    Mirrors `AutoRunStopped` rather than adding to it: everything here is
    already in the log, and a report that could say something the log does not
    is a second account of the same run.
    """

    run_id: UUID
    reason: str
    rounds: int
    findings: int
    unexamined_topics: int
    detail: str = ""

    @property
    def finished_cleanly(self) -> bool:
        """Whether the run ran out of work rather than out of permission to continue.

        The only reason that means the work is *done*. Everything else means it
        stopped, which is a different thing and must not be reported as success.
        """
        return self.reason == "queue_empty" and self.unexamined_topics == 0


class AutoResearchDriver:
    """Works a project's topic queue until a computed condition says stop."""

    def __init__(
        self,
        runs,
        topics: TopicWriter,
        queue: TopicQueuePort,
        *,
        run_round: RunRound,
        settle: Callable[[], Awaitable[None]] | None = None,
        grants: GrantRegistry | None = None,
    ) -> None:
        self._runs = runs
        self._topics = topics
        self._queue = queue
        self._run_round = run_round
        self._settle = settle
        # `None` is a valid build, not a missing one: a caller with no
        # approval gate to speak of (a test driving the queue directly) has
        # no registry to register into, and `run`/`_stop` below both check
        # before touching it. Wired for real from `composition.py`'s one
        # `GrantRegistry`, the same instance the gate and the grant-bound
        # `fetch` tool consult -- see that module for why there is exactly
        # one instance and what two would cost.
        self._grants = grants

    async def run(
        self,
        project_id: UUID,
        session_id: UUID,
        *,
        budget: Budget | None = None,
        fetch_hosts: Sequence[str] = (),
        fetch_budget: int = 0,
        autonomy_snapshot: dict[str, Any] | None = None,
        read_only: bool = True,
        run_id: UUID | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> RunReport:
        """Work the queue, and return how it ended.

        The autonomy policy is snapshotted into the start event because it is
        mutable mid-turn: without it, "was this run allowed to do that" stops
        being answerable the moment anyone changes a level.

        `run_id` is accepted rather than always minted here so a caller can
        name the run *before* it starts. A front end that starts a run in the
        background has to answer "how is it going" from the moment the request
        returns, and a report that only carries the id at the end leaves the
        first status call with nothing to fold.

        `cancelled` is asked once per round, in the same place the budget is.
        `cancelled` is one of `StopReason`'s values and until now had no
        producer, which made stopping a run something only the process dying
        could do -- and that leaves the stream with no stop event at all, so a
        later reader cannot tell an abandoned run from one still going. Asked
        between rounds rather than during one because a turn is atomic: there
        is nothing to interrupt inside a round that would not throw the
        round's work away.

        `fetch_hosts`/`fetch_budget` default to nothing granted, matching the
        REPL's `/research` (spec §6: "The REPL's `/research` gains nothing").
        They are recorded on `StartRun` and folded onto `AutoRunState` by the
        domain either way; what changes here is what this method does *with*
        the fold once it has one -- see the registration below.
        """
        run = self._runs.create_new(run_id or uuid4())
        run.execute(
            StartRun(
                run_id=run.aggregate_id,
                project_id=project_id,
                session_id=session_id,
                budget=budget or Budget(),
                autonomy_snapshot=autonomy_snapshot or {},
                read_only=read_only,
                fetch_hosts=list(fetch_hosts),
                fetch_budget=fetch_budget,
            )
        )
        await self._runs.save(run)

        if self._grants is not None:
            # From `run.state`, the fold, not from `fetch_hosts`/`fetch_budget`
            # directly -- one source, so the registry and the log can never
            # disagree about what this run was granted. Registered even when
            # nothing was: an empty `FetchGrant` covers no host and answers
            # `spent` immediately, but the session still needs to be *in* the
            # registry for `GrantRegistry.is_unattended` to find it, which is
            # what lets an unanswerable approval on an ungranted run time out
            # instead of hanging forever (Task 6).
            self._grants.register(
                session_id,
                FetchGrant(
                    run_id=run.aggregate_id,
                    hosts=frozenset(run.state.fetch_hosts),
                    budget=run.state.fetch_budget,
                ),
            )

        try:
            while True:
                # Asked before each round rather than after, so a run that
                # starts already exhausted stops without doing work it has no
                # budget for.
                exhausted = run.state.exhausted()
                if exhausted is not None:
                    return await self._stop(run, exhausted, project_id)

                if cancelled is not None and cancelled():
                    return await self._stop(run, "cancelled", project_id)

                queue = await self._queue.evaluate(project_id)
                if not queue:
                    return await self._stop(run, "queue_empty", project_id)

                attention = queue[0]
                run.execute(
                    BeginRound(
                        topic_id=attention.topic_id,
                        triggers=list(attention.triggers),
                        evidence=list(attention.evidence),
                        queue_depth=len(queue),
                    )
                )
                await self._runs.save(run)

                outcome = await self._round(run, attention, project_id)
                await self._runs.save(run)
                if outcome is None:
                    # The round failed and was recorded; the loop continues so
                    # one bad topic cannot end a run. `error_rate` stops it if
                    # they keep failing.
                    continue
        finally:
            # Every normal ending already goes through `_stop`, which
            # releases this same grant -- so on the common path this is a
            # second, harmless `GrantRegistry.release` (a `dict.pop(...,
            # None)`, idempotent). What this `finally` is actually for is the
            # path `_stop` never runs on: an exception from `self._runs.save`
            # or `self._queue.evaluate`, or a `CancelledError` from the task
            # this coroutine runs as (`ResearchSupervisor._run` cancels
            # nothing directly, but the process can). Without this, a crash
            # mid-run left the grant -- and the `is_unattended` flag Task 6's
            # bounded wait depends on -- alive in the registry for the rest
            # of the process's life, on a session id nothing would ever
            # release again. Spec §5 says the registry entry is "removed in
            # `_stop`"; that undersold it, and a whole-branch review caught
            # the gap between "the normal path releases" and "the registry
            # entry cannot outlive the run" that spec sentence actually
            # promises.
            if self._grants is not None:
                self._grants.release(session_id)

    async def _round(
        self, run, attention: TopicAttention, project_id: UUID
    ) -> RoundOutcome | None:
        """Run one round's turn, recording the look and what came of it.

        The look is recorded *whether or not the turn produced anything*. That
        is what makes `topic.rework_thrash` computable and what stops the same
        topic being handed back on the next round for the same reason -- an
        unrecorded look is indistinguishable from no look at all.
        """
        topic_id = attention.topic_id
        try:
            outcome = await self._run_round(topic_id, attention)
        except Exception as error:  # noqa: BLE001 - one bad topic must not end a run
            logger.warning("auto-research round failed on %s: %r", topic_id, error)
            run.execute(
                FailRound(
                    topic_id=topic_id,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
            )
            await self._record_look(
                topic_id, project_id, run.aggregate_id, summary="failed", outcome="failed"
            )
            return None

        await self._record_look(
            topic_id,
            project_id,
            run.aggregate_id,
            summary=_summarize(outcome),
            outcome="nothing" if outcome.produced_nothing else "produced",
        )
        run.execute(
            CompleteRound(
                topic_id=topic_id,
                findings=outcome.findings,
                sources_linked=outcome.sources_linked,
                sub_questions_opened=outcome.sub_questions_opened,
            )
        )
        return outcome

    async def _record_look(
        self,
        topic_id: UUID,
        project_id: UUID,
        run_id: UUID,
        *,
        summary: str,
        outcome: str,
    ) -> None:
        """Stamp the topic with how far the corpus had got when it was looked at.

        Best-effort: a topic that cannot be stamped must not fail the round,
        because the work the round did is already in the log. It will simply be
        offered again, which is the safe direction to fail in.

        `outcome` is required here though the domain's `RecordInvestigation`
        and `TopicInvestigated.outcome` are `str | None` -- the driver always
        knows how its own round ended, so there is no honest `None` to pass at
        this call site. The nullability on the domain type exists only for
        payloads written before the field did, not for this caller.
        """
        try:
            position = await self._queue.high_water(project_id)
            topic = await self._topics.load(topic_id)
            topic.execute(
                RecordInvestigation(
                    at_position=position, summary=summary, by_run_id=run_id, outcome=outcome
                )
            )
            await self._topics.save(topic)
        except Exception as error:  # noqa: BLE001 - see the docstring
            logger.warning("could not record the look at %s: %r", topic_id, error)
        if self._settle is not None:
            # Let the projection catch up before the next round reads the
            # queue, or the run is handed back the topic it just finished.
            await self._settle()

    async def _stop(self, run, reason: str, project_id: UUID) -> RunReport:
        """End the run, counting what it is leaving behind.

        The outstanding count is read from the queue at the moment of stopping
        rather than inferred, so a run that stops with work still waiting says
        so on its face instead of reporting success.

        Releases this run's grant from the registry, if `run` registered one.
        Every path that ends a run passes through here (`exhausted()`,
        `cancelled`, `queue_empty`), so this is the one place a release has
        to happen -- a grant is scoped to the run, and the run is over.
        Without this, a spent-out or completed run's session would stay
        `is_unattended` forever, and its host list would keep answering
        `covers()` for a run that no longer exists.
        """
        outstanding = (
            0 if reason == "queue_empty" else len(await self._queue.evaluate(project_id))
        )
        run.execute(StopRun(reason=reason, unexamined_topics=outstanding))
        await self._runs.save(run)
        if self._grants is not None and run.state.session_id is not None:
            self._grants.release(run.state.session_id)
        return RunReport(
            run_id=run.aggregate_id,
            reason=reason,
            rounds=run.state.rounds,
            findings=run.state.findings,
            unexamined_topics=outstanding,
        )


def _summarize(outcome: RoundOutcome) -> str:
    """A one-line account of a round, in counts rather than prose."""
    if outcome.produced_nothing:
        return "nothing recorded"
    parts = []
    if outcome.findings:
        parts.append(f"{outcome.findings} finding(s)")
    if outcome.sources_linked:
        parts.append(f"{outcome.sources_linked} source(s) linked")
    if outcome.sub_questions_opened:
        parts.append(f"{outcome.sub_questions_opened} sub-question(s) opened")
    return ", ".join(parts)
