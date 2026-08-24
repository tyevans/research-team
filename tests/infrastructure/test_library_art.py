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


def _candidate(
    slug: str, title: str, category: str = "work", membership_hash: str = "h"
) -> CourseCandidate:
    return CourseCandidate(
        slug=slug,
        title=title,
        category=category,
        prominence=1.0,
        size=1,
        membership_hash=membership_hash,
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
    await candidate_art.put(project_id, "already-assigned", art_id, "h")
    provider = LibraryArtProvider(art, candidate_art, _FakeFallback())

    result = await provider.for_candidate(
        project_id, _candidate("already-assigned", "Anything at all")
    )

    assert result.url == f"/api/art/{art_id}.svg"


async def test_a_drifted_assignment_is_upgraded_to_a_fresh_library_match(stores):
    """A candidate whose art was assigned against a since-changed
    `membership_hash` is treated as needing art, exactly like a candidate
    with no assignment -- the art-refresh feature's read path. If the
    library now has something that matches better, it is picked up on the
    very next read; the old piece stays in the library but stops counting
    this candidate among its uses.
    """
    art, candidate_art = stores
    old_id = uuid4()
    await art.put(
        art_id=old_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="old picture, nothing in particular",
        tags=[],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    project_id = uuid4()
    # Assigned against a hash the candidate no longer carries -- the
    # drifted case.
    await candidate_art.put(project_id, "warp-drive", old_id, "old-hash")
    await art.increment_uses(old_id)

    new_id = uuid4()
    await art.put(
        art_id=new_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="warp drive propulsion engineering",
        tags=["work"],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    provider = LibraryArtProvider(art, candidate_art, _FakeFallback())

    candidate = _candidate("warp-drive", "Warp drive propulsion", membership_hash="new-hash")
    result = await provider.for_candidate(project_id, candidate)

    assert result.url == f"/api/art/{new_id}.svg"
    reassigned = await candidate_art.get(project_id, "warp-drive")
    assert reassigned.art_id == new_id
    assert reassigned.membership_hash == "new-hash"
    old_row = await art.get(old_id)
    new_row = await art.get(new_id)
    assert old_row.uses == 0
    assert new_row.uses == 1


async def test_a_drifted_assignment_with_no_better_match_keeps_its_picture(stores):
    """Staleness alone must not discard a candidate's existing art down to
    the fallback -- only the sweep generates a replacement for a drifted
    candidate the library still has nothing for (see `library_art.py`'s
    docstring on why a model call per catalog read is out of the
    question)."""
    art, candidate_art = stores
    art_id = uuid4()
    await art.put(
        art_id=art_id,
        svg="<svg viewBox='0 0 1 1'></svg>",
        description="nothing that shares a token with the query",
        tags=[],
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
    )
    project_id = uuid4()
    await candidate_art.put(project_id, "warp-drive", art_id, "old-hash")
    fallback = _FakeFallback()
    provider = LibraryArtProvider(art, candidate_art, fallback)

    result = await provider.for_candidate(
        project_id, _candidate("warp-drive", "Zzz Qqq Xxx", membership_hash="new-hash")
    )

    assert result.url == f"/api/art/{art_id}.svg"
    assert fallback.calls == 0


async def test_a_row_written_before_membership_hash_existed_reads_as_stale():
    """A `CandidateArtRow` written before this feature shipped has no
    `membership_hash` column and `apply_schema` reconciles it in as `""` --
    which must never equal a real candidate's hash (a sha256 hex digest, so
    never empty), or every pre-existing assignment would silently never
    refresh again. Simulated the same way
    `test_a_database_written_before_a_field_existed_gains_its_column`
    (CLAUDE.md's own precedent) does: drop the column back off and reopen.
    """
    import aiosqlite

    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/art.db"
        candidate_art = await CandidateArtStore.open(db_path)
        project_id = uuid4()
        art_id = uuid4()
        await candidate_art.put(project_id, "warp-drive", art_id, "h")
        await candidate_art.close()

        async with aiosqlite.connect(db_path) as raw:
            await raw.execute("ALTER TABLE candidate_art DROP COLUMN membership_hash")
            await raw.commit()

        reopened = await CandidateArtStore.open(db_path)
        try:
            row = await reopened.get(project_id, "warp-drive")
            assert row.membership_hash == ""
            # And it disagrees with any real hash a candidate would carry.
            assert row.membership_hash != "h"
        finally:
            await reopened.close()
