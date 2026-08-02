# Event-Sourced Coding Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a coding agent whose conversation, tool results, and virtual filesystem are all folds over a single in-memory event stream, driven from a REPL.

**Architecture:** One `CodingSession` aggregate owns one event stream. `EventSourcedBackend` subclasses deepagents' `StateBackend`, overriding only its two private state seams so every file-tool semantic is inherited rather than reimplemented. Messages are stored as langchain's own `message_to_dict` payloads. `create_deep_agent(checkpointer=None)` keeps LangGraph stateless, so the event log is the sole source of truth.

**Tech Stack:** Python 3.13, `eventsource-py` 0.9, `deepagents` 0.7.1, `langchain-openai`, `pytest` + `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-08-01-event-sourced-coding-agent-design.md`

## Global Constraints

- **Lean on the libraries.** Before writing a helper, check whether `deepagents.backends.utils`, `langchain_core.messages`, or `eventsource` already provides it. Reimplementation is a review-blocking defect. See the spec's "Library Leverage" table.
- **Dependency pin:** `deepagents>=0.7.1,<0.8` — we subclass over private seams.
- Everything in memory. No disk I/O, no shell, no network except the model call.
- All events subclass `eventsource.DomainEvent`, are `@register_event`-decorated, and set `aggregate_type: str = "CodingSession"`.
- Events are frozen and `extra="forbid"`. Every event is self-contained.
- No test may call the live model. Live tests are marked `@pytest.mark.live` and skipped by default.
- Run tests with `uv run pytest`. Package dir is `research_team/`, tests in `tests/`.
- Python 3.13 built-in generics (`dict[str, Any]`, `X | None`). No `typing.Dict`/`Optional`.
- Commit after every task with the message given in the task's final step.

## File Structure

| File | Responsibility |
|---|---|
| `research_team/events.py` | Event class definitions and registration. No logic. |
| `research_team/session.py` | `SessionState` + `CodingSession` aggregate: commands (validate + emit) and `@handles` reducers (fold only). |
| `research_team/messages.py` | Pure conversion between `SessionState.messages` and langchain `BaseMessage`. No I/O, no aggregate import. |
| `research_team/backend.py` | `EventSourcedBackend(StateBackend)` — two seam overrides plus `edit()` intent capture. |
| `research_team/runtime.py` | Wiring (store, snapshots, repo, model) and the turn/replay operations. |
| `research_team/repl.py` | Terminal loop and meta-commands. Formatting only — no domain logic. |
| `tests/conftest.py` | Shared fixtures: store, repo, session id, started aggregate, `ToolAwareFakeChatModel`. |

Tasks 3 and 4 are independent of each other; both depend on Task 2.

---

### Task 1: Events

**Files:**
- Create: `research_team/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SessionStarted(system_prompt: str, model_name: str)`, `UserMessageSent(message: dict[str, Any])`, `AssistantMessageAdded(message: dict[str, Any])`, `ToolResultRecorded(message: dict[str, Any], is_error: bool = False)`, `TurnCompleted(turn_index: int)`, `FileWritten(path: str, file_data: dict[str, Any])`, `FileEdited(path: str, file_data: dict[str, Any], old_string: str, new_string: str, replace_all: bool)`, `FileDeleted(path: str)`. Also `SESSION_EVENTS: tuple[type[DomainEvent], ...]` listing all eight.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
import pytest
from pydantic import ValidationError

from research_team.events import (
    SESSION_EVENTS,
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)
from eventsource.domain.event_registry import get_event_class


def test_all_events_exported():
    assert set(SESSION_EVENTS) == {
        SessionStarted, UserMessageSent, AssistantMessageAdded,
        ToolResultRecorded, TurnCompleted, FileWritten, FileEdited, FileDeleted,
    }


@pytest.mark.parametrize("event_class", [
    SessionStarted, UserMessageSent, AssistantMessageAdded, ToolResultRecorded,
    TurnCompleted, FileWritten, FileEdited, FileDeleted,
])
def test_event_is_registered_under_its_name(event_class):
    assert get_event_class(event_class.__name__) is event_class


@pytest.mark.parametrize("event_class", list(SESSION_EVENTS))
def test_aggregate_type_is_coding_session(event_class):
    assert event_class.model_fields["aggregate_type"].default == "CodingSession"


def test_events_are_frozen():
    event = TurnCompleted(turn_index=1)
    with pytest.raises(ValidationError):
        event.turn_index = 2


def test_events_forbid_extra_fields():
    with pytest.raises(ValidationError):
        TurnCompleted(turn_index=1, bogus="nope")


def test_file_written_round_trips():
    file_data = {"content": "print(1)\n", "encoding": "utf-8"}
    event = FileWritten(path="/a.py", file_data=file_data)
    restored = FileWritten.model_validate_json(event.model_dump_json())
    assert restored.path == "/a.py"
    assert restored.file_data == file_data


def test_file_edited_carries_intent_and_result():
    event = FileEdited(
        path="/a.py",
        file_data={"content": "print(2)\n"},
        old_string="1",
        new_string="2",
        replace_all=False,
    )
    assert (event.old_string, event.new_string, event.replace_all) == ("1", "2", False)
    assert event.file_data["content"] == "print(2)\n"


def test_tool_result_defaults_to_success():
    assert ToolResultRecorded(message={"type": "tool"}).is_error is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.events'`

- [ ] **Step 3: Write minimal implementation**

```python
# research_team/events.py
"""Domain events for a coding session.

One stream carries both the conversation and the virtual filesystem, so
ordering between "the model said X" and "file Y changed" is total.
"""

from typing import Any

from eventsource import DomainEvent, register_event


@register_event
class SessionStarted(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "CodingSession"
    system_prompt: str
    model_name: str


@register_event
class UserMessageSent(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class AssistantMessageAdded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class ToolResultRecorded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]
    is_error: bool = False


@register_event
class TurnCompleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    turn_index: int


@register_event
class FileWritten(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]


@register_event
class FileEdited(DomainEvent):
    """Carries both the resulting file_data and the edit intent.

    file_data keeps the fold O(1); old_string/new_string keep the audit
    trail meaningful.
    """

    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]
    old_string: str
    new_string: str
    replace_all: bool = False


@register_event
class FileDeleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str


SESSION_EVENTS: tuple[type[DomainEvent], ...] = (
    SessionStarted,
    UserMessageSent,
    AssistantMessageAdded,
    ToolResultRecorded,
    TurnCompleted,
    FileWritten,
    FileEdited,
    FileDeleted,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_events.py -v`
Expected: PASS, 16 passed.

- [ ] **Step 5: Commit**

```bash
git add research_team/events.py tests/test_events.py
git commit -m "feat: add coding session domain events"
```

---

### Task 2: Session aggregate

