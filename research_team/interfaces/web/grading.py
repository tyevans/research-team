"""Fast semantic grading for interactive learner inputs using Ollaya."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from research_team.infrastructure import config
from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient

logger = logging.getLogger(__name__)

grading_router = APIRouter(prefix="/api/grade", tags=["grading"])


class SemanticGradeRequest(BaseModel):
    """A learner submission to grade against an expected concept."""

    target: str = Field(description="The expected concept, term, or answer")
    submission: str = Field(description="The learner's submitted answer text")
    prompt: str = Field(default="", description="The surrounding context or question")


class SemanticGradeResponse(BaseModel):
    """The grading outcome."""

    is_correct: bool
    confidence: float
    verdict: str
    explanation: str


_GRADE_QUESTION = {
    "semantic_match": {
        "type": "choice",
        "instructions": (
            "Determine whether the learner's submitted answer demonstrates the target concept "
            "correctly in the context of the question."
        ),
        "criteria": {
            "correct": (
                "Conceptually accurate, synonymous, or valid phrasing of the target concept"
            ),
            "incorrect": (
                "Conceptually wrong, contradictory, irrelevant, or missing the core concept"
            ),
        },
    }
}


def _get_decision_client() -> OllayaDecisionClient | None:
    url = config.decision_base_url()
    if not url:
        return None
    return OllayaDecisionClient(base_url=url, default_model=config.decision_model())


@grading_router.post("/semantic", response_model=SemanticGradeResponse)
async def grade_submission(req: SemanticGradeRequest) -> SemanticGradeResponse:
    """Grade a learner's free-form input against the expected concept in <50ms."""
    submission_clean = req.submission.strip()
    target_clean = req.target.strip()

    # Fast path: exact string match requires no model call
    if submission_clean.casefold() == target_clean.casefold():
        return SemanticGradeResponse(
            is_correct=True,
            confidence=1.0,
            verdict="exact_match",
            explanation="Exact match",
        )

    client = _get_decision_client()
    if client is None:
        # Fallback when decision model is not configured: fuzzy containment or exact match only
        is_sub = target_clean.casefold() in submission_clean.casefold()
        return SemanticGradeResponse(
            is_correct=is_sub,
            confidence=0.7 if is_sub else 0.0,
            verdict="substring_fallback" if is_sub else "incorrect",
            explanation="Heuristic fallback (no decision model configured)",
        )

    state = (
        f"Context / Question: {req.prompt or 'N/A'}\n"
        f"Target Concept: {req.target}\n"
        f"Learner Submission: {req.submission}"
    )

    try:
        res = await client.decide_raw(
            state=state,
            questions=_GRADE_QUESTION,
        )
        ans = res.get("answers", {}).get("semantic_match", {})
        choice = ans.get("choice", "incorrect")
        confidence = float(ans.get("confidence", 0.0))
        prob_correct = float(ans.get("probabilities", {}).get("correct", 0.0))

        is_correct = (choice == "correct") and (prob_correct >= 0.70)
        return SemanticGradeResponse(
            is_correct=is_correct,
            confidence=confidence,
            verdict=choice,
            explanation=f"Ollaya calibrated p_correct={prob_correct:.3f}",
        )
    except Exception as err:
        logger.warning("Ollaya semantic grading failed: %s", err, exc_info=True)
        return SemanticGradeResponse(
            is_correct=False,
            confidence=0.0,
            verdict="error_fallback",
            explanation=f"Grading error: {err}",
        )
