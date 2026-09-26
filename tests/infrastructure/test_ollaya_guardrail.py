"""Unit tests for OllayaToolGuardrail."""

from unittest.mock import AsyncMock

import pytest

from research_team.infrastructure.agent.ollaya_guardrail import OllayaToolGuardrail
from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=OllayaDecisionClient)


async def test_guardrail_allows_safe_fetch(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "action": {
                "type": "choice",
                "choice": "allow",
                "confidence": 0.95,
                "probabilities": {"allow": 0.98, "block": 0.02},
            }
        },
    }

    guardrail = OllayaToolGuardrail(mock_client, model="laya")
    should_block = await guardrail.should_intercept(
        "fetch", {"url": "https://en.wikipedia.org/wiki/Vacuum_tube"}
    )
    assert should_block is False


async def test_guardrail_intercepts_suspicious_call(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "action": {
                "type": "choice",
                "choice": "block",
                "confidence": 0.89,
                "probabilities": {"allow": 0.10, "block": 0.90},
            }
        },
    }

    guardrail = OllayaToolGuardrail(mock_client, model="laya")
    should_block = await guardrail.should_intercept(
        "fetch", {"url": "http://malicious-gateway.internal/exfiltrate"}
    )
    assert should_block is True


async def test_guardrail_error_fails_open(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.side_effect = RuntimeError("Ollaya unavailable")

    guardrail = OllayaToolGuardrail(mock_client, model="laya")
    should_block = await guardrail.should_intercept("fetch", {"url": "https://example.com"})
    assert should_block is False
