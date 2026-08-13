# Project Ask Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A third project page where a person asks questions about the material a project has gathered, answered by a read-only agent that persists nothing.

**Architecture:** A parallel path beside `SessionService`, never through it. `application/ask.py` holds framework-free conversation state and orchestration behind an `AskExecutor` port; `infrastructure/agent/ask_agent.py` implements that port with `create_deep_agent`, a name-allowlisted read-only tool set and a write-refusing filesystem backend. One `POST` route streams a single question's answer as its own SSE response. The browser owns a new `ask` route facet, a pure transcript fold, a zustand store and a `fetch`-based SSE reader.

**Tech Stack:** Python 3.12, FastAPI, LangChain/`deepagents`, `eventsource`, pytest. React 19, wouter, zustand, TanStack Query, zod, Tailwind 4, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-12-project-ask-page-design.md`

## Global Constraints

- **Four gates, all of them.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands cover the whole repository, including test files.
- **The layer rule is enforced by `tests/test_architecture.py`.** `research_team/application/` may import `eventsource` and nothing else framework-shaped — no `langchain`, `langchain_core`, `deepagents`, `redstring`. Every LangChain type in this plan lives in `infrastructure/`.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **Nothing this feature adds may write to the event store.** No new events, no new read models, no projection changes.
- **Frontend imports carry explicit extensions** (`.ts` / `.tsx`) and use the `@domain` / `@application` / `@infrastructure` / `@presentation` / `@app` aliases.
- Python tests are async with no `@pytest.mark.asyncio` decorator (asyncio auto mode via `tests/conftest.py`).
- Commit messages follow `CLAUDE.md`: why, not what; state costs and what is deliberately left undone.

---

### Task 1: A filesystem backend that refuses to write

**Files:**
- Create: `research_team/infrastructure/agent/read_only_backend.py`
- Test: `tests/infrastructure/test_read_only_backend.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ReadOnlyProjectBackend(files: dict[str, Any])` with `_read_files() -> dict[str, Any]` and `_send_files_update(update: dict[str, Any]) -> NoReturn`; raises `ReadOnlyFilesystem(RuntimeError)`.

`EventSourcedBackend` in `backend.py` shows the shape: `StateBackend` implements every file tool in terms of `_read_files` and `_send_files_update`, and its module docstring says not to reimplement inherited methods. This variant overrides the same two, reading a snapshot dict and refusing every write.

- [ ] **Step 1: Write the failing test**

```python
"""A filesystem the ask agent can read and cannot write.

The refusal is loud on purpose. A backend that silently dropped writes would
let a prompt believe it had saved something, and the failure would surface
later as absence rather than as an error.
"""

import pytest

from research_team.infrastructure.agent.read_only_backend import (
    ReadOnlyFilesystem,
    ReadOnlyProjectBackend,
)


def test_files_given_at_construction_are_readable():
    """The agent's whole reason to have a filesystem is reading what a project wrote."""
    backend = ReadOnlyProjectBackend({"notes.md": {"content": "hello"}})

    assert backend._read_files() == {"notes.md": {"content": "hello"}}


def test_a_write_raises_rather_than_being_dropped():
    """Silence here would read as success to the model and as data loss to a person."""
    backend = ReadOnlyProjectBackend({})

    with pytest.raises(ReadOnlyFilesystem):
        backend._send_files_update({"notes.md": {"content": "hello"}})


def test_the_snapshot_is_copied_so_a_caller_cannot_mutate_it_afterwards():
    """Handing out the caller's own dict would be a write path with extra steps."""
    files = {"notes.md": {"content": "hello"}}
    backend = ReadOnlyProjectBackend(files)
    files["other.md"] = {"content": "snuck in"}

    assert "other.md" not in backend._read_files()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_read_only_backend.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_team.infrastructure.agent.read_only_backend'`

- [ ] **Step 3: Write minimal implementation**

```python
"""A `StateBackend` over a snapshot of a project's files, with writes refused.

`EventSourcedBackend` turns the deep agent's file tools into domain events.
This one turns the reads into dictionary lookups and the writes into an
exception, because the ask page has no session to append to and no business
appending to one.

As in `backend.py`: `StateBackend` implements every file tool in terms of the
two methods below. Do not reimplement any inherited method.
"""

from typing import Any, NoReturn

from deepagents.backends.state import StateBackend


class ReadOnlyFilesystem(RuntimeError):
    """Raised when the ask agent tries to write.

    A distinct type so a test can name it, and so a caller can tell this
    apart from a genuine backend fault.
    """


class ReadOnlyProjectBackend(StateBackend):
    def __init__(self, files: dict[str, Any]) -> None:
        # Copied, not aliased: the caller's dict is a live project snapshot
        # elsewhere, and sharing it would make this backend writable by
        # accident.
        self._files = dict(files)

    def _read_files(self) -> dict[str, Any]:
        return dict(self._files)

    def _send_files_update(self, update: dict[str, Any]) -> NoReturn:
        raise ReadOnlyFilesystem(
            f"the ask agent cannot write files (attempted: {sorted(update)})"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_read_only_backend.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/agent/read_only_backend.py tests/infrastructure/test_read_only_backend.py
git commit -m "A filesystem the ask agent can read and cannot write

The ask page has no session to append to, so the deep agent's file tools
need a backend that is not the event-sourced one. Writes raise instead of
no-opping: a dropped write would look like success to the model and like
data loss to a person, and only the raising version can be pinned by a test."
```

---

### Task 2: Ephemeral conversation state

**Files:**
- Create: `research_team/application/ask.py`
- Test: `tests/application/test_ask_registry.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all framework-free and importable from `research_team.application.ask`:
  - `AskMessage(role: Literal["user", "assistant"], text: str)` — frozen dataclass.
  - `Citation(kind: Literal["source", "topic"], id: str)` — frozen dataclass.
  - `AskAnswer(text: str, citations: tuple[Citation, ...])` — frozen dataclass.
  - `Conversation(chat_id: str, project_id: UUID, messages: tuple[AskMessage, ...], used_at: float)` — frozen dataclass with `appended(*messages: AskMessage, at: float) -> Conversation`.
  - `ConversationRegistry(now: Callable[[], float], limit: int = 64, idle_seconds: float = 3600.0)` with `get(chat_id, project_id) -> Conversation`, `put(conversation) -> None`, `drop(chat_id) -> None`, `__len__`.

This file grows further in Task 3; this task establishes only the state.

- [ ] **Step 1: Write the failing test**

```python
"""In-memory conversations for the ask page, and the bounds on keeping them.

Nothing here is persisted. The registry exists so a follow-up question can see
the question before it within one browser tab, and the bounds exist so a
long-lived server cannot accumulate conversations without limit.
"""

from uuid import uuid4

from research_team.application.ask import AskMessage, Conversation, ConversationRegistry


def registry(clock, **kwargs) -> ConversationRegistry:
    return ConversationRegistry(now=clock, **kwargs)


def test_an_unknown_chat_id_yields_an_empty_conversation():
    """A first question should not need the browser to announce itself first."""
    conversations = registry(lambda: 0.0)

    conversation = conversations.get("chat-1", uuid4())

    assert conversation.messages == ()


def test_a_stored_conversation_comes_back_with_its_messages():
    """This is the whole point of holding them: a follow-up sees what came before."""
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conversation = conversations.get("chat-1", project).appended(
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
        at=0.0,
    )
    conversations.put(conversation)

    assert conversations.get("chat-1", project).messages == (
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
    )


def test_a_conversation_idle_past_the_ttl_is_forgotten():
    """Held forever, an ephemeral store is just a leak with a nicer name."""
    project = uuid4()
    clock = iter([0.0, 0.0, 3_601.0])
    conversations = registry(lambda: next(clock), idle_seconds=3_600.0)
    conversations.put(
        conversations.get("chat-1", project).appended(
            AskMessage(role="user", text="hello"), at=0.0
        )
    )

    assert conversations.get("chat-1", project).messages == ()


def test_the_least_recently_used_conversation_is_evicted_at_the_limit():
    """A bound that only trims the newest would evict the chat someone is using."""
    project = uuid4()
    ticks = iter(range(100))
    conversations = registry(lambda: float(next(ticks)), limit=2)
    for chat_id in ("a", "b"):
        conversations.put(
            conversations.get(chat_id, project).appended(
                AskMessage(role="user", text=chat_id), at=0.0
            )
        )
    conversations.get("a", project)  # touch: 'b' is now the least recent

    conversations.put(
        conversations.get("c", project).appended(AskMessage(role="user", text="c"), at=0.0)
    )

    assert len(conversations) == 2
    assert conversations.get("a", project).messages != ()
    assert conversations.get("b", project).messages == ()


def test_a_chat_id_belonging_to_another_project_is_not_served():
    """Chat ids come from the browser; one must not read another project's answers."""
    conversations = registry(lambda: 0.0)
    conversations.put(
        conversations.get("chat-1", uuid4()).appended(
            AskMessage(role="user", text="secret"), at=0.0
        )
    )

    assert conversations.get("chat-1", uuid4()).messages == ()


def test_dropping_a_conversation_forgets_it():
    """The 'new chat' control has to mean something on the server too."""
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conversations.put(
        conversations.get("chat-1", project).appended(
            AskMessage(role="user", text="hello"), at=0.0
        )
    )

    conversations.drop("chat-1")

    assert conversations.get("chat-1", project).messages == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_ask_registry.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_team.application.ask'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_ask_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: Verify the layer rule still holds**

Run: `uv run pytest tests/test_architecture.py -v`
Expected: PASS — `application/ask.py` names no framework.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/ask.py tests/application/test_ask_registry.py
git commit -m "Ephemeral conversation state for asking a project

