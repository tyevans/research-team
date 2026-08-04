# SearXNG Tool with Human-in-the-Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent a SearXNG web search tool, gated by per-tool human-in-the-loop approval whose autonomy level (`auto` / `ask` / `deny`) is adjustable at any time.

**Architecture:** A framework-free `AutonomyPolicy` in the application layer is consulted per tool call through deepagents' `interrupt_on` `when` predicate. Interrupted calls surface to a new `ApprovalPort`; the turn executor gains a per-turn `MemorySaver` and a resume loop that answers each interrupt with a decision and resumes the graph. Every decision is recorded on the session's event stream.

**Tech Stack:** Python 3.13, deepagents, langchain/langgraph, eventsource-py, pytest, Hypothesis, mutmut, httpx.

**Spec:** `docs/superpowers/specs/2026-08-03-searxng-tool-with-hitl-design.md`

## Global Constraints

- **The dependency rule is a test.** `tests/test_architecture.py` asserts that `domain` and `application` may import no framework except `eventsource`. `application/autonomy.py` and the new port types must import **no** langchain, langgraph, or deepagents. Any closure that touches langchain types lives in `infrastructure`.
- **Layers:** innermost first — `domain`, `application`, `infrastructure`, `interfaces`. A layer may import itself and anything before it, never after.
- **Events are append-only.** Any new event needs a case in `tests/infrastructure/test_schema_evolution.py`. Adding a field to an existing event requires a default meaning what its absence meant. See the docstring at the top of `research_team/domain/events.py`.
- **`config.py` is the only module that reads the environment.** Tests configure by passing arguments, never by setting variables.
- **Line length 95.** Ruff with `select = ["E", "F", "I", "UP", "B", "SIM", "RUF", "C4", "BLE"]`. Every broad `except` needs a `noqa` with a reason — BLE is enabled precisely so those comments stay load-bearing.
- **Tests are async by default** (`asyncio_mode = "auto"`). The `live` marker is deselected by default via `addopts = "-m 'not live'"`.
- **Run tests with `uv run pytest`.** Run a single test with `uv run pytest path::name -v`.
- **Decision vocabulary is langchain's, not ours:** `"approve"`, `"edit"`, `"reject"`, `"respond"`. Do not invent `"accept"`.
- **Commit after every task.** Conventional commit prefixes (`feat:`, `test:`, `docs:`, `chore:`, `refactor:`).

## Verified library contract

These were confirmed against the installed versions. Do not re-derive them; do not assume anything beyond them.

```python
# create_deep_agent accepts both of these; the codebase currently passes neither.
create_deep_agent(
    model=..., tools=[...], interrupt_on={...}, backend=..., checkpointer=...
)

# interrupt_on: dict[str, bool | InterruptOnConfig]
class InterruptOnConfig(TypedDict):
    allowed_decisions: list[Literal["approve", "edit", "reject", "respond"]]
    description: NotRequired[str | Callable]
    args_schema: NotRequired[dict]
    when: NotRequired[Callable[[ToolCallRequest], bool]]

# The interrupt payload the graph emits (one interrupt per AI message,
# carrying ALL of that message's interrupted calls in parallel lists):
{
    "action_requests": [{"name": str, "args": dict, "description": str}, ...],
    "review_configs": [{"action_name": str, "allowed_decisions": [...]}, ...],
}

# Resume. len(decisions) MUST equal the number of interrupted calls or
# the middleware raises ValueError.
Command(resume={"decisions": [
    {"type": "approve"},
    {"type": "edit", "edited_action": {"name": str, "args": dict}},
    {"type": "reject", "message": str},      # message optional
    {"type": "respond", "message": str},
]})
```

**A checkpointer is mandatory.** Verified: `interrupt()` with `checkpointer=None` halts and returns `__interrupt__` in the state, but `Command(resume=...)` then raises `RuntimeError: Cannot use Command(resume=...) without checkpointer`. With `MemorySaver` it resumes correctly.

## File Structure

**Create:**
- `research_team/application/autonomy.py` — `Level`, `AutonomyPolicy`, `GATED_TOOLS`. Framework-free.
- `research_team/infrastructure/agent/search.py` — the SearXNG tool and its result formatting.
- `research_team/infrastructure/agent/approval.py` — the `when` closure and interrupt-payload translation. This is where langchain types meet the policy, and the reason the policy itself stays clean.
- `tests/application/test_autonomy.py`
- `tests/infrastructure/test_search.py`
- `tests/infrastructure/test_resume_loop.py`
- `tests/integration/test_no_network.py`
- `tests/integration/test_approval.py`

