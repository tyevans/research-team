"""The blurb sweep: writes copy and outlines for every candidate that lacks
either or has outgrown them, in the background, one run per project.

Modelled on `tests/interfaces/test_authoring.py`'s shape for
`AuthoringActivity` -- one run at a time, in-memory progress, a refused
second start -- but there is no aggregate underneath this one and no test
here reads anything back off a log, because nothing on the log describes a
blurb or an outline (see
`research_team/interfaces/web/blurb_sweep.py`'s module docstring).

Outline generation used to happen inside `CourseService._outline_for`, on
demand behind a candidate's detail-page request; it has moved here, folded
into the same sweep rather than built as a second one beside it -- see the
module docstring's paragraph on independence for why `done`/`failed` count a
candidate by "did everything it needed come out fresh", not "did at least
one artifact get written".
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.course_catalog import DraftBlurb, DraftOutline
from research_team.domain.learning_area import AreaMember
from research_team.interfaces.web.blurb_sweep import BlurbSweep, SweepAlreadyActive


class _FakeCache:
    """Records every `put`, and answers `get` from a seeded table.

    Not `CachedBlurb` fixtures shared with `test_catalog_service.py`: this
    module only needs the one field the sweep actually branches on
    (`membership_hash`), and reusing that fixture would drag a `title` and
    `model` a hash-only test has no use for. Shared shape with
    `_FakeOutlineCache` below -- the sweep treats both caches identically.
    """

    def __init__(self, seeded: dict[str, str] | None = None) -> None:
        self._seeded = seeded or {}
        self.put_calls: list[tuple] = []

    async def get(self, project_id, slug):
        hash_ = self._seeded.get(slug)
        if hash_ is None:
            return None
        return _Cached(hash_)

    async def put(self, project_id, slug, title, text, membership_hash, model, generated_at):
        self.put_calls.append(
            (project_id, slug, title, text, membership_hash, model, generated_at)
        )


class _FakeOutlineCache:
    """`_FakeCache`'s shape, over `OutlineCachePort`'s `put` signature."""

    def __init__(self, seeded: dict[str, str] | None = None) -> None:
        self._seeded = seeded or {}
        self.put_calls: list[tuple] = []

    async def get(self, project_id, slug):
        hash_ = self._seeded.get(slug)
        if hash_ is None:
            return None
        return _Cached(hash_)

    async def put(
        self, project_id, slug, promise, sections, membership_hash, model, generated_at
    ):
        self.put_calls.append(
            (project_id, slug, promise, sections, membership_hash, model, generated_at)
        )


class _Cached:
    def __init__(self, membership_hash: str) -> None:
        self.membership_hash = membership_hash


class _FakeWriter:
    """`BlurbTextPort`-shaped. `refuse` names slugs `write` returns `None`
    for, matching how a real writer refuses ungrounded copy."""

    def __init__(self, refuse: set[str] | None = None) -> None:
        self.model_name = "fake-model"
        self._refuse = refuse or set()

    async def write(self, title: str, anchors) -> DraftBlurb | None:
        if title in self._refuse:
            return None
        return DraftBlurb(title=f"{title} (written)", text=f"Copy for {title}.")


class _FakeOutlineWriter:
    """`_FakeWriter`'s shape, over `OutlineTextPort`."""

    def __init__(self, refuse: set[str] | None = None) -> None:
        self.model_name = "fake-outline-model"
        self._refuse = refuse or set()

    async def write(self, title: str, anchors) -> DraftOutline | None:
        if title in self._refuse:
            return None
        return DraftOutline(promise=f"Learn {title}", sections=(("Intro", "Where it starts"),))


def _candidate(slug: str, membership_hash: str = "h1"):
    """The sliver of `CourseCandidate` the sweep reads: `slug`, `title`,
    `anchors`, `membership_hash`. A bare namespace rather than the real
    dataclass -- constructing one needs an `ArtRef` and a `category` this
    module never touches."""

    from types import SimpleNamespace

    return SimpleNamespace(
        slug=slug,
        title=slug.title(),
        anchors=(
            AreaMember(entity_id=f"{slug}-e", name=slug, entity_type="topic", centrality=1.0),
        ),
        membership_hash=membership_hash,
    )


