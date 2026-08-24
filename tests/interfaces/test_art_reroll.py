"""`ArtReroll`: regenerates one candidate's art, dropping its current
assignment, and never searches the library first -- see `art_sweep.py`'s
`ArtReroll` docstring for why. Modelled on `test_art_sweep.py`'s fakes."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from research_team.application.course_catalog import DraftArt
from research_team.domain.learning_area import AreaMember
from research_team.interfaces.web.art_sweep import ArtReroll, RerollAlreadyActive


class _FakeArtStore:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []
        self.decrement_calls: list = []

    async def put(self, **kwargs):
        self.put_calls.append(kwargs)

    async def decrement_uses(self, art_id):
        self.decrement_calls.append(art_id)


class _Assignment(SimpleNamespace):
    pass


class _FakeCandidateArtStore:
    def __init__(self, assigned: dict[str, tuple] | None = None) -> None:
        # slug -> (art_id, membership_hash) of the assignment before the
        # reroll, if any.
        self._assigned = assigned or {}
        self.put_calls: list[tuple] = []

    async def get(self, project_id, slug):
        if slug not in self._assigned:
            return None
        art_id, membership_hash = self._assigned[slug]
        return _Assignment(art_id=art_id, membership_hash=membership_hash)

    async def put(self, project_id, slug, art_id, membership_hash):
        self.put_calls.append((project_id, slug, art_id, membership_hash))
        self._assigned[slug] = (art_id, membership_hash)


class _FakeGenerator:
    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse
        self.calls: list[str] = []

    async def generate(self, title, anchors):
        self.calls.append(title)
        if self.refuse:
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


async def test_a_reroll_never_asks_the_matcher_and_always_generates():
    """The whole point of `ArtReroll`: unlike `ArtSweep`, there is no
    matcher parameter at all -- a reroll cannot silently reuse whatever
    library piece produced the picture the user is trying to get away
    from."""
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore(assigned={"warp": (uuid4(), "h")})
    generator = _FakeGenerator()
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), generator)
    await reroll.wait(project_id, "warp")

    assert generator.calls == ["Warp"]
    assert reroll.progress(project_id, "warp") == {
        "running": False,
        "done": 1,
        "total": 1,
        "failed": 0,
    }


async def test_a_reroll_drops_the_old_assignment_and_decrements_its_uses():
    art_store = _FakeArtStore()
    old_art_id = uuid4()
    candidate_art = _FakeCandidateArtStore(assigned={"warp": (old_art_id, "h")})
    generator = _FakeGenerator()
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), generator)
    await reroll.wait(project_id, "warp")

    assert art_store.decrement_calls == [old_art_id]
    [put_call] = candidate_art.put_calls
    assert put_call[1] == "warp"
    assert put_call[2] != old_art_id
    assert put_call[3] == "h"


async def test_a_refusal_is_counted_failed_and_leaves_the_assignment_untouched():
    art_store = _FakeArtStore()
    old_art_id = uuid4()
    candidate_art = _FakeCandidateArtStore(assigned={"warp": (old_art_id, "h")})
    generator = _FakeGenerator(refuse=True)
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), generator)
    await reroll.wait(project_id, "warp")

    assert reroll.progress(project_id, "warp") == {
        "running": False,
        "done": 0,
        "total": 1,
        "failed": 1,
    }
    assert candidate_art.put_calls == []
    assert art_store.decrement_calls == []


async def test_two_candidates_can_reroll_at_once_without_sharing_a_frame():
    """Unlike `ArtSweep`, a second reroll on a *different* candidate in the
    same project must not be refused -- only the same `(project_id, slug)`
    is serialised."""
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), _FakeGenerator())
    await reroll.start(project_id, "impulse", _candidate("impulse"), _FakeGenerator())
    await reroll.wait(project_id, "warp")
    await reroll.wait(project_id, "impulse")

    assert reroll.progress(project_id, "warp")["done"] == 1
    assert reroll.progress(project_id, "impulse")["done"] == 1


async def test_a_second_reroll_on_the_same_candidate_while_one_is_active_is_refused():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), _FakeGenerator())
    with pytest.raises(RerollAlreadyActive):
        await reroll.start(project_id, "warp", _candidate("warp"), _FakeGenerator())
    await reroll.wait(project_id, "warp")


async def test_a_crash_settles_the_frame_with_an_error_rather_than_hanging_at_running_true():
    art_store = _FakeArtStore()
    candidate_art = _FakeCandidateArtStore()
    reroll = ArtReroll(art_store, candidate_art)
    project_id = uuid4()

    await reroll.start(project_id, "warp", _candidate("warp"), _RaisingGenerator())
    await reroll.wait(project_id, "warp")

    frame = reroll.progress(project_id, "warp")
    assert frame["running"] is False
    assert "error" in frame
    assert "boom" in frame["error"]


async def test_progress_for_a_candidate_never_rerolled_answers_not_running():
    reroll = ArtReroll(_FakeArtStore(), _FakeCandidateArtStore())

    assert reroll.progress(uuid4(), "warp") == {
        "running": False,
        "done": 0,
        "total": 0,
        "failed": 0,
    }
