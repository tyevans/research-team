"""The extraction queue: one document at a time, and no document twice.

Shaped like `test_dispatch_queue.py`, because the queue is shaped like
`DispatchQueue`. What is under test here is only where the two differ -- the
deduplication, the absence of any feed, and the bool `start` answers -- plus
the ordering and release guarantees that would be silently lost if this were
ever rewritten from the precedent rather than kept beside it.

Driven with plain futures rather than a real extractor: none of this involves
a model, and a test that needed one would be testing redstring.
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.knowledge import IngestReport
from research_team.interfaces.web.extraction_queue import ExtractionQueue


@pytest.fixture
def queue():
    return ExtractionQueue()


@pytest.fixture
def project_id():
    return uuid4()


def _report(source_id: str, *, entities: int = 3, relationships: int = 2) -> IngestReport:
    return IngestReport(
        source_id=source_id,
        entity_count=entities,
        relationship_count=relationships,
        domain=None,
        domain_confidence=None,
    )


def _run(
    source_id: str,
    *,
    gate: asyncio.Event | None = None,
    fail: str | None = None,
    seen: list[str] | None = None,
):
    """An extraction that finishes when told to, so ordering can be observed."""

    async def run():
        if seen is not None:
            seen.append(source_id)
        if gate is not None:
            await gate.wait()
        if fail is not None:
            raise RuntimeError(fail)
        return _report(source_id)

    return run


async def test_the_first_document_starts_and_reports_itself_running(queue, project_id):
    gate = asyncio.Event()
    assert queue.start(project_id, "s1", _run("s1", gate=gate)) is True

    # One turn of the loop is enough for the drain task to claim the item.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert queue.current(project_id) == "s1"
    assert queue.queued(project_id) == ()

    gate.set()
    await queue.wait(project_id)


async def test_a_second_document_waits_for_the_first(queue, project_id):
    gate = asyncio.Event()
    seen: list[str] = []
    queue.start(project_id, "s1", _run("s1", gate=gate, seen=seen))
    queue.start(project_id, "s2", _run("s2", seen=seen))

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert queue.current(project_id) == "s1"
    assert queue.queued(project_id) == ("s2",)
    # The second has not been awaited at all, which is the point of the factory:
    # a queued item is not a live coroutine.
    assert seen == ["s1"]

    gate.set()
    await queue.wait(project_id)
    assert seen == ["s1", "s2"]


async def test_a_document_already_queued_is_not_queued_again(queue, project_id):
    gate = asyncio.Event()
    seen: list[str] = []
    assert queue.start(project_id, "s1", _run("s1", gate=gate, seen=seen)) is True
    assert queue.start(project_id, "s2", _run("s2", seen=seen)) is True
    assert queue.start(project_id, "s2", _run("s2", seen=seen)) is False

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert queue.queued(project_id) == ("s2",)

    gate.set()
    await queue.wait(project_id)
    assert seen == ["s1", "s2"]


async def test_a_document_already_running_is_not_queued_again(queue, project_id):
    """The dedupe covers the running item, not just the deque.

    Proved red by comparing only against `_pending`: `s1` has been popped off
    the deque by the time this asks, so a check that looked only there would
    queue the document being extracted right now behind itself.
    """
    gate = asyncio.Event()
    queue.start(project_id, "s1", _run("s1", gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert queue.current(project_id) == "s1"

    assert queue.start(project_id, "s1", _run("s1")) is False
    assert queue.queued(project_id) == ()

    gate.set()
    await queue.wait(project_id)


async def test_a_document_that_has_finished_can_be_queued_again(queue, project_id):
    """Dedupe is about work in flight, not a permanent refusal.

    Re-extracting a document after it has been extracted is a legitimate thing
    to want -- a model changed, an extraction was thin -- and this queue must
    not be what forbids it.
    """
    queue.start(project_id, "s1", _run("s1"))
    await queue.wait(project_id)

    assert queue.start(project_id, "s1", _run("s1")) is True
    await queue.wait(project_id)


async def test_a_failure_is_recorded_and_the_queue_keeps_going(queue, project_id):
    seen: list[str] = []
    queue.start(project_id, "s1", _run("s1", fail="Too many requests", seen=seen))
    queue.start(project_id, "s2", _run("s2", seen=seen))
    await queue.wait(project_id)

    assert seen == ["s1", "s2"]
    outcomes = {item["source_id"]: item for item in queue.finished(project_id)}
    assert outcomes["s1"]["status"] == "failed"
    assert outcomes["s1"]["detail"] == "Too many requests"
    assert outcomes["s2"]["status"] == "done"
    assert outcomes["s2"]["entities"] == 3
    assert outcomes["s2"]["relationships"] == 2


async def test_cancel_drops_the_waiting_and_stops_the_running(queue, project_id):
    gate = asyncio.Event()
    seen: list[str] = []
    queue.start(project_id, "s1", _run("s1", gate=gate, seen=seen))
    queue.start(project_id, "s2", _run("s2", seen=seen))
    queue.start(project_id, "s3", _run("s3", seen=seen))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Two waiting plus the one in flight.
    assert queue.cancel(project_id) == 3
    await queue.wait(project_id)

    assert seen == ["s1"]
    assert queue.current(project_id) is None
    assert queue.queued(project_id) == ()


async def test_a_cancelled_project_can_be_queued_again(queue, project_id):
    """`_draining` is released in `finally`, so a cancel does not wedge the project.

    Proved red by discarding from `_draining` only on the normal return path:
    every later press is then appended to a deque whose drain task has gone,
    and nothing runs again for the life of the process.
    """
    gate = asyncio.Event()
    queue.start(project_id, "s1", _run("s1", gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    queue.cancel(project_id)
    await queue.wait(project_id)

    seen: list[str] = []
    assert queue.start(project_id, "s2", _run("s2", seen=seen)) is True
    await queue.wait(project_id)
    assert seen == ["s2"]


async def test_two_projects_extract_at_the_same_time(queue):
    """The one-at-a-time bound is per project, not per process.

    The model-call ceiling is redstring's business (`AGENT_EXTRACTION_CONCURRENCY`);
    this queue exists to keep one project's documents in order, and serialising
    unrelated projects against each other would buy nothing.
    """
    first, second = uuid4(), uuid4()
    gate = asyncio.Event()
    queue.start(first, "s1", _run("s1", gate=gate))
    queue.start(second, "s2", _run("s2", gate=gate))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert queue.current(first) == "s1"
    assert queue.current(second) == "s2"

    gate.set()
    await queue.wait(first)
    await queue.wait(second)


async def test_an_untouched_project_reads_empty(queue, project_id):
    """Passes with the change reverted -- it asserts the absence of state.

    Kept because the catch-up route calls all three of these on a project that
    has never queued anything, and a `KeyError` there would 500 the Documents
    page for every project nobody has pressed the button on.
    """
    assert queue.current(project_id) is None
    assert queue.queued(project_id) == ()
    assert queue.finished(project_id) == []
