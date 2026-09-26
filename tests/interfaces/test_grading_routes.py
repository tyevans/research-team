"""Unit tests for the semantic grading endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_team.interfaces.web.grading import grading_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(grading_router)
    return TestClient(app)


def test_grade_exact_match(client: TestClient) -> None:
    res = client.post(
        "/api/grade/semantic",
        json={
            "target": "photosynthesis",
            "submission": "  Photosynthesis  ",
            "prompt": "How plants convert light into chemical energy",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_correct"] is True
    assert data["verdict"] == "exact_match"
    assert data["confidence"] == 1.0


def test_grade_fallback_when_no_decision_url(client: TestClient) -> None:
    with patch("research_team.infrastructure.config.decision_base_url", return_value=None):
        res = client.post(
            "/api/grade/semantic",
            json={
                "target": "electron",
                "submission": "electrons in orbit",
                "prompt": "Negatively charged subatomic particle",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_correct"] is True
        assert data["verdict"] == "substring_fallback"


def test_grade_with_ollaya_decision_model(client: TestClient) -> None:
    mock_ollaya = AsyncMock()
    mock_ollaya.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "semantic_match": {
                "type": "choice",
                "choice": "correct",
                "confidence": 0.94,
                "probabilities": {"correct": 0.96, "incorrect": 0.04},
            }
        },
    }

    with (
        patch(
            "research_team.infrastructure.config.decision_base_url",
            return_value="http://localhost:11435",
        ),
        patch(
            "research_team.interfaces.web.grading._get_decision_client",
            return_value=mock_ollaya,
        ),
    ):
        res = client.post(
            "/api/grade/semantic",
            json={
                "target": "speed of light",
                "submission": "velocity of electromagnetic waves in vacuum",
                "prompt": "What is c in E=mc^2?",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_correct"] is True
        assert data["verdict"] == "correct"
        assert data["confidence"] == 0.94
