"""`LibraryArtProvider`: prior assignment, then a library search match, then
a fallback -- and the assignment, once made, is stable across calls."""

import tempfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.domain.course_catalog import CourseCandidate
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.persistence.read_models import ArtStore, CandidateArtStore


class _FakeFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def for_candidate(self, project_id, candidate):
        self.calls += 1
        from research_team.domain.course_catalog import ArtRef

        return ArtRef(url="data:fallback", alt="fallback")


def _candidate(slug: str, title: str, category: str = "work") -> CourseCandidate:
    return CourseCandidate(
        slug=slug,
        title=title,
        category=category,
        prominence=1.0,
        size=1,
        membership_hash="h",
        anchors=(),
        art=None,  # type: ignore[arg-type]
    )


@pytest.fixture
async def stores():
    with tempfile.TemporaryDirectory() as tmp:
        art = await ArtStore.open(f"{tmp}/art.db")
        candidate_art = await CandidateArtStore.open(f"{tmp}/art.db")
        try:
            yield art, candidate_art
        finally:
            await art.close()
            await candidate_art.close()


async def test_a_search_match_above_threshold_is_assigned_and_stable_across_calls(stores):
    art, candidate_art = stores
    art_id = uuid4()
    await art.put(
        art_id=art_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="a glowing warp nacelle bending starlight",
        tags=["warp", "propulsion"],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    fallback = _FakeFallback()
    provider = LibraryArtProvider(
        art_store=art, candidate_art_store=candidate_art, fallback=fallback
    )
    project_id = uuid4()
    candidate = _candidate("warp-drive", "Warp drive propulsion")

    first = await provider.for_candidate(project_id, candidate)
    second = await provider.for_candidate(project_id, candidate)

    assert first == second
    assert first.url == f"/api/art/{art_id}.svg"
    assert fallback.calls == 0

    assigned = await candidate_art.get(project_id, "warp-drive")
    assert assigned is not None
    assert assigned.art_id == art_id


async def test_stability_holds_across_two_separately_constructed_providers(stores):
    """Simulates two separate `CatalogService.build` calls -- e.g. two
    requests hitting a fresh provider instance each time -- to confirm the
    stability comes from the stored assignment, not from any state held on
    the provider object itself."""
    art, candidate_art = stores
    art_id = uuid4()
    await art.put(
        art_id=art_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="a glowing warp nacelle bending starlight",
        tags=["warp", "propulsion"],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    project_id = uuid4()
    candidate = _candidate("warp-drive", "Warp drive propulsion")

    first_provider = LibraryArtProvider(art, candidate_art, _FakeFallback())
    first = await first_provider.for_candidate(project_id, candidate)

    second_provider = LibraryArtProvider(art, candidate_art, _FakeFallback())
    second = await second_provider.for_candidate(project_id, candidate)

    assert first.url == second.url == f"/api/art/{art_id}.svg"


async def test_no_library_match_falls_back_and_writes_no_assignment(stores):
    art, candidate_art = stores
    fallback = _FakeFallback()
    provider = LibraryArtProvider(art, candidate_art, fallback)
    project_id = uuid4()
    candidate = _candidate("unrelated", "Something entirely unrelated")

    result = await provider.for_candidate(project_id, candidate)

    assert result.url == "data:fallback"
    assert fallback.calls == 1
    assert await candidate_art.get(project_id, "unrelated") is None


async def test_a_prior_assignment_is_read_back_without_searching_again(stores):
    art, candidate_art = stores
    art_id = uuid4()
    await art.put(
        art_id=art_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="anything",
        tags=[],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    project_id = uuid4()
    await candidate_art.put(project_id, "already-assigned", art_id)
    provider = LibraryArtProvider(art, candidate_art, _FakeFallback())

    result = await provider.for_candidate(
        project_id, _candidate("already-assigned", "Anything at all")
    )

    assert result.url == f"/api/art/{art_id}.svg"
