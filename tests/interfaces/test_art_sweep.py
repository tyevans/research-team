"""The art sweep: generates art for every candidate the library has neither
assigned nor matched, in the background, one run per project. Modelled on
`test_blurb_sweep.py` -- read it first for the shared shape."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from research_team.application.course_catalog import DraftArt
from research_team.domain.learning_area import AreaMember
from research_team.interfaces.web.art_sweep import ArtSweep, SweepAlreadyActive


class _FakeArtStore:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.decrement_calls: list = []

    async def put(self, **kwargs):
        self.put_calls.append(kwargs)

    async def decrement_uses(self, art_id):
        self.decrement_calls.append(art_id)


class _Assignment(SimpleNamespace):
    """`CandidateArtRow`-shaped enough for the sweep: an `art_id` and the
    `membership_hash` it was assigned against."""


class _FakeCandidateArtStore:
    def __init__(self, assigned: dict[str, str] | None = None) -> None:
        # slug -> the membership_hash the (fake) assignment was made
        # against, so a test can put a slug's assignment out of date with
        # `_candidate`'s current hash without a real store.
        self._assigned = assigned or {}
        self.put_calls: list[tuple] = []

    async def get(self, project_id, slug):
        if slug not in self._assigned:
            return None
        return _Assignment(art_id=object(), membership_hash=self._assigned[slug])

    async def put(self, project_id, slug, art_id, membership_hash):
        self.put_calls.append((project_id, slug, art_id, membership_hash))
        self._assigned[slug] = membership_hash


class _FakeMatcher:
    """`LibraryArtProvider`-shaped. `matches` names slugs `match` answers
    something (not `None`) for."""

    def __init__(self, matches: set[str] | None = None) -> None:
        self._matches = matches or set()
        self.calls: list[str] = []

    async def match(self, candidate):
        self.calls.append(candidate.slug)
        if candidate.slug in self._matches:
            return (object(), 0.9)
        return None


class _FakeGenerator:
    def __init__(self, refuse: set[str] | None = None) -> None:
        self._refuse = refuse or set()
        self.calls: list[str] = []

    async def generate(self, title, anchors):
        self.calls.append(title)
        if title in self._refuse:
            return None
        return DraftArt(svg="<svg viewBox='0 0 1 1'/>", description=f"Art for {title}.")


class _RaisingGenerator:
    async def generate(self, title, anchors):
        raise RuntimeError("boom")


def _candidate(slug: str, category: str = "work", membership_hash: str = "h"):
    return SimpleNamespace(
        slug=slug,
        title=slug.title(),
        category=category,
        membership_hash=membership_hash,
        anchors=(
            AreaMember(entity_id=f"{slug}-e", name=slug, entity_type="topic", centrality=1.0),
        ),
    )


async def test_a_candidate_already_assigned_is_skipped_and_counted_done():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore(assigned={"already": "h"})
    matcher = _FakeMatcher()
    generator = _FakeGenerator()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("already")], generator, matcher)
    await sweep.wait(project_id)

    assert sweep.progress(project_id) == {
        "running": False,
        "done": 1,
        "total": 1,
        "failed": 0,
    }
    assert generator.calls == []
    assert matcher.calls == []


async def test_a_candidate_the_library_already_matches_is_skipped_and_not_generated_for():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    matcher = _FakeMatcher(matches={"warp"})
    generator = _FakeGenerator()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("warp")], generator, matcher)
    await sweep.wait(project_id)

    assert sweep.progress(project_id)["done"] == 1
    assert sweep.progress(project_id)["failed"] == 0
    assert generator.calls == []
    # And no assignment written -- LibraryArtProvider.for_candidate is the
    # one place that resolves and records a match, on demand.
    assert candidate_art.put_calls == []


async def test_a_generated_candidate_is_stored_and_assigned():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    matcher = _FakeMatcher()
    generator = _FakeGenerator()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("warp", category="work")], generator, matcher)
    await sweep.wait(project_id)

    assert sweep.progress(project_id) == {
        "running": False,
        "done": 1,
        "total": 1,
        "failed": 0,
    }
    assert len(art_store.put_calls) == 1
    stored = art_store.put_calls[0]
    assert stored["source"] == "generated"
    assert stored["tags"] == ["work"]
    assert len(candidate_art.put_calls) == 1
    assert candidate_art.put_calls[0][1] == "warp"
    assert candidate_art.put_calls[0][2] == stored["art_id"]


async def test_a_refusal_is_counted_failed_and_writes_nothing():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    matcher = _FakeMatcher()
    generator = _FakeGenerator(refuse={"Warp"})
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("warp")], generator, matcher)
    await sweep.wait(project_id)

    assert sweep.progress(project_id) == {
        "running": False,
        "done": 0,
        "total": 1,
        "failed": 1,
    }
    assert art_store.put_calls == []
    assert candidate_art.put_calls == []


async def test_a_second_sweep_on_the_same_project_while_one_is_active_is_refused():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(
        project_id, [_candidate("a"), _candidate("b")], _FakeGenerator(), _FakeMatcher()
    )
    with pytest.raises(SweepAlreadyActive):
        await sweep.start(project_id, [_candidate("a")], _FakeGenerator(), _FakeMatcher())
    await sweep.wait(project_id)


async def test_a_crash_settles_the_frame_with_an_error_rather_than_hanging_at_running_true():
    """The exact regression `blurb_sweep._drive`'s `except` guards against --
    without it, an uncaught exception leaves `progress()` reporting
    `running: True` forever, indistinguishable from a sweep that is merely
    slow."""
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(project_id, [_candidate("warp")], _RaisingGenerator(), _FakeMatcher())
    await sweep.wait(project_id)

    frame = sweep.progress(project_id)
    assert frame["running"] is False
    assert "error" in frame
    assert "boom" in frame["error"]


async def test_progress_for_a_project_never_swept_answers_not_running():
    sweep = ArtSweep(_FakeArtStore(), _FakeCandidateArtStore())

    assert sweep.progress(uuid4()) == {
        "running": False,
        "done": 0,
        "total": 0,
        "failed": 0,
    }


async def test_a_drifted_assignment_is_regenerated_not_skipped():
    """A candidate whose assignment predates its current cluster
    (`membership_hash` disagrees) counts as needing art, exactly like an
    unassigned one -- the sweep's half of the art-refresh feature."""
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore(assigned={"warp": "old-hash"})
    matcher = _FakeMatcher()
    generator = _FakeGenerator()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(
        project_id, [_candidate("warp", membership_hash="new-hash")], generator, matcher
    )
    await sweep.wait(project_id)

    assert sweep.progress(project_id)["done"] == 1
    assert generator.calls == ["Warp"]
    assert len(candidate_art.put_calls) == 1
    assert candidate_art.put_calls[0][3] == "new-hash"
    # The old assignment's art loses this candidate's use.
    assert len(art_store.decrement_calls) == 1