Held in memory, keyed by a browser-supplied chat id, bounded by count and
by idle time. The bounds are guesses at a single-user console rather than
measurements; LRU rather than newest-first because trimming the newest
evicts the chat someone is using.

A chat id's project is checked rather than trusted, since the id comes from
the browser and a guessed one must not read another project's answers.

The whole module is framework-free: tests/test_architecture.py holds the
application layer to eventsource alone, so the LangChain half of this
feature will sit behind a port."
```

---

### Task 3: The service, its port, and the one-at-a-time rule

**Files:**
- Modify: `research_team/application/ask.py` (append; do not disturb Task 2's contents)
- Test: `tests/application/test_ask_service.py`

**Interfaces:**
- Consumes: `AskMessage`, `Citation`, `AskAnswer`, `Conversation`, `ConversationRegistry` from Task 2; `ActivityMessage`, `ActivityDelta`, `ActivityNote`, `ActivityReporter` from `research_team.application.ports`.
- Produces:
  - `AskInFlight(RuntimeError)`.
  - `class AskExecutor(Protocol)` with
    `async def run(self, *, project_id: UUID, history: Sequence[AskMessage], question: str, on_activity: ActivityReporter) -> AskAnswer`.
  - `AskService(executor: AskExecutor, conversations: ConversationRegistry, now: Callable[[], float])` with
    `def ask(self, *, project_id: UUID, chat_id: str, question: str) -> AsyncIterator[AskNote]` and
    `def forget(self, chat_id: str) -> None`.
  - `AskNote = ActivityNote | AskAnswer` — what the iterator yields, ending with the `AskAnswer`.

The iterator streams the executor's activity as it happens: the reporter feeds an `asyncio.Queue`, the executor runs as a task, and the loop drains the queue until the task finishes.

- [ ] **Step 1: Write the failing test**

```python
"""What the ask service guarantees around an executor it does not trust.

Streaming order, the one-at-a-time rule, and the fact that a failed answer
leaves no half-conversation behind.
"""

import asyncio
from collections.abc import Sequence
from uuid import uuid4

import pytest

from research_team.application.ask import (
    AskAnswer,
    AskInFlight,
    AskMessage,
    AskService,
    Citation,
    ConversationRegistry,
)
from research_team.application.ports import ActivityDelta, ActivityReporter


class FakeExecutor:
    """Records what it was asked, reports the notes it was told to, answers."""

    def __init__(self, notes=(), answer=AskAnswer(text="an answer"), fail=None):
        self.notes = list(notes)
        self.answer = answer
        self.fail = fail
        self.calls: list[tuple[Sequence[AskMessage], str]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def run(self, *, project_id, history, question, on_activity: ActivityReporter):
        self.calls.append((tuple(history), question))
        self.started.set()
        await self.release.wait()
        for note in self.notes:
            on_activity(note)
        if self.fail is not None:
            raise self.fail
        return self.answer


def service(executor, **kwargs) -> AskService:
    return AskService(
        executor=executor,
        conversations=ConversationRegistry(now=lambda: 0.0, **kwargs),
        now=lambda: 0.0,
    )


async def drain(iterator):
    return [note async for note in iterator]


async def test_activity_is_yielded_before_the_answer():
    """A page that only saw the answer would have nothing to stream."""
    delta = ActivityDelta(message_id="m1", text="think")
    ask = service(FakeExecutor(notes=[delta]))

    notes = await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))

    assert notes[0] == delta
    assert notes[-1] == AskAnswer(text="an answer")


async def test_the_next_question_sees_the_previous_exchange():
    """'And the second one?' is the reason conversations are held at all."""
    executor = FakeExecutor(answer=AskAnswer(text="two papers"))
    ask = service(executor)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="what did we find?"))
    await drain(ask.ask(project_id=project, chat_id="c", question="and the second?"))

    history, question = executor.calls[1]
    assert question == "and the second?"
    assert history == (
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
    )


async def test_a_second_question_on_the_same_chat_is_refused_while_one_runs():
    """Two answers interleaving into one transcript is worse than a refusal."""
    executor = FakeExecutor()
    executor.release.clear()
    ask = service(executor)
    project = uuid4()

    first = asyncio.create_task(
        drain(ask.ask(project_id=project, chat_id="c", question="one"))
    )
    await executor.started.wait()

    with pytest.raises(AskInFlight):
        await drain(ask.ask(project_id=project, chat_id="c", question="two"))

    executor.release.set()
    await first


async def test_a_different_chat_may_ask_while_one_is_running():
    """The bound is per conversation; two tabs are not each other's problem."""
    executor = FakeExecutor()
    executor.release.clear()
    ask = service(executor)
    project = uuid4()

    first = asyncio.create_task(
        drain(ask.ask(project_id=project, chat_id="a", question="one"))
    )
    await executor.started.wait()
    executor.release.set()

    notes = await drain(ask.ask(project_id=project, chat_id="b", question="two"))

    assert notes[-1] == AskAnswer(text="an answer")
    await first


async def test_a_failed_answer_leaves_the_question_out_of_the_history():
    """Half an exchange would make the next answer reference a reply nobody saw."""
    executor = FakeExecutor(fail=RuntimeError("model fell over"))
    ask = service(executor)
    project = uuid4()

    with pytest.raises(RuntimeError):
        await drain(ask.ask(project_id=project, chat_id="c", question="one"))

    executor.fail = None
    await drain(ask.ask(project_id=project, chat_id="c", question="two"))
    history, _ = executor.calls[1]
    assert history == ()


async def test_a_failure_releases_the_chat_for_the_next_question():
    """A crash that left the slot held would need a page reload to clear."""
    executor = FakeExecutor(fail=RuntimeError("model fell over"))
    ask = service(executor)
    project = uuid4()

    with pytest.raises(RuntimeError):
        await drain(ask.ask(project_id=project, chat_id="c", question="one"))

    executor.fail = None
    notes = await drain(ask.ask(project_id=project, chat_id="c", question="two"))
    assert notes[-1] == AskAnswer(text="an answer")


async def test_citations_travel_with_the_answer():
    """The page renders them beside the reply, so they arrive together."""
    answer = AskAnswer(text="two papers", citations=(Citation(kind="source", id="s1"),))
    ask = service(FakeExecutor(answer=answer))

    notes = await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))

    assert notes[-1].citations == (Citation(kind="source", id="s1"),)


async def test_forgetting_a_chat_clears_its_history():
    """'New chat' has to mean the next question starts from nothing."""
    executor = FakeExecutor()
    ask = service(executor)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="one"))
    ask.forget("c")
    await drain(ask.ask(project_id=project, chat_id="c", question="two"))

    history, _ = executor.calls[1]
    assert history == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_ask_service.py -v`
Expected: FAIL, `ImportError: cannot import name 'AskService'`

- [ ] **Step 3: Write minimal implementation**

Append to `research_team/application/ask.py`, and extend its imports to
`import asyncio`, `from collections.abc import AsyncIterator, Callable, Sequence`,
`from typing import Protocol`, plus
`from research_team.application.ports import ActivityNote, ActivityReporter`.

```python
class AskInFlight(RuntimeError):
    """Raised when a chat already has a question running.

    One answer at a time per conversation. Two streams interleaving into one
    transcript is a worse outcome for the reader than a refusal they can act
    on.
    """


class AskExecutor(Protocol):
    """Answers one question against a project's gathered material.

    Implemented in `infrastructure/agent/ask_agent.py`; the port exists so
    this layer never names LangChain.
    """

    async def run(
        self,
        *,
        project_id: UUID,
        history: Sequence[AskMessage],
        question: str,
        on_activity: ActivityReporter,
    ) -> AskAnswer: ...


AskNote = ActivityNote | AskAnswer
"""What `AskService.ask` yields: activity as it happens, then one answer last."""


