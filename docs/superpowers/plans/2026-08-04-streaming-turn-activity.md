# Streaming Turn Activity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show what a turn is doing in the web UI while it runs, without making the event log incremental.

**Architecture:** A turn is atomic — every event appends in one `repository.save()` at the end — so the live feed has nothing to show mid-turn. Rather than change that, add a second, explicitly non-durable channel: the executor reports structured notes as the agent produces them, a per-session buffer holds them for the running turn, and they ride the existing SSE connection as frames with no `id` (exactly as approval frames already do). The timeline keeps rendering the log; provisional content is replaced, not merged, on commit.

**Tech Stack:** Python 3.13, FastAPI, langgraph 1.2.10, deepagents 0.7.1, langchain-core, pytest (async), vanilla JS frontend (no build step, no framework).

**Spec:** `docs/superpowers/specs/2026-08-04-streaming-turn-activity-design.md`

## Global Constraints

- **Turn atomicity is inviolable.** No task may append an event mid-turn. `SessionService._run_turn` still calls `repository.save()` exactly once. Task 8 is the regression guard for this.
- **The dependency rule is enforced by `tests/test_architecture.py`.** Layers are `domain → application → infrastructure → interfaces`; imports point inward only. `application` and `domain` may import `eventsource` and nothing else framework-shaped — **no `langchain`, `langchain_core`, or `deepagents` imports in `research_team/application/`.** New port types must be plain dataclasses over `dict`.
- **`TurnActivity` is a transport frame type, never a domain event.** Do not add it to `research_team/domain/events.py`.
- **Frame types are PascalCase** to match the existing `type` field the browser switches on (see `approvals.py:23-26`).
- **The durable record must be byte-identical** whether or not a reporter is attached. Token deltas never feed `new_messages()`.
- **REPL terminal output must not change.**
- **No new dependencies.** No schema change, no migration, no new event types.
- Run tests with `uv run pytest`. Lint with `uv run ruff check`.
- Commit after every task.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `research_team/application/ports.py` | Declare `ActivityMessage`, `ActivityDelta`, `ActivityNote`; widen `ActivityReporter` | 1 |
| `research_team/infrastructure/agent/deep_agent.py` | Dual-mode stream; emit structured notes | 2, 3 |
| `research_team/interfaces/cli/repl.py` | Format notes to terminal lines | 4 |
| `research_team/interfaces/web/activity.py` | **New.** Per-session buffer + broadcast | 5 |
| `research_team/interfaces/web/__init__.py` | Export `TurnActivity` | 5 |
| `research_team/interfaces/web/app.py` | Wire reporter into the turn route; catch-up route; SSE pump | 6 |
| `web.py` | Construct `TurnActivity` at the composition root | 6 |
| `research_team/interfaces/web/static/app.js` | Provisional bubbles, delta accumulation, reconciliation | 7 |
| `research_team/interfaces/web/static/style.css` | Provisional / discarded styling | 7 |
| `tests/integration/test_turn_visibility.py` | Atomicity regression guard | 8 |

---

### Task 1: The port — structured activity notes

**Files:**
- Modify: `research_team/application/ports.py:23` (the `ActivityReporter` alias) and the dataclass region near `RecordedMessage` (~line 165)
- Test: `tests/application/test_live_feed.py` — no; use `tests/application/test_context.py`? No. **Create:** `tests/application/test_activity_notes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ActivityMessage(message_id: str, kind: MessageKind, payload: dict, is_error: bool = False)`, `ActivityDelta(message_id: str, text: str)`, `ActivityNote = ActivityMessage | ActivityDelta`, `ActivityReporter = Callable[[ActivityNote], None]`. Tasks 2–7 all depend on these exact names.

**Context:** `ActivityReporter` is currently `Callable[[str], None]` (`ports.py:23`), which cannot carry structure. `MessageKind = Literal["assistant", "tool"]` already exists at `ports.py` (~line 160) — reuse it, do not redefine it. `payload` is an opaque `dict` for the same reason `RecordedMessage.payload` is: the application layer must not know langchain's message shape, and the architecture test forbids importing it here.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_activity_notes.py`:

```python
"""The activity note types the executor reports and the web layer buffers."""

from research_team.application.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityReporter,
)


def test_activity_message_carries_an_opaque_payload():
    note = ActivityMessage(
        message_id="a1",
        kind="assistant",
        payload={"content": "hello", "id": "a1"},
        is_error=False,
    )
    assert note.message_id == "a1"
    assert note.kind == "assistant"
    assert note.payload["content"] == "hello"
    assert note.is_error is False


def test_activity_message_defaults_to_not_an_error():
    note = ActivityMessage(message_id="t1", kind="tool", payload={})
    assert note.is_error is False


def test_activity_delta_carries_text_for_one_message():
    note = ActivityDelta(message_id="a1", text="hel")
    assert note.message_id == "a1"
    assert note.text == "hel"


def test_notes_are_frozen():
    import dataclasses
    import pytest

    note = ActivityDelta(message_id="a1", text="hel")
    with pytest.raises(dataclasses.FrozenInstanceError):
        note.text = "changed"


def test_reporter_accepts_either_note():
    seen: list = []
    reporter: ActivityReporter = seen.append
    reporter(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    reporter(ActivityDelta(message_id="a1", text="x"))
    assert len(seen) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_activity_notes.py -v`
Expected: FAIL with `ImportError: cannot import name 'ActivityDelta' from 'research_team.application.ports'`

- [ ] **Step 3: Write minimal implementation**

In `research_team/application/ports.py`, **replace** the existing alias at line 23:

```python
ActivityReporter = Callable[[str], None]
"""Called with a one-line progress note while a turn is in flight."""
```

with a forward-declared version placed *after* the note dataclasses. Add the dataclasses immediately below the existing `MessageKind` / `RecordedMessage` definitions:

