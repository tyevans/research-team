"""The autonomous run: what stops it, and what it may not claim.

Two invariants carry this feature, and both get their own test:

- **No round without a reason.** A round names the triggers that raised its
  topic, so "why did the agent research this" is answerable from the log.
- **No stop without evidence.** Every `StopReason` is recomputable from the
  events before it. There is deliberately no path by which the agent's prose
  ends a run.

The driver is exercised with a fake round function and an in-memory queue, so a
whole run -- budgets, novelty decay, failures, resumption -- is tested with no
model, no store and no event loop beyond asyncio itself.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.application.auto_research import (
    AutoResearchDriver,
    RoundOutcome,
    RunReport,
)
from research_team.application.topic_attention import Finding, TopicAttention
from research_team.domain.auto_research import (
    AutoResearchRun,
    AutoRoundCompleted,
    AutoRunStarted,
    AutoRunStopped,
    BeginRound,
    Budget,
    CompleteRound,
    FailRound,
    StartRun,
    StopRun,
    decide,
    evolve,
    initial_state,
)


def run_commands(state, *commands):
    for command in commands:
        for event in decide(command, state):
            state = evolve(state, event)
    return state


def started(**kwargs):
    return run_commands(
        initial_state(),
        StartRun(
            run_id=kwargs.get("run_id", uuid4()),
            project_id=uuid4(),
            session_id=uuid4(),
            budget=kwargs.get("budget", Budget()),
        ),
    )


def attention(topic_id=None, triggers=("topic.never_investigated",), evidence=()):
    return TopicAttention(
        topic_id=topic_id or uuid4(),
        findings=tuple(
            Finding(check=t, severity="blocking", message=t, cites=tuple(evidence))
            for t in triggers
        ),
    )


# ---------------- the aggregate ----------------


def test_a_run_records_the_autonomy_policy_it_started_under():
    """Without the snapshot, "was it allowed to do that" stops being answerable.

    The policy is mutable mid-turn, so reading it back later tells you what it
    is now, not what the run was operating under.
    """
    [event] = decide(
        StartRun(
            run_id=uuid4(),
            project_id=uuid4(),
            session_id=uuid4(),
            autonomy_snapshot={"fetch": "ask", "default": "auto"},
        ),
        initial_state(),
    )

    assert isinstance(event, AutoRunStarted)
    assert event.autonomy_snapshot == {"fetch": "ask", "default": "auto"}
    assert event.read_only is True


def test_a_round_must_name_the_triggers_that_raised_it():
    """The "no round without a reason" invariant, enforced in the domain.

    A round with no triggers cannot say why it chose its topic, which makes the
    whole run's audit trail decorative.
    """
    with pytest.raises(CommandRejectedError, match="triggers"):
        decide(BeginRound(topic_id=uuid4(), triggers=[], evidence=[]), started())


def test_a_round_carries_the_evidence_its_triggers_cited():
    state = started()

    [event] = decide(
        BeginRound(
            topic_id=uuid4(),
            triggers=["topic.source_dropped"],
            evidence=["s1", "s2"],
            queue_depth=4,
        ),
        state,
    )

    assert event.evidence == ["s1", "s2"]
    assert event.queue_depth == 4


def test_two_rounds_cannot_be_in_flight_at_once():
    state = run_commands(started(), BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]))

    with pytest.raises(CommandRejectedError, match="in flight"):
        decide(BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]), state)


def test_an_in_flight_topic_survives_so_a_crash_is_distinguishable():
    """A round that began and never ended is not a topic nobody picked."""
    topic_id = uuid4()
    state = run_commands(started(), BeginRound(topic_id=topic_id, triggers=["t"], evidence=[]))

    assert state.in_flight_topic == topic_id

    state = run_commands(state, CompleteRound(topic_id=topic_id))
    assert state.in_flight_topic is None


def test_completing_a_round_that_never_began_is_refused():
    with pytest.raises(CommandRejectedError, match="no round is in flight"):
        decide(CompleteRound(topic_id=uuid4()), started())


def test_a_stopped_run_accepts_nothing_further():
    """Appending after the stop would make the stop event a lie."""
    state = run_commands(started(), StopRun(reason="queue_empty"))

    with pytest.raises(CommandRejectedError, match="already stopped"):
        decide(BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]), state)


# ---------------- what counts as progress ----------------


def test_a_round_that_appended_nothing_is_empty_however_it_described_itself():
    state = run_commands(
        started(),
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        CompleteRound(topic_id=uuid4()),
    )

    assert state.consecutive_quiet_rounds == 1
    assert state.findings == 0


@pytest.mark.parametrize(
    "produced",
    [
        {"findings": 1},
        {"sources_linked": 1},
        {"sub_questions_opened": 1},
    ],
    ids=["finding", "source", "sub-question"],
)
def test_any_real_production_resets_novelty_decay(produced):
    """Linking a source is progress too -- a run doing it is still learning."""
    state = run_commands(
        started(),
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        CompleteRound(topic_id=uuid4()),
    )
    assert state.consecutive_quiet_rounds == 1

    state = run_commands(
        state,
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        CompleteRound(topic_id=uuid4(), **produced),
    )

    assert state.consecutive_quiet_rounds == 0


def test_produced_nothing_reads_off_the_event_rather_than_the_narration():
    empty = AutoRoundCompleted(aggregate_id=uuid4(), round_number=1, topic_id=uuid4())
    assert empty.produced_nothing

    real = AutoRoundCompleted(
        aggregate_id=uuid4(), round_number=1, topic_id=uuid4(), findings=1
    )
    assert not real.produced_nothing


# ---------------- stop conditions ----------------


def test_a_fresh_run_is_not_exhausted():
    assert started().exhausted() is None


def test_novelty_decay_stops_a_run_that_has_stopped_learning():
    state = started(budget=Budget(quiet_rounds=2))
    for _ in range(2):
        state = run_commands(
            state,
            BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
            CompleteRound(topic_id=uuid4()),
        )

    assert state.exhausted() == "no_new_findings"


def test_consecutive_failures_stop_a_run_that_is_only_failing():
    """The condition most autonomous loops forget: a failing run still runs."""
    state = started(budget=Budget(max_consecutive_failures=2))
    for _ in range(2):
        state = run_commands(
            state,
            BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
            FailRound(topic_id=uuid4(), error_type="RuntimeError"),
        )

    assert state.exhausted() == "error_rate"


def test_a_success_clears_the_failure_streak():
    state = started(budget=Budget(max_consecutive_failures=2))
    state = run_commands(
        state,
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        FailRound(topic_id=uuid4(), error_type="RuntimeError"),
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        CompleteRound(topic_id=uuid4(), findings=1),
    )

    assert state.consecutive_failures == 0
    assert state.exhausted() is None


def test_max_rounds_is_the_backstop():
    state = started(budget=Budget(max_rounds=2, quiet_rounds=99))
    for _ in range(2):
        state = run_commands(
            state,
            BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
            CompleteRound(topic_id=uuid4(), findings=1),
        )

    assert state.exhausted() == "max_rounds"


def test_failures_are_reported_ahead_of_running_out_of_rounds():
    """A run that is failing should say so, not report that it finished its rounds."""
    state = started(budget=Budget(max_rounds=2, max_consecutive_failures=2))
    for _ in range(2):
        state = run_commands(
            state,
            BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
            FailRound(topic_id=uuid4(), error_type="RuntimeError"),
        )

    assert state.exhausted() == "error_rate"


def test_the_stop_event_carries_what_the_run_is_leaving_behind():
    state = run_commands(
        started(),
        BeginRound(topic_id=uuid4(), triggers=["t"], evidence=[]),
        CompleteRound(topic_id=uuid4(), findings=2),
    )

    [event] = decide(StopRun(reason="max_rounds", unexamined_topics=5), state)

    assert isinstance(event, AutoRunStopped)
    assert (event.rounds, event.findings, event.unexamined_topics) == (1, 2, 5)


# ---------------- the driver ----------------


class FakeQueue:
    """A queue that empties as topics are completed."""

    def __init__(self, *attentions):
        self.pending = list(attentions)
        self.position = "000000000001"

    async def evaluate(self, project_id):
        return list(self.pending)

    async def high_water(self, project_id):
        return self.position

    def resolve(self, topic_id):
        self.pending = [a for a in self.pending if a.topic_id != topic_id]


class FakeTopics:
    """Records the looks a run stamps, without a store."""

    def __init__(self):
        self.looks: list[UUID] = []

    async def load(self, topic_id):
        return _FakeTopic(topic_id, self.looks)

    async def save(self, aggregate):
        return None


class _FakeTopic:
    def __init__(self, topic_id, looks):
        self.aggregate_id = topic_id
        self._looks = looks

    def execute(self, command):
        self._looks.append(self.aggregate_id)


class FakeRuns:
    """The aggregate itself, saved to nothing."""

    def create_new(self, run_id):
        return AutoResearchRun(run_id)

    async def save(self, aggregate):
        return None


@pytest.fixture
def runs():
    return FakeRuns()


async def test_a_run_over_an_empty_queue_stops_immediately_and_cleanly(runs):
    """The good ending: nothing wanted attention, so nothing was left behind."""
    queue = FakeQueue()
    driver = AutoResearchDriver(runs, FakeTopics(), queue, run_round=_never_called)

    report = await driver.run(uuid4(), uuid4())

    assert report.reason == "queue_empty"
    assert report.rounds == 0
    assert report.finished_cleanly


async def test_a_run_works_the_queue_until_it_empties(runs):
    queue = FakeQueue(attention(), attention(), attention())
    topics = FakeTopics()

    async def work(topic_id, why):
        queue.resolve(topic_id)
        return RoundOutcome(findings=1)

    driver = AutoResearchDriver(runs, topics, queue, run_round=work)

    report = await driver.run(uuid4(), uuid4())

    assert report.reason == "queue_empty"
    assert report.rounds == 3
    assert report.findings == 3
    assert len(topics.looks) == 3
    assert report.finished_cleanly


async def test_the_round_is_told_why_its_topic_was_raised(runs):
    """What the agent needs in order to do the right thing with the round."""
    raised = attention(triggers=["topic.source_dropped"], evidence=["s1"])
    queue = FakeQueue(raised)
    seen = []

    async def work(topic_id, why):
        seen.append((topic_id, why.triggers, why.evidence))
        queue.resolve(topic_id)
        return RoundOutcome(findings=1)

    await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(uuid4(), uuid4())

    assert seen == [(raised.topic_id, ("topic.source_dropped",), ("s1",))]


async def test_a_look_is_recorded_even_when_the_round_finds_nothing(runs):
    """An unrecorded look is indistinguishable from no look at all.

    Without this the same topic comes back next round for the same reason, and
    the run re-reads the same material until its budget runs out.
    """
    queue = FakeQueue(attention())
    topics = FakeTopics()

    async def work(topic_id, why):
        queue.resolve(topic_id)
        return RoundOutcome()

    await AutoResearchDriver(runs, topics, queue, run_round=work).run(uuid4(), uuid4())

    assert len(topics.looks) == 1


async def test_novelty_decay_stops_a_run_the_queue_would_never_empty(runs):
    """The queue keeps offering the same topic; the run must not keep taking it."""
    queue = FakeQueue(attention())

    async def work(topic_id, why):
        return RoundOutcome()  # never resolves anything

    report = await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(
        uuid4(), uuid4(), budget=Budget(quiet_rounds=2, max_rounds=50)
    )

    assert report.reason == "no_new_findings"
    assert report.rounds == 2


async def test_a_failing_round_does_not_end_the_run_but_a_streak_does(runs):
    queue = FakeQueue(attention())
    attempts = []

    async def work(topic_id, why):
        attempts.append(topic_id)
        raise RuntimeError("boom")

    report = await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(
        uuid4(), uuid4(), budget=Budget(max_consecutive_failures=3, max_rounds=50)
    )

    assert report.reason == "error_rate"
    assert len(attempts) == 3


async def test_a_run_that_stops_early_reports_what_it_left_behind(runs):
    """A stop with work outstanding must not read as success."""
    queue = FakeQueue(attention(), attention(), attention())

    async def work(topic_id, why):
        return RoundOutcome()

    report = await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(
        uuid4(), uuid4(), budget=Budget(quiet_rounds=1, max_rounds=50)
    )

    assert report.reason == "no_new_findings"
    assert report.unexamined_topics == 3
    assert not report.finished_cleanly


async def test_max_rounds_bounds_a_run_whose_rounds_keep_producing(runs):
    """A run that never stops learning still has to stop."""
    queue = FakeQueue(attention())

    async def work(topic_id, why):
        return RoundOutcome(findings=1)

    report = await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(
        uuid4(), uuid4(), budget=Budget(max_rounds=4)
    )

    assert report.reason == "max_rounds"
    assert report.rounds == 4


async def test_a_cancelled_run_stops_between_rounds_and_records_why(runs):
    """`cancelled` is a reason in the log, not a run that simply goes quiet.

    Asked between rounds rather than during one, so the round in flight
    finishes: the alternative abandons a turn mid-write and leaves the stream
    with no stop event at all.
    """
    queue = FakeQueue(attention())
    stop_after = []

    async def work(topic_id, why):
        stop_after.append(topic_id)
        return RoundOutcome(findings=1)

    report = await AutoResearchDriver(runs, FakeTopics(), queue, run_round=work).run(
        uuid4(),
        uuid4(),
        budget=Budget(max_rounds=50, quiet_rounds=50),
        cancelled=lambda: bool(stop_after),
    )

    assert report.reason == "cancelled"
    assert report.rounds == 1
    assert report.unexamined_topics == 1
    assert not report.finished_cleanly


async def test_a_run_can_be_named_before_it_starts(runs):
    """So a caller that starts one in the background can report on it at once."""
    named = uuid4()

    report = await AutoResearchDriver(
        runs, FakeTopics(), FakeQueue(), run_round=_never_called
    ).run(uuid4(), uuid4(), run_id=named)

    assert report.run_id == named


async def test_a_run_that_starts_cancelled_does_no_work(runs):
    report = await AutoResearchDriver(
        runs, FakeTopics(), FakeQueue(attention()), run_round=_never_called
    ).run(uuid4(), uuid4(), cancelled=lambda: True)

    assert report.reason == "cancelled"
    assert report.rounds == 0


async def test_the_report_only_calls_a_run_clean_when_nothing_is_outstanding():
    stopped_early = RunReport(
        run_id=uuid4(), reason="max_rounds", rounds=4, findings=1, unexamined_topics=2
    )
    assert not stopped_early.finished_cleanly

    drained = RunReport(
        run_id=uuid4(), reason="queue_empty", rounds=4, findings=1, unexamined_topics=0
    )
    assert drained.finished_cleanly


async def _never_called(topic_id, why):
    raise AssertionError("the round should not have run")