class AskService:
    def __init__(
        self,
        *,
        executor: AskExecutor,
        conversations: ConversationRegistry,
        now: Callable[[], float],
    ) -> None:
        self._executor = executor
        self._conversations = conversations
        self._now = now
        self._running: set[str] = set()

    def forget(self, chat_id: str) -> None:
        self._conversations.drop(chat_id)

    async def ask(
        self, *, project_id: UUID, chat_id: str, question: str
    ) -> AsyncIterator[AskNote]:
        if chat_id in self._running:
            raise AskInFlight(f"chat {chat_id} already has a question running")
        self._running.add(chat_id)
        try:
            conversation = self._conversations.get(chat_id, project_id)
            # The queue is what turns a callback-shaped reporter into an
            # iterator: the executor pushes notes from whatever task it runs
            # on, and the loop below drains them while awaiting the answer.
            notes: asyncio.Queue[ActivityNote] = asyncio.Queue()
            running = asyncio.create_task(
                self._executor.run(
                    project_id=project_id,
                    history=conversation.messages,
                    question=question,
                    on_activity=notes.put_nowait,
                )
            )
            async for note in self._drain(notes, running):
                yield note
            answer = await running
        finally:
            self._running.discard(chat_id)

        # Recorded only on success. A stored question with no reply would make
        # the next answer refer to an exchange the reader never saw.
        self._conversations.put(
            conversation.appended(
                AskMessage(role="user", text=question),
                AskMessage(role="assistant", text=answer.text),
                at=self._now(),
            )
        )
        yield answer

    @staticmethod
    async def _drain(
        notes: "asyncio.Queue[ActivityNote]", running: "asyncio.Task[AskAnswer]"
    ) -> AsyncIterator[ActivityNote]:
        while True:
            getter = asyncio.ensure_future(notes.get())
            done, _ = await asyncio.wait(
                {getter, running}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                yield getter.result()
                continue
            getter.cancel()
            # The executor finished; anything it queued just before returning
            # is still owed to the reader.
            while not notes.empty():
                yield notes.get_nowait()
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_ask_service.py tests/application/test_ask_registry.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/application/ask.py tests/application/test_ask_service.py
git commit -m "The ask service, and the rules it holds an executor to

One question at a time per conversation, because two answers interleaving
into one transcript is worse for a reader than a refusal. The exchange is
recorded only when the answer succeeds -- a stored question with no reply
would make the following answer refer to something nobody saw.

The queue drain is the awkward part and is deliberate: the executor reports
activity through a callback, the route wants an iterator, and this is the
seam between them. It re-yields anything queued just before the executor
returned, which a naive loop drops."
```

---

### Task 4: The read-only deep agent

**Files:**
- Create: `research_team/infrastructure/agent/ask_agent.py`
- Test: `tests/infrastructure/test_ask_agent.py`

**Interfaces:**
- Consumes: `AskMessage`, `AskAnswer`, `Citation`, `AskExecutor` from Task 3; `ReadOnlyProjectBackend` from Task 1; `to_activity_message` / `to_activity_delta` / `MAIN_AGENT_NODE` from `research_team.infrastructure.agent.deep_agent`; the tool-name constants `LIST_SOURCES_TOOL`, `READ_SOURCE_TOOL` (`application.corpus_read`), `GRAPH_SEARCH_TOOL` (`application.knowledge`), `LIST_TOPICS_TOOL`, `OPEN_TOPIC_TOOL` (`application.topics`).
- Produces:
  - `READ_ONLY_TOOLS: frozenset[str]` — the five admitted names.
  - `readable(tools: Iterable[BaseTool]) -> tuple[BaseTool, ...]` — allowlist filter.
  - `citations(messages: Sequence[BaseMessage]) -> tuple[Citation, ...]`.
  - `DeepAgentAskExecutor(model, open_graph, project_files, system_prompt=ASK_PROMPT)` implementing `AskExecutor`, where `open_graph: Callable[[UUID], Awaitable[tuple[Any, tuple[BaseTool, ...]]]]` and `project_files: Callable[[UUID], Awaitable[dict[str, Any]]]`.

Note `open_graph` is a closure built inside `build_application`, not a module function; it is injected here and wired in Task 5.

**The allowlist is the security boundary.** A tool added to `open_graph` later is excluded until someone adds its name here on purpose.

**Citations come from tool calls, not prose.** Only `read_source` and `open_topic` name a specific thing they read; `graph_search` and `list_sources` are searches, and searching is not reading. Scanning the final message list for those two tool calls needs no tool wrapping and is testable with plain message fixtures.

- [ ] **Step 1: Write the failing test**

```python
"""The agent behind the ask page: what it may touch, and what it may cite.

The two assertions that carry the design are here -- the exact tool set, and
that a citation can only name something a tool actually opened.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from research_team.application.ask import Citation
from research_team.infrastructure.agent.ask_agent import (
    READ_ONLY_TOOLS,
    citations,
    readable,
)


def named(name: str):
    @tool(name)
    def _stub(argument: str = "") -> str:
        """A stand-in for a project tool."""
        return ""

    return _stub


def test_the_admitted_tools_are_exactly_the_five_readers():
    """This set is the security boundary; a change to it should be deliberate."""
    assert READ_ONLY_TOOLS == frozenset(
        {"list_sources", "read_source", "graph_search", "list_topics", "open_topic"}
    )


def test_every_mutating_project_tool_is_filtered_out():
    """The ask page must not be a second way to edit a project's knowledge."""
    tools = [
        named(name)
        for name in (
            "remember",
            "remember_page",
            "unmerge",
            "record_finding",
            "record_gap",
            "link_source",
            "fetch",
            "web_search",
            "read_source",
        )
    ]

    assert [kept.name for kept in readable(tools)] == ["read_source"]


def test_a_tool_nobody_has_admitted_yet_is_excluded():
    """An allowlist so that a tool added to open_graph later cannot arrive here
    by default. This test is the one that fails when that happens."""
    assert readable([named("summarise_everything")]) == ()


def test_a_read_source_call_becomes_a_source_citation():
    """A citation records a read, and this is what reading a source looks like."""
    messages = [
        HumanMessage(content="what did we find?"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"}
            ],
        ),
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_an_open_topic_call_becomes_a_topic_citation():
    """The other tool that names one identified thing it opened."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "open_topic", "args": {"topic_id": "t-9"}, "id": "t1"}
            ],
        )
    ]

    assert citations(messages) == (Citation(kind="topic", id="t-9"),)


def test_a_search_is_not_a_citation():
    """Searching is not reading. graph_search returns candidates the agent may
    never open, and citing them would overstate what it looked at."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "graph_search", "args": {"query": "boundary layer"}, "id": "t1"},
                {"name": "list_sources", "args": {}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == ()


def test_the_same_source_read_twice_is_cited_once():
    """A citation list is a set of things read, not a tally of reads."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_citation_order_follows_the_order_things_were_read():
    """Stable output; a set would reorder the list between identical runs."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "b"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "a"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (
        Citation(kind="source", id="b"),
        Citation(kind="source", id="a"),
    )


def test_a_tool_call_without_its_identifying_argument_is_skipped():
    """A malformed call should not produce a citation to nothing."""
    messages = [
        AIMessage(
            content="", tool_calls=[{"name": "read_source", "args": {}, "id": "t1"}]
        )
    ]

    assert citations(messages) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_ask_agent.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_team.infrastructure.agent.ask_agent'`

- [ ] **Step 3: Write minimal implementation**

```python
"""A deep agent that can read a project and change nothing about it.

The executor behind `AskService`. It reuses the project tools that
`build_application.open_graph` assembles, keeps only the readers, and gives
the built-in file tools a backend that refuses to write.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any
from uuid import UUID

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from research_team.application.ask import AskAnswer, AskMessage, Citation
from research_team.application.corpus_read import LIST_SOURCES_TOOL, READ_SOURCE_TOOL
from research_team.application.knowledge import GRAPH_SEARCH_TOOL
from research_team.application.ports import ActivityReporter
from research_team.application.topics import LIST_TOPICS_TOOL, OPEN_TOPIC_TOOL
from research_team.infrastructure.agent.deep_agent import (
    to_activity_delta,
    to_activity_message,
)
from research_team.infrastructure.agent.read_only_backend import ReadOnlyProjectBackend

READ_ONLY_TOOLS = frozenset(
    {
        LIST_SOURCES_TOOL,
        READ_SOURCE_TOOL,
        GRAPH_SEARCH_TOOL,
        LIST_TOPICS_TOOL,
        OPEN_TOPIC_TOOL,
    }
)
"""The tools the ask agent may hold.

An allowlist rather than a denylist so that a tool added to `open_graph`
later is excluded until someone names it here. `fetch` and `web_search` are
absent, which is also why this path wires no approval gate: there is nothing
to gate.
"""

CITED_BY_TOOL = {READ_SOURCE_TOOL: ("source", "source_id"), OPEN_TOPIC_TOOL: ("topic", "topic_id")}
"""Tool name -> (citation kind, the argument naming what was read).

Only these two open one identified thing. A search returns candidates the
agent may never read, so it earns no citation.
"""

ASK_PROMPT = """You are answering questions about one research project's gathered material.

Use the tools to look things up before answering. You can read the project's
sources, its knowledge graph, its topics and its files. You cannot change any
of them, and you have no access to the web -- if the material does not answer
the question, say so plainly rather than filling the gap from memory.

Prefer quoting what a source actually says over paraphrasing it, and say which
source you got something from."""


def readable(tools: Iterable[BaseTool]) -> tuple[BaseTool, ...]:
    return tuple(tool for tool in tools if tool.name in READ_ONLY_TOOLS)


def citations(messages: Sequence[BaseMessage]) -> tuple[Citation, ...]:
    """What the agent opened, in the order it opened it.

    Derived from tool calls rather than from the answer's prose, so the agent
    cannot cite a document it never read. Ordered rather than a set, so two
    identical runs produce identical output.
    """
    found: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        for call in getattr(message, "tool_calls", ()) or ():
            cited = CITED_BY_TOOL.get(call.get("name", ""))
            if cited is None:
                continue
            kind, argument = cited
            identifier = (call.get("args") or {}).get(argument)
            if not identifier or (kind, str(identifier)) in seen:
                continue
            seen.add((kind, str(identifier)))
            found.append(Citation(kind=kind, id=str(identifier)))
    return tuple(found)


def _history(history: Sequence[AskMessage], question: str) -> list[BaseMessage]:
    prior: list[BaseMessage] = [
        HumanMessage(content=message.text)
        if message.role == "user"
        else AIMessage(content=message.text)
        for message in history
    ]
    return [*prior, HumanMessage(content=question)]


class DeepAgentAskExecutor:
    """Runs one question. Builds a fresh agent per question, as the turn
    executor does per pass -- the tools are bound to a project and a stale
    agent would answer about the wrong one."""

    def __init__(
        self,
        *,
        model: BaseChatModel,
        open_graph: Callable[[UUID], Awaitable[tuple[Any, tuple[BaseTool, ...]]]],
        project_files: Callable[[UUID], Awaitable[dict[str, Any]]],
        system_prompt: str = ASK_PROMPT,
    ) -> None:
        self._model = model
        self._open_graph = open_graph
        self._project_files = project_files
        self._system_prompt = system_prompt

    async def run(
        self,
        *,
        project_id: UUID,
        history: Sequence[AskMessage],
        question: str,
        on_activity: ActivityReporter,
    ) -> AskAnswer:
        _knowledge, project_tools = await self._open_graph(project_id)
        agent = create_deep_agent(
            model=self._model,
            tools=list(readable(project_tools)) or None,
            backend=ReadOnlyProjectBackend(await self._project_files(project_id)),
            system_prompt=self._system_prompt,
            checkpointer=MemorySaver(),
        )

        messages = _history(history, question)
        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        async for mode, chunk in agent.astream(
            {"messages": messages}, stream_mode=["values", "messages"]
        ):
            if mode == "values":
                final = chunk.get("messages", final)
                for message in final[reported:]:
                    note = to_activity_message(message)
                    if note is not None:
                        on_activity(note)
                reported = len(final)
            elif mode == "messages":
                delta = to_activity_delta(chunk)
                if delta is not None:
                    on_activity(delta)

        answered = final[-1] if final else None
        text = answered.text() if isinstance(answered, AIMessage) else ""
        return AskAnswer(text=text, citations=citations(final))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_ask_agent.py -v`
Expected: 9 passed

If `AIMessage.text()` is not callable in the installed LangChain version, use the
`content` attribute coerced to `str` instead; check
`research_team/infrastructure/agent/deep_agent.py` for how it reads message text
and match that.

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/agent/ask_agent.py tests/infrastructure/test_ask_agent.py
git commit -m "A deep agent that reads a project and changes nothing

The tool set is an allowlist of five readers rather than a denylist of the
mutators, so a tool added to open_graph later is excluded until someone
admits it here on purpose. The test on the exact names is what fails when
that happens, which is the point of writing it down.

Citations come from tool calls, not from the answer's prose, so the agent
cannot cite a document it never opened. Only read_source and open_topic
count: graph_search returns candidates it may never read, and citing a
search would overstate what it looked at.

fetch and web_search are absent from the set, which is why this path wires
no approval gate -- there is nothing left to gate."
```

---

### Task 5: Wiring and the routes

**Files:**
- Modify: `research_team/composition.py` (add `ask` to `Application`; construct it inside `build_application` beside the `KnowledgeAttachment` wiring, where `open_graph` is in scope)
- Modify: `research_team/interfaces/web/app.py` (`create_app` gains `ask: AskService | None = None`; three routes)
- Modify: `web.py` (pass `ask=application.ask` into `create_app`)
- Test: `tests/interfaces/test_ask_routes.py`

**Interfaces:**
- Consumes: `AskService`, `AskInFlight`, `AskAnswer`, `Citation` (Task 3); `DeepAgentAskExecutor` (Task 4).
- Produces:
  - `Application.ask: AskService`.
  - `POST /api/projects/{project_id}/ask`, body `{"chat_id": str, "question": str}` → `text/event-stream`.
  - `DELETE /api/projects/{project_id}/ask/{chat_id}` → `{"ok": true}`.
  - Frame shapes on the wire, one JSON object per SSE `data:` line:
    - `{"type": "delta", "message_id": str, "text": str}`
    - `{"type": "message", "message_id": str, "kind": "assistant"|"tool", "payload": object, "is_error": bool}`
    - `{"type": "answer", "text": str, "citations": [{"kind": "source"|"topic", "id": str}]}`
    - `{"type": "error", "detail": str}`

`payload` and `kind` mirror `ActivityMessage`, so the browser parses shapes it
already knows from the activity feed.

- [ ] **Step 1: Write the failing test**

```python
"""The ask routes, and the claim that asking writes nothing.

The position assertion is the load-bearing one: it is what makes 'ephemeral'
a property of the system rather than a promise in a document.
"""

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from research_team.application.ask import (
    AskAnswer,
    AskInFlight,
    AskMessage,
    AskService,
    Citation,
    ConversationRegistry,
)
from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.interfaces.web.app import create_app


class StubExecutor:
    def __init__(self, notes=(), answer=AskAnswer(text="an answer")):
        self.notes = list(notes)
        self.answer = answer

    async def run(self, *, project_id, history, question, on_activity):
        for note in self.notes:
            on_activity(note)
        return self.answer


def client(ask: AskService, **kwargs) -> TestClient:
    """`create_app` takes every dependency as a parameter; the ask routes need
    only `ask`, so the rest stay None and their routes stay unexercised."""
    return TestClient(create_app(service=None, feed=None, turns=None, ask=ask, **kwargs))


def ask_service(executor) -> AskService:
    return AskService(
        executor=executor,
        conversations=ConversationRegistry(now=lambda: 0.0),
        now=lambda: 0.0,
    )


def frames(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_the_answer_arrives_last_with_its_citations():
    """The page renders the reply and its citations together."""
    executor = StubExecutor(
        answer=AskAnswer(text="two papers", citations=(Citation(kind="source", id="s1"),))
    )
    response = client(ask_service(executor)).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert response.status_code == 200
    last = frames(response)[-1]
    assert last == {
        "type": "answer",
        "text": "two papers",
        "citations": [{"kind": "source", "id": "s1"}],
    }


def test_activity_is_streamed_before_the_answer():
    """Without this the page has nothing to show while the model works."""
    executor = StubExecutor(
        notes=[
            ActivityDelta(message_id="m1", text="thinking"),
            ActivityMessage(message_id="m2", kind="tool", payload={"name": "read_source"}),
        ]
    )
    response = client(ask_service(executor)).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    kinds = [frame["type"] for frame in frames(response)]
    assert kinds == ["delta", "message", "answer"]


def test_a_failing_executor_reports_an_error_frame_rather_than_a_dead_stream():
    """A stream that just stops is indistinguishable from a slow model."""

    class Broken:
        async def run(self, **_):
            raise RuntimeError("model fell over")

    response = client(ask_service(Broken())).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert frames(response)[-1]["type"] == "error"


def test_a_second_question_on_a_busy_chat_answers_409():
    """The service's one-at-a-time rule has to reach the browser as a status."""

    class Busy:
        async def run(self, **_):
            raise AssertionError("should not have been reached")

    ask = ask_service(Busy())

    async def refuse(**_):
        raise AskInFlight("busy")

    ask.ask = refuse  # type: ignore[method-assign]
    response = client(ask).post(
        f"/api/projects/{uuid4()}/ask", json={"chat_id": "c", "question": "why?"}
    )

    assert response.status_code == 409


def test_deleting_a_chat_forgets_its_history():
    """Backs the 'new chat' control."""
    ask = ask_service(StubExecutor())
    project, app = uuid4(), None
    http = client(ask)
    http.post(f"/api/projects/{project}/ask", json={"chat_id": "c", "question": "one"})

    response = http.delete(f"/api/projects/{project}/ask/c")

    assert response.status_code == 200
    assert ask._conversations.get("c", project).messages == ()
```

Add one integration test in the same file that pins the ephemerality claim
against a real application, in the style of
`tests/integration/test_no_network.py`. Place it at
`tests/integration/test_ask_writes_nothing.py`:

```python
"""Asking a project must leave its log exactly where it found it.

This is what makes the ask page ephemeral in fact rather than by intention.
It fails the moment anything on that path appends an event.
"""

from uuid import uuid4

from research_team.application.ask import AskAnswer


async def test_asking_appends_no_events(application):
    """The whole design rests on this: no session, no events, no tip moved."""

    class Stub:
        async def run(self, *, project_id, history, question, on_activity):
            return AskAnswer(text="an answer")

    application.ask._executor = Stub()
    before = await application.service.repository.latest_position()

    async for _ in application.ask.ask(
        project_id=uuid4(), chat_id="c", question="what did we find?"
    ):
        pass

    assert await application.service.repository.latest_position() == before
```

Reuse whatever `application` fixture the existing integration tests use — read
`tests/integration/test_no_network.py` and `tests/integration/conftest.py` first
and match them, including how they reach the repository's latest position. If
the accessor differs from `application.service.repository.latest_position()`,
use theirs; the assertion is what matters, not the spelling.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/interfaces/test_ask_routes.py -v`
Expected: FAIL, `TypeError: create_app() got an unexpected keyword argument 'ask'`

- [ ] **Step 3: Write the routes**

In `research_team/interfaces/web/app.py`, add `ask: AskService | None = None` to
`create_app`'s parameters, and these routes among the other project routes:

```python
class AskRequest(BaseModel):
    chat_id: str
    question: str


def _ask_frame(note: object) -> str:
    """One SSE `data:` line per note.

    `message` mirrors ActivityMessage's fields so the browser reuses the
    parsing it already has for the session activity feed.
    """
    if isinstance(note, ActivityDelta):
        body = {"type": "delta", "message_id": note.message_id, "text": note.text}
    elif isinstance(note, ActivityMessage):
        body = {
            "type": "message",
            "message_id": note.message_id,
            "kind": note.kind,
            "payload": note.payload,
            "is_error": note.is_error,
        }
    elif isinstance(note, AskAnswer):
        body = {
            "type": "answer",
            "text": note.text,
            "citations": [
                {"kind": citation.kind, "id": citation.id} for citation in note.citations
            ],
        }
    else:  # ActivityRemark and anything added later
        body = {"type": "message", "message_id": "", "kind": "assistant", "payload": {}}
    return f"data: {json.dumps(body)}\n\n"


@app.post("/api/projects/{project_id}/ask")
async def ask_project(project_id: UUID, body: AskRequest):
    if ask is None:
        raise HTTPException(status_code=503, detail="asking is not configured")

    notes = ask.ask(project_id=project_id, chat_id=body.chat_id, question=body.question)
    try:
        first = await anext(notes)
    except AskInFlight as busy:
        # Raised before any streaming begins, so it can still be a status code
        # rather than an error frame the browser has to special-case.
        raise HTTPException(status_code=409, detail=str(busy)) from busy
    except StopAsyncIteration:
        first = None

    async def stream():
        if first is not None:
            yield _ask_frame(first)
        try:
            async for note in notes:
                yield _ask_frame(note)
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            # A stream that simply stops looks identical to a slow model, so a
            # failure is reported in-band before the connection closes.
            yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/projects/{project_id}/ask/{chat_id}")
async def forget_ask(project_id: UUID, chat_id: str):
    if ask is None:
        raise HTTPException(status_code=503, detail="asking is not configured")
    ask.forget(chat_id)
    return {"ok": True}
```

Import `json`, `AskAnswer`, `AskInFlight`, `AskService`, `ActivityDelta` and
`ActivityMessage` at the top of the module alongside the existing imports.

- [ ] **Step 4: Wire the composition root**

In `research_team/composition.py`, add `ask: AskService` to the `Application`
dataclass, and construct it inside `build_application` after `open_graph` and
`close_graph` are defined (they are closures, so this must be in the same
scope):

```python
    ask_service = AskService(
        executor=DeepAgentAskExecutor(
            model=chat_model,
            open_graph=open_graph,
            project_files=service.project_files,
        ),
        conversations=ConversationRegistry(now=time.monotonic),
        now=time.monotonic,
    )
```

Use whatever local name `build_application` already binds the chat model to —
read the surrounding lines rather than assuming `chat_model`. Pass
`ask=ask_service` in the `return Application(...)` call, and in `web.py` pass
`ask=application.ask` into `create_app`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/interfaces/test_ask_routes.py tests/integration/test_ask_writes_nothing.py -v`
Expected: all pass

- [ ] **Step 6: Run the whole backend suite and both ruff gates**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
Expected: all pass. These run over the whole repository, including the new test files.

- [ ] **Step 7: Commit**

```bash
git add research_team/composition.py research_team/interfaces/web/app.py web.py tests/interfaces/test_ask_routes.py tests/integration/test_ask_writes_nothing.py
git commit -m "Routes for asking a project, and a test that it writes nothing

One POST streams a single question's answer as its own SSE response rather
than riding /api/stream. The shared stream carries background processes a
browser discovers after the fact and needs REST catch-up for that reason; an
answer is the response to a request the browser just made, and multiplexing
it would add frame addressing to solve a problem this request does not have.

A busy chat answers 409 rather than an error frame, which is possible only
because the refusal happens before the first note -- hence the awkward
anext() before the StreamingResponse. A failure after streaming starts has
no such option and is reported in-band, because a stream that simply stops
is indistinguishable from a slow model.

The integration test asserting the log's position is unchanged is what makes
'ephemeral' a property of the system rather than a promise in a spec."
```

---

### Task 6: The transcript fold

**Files:**
- Create: `frontend/src/domain/ask/conversation.ts`
- Test: `frontend/src/domain/ask/conversation.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```ts
export interface Citation { readonly kind: 'source' | 'topic'; readonly id: string }
export interface AskActivity { readonly messageId: string; readonly kind: 'assistant' | 'tool'; readonly payload: unknown; readonly isError: boolean }
export interface AskTurn {
  readonly question: string
  readonly answer: string
  readonly activity: readonly AskActivity[]
  readonly citations: readonly Citation[]
  readonly error: string | null
  readonly settled: boolean
}
export type AskTranscript = readonly AskTurn[]
export type AskEvent =
  | { readonly type: 'delta'; readonly messageId: string; readonly text: string }
  | { readonly type: 'message'; readonly messageId: string; readonly kind: 'assistant' | 'tool'; readonly payload: unknown; readonly isError: boolean }
  | { readonly type: 'answer'; readonly text: string; readonly citations: readonly Citation[] }
  | { readonly type: 'error'; readonly detail: string }
export const asked: (transcript: AskTranscript, question: string) => AskTranscript
export const applyEvent: (transcript: AskTranscript, event: AskEvent) => AskTranscript
```

Deltas accumulate into the open turn's `answer`; the `answer` event replaces
that accumulation with the server's text and settles the turn. Replacing rather
than appending matters — the deltas and the final text are the same words, and
appending would double them.

- [ ] **Step 1: Write the failing test**

```ts
/** Folding a stream of ask events into a transcript.
 *
 * Streaming order is where this goes subtly wrong, so the order cases are the
 * ones worth having: a delta before its turn exists, an answer that arrives
 * after deltas already rendered the same words, an error mid-stream.
 */
import { expect, it } from 'vitest'

import { applyEvent, asked, type AskTranscript } from './conversation.ts'

const open = (question = 'what did we find?'): AskTranscript => asked([], question)

it('opens an unsettled turn holding the question', () => {
  const [turn] = open()

  expect(turn.question).toBe('what did we find?')
  expect(turn.answer).toBe('')
  expect(turn.settled).toBe(false)
})

it('accumulates deltas into the open turn', () => {
  let transcript = open()

  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'two ' })
  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'papers' })

  expect(transcript[0].answer).toBe('two papers')
})

it('replaces the accumulated deltas with the final answer rather than appending', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'two papers' })

  transcript = applyEvent(transcript, { type: 'answer', text: 'two papers', citations: [] })

  // Appending would render the answer twice: the deltas are the same words.
  expect(transcript[0].answer).toBe('two papers')
  expect(transcript[0].settled).toBe(true)
})

it('keeps citations with the turn they belong to', () => {
  let transcript = open()

  transcript = applyEvent(transcript, {
    type: 'answer',
    text: 'two papers',
    citations: [{ kind: 'source', id: 's1' }],
  })

  expect(transcript[0].citations).toEqual([{ kind: 'source', id: 's1' }])
})

it('records activity in arrival order', () => {
  let transcript = open()

  transcript = applyEvent(transcript, {
    type: 'message', messageId: 'm1', kind: 'tool', payload: { name: 'read_source' }, isError: false,
  })

  expect(transcript[0].activity).toEqual([
    { messageId: 'm1', kind: 'tool', payload: { name: 'read_source' }, isError: false },
  ])
})

it('settles a turn on error and keeps the reason', () => {
  let transcript = open()

  transcript = applyEvent(transcript, { type: 'error', detail: 'model fell over' })

  expect(transcript[0].error).toBe('model fell over')
  expect(transcript[0].settled).toBe(true)
})

it('leaves a settled turn alone when a late event arrives', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'answer', text: 'done', citations: [] })

  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'late' })

  // A late delta belongs to nothing; writing it into the settled turn would
  // corrupt an answer the reader has already read.
  expect(transcript[0].answer).toBe('done')
})

it('ignores an event with no turn open at all', () => {
  const transcript = applyEvent([], { type: 'delta', messageId: 'm1', text: 'orphan' })

  expect(transcript).toEqual([])
})

it('appends a second turn without disturbing the first', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'answer', text: 'two papers', citations: [] })

  transcript = asked(transcript, 'and the second?')

  expect(transcript).toHaveLength(2)
  expect(transcript[0].answer).toBe('two papers')
  expect(transcript[1].settled).toBe(false)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/domain/ask/conversation.test.ts`
Expected: FAIL, cannot resolve `./conversation.ts`

- [ ] **Step 3: Write minimal implementation**

```ts
/** The ask page's transcript, as a fold over the stream.
 *
 * Pure on purpose: streaming order is the part that goes subtly wrong, and it
 * is far cheaper to get right here than through a rendered component.
 */

export interface Citation {
  readonly kind: 'source' | 'topic'
  readonly id: string
}

export interface AskActivity {
  readonly messageId: string
  readonly kind: 'assistant' | 'tool'
  readonly payload: unknown
  readonly isError: boolean
}

export interface AskTurn {
  readonly question: string
  readonly answer: string
  readonly activity: readonly AskActivity[]
  readonly citations: readonly Citation[]
  readonly error: string | null
  /** Settled turns are closed to further events -- see `applyEvent`. */
  readonly settled: boolean
}

export type AskTranscript = readonly AskTurn[]

export type AskEvent =
  | { readonly type: 'delta'; readonly messageId: string; readonly text: string }
  | {
      readonly type: 'message'
      readonly messageId: string
      readonly kind: 'assistant' | 'tool'
      readonly payload: unknown
      readonly isError: boolean
    }
  | { readonly type: 'answer'; readonly text: string; readonly citations: readonly Citation[] }
  | { readonly type: 'error'; readonly detail: string }

export const asked = (transcript: AskTranscript, question: string): AskTranscript => [
  ...transcript,
  { question, answer: '', activity: [], citations: [], error: null, settled: false },
]

export const applyEvent = (transcript: AskTranscript, event: AskEvent): AskTranscript => {
  const open = transcript.length - 1
  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would corrupt an answer the reader has already read.
  if (open < 0 || transcript[open].settled) return transcript

  const turn = transcript[open]
  const replaced = (next: AskTurn): AskTranscript => [
    ...transcript.slice(0, open),
    next,
    ...transcript.slice(open + 1),
  ]

  switch (event.type) {
    case 'delta':
      return replaced({ ...turn, answer: turn.answer + event.text })
    case 'message':
      return replaced({
        ...turn,
        activity: [
          ...turn.activity,
          {
            messageId: event.messageId,
            kind: event.kind,
            payload: event.payload,
            isError: event.isError,
          },
        ],
      })
    case 'answer':
      // Replaced, not appended: the deltas already carried these same words,
      // and appending would render the answer twice.
      return replaced({
        ...turn,
        answer: event.text,
        citations: event.citations,
        settled: true,
      })
    case 'error':
      return replaced({ ...turn, error: event.detail, settled: true })
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/domain/ask/conversation.test.ts`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/ask/conversation.ts frontend/src/domain/ask/conversation.test.ts
git commit -m "The ask transcript as a pure fold

Streaming order is where this kind of code goes subtly wrong, and it is far
cheaper to get right in a pure function than through a rendered component --
so the interesting cases live here: a late frame after a turn settled, and
an answer arriving after deltas already rendered the same words.

The answer replaces the accumulated deltas rather than appending to them.
They are the same words, and appending renders the reply twice; that was
worth a test rather than a comment."
```

---

### Task 7: Reading an SSE response the browser cannot `EventSource`

**Files:**
- Create: `frontend/src/infrastructure/http/ask-repository.ts`
- Modify: `frontend/src/application/ports/repositories.ts` (append `AskRepository`)
- Modify: `frontend/src/app/container.ts` (type import, interface field, factory line)
- Test: `frontend/src/infrastructure/http/ask-repository.test.ts`

**Interfaces:**
- Consumes: `AskEvent`, `Citation` from Task 6; `ProjectId` from `@domain/shared/identifier.ts`; `ApiError` from `@application/ports/errors.ts`.
- Produces:

```ts
export interface AskRepository {
  ask(
    projectId: ProjectId,
    chatId: string,
    question: string,
    onEvent: (event: AskEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
  forget(projectId: ProjectId, chatId: string): Promise<void>
}
```
and `class HttpAskRepository implements AskRepository`, constructed as
`new HttpAskRepository(baseUrl)` and added to the container as `ask`.

`EventSource` cannot issue a POST, so this reads `response.body` and parses SSE
frames itself. It cannot use `HttpClient`, which reads the whole body as text.
Non-2xx still raises `ApiError` so 409 reaches the store as a conflict.

- [ ] **Step 1: Write the failing test**

```ts
/** Parsing an SSE body that arrives in whatever chunks the network chose.
 *
 * The split-frame cases are the reason this is tested rather than trusted: a
 * parser that assumes one chunk is one frame works locally and drops events
 * the moment a body is split across packets.
 */
import { expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { HttpAskRepository } from './ask-repository.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const body = (...chunks: string[]) => {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

const respond = (...chunks: string[]) =>
  vi.fn().mockResolvedValue(new Response(body(...chunks), { status: 200 }))

const collect = async (fetcher: typeof fetch) => {
  const seen: AskEvent[] = []
  await new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', (e) => seen.push(e))
  return seen
}

it('yields one event per frame', async () => {
  const seen = await collect(
    respond(
      'data: {"type":"delta","message_id":"m1","text":"two"}\n\n',
      'data: {"type":"answer","text":"two papers","citations":[]}\n\n',
    ),
  )

  expect(seen).toEqual([
    { type: 'delta', messageId: 'm1', text: 'two' },
    { type: 'answer', text: 'two papers', citations: [] },
  ])
})

it('reassembles a frame split across chunks', async () => {
  const seen = await collect(
    respond('data: {"type":"delta","mess', 'age_id":"m1","text":"two"}\n\n'),
  )

  expect(seen).toEqual([{ type: 'delta', messageId: 'm1', text: 'two' }])
})

it('reads two frames delivered in one chunk', async () => {
  const seen = await collect(
    respond(
      'data: {"type":"delta","message_id":"m1","text":"a"}\n\ndata: {"type":"delta","message_id":"m1","text":"b"}\n\n',
    ),
  )

  expect(seen).toHaveLength(2)
})

it('maps citations off the wire', async () => {
  const seen = await collect(
    respond('data: {"type":"answer","text":"x","citations":[{"kind":"source","id":"s1"}]}\n\n'),
  )

  expect(seen[0]).toEqual({ type: 'answer', text: 'x', citations: [{ kind: 'source', id: 's1' }] })
})

it('drops a frame whose shape this build does not understand', async () => {
  // A frame from a newer server should cost one event, not the whole stream.
  const seen = await collect(
    respond(
      'data: {"type":"something_new"}\n\n',
      'data: {"type":"answer","text":"x","citations":[]}\n\n',
    ),
  )

  expect(seen).toEqual([{ type: 'answer', text: 'x', citations: [] }])
})

it('raises an ApiError carrying the status when the server refuses', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{"detail":"busy"}', { status: 409 }))

  await expect(
    new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', () => {}),
  ).rejects.toMatchObject({ status: 409 })
  await expect(
    new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', () => {}),
  ).rejects.toBeInstanceOf(ApiError)
})

it('posts the chat id and question', async () => {
  const fetcher = respond('data: {"type":"answer","text":"x","citations":[]}\n\n')

  await collect(fetcher)

  const [url, init] = fetcher.mock.calls[0]
  expect(url).toBe(`/api/projects/${PROJECT}/ask`)
  expect(JSON.parse(init.body)).toEqual({ chat_id: 'c', question: 'why?' })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/infrastructure/http/ask-repository.test.ts`
Expected: FAIL, cannot resolve `./ask-repository.ts`

- [ ] **Step 3: Write minimal implementation**

```ts
/** The one genuinely new piece of infrastructure on the ask page.
 *
 * `EventSource` cannot issue a POST, and `HttpClient` reads a whole body as
 * text, so neither can carry a streamed answer to a posted question. This
 * reads `response.body` and parses SSE frames itself, validating each through
 * zod as every other wire boundary here does.
 */
import { z } from 'zod'

import { ApiError } from '@application/ports/errors.ts'
import type { AskRepository } from '@application/ports/repositories.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { seg } from './http-client.ts'

const citationDto = z.object({ kind: z.enum(['source', 'topic']), id: z.string() })

const askFrameDto = z.discriminatedUnion('type', [
  z.object({ type: z.literal('delta'), message_id: z.string(), text: z.string() }),
  z.object({
    type: z.literal('message'),
    message_id: z.string(),
    kind: z.enum(['assistant', 'tool']),
    payload: z.unknown(),
    is_error: z.boolean().default(false),
  }),
  z.object({
    type: z.literal('answer'),
    text: z.string(),
    citations: z.array(citationDto).default([]),
  }),
  z.object({ type: z.literal('error'), detail: z.string() }),
])

const toEvent = (raw: z.output<typeof askFrameDto>): AskEvent => {
  switch (raw.type) {
    case 'delta':
      return { type: 'delta', messageId: raw.message_id, text: raw.text }
    case 'message':
      return {
        type: 'message',
        messageId: raw.message_id,
        kind: raw.kind,
        payload: raw.payload,
        isError: raw.is_error,
      }
    case 'answer':
      return { type: 'answer', text: raw.text, citations: raw.citations }
    case 'error':
      return { type: 'error', detail: raw.detail }
  }
}

export class HttpAskRepository implements AskRepository {
  constructor(
    private readonly baseUrl: string = '',
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  async ask(
    projectId: ProjectId,
    chatId: string,
    question: string,
    onEvent: (event: AskEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/projects/${seg(projectId)}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ chat_id: chatId, question }),
      signal,
    })

    if (!response.ok || !response.body) {
      throw new ApiError(await detail(response), response.status)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    // Held across reads: the network decides where a body is split, and a
    // parser that assumed one chunk is one frame would drop events the first
    // time a frame straddled that boundary.
    let pending = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      const frames = pending.split('\n\n')
      pending = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseFrame(frame)
        if (event !== null) onEvent(event)
      }
    }
  }

  async forget(projectId: ProjectId, chatId: string): Promise<void> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/ask/${seg(chatId)}`,
      { method: 'DELETE' },
    )
    if (!response.ok) throw new ApiError(await detail(response), response.status)
  }
}

/** `null` for a frame this build does not understand -- one lost event rather
 *  than a dead stream, since a newer server may send types added later. */
const parseFrame = (frame: string): AskEvent | null => {
  const line = frame.split('\n').find((candidate) => candidate.startsWith('data: '))
  if (!line) return null
  try {
    const parsed = askFrameDto.safeParse(JSON.parse(line.slice('data: '.length)))
    return parsed.success ? toEvent(parsed.data) : null
  } catch {
    return null
  }
}

const detail = async (response: Response): Promise<string> => {
  try {
    const body: unknown = JSON.parse(await response.text())
    if (body && typeof body === 'object' && 'detail' in body) return String(body.detail)
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || `request failed with ${String(response.status)}`
}
```

Append the port to `frontend/src/application/ports/repositories.ts`:

```ts
export interface AskRepository {
  /** Streams one question's answer, calling `onEvent` per frame. Rejects with
   *  a 409 `ApiError` when the chat already has a question running -- the
   *  caller must surface that rather than retry, since retrying would join a
   *  queue that does not exist. */
  ask(
    projectId: ProjectId,
    chatId: string,
    question: string,
    onEvent: (event: AskEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
  /** Forgets the server's copy of a conversation, backing "new chat". */
  forget(projectId: ProjectId, chatId: string): Promise<void>
}
```

Wire the container in `frontend/src/app/container.ts`: import the type and the
adapter, add `readonly ask: AskRepository` to `Container`, and add
`ask: new HttpAskRepository(baseUrl),` to the factory's returned object.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/infrastructure/http/ask-repository.test.ts`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/infrastructure/http/ask-repository.ts frontend/src/infrastructure/http/ask-repository.test.ts frontend/src/application/ports/repositories.ts frontend/src/app/container.ts
git commit -m "An SSE reader for a response the browser cannot EventSource

EventSource cannot POST and HttpClient reads a whole body as text, so
neither carries a streamed answer to a posted question. This reads the body
and parses frames itself, holding a buffer across reads: the network decides
where a body splits, and a parser assuming one chunk is one frame works
locally and drops events in production.

An unrecognised frame costs one event rather than the stream, so a newer
server adding a frame type degrades instead of breaking."
```

---

### Task 8: The store

**Files:**
- Create: `frontend/src/application/ask/ask-store.ts`
- Test: `frontend/src/application/ask/ask-store.test.ts`

**Interfaces:**
- Consumes: `AskRepository` (Task 7); `applyEvent`, `asked`, `AskTranscript` (Task 6); `errorMessage` from `@application/ports/errors.ts`.
- Produces:

```ts
export interface AskState {
  readonly transcript: AskTranscript
  readonly asking: boolean
  readonly error: string | null
  readonly chatId: string
  send(question: string): Promise<void>
  reset(): Promise<void>
}
export type AskStore = ReturnType<typeof createAskStore>
export const createAskStore: (deps: {
  ask: AskRepository
  projectId: ProjectId
  newChatId: () => string
}) => AskStore
```

- [ ] **Step 1: Write the failing test**

```ts
/** What the ask store guarantees on top of the fold and the repository. */
import { expect, it, vi } from 'vitest'

import type { AskRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { createAskStore } from './ask-store.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const fakeAsk = (over: Partial<AskRepository> = {}): AskRepository => ({
  ask: vi.fn(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'answer', text: 'two papers', citations: [] })
  }),
  forget: vi.fn().mockResolvedValue(undefined),
  ...over,
})