**Modify:**
- `research_team/application/ports.py` — `ApprovalRequest`, `ApprovalDecision`, `ApprovalPort`.
- `research_team/application/__init__.py` — re-export the new names.
- `research_team/application/session_service.py:38` — `DEFAULT_SYSTEM_PROMPT`.
- `research_team/domain/events.py` — two new events, added to `SESSION_EVENTS`.
- `research_team/domain/session.py` — commands to record them. (Corrected mid-execution: this branch is based on `origin/main`, where there is no `domain/commands.py` — commands are plain methods on `CodingSession`. The `refactor/decider-pattern` branch, which does have that file, is **not** in this branch's history.)
- `research_team/domain/__init__.py` — re-export.
- `research_team/infrastructure/config.py` — two new settings.
- `research_team/infrastructure/agent/deep_agent.py` — `tools=`, `interrupt_on=`, checkpointer, resume loop.
- `research_team/composition.py` — wire it all.
- `research_team/interfaces/cli/repl.py` — approval prompt, `/autonomy` command.
- `research_team/interfaces/web/app.py` — approval over SSE + POST.
- `pyproject.toml` — deps and mutmut config.
- `README.md` — env table, gated-egress note.
- `tests/infrastructure/test_schema_evolution.py` — cases for both new events.

---

### Task 0: Spike — does `interrupt_on` reach subagents?

The spec's open question. It decides whether Task 8 gates the `worker` subagent's file writes or documents that it cannot. **This task writes no production code** — it produces a finding and records it.

**Files:**
- Create: `docs/superpowers/plans/2026-08-03-subagent-interrupt-finding.md`

- [ ] **Step 1: Write a throwaway probe**

Put this in `/tmp/probe_subagent_interrupt.py` (throwaway — not committed):

```python
import asyncio
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from tests.conftest import ToolAwareFakeChatModel
from langchain_core.messages import AIMessage

# A model that, on the parent, calls `task` to delegate; the subagent then
# tries to write a file. If interrupt_on reaches the subagent, the parent
# stream yields __interrupt__ for write_file. If not, the write just happens.
```

Build a `create_deep_agent` with `subagents=[WORKER]`, `interrupt_on={"write_file": {"allowed_decisions": ["approve", "reject"]}}`, `checkpointer=MemorySaver()`, and a scripted model that delegates a write to the `worker`. Stream it and print whether `__interrupt__` appears and which tool name it names.

- [ ] **Step 2: Run the probe both ways**

Run: `uv run python /tmp/probe_subagent_interrupt.py`

Run it a second time with the write happening on the **parent** instead of via `task`, to confirm the probe itself is sound — the parent case must interrupt. A probe that never interrupts in either case proves nothing.

- [ ] **Step 3: Record the finding**

Write `docs/superpowers/plans/2026-08-03-subagent-interrupt-finding.md` stating, in a few sentences: what was run, what happened in each case, and the consequence — either "subagent file writes gate, Task 8 wires them" or "they do not gate; the README must say the gate covers the parent's own tool calls only."

**Do not** guess. If the probe is inconclusive, say so and choose the conservative reading (does not propagate).

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-08-03-subagent-interrupt-finding.md
git commit -m "docs: record whether interrupt_on reaches subagents"
```

---

### Task 1: Dependencies and mutation-testing config

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `hypothesis` and `mutmut` importable/runnable in the dev environment; `httpx` available to shipped code.

- [ ] **Step 1: Move `httpx` and add the test tooling**

In `pyproject.toml`, add `"httpx>=0.28.1"` to `[project] dependencies`, and remove it from `[dependency-groups] dev`. Then add to `dev`:

```toml
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
    "hypothesis>=6.100",
    "mutmut>=3.0",
]
```

- [ ] **Step 2: Configure mutmut to the new modules only**

Append to `pyproject.toml`. Scoped deliberately: a whole-repo mutation run is slow enough that nobody runs it twice.

```toml
[tool.mutmut]
paths_to_mutate = [
    "research_team/application/autonomy.py",
    "research_team/infrastructure/agent/search.py",
    "research_team/infrastructure/agent/approval.py",
]
tests_dir = "tests/"
```

- [ ] **Step 3: Sync and verify**

Run: `uv sync --group dev`
Then: `uv run python -c "import hypothesis, httpx; print('ok')"`
Expected: prints `ok`.

Run: `uv run pytest -q`
Expected: the existing suite still passes. Moving `httpx` between groups must not change anything.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add hypothesis and mutmut, promote httpx to a runtime dependency"
```

---

### Task 2: The autonomy policy

**Files:**
- Create: `research_team/application/autonomy.py`
- Modify: `research_team/application/__init__.py`
- Test: `tests/application/test_autonomy.py`

**Interfaces:**
- Produces:
  - `Level = Literal["auto", "ask", "deny"]`
  - `SEARCH_TOOL: str = "web_search"`
  - `GATED_TOOLS: tuple[str, ...] = (SEARCH_TOOL, "write_file", "edit_file", "delete_file")`
  - `AutonomyPolicy(default: Level = "auto")` with `.level_for(tool_name: str) -> Level`, `.set(tool_name: str, level: Level) -> None`, `.levels() -> dict[str, Level]`
  - `AutonomyPolicy.set` raises `ValueError` on an unknown level.

- [ ] **Step 1: Write the failing tests**

Create `tests/application/test_autonomy.py`. Note this file imports **only** from `research_team.application` — the architecture test will fail the build if `autonomy.py` reaches for a framework.