async def test_the_sweep_writes_a_blurb_and_an_outline_for_every_candidate_that_lacks_one():
    cache = _FakeCache()
    outline_cache = _FakeOutlineCache()
    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    await sweep.start(project_id, candidates, _FakeWriter(), _FakeOutlineWriter())
    await sweep.wait(project_id)

    assert len(cache.put_calls) == 3
    assert len(outline_cache.put_calls) == 3
    progress = sweep.progress(project_id)
    assert progress == {"running": False, "done": 3, "total": 3, "failed": 0}


async def test_a_candidate_whose_blurb_and_outline_match_the_current_hash_is_skipped():
    cache = _FakeCache(seeded={"a": "h1"})
    outline_cache = _FakeOutlineCache(seeded={"a": "h1"})
    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    candidates = [_candidate("a", membership_hash="h1"), _candidate("b", membership_hash="h1")]
    await sweep.start(project_id, candidates, _FakeWriter(), _FakeOutlineWriter())
    await sweep.wait(project_id)

    assert [call[1] for call in cache.put_calls] == ["b"]
    assert [call[1] for call in outline_cache.put_calls] == ["b"]


async def test_a_stale_cached_blurb_and_outline_are_both_regenerated():
    """The hash on file is *not* the area's current hash -- this is the case
    a version that only checks presence would wrongly skip."""
    cache = _FakeCache(seeded={"a": "old-hash"})
    outline_cache = _FakeOutlineCache(seeded={"a": "old-hash"})
    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate("a", membership_hash="new-hash")],
        _FakeWriter(),
        _FakeOutlineWriter(),
    )
    await sweep.wait(project_id)

    assert len(cache.put_calls) == 1
    assert cache.put_calls[0][4] == "new-hash"
    assert len(outline_cache.put_calls) == 1
    assert outline_cache.put_calls[0][4] == "new-hash"


async def test_a_refusal_is_counted_and_does_not_stop_the_sweep():
    """A blurb the model will not ground is a card that keeps its title and
    its art -- exactly what increment 1 renders today. Stopping would let one
    stubborn cluster block every card behind it."""
    cache = _FakeCache()
    outline_cache = _FakeOutlineCache()
    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    candidates = [_candidate("a"), _candidate("stubborn"), _candidate("c")]
    # _candidate uses slug.title() for `title`, so "stubborn" -> "Stubborn".
    await sweep.start(
        project_id, candidates, _FakeWriter(refuse={"Stubborn"}), _FakeOutlineWriter()
    )
    await sweep.wait(project_id)

    progress = sweep.progress(project_id)
    assert progress["failed"] == 1
    assert progress["done"] == 2
    assert len(cache.put_calls) == 2
    # The outline writer never refused anything -- every candidate still gets
    # an outline, including the one whose blurb was refused. See the module
    # docstring: the two artifacts are attempted independently.
    assert len(outline_cache.put_calls) == 3


async def test_an_outline_refusal_alone_still_writes_the_blurb_and_counts_failed():
    """The mirror of the test above: a candidate whose *outline* the model
    refuses still gets its blurb written, and the candidate is `failed`
    overall -- not `done`, because it is not fully written. A version that
    only checked the blurb's outcome would report this sweep finished with
    every card complete while one card's outline pane stays empty.

    The refused title is `"Stubborn (written)"` and not `"Stubborn"`, which
    is this test doubling as the assertion for the title fix: the outline
    writer is now handed the title the blurb writer just chose rather than
    the one frozen into the candidate at `start()`. Set it back to
    `"Stubborn"` and this test fails on `failed == 1`, because the refusal
    never fires.
    """
    cache = _FakeCache()
    outline_cache = _FakeOutlineCache()
    sweep = BlurbSweep(cache, outline_cache, concurrency=1)
    project_id = uuid4()

    candidates = [_candidate("a"), _candidate("stubborn")]
    await sweep.start(
        project_id,
        candidates,
        _FakeWriter(),
        _FakeOutlineWriter(refuse={"Stubborn (written)"}),
    )
    await sweep.wait(project_id)

    progress = sweep.progress(project_id)
    assert progress["failed"] == 1
    assert progress["done"] == 1
    # Both candidates' blurbs were written -- the outline refusal did not
    # skip the blurb attempt.
    assert [call[1] for call in cache.put_calls] == ["a", "stubborn"]
    assert [call[1] for call in outline_cache.put_calls] == ["a"]