let counter = 0
const store = (ask: AskRepository = fakeAsk()) =>
  createAskStore({ ask, projectId: PROJECT, newChatId: () => `chat-${String(++counter)}` })

it('records the question before the first frame arrives', async () => {
  const ask = fakeAsk({
    ask: vi.fn(async () => {
      await Promise.resolve()
    }),
  })
  const asking = store(ask)

  const sending = asking.getState().send('what did we find?')

  expect(asking.getState().transcript[0].question).toBe('what did we find?')
  await sending
})

it('folds streamed events into the transcript', async () => {
  const asking = store()

  await asking.getState().send('what did we find?')

  expect(asking.getState().transcript[0].answer).toBe('two papers')
  expect(asking.getState().transcript[0].settled).toBe(true)
})

it('clears the asking flag once the answer settles', async () => {
  const asking = store()

  await asking.getState().send('why?')

  expect(asking.getState().asking).toBe(false)
})

it('surfaces a refusal rather than retrying it', async () => {
  const conflict = Object.assign(new Error('busy'), { status: 409 })
  const asking = store(fakeAsk({ ask: vi.fn().mockRejectedValue(conflict) }))

  await asking.getState().send('why?')

  expect(asking.getState().error).toBe('busy')
  expect(asking.getState().asking).toBe(false)
})

