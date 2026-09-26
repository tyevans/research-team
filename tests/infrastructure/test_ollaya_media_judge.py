"""Unit tests for OllayaMediaJudge."""

from unittest.mock import AsyncMock

import pytest

from research_team.infrastructure.agent.ollaya_media_judge import OllayaMediaJudge
from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient
from research_team.research.application.media_curation import MediaNeed, SearchResult


def _need(need_id: str = "need-1") -> MediaNeed:
    return MediaNeed(
        need_id=need_id,
        medium="image",
        description="A diagram showing how triode vacuum tubes work",
        why="Visualizes grid control of electron flow",
    )


def _result(
    title: str = "Vacuum Tube Diagram", asset_url: str = "https://example.com/tube.png"
) -> SearchResult:
    return SearchResult(
        title=title,
        url="https://example.com/page",
        snippet="Schematic of a triode showing filament, grid, and plate",
        kind="image",
        asset_url=asset_url,
        detail="800x600",
        thumbnail_url="https://example.com/thumb.png",
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=OllayaDecisionClient)


async def test_ollaya_media_judge_keeps_relevant_candidate(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "is_relevant": {
                "type": "choice",
                "choice": "keep",
                "confidence": 0.90,
                "probabilities": {"keep": 0.94, "reject": 0.06},
            }
        },
    }

    judge = OllayaMediaJudge(mock_client, model="laya", threshold=0.70)
    need = _need()
    candidates = [_result()]

    judgements = await judge.judge_candidates(need, candidates)
    assert len(judgements) == 1
    assert judgements[0].need_id == "need-1"
    assert judgements[0].index == 0
    assert "p_keep=0.940" in judgements[0].reason


async def test_ollaya_media_judge_rejects_irrelevant_candidate(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "is_relevant": {
                "type": "choice",
                "choice": "reject",
                "confidence": 0.85,
                "probabilities": {"keep": 0.10, "reject": 0.90},
            }
        },
    }

    judge = OllayaMediaJudge(mock_client, model="laya", threshold=0.70)
    need = _need()
    candidates = [_result(title="Funny Cat Video")]

    judgements = await judge.judge_candidates(need, candidates)
    assert len(judgements) == 0


async def test_ollaya_media_judge_handles_error_gracefully(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.side_effect = RuntimeError("Ollaya unavailable")

    judge = OllayaMediaJudge(mock_client, model="laya")
    need = _need()
    candidates = [_result()]

    judgements = await judge.judge_candidates(need, candidates)
    assert len(judgements) == 0
