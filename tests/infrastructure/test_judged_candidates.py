"""What a human's judgements do to consolidation's candidate list.

Asserted against fakes rather than a real `CandidateFinder`: the point of this
class is what it adds and removes, and a real finder would make every
assertion depend on scoring behaviour these tests are not about.
"""

from uuid import uuid4

import pytest
from redstring.consolidation.candidates import ScoredCandidate
from redstring.domain.similarity import SimilarityFeatures

from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    evolve,
    initial_state,
    normalize_name,
)
from research_team.infrastructure.knowledge.judged_candidates import JudgedCandidates

TENANT = uuid4()


class _Entity:
    """Enough of redstring's `Entity` for these tests: an id, a name, a type.

    Carries `normalized_name` because the real entity does and `_FakeGraph`
    matches on it exactly -- see that method for why the fake must not be more
    forgiving than the store it stands in for.
    """

    def __init__(self, name: str, entity_type: str = "person") -> None:
        self.id = uuid4()
        self.name = name
        self.normalized_name = normalize_name(name)
        self.entity_type = entity_type


class _FakeInner:
    def __init__(self, *candidates: ScoredCandidate) -> None:
        self._candidates = list(candidates)
        self.asked_with: float | None = None

    async def candidates(self, subject, *, minimum_score: float = 0.0):
        self.asked_with = minimum_score
        return list(self._candidates)


class _FakeGraph:
    """Answers `find_entities(name=...)` the way redstring's stores do."""

    def __init__(self, *entities: _Entity) -> None:
        self._entities = list(entities)

    async def find_entities(self, tenant_id, *, name=None, **_):
        """Compares `normalized_name` to `name` **exactly**, as the real store does.

        `InMemoryGraphStore.find_entities` does not normalise its argument --
        it matches `entity.normalized_name == name` and nothing more. A fake
        that normalised both sides would accept a caller passing a raw name,
        and every test here would still pass while production matched nothing:
        the silent "the judgement did nothing" failure that `EntityKey.of`
        exists to prevent. Being exactly as unforgiving as the real store is
        what makes this file able to catch that.
        """
        if name is None:
            return list(self._entities)
        return [e for e in self._entities if e.normalized_name == name]


def _scored(entity: _Entity, score: float) -> ScoredCandidate:
    return ScoredCandidate(entity=entity, features=SimilarityFeatures(name=score), score=score)


def _state(*events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


@pytest.mark.asyncio
async def test_a_held_same_counterpart_is_injected_even_when_it_scores_nothing():
    """The `JFK` case, and the reason injection exists rather than reweighting.

    `JFK`/`John F. Kennedy` scores 0.609 against a real embedding model and
    shares no blocking prefix, so `CandidateFinder` never surfaces it at all --
    no threshold change reaches a candidate that is never built. The inner
    finder here returns nothing, which is exactly that situation.

    Would pass with the feature removed only if the inner finder returned the
    counterpart itself; it deliberately returns an empty list so it cannot.
    """
    subject = _Entity("JFK")
    counterpart = _Entity("John F. Kennedy")
    finder = JudgedCandidates(
        _FakeInner(),
        graph_store=_FakeGraph(counterpart),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[
                    EntityKey.of("JFK", "person"),
                    EntityKey.of("John F. Kennedy", "person"),
                ],
                reason="same man",
            )
        ),
    )

    found = await finder.candidates(subject, minimum_score=0.75)

    assert [c.entity.id for c in found] == [counterpart.id]
    assert found[0].score == 1.0, "above HIGH_SIMILARITY, so it merges without a model call"


@pytest.mark.asyncio
async def test_a_held_distinct_candidate_is_dropped_before_it_is_scored():
    """Dropped rather than vetoed at the adjudicator, which is the whole reason
    the seam is the finder.

    An adjudicator-level veto is skipped entirely by a pair scoring at or above
    `HIGH_SIMILARITY` -- unreachable cross-document today, reachable if B58
    lands, where `Retriever`/`Retrievers` scores 0.968. The 1.0 here is that
    case.
    """
    subject = _Entity("Iran", "place")
    other = _Entity("Iraq", "place")
    finder = JudgedCandidates(
        _FakeInner(_scored(other, 1.0)),
        graph_store=_FakeGraph(other),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldDistinct(
                aggregate_id=TENANT,
                left=EntityKey.of("Iran", "place"),
                right=EntityKey.of("Iraq", "place"),
                reason="different countries",
            )
        ),
    )

    assert await finder.candidates(subject, minimum_score=0.75) == []