it('marks the open turn failed when the stream breaks', async () => {
  const asking = store(fakeAsk({ ask: vi.fn().mockRejectedValue(new Error('network gone')) }))

  await asking.getState().send('why?')

  // Without this the turn spins forever with no answer and no reason.
  expect(asking.getState().transcript[0].settled).toBe(true)
  expect(asking.getState().transcript[0].error).toBe('network gone')
})

it('refuses a second question while one is running', async () => {
  const ask = vi.fn(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5))
  })
  const asking = store(fakeAsk({ ask }))

  const first = asking.getState().send('one')
  await asking.getState().send('two')
  await first

  expect(ask).toHaveBeenCalledTimes(1)
  expect(asking.getState().transcript).toHaveLength(1)
})

it('sends the same chat id for every question in a conversation', async () => {
  const ask = vi.fn(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'answer', text: 'x', citations: [] })
  })
  const asking = store(fakeAsk({ ask }))

  await asking.getState().send('one')
  await asking.getState().send('two')

  expect(ask.mock.calls[0][1]).toBe(ask.mock.calls[1][1])
})

it('reset forgets the server copy and starts a new chat id', async () => {
  const forget = vi.fn().mockResolvedValue(undefined)
  const asking = store(fakeAsk({ forget }))
  await asking.getState().send('one')
  const before = asking.getState().chatId

  await asking.getState().reset()

  expect(forget).toHaveBeenCalledWith(PROJECT, before)
  expect(asking.getState().transcript).toEqual([])
  expect(asking.getState().chatId).not.toBe(before)
})