**Files:**
- Create: `research_team/session.py`
- Create: `tests/conftest.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: all events from Task 1.
- Produces:
  - `SessionState(session_id: UUID, system_prompt: str, model_name: str, files: dict[str, dict[str, Any]], messages: list[dict[str, Any]], turn_index: int)`
  - `CodingSession` with `aggregate_type = "CodingSession"`, `requires_creation_event = True`, `schema_version = 1`, and commands:
    - `start(system_prompt: str, model_name: str) -> None`
    - `send_user_message(message: dict[str, Any]) -> None`
    - `record_assistant_message(message: dict[str, Any]) -> None`
    - `record_tool_result(message: dict[str, Any], *, is_error: bool = False) -> None`
    - `complete_turn() -> None`
    - `write_file(path: str, file_data: dict[str, Any]) -> None`
    - `edit_file(path: str, file_data: dict[str, Any], old_string: str, new_string: str, replace_all: bool) -> None`
    - `delete_file(path: str) -> None`
  - `conftest.py` fixtures: `store`, `repo`, `session_id`, `session` (a started `CodingSession`).

- [ ] **Step 1: Write the conftest fixtures**

```python
# tests/conftest.py
from uuid import uuid4

import pytest
from eventsource.adapters.memory import InMemoryEventStore
from eventsource.adapters.memory.snapshots import InMemorySnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository

from research_team.session import CodingSession

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


@pytest.fixture
def store() -> InMemoryEventStore:
    return InMemoryEventStore()


@pytest.fixture
def snapshots() -> InMemorySnapshotStore:
    return InMemorySnapshotStore()


@pytest.fixture
def repo(store, snapshots) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        snapshot_store=snapshots,
        snapshot_threshold=50,
        snapshot_mode="sync",
    )


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def session(repo, session_id) -> CodingSession:
    aggregate = repo.create_new(session_id)
    aggregate.start(SYSTEM_PROMPT, MODEL_NAME)
    return aggregate
```

Also create `pytest.ini` settings in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["live: hits the real model endpoint; deselected by default"]
addopts = "-m 'not live'"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_session.py
import pytest

from research_team.events import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)
from research_team.session import CodingSession

from .conftest import MODEL_NAME, SYSTEM_PROMPT

FILE_DATA = {"content": "print(1)\n", "encoding": "utf-8"}
EDITED = {"content": "print(2)\n", "encoding": "utf-8"}


def types_of(aggregate: CodingSession) -> list[type]:
    return [type(e) for e in aggregate.uncommitted_events]


def test_start_emits_session_started(session):
    assert types_of(session) == [SessionStarted]
    assert session.state.system_prompt == SYSTEM_PROMPT
    assert session.state.model_name == MODEL_NAME


def test_start_twice_is_rejected(session):
    with pytest.raises(ValueError, match="already started"):
        session.start(SYSTEM_PROMPT, MODEL_NAME)


def test_commands_require_started_session(repo, session_id):
    fresh = repo.create_new(session_id)
    with pytest.raises(ValueError, match="not started"):
        fresh.write_file("/a.py", FILE_DATA)


def test_user_message_appended(session):
    session.send_user_message({"type": "human", "data": {"content": "hi"}})
    assert types_of(session)[-1] is UserMessageSent
    assert session.state.messages[-1]["data"]["content"] == "hi"


def test_assistant_message_appended(session):
    session.record_assistant_message({"type": "ai", "data": {"content": "yo", "tool_calls": []}})
    assert types_of(session)[-1] is AssistantMessageAdded
    assert session.state.messages[-1]["type"] == "ai"


def test_write_file_creates_entry(session):
    session.write_file("/a.py", FILE_DATA)
    assert types_of(session)[-1] is FileWritten
    assert session.state.files["/a.py"] == FILE_DATA


def test_edit_file_replaces_entry(session):
    session.write_file("/a.py", FILE_DATA)
    session.edit_file("/a.py", EDITED, "1", "2", False)
    assert types_of(session)[-1] is FileEdited
    assert session.state.files["/a.py"] == EDITED


def test_edit_missing_file_is_rejected(session):
    with pytest.raises(ValueError, match="does not exist"):
        session.edit_file("/nope.py", EDITED, "1", "2", False)


def test_delete_file_removes_entry(session):
    session.write_file("/a.py", FILE_DATA)
    session.delete_file("/a.py")
    assert types_of(session)[-1] is FileDeleted
    assert "/a.py" not in session.state.files


def test_delete_missing_file_is_rejected(session):
    with pytest.raises(ValueError, match="does not exist"):
        session.delete_file("/nope.py")


def test_tool_result_requires_outstanding_call(session):
    with pytest.raises(ValueError, match="no outstanding tool call"):
        session.record_tool_result({"type": "tool", "data": {"tool_call_id": "t1", "content": "ok"}})


def test_tool_result_accepted_when_call_outstanding(session):
    session.record_assistant_message({
        "type": "ai",
        "data": {"content": "", "tool_calls": [{"id": "t1", "name": "write_file", "args": {}}]},
    })
    session.record_tool_result({"type": "tool", "data": {"tool_call_id": "t1", "content": "ok"}})
    assert types_of(session)[-1] is ToolResultRecorded


def test_tool_results_may_resolve_out_of_order(session):
    session.record_assistant_message({
        "type": "ai",
        "data": {"content": "", "tool_calls": [
            {"id": "t1", "name": "write_file", "args": {}},
            {"id": "t2", "name": "read_file", "args": {}},
        ]},
    })
    session.record_tool_result({"type": "tool", "data": {"tool_call_id": "t2", "content": "b"}})
    session.record_tool_result({"type": "tool", "data": {"tool_call_id": "t1", "content": "a"}})
    assert types_of(session)[-2:] == [ToolResultRecorded, ToolResultRecorded]


def test_complete_turn_increments_index(session):
    session.complete_turn()
    session.complete_turn()
    assert types_of(session)[-1] is TurnCompleted
    assert session.state.turn_index == 2


async def test_state_survives_save_and_reload(repo, session, session_id):
    session.write_file("/a.py", FILE_DATA)
    session.send_user_message({"type": "human", "data": {"content": "hi"}})
    await repo.save(session)

    reloaded = await repo.load(session_id)
    assert reloaded.state.files == {"/a.py": FILE_DATA}
    assert reloaded.state.messages[-1]["data"]["content"] == "hi"
    assert reloaded.version == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.session'`

- [ ] **Step 4: Write minimal implementation**

Reducers must never validate — validation belongs in commands, because a reducer also runs during replay of already-accepted events.

