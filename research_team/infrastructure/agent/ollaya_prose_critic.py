"""Ollaya-backed fast evaluation of draft lessons against the six prose rules."""

import logging
from dataclasses import dataclass

from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProseRuleVerdict:
    rule_number: int
    rule_name: str
    passed: bool
    confidence: float
    reason: str


_RULES_QUESTIONS = {
    "rule_1_problem": {
        "type": "choice",
        "instructions": (
            "Rule 1: Does the opening (first ~80 words) begin with a concrete problem, "
            "incident, failure, or contradiction rather than an abstract thesis or "
            "topic sentence?"
        ),
        "criteria": {
            "pass": "Opens with a concrete incident, failure, or measured surprise",
            "fail": "Opens with an abstract topic sentence, definition, or thesis",
        },
    },
    "rule_2_withholding": {
        "type": "choice",
        "instructions": (
            "Rule 2: Is a question or puzzle raised and withheld for at least a paragraph "
            "before being answered?"
        ),
        "criteria": {
            "pass": "Withholds an answer across paragraphs to sustain curiosity",
            "fail": "Answers every question immediately in the same sentence or has no puzzle",
        },
    },
    "rule_3_stated_cost": {
        "type": "choice",
        "instructions": (
            "Rule 3: Does the lesson state a concrete, observable cost or failure mode if "
            "this concept is gotten wrong?"
        ),
        "criteria": {
            "pass": "Names what breaks with concrete evidence",
            "fail": "Abstract claims with no demonstrated consequence or cost",
        },
    },
    "rule_4_unpacking": {
        "type": "choice",
        "instructions": (
            "Rule 4: Does the lesson perform at most one 'unpacking' move (announcing and "
            "cataloging parts of a quotation or claim)?"
        ),
        "criteria": {
            "pass": "At most one unpacking move throughout the lesson",
            "fail": "Two or more repetitive unpacking explanations",
        },
    },
    "rule_5_second_person": {
        "type": "choice",
        "instructions": (
            "Rule 5: Is the learner addressed in the second person ('you') with an active "
            "task or decision to make?"
        ),
        "criteria": {
            "pass": "Uses 'you' with an active task or decision",
            "fail": "Passive third-person description with no learner task",
        },
    },
    "rule_6_varied_shape": {
        "type": "choice",
        "instructions": (
            "Rule 6: Do consecutive sections vary in structure rather than repeating "
            "identical parallel lists?"
        ),
        "criteria": {
            "pass": "Varied rhythm, section length, and layout",
            "fail": "Repetitive boilerplate or decorative parallel bullet lists",
        },
    },
}

_RULE_NAMES = {
    1: ("rule_1_problem", "Opens with a problem"),
    2: ("rule_2_withholding", "Something is withheld"),
    3: ("rule_3_stated_cost", "One stated cost"),
    4: ("rule_4_unpacking", "At most one unpacking"),
    5: ("rule_5_second_person", "Second person with a task"),
    6: ("rule_6_varied_shape", "Varied section shape"),
}


class OllayaProseCritic:
    """Evaluates lesson prose against the 6 rubric rules using an Ollaya decision model."""

    def __init__(self, client: OllayaDecisionClient, *, model: str = "laya") -> None:
        self._client = client
        self._model = model

    async def evaluate_lesson(self, lesson_markdown: str) -> list[ProseRuleVerdict]:
        """Evaluate a lesson against all 6 rules in a single parallel request."""
        try:
            res = await self._client.decide_raw(
                model=self._model,
                state=lesson_markdown,
                questions=_RULES_QUESTIONS,
            )
            answers = res.get("answers", {})
        except Exception:
            logger.warning("Ollaya prose critic evaluation failed", exc_info=True)
            return []

        verdicts: list[ProseRuleVerdict] = []
        for num in range(1, 7):
            q_key, name = _RULE_NAMES[num]
            ans = answers.get(q_key, {})
            choice = ans.get("choice", "")
            confidence = float(ans.get("confidence", 0.0))
            passed = choice == "pass"

            verdicts.append(
                ProseRuleVerdict(
                    rule_number=num,
                    rule_name=name,
                    passed=passed,
                    confidence=confidence,
                    reason=f"ollaya:{self._model} choice={choice} (conf={confidence:.3f})",
                )
            )

        return verdicts
