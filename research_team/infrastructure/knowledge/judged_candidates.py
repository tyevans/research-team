"""Consolidation's candidate list, with a human's judgements applied.

redstring exposes `CandidateSource` as a Protocol and `Consolidator.resolve`
takes `finder=`, which is the whole seam this needs. One layer covers both
directions, at the place where "is this a candidate" is already decided.

**Why injection rather than reweighting.** `JFK`/`John F. Kennedy` scores 0.609
against a real embedding model (measured 2026-08-14; BACKLOG B58 carries the
table) and the two names share no blocking prefix, so `CandidateFinder` never
builds that candidate at all. No threshold or weight change reaches a pair that
is never scored. Injecting it sidesteps scoring, which is the only mechanism
that works for the cases this feature exists for.

**Why dropping rather than vetoing at the adjudicator.** A veto placed on
`MergeAdjudicator` is skipped entirely by any pair scoring at or above
`HIGH_SIMILARITY` (0.92), because that band merges without asking. That is
unreachable cross-document today -- a present `graph = 0.0` caps such a pair at
0.8 -- but becomes reachable if B58 lands, where `Retriever`/`Retrievers`
scores 0.968. Dropping at the candidate stage is correct under both, so the
seam does not have to move later.
"""

from typing import Any
from uuid import UUID

from redstring.consolidation.candidates import ScoredCandidate
from redstring.domain.similarity import SimilarityFeatures

from research_team.domain.judgements import EntityKey, JudgementsState

#: The score an injected candidate carries.
#:
#: Above `HIGH_SIMILARITY` (0.92), so a held-same pair merges without a model
#: call -- a human has already made the judgement the adjudicator would be
#: asked to make, and paying for it again would be asking a model to
#: second-guess the person who owns the graph.
JUDGED_SAME_SCORE = 1.0


class JudgedCandidates:
    """A `CandidateSource` that applies this project's judgements to another.

    With an empty judgement set this is a pure passthrough, which is what makes
    it safe to wire in before anything can create a judgement.
    """

    def __init__(
        self,
        inner: Any,
        *,
        graph_store: Any,
        tenant_id: UUID,
        judgements: JudgementsState,
    ) -> None:
        self._inner = inner
        self._graph = graph_store
        self._tenant_id = tenant_id
        self._judgements = judgements

    async def candidates(
        self, subject: Any, *, minimum_score: float = 0.0
    ) -> list[ScoredCandidate]:
        subject_key = EntityKey.of(subject.name, subject.entity_type)
        group = self._judgements.group_for(subject_key)

        found = await self._inner.candidates(subject, minimum_score=minimum_score)
        kept = [
            candidate
            for candidate in found
            if not self._judgements.are_held_distinct(
                subject_key, EntityKey.of(candidate.entity.name, candidate.entity.entity_type)
            )
        ]

        injected = await self._injected(subject, group)
        # Injected wins over computed: the same entity found by both keeps the
        # judgement's score, not the finder's.
        by_id = {candidate.entity.id: candidate for candidate in kept}
        by_id.update({candidate.entity.id: candidate for candidate in injected})

        # `CandidateSource` requires descending score with ties broken by a
        # further total order -- `CandidateFinder` uses ascending entity id as
        # a string. Injected candidates all share one score and so are all one
        # tie; without the second key a cutoff inside it would fall differently
        # between runs and consolidation would stop being reproducible.
        return sorted(by_id.values(), key=lambda c: (-c.score, str(c.entity.id)))

    async def _injected(
        self, subject: Any, group: frozenset[EntityKey]
    ) -> list[ScoredCandidate]:
        """Entities matching any other key in the subject's held-same group."""
        subject_key = EntityKey.of(subject.name, subject.entity_type)
        injected: list[ScoredCandidate] = []
        for key in group:
            if key == subject_key:
                continue
            entities = await self._graph.find_entities(
                self._tenant_id, name=key.normalized_name
            )
            for entity in entities:
                if entity.id == subject.id:
                    continue
                if entity.entity_type != key.entity_type:
                    continue
                injected.append(
                    ScoredCandidate(
                        entity=entity,
                        # Every feature absent, deliberately. The score did not
                        # come from these and saying otherwise would put a
                        # number nobody computed into the explanation a
                        # threshold decision is read back from.
                        features=SimilarityFeatures(),
                        score=JUDGED_SAME_SCORE,
                    )
                )
        return injected