async def test_force_regenerates_a_fresh_assignment_and_skips_matching():
    """`force=True` is what the whole-project "force" route uses: it must
    call the model even for a candidate whose assignment is already fresh,
    and must not let a library match short-circuit that -- see the module
    docstring for why a forced sweep that quietly re-matched most cards back
    to what they already had would defeat the point of forcing."""
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore(assigned={"warp": "h"})
    matcher = _FakeMatcher(matches={"warp"})
    generator = _FakeGenerator()
    sweep = ArtSweep(art_store, candidate_art)
    project_id = uuid4()

    await sweep.start(
        project_id, [_candidate("warp", membership_hash="h")], generator, matcher, force=True
    )
    await sweep.wait(project_id)

    assert sweep.progress(project_id)["done"] == 1
    assert generator.calls == ["Warp"]
    assert matcher.calls == []
    assert len(art_store.decrement_calls) == 1


async def test_a_raising_generator_costs_one_candidate_and_not_the_rest():
    """`test_blurb_sweep`'s equivalent, and the same deliberate change: a
    candidate whose generation raises is `failed` and the sweep carries on,
    where the sequential loop ended the run. Proved red by re-raising out of
    `sweep_one` instead of tallying -- `done` then reads 0."""

    class _SelectivelyRaising:
        async def generate(self, title, anchors):
            if title == "Warp":
                raise RuntimeError("boom")
            return DraftArt(svg="<svg viewBox='0 0 1 1'/>", description=f"Art for {title}.")

    art_store = _FakeArtStore()
    sweep = ArtSweep(art_store, _FakeCandidateArtStore())
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate("warp"), _candidate("xindi"), _candidate("borg")],
        _SelectivelyRaising(),
        _FakeMatcher(),
    )
    await sweep.wait(project_id)

    frame = sweep.progress(project_id)
    assert frame == {
        "running": False,
        "done": 2,
        "total": 3,
        "failed": 1,
        "error": frame["error"],
    }
    assert "boom" in frame["error"]
    assert len(art_store.put_calls) == 2


