"""Ollaya decision model client implementing DecisionPort over HTTP."""

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from research_team.platform.shared.decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionPort,
    ScoreAnswer,
    ScoreQuestion,
    TruthAnswer,
    TruthQuestion,
)
from research_team.platform.shared.retry import with_retry

logger = logging.getLogger(__name__)


class DecisionClientError(Exception):
    """Base exception for decision client failures."""


class DecisionModelNotFoundError(DecisionClientError):
    """The requested decision model was not pulled in Ollaya."""


class DecisionValidationError(DecisionClientError):
    """The request failed schema or token limits validation."""


class OllayaDecisionClient(DecisionPort):
    """HTTP client for Ollaya and TypeSafe-compatible decision endpoints."""

    def __init__(
        self,
        base_url: str = "http://localhost:11435",
        *,
        default_model: str = "laya",
        timeout: float = 5.0,
        api_key: str = "local",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout
        self._api_key = api_key
        self._external_client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._external_client is not None:
            return self._external_client
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    def _serialize_question(self, q: Any) -> dict[str, Any]:
        if isinstance(q, ChoiceQuestion):
            payload: dict[str, Any] = {"type": "choice", "criteria": dict(q.criteria)}
            if q.instructions:
                payload["instructions"] = q.instructions
            return payload
        if isinstance(q, ScoreQuestion):
            payload = {"type": "score", "criteria": list(q.criteria)}
            if q.instructions:
                payload["instructions"] = q.instructions
            return payload
        if isinstance(q, TruthQuestion):
            payload = {
                "type": "noul",
                "criteria": {"true": q.true_criteria, "false": q.false_criteria},
            }
            if q.instructions:
                payload["instructions"] = q.instructions
            return payload
        if isinstance(q, dict):
            return q
        raise TypeError(f"Unsupported question type: {type(q)}")

    async def decide_raw(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, Any],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a raw decision request and return the deserialized JSON dictionary."""
        model_name = model or self._default_model
        serialized_questions = {k: self._serialize_question(v) for k, v in questions.items()}
        payload = {
            "model": model_name,
            "state": state,
            "questions": serialized_questions,
        }

        async def _call() -> httpx.Response:
            client = self._get_client()
            if self._external_client is not None:
                return await client.post("/v1/systemone", json=payload)
            async with client as c:
                return await c.post("/v1/systemone", json=payload)

        try:
            response = await with_retry(
                _call,
                retryable_statuses={502, 503, 504},
            )
        except Exception as err:
            raise DecisionClientError(f"Decision request failed: {err}") from err

        if response.status_code == 404:
            raise DecisionModelNotFoundError(
                f"Model '{model_name}' not found. Pull it first in Ollaya."
            )
        if response.status_code == 422:
            raise DecisionValidationError(
                f"Validation error from decision endpoint: {response.text}"
            )
        response.raise_for_status()
        return response.json()

    async def decide(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[
            str, ChoiceQuestion | ScoreQuestion | TruthQuestion | Mapping[str, Any]
        ],
        *,
        model: str | None = None,
    ) -> dict[str, ChoiceAnswer | ScoreAnswer | TruthAnswer]:
        """Evaluate typed questions and return structured typed answer objects."""
        raw_result = await self.decide_raw(state, questions, model=model)
        raw_answers = raw_result.get("answers", {})
        parsed: dict[str, ChoiceAnswer | ScoreAnswer | TruthAnswer] = {}

        for k, ans in raw_answers.items():
            ans_type = ans.get("type")
            if ans_type == "choice":
                parsed[k] = ChoiceAnswer(
                    choice=ans.get("choice", ""),
                    confidence=float(ans.get("confidence", 0.0)),
                    probabilities=ans.get("probabilities", {}),
                )
            elif ans_type == "score":
                parsed[k] = ScoreAnswer(
                    score=float(ans.get("score", 0.0)),
                    confidence=float(ans.get("confidence", 0.0)),
                    probabilities=ans.get("probabilities", {}),
                )
            elif ans_type == "noul":
                parsed[k] = TruthAnswer(
                    probability=float(ans.get("noul", 0.0)),
                    confidence=1.0,
                )
            else:
                # Fallback for choices without explicit type in answer dict
                if "choice" in ans:
                    parsed[k] = ChoiceAnswer(
                        choice=ans["choice"],
                        confidence=float(ans.get("confidence", 0.0)),
                        probabilities=ans.get("probabilities", {}),
                    )
        return parsed