@pytest.mark.asyncio
async def test_an_empty_judgement_set_changes_nothing():
    """The property that makes this safe to wire in before any UI exists."""
    subject = _Entity("Grant")
    other = _Entity("Dr. Grant")
    inner = _FakeInner(_scored(other, 0.8))
    finder = JudgedCandidates(
        inner, graph_store=_FakeGraph(other), tenant_id=TENANT, judgements=initial_state()
    )

    found = await finder.candidates(subject, minimum_score=0.75)

    assert [(c.entity.id, c.score) for c in found] == [(other.id, 0.8)]
    assert inner.asked_with == 0.75, "the threshold is passed through untouched"


@pytest.mark.asyncio
async def test_the_subject_is_never_its_own_candidate():
    """A group contains the subject's own key, so the lookup finds the subject.

    The fake graph holds an entity named "John F. Kennedy" -- the counterpart
    key's name, which is what `_injected` searches for once it skips the
    subject's own key -- but that entity carries `subject.id` (a distinct
    object, id assigned to match, since the graph is answered by name and
    would otherwise never be asked about "JFK" at all). So the lookup finds
    an entity whose id equals the subject's, and the `entity.id ==
    subject.id` guard in `_injected` is what excludes it from the result.

    Written the other way -- a graph containing only an entity named "JFK",
    as the brief originally had it -- the lookup for the counterpart key
    matches nothing at all, the guard is never exercised, and this test would
    still pass with the guard deleted from `_injected`. Verified: with the
    guard's `if entity.id == subject.id: continue` removed from
    `judged_candidates.py`, this version of the test fails (the excluded
    entity comes back as a candidate); the brief's original version still
    passed.

    **The fixture is impossible in production, and the guard is unreachable
    there.** Two entities cannot share an id in a real graph store. And
    `_injected` skips `key == subject_key`, so the only way a lookup returns
    the subject at all is a key carrying the subject's `normalized_name` under
    a *different* `entity_type` -- which the `entity.entity_type !=
    key.entity_type` check one line later excludes, not the id guard. So this
    manufactures a state the system cannot reach, to exercise one line of
    defence-in-depth against a future store or lookup path. Said plainly
    because the paragraphs above argue carefully that this version is the
    honest one, and leaving it out would let the test read as proving more
    than it does.
    """
    subject = _Entity("JFK")
    impostor = _Entity("John F. Kennedy")
    impostor.id = subject.id
    finder = JudgedCandidates(
        _FakeInner(),
        graph_store=_FakeGraph(impostor),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[
                    EntityKey.of("JFK", "person"),
                    EntityKey.of("John F. Kennedy", "person"),
                ],
                reason="r",
            )
        ),
    )

    assert await finder.candidates(subject) == []


@pytest.mark.asyncio
async def test_an_injected_candidate_is_not_duplicated_when_the_finder_also_found_it():
    subject = _Entity("JFK")
    counterpart = _Entity("John F. Kennedy")
    finder = JudgedCandidates(
        _FakeInner(_scored(counterpart, 0.8)),
        graph_store=_FakeGraph(counterpart),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[
                    EntityKey.of("JFK", "person"),
                    EntityKey.of("John F. Kennedy", "person"),
                ],
                reason="r",
            )
        ),
    )

    found = await finder.candidates(subject)

    assert len(found) == 1
    assert found[0].score == 1.0, "the judgement wins over the computed score"


@pytest.mark.asyncio
async def test_candidates_come_back_in_descending_score_with_ties_broken_by_id():
    """`CandidateSource`'s ordering contract, and it is not cosmetic: a cutoff
    falling inside a tie must be decided the same way on every run, or
    consolidation stops being reproducible. Injected candidates all score 1.0
    and so are all one tie.
    """
    subject = _Entity("JFK")
    first, second = _Entity("John F. Kennedy"), _Entity("Kennedy")
    finder = JudgedCandidates(
        _FakeInner(_scored(_Entity("Someone"), 0.9)),
        graph_store=_FakeGraph(first, second),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[
                    EntityKey.of("JFK", "person"),
                    EntityKey.of("John F. Kennedy", "person"),
                    EntityKey.of("Kennedy", "person"),
                ],
                reason="r",
            )
        ),
    )

    found = await finder.candidates(subject)

    assert [c.score for c in found] == sorted((c.score for c in found), reverse=True)
    injected = [str(c.entity.id) for c in found if c.score == 1.0]
    assert injected == sorted(injected)