async def test_the_art_sweep_holds_the_configured_number_of_candidates_in_flight():
    """`test_blurb_sweep`'s ceiling test over the generator. Both bounds for
    the same reason -- see that test's docstring."""
    import asyncio

    in_flight = 0
    peak = 0
    release = asyncio.Event()

    class _CountingGenerator:
        async def generate(self, title, anchors):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await release.wait()
            in_flight -= 1
            return DraftArt(svg="<svg viewBox='0 0 1 1'/>", description="art")

    sweep = ArtSweep(_FakeArtStore(), _FakeCandidateArtStore(), concurrency=3)
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate(f"c{n}") for n in range(8)],
        _CountingGenerator(),
        _FakeMatcher(),
    )
    for _ in range(20):
        await asyncio.sleep(0)
    assert peak == 3

    release.set()
    await sweep.wait(project_id)
    assert sweep.progress(project_id) == {
        "running": False,
        "done": 8,
        "total": 8,
        "failed": 0,
    }


async def test_two_candidates_moving_off_one_picture_both_decrement_its_uses():
    """`ArtStore.decrement_uses` is a read-modify-write over one row, and the
    sweep is the only place two candidates can reach it at the same moment --
    a drifted assignment each, pointing at the same piece.

    This drives a store that models the real one's read-then-save rather than
    just recording calls, because a `decrement_calls` list would count two
    calls whether or not either was lost. Proved red by removing
    `async with uses_lock` from `_drive`: `uses` then ends at 1, both
    decrements having read the same 2.
    """
    import asyncio

    class _RaceyArtStore:
        """`_FakeArtStore` plus the real store's non-atomic decrement: a read,
        a yield to the loop (which `aiosqlite` does at every round trip), then
        a save."""

        def __init__(self) -> None:
            self.uses = 2
            self.put_calls: list[dict] = []

        async def put(self, **kwargs):
            self.put_calls.append(kwargs)

        async def decrement_uses(self, art_id):
            seen = self.uses
            await asyncio.sleep(0)
            self.uses = max(0, seen - 1)

    shared = object()

    class _SharedAssignmentStore(_FakeCandidateArtStore):
        async def get(self, project_id, slug):
            # Both candidates already point at one picture, assigned against
            # a hash that no longer matches -- so both drift and both
            # regenerate.
            return _Assignment(art_id=shared, membership_hash="stale")

    art_store = _RaceyArtStore()
    sweep = ArtSweep(art_store, _SharedAssignmentStore(), concurrency=2)
    project_id = uuid4()

    await sweep.start(
        project_id,
        [_candidate("warp"), _candidate("xindi")],
        _FakeGenerator(),
        _FakeMatcher(),
    )
    await sweep.wait(project_id)

    assert art_store.uses == 0