it('clears the transcript even when forgetting the server copy fails', async () => {
  const asking = store(fakeAsk({ forget: vi.fn().mockRejectedValue(new Error('offline')) }))
  await asking.getState().send('one')

  await asking.getState().reset()

  // The server's copy expires on its own; refusing to clear the page would
  // strand the reader in a conversation they asked to leave.
  expect(asking.getState().transcript).toEqual([])
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/application/ask/ask-store.test.ts`
Expected: FAIL, cannot resolve `./ask-store.ts`

- [ ] **Step 3: Write minimal implementation**

```ts
import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import type { AskRepository } from '@application/ports/repositories.ts'
import { applyEvent, asked, type AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

export interface AskState {
  readonly transcript: AskTranscript
  readonly asking: boolean
  readonly error: string | null
  readonly chatId: string
  send(question: string): Promise<void>
  reset(): Promise<void>
}

export type AskStore = ReturnType<typeof createAskStore>

export const createAskStore = ({
  ask,
  projectId,
  newChatId,
}: {
  ask: AskRepository
  projectId: ProjectId
  newChatId: () => string
}) =>
  create<AskState>((set, get) => ({
    transcript: [],
    asking: false,
    error: null,
    chatId: newChatId(),

    async send(question) {
      const trimmed = question.trim()
      // The server refuses a second question on a busy chat with a 409; not
      // sending it is the same answer without the round trip.
      if (!trimmed || get().asking) return

      set((state) => ({ transcript: asked(state.transcript, trimmed), asking: true, error: null }))
      try {
        await ask.ask(projectId, get().chatId, trimmed, (event) => {
          set((state) => ({ transcript: applyEvent(state.transcript, event) }))
        })
      } catch (err) {
        const detail = errorMessage(err)
        // Settle the turn as well as setting the banner: an open turn with no
        // answer and no reason spins forever.
        set((state) => ({
          transcript: applyEvent(state.transcript, { type: 'error', detail }),
          error: detail,
        }))
      } finally {
        set({ asking: false })
      }
    },

    async reset() {
      const previous = get().chatId
      set({ transcript: [], error: null, chatId: newChatId() })
      try {
        await ask.forget(projectId, previous)
      } catch {
        // The server's copy expires on its own, and refusing to clear the page
        // would strand the reader in a conversation they asked to leave.
      }
    },
  }))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/application/ask/ask-store.test.ts`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/application/ask/ask-store.ts frontend/src/application/ask/ask-store.test.ts
git commit -m "The ask store

A broken stream settles the open turn as well as raising the banner: a turn
left open with no answer and no reason spins forever, which reads as a hung
model rather than a failed request.

reset clears the page even when telling the server to forget fails. The
server's copy expires on its own, and refusing to clear would strand the
reader in a conversation they asked to leave."
```

---

### Task 9: The page

**Files:**
- Create: `frontend/src/presentation/ask/AskView.tsx`, `AskThread.tsx`, `AskComposer.tsx`, `CitationList.tsx`
- Create: `frontend/src/presentation/ask/AskView.test.tsx`
- Modify: `frontend/src/presentation/routing/routes.ts` (add `'ask'` to `FACETS`)
- Modify: `frontend/src/app/App.tsx` (branch the facet before the `CourseView` fallthrough)
- Modify: `frontend/src/presentation/course/CourseView.tsx` (nav link)
- Modify: `frontend/src/presentation/research/ResearchView.tsx` (nav link)
- Modify: `frontend/src/styles/` — add the ask page's rules to the stylesheet the other views use; follow whatever file organisation is already there.

**Interfaces:**
- Consumes: `createAskStore` / `AskStore` (Task 8); `useContainer` from `@app/container-context.tsx`; `projectHref` from `@presentation/routing/routes.ts`.
- Produces: `AskView({ projectId }: { projectId: ProjectId })`.

`'ask'` is a `PlainFacet`, so adding it to `FACETS` makes `#/p/<id>/ask` parse
and `projectHref(projectId, { facet: 'ask', id: null })` build with no change to
the href builders.

The store is created per project, as `GraphPane` does:
`const store = useMemo(() => createAskStore({ ask, projectId, newChatId: () => crypto.randomUUID() }), [ask, projectId])`.
Read data through `store()` during render and reach actions via
`store.getState()` in handlers — `store()` is a hook.

Tool activity renders collapsed behind a disclosure, as `Segments.tsx` collapses
consecutive tool machinery. Citations render as links: a `source` citation to
`projectHref(projectId, { facet: 'doc', id })`, a `topic` citation to
`projectHref(projectId, { facet: 'topic', id })`.

- [ ] **Step 1: Write the failing test**

```tsx
/** The ask page, from a reader's point of view. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AskRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { AskView } from './AskView.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const renderAsk = (ask: Partial<AskRepository>) => {
  const container = { ask: { forget: vi.fn(), ...ask } } as unknown as AppContainer
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  return render(<AskView projectId={PROJECT} />, { wrapper })
}

const answering = (text: string, citations: { kind: 'source' | 'topic'; id: string }[] = []) =>
  vi.fn(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'answer', text, citations })
  })

it('shows the question and its answer', async () => {
  renderAsk({ ask: answering('two papers') })

  await userEvent.type(screen.getByRole('textbox'), 'what did we find?')
  await userEvent.click(screen.getByRole('button', { name: /ask/i }))

  expect(await screen.findByText('what did we find?')).toBeInTheDocument()
  expect(await screen.findByText('two papers')).toBeInTheDocument()
})

it('links a source citation to the project document it came from', async () => {
  renderAsk({ ask: answering('two papers', [{ kind: 'source', id: 's1' }]) })

  await userEvent.type(screen.getByRole('textbox'), 'why?')
  await userEvent.click(screen.getByRole('button', { name: /ask/i }))

  const link = await screen.findByRole('link', { name: /s1/ })
  expect(link).toHaveAttribute('href', `#/p/${PROJECT}/doc/s1`)
})

it('says the page keeps nothing', () => {
  // The contract is ephemerality; a reader who does not know that will expect
  // to find this conversation again tomorrow.
  renderAsk({ ask: answering('x') })

  expect(screen.getByText(/not saved|ephemeral|kept/i)).toBeInTheDocument()
})

it('surfaces a refusal to the reader', async () => {
  renderAsk({ ask: vi.fn().mockRejectedValue(new Error('busy')) })

  await userEvent.type(screen.getByRole('textbox'), 'why?')
  await userEvent.click(screen.getByRole('button', { name: /ask/i }))

  expect(await screen.findByText(/busy/)).toBeInTheDocument()
})

it('clears the thread on a new chat', async () => {
  renderAsk({ ask: answering('two papers') })
  await userEvent.type(screen.getByRole('textbox'), 'why?')
  await userEvent.click(screen.getByRole('button', { name: /ask/i }))
  expect(await screen.findByText('two papers')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /new chat/i }))

  expect(screen.queryByText('two papers')).not.toBeInTheDocument()
})