```python
"""The autonomy policy: what the agent may do without being asked.

Mutable on purpose. It is read once per tool call rather than once per turn,
so raising or lowering autonomy lands on the next tool call -- including
partway through a turn already running.
"""

import pytest
from hypothesis import given, strategies as st

from research_team.application import GATED_TOOLS, AutonomyPolicy

LEVELS = ("auto", "ask", "deny")


def test_defaults_to_auto_so_existing_behaviour_is_unchanged():
    policy = AutonomyPolicy()
    for tool in GATED_TOOLS:
        assert policy.level_for(tool) == "auto"


def test_an_ungated_tool_is_always_auto():
    policy = AutonomyPolicy(default="ask")
    policy.set("write_file", "deny")
    assert policy.level_for("read_file") == "auto"


def test_setting_a_level_takes_effect_immediately():
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    assert policy.level_for("web_search") == "ask"
    policy.set("web_search", "deny")
    assert policy.level_for("web_search") == "deny"


def test_an_unknown_level_is_refused():
    policy = AutonomyPolicy()
    with pytest.raises(ValueError, match="sometimes"):
        policy.set("web_search", "sometimes")


def test_an_ungated_tool_cannot_be_set():
    policy = AutonomyPolicy()
    with pytest.raises(ValueError, match="read_file"):
        policy.set("read_file", "ask")


@given(
    st.lists(
        st.tuples(st.sampled_from(GATED_TOOLS), st.sampled_from(LEVELS)),
        min_size=1,
        max_size=30,
    )
)
def test_level_for_returns_the_last_level_set(writes):
    """For any sequence of sets, each tool reads back its own last write."""
    policy = AutonomyPolicy()
    expected = {}
    for tool, level in writes:
        policy.set(tool, level)
        expected[tool] = level
    for tool, level in expected.items():
        assert policy.level_for(tool) == level


@given(
    st.lists(
        st.tuples(st.sampled_from(GATED_TOOLS), st.sampled_from(LEVELS)),
        max_size=30,
    )
)
def test_levels_never_leak_between_tools(writes):
    """A tool nobody wrote to still reads the default."""
    policy = AutonomyPolicy()
    for tool, level in writes:
        policy.set(tool, level)
    untouched = set(GATED_TOOLS) - {tool for tool, _ in writes}
    for tool in untouched:
        assert policy.level_for(tool) == "auto"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/application/test_autonomy.py -v`
Expected: FAIL — `ImportError: cannot import name 'AutonomyPolicy'`.

- [ ] **Step 3: Write the implementation**

Create `research_team/application/autonomy.py`:

```python
"""How much the agent may do without asking.

Held as a mutable object rather than passed at construction time, because the
question "may this agent search the web right now?" has a different answer at
different moments and nobody wants to restart a session to change it. The
predicate that consults this runs once per tool call, so a change lands on the
next call -- including partway through a turn already in flight.

Framework-free on purpose: `tests/test_architecture.py` holds this layer to
importing nothing but `eventsource`, and the closure that adapts this to
langchain's `when` predicate lives in `infrastructure` instead.
"""

from typing import Literal

Level = Literal["auto", "ask", "deny"]
"""`auto` runs it, `ask` interrupts for a human, `deny` refuses without asking."""

LEVELS: tuple[Level, ...] = ("auto", "ask", "deny")

SEARCH_TOOL = "web_search"

GATED_TOOLS: tuple[str, ...] = (
    SEARCH_TOOL,
    "write_file",
    "edit_file",
    "delete_file",
)
"""What can be gated. Read-only file tools are absent deliberately: they cost
nothing and escape nothing, and gating them would train people to click
through approvals without reading them."""


class AutonomyPolicy:
    """Per-tool autonomy levels, mutable at any time."""

    def __init__(self, default: Level = "auto") -> None:
        self._default: Level = default
        self._levels: dict[str, Level] = {}

    def level_for(self, tool_name: str) -> Level:
        """The level for a tool. Ungated tools are always `auto`."""
        if tool_name not in GATED_TOOLS:
            return "auto"
        return self._levels.get(tool_name, self._default)

    def set(self, tool_name: str, level: Level) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown autonomy level: {level!r}")
        if tool_name not in GATED_TOOLS:
            raise ValueError(f"not a gated tool: {tool_name!r}")
        self._levels[tool_name] = level

    def levels(self) -> dict[str, Level]:
        """Every gated tool's current level, for display."""
        return {tool: self.level_for(tool) for tool in GATED_TOOLS}
```

- [ ] **Step 4: Re-export from the package**

In `research_team/application/__init__.py`, add `AutonomyPolicy`, `Level`, `GATED_TOOLS`, `SEARCH_TOOL` to the imports and to `__all__`, following the file's existing ordering.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/application/test_autonomy.py tests/test_architecture.py -v`
Expected: PASS, including the architecture test.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/autonomy.py research_team/application/__init__.py tests/application/test_autonomy.py
git commit -m "feat: per-tool autonomy levels, adjustable at any time"
```

---

### Task 3: Configuration

**Files:**
- Modify: `research_team/infrastructure/config.py`
- Test: `tests/infrastructure/test_config.py`

**Interfaces:**
- Produces: `config.searxng_url() -> str | None` (None when unset or blank), `config.searxng_results() -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_config.py`, matching how that file already sets and clears variables (use its existing fixture/monkeypatch idiom rather than inventing one):

```python
def test_no_searxng_url_means_no_search_tool(monkeypatch):
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)
    assert config.searxng_url() is None


def test_a_blank_searxng_url_reads_as_unset(monkeypatch):
    monkeypatch.setenv("AGENT_SEARXNG_URL", "   ")
    assert config.searxng_url() is None


def test_searxng_url_loses_its_trailing_slash(monkeypatch):
    monkeypatch.setenv("AGENT_SEARXNG_URL", "http://searx.local/")
    assert config.searxng_url() == "http://searx.local"


def test_result_cap_defaults(monkeypatch):
    monkeypatch.delenv("AGENT_SEARXNG_RESULTS", raising=False)
    assert config.searxng_results() == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_config.py -v -k searxng`
Expected: FAIL — `AttributeError: module ... has no attribute 'searxng_url'`.

- [ ] **Step 3: Implement**

Add near the other constants in `config.py`:

```python
DEFAULT_SEARXNG_RESULTS = 5
```

and the two readers, in the file's existing style:

```python
def searxng_url() -> str | None:
    """The SearXNG instance to search, or None if this install has no search.

    Unset is the default and means the agent gets no network tool at all --
    which is what keeps the sandbox claim true for anyone who has not opted in.
    """
    configured = os.getenv("AGENT_SEARXNG_URL", "").strip()
    return configured.rstrip("/") or None


