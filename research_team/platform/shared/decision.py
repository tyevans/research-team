"""Abstract protocols and data types for fast System One decision models.

Defines the questions and answers supported by non-autoregressive decision models
(such as Ollaya / TypeSafe System One), without depending on any external HTTP client
or model framework.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChoiceQuestion:
    """A question asking to select one label from a set of criteria."""

    criteria: Mapping[str, str]
    instructions: str = ""


@dataclass(frozen=True)
class ScoreQuestion:
    """A question asking for an expected numeric score over ordered levels."""

    criteria: Sequence[str]
    instructions: str = ""


@dataclass(frozen=True)
class TruthQuestion:
    """A question asking for the calibrated probability that a statement holds."""

    instructions: str = ""
    true_criteria: str = "True"
    false_criteria: str = "False"


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TruthAnswer:
    probability: float
    confidence: float = 1.0


class DecisionPort(Protocol):
    """Port for non-autoregressive parallel decision evaluation."""

    async def decide(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[
            str, ChoiceQuestion | ScoreQuestion | TruthQuestion | Mapping[str, Any]
        ],
        *,
        model: str | None = None,
    ) -> Mapping[str, ChoiceAnswer | ScoreAnswer | TruthAnswer]:
        """Evaluate typed questions against state in a single pass."""
        ...