it('keeps tool activity out of the way until asked for', async () => {
  const ask = vi.fn(async (_p, _c, _q, onEvent) => {
    onEvent({
      type: 'message', messageId: 'm1', kind: 'tool',
      payload: { name: 'read_source' }, isError: false,
    })
    onEvent({ type: 'answer', text: 'two papers', citations: [] })
  })
  renderAsk({ ask })

  await userEvent.type(screen.getByRole('textbox'), 'why?')
  await userEvent.click(screen.getByRole('button', { name: /ask/i }))

  // Collapsed, not absent: the reader wants the answer, and the trace second.
  const disclosure = await screen.findByRole('button', { name: /looked at|activity/i })
  expect(disclosure).toBeInTheDocument()
  expect(screen.queryByText(/read_source/)).not.toBeInTheDocument()
})
```

Add one route test to the existing routing test file (find it next to
`routes.ts`), matching its style:

```ts
it('parses the ask facet', () => {
  expect(parseRoute('#/p/abc/ask')).toEqual({
    name: 'project',
    id: ProjectId('abc'),
    selection: { facet: 'ask', id: null },
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/presentation/ask/AskView.test.tsx`
Expected: FAIL, cannot resolve `./AskView.tsx`

- [ ] **Step 3: Build the page**

Write the four components. Requirements the tests above pin, restated so they
are not inferred from assertions alone:

- `AskView` renders a `view` section with a `view-head` (`<h1>Ask</h1>`, a
  subtitle stating plainly that this conversation is not saved), a
  `.view-head-actions` row containing a "New chat" button plus links to Course
  and Research built with `projectHref`, then `AskThread`, then `AskComposer`.
- `AskThread` renders each turn: the question, the collapsed activity
  disclosure (label "Looked at", rendered only when the turn has activity), the
  answer text, and `CitationList`. An unsettled turn shows a busy indicator.
- `AskComposer` is a textarea plus an "Ask" button, submitting on Ctrl+Enter as
  `Composer.tsx` does, disabled while `asking`.
- `CitationList` renders nothing for an empty list; otherwise a labelled list of
  links, each named by its id, `doc` for a source and `topic` for a topic.
- The store's `error` renders in a banner.

Then add `'ask'` to `FACETS` in `routes.ts` (keep it in the existing list order
convention), and in `App.tsx` branch before the `CourseView` fallthrough:

```tsx
  if (selection?.facet === 'ask') return <AskView key={id} projectId={id} />
```

Add the nav link to both `CourseView.tsx` and `ResearchView.tsx` inside their
`.view-head-actions` divs:

```tsx
<a className="btn btn-quiet" href={projectHref(projectId, { facet: 'ask', id: null })}>
  Ask
</a>
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/presentation/ask src/presentation/routing`
Expected: all pass

- [ ] **Step 5: Run the browser suite if styling was touched**

If Step 3 added or changed any stylesheet rule, or the layout's correctness
depends on a computed style, run:

```bash
cd frontend && npm run test:browser
```

jsdom applies no stylesheet, so a collapsed-by-default disclosure that is
collapsed *by CSS* is invisible to the jsdom test above — it would pass against
a broken page. If the disclosure hides its content by CSS rather than by not
rendering it, a browser test asserting the computed style is required, not
optional. Say which of the two the implementation chose in the commit message.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/ask frontend/src/presentation/routing frontend/src/app/App.tsx frontend/src/presentation/course/CourseView.tsx frontend/src/presentation/research/ResearchView.tsx frontend/src/styles
git commit -m "The ask page

A third facet beside Course and Research, reached by the same
.view-head-actions links those two already use rather than a fourth kind of
navigation.

Conversation.tsx and Composer.tsx are not reused. Both are bound to
session-store's TurnState, to scrubbing and to fork affordances, and bending
them here would carry session concepts onto a page whose whole point is not
being a session. The cost is two transcripts that look alike and are not
shared; that is the trade accepted.

The subtitle says the conversation is not saved, because a reader who does
not know that will come back tomorrow looking for it."
```

---

### Task 10: The gates, the docs, and the PR

**Files:**
- Modify: `README.md` (a short paragraph on the ask page, in the voice of the surrounding text)
- Modify: `frontend/README.md` if it enumerates the views
- Modify: `BACKLOG.md` (record what the spec deliberately left unbuilt)

- [ ] **Step 1: Run all four gates, in order, one at a time**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Every one must pass. `npm run verify` covers no Python and `pytest` covers no
formatting, so three of four is not passing. If `verify` fails the bundle-size
budget, raise the budget rather than shaving the feature, and say so in the
commit.

- [ ] **Step 2: Write the docs**

In `README.md`, after the web console paragraph, describe the page in two or
three sentences: what it answers from, that it writes nothing and keeps
nothing, and that it has no network access. Match the surrounding voice — plain
claims, no adjectives doing work a fact could do.

In `BACKLOG.md`, add an entry recording the deferred pieces from the spec's
"Deliberately not built": persistence and resumption, forking, steering project
work from the chat, subagent fan-out. Give each enough detail to pick up, and
note that each would be a reason to revisit whether this should have been a
session.

- [ ] **Step 3: Commit the docs**

```bash
git add README.md frontend/README.md BACKLOG.md
git commit -m "Write down the ask page and what it deliberately is not

The backlog entries matter more than the README paragraph: each deferred
piece is a decision with a reason, and a reader finding only its absence
would read it as an oversight."
```

- [ ] **Step 4: Open the PR**

```bash
git push -u origin HEAD
gh pr create --title "A page for asking a project about what it gathered" --body "$(cat <<'EOF'
## Summary

A third project page, beside Course and Research, for asking questions about the material a project has gathered. Ephemeral, read-only, outside the knowledge graph and outside the session machinery.

## The decision worth reviewing

This is not a session. Every agent interaction today runs through `SessionService`, and joining a project forks the previous holder's filesystem, advances the tip, and takes exclusive hold of the project. An asking surface needs none of that and would be blocked by the last of it — so this is a parallel path that shares the composition root's project tooling and nothing else.

Two alternatives were considered and rejected, with reasons recorded in the spec: a `Session` over an in-memory event store, and multiplexing answers onto the shared `/api/stream`.

## What holds the design up

- The tool set is an **allowlist** of five readers, so a tool added to `open_graph` later is excluded until someone admits it here on purpose. A test on the exact names fails when that happens.
- **Citations come from tool calls, not prose** — the agent cannot cite a document it never opened. Searching is not reading, so `graph_search` earns no citation.
- An integration test asserts the event log's position is **unchanged** across a full ask. That is what makes "ephemeral" a property of the system rather than a promise in a document.
- Writes to the filesystem **raise** rather than no-op, so a prompt that tries one fails visibly in a test.

## Deliberately not built

Persistence, forking, steering project work from the chat, subagent fan-out. Each is recorded in `BACKLOG.md`, and each would be a reason to revisit whether this should have been a session after all.

## Verification

All four gates: `ruff check`, `ruff format --check`, `pytest`, `npm run verify`.

Spec: `docs/superpowers/specs/2026-08-12-project-ask-page-design.md`
Plan: `docs/superpowers/plans/2026-08-12-project-ask-page.md`
EOF
)"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: "Why this is not a
session" → the parallel path in Tasks 2–5; ephemeral server-held conversations →
Task 2; the read-only tool set and its pinning test → Task 4; the read-only
filesystem → Task 1; streaming and the routes → Task 5; derived citations →
Task 4 (produced) and Task 9 (rendered); the frontend layering → Tasks 6–9;
verification and "deliberately not built" → Task 10.

**Two adjustments to the spec, both forced by the code.** `open_graph` is a
closure inside `build_application` rather than a module function, so it is
injected into the executor and wired in Task 5. And `tests/test_architecture.py`
forbids the application layer from importing `langchain` or `deepagents`, so
`AskService` holds framework-free types behind the `AskExecutor` port and the
agent lives in `infrastructure/`. The spec's prose describes the first shape;
this plan is the corrected one, and the difference is worth mentioning in
review.

**Type consistency.** `AskMessage`, `AskAnswer`, `Citation`, `AskExecutor`,
`AskService`, `ConversationRegistry` keep one spelling from Task 2 through Task
5. On the wire the frames are snake_case (`message_id`, `is_error`) and the
browser's domain types are camelCase (`messageId`, `isError`); the mapping is in
Task 7's `toEvent` and nowhere else, which is the same split the existing DTOs
and mappers use.
