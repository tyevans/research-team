"""Data models, exceptions, registry cache, and protocols for Socratic dialogues.

Extracted from `socratic.py` to separate message/dialogue types and caching
from the dialogue orchestration use-case service.
"""

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol
from uuid import UUID

from research_team.dialogue.domain.socratic import (
    Citation,
    EvidenceKind,
)
from research_team.platform.shared.ports import ActivityNote, ActivityReporter
from research_team.platform.shared.registry_cache import ExpiringLruCache

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class DialogueMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class SocraticFraming:
    """What the dialogue is for, decided once from the topic.

    Produced by `SocraticExecutor.frame` and written to the stream by `begin`,
    which is what makes it survive an eviction -- a framing held only in the
    registry would be gone with it.
    """

    goal: str
    stopping_condition: str
    opening_prompt: str


@dataclass(frozen=True)
class SocraticObservation:
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""


@dataclass(frozen=True)
class SocraticPrompt:
    """The dialogue's NEXT question, not a reply to anything.

    Named for what it holds -- an earlier draft called this `SocraticReply`
    with a `text` field, which put a question in a field named for the reader's
    answer and is precisely the confusion the naming ruling exists to prevent.
    """

    prompt: str
    citations: tuple[Citation, ...] = ()
    observation: SocraticObservation | None = None
    concluded: bool = False
    """The stopping condition was met by the exchange that produced this.
    `prompt` is empty when so -- there is no further question."""
    position: int = 0
    """Which exchange of this dialogue this is, zero-based -- the same number
    `SocraticTurnRow.position` stores. Counted from the rehydrated history
    *before* this turn's pair is appended, so it is the count of exchanges
    behind this one -- `len(messages) // 2`, and see `respond` for why the
    leading opening question does NOT make that `(len - 1) // 2`."""


@dataclass(frozen=True)
class SocraticDialogueOpened:
    dialogue_id: UUID
    goal: str
    stopping_condition: str
    pending_prompt: str
    """The question the reader is looking at right now: the opening one on a
    fresh dialogue, the outstanding one on a resumed dialogue. Named for what
    it is rather than `opening_prompt`, because after an eviction it is not the
    opening question and a page that labelled it so would be lying."""
    topic: str = ""


SocraticNote = SocraticDialogueOpened | ActivityNote | SocraticPrompt
"""What `SocraticDialogueService.respond` yields: the framing first, then
activity as it happens, then one question last."""


class UnknownDialogue(LookupError):
    """No dialogue by that id in that project -- or one that has concluded.

    A refusal rather than a fresh start. The three cases it covers are set out
    on `SocraticDialogueService._resume`. Two of them -- a guessed id and
    another project's -- stay one exception on purpose, because a caller has
    the same move for both and telling them apart would tell a prober which
    ids exist.

    The third no longer shares that move: see `DialogueConcluded`, which is a
    subclass so this arm still catches it.
    """


class DialogueConcluded(UnknownDialogue):
    """This dialogue exists, belongs to this project, and has finished.

    A subclass, not a sibling, so every existing `except UnknownDialogue` keeps
    catching it and no call site changes behaviour silently when a dialogue
    starts being able to conclude. That is deliberate and it has a cost: a
    caller that wants the narrower case must order its `except` arms with this
    one *first*, or the broader arm swallows it and the code reads as working.
    `reply_to_dialogue` is the one caller that does, and
    `test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing`
    is what fails -- with a 404 -- if the arms are ever swapped back.

    Why it is worth the cost: a concluded dialogue is the reader's own and its
    history is still stored. Reporting it as absent says the opposite.
    """


class DialogueInFlight(RuntimeError):
    """Raised when a dialogue already has a reply running.

    One reply at a time per dialogue, for `AskInFlight`'s reason -- and here it
    would also interleave two writes to one stream.
    """


@dataclass(frozen=True)
class LiveDialogue:
    dialogue_id: UUID
    project_id: UUID
    goal: str
    stopping_condition: str
    messages: tuple[DialogueMessage, ...] = ()
    """The conversation so far, alternating assistant/user and *starting* with
    the assistant -- the opening question is `messages[0]`. The outstanding
    question is simply `messages[-1]`, so nothing here caches it."""
    used_at: float = 0.0
    topic: str = ""

    def appended(self, *messages: DialogueMessage, at: float) -> "LiveDialogue":
        return replace(self, messages=(*self.messages, *messages), used_at=at)


