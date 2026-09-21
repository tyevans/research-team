"""The ask and socratic dialogue HTTP routes.

Extracted into `ask.py` and `socratic.py`: this module provides
the combined `DialogueDeps` and `dialogue_router` facade for backwards
compatibility with `create_app` and existing tests.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter

from research_team.application.dialogue.ask import AskService
from research_team.application.dialogue.socratic import SocraticDialogueService
from research_team.infrastructure.persistence.read_models import (
    AskConversationRunner,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.ask import (
    AskAttempt,
    AskDeps,
    AskRequest,
    _ask_frame,
    _conversation_view,
    ask_router,
)
from research_team.interfaces.web.socratic import (
    Attempt,
    SocraticAttempt,
    SocraticDeps,
    SocraticReply,
    SocraticStart,
    _dialogue_view,
    _socratic_frame,
    socratic_router,
)

__all__ = [
    "AskAttempt",
    "AskDeps",
    "AskRequest",
    "Attempt",
    "DialogueDeps",
    "SocraticAttempt",
    "SocraticDeps",
    "SocraticReply",
    "SocraticStart",
    "_ask_frame",
    "_conversation_view",
    "_dialogue_view",
    "_socratic_frame",
    "ask_router",
    "dialogue_router",
    "socratic_router",
]


@dataclass(frozen=True)
class DialogueDeps:
    """What the dialogue and ask routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    service: Any | None = None
    ask: AskService | None = None
    asks: AskConversationRunner | None = None
    socratic: SocraticDialogueService | None = None
    dialogues: SocraticDialogueRunner | None = None
    turns: Any | None = None
    # Aliases for flexibility across callers
    socratic_dialogues: SocraticDialogueRunner | None = None
    socratic_service: SocraticDialogueService | None = None
    ask_reader: AskService | None = None

    def __post_init__(self) -> None:
        if self.dialogues is None and self.socratic_dialogues is not None:
            object.__setattr__(self, "dialogues", self.socratic_dialogues)
        if self.socratic is None and self.socratic_service is not None:
            object.__setattr__(self, "socratic", self.socratic_service)
        if self.ask is None and self.ask_reader is not None:
            object.__setattr__(self, "ask", self.ask_reader)

    def to_ask_deps(self) -> AskDeps:
        return AskDeps(
            require_project=self.require_project,
            service=self.service,
            ask=self.ask,
            asks=self.asks,
            turns=self.turns,
            ask_reader=self.ask_reader,
        )

    def to_socratic_deps(self) -> SocraticDeps:
        return SocraticDeps(
            require_project=self.require_project,
            service=self.service,
            socratic=self.socratic,
            dialogues=self.dialogues,
            turns=self.turns,
            socratic_dialogues=self.socratic_dialogues,
            socratic_service=self.socratic_service,
        )


def dialogue_router(deps: DialogueDeps) -> APIRouter:
    """The Ask and Socratic Dialogue routes, ready for `app.include_router`."""
    router = APIRouter()
    router.routes.extend(ask_router(deps.to_ask_deps()).routes)
    router.routes.extend(socratic_router(deps.to_socratic_deps()).routes)
    return router
