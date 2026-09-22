"""Dependencies for session, turn, approval, and autonomy HTTP routes."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import WebApprovals
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor

__all__ = ["SessionDeps"]


@dataclass(frozen=True)
class SessionDeps:
    """What the session, turn, approval, and autonomy routes need from
    `create_app`'s closure.

    A record rather than a long parameter list, matching `TopicDeps`,
    `KnowledgeDeps`, and `DialogueDeps`.
    """

    service: SessionService
    turns: TurnSupervisor
    approvals: WebApprovals | None = None
    activity: TurnActivity | None = None
    policy: AutonomyPolicy | None = None
    load: Callable[[UUID], Awaitable[Any]] | None = None