def searxng_results() -> int:
    """How many results reach the model. Capped because context is the cost."""
    return int(os.getenv("AGENT_SEARXNG_RESULTS", str(DEFAULT_SEARXNG_RESULTS)))
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/infrastructure/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/config.py tests/infrastructure/test_config.py
git commit -m "feat: read SearXNG settings from the environment"
```

---

### Task 4: The search tool

**Files:**
- Create: `research_team/infrastructure/agent/search.py`
- Test: `tests/infrastructure/test_search.py`

**Interfaces:**
- Consumes: `config.searxng_url()`, `config.searxng_results()` (Task 3); `SEARCH_TOOL` (Task 2).
- Produces:
  - `format_results(payload: dict, limit: int) -> str` — pure, no I/O, separately testable.
  - `build_search_tool(base_url: str, *, limit: int = 5, client: httpx.AsyncClient | None = None) -> BaseTool` — a langchain tool named `web_search` taking one argument `query: str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_search.py`. Note the stubbed transport — no test in this suite touches the real network.

```python
"""The search tool, against a stubbed transport.

No test here reaches the network. The live test lives behind the `live`
marker, like the model tests do.
"""

import httpx
import pytest
from hypothesis import given, strategies as st

from research_team.infrastructure.agent.search import (
    format_results,
    build_search_tool,
)