```python
@dataclass(frozen=True)
class ActivityMessage:
    """A whole message the agent produced, reported before the turn commits.

    Provisional by construction: the turn may still fail, in which case none of
    these becomes an event. `payload` is opaque here for the same reason
    `RecordedMessage.payload` is -- only the executor that produced it knows
    its shape, and this layer may not name langchain.
    """

    message_id: str
    """The message's own id, so a delta and the whole message that supersedes
    it can be matched without inventing a correlation scheme."""

    kind: MessageKind
    payload: dict
    is_error: bool = False


@dataclass(frozen=True)
class ActivityDelta:
    """A chunk of assistant prose, to append to `message_id`.

    Only ever prose. Tool call arguments are never streamed in pieces: partial
    JSON renders as garbage and would have to be buffered whole anyway.
    """

    message_id: str
    text: str


ActivityNote = ActivityMessage | ActivityDelta

ActivityReporter = Callable[[ActivityNote], None]
"""Called with progress as a turn runs, before anything is appended to the log.

Widened from a one-line string: the web UI renders the content itself, so a
formatted line is not enough. The terminal formats these back down to a line
(`research_team.interfaces.cli.repl`).

Never called for anything the log will not eventually contain on a successful
turn -- this is a preview of the turn, not a side channel for commentary.
"""
```

Move the `ActivityReporter` alias so it appears **after** `ActivityNote`. `MessageKind` is already defined above `RecordedMessage`; if the dataclasses are placed before it, move them below instead — do not duplicate `MessageKind`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_activity_notes.py -v`
Expected: 5 passed

Then confirm the layering rule still holds:

Run: `uv run pytest tests/test_architecture.py -v`
Expected: all pass (the new types import nothing new)

- [ ] **Step 5: Check what still type-checks**

Run: `uv run ruff check research_team/`
Expected: clean. Callers passing `str`-shaped reporters are still syntactically valid Python; Tasks 2 and 4 fix them semantically.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/ports.py tests/application/test_activity_notes.py
git commit -m "feat: structured activity notes on the reporter port"
```

---

### Task 2: Executor emits whole messages as structured notes

**Files:**
- Modify: `research_team/infrastructure/agent/deep_agent.py:45-55` (`describe_activity`), `:155-175` (the `astream` loop)
- Test: `tests/infrastructure/test_backend.py`? No. **Create:** `tests/infrastructure/test_activity_stream.py`

**Interfaces:**
- Consumes: `ActivityMessage`, `ActivityDelta`, `ActivityNote` from Task 1.
- Produces: `to_activity_message(message) -> ActivityMessage | None` in `deep_agent.py`. Task 3 extends the same loop; Task 4 reuses `describe_activity`.

**Context:** The loop at `deep_agent.py:163` currently does:

```python
if on_activity is not None:
    for message in final[reported:]:
        note = describe_activity(message)
        if note:
            on_activity(note)
```

`describe_activity` stays exactly as it is — Task 4 needs it for the terminal. This task adds a *second* converter that produces structured notes, and switches the loop to call it.

`to_recorded` already exists in this module's neighbourhood (used by `execute`) and converts a langchain message to a `RecordedMessage` with `kind`/`payload`/`is_error`. Reuse it rather than re-deriving the mapping — a drift between what is streamed and what is recorded is the exact bug this design is meant to prevent.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_activity_stream.py`:

```python
"""What the executor reports while a turn is in flight."""

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.domain import StartSession
from research_team.infrastructure.agent.deep_agent import (
    DeepAgentTurnExecutor,
    to_activity_message,
)


class ToolAwareFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolAwareFakeChatModel":
        return self


def test_assistant_message_becomes_an_activity_message():
    note = to_activity_message(AIMessage(content="hello", id="a1"))
    assert isinstance(note, ActivityMessage)
    assert note.message_id == "a1"
    assert note.kind == "assistant"
    assert note.is_error is False


def test_tool_message_becomes_a_tool_activity_message():
    note = to_activity_message(
        ToolMessage(content="result text", tool_call_id="c1", id="t1")
    )
    assert isinstance(note, ActivityMessage)
    assert note.message_id == "t1"
    assert note.kind == "tool"


def test_a_message_without_an_id_is_not_reported():
    """Guessing an id would splice two messages together in the accumulator."""
    assert to_activity_message(AIMessage(content="hello", id=None)) is None


async def test_running_a_turn_reports_whole_messages(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(StartSession(system_prompt="be brief", model_name="fake"))
    model = ToolAwareFakeChatModel(
        responses=[AIMessage(content="the reply", id="a1")]
    )
    executor = DeepAgentTurnExecutor(model)

    seen: list = []
    await executor.execute(
        session,
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="be brief",
        on_activity=seen.append,
    )

    messages = [n for n in seen if isinstance(n, ActivityMessage)]
    assert any(n.kind == "assistant" for n in messages)
    assert all(isinstance(n, (ActivityMessage, ActivityDelta)) for n in seen)
    assert not any(isinstance(n, str) for n in seen)
```

Note: `aggregates` and `session_id` are existing fixtures in `tests/conftest.py`. The message shape passed to `execute` must match what `to_payload_messages` expects — check `tests/infrastructure/test_backend.py` for the exact dict shape used elsewhere and copy it.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_activity_stream.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_activity_message'`

- [ ] **Step 3: Write minimal implementation**

In `research_team/infrastructure/agent/deep_agent.py`, add below `describe_activity`:

```python
def to_activity_message(message: BaseMessage) -> ActivityMessage | None:
    """A whole message as a provisional note, or None if it cannot be keyed.

    Built from `to_recorded` rather than from a second reading of the message,
    so what streams and what is eventually recorded cannot disagree about kind
    or payload -- that divergence is the failure mode this channel most needs
    to avoid.

    A message with no id is dropped rather than given a synthetic one: the id
    is what the browser accumulates deltas against, and a guessed one would
    splice two messages into one bubble.
    """
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    recorded = to_recorded(message)
    return ActivityMessage(
        message_id=str(message_id),
        kind=recorded.kind,
        payload=recorded.payload,
        is_error=recorded.is_error,
    )
```

Add the import at the top of the module:

```python
from research_team.application.ports import (
    ActivityMessage,
    ActivityReporter,
)
```

(`ActivityReporter` is likely already imported — extend the existing import rather than adding a second one.)

Then replace the reporting block inside the `astream` loop (`deep_agent.py:163-167`):

```python
                if on_activity is not None:
                    for message in final[reported:]:
                        note = to_activity_message(message)
                        if note is not None:
                            on_activity(note)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_activity_stream.py -v`
Expected: 4 passed

- [ ] **Step 5: Confirm nothing else regressed yet**

