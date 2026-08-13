"""Asking a project about the material it has gathered.

A parallel path to `SessionService`, not a caller of it. Sessions are
event-sourced, hold a project exclusively, and fork a filesystem when they
join one; an asking surface wants none of that, so it gets its own path and
persists nothing.

Nothing in this module may import a framework. `tests/test_architecture.py`
holds the application layer to `eventsource` alone, so the LangChain side of
this feature lives behind `AskExecutor` in `infrastructure/agent/ask_agent.py`.
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class AskMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class Citation:
    """Something the agent opened while answering.

    `kind` is deliberately narrow: a citation records a read, and only
    `read_source` and `open_topic` read a specific identified thing.
    """

    kind: Literal["source", "topic"]
    id: str


@dataclass(frozen=True)
class AskAnswer:
    text: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class Conversation:
    chat_id: str
    project_id: UUID
    messages: tuple[AskMessage, ...] = ()
    used_at: float = 0.0

    def appended(self, *messages: AskMessage, at: float) -> "Conversation":
        return replace(self, messages=(*self.messages, *messages), used_at=at)


class ConversationRegistry:
    """Ephemeral conversations, bounded two ways.

    The defaults -- 64 conversations, an hour idle -- are guesses at the shape
    of a single-user console rather than measurements, and are cheap to change.
    Eviction is least-recently-used because a bound that trimmed the newest
    would throw away the chat someone is in the middle of.
    """

    def __init__(
        self,
        *,
        now: Callable[[], float],
        limit: int = 64,
        idle_seconds: float = 3_600.0,
    ) -> None:
        self._now = now
        self._limit = limit
        self._idle_seconds = idle_seconds
        self._held: OrderedDict[str, Conversation] = OrderedDict()

    def __len__(self) -> int:
        return len(self._held)

    def get(self, chat_id: str, project_id: UUID) -> Conversation:
        now = self._now()
        held = self._held.get(chat_id)
        # A chat id arrives from the browser, so the project it was opened
        # under is checked rather than trusted; a mismatch is treated as
        # absence, which is also what a guessed id deserves.
        if (
            held is None
            or held.project_id != project_id
            or now - held.used_at > self._idle_seconds
        ):
            self._held.pop(chat_id, None)
            return Conversation(chat_id=chat_id, project_id=project_id, used_at=now)
        self._held.move_to_end(chat_id)
        return held

    def put(self, conversation: Conversation) -> None:
        self._held[conversation.chat_id] = conversation
        self._held.move_to_end(conversation.chat_id)
        while len(self._held) > self._limit:
            self._held.popitem(last=False)

    def drop(self, chat_id: str) -> None:
        self._held.pop(chat_id, None)
