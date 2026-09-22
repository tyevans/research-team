"""Socratic dialogue models, dependencies, SSE framing, and view formatting.

Extracted from `socratic.py` to isolate request/response shapes, dependency injection
structures, and streaming note projections from HTTP route registration.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from research_team.dialogue.application.socratic import (
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticPrompt,
)
from research_team.dialogue.application.socratic_components import dialogue_document
from research_team.infrastructure.persistence.read_models import (
    SocraticDialogueRow,
    SocraticDialogueRunner,
)
from research_team.platform.shared.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityRemark,
)

__all__ = [
    "Attempt",
    "SocraticAttempt",
    "SocraticDeps",
    "SocraticReply",
    "SocraticStart",
    "_dialogue_view",
    "_socratic_frame",
]


class Attempt(BaseModel):
    """One learner's answer to one component, addressed in the body.

    The component is named in the body rather than in the path because a file
    path contains slashes, and a route of `/files/{path}/components/{id}` would
    make every caller double-encode one to reach the other. Nothing else about
    the shape depends on that.

    `at` grades against the file as it stood at that event rather than at HEAD.
    Without it, an author revising a question would silently re-mark attempts
    made against the version the learner actually read.
    """

    path: str
    component_id: str
    response: Any = None
    at: int | None = None


class SocraticStart(BaseModel):
    """A topic to build a dialogue around.

    No id: unlike an ask's `chat_id`, the dialogue's id is minted by the server
    and returned, because it is an aggregate id, a row key and a URL segment --
    the identical hazard as letting a browser or a model pick one.
    """

    topic: str = Field(min_length=1)


class SocraticReply(BaseModel):
    """What the reader said in answer to the outstanding question.

    Named `reply` and not `question`, matching the domain: on this surface the
    system asks and the reader answers, which is the inverse of the ask.
    """

    reply: str


class SocraticAttempt(BaseModel):
    """One reader's answer to a component the dialogue asked.

    Addressed by `(position, component_id)`, matching `AskAttempt`: a dialogue
    turn has no file path, and the turn is what the server re-parses to recover
    the key. No `at` -- a `SocraticTurnRecorded` is never rewritten, so there is
    no second version to grade against.
    """

    position: int
    component_id: str
    response: Any = None


@dataclass(frozen=True)
class SocraticDeps:
    """What the socratic routes need from `create_app`'s closure."""

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    service: Any | None = None
    socratic: SocraticDialogueService | None = None
    dialogues: SocraticDialogueRunner | None = None
    turns: Any | None = None
    # Aliases for flexibility across callers
    socratic_dialogues: SocraticDialogueRunner | None = None
    socratic_service: SocraticDialogueService | None = None

    def __post_init__(self) -> None:
        if self.dialogues is None and self.socratic_dialogues is not None:
            object.__setattr__(self, "dialogues", self.socratic_dialogues)
        if self.socratic is None and self.socratic_service is not None:
            object.__setattr__(self, "socratic", self.socratic_service)


def _socratic_frame(note: object) -> str | None:
    """One SSE `data:` line per note, or `None` for a note with nothing to draw.

    Deliberately its own function rather than a branch inside `_ask_frame`:
    the last frame of a dialogue turn is typed `prompt` and not `answer`,
    because it is a question. A page that reused the ask's handler would
    draw the dialogue's question in the reader's own column -- and it would
    render, which is why this is a separate function with its own test
    (`test_the_last_frame_is_typed_prompt_and_not_answer`, red against a
    copy-paste of `_ask_frame`).
    """
    if isinstance(note, SocraticDialogueOpened):
        body: dict[str, Any] = {
            "type": "dialogue",
            "dialogue_id": str(note.dialogue_id),
            "topic": note.topic,
            "goal": note.goal,
            "stopping_condition": note.stopping_condition,
            "pending_blocks": dialogue_document(note.pending_prompt)["blocks"],
        }
    elif isinstance(note, ActivityDelta):
        body = {"type": "delta", "message_id": note.message_id, "text": ""}
    elif isinstance(note, ActivityMessage):
        if note.kind == "assistant":
            return None
        body = {
            "type": "message",
            "message_id": note.message_id,
            "kind": note.kind,
            "payload": note.payload,
            "is_error": note.is_error,
        }
    elif isinstance(note, SocraticPrompt):
        body = {
            "type": "prompt",
            "blocks": dialogue_document(note.prompt)["blocks"],
            "position": note.position,
            "citations": [{"kind": kind, "id": cited} for kind, cited in note.citations],
            "concluded": note.concluded,
        }
    elif isinstance(note, ActivityRemark):
        body = {
            "type": "message",
            "message_id": "",
            "kind": "remark",
            "payload": {"text": note.text},
            "is_error": False,
        }
    else:
        return None
    return f"data: {json.dumps(body)}\n\n"


def _dialogue_view(row: SocraticDialogueRow) -> dict[str, Any]:
    """One dialogue, without its turns -- what a history list needs."""
    return {
        "dialogueId": str(row.id),
        "projectId": str(row.project_id),
        "topic": row.topic,
        "goal": row.goal,
        "stoppingCondition": row.stopping_condition,
        "openingBlocks": dialogue_document(row.opening_prompt)["blocks"],
        "pendingBlocks": dialogue_document(row.pending_prompt)["blocks"],
        "openedAt": row.opened_at.isoformat(),
        "status": row.status,
        "concludedReason": row.concluded_reason,
        "turnCount": row.turn_count,
        "observations": row.observations,
    }
