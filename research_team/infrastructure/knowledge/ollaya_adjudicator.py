"""An entity consolidation adjudicator powered by Ollaya decision models.

Implements `redstring.MergeAdjudicator` via non-autoregressive decision calls.
"""

import asyncio
import logging
from collections.abc import Sequence

from redstring import AdjudicationVerdict, Entity, ScoredCandidate

from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient

logger = logging.getLogger(__name__)

#: Threshold on Ollaya's calibrated probability to declare two entities the same.
CONFIDENCE_THRESHOLD = 0.80

_QUESTION = {
    "is_same": {
        "type": "choice",
        "instructions": (
            "Do Entity A and Entity B refer to the exact same real-world entity, "
            "person, organization, concept, or historical subject?"
        ),
        "criteria": {
            "same": (
                "They refer to the exact same entity (e.g. acronym, full name, alias, "
                "title variant)"
            ),
            "distinct": (
                "They are different entities, different concepts, or there is "
                "insufficient evidence to equate them"
            ),
        },
    }
}


class OllayaAdjudicator:
    """Implements `redstring.MergeAdjudicator` using an Ollaya decision model."""

    def __init__(
        self,
        client: OllayaDecisionClient,
        *,
        model: str = "laya",
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        concurrency: int = 8,
    ) -> None:
        self._client = client
        self._model = model
        self._threshold = confidence_threshold
        self._sem = asyncio.Semaphore(concurrency)

    async def adjudicate(
        self, subject: Entity, candidates: Sequence[ScoredCandidate]
    ) -> list[AdjudicationVerdict | None]:
        """One verdict per candidate, positionally aligned."""
        tasks = [self._adjudicate_pair(subject, candidate) for candidate in candidates]
        return await asyncio.gather(*tasks)

    async def adjudicate_many(
        self, work: Sequence[tuple[Entity, Sequence[ScoredCandidate]]]
    ) -> list[list[AdjudicationVerdict | None]]:
        """Verdicts across multiple subjects, preserving positional structure."""
        return [await self.adjudicate(subject, candidates) for subject, candidates in work]

    async def _adjudicate_pair(
        self, subject: Entity, candidate: ScoredCandidate
    ) -> AdjudicationVerdict | None:
        cand_entity = candidate.entity
        state = (
            f"Entity A:\nName: {subject.name}\nType: {subject.entity_type}\n"
            f"Description: {subject.description or 'None'}\n\n"
            f"Entity B:\nName: {cand_entity.name}\nType: {cand_entity.entity_type}\n"
            f"Description: {cand_entity.description or 'None'}"
        )

        async with self._sem:
            try:
                result = await self._client.decide_raw(
                    state=state,
                    questions=_QUESTION,
                    model=self._model,
                )
                answer = result["answers"]["is_same"]
                prob_same = float(answer.get("probabilities", {}).get("same", 0.0))
                choice = answer.get("choice", "")
                confidence = float(answer.get("confidence", 0.0))
                is_same = (choice == "same") and (prob_same >= self._threshold)

                return AdjudicationVerdict(
                    same=is_same,
                    confidence=confidence,
                    reason=(
                        f"ollaya:{self._model} (p_same={prob_same:.3f}, conf={confidence:.3f})"
                    ),
                )
            except Exception:
                # Follow redstring's safety contract: return None on error so
                # unconfirmed pairs are not treated as "definitely distinct".
                logger.warning(
                    "Ollaya adjudication failed for '%s' vs '%s'",
                    subject.name,
                    cand_entity.name,
                    exc_info=True,
                )
                return None
