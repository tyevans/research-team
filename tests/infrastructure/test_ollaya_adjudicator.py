"""Unit tests for OllayaAdjudicator."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redstring import Entity, ExtractionMethod, Provenance, ScoredCandidate, SimilarityFeatures

from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient
from research_team.infrastructure.knowledge.ollaya_adjudicator import OllayaAdjudicator

TENANT_ID = uuid4()


def _entity(name: str, entity_type: str = "Person", description: str = "") -> Entity:
    return Entity(
        id=uuid4(),
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        description=description,
        properties={},
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


def _candidate(entity: Entity, score: float = 0.8) -> ScoredCandidate:
    return ScoredCandidate(
        entity=entity,
        score=score,
        features=SimilarityFeatures(name=1.0, embedding=0.8, graph=None),
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=OllayaDecisionClient)


async def test_ollaya_adjudicator_verdict_same(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "is_same": {
                "type": "choice",
                "choice": "same",
                "confidence": 0.95,
                "probabilities": {"same": 0.97, "distinct": 0.03},
            }
        },
    }

    adjudicator = OllayaAdjudicator(mock_client, model="laya")
    subject = _entity("John F. Kennedy", description="35th US President")
    cand = _candidate(_entity("JFK", description="US President"))

    verdicts = await adjudicator.adjudicate(subject, [cand])
    assert len(verdicts) == 1
    assert verdicts[0] is not None
    assert verdicts[0].same is True
    assert verdicts[0].confidence == 0.95
    assert "p_same=0.970" in verdicts[0].reason


async def test_ollaya_adjudicator_verdict_distinct(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "is_same": {
                "type": "choice",
                "choice": "distinct",
                "confidence": 0.91,
                "probabilities": {"same": 0.05, "distinct": 0.95},
            }
        },
    }

    adjudicator = OllayaAdjudicator(mock_client, model="laya")
    subject = _entity("Mercury", entity_type="Planet", description="First planet from Sun")
    cand = _candidate(
        _entity("Mercury", entity_type="Element", description="Chemical element")
    )

    verdicts = await adjudicator.adjudicate(subject, [cand])
    assert len(verdicts) == 1
    assert verdicts[0] is not None
    assert verdicts[0].same is False
    assert verdicts[0].confidence == 0.91


async def test_ollaya_adjudicator_error_returns_none(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.side_effect = RuntimeError("Connection timeout")

    adjudicator = OllayaAdjudicator(mock_client, model="laya")
    subject = _entity("Alice")
    cand = _candidate(_entity("Bob"))

    verdicts = await adjudicator.adjudicate(subject, [cand])
    assert len(verdicts) == 1
    assert verdicts[0] is None


async def test_ollaya_adjudicate_many(mock_client: AsyncMock) -> None:
    mock_client.decide_raw.return_value = {
        "model": "laya:en",
        "answers": {
            "is_same": {
                "type": "choice",
                "choice": "same",
                "confidence": 0.88,
                "probabilities": {"same": 0.92, "distinct": 0.08},
            }
        },
    }

    adjudicator = OllayaAdjudicator(mock_client, model="laya")
    subject1 = _entity("Marie Curie")
    cand1 = _candidate(_entity("Madame Curie"))
    subject2 = _entity("Albert Einstein")
    cand2 = _candidate(_entity("Einstein"))

    work = [(subject1, [cand1]), (subject2, [cand2])]
    results = await adjudicator.adjudicate_many(work)

    assert len(results) == 2
    assert len(results[0]) == 1
    assert len(results[1]) == 1
    assert results[0][0] is not None and results[0][0].same is True
    assert results[1][0] is not None and results[1][0].same is True