Run: `uv run pytest tests/infrastructure tests/application -v`
Expected: PASS except `tests/interfaces/test_repl.py` is untouched here; if any REPL test imports through this path and fails on a note object reaching `print`, leave it — Task 4 fixes it. Record which tests fail so Task 4 can confirm it fixed exactly those.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/agent/deep_agent.py tests/infrastructure/test_activity_stream.py
git commit -m "feat: report whole messages as structured activity notes"
```

---

### Task 3: Executor emits prose deltas from a dual-mode stream

**Files:**
- Modify: `research_team/infrastructure/agent/deep_agent.py:155-175` (the `astream` call and loop)
- Test: `tests/infrastructure/test_activity_stream.py` (extend)

**Interfaces:**
- Consumes: `ActivityDelta` (Task 1), `to_activity_message` (Task 2).
- Produces: no new public names. The loop now handles `(mode, chunk)` tuples.

**Context — verified against the pinned versions, do not re-litigate:**

- `create_deep_agent(...)` returns a `CompiledStateGraph` (a `Pregel`) whose `astream` accepts `stream_mode: StreamMode | Sequence[StreamMode]`.
- `stream_mode=["values", "messages"]` yields `(mode, chunk)` **tuples**, interleaved, from one pass.
- For `"messages"`, `chunk` is `(message, metadata)`.
- `metadata["langgraph_node"]` is `"model"` for the main agent — this is the subagent discriminator.
- `message.id` is identical across both channels, so delta/message correlation holds.

**Critical detail:** filter with `isinstance(chunk_message, AIMessage)`, **not** `AIMessageChunk`. `AIMessageChunk` subclasses `AIMessage`, so the broad test covers both — and a non-streaming model (including `ToolAwareFakeChatModel`, which every existing test uses) delivers one whole `AIMessage` on this channel rather than a series of chunks. Testing for `AIMessageChunk` alone yields zero deltas under every test fixture in this repo.

**Critical detail:** the `values` branch must keep driving `final` and `reported` exactly as before. `state` (used after the loop for `__interrupt__`) is only assigned from `values` chunks. Do not let a `messages` chunk overwrite it.

- [ ] **Step 1: Write the failing test**

Append to `tests/infrastructure/test_activity_stream.py`:

```python
async def test_prose_is_reported_as_a_delta(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(StartSession(system_prompt="be brief", model_name="fake"))
    model = ToolAwareFakeChatModel(
        responses=[AIMessage(content="the streamed reply", id="a1")]
    )
    executor = DeepAgentTurnExecutor(model)

    seen: list = []
    await executor.execute(
        session,
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="be brief",
        on_activity=seen.append,
    )

    deltas = [n for n in seen if isinstance(n, ActivityDelta)]
    assert deltas, "expected at least one prose delta"
    assert all(d.message_id == "a1" for d in deltas)
    assert "".join(d.text for d in deltas) == "the streamed reply"


async def test_the_durable_record_is_identical_with_and_without_a_reporter(
    aggregates, session_id
):
    """The stream must never be an input to the log."""

    async def run(reporter):
        session = aggregates.create_new(session_id)
        session.execute(StartSession(system_prompt="be brief", model_name="fake"))
        model = ToolAwareFakeChatModel(
            responses=[AIMessage(content="the reply", id="a1")]
        )
        executor = DeepAgentTurnExecutor(model)
        return await executor.execute(
            session,
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="be brief",
            on_activity=reporter,
        )

    with_reporter = await run([].append)
    without = await run(None)

    assert with_reporter.reply_text == without.reply_text
    assert [m.payload for m in with_reporter.messages] == [
        m.payload for m in without.messages
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_activity_stream.py::test_prose_is_reported_as_a_delta -v`
Expected: FAIL — `assert deltas` fails, because only `values` is streamed today so no delta is ever produced.

- [ ] **Step 3: Write minimal implementation**

In `_invoke`, change the stream call and loop:

```python
        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        payload: Any = {"messages": messages}
        while True:
            state: dict[str, Any] = {}
            async for mode, chunk in agent.astream(
                payload,
                config=run_config,
                # Two modes from one pass. `values` is what the durable record
                # is built from, exactly as before; `messages` exists only to
                # let prose reach a waiting human before the turn commits. One
                # pass rather than two is what keeps them from disagreeing.
                stream_mode=["values", "messages"],
            ):
                if mode == "values":
                    state = chunk
                    final = state.get("messages", final)
                    if on_activity is not None:
                        for message in final[reported:]:
                            note = to_activity_message(message)
                            if note is not None:
                                on_activity(note)
                    reported = len(final)
                elif mode == "messages" and on_activity is not None:
                    delta = to_activity_delta(chunk)
                    if delta is not None:
                        on_activity(delta)
            interrupts = state.get("__interrupt__")
            if not interrupts:
                return final
            decisions = await self._settle(session, interrupts)
            payload = Command(resume={"decisions": decisions})
```

Add the converter beside `to_activity_message`:

```python
MAIN_AGENT_NODE = "model"
"""The graph node the top-level agent's model call runs under.

Subagents stream on the same channel. Without this discriminator a subagent's
internal reasoning would render as the main agent's answer to the user.
"""


def to_activity_delta(chunk: Any) -> ActivityDelta | None:
    """A prose delta from a `messages`-mode chunk, or None if it is not one.

    Returns None for tool calls, for subagent chunks, and for anything without
    text -- this channel carries only what a person is waiting to read.

    The type test is `AIMessage`, which covers `AIMessageChunk` because it
    subclasses it. Testing for the chunk type alone would report nothing at
    all from a non-streaming model, which delivers one whole message here.
    """
    try:
        message, metadata = chunk
    except (TypeError, ValueError):
        return None
    if metadata.get("langgraph_node") != MAIN_AGENT_NODE:
        return None
    if not isinstance(message, AIMessage):
        return None
    if getattr(message, "tool_calls", None):
        return None
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    text = message.text() if callable(getattr(message, "text", None)) else message.content
    if not isinstance(text, str) or not text:
        return None
    return ActivityDelta(message_id=str(message_id), text=text)
```

Import `AIMessage` and `ActivityDelta` at the top of the module (extend the existing import lines).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_activity_stream.py -v`
Expected: 6 passed

- [ ] **Step 5: Verify the interrupt/resume path still works**

The `values`/`state` split is the risky part — `state` must still carry `__interrupt__`.

Run: `uv run pytest tests/integration/test_approval.py tests/infrastructure/test_resume_loop.py -v`
Expected: PASS. If `__interrupt__` is not found, the `state = chunk` assignment is being clobbered by a `messages` chunk — confirm it is inside the `values` branch only.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/agent/deep_agent.py tests/infrastructure/test_activity_stream.py
git commit -m "feat: stream assistant prose as deltas alongside whole messages"
```

---

### Task 4: The REPL formats notes back down to lines

**Files:**
- Modify: `research_team/interfaces/cli/repl.py:306` (the `on_activity=print` call site)
- Test: `tests/interfaces/test_repl.py` (extend)

**Interfaces:**
- Consumes: `ActivityMessage`, `ActivityDelta` (Task 1), `describe_activity` (existing, unchanged).
- Produces: `format_activity(note) -> str | None` in `repl.py`.

**Context:** `repl.py:306` passes `on_activity=print`, which now receives note objects and would print `ActivityMessage(message_id='a1', ...)` into the transcript. The terminal output must stay byte-identical to today.

`describe_activity` in `deep_agent.py` takes a *langchain message*, not a note — it cannot be reused directly, because the REPL (an `interfaces` module) may import `infrastructure`, but the note only carries an opaque `payload` dict. Implement the formatting against the payload instead, matching `describe_activity`'s output exactly:

- Assistant message with `tool_calls` → `"· name(first_arg), name(first_arg)"`
- Tool message → `"  ↳ " + first line, truncated to 70 chars`
- Anything else (plain assistant prose, deltas) → `None`, printing nothing.

The last rule is what keeps output identical: `describe_activity` returns `None` for prose today, so the terminal has never shown it mid-turn.

- [ ] **Step 1: Write the failing test**

Append to `tests/interfaces/test_repl.py`:

```python
from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.interfaces.cli.repl import format_activity


def test_tool_calls_format_as_a_bullet_line():
    note = ActivityMessage(
        message_id="a1",
        kind="assistant",
        payload={
            "tool_calls": [{"name": "read_file", "args": {"file_path": "a.py"}}]
        },
    )
    assert format_activity(note) == "· read_file(a.py)"


def test_tool_results_format_as_an_indented_first_line():
    note = ActivityMessage(
        message_id="t1",
        kind="tool",
        payload={"content": "found 3 matches\nline two"},
    )
    assert format_activity(note) == "  ↳ found 3 matches"


def test_plain_prose_prints_nothing():
    note = ActivityMessage(
        message_id="a1", kind="assistant", payload={"content": "hello"}
    )
    assert format_activity(note) is None


def test_deltas_print_nothing():
    """The terminal shows the reply when the turn completes, not token by token."""
    assert format_activity(ActivityDelta(message_id="a1", text="hel")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/interfaces/test_repl.py -k activity -v`
Expected: FAIL with `ImportError: cannot import name 'format_activity'`

- [ ] **Step 3: Write minimal implementation**

Add to `research_team/interfaces/cli/repl.py`:

```python
ACTIVITY_RESULT_WIDTH = 70
"""Matches what the terminal has always shown for a tool result."""


def format_activity(note: ActivityNote) -> str | None:
    """One terminal line for a note, or None if it is not worth showing.

    Deliberately silent for prose and deltas: the transcript prints the reply
    when the turn completes, and echoing it token by token into a scrolling
    terminal would be noise. This is the terminal's presenter for the same
    notes the web UI renders as content.
    """
    if isinstance(note, ActivityDelta):
        return None
    calls = note.payload.get("tool_calls") or []
    if calls:
        return "· " + ", ".join(
            f"{call.get('name', '?')}({_first_arg(call.get('args') or {})})"
            for call in calls
        )
    if note.kind == "tool":
        lines = str(note.payload.get("content", "")).strip().splitlines()
        return f"  ↳ {lines[0][:ACTIVITY_RESULT_WIDTH]}" if lines else None
    return None


def _first_arg(args: dict) -> str:
    for key in ("file_path", "path", "pattern", "command"):
        if key in args:
            return str(args[key])
    return ""
```

Import `ActivityDelta`, `ActivityNote` from `research_team.application.ports`.

Then change the call site at `repl.py:306`:

```python
                output = await handle_command(repl, line, on_activity=_print_activity)
```

and add near `format_activity`:

```python
def _print_activity(note: ActivityNote) -> None:
    line = format_activity(note)
    if line is not None:
        print(line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_repl.py -v`
Expected: all pass, including the tests noted as failing at the end of Task 2.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all pass. The web layer still passes no reporter, so nothing there has changed yet.

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces/cli/repl.py tests/interfaces/test_repl.py
git commit -m "feat: format activity notes for the terminal"
```

---

### Task 5: The buffer — `TurnActivity`

**Files:**
- Create: `research_team/interfaces/web/activity.py`
- Modify: `research_team/interfaces/web/__init__.py`
- Test: `tests/interfaces/test_turn_activity.py` (create)

**Interfaces:**
- Consumes: `ActivityMessage`, `ActivityDelta`, `ActivityNote`, `ActivityReporter` (Task 1).
- Produces: class `TurnActivity` with `reporter(session_id) -> ActivityReporter`, `begin(session_id) -> None`, `current(session_id) -> list[dict]`, `discarded(session_id) -> list[dict]`, `settle(session_id, *, committed: bool) -> None`, `listen() -> asyncio.Queue`, `stop_listening(queue) -> None`. Task 6 wires all of these.

**Context:** Mirror `research_team/interfaces/web/approvals.py` — same `listen`/`stop_listening`/`_announce` broadcast shape, same per-session dict, same unbounded queues. Read it before starting.

Frame type constant: `ACTIVITY = "TurnActivity"`. PascalCase to match the neighbouring frame types, but **it is not a domain event and must never become one.**

Buffer entry shape (what `current()` returns and what rides the wire):

```python
{
    "message_id": "a1",
    "kind": "assistant",
    "payload": {...},
    "is_error": False,
    "text": "accumulated prose so far",  # deltas only; "" for whole messages
}
```

A delta for an unseen `message_id` creates a text-only entry (`kind: "assistant"`, empty `payload`). A whole message for an id that already has accumulated text **replaces** the entry — the whole message is authoritative over the deltas that preceded it.

- [ ] **Step 1: Write the failing test**

Create `tests/interfaces/test_turn_activity.py`:

```python
"""The in-flight buffer that lets a browser join a turn late."""

from uuid import uuid4

import pytest

from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.interfaces.web.activity import ACTIVITY, TurnActivity


@pytest.fixture
def session_id():
    return uuid4()


def test_a_whole_message_lands_in_the_buffer(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    assert [e["message_id"] for e in activity.current(session_id)] == ["a1"]


def test_deltas_accumulate_onto_one_entry(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityDelta(message_id="a1", text="hel"))
    report(ActivityDelta(message_id="a1", text="lo"))
    entries = activity.current(session_id)
    assert len(entries) == 1
    assert entries[0]["text"] == "hello"


def test_a_whole_message_supersedes_its_deltas(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityDelta(message_id="a1", text="par"))
    report(ActivityMessage(message_id="a1", kind="assistant", payload={"content": "partial"}))
    entries = activity.current(session_id)
    assert len(entries) == 1
    assert entries[0]["payload"] == {"content": "partial"}


def test_entries_keep_arrival_order(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    report(ActivityMessage(message_id="t1", kind="tool", payload={}))
    report(ActivityDelta(message_id="a1", text="more"))
    assert [e["message_id"] for e in activity.current(session_id)] == ["a1", "t1"]


def test_beginning_a_turn_clears_both_slots(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    activity.settle(session_id, committed=False)
    activity.begin(session_id)
    assert activity.current(session_id) == []
    assert activity.discarded(session_id) == []


def test_committing_drops_the_buffer(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    activity.settle(session_id, committed=True)
    assert activity.current(session_id) == []
    assert activity.discarded(session_id) == []


def test_failing_moves_the_buffer_to_discarded(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    activity.settle(session_id, committed=False)
    assert activity.current(session_id) == []
    assert [e["message_id"] for e in activity.discarded(session_id)] == ["a1"]


def test_sessions_do_not_share_a_buffer():
    activity = TurnActivity()
    one, two = uuid4(), uuid4()
    activity.begin(one)
    activity.begin(two)
    activity.reporter(one)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    assert activity.current(two) == []


async def test_listeners_receive_frames(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    frame = queue.get_nowait()
    assert frame["type"] == ACTIVITY
    assert frame["session_id"] == str(session_id)
    assert frame["message_id"] == "a1"


async def test_stop_listening_ends_delivery(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.stop_listening(queue)
    activity.reporter(session_id)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    assert queue.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/interfaces/test_turn_activity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'research_team.interfaces.web.activity'`

- [ ] **Step 3: Write minimal implementation**

Create `research_team/interfaces/web/activity.py`:

```python
"""What a turn is doing, before the log has anything to say about it.

A turn is atomic: every event appends in one write at the end, so the live
feed -- which reads the log -- has nothing to show while a turn runs. This is
the other channel. It carries provisional content, holds it for exactly as
long as the turn lasts, and is never the source of anything durable.

The buffer is not an optimisation. These frames carry no feed position, so
`Last-Event-ID` cannot replay them, and an SSE connection drops routinely --
sleep, a network change, a proxy closing an idle socket. Log events already
survive that. Without somewhere to catch up from, provisional content would
not, and a lossy reconnect would look exactly like a slow model: a frozen
pane either way.

Shaped deliberately like `approvals.py`, which solves the same problem for the
same reason.
"""

import asyncio
from typing import Any
from uuid import UUID

from research_team.application.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityNote,
    ActivityReporter,
)

ACTIVITY = "TurnActivity"
"""The frame type on the live feed.

PascalCase like the event names beside it, because the browser switches on one
`type` field for everything it receives. It is *not* a domain event and must
never become one -- the log has no such entry, and that is the point.
"""


class TurnActivity:
    """Provisional turn content, keyed by session, plus the feed that carries it."""

    def __init__(self) -> None:
        self._running: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._discarded: dict[UUID, dict[str, dict[str, Any]]] = {}
        self._listeners: set[asyncio.Queue] = set()

    # ---------------- what the turn drives ----------------

    def begin(self, session_id: UUID) -> None:
        """Start a turn's buffer, dropping whatever the last one left behind."""
        self._running[session_id] = {}
        self._discarded.pop(session_id, None)

    def reporter(self, session_id: UUID) -> ActivityReporter:
        """An `ActivityReporter` that buffers and broadcasts for one session."""

        def report(note: ActivityNote) -> None:
            self._record(session_id, note)

        return report

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        """End the turn's buffer.

        A committed turn's content is now on the log, which is authoritative --
        so the provisional copy is dropped rather than reconciled. A turn that
        failed or was cancelled recorded nothing, so what streamed is the only
        trace of it that exists; it moves aside rather than vanishing, and the
        UI offers it as explicitly discarded.
        """
        buffered = self._running.pop(session_id, None)
        if committed or not buffered:
            self._discarded.pop(session_id, None)
            return
        self._discarded[session_id] = buffered

    # ---------------- what the HTTP layer drives ----------------

    def current(self, session_id: UUID) -> list[dict[str, Any]]:
        """The running turn's content so far, for a tab that arrived mid-turn."""
        return list(self._running.get(session_id, {}).values())

    def discarded(self, session_id: UUID) -> list[dict[str, Any]]:
        """What the last failed turn streamed before it was thrown away."""
        return list(self._discarded.get(session_id, {}).values())

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to activity frames.

        Unbounded, matching the approvals feed: a dropped frame leaves a gap in
        rendered prose with nothing to reconcile it.

        Not seeded with the running buffer, unlike approvals -- a subscriber
        gets that from the catch-up route, which it must call anyway to learn
        about a turn that started before it connected.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    # ---------------- internals ----------------

    def _record(self, session_id: UUID, note: ActivityNote) -> None:
        entries = self._running.setdefault(session_id, {})
        if isinstance(note, ActivityMessage):
            entry = {
                "message_id": note.message_id,
                "kind": note.kind,
                "payload": note.payload,
                "is_error": note.is_error,
                "text": "",
            }
            # Replaces any accumulated deltas: the whole message is what the
            # log will record, so it wins over the pieces that preceded it.
            entries[note.message_id] = entry
        else:
            entry = entries.get(note.message_id)
            if entry is None:
                entry = {
                    "message_id": note.message_id,
                    "kind": "assistant",
                    "payload": {},
                    "is_error": False,
                    "text": "",
                }
                entries[note.message_id] = entry
            entry["text"] = entry["text"] + note.text
        self._announce({"type": ACTIVITY, "session_id": str(session_id), **entry})

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
```

Then export it from `research_team/interfaces/web/__init__.py` alongside `WebApprovals` and `create_app`, following the existing style.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_turn_activity.py -v`
Expected: 10 passed

- [ ] **Step 5: Confirm layering**

Run: `uv run pytest tests/test_architecture.py -v`
Expected: PASS — `interfaces` importing `application` points inward.

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces/web/activity.py research_team/interfaces/web/__init__.py tests/interfaces/test_turn_activity.py
git commit -m "feat: buffer in-flight turn activity for the web UI"
```

---

### Task 6: Wire the channel through HTTP

**Files:**
- Modify: `research_team/interfaces/web/app.py` (signature ~`:69`, turn route `:180-208`, new route near `:224`, `_sse` `:309-389`)
- Modify: `web.py`
- Test: `tests/interfaces/test_web.py` (extend)

**Interfaces:**
- Consumes: `TurnActivity` and all its methods (Task 5).
- Produces: `create_app(..., activity: TurnActivity | None = None)`; route `GET /api/sessions/{id}/turns/current/activity` returning `{"running": [...], "discarded": [...]}`.

**Context:** `create_app` already takes `approvals: WebApprovals | None = None` — follow that shape exactly so tests can build an app without activity wired.

`TurnSupervisor.run(session_id, user_input, on_activity)` already accepts a reporter (`turn_supervisor.py:96-101`); the web route at `app.py:184` simply calls `turns.run(session_id, body.input)` without one.

`settle(committed=...)` must be called on **every** exit path from the turn route — success, `TurnCancelled`, `OptimisticLockError`, and any other exception. Use `try/except/else` or a flag; a `finally` that always passes `committed=False` would discard a successful turn's buffer into the discarded slot.

`TurnAlreadyRunning` is raised *before* the turn starts, so it must **not** call `settle` — doing so would wipe the buffer of the turn that is legitimately running.

- [ ] **Step 1: Write the failing test**

Append to `tests/interfaces/test_web.py`:

```python
from research_team.interfaces.web import TurnActivity


@pytest.fixture
async def activity_app(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    activity = TurnActivity()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        activity=activity,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client, activity
    await application.close()


async def test_activity_catch_up_route_is_empty_before_a_turn(activity_app):
    _, client, _ = activity_app
    session_id = await _new_session(client)
    body = (
        await client.get(f"/api/sessions/{session_id}/turns/current/activity")
    ).json()
    assert body == {"running": [], "discarded": []}


async def test_a_turn_reports_activity_into_the_buffer(activity_app):
    """The buffer fills during the turn; it is dropped once the turn commits."""
    _, client, activity = activity_app
    session_id = await _new_session(client)
    response = await client.post(
        f"/api/sessions/{session_id}/turns", json={"input": "hi"}
    )
    assert response.status_code == 200
    # Committed, so the log is authoritative and the buffer is gone.
    body = (
        await client.get(f"/api/sessions/{session_id}/turns/current/activity")
    ).json()
    assert body["running"] == []


async def test_activity_frames_ride_the_stream_without_an_id(activity_app):
    _, client, activity = activity_app
    session_id = await _new_session(client)

    frames = []

    async def read():
        async with client.stream("GET", "/api/stream") as response:
            async for line in response.aiter_lines():
                frames.append(line)
                if len([f for f in frames if f.startswith("data:")]) >= 1:
                    return

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.1)
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    await asyncio.wait_for(reader, timeout=5)

    data = [f for f in frames if f.startswith("data:")]
    payload = json.loads(data[0][len("data:"):].strip())
    assert payload["type"] == "TurnActivity"
    assert payload["message_id"] == "a1"
    # Not a log entry: no SSE id frame precedes it.
    assert not any(f.startswith("id:") for f in frames)
```

Import `ActivityMessage` from `research_team.application.ports` at the top of the test module.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/interfaces/test_web.py -k activity -v`
Expected: FAIL — `create_app()` got an unexpected keyword argument `activity`

- [ ] **Step 3: Write minimal implementation**

In `app.py`, extend the signature:

```python
def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
) -> FastAPI:
```

Replace the body of `run_turn`:

```python
    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        try:
            outcome = await turns.run(session_id, body.input)
        except TurnAlreadyRunning as error:
            ...
```

with a version that opens and settles the buffer. Note the ordering: `begin` happens after the `TurnAlreadyRunning` check would have fired, so a refused second turn never touches the running turn's buffer.

```python
    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        if turns.is_running(session_id):
            # Checked here as well as in the supervisor so that a refused
            # second turn cannot reach `begin` and wipe the buffer of the turn
            # that is legitimately running.
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            )
        reporter = None
        if activity is not None:
            activity.begin(session_id)
            reporter = activity.reporter(session_id)
        try:
            outcome = await turns.run(session_id, body.input, reporter)
        except TurnAlreadyRunning as error:
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            if activity is not None:
                activity.settle(session_id, committed=False)
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            if activity is not None:
                activity.settle(session_id, committed=False)
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        except BaseException:
            if activity is not None:
                activity.settle(session_id, committed=False)
            raise
        else:
            if activity is not None:
                activity.settle(session_id, committed=True)
        return {
            "reply": outcome.reply,
            "turn_index": outcome.turn_index,
            "from_index": outcome.from_index,
            "to_index": outcome.to_index,
        }
```

Add the catch-up route beside `current_turn`:

```python
    @app.get("/api/sessions/{session_id}/turns/current/activity")
    async def current_activity(session_id: UUID):
        """What the running turn has produced so far, and what the last failed
        one threw away.

        The live feed announces each note as it arrives, but a tab that opened
        mid-turn never saw those frames -- and unlike log events they carry no
        position, so `Last-Event-ID` cannot replay them. This is how it
        catches up, exactly as `/approvals` is for a parked approval.
        """
        await _load(session_id)
        if activity is None:
            return {"running": [], "discarded": []}
        return {
            "running": activity.current(session_id),
            "discarded": activity.discarded(session_id),
        }
```

Pass `activity` into `_sse`:

```python
        return StreamingResponse(
            _sse(request, feed, resume_from, approvals, activity),
            ...
        )
```

Extend `_sse`'s signature and add a third pump. In the loop, treat `"activity"` like `"approval"` — a frame with no id:

```python
    if activity is not None:
        watching = activity.listen()

        async def pump_activity() -> None:
            while True:
                await queue.put(("activity", await watching.get()))

        pumps.append(asyncio.create_task(pump_activity()))
```

and in the dispatch:

```python
            if kind in ("approval", "activity"):
                yield f"data: {json.dumps(item)}\n\n"
                continue
```

Clean up `watching` in the `finally` alongside `listening`.

Update `_sse`'s docstring to mention that activity frames ride the same connection for the same reason approvals do.

Finally, in `web.py`, construct and pass it:

```python
    approvals = WebApprovals()
    activity = TurnActivity()
    application = build_application(approvals=approvals)
    ...
        create_app(
            application.service,
            application.feed,
            application.turns,
            lifespan,
            approvals=approvals,
            activity=activity,
        ),
```

Import `TurnActivity` from `research_team.interfaces.web`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_web.py -v`
Expected: all pass, including the three new ones.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces/web/app.py web.py tests/interfaces/test_web.py
git commit -m "feat: stream turn activity over SSE with a catch-up route"
```

---

### Task 7: The frontend renders provisional content

**Files:**
- Modify: `research_team/interfaces/web/static/app.js` (state ~`:333`, session load ~`:645`, `onStreamEvent` ~`:1902`, timeline render)
- Modify: `research_team/interfaces/web/static/style.css`
- Test: manual — this repo has no JS test harness. Verification is by running the app.

**Interfaces:**
- Consumes: the `TurnActivity` frame shape from Task 5 (`{type, session_id, message_id, kind, payload, is_error, text}`) and the catch-up route from Task 6.
- Produces: no names other tasks depend on.

**Context:** `onStreamEvent` (`app.js:1902`) already routes approval frames out before index handling:

```js
  if (payload.type === 'ApprovalRequested' || payload.type === 'ApprovalSettled') {
    onApprovalFrame(payload);
    return;
  }
```

Activity frames need the same treatment, for the same reason — they are not log entries and must not be given a synthesised `index`.

The stale comment at `app.js:1946` (`// No narration here on purpose...`) describes the behaviour this change replaces. Replace it rather than leaving it to contradict the code.

- [ ] **Step 1: Add state**

Next to `state.approvals` (`app.js:333`):

```js
  activity: { order: [], byId: {} },  // provisional content for the running turn
  discarded: {},                      // failed turn index -> provisional content
```

Reset both where `state.approvals` is reset (`app.js:422`).

- [ ] **Step 2: Route the frame**

In `onStreamEvent`, immediately after the approval branch:

```js
  if (payload.type === 'TurnActivity') {
    onActivityFrame(payload);
    return;
  }
```

Add the handler beside `onApprovalFrame`:

```js
// Provisional turn content. Not a log entry -- it carries no index, and the
// events it previews may never be appended at all if the turn fails.
function onActivityFrame(payload) {
  if (state.route.name !== 'session' || payload.session_id !== state.sessionId) return;
  putActivity(payload);
  renderActivity();
}

function putActivity(entry) {
  const id = entry.message_id;
  if (!state.activity.byId[id]) state.activity.order.push(id);
  state.activity.byId[id] = entry;
}
```

The server already accumulates delta text, so the browser stores whole entries rather than appending — one accumulator, on the side that has to answer the catch-up route anyway.

- [ ] **Step 3: Render provisional bubbles**

Add a render function that draws `state.activity.order` below the timeline while `state.turnRunning`, each entry marked provisional. Use `contentText(entry.payload.content)` for a whole message and `entry.text` for accumulated prose, preferring `text` when `payload` is empty:

```js
function renderActivity() {
  if (!sessionEls || !sessionEls.activity) return;
  const box = sessionEls.activity;
  clear(box);
  if (!state.turnRunning || !state.activity.order.length) return;
  state.activity.order.forEach(function (id) {
    const entry = state.activity.byId[id];
    if (entry) box.appendChild(renderProvisional(entry));
  });
}

function renderProvisional(entry) {
  const body = entry.text || contentText(entry.payload && entry.payload.content);
  return h('div', { class: 'provisional provisional-' + entry.kind }, [
    h('div', { class: 'provisional-tag', text: 'in progress — not yet recorded' }),
    h('div', { class: 'provisional-body', text: body })
  ]);
}
```

Add a `data-slot="activity"` element to the session template in `index.html`, below the timeline slot, and wire it into `sessionEls` next to `approvals` (`app.js:614`).

- [ ] **Step 4: Reconcile on turn end**

Where `TurnCompleted` / `TurnFailed` are handled, before the existing logic:

```js
  if (isTurnEnd(payload.type)) {
    if (payload.type === 'TurnFailed') {
      // The turn recorded nothing but this marker, so what streamed is the
      // only trace of it. Kept behind a disclosure rather than dropped --
      // ephemeral, and gone on reload, which the label says plainly.
      state.discarded[index] = state.activity.order
        .map(function (id) { return state.activity.byId[id]; })
        .filter(Boolean);
    }
    state.activity = { order: [], byId: {} };
    renderActivity();
  }
```

Render `state.discarded[index]` as a `<details>` on that timeline row, summary `discarded — not recorded`.

- [ ] **Step 5: Catch up on load**

Beside the mid-approval refetch (`app.js:645`):

```js
    // A tab that (re)loads mid-turn never saw the activity frames, and they
    // carry no position for Last-Event-ID to resume from.
    api.get('/api/sessions/' + encodeURIComponent(id) + '/turns/current/activity')
      .then(function (body) {
        (body.running || []).forEach(putActivity);
        renderActivity();
      })
      .catch(function () { /* catch-up is best-effort */ });
```

- [ ] **Step 6: Replace the stale comment**

Delete the `// No narration here on purpose...` comment at `app.js:1946` and put in its place:

```js
  // Log frames and activity frames are different channels on purpose: this one
  // is the durable record, arriving in a burst when the turn commits, while
  // provisional content streams in above via onActivityFrame.
```

- [ ] **Step 7: Style it**

In `style.css`, make provisional content visibly distinct from committed events — reduced opacity plus a left border is enough, following whatever the approval card already does. Add a `.discarded` style with strikethrough or muted text.

- [ ] **Step 8: Verify by running the app**

Run: `uv run python web.py`

Check, in a browser:
1. Start a turn — content appears while it runs, marked provisional.
2. It is replaced by real timeline events when the turn completes (no duplicates).
3. Open a second tab mid-turn — it catches up rather than showing an empty pane.
4. Cancel a turn — content moves to a `discarded` disclosure on the `TurnFailed` row.

- [ ] **Step 9: Commit**

```bash
git add research_team/interfaces/web/static/
git commit -m "feat: render streaming turn activity in the web UI"
```

---

### Task 8: The atomicity regression guard

**Files:**
- Modify: `tests/integration/test_turn_visibility.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: nothing.

**Context:** This is the test that protects the property this whole design bends around. Read `tests/integration/test_turn_visibility.py` first — it already tests what is visible during a turn, and this belongs beside it.

The assertion: while a turn is running and streaming activity, the session's event count does not change. It changes exactly once, at commit.

- [ ] **Step 1: Write the test**

```python
async def test_activity_streams_without_appending_to_the_log(db_path, fake_model):
    """The whole design in one assertion: content streams, the log does not move.

    If this fails, someone has made the turn incremental -- which would mean a
    failed turn can no longer be discarded whole.
    """
    application = await _started(model=fake_model, db_path=db_path)
    activity = TurnActivity()
    api = create_app(
        application.service, application.feed, application.turns, activity=activity
    )
    session_id = ...  # create via the client, as the neighbouring tests do

    counts = []

    def counting_reporter(note):
        events = asyncio.run_coroutine_threadsafe(...)  # see note below
        ...

    # Simpler and sufficient: record the event count each time a note arrives,
    # by wrapping the reporter the app would use.
    original = activity.reporter
    observed = []

    def wrapped(sid):
        report = original(sid)

        def reporting(note):
            observed.append(note)
            report(note)

        return reporting

    activity.reporter = wrapped

    before = len(await application.service.history(session_id))
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    after = len(await application.service.history(session_id))

    assert observed, "the turn reported no activity at all"
    assert after > before, "the turn appended nothing"
    # The buffer is dropped on commit, so nothing provisional survives.
    assert activity.current(session_id) == []
    await application.close()
```

Rewrite the sketch above into the file's existing style — reuse its client fixture and session helper rather than the placeholders. The load-bearing assertions are the last three. If checking the count *during* the turn proves awkward with the fake model (which completes in one pass), assert instead that `to_index - from_index` equals the number of events appended and that no `TurnCompleted` exists in the log at the moment the first note is observed.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_turn_visibility.py -v`
Expected: PASS

- [ ] **Step 3: Prove it can fail**

Temporarily add a `await self._repository.save(aggregate)` in the middle of `_run_turn`, re-run, confirm the test fails, then revert.

- [ ] **Step 4: Full suite and lint**

Run: `uv run pytest`
Expected: all pass

Run: `uv run ruff check`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_turn_visibility.py
git commit -m "test: guard turn atomicity against the activity channel"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Port — `ActivityMessage` / `ActivityDelta` / `ActivityNote` | 1 |
| Executor — `values` unchanged, whole messages | 2 |
| Executor — dual mode, prose deltas, subagent filter | 3 |
| REPL — formatter, output unchanged, deltas dropped | 4 |
| Buffer — `TurnActivity`, lifecycle, broadcast | 5 |
| HTTP — reporter wiring, catch-up route, SSE pump | 6 |
| Frontend — accumulator, reconciliation, discarded disclosure | 7 |
| Testing — atomicity guard | 8 |
| Testing — record identical with/without reporter | 3 |
| Testing — deltas only for main-agent prose | 3 |
| Testing — whole message supersedes deltas | 5 |
| Testing — frames carry no `id` | 6 |
| Testing — settle committed/failed | 5 |
| Testing — REPL output unchanged | 4 |
| Error handling — missing `message_id` dropped | 2, 3 |
| Error handling — no listeners is normal | 5 |
| Error handling — buffer bounded by one turn | 5 |

**Gap found and closed:** the spec's *Error handling* says "reporter raises must never fail a turn," and no task implemented it. Add to **Task 2, Step 3** — wrap the `on_activity(note)` call sites in `_invoke`:

```python
def _report(on_activity: ActivityReporter | None, note: ActivityNote) -> None:
    """Never let a progress channel fail a turn.

    A minute of model work is not worth discarding because a browser feed
    raised. The turn is the valuable thing here; this channel is a courtesy.
    """
    if on_activity is None:
        return
    try:
        on_activity(note)
    except Exception:  # noqa: BLE001 -- a broken feed must not fail a turn
        logger.warning("activity reporter raised; dropping note", exc_info=True)
```

Route both the whole-message and delta calls through `_report`, and add a test in Task 3, Step 1:

```python
async def test_a_raising_reporter_does_not_fail_the_turn(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(StartSession(system_prompt="be brief", model_name="fake"))
    model = ToolAwareFakeChatModel(responses=[AIMessage(content="ok", id="a1")])

    def boom(note):
        raise RuntimeError("feed exploded")

    result = await DeepAgentTurnExecutor(model).execute(
        session,
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="be brief",
        on_activity=boom,
    )
    assert result.reply_text == "ok"
```

**Placeholder scan:** Task 8's test body is a sketch with `...` in it, flagged inline as needing adaptation to the file's fixtures. That is deliberate — the file's client fixture must be read first — and the required assertions are stated exactly. Everything else contains literal code.

**Type consistency:** `ActivityMessage` / `ActivityDelta` / `ActivityNote` / `ActivityReporter` used identically in Tasks 1–7. `to_activity_message` (Task 2) and `to_activity_delta` (Task 3) named consistently. `begin` / `reporter` / `current` / `discarded` / `settle` / `listen` / `stop_listening` (Task 5) match their call sites in Task 6. Frame type `"TurnActivity"` matches between Task 5's `ACTIVITY` constant, Task 6's test, and Task 7's router. Buffer entry keys (`message_id`, `kind`, `payload`, `is_error`, `text`) match between Task 5's `_record` and Task 7's `renderProvisional`.