```python
# research_team/session.py
"""The CodingSession aggregate: the single source of truth for a session."""

from typing import Any
from uuid import UUID

from eventsource import DeclarativeAggregate, handles
from pydantic import BaseModel, Field

from research_team.events import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)


class SessionState(BaseModel):
    """Everything derivable from the event stream."""

    session_id: UUID
    system_prompt: str = ""
    model_name: str = ""
    files: dict[str, dict[str, Any]] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    turn_index: int = 0


def _outstanding_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Tool call ids requested by the last AI message but not yet answered."""
    requested: set[str] = set()
    for message in reversed(messages):
        if message.get("type") == "ai":
            requested = {
                call["id"] for call in message.get("data", {}).get("tool_calls", [])
            }
            break
    answered = {
        message.get("data", {}).get("tool_call_id")
        for message in messages
        if message.get("type") == "tool"
    }
    return requested - answered


class CodingSession(DeclarativeAggregate[SessionState]):
    aggregate_type = "CodingSession"
    requires_creation_event = True
    schema_version = 1

    # ---------------- commands ----------------

    def start(self, system_prompt: str, model_name: str) -> None:
        if self.version > 0:
            raise ValueError("session already started")
        self.create_event(
            SessionStarted, system_prompt=system_prompt, model_name=model_name
        )

    def send_user_message(self, message: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(UserMessageSent, message=message)

    def record_assistant_message(self, message: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(AssistantMessageAdded, message=message)

    def record_tool_result(
        self, message: dict[str, Any], *, is_error: bool = False
    ) -> None:
        self._require_started()
        call_id = message.get("data", {}).get("tool_call_id")
        if call_id not in _outstanding_tool_call_ids(self.state.messages):
            raise ValueError(f"no outstanding tool call with id {call_id!r}")
        self.create_event(ToolResultRecorded, message=message, is_error=is_error)

    def complete_turn(self) -> None:
        self._require_started()
        self.create_event(TurnCompleted, turn_index=self.state.turn_index + 1)

    def write_file(self, path: str, file_data: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(FileWritten, path=path, file_data=file_data)

    def edit_file(
        self,
        path: str,
        file_data: dict[str, Any],
        old_string: str,
        new_string: str,
        replace_all: bool,
    ) -> None:
        self._require_started()
        self._require_file(path)
        self.create_event(
            FileEdited,
            path=path,
            file_data=file_data,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )

    def delete_file(self, path: str) -> None:
        self._require_started()
        self._require_file(path)
        self.create_event(FileDeleted, path=path)

    # ---------------- guards ----------------

    def _require_started(self) -> None:
        if self.version == 0:
            raise ValueError("session not started")

    def _require_file(self, path: str) -> None:
        if path not in self.state.files:
            raise ValueError(f"file {path!r} does not exist")

    # ---------------- reducers ----------------

    @handles(SessionStarted)
    def _on_started(self, event: SessionStarted) -> None:
        self._state = SessionState(
            session_id=self.aggregate_id,
            system_prompt=event.system_prompt,
            model_name=event.model_name,
        )

    @handles(UserMessageSent)
    def _on_user_message(self, event: UserMessageSent) -> None:
        self._append_message(event.message)

    @handles(AssistantMessageAdded)
    def _on_assistant_message(self, event: AssistantMessageAdded) -> None:
        self._append_message(event.message)

    @handles(ToolResultRecorded)
    def _on_tool_result(self, event: ToolResultRecorded) -> None:
        self._append_message(event.message)

    @handles(TurnCompleted)
    def _on_turn_completed(self, event: TurnCompleted) -> None:
        self._state = self._state.model_copy(update={"turn_index": event.turn_index})

    @handles(FileWritten)
    def _on_file_written(self, event: FileWritten) -> None:
        self._put_file(event.path, event.file_data)

    @handles(FileEdited)
    def _on_file_edited(self, event: FileEdited) -> None:
        self._put_file(event.path, event.file_data)

    @handles(FileDeleted)
    def _on_file_deleted(self, event: FileDeleted) -> None:
        files = {k: v for k, v in self._state.files.items() if k != event.path}
        self._state = self._state.model_copy(update={"files": files})

    # ---------------- reducer helpers ----------------

    def _append_message(self, message: dict[str, Any]) -> None:
        self._state = self._state.model_copy(
            update={"messages": [*self._state.messages, message]}
        )

    def _put_file(self, path: str, file_data: dict[str, Any]) -> None:
        self._state = self._state.model_copy(
            update={"files": {**self._state.files, path: file_data}}
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — all Task 1 and Task 2 tests green.

- [ ] **Step 6: Commit**

```bash
git add research_team/session.py tests/conftest.py tests/test_session.py pyproject.toml
git commit -m "feat: add CodingSession aggregate with commands and reducers"
```

---

### Task 3: Message conversion

**Files:**
- Create: `research_team/messages.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: `SessionState` from Task 2.
- Produces:
  - `to_langchain(state: SessionState) -> list[BaseMessage]`
  - `classify(message: BaseMessage) -> type[DomainEvent]`
  - `new_messages(sent_count: int, after: list[BaseMessage]) -> list[BaseMessage]`

This module must not import `research_team.session` at runtime (only under `TYPE_CHECKING`) — it stays a pure conversion layer.

**Verified behavior this relies on** (confirmed by spike against deepagents 0.7.1): the agent returns the messages it was given, in order, followed by the new ones — and the `SystemMessage` is *not* among them, because `create_deep_agent` takes `system_prompt` separately. So the new messages are exactly `after[sent_count:]` where `sent_count` is the number of stored messages at invoke time. Do not diff on message `id`: ids exist but relying on them is needlessly fragile.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_messages.py
import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_to_dict,
)

from research_team.events import (
    AssistantMessageAdded,
    ToolResultRecorded,
    UserMessageSent,
)
from research_team.messages import classify, new_messages, to_langchain
from research_team.session import SessionState

from uuid import uuid4


def make_state(**kwargs) -> SessionState:
    return SessionState(session_id=uuid4(), system_prompt="SYS", **kwargs)


def test_system_prompt_is_prepended():
    messages = to_langchain(make_state())
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "SYS"


def test_round_trip_preserves_human_message():
    state = make_state(messages=[message_to_dict(HumanMessage("hello", id="h1"))])
    restored = to_langchain(state)[1]
    assert isinstance(restored, HumanMessage)
    assert restored.content == "hello"


def test_round_trip_preserves_tool_calls():
    original = AIMessage(
        content="",
        id="a1",
        tool_calls=[{"name": "write_file", "args": {"path": "/a.py"}, "id": "t1"}],
    )
    state = make_state(messages=[message_to_dict(original)])
    restored = to_langchain(state)[1]
    assert isinstance(restored, AIMessage)
    assert restored.tool_calls[0]["id"] == "t1"
    assert restored.tool_calls[0]["args"] == {"path": "/a.py"}


def test_round_trip_preserves_tool_message():
    state = make_state(
        messages=[message_to_dict(ToolMessage(content="done", tool_call_id="t1", id="m1"))]
    )
    restored = to_langchain(state)[1]
    assert isinstance(restored, ToolMessage)
    assert restored.tool_call_id == "t1"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (HumanMessage("x"), UserMessageSent),
        (AIMessage("x"), AssistantMessageAdded),
        (ToolMessage(content="x", tool_call_id="t1"), ToolResultRecorded),
    ],
)
def test_classify(message, expected):
    assert classify(message) is expected


def test_classify_rejects_unknown_type():
    with pytest.raises(TypeError, match="cannot record"):
        classify(SystemMessage("x"))


def test_new_messages_returns_suffix():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert [m.id for m in new_messages(1, after)] == ["2"]


