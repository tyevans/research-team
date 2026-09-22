"""Dialogue read models, projections, stores, and runners facade.

Re-exports read-side state, models, stores, projections, and runners for Ask
conversations (from `ask_read_models`) and Socratic dialogues (from
`socratic_read_models`).
"""

from __future__ import annotations

from research_team.infrastructure.persistence.ask_read_models import (
    ASK_NAMESPACE,
    AskConversationProjection,
    AskConversationRow,
    AskConversationRunner,
    AskConversationStore,
    AskTurnRow,
)
from research_team.infrastructure.persistence.socratic_read_models import (
    SOCRATIC_NAMESPACE,
    SocraticDialogueProjection,
    SocraticDialogueRow,
    SocraticDialogueRunner,
    SocraticDialogueStore,
    SocraticTurnRow,
)

__all__ = [
    "ASK_NAMESPACE",
    "SOCRATIC_NAMESPACE",
    "AskConversationProjection",
    "AskConversationRow",
    "AskConversationRunner",
    "AskConversationStore",
    "AskTurnRow",
    "SocraticDialogueProjection",
    "SocraticDialogueRow",
    "SocraticDialogueRunner",
    "SocraticDialogueStore",
    "SocraticTurnRow",
]
