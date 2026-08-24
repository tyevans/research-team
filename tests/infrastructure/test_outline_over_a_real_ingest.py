"""The both-ends test Task 13's brief and CLAUDE.md both ask for.

`OutlineTextPort` has exactly one production adapter (`ModelOutlineWriter`),
and per CLAUDE.md a port with one adapter and no test driving both ends is
two things that were never checked against each other -- the co-mention
channel shipped exactly that way, with every piece unit-tested, and produced
nothing for a whole release. This drives the *real* `ModelOutlineWriter`
against a live model, over anchors from a real ingest through
`build_application`/`create_app` (`composition.py`'s own wiring), through the
`GET /catalog/{slug}` route that generates and caches an outline
(`CourseService._outline_for`).

**Skips loudly, not silently**, when no live model answers at the configured
endpoint -- a silently skipped both-ends test is the same nothing the port
already had before this test existed.

**The mapping assertion this test exists to make.** `DraftOutline.sections`
is `tuple[tuple[str, str], ...]` -- positional, `(heading, summary)` -- and
`CourseOutlineRow.sections` is `list[dict]` keyed `heading`/`summary`.
`_LazyOutlineCache` in `composition.py` converts between the two by
position in both directions, so a transposed pair (a summary written into a
heading, or the reverse) would typecheck, round-trip, and render backwards
with nothing else in the suite asserting the pairing survived. This test
generates an outline once (a live model call, cached), then reads the same
candidate's detail page a second time -- a cache hit, no model call -- and
asserts the two responses carry byte-identical `heading`/`summary` pairs in
the same order. A transposition bug on either the write or the read side of
`_LazyOutlineCache` would still pass a same-shape assertion done once; only
comparing the freshly-generated response against the cached re-read exercises
both `put` and `get` on the same data and would catch either direction
disagreeing with itself.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_openai import ChatOpenAI
from redstring import Entity, ExtractionMethod, Provenance, Relationship

from research_team.application.course_catalog import CatalogService
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper
from research_team.interfaces.web import create_app

pytestmark = pytest.mark.asyncio

#: The reachable endpoint for live-model tests in this environment -- the
#: package default (`config.DEFAULT_BASE_URL`, `localhost:8080`) answers
#: nothing here. See CLAUDE.md/the project memory on live testing: this is
#: the address to use, and the model below is not to be swapped for a
#: different one on a whim -- it is what this environment actually serves.
_LIVE_BASE_URL = "http://192.168.1.14:8080/v1/"
_LIVE_MODEL = "qwen3.8-27b-64k-txt"
#: Not `qwen3.8-27b-mtp`, which is the same weights behind a different
#: serving profile and is what `config.model_name()` names. That profile
#: answers `/models` and then refuses every completion with `"unable to start
#: process: upstream command exited prematurely but successfully"` -- measured
#: 2026-08-23, and the reason this test skipped on the day it was written.
#: The 64k-txt profile at the same endpoint serves the same model and answers,
#: so this is a serving-profile choice rather than a different model, which is
#: why it does not count as swapping the model out from under the test.


def _live_model_unreachable_reason() -> str | None:
    """`None` when the configured live model actually answers a completion,
    else the reason it doesn't -- named so the skip that follows can quote it
    rather than say only "skipped".

    A real completion, not just a reachable `/models` listing: this
    endpoint's model-swap layer has answered a listed model with
    `"unable to start process: upstream command exited prematurely but
    successfully"` while `/models` itself was still returning 200 -- an
    address that is up and a model that will actually serve a request are two
    different facts, and only the second one is what this test needs.
    """
    try:
        response = httpx.post(
            f"{_LIVE_BASE_URL}chat/completions",
            json={
                "model": _LIVE_MODEL,
                "messages": [{"role": "user", "content": "say hi"}],
                "temperature": 0,
            },
            timeout=60.0,
        )
    except httpx.HTTPError as error:
        return f"{_LIVE_BASE_URL} is not reachable: {error}"
    if response.status_code != 200:
        return (
            f"{_LIVE_MODEL} at {_LIVE_BASE_URL} answered "
            f"{response.status_code}: {response.text}"
        )
    return None


class _NoFeatures:
    """A `CatalogFeatureStore` stand-in with nothing ever featured, matching
    `test_course_routes.py`'s own -- `_catalog` (`app.py`) refuses to build a
    catalog at all unless it can call `featured_for`."""

    async def featured_for(self, project_id):
        return {}


class _NoBlurbs:
    """A `BlurbCachePort` that has never cached anything, matching
    `test_course_routes.py`'s own -- nothing here asserts on blurb text, only
    on the outline, so a real blurb writer would just be an unused live-model
    call this test does not need."""

    async def get(self, project_id, slug):
        return None

    async def put(self, *args, **kwargs) -> None:  # pragma: no cover -- never called here
        raise AssertionError("nothing in this module caches a blurb")


def _entity(tenant_id: UUID, name: str) -> Entity:
    return Entity(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type="concept",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


async def _seed_one_cluster(application, project_id: str) -> None:
    """One four-clique of real, named entities -- exactly one candidate, so
    the anchors a real model writes from are real entity names rather than a
    stub's placeholder. Follows `test_course_routes.py::_seed_one_cluster`."""
    tenant_id = UUID(project_id)
    store = await application.graphs.open(tenant_id)
    # A realistic cluster, not a minimal one. Four entities was the first
    # version and it made this test skip every run: grounding is checked
    # against the cluster's membership, and a model asked to outline a course
    # on warp drive names the Vulcans and the Federation whether or not a
    # four-entity cluster happens to contain them. Measured 2026-08-23 against
    # the live model -- the outline it wrote was good and was refused on
    # `Vulcan` and `United Federation of Planets` alone.
    #
    # That refusal is the check working, not failing: an outline must not
    # promise coverage of entities the cluster does not hold. But a real
    # `LearningArea` from a real ingest holds dozens of members, so a
    # four-member fixture tests a stricter world than production has, and the
    # seam this test exists for never gets exercised.
    names = (
        "Zefram Cochrane",
        "The Phoenix",
        "Warp Drive Theory",
        "First Contact Day",
        "Vulcan",
        "Vulcans",
        "United Federation of Planets",
        "Starfleet",
        "Earth",
        "Bozeman, Montana",
        "Spacetime",
        "Faster-than-light travel",
        "Warp core",
        "Dilithium",
        "Enterprise",
        "Humanity",
    )
    entities = [_entity(tenant_id, name) for name in names]
    await store.upsert_entities(entities)
    edges = [
        Relationship(
            id=uuid4(),
            tenant_id=tenant_id,
            source_entity_id=left.id,
            target_entity_id=right.id,
            relationship_type="relates_to",
            confidence=1.0,
        )
        for i, left in enumerate(entities)
        for right in entities[i + 1 :]
    ]
    await store.upsert_relationships(edges)