async def test_a_second_sweep_while_one_runs_is_refused():
    cache = _FakeCache()
    outline_cache = _FakeOutlineCache()
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowWriter:
        model_name = "slow-model"

        async def write(self, title, anchors):
            started.set()
            await release.wait()
            return DraftBlurb(title=title, text="slow copy")

    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    await sweep.start(
        project_id, [_candidate("a"), _candidate("b")], _SlowWriter(), _FakeOutlineWriter()
    )
    await started.wait()

    with pytest.raises(SweepAlreadyActive):
        await sweep.start(project_id, [_candidate("c")], _SlowWriter(), _FakeOutlineWriter())

    release.set()
    await sweep.wait(project_id)


async def test_a_raising_writer_costs_one_candidate_and_not_the_rest_of_the_sweep():
    """A writer that raises must settle the frame *and* leave the other
    candidates written. Two separate things, learned in two separate
    incidents.

    The frame half is older: the closing `running: False` write used to sit
    after the loop, so an exception partway through skipped it and left the
    frame at `running: True` permanently -- indistinguishable from a sweep
    that is merely slow, since nothing in production awaits the background
    task to notice it died.

    The survival half is this change. The sequential loop let the exception
    out of the `for`, which ended the whole run: over 71 candidates and two
    and a half hours of wall clock, one 502 from the endpoint would have left
    most cards bare. The raising candidate is now `failed`, `error` still
    marks the run as having hit a defect, and the other two are `done`.

    Keyed by title rather than by call count, deliberately: a counter would
    pick whichever candidate happened to reach the writer second, which under
    a concurrency ceiling above 1 is not a property of the sweep at all.
    """
    cache = _FakeCache()
    outline_cache = _FakeOutlineCache()

    class _CrashingWriter:
        model_name = "crashing-model"

        async def write(self, title, anchors):
            if title == "B":
                raise RuntimeError("model endpoint unreachable")
            return DraftBlurb(title=title, text="ok")

    sweep = BlurbSweep(cache, outline_cache)
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate("a"), _candidate("b"), _candidate("c")],
        _CrashingWriter(),
        _FakeOutlineWriter(),
    )
    await sweep.wait(project_id)

    progress = sweep.progress(project_id)
    assert progress["running"] is False
    assert progress["done"] == 2
    assert progress["failed"] == 1
    assert "error" in progress
    assert sorted(call[1] for call in cache.put_calls) == ["a", "c"]


async def test_progress_for_a_project_that_never_swept_reports_not_running():
    sweep = BlurbSweep(_FakeCache(), _FakeOutlineCache())
    assert sweep.progress(uuid4()) == {"running": False, "done": 0, "total": 0, "failed": 0}


async def test_the_sweep_holds_the_configured_number_of_candidates_in_flight():
    """The ceiling is both a floor and a cap, and both halves matter.

    `peak == 3` alone would pass against a sweep that never overlaps anything
    at all if the assertion were `<= 3`; `>= 2` alone would pass against an
    unbounded `gather` that puts all ten candidates on the endpoint at once.
    Together they pin the semaphore. Proved red twice: with `permits`
    replaced by `asyncio.Semaphore(len(candidates))` the peak is 10, and with
    the `gather` reverted to a `for` loop it is 1.

    The writer holds a barrier open rather than sleeping -- a `sleep`-based
    version of this measures the event loop's scheduling rather than the
    sweep's ceiling, and is the kind of timing-sensitive test CLAUDE.md warns
    fails under load for reasons unrelated to the code.
    """
    in_flight = 0
    peak = 0
    release = asyncio.Event()

    class _CountingWriter:
        model_name = "counting-model"

        async def write(self, title, anchors):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1
            return DraftBlurb(title=title, text="ok")

    sweep = BlurbSweep(_FakeCache(), _FakeOutlineCache(), concurrency=3)
    project_id = uuid4()
    candidates = [_candidate(f"c{n}") for n in range(10)]

    await sweep.start(project_id, candidates, _CountingWriter(), _FakeOutlineWriter())
    # Let every task that can start, start: three should be parked on the
    # barrier and seven on the semaphore.
    for _ in range(20):
        await asyncio.sleep(0)
    assert peak == 3

    release.set()
    await sweep.wait(project_id)
    assert sweep.progress(project_id)["done"] == 10