PAYLOAD = {
    "results": [
        {"title": "Event sourcing", "url": "https://a.example", "content": "A log."},
        {"title": "CQRS", "url": "https://b.example", "content": "Two models."},
        {"title": "Third", "url": "https://c.example", "content": "Extra."},
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_results_are_formatted_with_title_url_and_snippet():
    text = format_results(PAYLOAD, limit=5)
    assert "Event sourcing" in text
    assert "https://a.example" in text
    assert "A log." in text


def test_the_result_cap_is_honoured():
    text = format_results(PAYLOAD, limit=2)
    assert "Event sourcing" in text
    assert "Third" not in text


def test_no_results_says_so_rather_than_returning_nothing():
    assert "no results" in format_results({"results": []}, limit=5).lower()


async def test_a_query_reaches_the_instance_and_comes_back_formatted():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=PAYLOAD)

    tool = build_search_tool("http://searx.local", limit=5, client=_client(handler))
    text = await tool.ainvoke({"query": "event sourcing"})

    assert "format=json" in seen["url"]
    assert "event+sourcing" in seen["url"] or "event%20sourcing" in seen["url"]
    assert "Event sourcing" in text


async def test_a_non_json_response_names_the_setting_that_causes_it():
    """SearXNG ships with the JSON API disabled; say so instead of exploding."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert "formats" in text
    assert "settings.yml" in text


async def test_an_unreachable_instance_is_an_ordinary_tool_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert "could not reach" in text.lower()


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "title": st.text(max_size=200),
                "url": st.text(max_size=200),
                "content": st.text(max_size=500),
            }
        ),
        max_size=50,
    ),
    st.integers(min_value=1, max_value=10),
)
def test_formatting_never_raises_and_never_exceeds_the_cap(results, limit):
    """Whatever an instance returns, formatting is total and bounded."""
    text = format_results({"results": results}, limit=limit)
    assert isinstance(text, str)
    shown = text.count("\n\n")
    assert shown <= limit
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_search.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `research_team/infrastructure/agent/search.py`:

```python
"""Web search, via a SearXNG instance.

The one tool in this system that leaves the process. It is registered only when
an instance is configured, and it is gated by the autonomy policy like the file
tools are -- both of which are what keep "nothing escapes" an accurate
statement about a default install rather than a fond memory.

Results are capped and flattened before they reach the model. An uncapped
result set is a context leak of exactly the kind the `elide` and `compact`
strategies exist to clean up afterwards, and it is cheaper not to make the mess.
"""

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application import SEARCH_TOOL

TIMEOUT = httpx.Timeout(10.0)

_JSON_DISABLED = (
    "The SearXNG instance did not return JSON. Its JSON API is disabled by "
    "default -- the instance needs `formats: [json]` under `search:` in its "
    "settings.yml. No results this time."
)


def format_results(payload: dict, limit: int) -> str:
    """Flatten a SearXNG payload to title/url/snippet, capped at `limit`.

    Total by construction: an instance is a foreign system and a missing key is
    an ordinary thing for one to return, not an exception for the agent to
    reason about.
    """
    results = payload.get("results") or []
    chosen = results[:limit]
    if not chosen:
        return "No results."
    blocks = []
    for result in chosen:
        title = str(result.get("title", "")).strip() or "(untitled)"
        url = str(result.get("url", "")).strip()
        snippet = " ".join(str(result.get("content", "")).split())
        blocks.append(f"{title}\n{url}\n{snippet}")
    return "\n\n".join(blocks)


def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """A `web_search` tool against one SearXNG instance.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network.
    """

    @tool(SEARCH_TOOL)
    async def web_search(query: str) -> str:
        """Search the web. Returns titles, URLs, and short snippets."""
        owned = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await http.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
        except ValueError:
            # Not JSON. Overwhelmingly the default-settings case, and worth
            # naming precisely -- the model cannot fix it, but the person
            # reading the log can.
            return _JSON_DISABLED
        except httpx.HTTPError as error:
            return f"Could not reach the search instance: {error}"
        finally:
            if owned:
                await http.aclose()
        return format_results(payload, limit)

    return web_search
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/infrastructure/test_search.py -v`
Expected: PASS, all cases including both Hypothesis properties.

If `test_formatting_never_raises_and_never_exceeds_the_cap` fails on a shrunk example, fix `format_results` — do not weaken the property.

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/agent/search.py tests/infrastructure/test_search.py
git commit -m "feat: a SearXNG-backed web_search tool"
```

---

### Task 5: Events for decisions and autonomy changes

**Files:**
- Modify: `research_team/domain/events.py`, `research_team/domain/commands.py`, `research_team/domain/session.py`, `research_team/domain/__init__.py`
- Test: `tests/domain/test_session.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - Events `ToolCallDecided(tool_name, args, decision, decided_by, edited_args)` and `AutonomyChanged(tool_name, level)`.
  - Aggregate methods `CodingSession.record_tool_decision(...)` and `CodingSession.record_autonomy_change(tool_name, level)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/domain/test_session.py`, following that file's existing construction idiom:

```python
def test_a_tool_decision_is_recorded_on_the_stream(started_session):
    started_session.record_tool_decision(
        tool_name="web_search",
        args={"query": "event sourcing"},
        decision="approve",
        decided_by="human",
    )
    event = started_session.pending_events[-1]
    assert isinstance(event, ToolCallDecided)
    assert event.decision == "approve"
    assert event.decided_by == "human"
    assert event.edited_args is None


def test_an_autonomy_change_is_recorded_on_the_stream(started_session):
    started_session.record_autonomy_change("web_search", "ask")
    event = started_session.pending_events[-1]
    assert isinstance(event, AutonomyChanged)
    assert event.tool_name == "web_search"
    assert event.level == "ask"
```

Add to `tests/infrastructure/test_schema_evolution.py`, following exactly the pattern the existing cases use to write an old-shaped payload straight into the events table and read it back:

```python
# A payload written before `edited_args` existed must still load, reading as
# "no edit was made" -- which is what its absence meant.
TOOL_CALL_DECIDED_WITHOUT_EDITED_ARGS = {
    "tool_name": "web_search",
    "args": {"query": "x"},
    "decision": "approve",
    "decided_by": "human",
}
```

with an assertion that the loaded event has `edited_args is None`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_session.py -v -k "decision or autonomy"`
Expected: FAIL — names not defined.

- [ ] **Step 3: Add the events**

In `research_team/domain/events.py`, before `SESSION_EVENTS`:

```python
@register_event
class ToolCallDecided(DomainEvent):
    """A gated tool call was allowed, refused, or amended -- and by whom.

    Recorded because a supervision decision is a fact about how the session was
    conducted, and one that is not recoverable afterwards: the policy that
    produced it is configuration, and configuration changes. `decided_by`
    separates a human's judgement from the policy's own refusal; both stop a
    call, and an audit trail that cannot tell them apart is a worse one.
    """

    aggregate_type: str = "CodingSession"
    tool_name: str
    args: dict[str, Any]
    decision: str
    """langchain's vocabulary: approve | edit | reject | respond."""
    decided_by: str
    """`human` or `policy`."""
    edited_args: dict[str, Any] | None = None
    """The amended arguments when `decision` is `edit`. None otherwise."""


@register_event
class AutonomyChanged(DomainEvent):
    """How much the agent may do without asking was changed mid-session."""

    aggregate_type: str = "CodingSession"
    tool_name: str
    level: str
    """auto | ask | deny."""
```

Add both to `SESSION_EVENTS`.

- [ ] **Step 4: Add the commands and aggregate methods**

Follow the existing command/handler pattern in `commands.py` and `session.py` exactly — this codebase was just refactored to a decider, so match how a neighbouring command such as `WriteFile` is declared, decided, and folded. Neither new event changes derived state: they are recorded for the audit trail, so their reducers return state unchanged. Say that in a comment, because a reducer that does nothing looks like a bug otherwise.

Re-export both events from `research_team/domain/__init__.py`.

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/domain tests/infrastructure/test_schema_evolution.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add research_team/domain tests/domain tests/infrastructure/test_schema_evolution.py
git commit -m "feat: record tool decisions and autonomy changes on the stream"
```

---

### Task 6: The approval port

**Files:**
- Modify: `research_team/application/ports.py`, `research_team/application/__init__.py`
- Test: covered by Task 7's tests; this task adds types only.

**Interfaces:**
- Produces (framework-free — these cross the application boundary):

```python
@dataclass(frozen=True)
class ApprovalRequest:
    session_id: UUID
    tool_name: str
    args: dict
    description: str
    allowed_decisions: tuple[str, ...]

@dataclass(frozen=True)
class ApprovalDecision:
    type: str                       # approve | edit | reject | respond
    edited_args: dict | None = None
    message: str | None = None

class ApprovalPort(Protocol):
    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

- [ ] **Step 1: Add the types**

Add to `research_team/application/ports.py`, in the file's established style — a docstring on each explaining why it exists, not what it holds. The key sentence for `ApprovalPort`: the executor must not know whether a human is at a terminal or a browser, which is the same reason every other outside-world concern here is a port.

- [ ] **Step 2: Re-export and verify the layer stays clean**

Add the three names to `research_team/application/__init__.py` and `__all__`.

Run: `uv run pytest tests/test_architecture.py -v`
Expected: PASS — nothing imported from langchain.

- [ ] **Step 3: Commit**

```bash
git add research_team/application/ports.py research_team/application/__init__.py
git commit -m "feat: declare the approval port"
```

---

### Task 7: The resume loop

The heart of the change, and the piece most likely to break.

**Files:**
- Create: `research_team/infrastructure/agent/approval.py`
- Modify: `research_team/infrastructure/agent/deep_agent.py`
- Test: `tests/infrastructure/test_resume_loop.py`

**Interfaces:**
- Consumes: `AutonomyPolicy` (Task 2), `ApprovalPort`/`ApprovalRequest`/`ApprovalDecision` (Task 6), `ToolCallDecided` recording (Task 5).
- Produces:
  - `interrupt_config(policy: AutonomyPolicy) -> dict[str, InterruptOnConfig]` in `approval.py` — builds the `when` closures. **This is where langchain meets the policy**, keeping the application layer clean.
  - `DeepAgentTurnExecutor(model, *, subagents=(), tools=(), policy=None, approvals=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_resume_loop.py`:

```python
"""The resume loop: what happens when a gated tool call is interrupted.

The failure mode this guards is a miscount. All of one AI message's
interrupted calls arrive as a single interrupt carrying parallel lists, and
langchain raises if the number of decisions coming back does not match. A
loop that resumes more than once must not lose track across passes.
"""

import pytest
from hypothesis import given, settings, strategies as st

from research_team.application import ApprovalDecision, AutonomyPolicy
from research_team.domain import ToolCallDecided


class ScriptedApprovals:
    """An ApprovalPort that answers from a list and records what it was asked."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.seen = []

    async def decide(self, request):
        self.seen.append(request)
        return self._decisions.pop(0) if self._decisions else ApprovalDecision("approve")


async def test_an_approved_search_runs(...):
    """policy=ask, human approves -> the tool executes and its result is recorded."""


async def test_a_rejected_search_does_not_run_and_the_model_is_told(...):
    """policy=ask, human rejects -> no network call, a ToolMessage explains."""


async def test_a_denied_search_never_reaches_the_human(...):
    """policy=deny -> approvals.seen is empty, and a ToolCallDecided is
    recorded with decided_by='policy'."""


async def test_an_edited_call_runs_with_the_amended_arguments(...):
    """policy=ask, human edits the query -> the tool sees the new query and
    ToolCallDecided.edited_args carries it."""


async def test_an_auto_tool_is_never_interrupted(...):
    """policy=auto -> approvals.seen is empty and no ToolCallDecided appears."""


async def test_a_level_raised_mid_turn_gates_the_next_call(...):
    """Two search calls in one turn. The port sets the policy to `deny` while
    answering the first. The second must not reach the human -- this is the
    whole point of a live policy object."""


@settings(deadline=None, max_examples=25)
@given(st.lists(st.sampled_from(["approve", "reject"]), min_size=1, max_size=6))
async def test_every_interrupted_call_gets_exactly_one_decision(decisions):
    """For any sequence of decisions the loop terminates, and exactly one
    ToolCallDecided is recorded per interrupted call -- no double-counting
    across resumed passes, no dropped decision."""
```

Fill each body using `ToolAwareFakeChatModel` from `tests/conftest.py` (the same double `test_no_shell.py` uses) to script tool calls, and the stubbed search tool from Task 4. Every test asserts on recorded events, not on log output.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_resume_loop.py -v`
Expected: FAIL.

- [ ] **Step 3: Write `approval.py`**

```python
"""Where the autonomy policy meets langchain's interrupt machinery.

The policy itself names no framework -- the architecture test holds the
application layer to that -- so the adaptation lives here. `when` answers only
`auto` vs. not-auto, because it returns a bool; the difference between `ask`
and `deny` is settled by the resume loop, which can refuse without asking.
"""

from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig

from research_team.application import GATED_TOOLS, AutonomyPolicy

ALLOWED_DECISIONS = ["approve", "edit", "reject"]
"""No `respond`: answering on a tool's behalf invents a result, and this log is
supposed to record what actually happened."""


def interrupt_config(policy: AutonomyPolicy) -> dict[str, InterruptOnConfig]:
    """One entry per gated tool, each consulting the live policy per call."""
    return {
        tool: InterruptOnConfig(
            allowed_decisions=ALLOWED_DECISIONS,
            when=_gate_for(policy, tool),
        )
        for tool in GATED_TOOLS
    }


def _gate_for(policy: AutonomyPolicy, tool: str):
    """Closes over the policy rather than its current value.

    This is what makes autonomy adjustable at any time: langchain calls the
    predicate once per tool call, so a level raised mid-turn is honoured on the
    very next call rather than at the next restart.
    """

    def when(request) -> bool:  # noqa: ANN001 - langchain's ToolCallRequest
        return policy.level_for(tool) != "auto"

    return when
```

- [ ] **Step 4: Rewrite `_invoke` as a resume loop**

In `deep_agent.py`: accept `tools`, `policy`, and `approvals` in `__init__`; pass `tools=` and `interrupt_on=interrupt_config(policy)` to `create_deep_agent`; replace `checkpointer=None` with a per-turn `MemorySaver` and a config carrying a `thread_id` built from the session id and turn index.

The loop, in prose so the implementer writes it rather than pastes it: stream the agent as it does today, keeping the existing `reported` cursor so activity is not re-reported across passes. When a completed stream leaves `__interrupt__` in the state, read its `action_requests` and `review_configs`, and for each one in order decide — `deny` produces a `reject` decision with no human contact, anything else calls `approvals.decide(...)`. Record a `ToolCallDecided` on the aggregate for each. Then resume with `Command(resume={"decisions": [...]})` and stream again, appending decisions **in the same order as the action requests**. Repeat until a pass ends with no interrupt.

Two things to get right, both of which the tests check:
- The decision list length must equal the number of action requests, or langchain raises.
- `reported` must carry across passes, or the caller sees duplicated activity lines.

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest tests/infrastructure/test_resume_loop.py -v`
Expected: PASS.

Then: `uv run pytest -q`
Expected: the whole suite still passes. Adding a checkpointer must not change ungated behaviour.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/agent/approval.py research_team/infrastructure/agent/deep_agent.py tests/infrastructure/test_resume_loop.py
git commit -m "feat: interrupt gated tool calls and resume on a decision"
```

---

### Task 8: Composition and prompts

**Files:**
- Modify: `research_team/composition.py`, `research_team/application/session_service.py:38`
- Test: `tests/integration/test_no_network.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces: `Application.policy: AutonomyPolicy`, and `build_application(..., approvals: ApprovalPort | None = None, policy: AutonomyPolicy | None = None)`.

- [ ] **Step 1: Write the failing invariant test**

Create `tests/integration/test_no_network.py`, in the spirit of `test_no_shell.py` — an invariant that should fail loudly if it ever silently changes:

```python
"""No search tool unless one was configured.

The README promises a default install reaches nothing outside the process.
That promise now rests on a conditional registration rather than on an absent
dependency, which is a weaker thing to rest on -- so it is asserted here.
"""


async def test_a_default_application_has_no_search_tool(build_application):
    """With no SearXNG configured, the agent is offered no network tool."""


async def test_a_configured_application_offers_search(build_application):
    """With one configured, the tool appears -- and is gated, not free."""
```

Fill both by inspecting the tools the executor was built with.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_no_network.py -v`
Expected: FAIL.

- [ ] **Step 3: Wire it up**

In `composition.py`: build an `AutonomyPolicy` (or take the injected one), build the search tool only when `config.searxng_url()` returns a URL, pass tools/policy/approvals into `DeepAgentTurnExecutor`, and expose `policy` on `Application`.

Add a search prompt fragment shaped like `DELEGATION_PROMPT` — put it in `search.py` next to the tool it describes. It should tell the model that search results are a snapshot recorded in the log, that a refused search is an answer and not something to retry, and that it should search when its own knowledge is stale or thin rather than reflexively.

- [ ] **Step 4: Fix the system prompt's now-false claim**

`DEFAULT_SYSTEM_PROMPT` at `session_service.py:38` ends "There is no shell and no network." With search configured that is a lie, and a model told it has no network will not search. Split the sentence: keep "There is no shell" unconditional, and let composition append the network clause only when no search tool is registered.

- [ ] **Step 5: Apply the Task 0 finding**

If the spike found that `interrupt_on` reaches subagents, nothing more is needed — `GATED_TOOLS` already covers the file tools. If it found otherwise, note it in the README in Task 10 and add a comment in `delegation.py` saying subagent file writes are ungated and why.

- [ ] **Step 6: Run to verify passing**

Run: `uv run pytest -q`
Expected: whole suite passes.

- [ ] **Step 7: Commit**

```bash
git add research_team/composition.py research_team/application/session_service.py research_team/infrastructure/agent/search.py tests/integration/test_no_network.py
git commit -m "feat: register search only when configured, and gate it"
```

---

### Task 9: The two adapters

**Files:**
- Modify: `research_team/interfaces/cli/repl.py`, `research_team/interfaces/web/app.py`
- Test: `tests/integration/test_approval.py`

**Interfaces:**
- Consumes: `ApprovalPort` (Task 6), `Application.policy` (Task 8).
- Produces: a CLI `/autonomy` command, and web endpoints for pending approvals.

- [ ] **Step 1: Write the failing end-to-end test**

Create `tests/integration/test_approval.py`: drive a full turn through `SessionService` with a scripted model that searches, an `ask` policy, and a fake approving port; assert the log contains `ToolCallDecided` followed by the search's `ToolResultRecorded`, in that order. Then the same with a rejecting port, asserting no result but a recorded decision.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_approval.py -v`

- [ ] **Step 3: Implement the CLI adapter**

An `ApprovalPort` that prints the tool name and arguments and reads a single key: approve / reject / edit. Put it beside the existing activity printing in `repl.py` so approval and progress share one visual language. Add `/autonomy` with no arguments to list levels and `/autonomy <tool> <level>` to set one, recording an `AutonomyChanged` event.

- [ ] **Step 4: Implement the web adapter**

An `ApprovalPort` holding a registry of pending approvals keyed by session, each an `asyncio.Future`. Requesting an approval publishes it on the existing SSE feed and awaits the future; a `POST` resolves it. A session whose browser goes away leaves a turn awaiting a decision — the existing turn cancellation path is what unblocks it, so make sure the future is cancelled when the turn is.

- [ ] **Step 5: Run to verify passing**

Run: `uv run pytest -q`

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces tests/integration/test_approval.py
git commit -m "feat: approve tool calls from the REPL and the web UI"
```

---

### Task 9b: The browser approval UI

Added mid-execution. Task 9 delivered a complete web *backend* — approval frames on the SSE channel, a GET for pending approvals, a POST to resolve one — but `static/app.js` renders none of it, so a gated turn in the browser parks correctly and looks to a person like a hang. The plan's Task 9 file list omitted the frontend; that was a plan gap, not an implementation failure. A human-in-the-loop feature whose main UI cannot answer the prompt is not finished.

**Files:**
- Modify: `research_team/interfaces/web/static/app.js` (1918 lines), and `index.html`/CSS as needed

**Interfaces (already built, do not change):**
- SSE frames on the existing `/api/stream` channel, types `ApprovalRequested` and `ApprovalSettled`
- `GET /api/sessions/{id}/approvals` — pending approvals for a session
- `POST /api/sessions/{id}/approvals/{approval_id}` — resolve one with a decision

- [ ] **Step 1: Render pending approvals**

On an `ApprovalRequested` frame for the open session, show the tool name and its arguments where the turn's activity already appears, with approve / reject buttons. Match the existing rendering idiom in `app.js` — it has a small element helper at the top and a frame dispatch near the `EventSource` wiring at line ~1775. Do not introduce a framework.

- [ ] **Step 2: Resolve on click**

POST the decision to the endpoint above. On `ApprovalSettled`, clear the prompt — including when it was settled elsewhere (the REPL, or another browser tab), which is why the settled frame exists rather than just hiding the card locally.

- [ ] **Step 3: Reconcile on reconnect**

A browser that connects mid-approval must not miss the prompt. On load and on SSE reconnect, `GET` the pending approvals for the open session and render any that are outstanding. This is the case the SSE frame alone cannot cover.

- [ ] **Step 4: Verify by hand**

Run `uv run web.py` with `AGENT_SEARXNG_URL` set and the policy at `ask`, drive a search from the browser, and confirm: the prompt appears, approving lets the turn finish, rejecting records the refusal, and a page reload mid-approval still shows it. Report what you actually observed.

- [ ] **Step 5: Commit**

```bash
git add research_team/interfaces/web/static/app.js
git commit -m "feat: answer approval prompts from the browser"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the configuration table**

Add `AGENT_SEARXNG_URL` (default: unset, "SearXNG base URL; unset means no search tool") and `AGENT_SEARXNG_RESULTS` (default `5`).

- [ ] **Step 2: Amend the sandbox paragraph honestly**

The first paragraphs claim nothing escapes the process. Say what is now true: the filesystem is still virtual and there is still no shell; search is opt-in, absent unless configured, gated per-tool, and its results are replayed from the log rather than re-fetched, so replay stays pure. Note the `formats: [json]` requirement for the instance. If Task 0 found that subagent writes do not gate, say that too.

- [ ] **Step 3: Document autonomy**

A short section: the three levels, the `/autonomy` command, and that changes take effect on the next tool call rather than the next session.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document search, autonomy levels, and the gated-egress exception"
```

---

### Task 11: Mutation testing

The suite's own strength, measured rather than assumed.

**Files:**
- Modify: whichever test files the surviving mutants demand.

- [ ] **Step 1: Run mutmut over the new modules**

Run: `uv run mutmut run`
This covers only `autonomy.py`, `search.py`, and `approval.py` per Task 1's config.

- [ ] **Step 2: Read the survivors**

Run: `uv run mutmut results`
Then `uv run mutmut show <id>` for each survivor.

- [ ] **Step 3: Kill or justify each survivor**

For each: either add a test that fails against the mutant, or record in a comment beside the code why the mutant is equivalent (a change that genuinely cannot alter behaviour). **Do not** weaken a mutant by deleting the code it lives in, and do not claim equivalence to avoid writing a test — a survivor is usually a real gap.

Expect survivors in the boundary arithmetic of `format_results` (`limit` slicing) and in the level comparison in `_gate_for`. Both are behaviour worth a test.

- [ ] **Step 4: Re-run to confirm**

Run: `uv run mutmut run` then `uv run mutmut results`
Expected: every survivor either killed or annotated.

- [ ] **Step 5: Commit**

```bash
git add tests research_team
git commit -m "test: kill mutants surviving in the autonomy, search, and approval modules"
```

---

### Task 12: Final verification and PR

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q`
Expected: PASS. Report the actual count.

- [ ] **Step 2: Lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Architecture test explicitly**

Run: `uv run pytest tests/test_architecture.py -v`
Expected: PASS — the application layer still names no framework.

- [ ] **Step 4: Open a draft PR**

Title: `feat: SearXNG search, gated by human-in-the-loop autonomy levels`

The body should state what changed, that search is opt-in and off by default, the three autonomy levels, the Task 0 finding about subagents, and the mutation-testing result. Link the spec and this plan.

## Self-Review

**Spec coverage.** Policy → Task 2. Tool → Task 4. Resume loop and checkpointer → Task 7. Approval port → Task 6. Events → Task 5. Prompt and system-prompt fix → Task 8. Config → Task 3. Dependencies → Task 1. Error handling → Task 4 (non-JSON, unreachable) and Task 9 (adapter disappears). Testing including Hypothesis → Tasks 2, 4, 7; mutation → Task 11. Open question → Task 0. Docs → Task 10. No section unaccounted for.

**Type consistency.** `SEARCH_TOOL = "web_search"` is defined once in Task 2 and used in Tasks 4, 7, 8. `AutonomyPolicy.level_for`/`.set`/`.levels` keep the same names throughout. `ApprovalDecision.type` uses langchain's vocabulary in every task. `format_results(payload, limit)` and `build_search_tool(base_url, *, limit, client)` are consistent between Task 4's tests and implementation.

**Known softness.** Tasks 9's web adapter and Task 7's loop body are specified in prose rather than complete code, because both depend on the exact shape of existing code (`repl.py`'s command dispatch, `app.py`'s SSE plumbing) that the implementer will have in front of them and I would only be guessing at. Every behaviour they must produce is pinned by a test written out in full.