class DialogueRegistry:
    """Live dialogues, bounded two ways -- and only a cache.

    The defaults match `ConversationRegistry`'s (64 entries, an hour idle) and
    are guesses at a single-user console rather than measurements.

    **`get` returns `None` on a miss.** That is the one line that differs from
    the neighbour this is otherwise modelled on, and it is the whole of §2 of
    the design. `ConversationRegistry.get` hands back a fresh `Conversation`
    with a fresh stream id, so an evicted ask starts over silently; here the
    caller is made to decide, and the only honest decisions are "rehydrate" and
    "refuse".
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
        self._cache: ExpiringLruCache[UUID, LiveDialogue] = ExpiringLruCache(
            now=now,
            limit=limit,
            idle_seconds=idle_seconds,
            get_used_at=lambda d: d.used_at,
            get_project_id=lambda d: d.project_id,
        )
        self._held: OrderedDict[UUID, LiveDialogue] = self._cache._held

    def __len__(self) -> int:
        return len(self._cache)

    def __bool__(self) -> bool:
        """Always true. A registry exists or it does not; it is never absent
        for being empty.
        """
        return True

    def __contains__(self, dialogue_id: UUID) -> bool:
        return dialogue_id in self._cache

    def contains(self, dialogue_id: UUID, project_id: UUID | None = None) -> bool:
        """Check whether a dialogue is currently active in memory and unexpired."""
        return self._cache.contains(dialogue_id, project_id)

    def get(self, dialogue_id: UUID, project_id: UUID) -> LiveDialogue | None:
        return self._cache.get(dialogue_id, project_id)

    def put(self, dialogue: LiveDialogue) -> None:
        self._cache.put(dialogue.dialogue_id, dialogue)

    def drop(self, dialogue_id: UUID) -> None:
        self._cache.drop(dialogue_id)

    def clear(self) -> None:
        """Evict all cached dialogues."""
        self._cache.clear()

    def evict_idle(self, now: float | None = None) -> int:
        """Explicitly prune all dialogues that exceeded idle_seconds."""
        return self._cache.evict_idle(now)

    def active_ids(self, project_id: UUID | None = None) -> list[UUID]:
        """List active, non-expired dialogue IDs currently held in cache."""
        return self._cache.active_keys(project_id)


class SocraticExecutor(Protocol):
    """Frames a dialogue, and takes one turn in it.

    Two methods rather than one because they happen at different times and want
    different things: `frame` runs once, from a topic, and produces the goal and
    stopping condition that everything after it is measured against; `respond`
    runs per exchange and is handed that framing rather than deriving it.

    Keeping the framing out of `respond` is what makes the stopping condition
    testable. The agent is built fresh per turn with no checkpointer -- a
    `MemorySaver` was tried on the ask path and raised, because `astream`
    passes no `thread_id` -- so a stopping condition held in the model's context
    would not survive a turn boundary, let alone an eviction. It lives in the
    aggregate, which is the right place for it anyway: a stopping condition
    decided inside an LLM's context is one nothing can test.

    `on_activity` must not be called after `respond` returns, for the reason
    `AskExecutor` states at length -- the drain loop relies on every report
    happening-before the executor task's completion.
    """

    async def frame(self, *, project_id: UUID, topic: str) -> SocraticFraming: ...

    async def respond(
        self,
        *,
        project_id: UUID,
        history: Sequence[DialogueMessage],
        goal: str,
        stopping_condition: str,
        reply: str,
        on_activity: ActivityReporter,
    ) -> SocraticPrompt: ...


class DialogueReadModel(Protocol):
    """Where a dropped dialogue is read back from.

    Typed over `Any` deliberately: the application layer cannot name
    `SocraticDialogueRow` without importing infrastructure, and the service
    reads only `.project_id`, `.goal`, `.stopping_condition`, `.status`,
    `.opening_prompt`, `.prompt` and `.reply`. Structural typing is what lets
    `SocraticDialogueRunner` satisfy this with no adapter.
    """

    async def get(self, dialogue_id: UUID) -> Any | None: ...

    async def turns_for(self, dialogue_id: UUID) -> list[Any]: ...


__all__ = [
    "DialogueConcluded",
    "DialogueInFlight",
    "DialogueMessage",
    "DialogueReadModel",
    "DialogueRegistry",
    "LiveDialogue",
    "Role",
    "SocraticDialogueOpened",
    "SocraticExecutor",
    "SocraticFraming",
    "SocraticNote",
    "SocraticObservation",
    "SocraticPrompt",
    "UnknownDialogue",
]
