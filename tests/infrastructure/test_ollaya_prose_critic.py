"""Unit tests for OllayaProseCritic."""

from unittest.mock import AsyncMock

import pytest

from research_team.infrastructure.agent.ollaya_prose_critic import OllayaProseCritic
from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=OllayaDecisionClient)


async def test_ollaya_prose_critic_evaluates_all_six_rules(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "rule_1_problem": {"choice": "pass", "confidence": 0.92},
            "rule_2_withholding": {"choice": "pass", "confidence": 0.85},
            "rule_3_stated_cost": {"choice": "fail", "confidence": 0.78},
            "rule_4_unpacking": {"choice": "pass", "confidence": 0.95},
            "rule_5_second_person": {"choice": "pass", "confidence": 0.88},
            "rule_6_varied_shape": {"choice": "pass", "confidence": 0.82},
        },
    }

    critic = OllayaProseCritic(mock_client, model="laya")
    sample_lesson = (
        "# Lesson 1\nIn 1940, the Tacoma Narrows Bridge collapsed in 40 mph winds..."
    )

    verdicts = await critic.evaluate_lesson(sample_lesson)
    assert len(verdicts) == 6
    assert verdicts[0].rule_number == 1 and verdicts[0].passed is True
    assert verdicts[2].rule_number == 3 and verdicts[2].passed is False
    assert verdicts[2].rule_name == "One stated cost"


async def test_ollaya_prose_critic_handles_failure(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.side_effect = RuntimeError("Ollaya unavailable")

    critic = OllayaProseCritic(mock_client, model="laya")
    verdicts = await critic.evaluate_lesson("Some lesson text")
    assert verdicts == []
