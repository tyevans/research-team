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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

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
    ) -> None:
        self._runs = runs
        self._topics = topics
        self._queue = queue
        self._run_round = run_round
        self._settle = settle

    async def run(
        self,
        project_id: UUID,
        session_id: UUID,
        *,
        budget: Budget | None = None,
        autonomy_snapshot: dict[str, Any] | None = None,
        read_only: bool = True,
    ) -> RunReport:
        """Work the queue, and return how it ended.

        The autonomy policy is snapshotted into the start event because it is
        mutable mid-turn: without it, "was this run allowed to do that" stops
        being answerable the moment anyone changes a level.
        """
        run = self._runs.create_new(uuid4())
        run.execute(
            StartRun(
                run_id=run.aggregate_id,
                project_id=project_id,
                session_id=session_id,
                budget=budget or Budget(),
                autonomy_snapshot=autonomy_snapshot or {},
                read_only=read_only,
            )
        )
        await self._runs.save(run)

        while True:
            # Asked before each round rather than after, so a run that starts
            # already exhausted stops without doing work it has no budget for.
            exhausted = run.state.exhausted()
            if exhausted is not None:
                return await self._stop(run, exhausted, project_id)

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
                # The round failed and was recorded; the loop continues so one
                # bad topic cannot end a run. `error_rate` stops it if they
                # keep failing.
                continue

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
            await self._record_look(topic_id, project_id, run.aggregate_id, summary="failed")
            return None

        await self._record_look(
            topic_id, project_id, run.aggregate_id, summary=_summarize(outcome)
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
        self, topic_id: UUID, project_id: UUID, run_id: UUID, *, summary: str
    ) -> None:
        """Stamp the topic with how far the corpus had got when it was looked at.

        Best-effort: a topic that cannot be stamped must not fail the round,
        because the work the round did is already in the log. It will simply be
        offered again, which is the safe direction to fail in.
        """
        try:
            position = await self._queue.high_water(project_id)
            topic = await self._topics.load(topic_id)
            topic.execute(
                RecordInvestigation(at_position=position, summary=summary, by_run_id=run_id)
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
        """
        outstanding = (
            0 if reason == "queue_empty" else len(await self._queue.evaluate(project_id))
        )
        run.execute(StopRun(reason=reason, unexamined_topics=outstanding))
        await self._runs.save(run)
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
