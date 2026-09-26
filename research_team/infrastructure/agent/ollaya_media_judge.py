"""Ollaya-backed Stage 3 judge for media curation candidates."""

import asyncio
import logging
from collections.abc import Sequence

from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient
from research_team.research.application.media_curation import (
    Judgement,
    MediaNeed,
    SearchResult,
)

logger = logging.getLogger(__name__)

_QUESTION = {
    "is_relevant": {
        "type": "choice",
        "instructions": (
            "Does this media search result directly satisfy the stated pedagogical need?"
        ),
        "criteria": {
            "keep": (
                "The asset directly depicts or explains the requested visual/audio concept"
            ),
            "reject": "The asset is off-topic, spam, clickbait, or generic unrelated imagery",
        },
    }
}


class OllayaMediaJudge:
    """Evaluates media search results against topic needs using an Ollaya decision model."""

    def __init__(
        self,
        client: OllayaDecisionClient,
        *,
        model: str = "laya",
        threshold: float = 0.70,
        concurrency: int = 8,
    ) -> None:
        self._client = client
        self._model = model
        self._threshold = threshold
        self._sem = asyncio.Semaphore(concurrency)

    async def judge_candidates(
        self, need: MediaNeed, candidates: Sequence[SearchResult]
    ) -> list[Judgement]:
        """Judge a list of candidates for one need, returning only the kept ones."""
        tasks = [
            self._judge_single(need, idx, candidate)
            for idx, candidate in enumerate(candidates)
        ]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _judge_single(
        self, need: MediaNeed, index: int, candidate: SearchResult
    ) -> Judgement | None:
        state = (
            f"Need Medium: {need.medium}\n"
            f"Description: {need.description}\n"
            f"Pedagogical Goal: {need.why}\n\n"
            f"Search Result:\n"
            f"Title: {candidate.title}\n"
            f"Snippet: {candidate.snippet}\n"
            f"Asset URL: {candidate.asset_url}"
        )
        async with self._sem:
            try:
                res = await self._client.decide_raw(
                    model=self._model, state=state, questions=_QUESTION
                )
                ans = res["answers"]["is_relevant"]
                prob_keep = float(ans.get("probabilities", {}).get("keep", 0.0))
                choice = ans.get("choice", "")

                if choice == "keep" and prob_keep >= self._threshold:
                    return Judgement(
                        need_id=need.need_id,
                        index=index,
                        reason=f"ollaya:{self._model} (p_keep={prob_keep:.3f})",
                    )
                return None
            except Exception:
                logger.warning(
                    "Ollaya media candidate evaluation failed for need %s index %d",
                    need.need_id,
                    index,
                    exc_info=True,
                )
                return None
