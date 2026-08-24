"""The blurb sweep: writes copy for every candidate that lacks it or has
outgrown it, in the background, one run per project.

Modelled on `tests/interfaces/test_authoring.py`'s shape for
`AuthoringActivity` -- one run at a time, in-memory progress, a refused
second start -- but there is no aggregate underneath this one and no test
here reads anything back off a log, because nothing on the log describes a
blurb (see `research_team/interfaces/web/blurb_sweep.py`'s module docstring).
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.course_catalog import DraftBlurb
from research_team.domain.learning_area import AreaMember
from research_team.interfaces.web.blurb_sweep import BlurbSweep, SweepAlreadyActive


class _FakeCache:
    """Records every `put`, and answers `get` from a seeded table.

    Not `CachedBlurb` fixtures shared with `test_catalog_service.py`: this
    module only needs the one field the sweep actually branches on
    (`membership_hash`), and reusing that fixture would drag a `title` and
    `model` a hash-only test has no use for.
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


async def test_the_sweep_writes_a_blurb_for_every_candidate_that_lacks_one():
    cache = _FakeCache()
    writer = _FakeWriter()
    sweep = BlurbSweep(cache)
    project_id = uuid4()

    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    await sweep.start(project_id, candidates, writer)
    await sweep.wait(project_id)

    assert len(cache.put_calls) == 3
    progress = sweep.progress(project_id)
    assert progress == {"running": False, "done": 3, "total": 3, "failed": 0}


async def test_a_candidate_whose_blurb_matches_the_current_hash_is_skipped():
    cache = _FakeCache(seeded={"a": "h1"})
    writer = _FakeWriter()
    sweep = BlurbSweep(cache)
    project_id = uuid4()

    candidates = [_candidate("a", membership_hash="h1"), _candidate("b", membership_hash="h1")]
    await sweep.start(project_id, candidates, writer)
    await sweep.wait(project_id)

    assert [call[1] for call in cache.put_calls] == ["b"]


async def test_a_stale_cached_blurb_is_regenerated():
    """The hash on file is *not* the area's current hash -- this is the case
    a version that only checks presence would wrongly skip."""
    cache = _FakeCache(seeded={"a": "old-hash"})
    writer = _FakeWriter()
    sweep = BlurbSweep(cache)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("a", membership_hash="new-hash")], writer)
    await sweep.wait(project_id)

    assert len(cache.put_calls) == 1
    assert cache.put_calls[0][4] == "new-hash"


async def test_a_refusal_is_counted_and_does_not_stop_the_sweep():
    """A blurb the model will not ground is a card that keeps its title and
    its art -- exactly what increment 1 renders today. Stopping would let one
    stubborn cluster block every card behind it."""
    cache = _FakeCache()
    writer = _FakeWriter(refuse={"Stubborn"})
    sweep = BlurbSweep(cache)
    project_id = uuid4()

    candidates = [_candidate("a"), _candidate("stubborn"), _candidate("c")]
    # _candidate uses slug.title() for `title`, so "stubborn" -> "Stubborn".
    await sweep.start(project_id, candidates, writer)
    await sweep.wait(project_id)

    progress = sweep.progress(project_id)
    assert progress["failed"] == 1
    assert progress["done"] == 2
    assert len(cache.put_calls) == 2


async def test_a_second_sweep_while_one_runs_is_refused():
    cache = _FakeCache()
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowWriter:
        model_name = "slow-model"

        async def write(self, title, anchors):
            started.set()
            await release.wait()
            return DraftBlurb(title=title, text="slow copy")

    sweep = BlurbSweep(cache)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("a"), _candidate("b")], _SlowWriter())
    await started.wait()

    with pytest.raises(SweepAlreadyActive):
        await sweep.start(project_id, [_candidate("c")], _SlowWriter())

    release.set()
    await sweep.wait(project_id)


async def test_progress_for_a_project_that_never_swept_reports_not_running():
    sweep = BlurbSweep(_FakeCache())
    assert sweep.progress(uuid4()) == {"running": False, "done": 0, "total": 0, "failed": 0}