def test_new_messages_empty_when_nothing_appended():
    after = [HumanMessage("a", id="1")]
    assert new_messages(1, after) == []


def test_new_messages_returns_all_when_count_zero():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert len(new_messages(0, after)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.messages'`

- [ ] **Step 3: Write minimal implementation**

```python
# research_team/messages.py
"""Conversion between stored message payloads and langchain messages.

Storage format is whatever `langchain_core.messages.message_to_dict`
produces, so we never define or maintain a message schema of our own.
"""

from typing import TYPE_CHECKING

from eventsource import DomainEvent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
)

from research_team.events import (
    AssistantMessageAdded,
    ToolResultRecorded,
    UserMessageSent,
)

if TYPE_CHECKING:
    from research_team.session import SessionState

_EVENT_FOR_MESSAGE: tuple[tuple[type[BaseMessage], type[DomainEvent]], ...] = (
    (HumanMessage, UserMessageSent),
    (AIMessage, AssistantMessageAdded),
    (ToolMessage, ToolResultRecorded),
)


def to_langchain(state: "SessionState") -> list[BaseMessage]:
    """Fold stored payloads into the message list the agent consumes."""
    history = messages_from_dict(state.messages)
    if not state.system_prompt:
        return history
    return [SystemMessage(state.system_prompt), *history]


def classify(message: BaseMessage) -> type[DomainEvent]:
    """Return the event class that records this message."""
    for message_type, event_class in _EVENT_FOR_MESSAGE:
        if isinstance(message, message_type):
            return event_class
    raise TypeError(f"cannot record message of type {type(message).__name__}")


def new_messages(sent_count: int, after: list[BaseMessage]) -> list[BaseMessage]:
    """The messages the agent appended beyond the `sent_count` we gave it.

    LangGraph returns the input messages verbatim and in order, then the new
    ones, and the SystemMessage is not among them (deepagents passes the
    system prompt separately). So the suffix is exactly the new work.
    """
    return after[sent_count:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_messages.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 5: Commit**

```bash
git add research_team/messages.py tests/test_messages.py
git commit -m "feat: add message conversion using langchain serialization"
```

---

### Task 4: Event-sourced backend

**Files:**
- Create: `research_team/backend.py`
- Test: `tests/test_backend.py`

**Interfaces:**
- Consumes: `CodingSession` from Task 2.
- Produces: `EventSourcedBackend(aggregate: CodingSession)` — a `StateBackend` subclass usable outside a LangGraph context.

**Critical:** do not override `ls`, `read`, `write`, `delete`, `grep`, `glob`, `upload_files`, or `download_files`. They are inherited and must stay inherited. Only `_read_files`, `_send_files_update`, and `edit` are overridden.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend.py
import inspect

import pytest
from deepagents.backends.state import StateBackend

from research_team.backend import EventSourcedBackend
from research_team.events import FileDeleted, FileEdited, FileWritten


@pytest.fixture
def backend(session) -> EventSourcedBackend:
    return EventSourcedBackend(session)


def event_types(session) -> list[type]:
    return [type(e) for e in session.uncommitted_events]


def test_seams_still_exist_on_upstream_state_backend():
    """Guard: we subclass over private seams. An upstream change must fail loudly."""
    assert hasattr(StateBackend, "_read_files")
    assert hasattr(StateBackend, "_send_files_update")
    read_sig = inspect.signature(StateBackend._read_files)
    send_sig = inspect.signature(StateBackend._send_files_update)
    assert list(read_sig.parameters) == ["self"]
    assert list(send_sig.parameters) == ["self", "update"]


def test_write_emits_file_written(backend, session):
    result = backend.write("/a.py", "print(1)\n")
    assert result.error is None
    assert event_types(session)[-1] is FileWritten
    assert session.state.files["/a.py"]["content"] == "print(1)\n"


def test_read_returns_written_content(backend):
    backend.write("/a.py", "print(1)\n")
    result = backend.read("/a.py")
    assert result.error is None
    assert result.file_data["content"] == "print(1)\n"


def test_edit_emits_file_edited_with_intent(backend, session):
    backend.write("/a.py", "print(1)\n")
    result = backend.edit("/a.py", "1", "2")
    assert result.error is None

    event = session.uncommitted_events[-1]
    assert isinstance(event, FileEdited)
    assert (event.old_string, event.new_string) == ("1", "2")
    assert event.file_data["content"] == "print(2)\n"


def test_edit_on_missing_file_errors_without_emitting(backend, session):
    before = len(session.uncommitted_events)
    result = backend.edit("/nope.py", "1", "2")
    assert result.error is not None
    assert len(session.uncommitted_events) == before


def test_edit_intent_is_cleared_after_edit(backend, session):
    backend.write("/a.py", "print(1)\n")
    backend.edit("/a.py", "1", "2")
    backend.write("/b.py", "x = 1\n")
    assert event_types(session)[-1] is FileWritten


def test_edit_intent_cleared_even_when_edit_raises(backend, session):
    backend.write("/a.py", "print(1)\n")
    with pytest.raises(RuntimeError):
        backend.edit("/a.py", "1", "2", boom=True)  # type: ignore[call-arg]
    backend.write("/b.py", "x = 1\n")
    assert event_types(session)[-1] is FileWritten


def test_delete_emits_file_deleted(backend, session):
    backend.write("/a.py", "print(1)\n")
    result = backend.delete("/a.py")
    assert result.error is None
    assert event_types(session)[-1] is FileDeleted
    assert "/a.py" not in session.state.files


def test_inherited_ls_grep_glob_work(backend):
    backend.write("/a.py", "alpha\nbeta\n")
    backend.write("/b.txt", "gamma\n")

    assert {entry["path"] for entry in backend.ls("/").entries} == {"/a.py", "/b.txt"}
    assert [m["path"] for m in backend.glob("**/*.py").matches] == ["/a.py"]
    assert [m["line"] for m in backend.grep("beta").matches] == [2]


def test_ambiguous_edit_is_rejected_by_inherited_validation(backend, session):
    backend.write("/a.py", "x\nx\n")
    before = len(session.uncommitted_events)
    result = backend.edit("/a.py", "x", "y")
    assert result.error is not None
    assert len(session.uncommitted_events) == before


def test_replace_all_edits_every_occurrence(backend, session):
    backend.write("/a.py", "x\nx\n")
    result = backend.edit("/a.py", "x", "y", replace_all=True)
    assert result.error is None
    assert session.state.files["/a.py"]["content"] == "y\ny\n"


def test_file_ops_do_not_require_graph_context(backend):
    """Overriding both seams means _get_config is never reached."""
    assert backend.write("/a.py", "x\n").error is None
```

Note: `test_edit_intent_cleared_even_when_edit_raises` passes an invalid kwarg to force a `TypeError`. Change it to trigger the `finally` path in whatever way is cleanest — the requirement is that a raising `edit` still clears `_edit_intent`. If a `TypeError` is raised before the override body runs, instead monkeypatch `StateBackend.edit` to raise:

```python
def test_edit_intent_cleared_even_when_edit_raises(backend, session, monkeypatch):
    backend.write("/a.py", "print(1)\n")
    monkeypatch.setattr(
        StateBackend, "edit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError):
        backend.edit("/a.py", "1", "2")
    monkeypatch.undo()
    backend.write("/b.py", "x = 1\n")
    assert event_types(session)[-1] is FileWritten
```

Use the monkeypatch version; delete the invalid-kwarg version.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.backend'`

- [ ] **Step 3: Write minimal implementation**

```python
# research_team/backend.py
"""Filesystem backend that records every mutation as a domain event.

`StateBackend` implements every file tool in terms of two private seams,
`_read_files` and `_send_files_update`. Overriding just those two gives us
deepagents' exact semantics -- line numbering, read windowing, edit
ambiguity checks, glob/grep, truncation, error strings -- with the
aggregate as the store. Do not reimplement any inherited method.
"""

from typing import Any

from deepagents.backends.protocol import EditResult
from deepagents.backends.state import StateBackend

from research_team.session import CodingSession


class EventSourcedBackend(StateBackend):
    def __init__(self, aggregate: CodingSession) -> None:
        self._aggregate = aggregate
        self._edit_intent: tuple[str, str, bool] | None = None

    # ---- the two seams ----

    def _read_files(self) -> dict[str, Any]:
        return dict(self._aggregate.state.files)

    def _send_files_update(self, update: dict[str, Any]) -> None:
        for path, file_data in update.items():
            if file_data is None:
                self._aggregate.delete_file(path)
            elif self._edit_intent is not None:
                old_string, new_string, replace_all = self._edit_intent
                self._aggregate.edit_file(
                    path, file_data, old_string, new_string, replace_all
                )
            else:
                self._aggregate.write_file(path, file_data)

    # ---- intent capture ----

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Record *why* the file changed, then defer entirely to the superclass.

        The superclass performs all validation and the replacement itself; we
        only observe, so `FileEdited` can carry the edit intent alongside the
        resulting content.
        """
        self._edit_intent = (old_string, new_string, replace_all)
        try:
            return super().edit(
                file_path, old_string, new_string, replace_all=replace_all
            )
        finally:
            self._edit_intent = None
```

If `EditResult` is not importable from `deepagents.backends.protocol`, find its real location with `grep -rn "class EditResult" .venv/lib/python3.13/site-packages/deepagents/` and import from there.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_backend.py -v`
Expected: PASS, 13 passed.

- [ ] **Step 5: Commit**

```bash
git add research_team/backend.py tests/test_backend.py
git commit -m "feat: add event-sourced filesystem backend over StateBackend seams"
```

---

### Task 5: Runtime

**Files:**
- Create: `research_team/runtime.py`
- Modify: `tests/conftest.py` (add `ToolAwareFakeChatModel` and `fake_model` fixtures)
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `CodingSession`, `EventSourcedBackend`, `to_langchain`, `classify`, `new_messages`.
- Produces:
  - `AgentRuntime` dataclass with fields `store: InMemoryEventStore`, `repo: AggregateRepository[CodingSession]`, `session_id: UUID`, `model: BaseChatModel`.
  - `async def build_runtime(*, model: BaseChatModel | None = None, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> AgentRuntime`
  - `def build_model() -> BaseChatModel`
  - `async def run_turn(runtime: AgentRuntime, user_input: str) -> str`
  - `async def history(runtime: AgentRuntime) -> list[DomainEvent]`
  - `async def fork(runtime: AgentRuntime, at: int) -> UUID`
  - `async def rewind(runtime: AgentRuntime, at: int) -> None`
  - `DEFAULT_SYSTEM_PROMPT: str`

- [ ] **Step 1: Add fixtures to `tests/conftest.py`**

Append:

Use langchain's own fake and add only the one method it lacks. **This exact form is spike-verified against deepagents 0.7.1** — `FakeMessagesListChatModel` alone raises `NotImplementedError` from `bind_tools` inside `create_deep_agent`, and overriding it to return `self` is sufficient for tool calls to flow through.

```python
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage


class ToolAwareFakeChatModel(FakeMessagesListChatModel):
    """langchain's fake, plus the bind_tools deepagents requires.

    Replays `responses` one per invocation. Do not hand-roll a BaseChatModel
    subclass -- this is the library's fake with a single method added.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolAwareFakeChatModel":
        return self


@pytest.fixture
def fake_model() -> ToolAwareFakeChatModel:
    return ToolAwareFakeChatModel(responses=[AIMessage(content="done", id="a1")])
```

Note `responses` is consumed one per model call, and a tool-calling turn costs two calls (the tool-call message, then the follow-up). Tests that exercise tools must script both.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_runtime.py
import pytest
from langchain_core.messages import AIMessage

from research_team import runtime as rt
from research_team.events import (
    AssistantMessageAdded,
    FileWritten,
    SessionStarted,
    TurnCompleted,
    UserMessageSent,
)


@pytest.fixture
async def runtime(fake_model):
    return await rt.build_runtime(model=fake_model)


async def test_build_runtime_starts_session(runtime):
    events = await rt.history(runtime)
    assert [type(e) for e in events] == [SessionStarted]


async def test_run_turn_records_user_and_assistant(runtime):
    reply = await rt.run_turn(runtime, "hello")
    assert reply == "done"

    types = [type(e) for e in await rt.history(runtime)]
    assert types[0] is SessionStarted
    assert UserMessageSent in types
    assert AssistantMessageAdded in types
    assert types[-1] is TurnCompleted


async def test_turn_index_increments(runtime):
    await rt.run_turn(runtime, "one")
    await rt.run_turn(runtime, "two")
    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.turn_index == 2


async def test_history_is_ordered_by_version(runtime):
    await rt.run_turn(runtime, "hello")
    events = await rt.history(runtime)
    versions = [e.aggregate_version for e in events]
    assert versions == sorted(versions)


async def test_tool_call_writes_file_and_records_events(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/hello.py", "content": "print('hi')\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
    ]
    runtime = await rt.build_runtime(model=fake_model)
    reply = await rt.run_turn(runtime, "write hello.py")

    assert reply == "wrote it"
    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.files["/hello.py"]["content"] == "print('hi')\n"
    assert FileWritten in [type(e) for e in await rt.history(runtime)]


async def test_failed_turn_appends_nothing(runtime, monkeypatch):
    before = len(await rt.history(runtime))

    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "hello")

    assert len(await rt.history(runtime)) == before


async def test_fork_creates_independent_stream(runtime):
    await rt.run_turn(runtime, "hello")
    original_events = await rt.history(runtime)

    forked_id = await rt.fork(runtime, at=1)
    forked = await runtime.repo.load(forked_id)

    assert forked_id != runtime.session_id
    assert forked.version == 1
    assert forked.state.messages == []
    assert len(await rt.history(runtime)) == len(original_events)


async def test_rewind_repoints_session(runtime):
    await rt.run_turn(runtime, "hello")
    original_id = runtime.session_id

    await rt.rewind(runtime, at=1)

    assert runtime.session_id != original_id
    assert len(await rt.history(runtime)) == 1
    original = await runtime.repo.load(original_id)
    assert original.version > 1, "rewind must not destroy the original stream"


async def test_snapshot_threshold_is_configured(runtime):
    assert runtime.repo.snapshot_threshold == 50
    assert runtime.repo.has_snapshot_support
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.runtime'`

- [ ] **Step 4: Write minimal implementation**

```python
# research_team/runtime.py
"""Wiring and the operations that drive a session."""

import os
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from deepagents import create_deep_agent
from eventsource import DomainEvent, StreamId, collect
from eventsource.adapters.memory import InMemoryEventStore
from eventsource.adapters.memory.snapshots import InMemorySnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict
from langchain_openai import ChatOpenAI

from research_team.backend import EventSourcedBackend
from research_team.events import ToolResultRecorded
from research_team.messages import classify, new_messages, to_langchain
from research_team.session import CodingSession

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell and no network."
)

SNAPSHOT_THRESHOLD = 50


def build_model() -> BaseChatModel:
    """The local OpenAI-compatible endpoint, fully env-overridable."""
    return ChatOpenAI(
        model=os.getenv("AGENT_MODEL", "qwen3.6-27b-mtp"),
        base_url=os.getenv("AGENT_BASE_URL", "http://192.168.1.14:8080/v1/"),
        api_key=os.getenv("AGENT_API_KEY", "not-needed"),
        temperature=0,
    )


@dataclass
class AgentRuntime:
    store: InMemoryEventStore
    repo: AggregateRepository[CodingSession]
    session_id: UUID
    model: BaseChatModel
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


def _build_repo(store: InMemoryEventStore) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        snapshot_store=InMemorySnapshotStore(),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="sync",
    )


async def build_runtime(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> AgentRuntime:
    store = InMemoryEventStore()
    repo = _build_repo(store)
    resolved_model = model if model is not None else build_model()
    model_name = getattr(resolved_model, "model_name", type(resolved_model).__name__)

    session_id = uuid4()
    aggregate = repo.create_new(session_id)
    aggregate.start(system_prompt, model_name)
    await repo.save(aggregate)

    return AgentRuntime(
        store=store,
        repo=repo,
        session_id=session_id,
        model=resolved_model,
        system_prompt=system_prompt,
    )


async def _invoke_agent(
    runtime: AgentRuntime, aggregate: CodingSession, messages: list[BaseMessage]
) -> list[BaseMessage]:
    """Seam kept separate so tests can force a mid-turn failure."""
    agent = create_deep_agent(
        model=runtime.model,
        backend=EventSourcedBackend(aggregate),
        system_prompt=runtime.system_prompt,
        checkpointer=None,
    )
    result = await agent.ainvoke({"messages": messages})
    return result["messages"]


async def run_turn(runtime: AgentRuntime, user_input: str) -> str:
    """One user turn. All events append atomically at the end, or not at all."""
    aggregate = await runtime.repo.load(runtime.session_id)
    aggregate.send_user_message(message_to_dict(_human(user_input)))

    sent_count = len(aggregate.state.messages)
    after = await _invoke_agent(runtime, aggregate, to_langchain(aggregate.state))

    for message in new_messages(sent_count, after):
        event_class = classify(message)
        if event_class is ToolResultRecorded:
            aggregate.record_tool_result(message_to_dict(message))
        else:
            aggregate.record_assistant_message(message_to_dict(message))

    aggregate.complete_turn()
    await runtime.repo.save(aggregate)

    return _last_text(after)


def _human(text: str) -> BaseMessage:
    from langchain_core.messages import HumanMessage

    return HumanMessage(text)


def _last_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            if message.content:
                return message.content
    return ""


def _stream(session_id: UUID) -> StreamId:
    return StreamId(session_id, CodingSession.aggregate_type)


async def history(runtime: AgentRuntime) -> list[DomainEvent]:
    envelopes = await collect(runtime.store.read_stream(_stream(runtime.session_id)))
    return [envelope.event for envelope in envelopes]


async def fork(runtime: AgentRuntime, at: int) -> UUID:
    """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
    events = await history(runtime)
    if not 1 <= at <= len(events):
        raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

    new_id = uuid4()
    forked = runtime.repo.create_new(new_id)
    for event in events[:at]:
        forked.create_event(
            type(event),
            **event.model_dump(
                exclude={
                    "event_id",
                    "event_type",
                    "occurred_at",
                    "aggregate_id",
                    "aggregate_type",
                    "aggregate_version",
                }
            ),
        )
    await runtime.repo.save(forked)
    return new_id


async def rewind(runtime: AgentRuntime, at: int) -> None:
    """Fork at `at` and continue from the fork. The original stream remains."""
    runtime.session_id = await fork(runtime, at)
```

The `exclude` set in `fork` must drop exactly the fields `create_event` re-populates. If replay raises a duplicate-keyword or validation error, print `event.model_dump().keys()` and adjust the exclusion set — do not work around it by constructing events manually.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_runtime.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 6: Commit**

```bash
git add research_team/runtime.py tests/conftest.py tests/test_runtime.py
git commit -m "feat: add runtime with turn loop, fork and rewind"
```

---

### Task 6: Replay test

**Files:**
- Test: `tests/test_replay.py`

This task adds no production code. It exists to prove the central claim of the design: **refolding the log reproduces the exact workspace.** If it fails, something in Tasks 1–5 is wrong; fix that rather than weakening the assertion.

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing.

- [ ] **Step 1: Write the test**

```python
# tests/test_replay.py
import pytest
from langchain_core.messages import AIMessage

from research_team import runtime as rt
from research_team.session import CodingSession


@pytest.fixture
def scripted_model(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/app.py", "content": "x = 1\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="created app.py", id="a2"),
        AIMessage(
            content="",
            id="a3",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {"file_path": "/app.py", "old_string": "1", "new_string": "2"},
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="updated app.py", id="a4"),
    ]
    return fake_model


async def test_refolding_reproduces_state_exactly(scripted_model):
    runtime = await rt.build_runtime(model=scripted_model)
    await rt.run_turn(runtime, "create app.py")
    await rt.run_turn(runtime, "change 1 to 2")

    live = await runtime.repo.load(runtime.session_id)

    # Rebuild from event zero with a repository that has no snapshot cache.
    from eventsource.application.aggregates.repository import AggregateRepository

    cold_repo = AggregateRepository(runtime.store, CodingSession)
    replayed = await cold_repo.load(runtime.session_id)

    assert replayed.version == live.version
    assert replayed.state == live.state


async def test_replay_reproduces_file_content(scripted_model):
    runtime = await rt.build_runtime(model=scripted_model)
    await rt.run_turn(runtime, "create app.py")
    await rt.run_turn(runtime, "change 1 to 2")

    from eventsource.application.aggregates.repository import AggregateRepository

    cold_repo = AggregateRepository(runtime.store, CodingSession)
    replayed = await cold_repo.load(runtime.session_id)

    assert replayed.state.files["/app.py"]["content"] == "x = 2\n"


async def test_replay_is_deterministic_across_repeats(scripted_model):
    runtime = await rt.build_runtime(model=scripted_model)
    await rt.run_turn(runtime, "create app.py")

    from eventsource.application.aggregates.repository import AggregateRepository

    first = await AggregateRepository(runtime.store, CodingSession).load(runtime.session_id)
    second = await AggregateRepository(runtime.store, CodingSession).load(runtime.session_id)

    assert first.state == second.state


async def test_fork_diverges_without_affecting_original(scripted_model):
    runtime = await rt.build_runtime(model=scripted_model)
    await rt.run_turn(runtime, "create app.py")
    await rt.run_turn(runtime, "change 1 to 2")

    original_state = (await runtime.repo.load(runtime.session_id)).state
    forked_id = await rt.fork(runtime, at=2)
    forked = await runtime.repo.load(forked_id)

    assert forked.state != original_state
    assert (await runtime.repo.load(runtime.session_id)).state == original_state
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_replay.py -v`
Expected: PASS, 4 passed. If any fail, the defect is in Tasks 1–5.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_replay.py
git commit -m "test: prove refolding the log reproduces session state exactly"
```

---

### Task 7: REPL

**Files:**
- Create: `research_team/repl.py`
- Modify: `main.py`
- Test: `tests/test_repl.py`

**Interfaces:**
- Consumes: everything from Task 5.
- Produces:
  - `async def handle_command(runtime: AgentRuntime, line: str) -> str | None` — returns text to print, or `None` to signal quit. Raises nothing for user error; returns an error string.
  - `async def main() -> None` — the loop.
  - `def format_log(events: list[DomainEvent], limit: int) -> str`
  - `def format_files(events: list[DomainEvent], files: dict[str, dict[str, Any]]) -> str`
  - `def format_file_history(events: list[DomainEvent], path: str) -> str`

All formatting functions are pure so they can be tested without a runtime.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repl.py
import pytest

from research_team import repl
from research_team import runtime as rt
from research_team.events import FileEdited, FileWritten, SessionStarted, TurnCompleted


@pytest.fixture
async def runtime(fake_model):
    return await rt.build_runtime(model=fake_model)


def test_format_log_numbers_events():
    events = [
        SessionStarted(system_prompt="s", model_name="m", aggregate_version=1),
        TurnCompleted(turn_index=1, aggregate_version=2),
    ]
    output = repl.format_log(events, limit=10)
    assert "#1" in output and "SessionStarted" in output
    assert "#2" in output and "TurnCompleted" in output


def test_format_log_respects_limit():
    events = [TurnCompleted(turn_index=i, aggregate_version=i) for i in range(1, 6)]
    output = repl.format_log(events, limit=2)
    assert output.count("\n") == 1
    assert "#5" in output and "#1" not in output


def test_format_files_reports_revision_count():
    events = [
        FileWritten(path="/a.py", file_data={"content": "x\n"}, aggregate_version=1),
        FileEdited(
            path="/a.py", file_data={"content": "y\n"},
            old_string="x", new_string="y", replace_all=False, aggregate_version=2,
        ),
    ]
    output = repl.format_files(events, {"/a.py": {"content": "y\n"}})
    assert "/a.py" in output
    assert "2" in output


def test_format_files_when_empty():
    assert "no files" in repl.format_files([], {}).lower()


def test_format_file_history_lists_touching_events():
    events = [
        FileWritten(path="/a.py", file_data={"content": "x\n"}, aggregate_version=1),
        FileWritten(path="/b.py", file_data={"content": "z\n"}, aggregate_version=2),
        FileEdited(
            path="/a.py", file_data={"content": "y\n"},
            old_string="x", new_string="y", replace_all=False, aggregate_version=3,
        ),
    ]
    output = repl.format_file_history(events, "/a.py")
    assert "FileWritten" in output and "FileEdited" in output
    assert "/b.py" not in output


def test_format_file_history_unknown_path():
    assert "no history" in repl.format_file_history([], "/nope.py").lower()


async def test_quit_returns_none(runtime):
    assert await repl.handle_command(runtime, "/quit") is None


async def test_help_lists_commands(runtime):
    output = await repl.handle_command(runtime, "/help")
    for command in ("/log", "/files", "/cat", "/history", "/rewind", "/fork", "/state"):
        assert command in output


async def test_unknown_command_is_reported(runtime):
    output = await repl.handle_command(runtime, "/bogus")
    assert "unknown command" in output.lower()


async def test_cat_requires_argument(runtime):
    output = await repl.handle_command(runtime, "/cat")
    assert "usage" in output.lower()


async def test_cat_missing_file(runtime):
    output = await repl.handle_command(runtime, "/cat /nope.py")
    assert "not found" in output.lower()


async def test_rewind_requires_integer(runtime):
    output = await repl.handle_command(runtime, "/rewind abc")
    assert "usage" in output.lower()


async def test_rewind_out_of_range_is_reported(runtime):
    output = await repl.handle_command(runtime, "/rewind 99")
    assert "cannot" in output.lower() or "range" in output.lower()


async def test_state_reports_session_facts(runtime):
    output = await repl.handle_command(runtime, "/state")
    assert str(runtime.session_id) in output
    assert "events" in output.lower()


async def test_plain_input_runs_a_turn(runtime):
    output = await repl.handle_command(runtime, "hello there")
    assert output == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repl.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.repl'`

- [ ] **Step 3: Write minimal implementation**

```python
# research_team/repl.py
"""Terminal REPL. Formatting and dispatch only -- no domain logic."""

import asyncio
from typing import Any

from eventsource import DomainEvent

from research_team import runtime as rt
from research_team.events import FileDeleted, FileEdited, FileWritten
from research_team.runtime import AgentRuntime

FILE_EVENTS = (FileWritten, FileEdited, FileDeleted)

HELP = """\
Commands:
  /log [n]         last n events (default 20)
  /files           files in the workspace, with revision counts
  /cat <path>      current contents of a file
  /history <path>  every event that touched a path
  /rewind <n>      continue from a fork at event n
  /fork <n>        fork at event n and switch to it
  /state           session id, event count, turn count, file count
  /help            this message
  /quit            exit

Anything else is sent to the agent as a turn."""


def _summary(event: DomainEvent) -> str:
    if isinstance(event, FILE_EVENTS):
        return event.path
    if hasattr(event, "turn_index"):
        return f"turn {event.turn_index}"
    if hasattr(event, "message"):
        return str(event.message.get("data", {}).get("content", ""))[:60]
    return ""


def format_log(events: list[DomainEvent], limit: int) -> str:
    if not events:
        return "(no events)"
    selected = events[-limit:]
    offset = len(events) - len(selected)
    return "\n".join(
        f"#{offset + i + 1:<4} {type(event).__name__:<24} {_summary(event)}"
        for i, event in enumerate(selected)
    )


def format_files(events: list[DomainEvent], files: dict[str, dict[str, Any]]) -> str:
    if not files:
        return "(no files)"
    revisions: dict[str, int] = {}
    for event in events:
        if isinstance(event, FILE_EVENTS):
            revisions[event.path] = revisions.get(event.path, 0) + 1
    lines = []
    for path in sorted(files):
        size = len(files[path].get("content", ""))
        lines.append(f"{path:<40} {size:>8}B  rev {revisions.get(path, 0)}")
    return "\n".join(lines)


def format_file_history(events: list[DomainEvent], path: str) -> str:
    rows = [
        f"#{i + 1:<4} {type(event).__name__}"
        for i, event in enumerate(events)
        if isinstance(event, FILE_EVENTS) and event.path == path
    ]
    return "\n".join(rows) if rows else f"(no history for {path})"


async def handle_command(runtime: AgentRuntime, line: str) -> str | None:
    line = line.strip()
    if not line:
        return ""
    if not line.startswith("/"):
        return await rt.run_turn(runtime, line)

    command, _, argument = line.partition(" ")
    argument = argument.strip()

    if command == "/quit":
        return None
    if command == "/help":
        return HELP
    if command == "/log":
        limit = int(argument) if argument.isdigit() else 20
        return format_log(await rt.history(runtime), limit)
    if command == "/files":
        aggregate = await runtime.repo.load(runtime.session_id)
        return format_files(await rt.history(runtime), aggregate.state.files)
    if command == "/cat":
        if not argument:
            return "usage: /cat <path>"
        aggregate = await runtime.repo.load(runtime.session_id)
        entry = aggregate.state.files.get(argument)
        return entry["content"] if entry else f"{argument}: not found"
    if command == "/history":
        if not argument:
            return "usage: /history <path>"
        return format_file_history(await rt.history(runtime), argument)
    if command in ("/rewind", "/fork"):
        if not argument.isdigit():
            return f"usage: {command} <event-number>"
        try:
            if command == "/rewind":
                await rt.rewind(runtime, int(argument))
                return f"rewound to event {argument}; session {runtime.session_id}"
            new_id = await rt.fork(runtime, int(argument))
            runtime.session_id = new_id
            return f"forked at event {argument}; session {new_id}"
        except ValueError as error:
            return str(error)
    if command == "/state":
        events = await rt.history(runtime)
        aggregate = await runtime.repo.load(runtime.session_id)
        return (
            f"session  {runtime.session_id}\n"
            f"events   {len(events)}\n"
            f"turns    {aggregate.state.turn_index}\n"
            f"files    {len(aggregate.state.files)}"
        )
    return f"unknown command {command!r} -- try /help"


async def main() -> None:
    runtime = await rt.build_runtime()
    print(f"session {runtime.session_id} -- /help for commands")
    while True:
        try:
            line = await asyncio.to_thread(input, "> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            output = await handle_command(runtime, line)
        except Exception as error:  # noqa: BLE001 -- keep the REPL alive
            print(f"error: {type(error).__name__}: {error}")
            continue
        if output is None:
            return
        if output:
            print(output)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Update `main.py`**

```python
# main.py
import asyncio

from research_team.repl import main as repl_main


def main() -> None:
    asyncio.run(repl_main())


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_repl.py -v`
Expected: PASS, 15 passed.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add research_team/repl.py main.py tests/test_repl.py
git commit -m "feat: add REPL with event-log meta-commands"
```

---

### Task 8: Live smoke test and README

**Files:**
- Create: `tests/test_live.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything.
- Produces: nothing importable.

- [ ] **Step 1: Write the live test**

```python
# tests/test_live.py
"""Hits the real endpoint. Deselected by default; run with `-m live`."""

import pytest

from research_team import runtime as rt

pytestmark = pytest.mark.live


async def test_agent_writes_a_file_against_the_real_model():
    runtime = await rt.build_runtime()
    await rt.run_turn(
        runtime,
        "Create a file /fizzbuzz.py containing a fizzbuzz function. "
        "Use the write_file tool. Do not explain.",
    )

    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.files, "agent produced no files"
    assert any("fizz" in data["content"].lower() for data in aggregate.state.files.values())
```

- [ ] **Step 2: Run it against the endpoint**

Run: `uv run pytest tests/test_live.py -m live -v`

Expected: PASS. If the model emits malformed tool calls, that is a model-capability finding, not a code defect — record the observed behavior in the README's Status section and leave the test marked `live` so the default suite stays green. Do not weaken the assertion to make it pass.

- [ ] **Step 3: Verify the default suite still excludes it**

Run: `uv run pytest -v`
Expected: all green, `test_live.py` deselected.

- [ ] **Step 4: Write the README**

Cover: what this is (one paragraph, per the spec's Purpose), quickstart (`uv run main.py`), the four env vars (`AGENT_MODEL`, `AGENT_BASE_URL`, `AGENT_API_KEY`), the REPL command table copied from `HELP`, a short "How it works" section pointing at the spec, and a Status section recording live-model behavior observed in Step 2.

- [ ] **Step 5: Commit**

```bash
git add tests/test_live.py README.md
git commit -m "test: add live smoke test; docs: add README"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| `events.py` schema | 1 |
| `session.py` state, commands, invariants | 2 |
| `messages.py` conversion | 3 |
| `backend.py` seams + edit intent | 4 |
| `runtime.py` wiring, turn, history, fork, rewind | 5 |
| Snapshot config (threshold 50, sync) | 5 (`_build_repo`, asserted in `test_snapshot_threshold_is_configured`) |
| Model config + env vars | 5 (`build_model`) |
| `repl.py` + all eight meta-commands | 7 |
| Error handling: failed turn appends nothing | 5 (`test_failed_turn_appends_nothing`) |
| Error handling: tool errors visible to model | 4 (`test_edit_on_missing_file_errors_without_emitting`) |
| Error handling: REPL never tracebacks | 7 (`main` catch, arg-validation tests) |
| Testing: replay purity | 6 |
| Testing: live test skipped by default | 2 (`addopts`), 8 |
| Risk mitigation: seam-existence guard | 4 (`test_seams_still_exist_on_upstream_state_backend`) |
| Risk mitigation: out-of-order tool ids | 2 (`test_tool_results_may_resolve_out_of_order`) |
| Dependency pin `<0.8` | Already applied to `pyproject.toml` |

No gaps.

**Type consistency:** `write_file(path, file_data)`, `edit_file(path, file_data, old_string, new_string, replace_all)`, and `delete_file(path)` are called with exactly these signatures in Task 4's `_send_files_update`. `to_langchain`/`classify`/`new_messages` signatures in Task 3 match their call sites in Task 5. `history`/`fork`/`rewind` signatures in Task 5 match Task 7's calls.

**Known implementation risks flagged inline** (each has an instruction rather than a placeholder): ~~`EditResult` import location~~ — resolved: `deepagents.backends.protocol`, ~~`FakeChatModel` adequacy~~ — resolved by spike; `ToolAwareFakeChatModel` given verbatim, `fork` field-exclusion set (Task 5 Step 4). Each says what to check and what to do — none should be resolved by inventing a workaround.