async def test_the_counts_are_right_when_candidates_finish_out_of_order():
    """Completion order is not submission order once the sweep overlaps, and
    the progress frame has to survive that.

    The first candidate is held until every other candidate has finished, so
    the sweep settles in an order that is the reverse of the list. Proved red
    by rebuilding the frame from an index into `candidates` instead of from
    the counters -- `done` then reads 1 at the end, because the last frame
    written is the one for the candidate at position 0.

    The intermediate assertion is the other half: a frame claiming more
    candidates done than exist would be a counter incremented on a path that
    also `continue`d, which is exactly the shape the sequential loop had.
    """
    frames: list[dict] = []
    first_may_finish = asyncio.Event()
    others_done = 0

    class _StaggeredWriter:
        model_name = "staggered-model"

        async def write(self, title, anchors):
            nonlocal others_done
            if title == "C0":
                await first_may_finish.wait()
            else:
                others_done += 1
                if others_done == 4:
                    first_may_finish.set()
            return DraftBlurb(title=title, text="ok")

    sweep = BlurbSweep(_FakeCache(), _FakeOutlineCache(), concurrency=5)
    project_id = uuid4()
    candidates = [_candidate(f"c{n}") for n in range(5)]

    await sweep.start(project_id, candidates, _StaggeredWriter(), _FakeOutlineWriter())
    while sweep.progress(project_id)["running"]:
        frames.append(sweep.progress(project_id))
        await asyncio.sleep(0)
    await sweep.wait(project_id)

    settled = sweep.progress(project_id)
    assert settled == {"running": False, "done": 5, "total": 5, "failed": 0}
    assert all(f["done"] + f["failed"] <= f["total"] for f in frames)
    assert [f["done"] for f in frames] == sorted(f["done"] for f in frames)


async def test_cancelling_the_sweep_cancels_the_model_calls_already_in_flight():
    """Not merely "stops submitting new ones".

    `asyncio.gather` carries cancellation into every child, so a writer parked
    on an endpoint that is taking a minute per call sees `CancelledError`
    rather than being left to finish and have its result thrown away. That is
    the property worth pinning: at concurrency 6 over 71 candidates, "stop
    submitting" would still take a minute to come to rest and would keep
    spending on results nobody will read.

    Reaches into `_tasks` deliberately -- there is no cancel route or public
    `cancel()` on this class today, and that gap is the point of the test
    rather than something it works around. If one is added, this is the
    assertion it has to keep true.
    """
    entered = 0
    cancelled = 0
    both_in = asyncio.Event()

    class _BlockingWriter:
        model_name = "blocking-model"

        async def write(self, title, anchors):
            nonlocal entered, cancelled
            entered += 1
            if entered == 2:
                both_in.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled += 1
                raise
            return DraftBlurb(title=title, text="never")

    sweep = BlurbSweep(_FakeCache(), _FakeOutlineCache(), concurrency=2)
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate("a"), _candidate("b"), _candidate("c")],
        _BlockingWriter(),
        _FakeOutlineWriter(),
    )
    await both_in.wait()
    sweep._tasks[project_id].cancel()
    await sweep.wait(project_id)

    # Both of them, not just the one the loop happened to be inside. A
    # sequential `for` would pass a `cancelled >= 1` version of this
    # assertion, which is why it counts.
    assert (entered, cancelled) == (2, 2)
    # Settled rather than stuck at `running: True`: a poller that pressed
    # cancel has no other way to learn the sweep came to rest.
    assert sweep.progress(project_id)["running"] is False
