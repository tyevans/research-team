"""Grant lifecycle, registration, unattended tracking, and release tests
for ResearchRunDriver.
"""

import asyncio
from uuid import UUID, uuid4

import pytest

from research_team.research.application.research_run import (
    ResearchRunDriver,
    RoundOutcome,
)
from research_team.research.application.topic_attention import Finding, TopicAttention
from research_team.research.domain.run import ResearchRun
from research_team.tenancy.application.grants import GrantRegistry


def attention(topic_id=None, triggers=("topic.never_investigated",), evidence=()):
    return TopicAttention(
        topic_id=topic_id or uuid4(),
        findings=tuple(
            Finding(check=t, severity="blocking", message=t, cites=tuple(evidence))
            for t in triggers
        ),
    )


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
        return ResearchRun(run_id)

    async def save(self, aggregate):
        return None


@pytest.fixture
def runs():
    return FakeRuns()


class _ExplodingQueue:
    """Raises on the first `evaluate`, after the queue has been asked once
    for the pending count `exhausted()` reads (there is none) -- so `run()`
    reaches its own body and then dies mid-round, never reaching `_stop`."""

    async def evaluate(self, project_id):
        raise RuntimeError("the queue projection is down")


async def _never_called(topic_id, why):
    raise AssertionError("the round should not have run")


async def test_a_started_run_registers_its_grant_from_the_folded_state(runs):
    """From `run.state`, not from the `fetch_hosts`/`fetch_budget` arguments
    directly -- see the driver's docstring for why that is the one source
    that keeps the registry and the log from disagreeing.

    Checked mid-run (a gate the round holds open) rather than after `.run()`
    returns, because a run over one topic stops as soon as the round
    completes -- and stopping releases the grant, per the release test
    below. What this test pins is that the grant existed, with the right
    shape, *while the run was going*.
    """
    grants = GrantRegistry()
    session_id = uuid4()
    queue = FakeQueue(attention())
    gate = asyncio.Event()
    seen = {}

    async def work(topic_id, why):
        seen["grant"] = grants.get(session_id)
        await gate.wait()
        queue.resolve(topic_id)
        return RoundOutcome(findings=1)

    driver = ResearchRunDriver(runs, FakeTopics(), queue, run_round=work, grants=grants)
    task = asyncio.ensure_future(
        driver.run(uuid4(), session_id, fetch_hosts=["a.example"], fetch_budget=3)
    )
    await asyncio.sleep(0)
    gate.set()
    await task

    grant = seen["grant"]
    assert grant is not None
    assert grant.hosts == frozenset({"a.example"})
    assert grant.remaining == 3


async def test_a_run_granted_nothing_is_still_registered(runs):
    """Task 6's bounded wait keys off *being a run's session*, not off having
    hosts -- an ungranted run must still show up in the registry so an
    unanswerable approval on it times out instead of hanging forever."""
    grants = GrantRegistry()
    session_id = uuid4()
    queue = FakeQueue(attention())
    gate = asyncio.Event()
    seen = {}

    async def work(topic_id, why):
        seen["unattended"] = grants.is_unattended(session_id)
        seen["grant"] = grants.get(session_id)
        await gate.wait()
        queue.resolve(topic_id)
        return RoundOutcome(findings=1)

    driver = ResearchRunDriver(runs, FakeTopics(), queue, run_round=work, grants=grants)
    task = asyncio.ensure_future(driver.run(uuid4(), session_id))
    await asyncio.sleep(0)
    gate.set()
    await task

    assert seen["unattended"] is True
    grant = seen["grant"]
    assert grant is not None
    assert grant.hosts == frozenset()
    assert grant.covers("https://anything.example/") is False


async def test_a_stopped_runs_grant_is_released(runs):
    """The registry entry must not outlive the run it was scoped to. Checked
    against the same run: present while it works its one topic, gone once
    the queue empties and the run stops."""
    grants = GrantRegistry()
    session_id = uuid4()
    queue = FakeQueue(attention())
    gate = asyncio.Event()
    seen = {}

    async def work(topic_id, why):
        seen["grant_while_running"] = grants.get(session_id)
        await gate.wait()
        queue.resolve(topic_id)
        return RoundOutcome(findings=1)

    driver = ResearchRunDriver(runs, FakeTopics(), queue, run_round=work, grants=grants)
    task = asyncio.ensure_future(
        driver.run(uuid4(), session_id, fetch_hosts=["a.example"], fetch_budget=1)
    )
    await asyncio.sleep(0)
    gate.set()
    await task

    assert seen["grant_while_running"] is not None
    assert grants.get(session_id) is None
    assert grants.is_unattended(session_id) is False


async def test_without_a_registry_a_run_behaves_exactly_as_before(runs):
    """`grants=None` is the default, and every existing caller of `.run()` in
    this file relies on it: no registry, nothing registered, nothing to
    release, and no error either way."""
    driver = ResearchRunDriver(runs, FakeTopics(), FakeQueue(), run_round=_never_called)

    report = await driver.run(uuid4(), uuid4())

    assert report.reason == "queue_empty"


async def test_a_crash_mid_run_still_releases_the_grant(runs):
    """The gap a whole-branch review found: release lived only in `_stop`,
    and `run()` had no `try`/`finally` -- so an exception escaping the loop
    (from `self._queue.evaluate`, from `self._runs.save`, or a
    `CancelledError`) left the grant, and the `is_unattended` flag Task 6's
    bounded wait depends on, alive in the registry for the rest of the
    process's life. This is that path, forced with a queue that raises.
    """
    grants = GrantRegistry()
    session_id = uuid4()
    driver = ResearchRunDriver(
        runs, FakeTopics(), _ExplodingQueue(), run_round=_never_called, grants=grants
    )

    with pytest.raises(RuntimeError):
        await driver.run(uuid4(), session_id, fetch_hosts=["a.example"], fetch_budget=1)

    assert grants.get(session_id) is None
    assert grants.is_unattended(session_id) is False