async def test_an_outline_over_a_real_ingest_survives_its_own_cache_round_trip(db_path):
    """Drives the real writer against real anchors, not a stub against a
    stub.

    Skips when no real model answers at `_LIVE_BASE_URL`, and the skip is
    loud: a silently skipped both-ends test is the same nothing the port
    already had.
    """
    unreachable = _live_model_unreachable_reason()
    if unreachable is not None:
        pytest.skip(f"no live model to drive the real writer against: {unreachable}")

    model = ChatOpenAI(
        model=_LIVE_MODEL,
        base_url=_LIVE_BASE_URL,
        api_key="not-needed",
        temperature=0,
    )
    application = build_application(model=model, db_path=db_path)
    await application.start()
    curriculum = CurriculumService()
    catalog = CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    )
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        curriculum=curriculum,
        catalog=catalog,
        catalog_features=lambda: _NoFeatures(),
        course_service=application.course_service,
        course_repository=application.course_repository,
    )
    transport = ASGITransport(app=api)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects", json={"name": f"outline-real-ingest-{uuid4()}"}
            )
            assert created.status_code == 200
            project_id = created.json()["id"]

            await _seed_one_cluster(application, project_id)

            body = (await client.get(f"/api/projects/{project_id}/catalog")).json()
            all_candidates = [
                *body["hero"],
                *body["highlights"],
                *(c for cat in body["filed"] for c in cat["candidates"]),
            ]
            assert len(all_candidates) == 1, (
                "one four-clique should produce exactly one candidate -- if this "
                "fails, the seed or the grouper changed, not the outline path"
            )
            slug = all_candidates[0]["slug"]

            # First read: a cache miss, so `CourseService._outline_for` calls
            # the real `ModelOutlineWriter` and caches a non-refusal.
            first = await client.get(f"/api/projects/{project_id}/catalog/{slug}")
            assert first.status_code == 200
            first_outline = first.json()["outline"]

            if first_outline is None:
                # A real model is allowed to refuse -- ungrounded copy, too
                # few sections, an unparseable reply -- `OutlineTextPort`'s own
                # docstring says `None` is a legitimate answer, not a flake.
                # Nothing about the mapping can be asserted over an outline
                # that was never cached, so this is the honest, named stop
                # rather than a false pass.
                pytest.skip(
                    "the live model refused this outline (ungrounded, too few "
                    "sections, or unparseable) -- nothing to assert the "
                    "heading/summary mapping against this run"
                )

            # Second read: `candidate.membership_hash` has not changed, so
            # `_outline_for` returns the cached row without calling the model
            # again -- this is `OutlineCachePort.get` exercising the read side
            # of the exact conversion `.put` above exercised on the write
            # side, on the same data.
            second = await client.get(f"/api/projects/{project_id}/catalog/{slug}")
            assert second.status_code == 200
            second_outline = second.json()["outline"]
    finally:
        await application.close()

    assert second_outline is not None
    assert first_outline["promise"] == second_outline["promise"]
    assert len(first_outline["sections"]) >= 3
    assert first_outline["sections"] == second_outline["sections"]
    for section in first_outline["sections"]:
        # The mapping assertion itself: each `heading` and `summary` came
        # from the same position in the same `DraftOutline.sections` tuple.
        # A transposed pair -- the summary's long, ungrounded-entity-free
        # prose written into `heading` -- would still satisfy every assertion
        # above (the cache would round-trip its own mistake byte-for-byte),
        # so this checks the fields did not just round-trip consistently but
        # round-tripped the *right way round*: a heading is short prose
        # naming a topic, a summary is one or two full sentences, and
        # `outline_writer._PROMPT` asks for exactly that shape from the
        # model on both sides of the wire.
        assert section["heading"] != section["summary"]
        assert len(section["heading"]) < len(section["summary"])
