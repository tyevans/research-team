# Interaction Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture frontend user interaction — semantic actions, navigation and dwell — into its own event store, so later work on friction and preemption is designed against a real corpus.

**Architecture:** A second SQLite event store at `~/.research-team/interactions.db`, appended to directly (no aggregate) by a recorder that publishes to its own bus, projected into one flat table by one projection, fed by a batched browser emitter over a single POST route. Capture only: no consumer, no read route, no UI.

**Tech Stack:** Python 3.13, `eventsource-py>=0.14,<0.15`, FastAPI, pydantic, aiosqlite, pytest. Frontend: React 19, TypeScript, zustand, `@tanstack/react-query`, zod, wouter (hash routing), vitest (jsdom + Playwright browser project).

**Spec:** `docs/superpowers/specs/2026-08-17-interaction-log-design.md` — read it before Task 1. The plan argues from it; where they disagree, the spec wins and the plan is wrong.

## Global Constraints

- **Four gates, all repo-wide.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The two ruff commands cover the whole repository, not touched files.
- **A fifth gate for any `frontend/src` change:** `cd frontend && npm run build`, then commit the rebuilt `research_team/interfaces/web/static/assets/app.js` and `assets/index.css`. `npm run verify` runs the build but never compares it to the committed tree, so a stale console passes verify green.
- **`npm run test:browser` is not in verify and not in CI.** Run it for any task touching measurement or browser lifecycle (Tasks 11, 12).
- **Never run two vitest processes at once** — concurrent runs fail spuriously with coverage temp-file errors naming nothing.
- **Use `uv run` for all Python.** A bare `python -c "import eventsource"` resolves a stale 0.x copy under `~/.pyenv` that lacks `eventsource.ports` entirely. The correct library is the venv's `>=0.14,<0.15`.
- **Env var prefix is `AGENT_`.** `AGENT_INTERACTION_LOG`, `AGENT_INTERACTION_DB`.
- **Aggregate type string is spelled once**, as `BROWSER_SESSION_AGGREGATE_TYPE = "browser_session"` in `research_team/domain/interaction.py`, used both as the events' `aggregate_type` default and in every `StreamId`.
- **Appending does not publish.** Every direct `store.append(...)` must be followed by `await publisher.publish([...])` or a running projection sees nothing until restart. This is silent: nothing raises, nothing logs, the read model is simply empty.
- **The interaction store gets its own `InMemoryEventBus()`.** Never reuse `repository.publisher` — that bus belongs to `sessions.db`, and a bus whose wake-ups refer to a different log than the feed is a bug that looks like flakiness.
- **Coverage thresholds are ratchets.** `src/application/**` requires 66% lines / 46% functions / 50% branches. `src/app/**` is excluded from coverage entirely.
- **Bundle budget:** `app` bucket is 96 kB gzipped, currently 85.3. New code in `src/application/**` and `src/infrastructure/**` charges to `app`.
- **Comments explain why, not what.** State costs, name what a test would fail on, say when something was measured rather than reasoned. If a test would pass with the change reverted, say so in its docstring.
- **Commit messages carry the reasoning** — what was considered and rejected, what the change costs, what is left undone.

---

### Task 1: Configuration — the database path and the kill switch

**Files:**
- Modify: `research_team/infrastructure/config.py`
- Test: `tests/infrastructure/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.interaction_db_path() -> str`, `config.interaction_log_enabled() -> bool`.

Read `config.py` first: its module docstring states that everything the process reads from the environment lives in this one file, and that no layer below it asks the environment anything. Follow that.

`interaction_log_enabled` is **default-on**, which no existing boolean flag in this file is. That inversion needs the docstring below — a reviewer's first instinct will be that it contradicts the `research_run_over_http` reasoning, and the docstring is the answer.

- [ ] **Step 1: Write the failing tests**

Add to `tests/infrastructure/test_config.py`:

```python
def test_the_interaction_database_sits_beside_the_session_one(monkeypatch, tmp_path):
    """Its own file, because it is its own store: positions from two stores
    cannot be ordered against each other."""
    monkeypatch.delenv("AGENT_INTERACTION_DB", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    path = config.interaction_db_path()

    assert path.endswith("/.research-team/interactions.db")
    assert "sessions.db" not in path


def test_the_interaction_database_honours_an_override(monkeypatch):
    monkeypatch.setenv("AGENT_INTERACTION_DB", "/tmp/probe-interactions.db")

    assert config.interaction_db_path() == "/tmp/probe-interactions.db"


def test_the_interaction_log_collects_unless_switched_off(monkeypatch):
    """Default-on, unlike every other boolean in this module. Fails if someone
    "fixes" the inversion to match the others."""
    monkeypatch.delenv("AGENT_INTERACTION_LOG", raising=False)

    assert config.interaction_log_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " off "])
def test_the_interaction_log_switches_off(monkeypatch, value):
    monkeypatch.setenv("AGENT_INTERACTION_LOG", value)

    assert config.interaction_log_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_anything_else_leaves_the_interaction_log_collecting(monkeypatch, value):
    """An empty string is the unset-but-present case and must not read as off."""
    monkeypatch.setenv("AGENT_INTERACTION_LOG", value)

    assert config.interaction_log_enabled() is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_config.py -k interaction -v`
Expected: FAIL — `AttributeError: module 'research_team.infrastructure.config' has no attribute 'interaction_db_path'`

- [ ] **Step 3: Implement**

Add to `research_team/infrastructure/config.py`, beside `default_db_path`:

```python
def interaction_db_path() -> str:
    """Where the interaction log lives. Its own file, not `sessions.db`.

    Separate because `eventsource` derives a store id from the database string
    and every checkpoint position carries it, so a position from one store
    cannot be ordered against a position from another. That makes the split
    structural rather than tidy: no projection can span both stores, which is
    exactly the boundary this feature wants.

    Droppable by design. Unlike `sessions.db` there is no evolution contract
    over these payloads -- when the vocabulary changes, delete the file.
    """
    configured = os.getenv("AGENT_INTERACTION_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "interactions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def interaction_log_enabled() -> bool:
    """Whether the console reports what the user did. On unless switched off.

    The only default-on boolean in this module, and the inversion is
    deliberate. `research_run_over_http` is off by default because unset
    meaning "the route is not there" is a stronger promise than a check inside
    a route that exists -- and that reasoning still holds for anything that
    spends model time or reaches the network on a caller's behalf. This route
    does neither: it writes rows to a local file on the user's own machine.

    Default-on because a log nobody collects is worth nothing, and the whole
    point of this feature is to have a corpus to look at before designing
    against it. Off by default would mean discovering in a month that
    collection was never on.

    What the default costs, stated plainly: `AskSubmitted` carries the
    research prompt, which is a transcript of what someone was thinking
    about. That is the most sensitive field in the system and this variable is
    the answer to it.
    """
    return os.getenv("AGENT_INTERACTION_LOG", "on").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_config.py -k interaction -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/infrastructure/test_config.py -q
git add research_team/infrastructure/config.py tests/infrastructure/test_config.py
git commit
```

Commit message must record: why the path is separate (PositionForeignError, no projection spans both), and why this is the first default-on boolean in the file.

---

### Task 2: The event vocabulary

**Files:**
- Create: `research_team/domain/interaction.py`
- Test: `tests/domain/test_interaction_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `BROWSER_SESSION_AGGREGATE_TYPE: str = "browser_session"`
  - `InteractionEvent(DomainEvent)` — unregistered base carrying the envelope
  - 14 registered event classes: `ViewEntered`, `ViewExited`, `AttentionLost`, `AttentionRegained`, `EntityOpened`, `ProjectSwitched`, `ExtractionQueued`, `ExtractionCancelled`, `DispatchRequested`, `SearchPerformed`, `AskSubmitted`, `ApprovalDecided`, `ActionUndone`, `ActionRetried`, `EmptyResultEncountered`
  - `INTERACTION_EVENTS: tuple[type[InteractionEvent], ...]` — every kind, for the projection and the ingest decoder
  - `TEXT_BEARING_FIELDS: dict[str, tuple[str, ...]]` — the content allowlist, machine-readable

Note: that is 15 classes; the spec's "14 kinds" was written before `EmptyResultEncountered` was split out of the repair group. The set below is authoritative.

**`aggregate_id` IS the browser session id.** Do not add a separate `browser_session_id` field — the row's `aggregate_id` column comes from the `StreamId` while the payload comes from the event, and two fields that must agree will eventually disagree silently. One source.

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/test_interaction_events.py`:

```python
"""What the interaction vocabulary promises.

These are cheap tests over declarations, and they exist because the three
things they check are the three that break silently: an event whose
aggregate_type drifts from the constant lands in a stream nothing projects, a
kind missing from INTERACTION_EVENTS is accepted by no decoder, and a text
field absent from the allowlist is content nobody audited.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import DomainEvent

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    INTERACTION_EVENTS,
    TEXT_BEARING_FIELDS,
    AskSubmitted,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)


def _envelope() -> dict:
    return {
        "aggregate_id": uuid4(),
        "install_id": uuid4(),
        "seq": 1,
        "view": "project/entity",
        "occurred_at": datetime.now(UTC),
    }


def test_every_kind_streams_to_the_one_aggregate_type():
    for event_type in INTERACTION_EVENTS:
        assert event_type.model_fields["aggregate_type"].default == (
            BROWSER_SESSION_AGGREGATE_TYPE
        )


def test_every_kind_is_a_domain_event():
    for event_type in INTERACTION_EVENTS:
        assert issubclass(event_type, DomainEvent)


def test_the_allowlist_names_only_fields_that_exist():
    """A stale allowlist entry is worse than none: it claims an audit of a
    field that is not there."""
    by_name = {event_type.__name__: event_type for event_type in INTERACTION_EVENTS}
    for kind, fields in TEXT_BEARING_FIELDS.items():
        assert kind in by_name, f"{kind} is not an interaction event"
        for field in fields:
            assert field in by_name[kind].model_fields


def test_only_search_and_ask_carry_text():
    """The whole content allowlist, pinned. Widening it is a deliberate change
    and this test is where the decision is recorded."""
    assert TEXT_BEARING_FIELDS == {
        "SearchPerformed": ("query_text",),
        "AskSubmitted": ("query_text",),
    }


def test_a_view_entry_carries_where_and_when():
    event = ViewEntered(**_envelope(), params={"entity_id": "ent_4a1f"})

    assert event.aggregate_type == BROWSER_SESSION_AGGREGATE_TYPE
    assert event.view == "project/entity"
    assert event.params["entity_id"] == "ent_4a1f"


def test_a_view_exit_reports_hidden_time_separately_from_dwell():
    """Reported alongside rather than subtracted, so a consumer picks which it
    wants and the raw figures stay inspectable."""
    event = ViewExited(**_envelope(), dwell_ms=240_000, hidden_ms=180_000)

    assert event.dwell_ms == 240_000
    assert event.hidden_ms == 180_000


def test_domain_context_is_optional():
    """Plenty of interaction happens with no project in scope -- the tree view,
    the session list. A required project_id would make those unrecordable."""
    event = ViewEntered(**_envelope(), params={})

    assert event.project_id is None
    assert event.session_id is None


def test_a_search_carries_its_text_and_its_result_count():
    event = SearchPerformed(**_envelope(), query_text="diocletian", result_count=0)

    assert event.query_text == "diocletian"
    assert event.result_count == 0


def test_an_ask_carries_its_prompt():
    """The most sensitive field in the system. Present because near-duplicate
    detection is the strongest friction signal and lengths cannot express it;
    AGENT_INTERACTION_LOG=0 is the answer to it."""
    event = AskSubmitted(**_envelope(), query_text="what did the tetrarchy change")

    assert event.query_text == "what did the tetrarchy change"


def test_seq_is_required():
    """Ordering authority. An event without it cannot be placed, and a default
    would silently place it at zero."""
    envelope = _envelope()
    del envelope["seq"]

    with pytest.raises(ValueError):
        ViewEntered(**envelope, params={})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_interaction_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.domain.interaction'`

- [ ] **Step 3: Implement**

Create `research_team/domain/interaction.py`:

```python
"""What the user did in the console, as events in their own store.

**These payloads carry no evolution contract, and that is the point.**
`domain/events.py` opens with a promise that events already written stay
readable, because that log is the domain's history and is never rewritten.
This log is not history. It is observation: high-volume, derived from a UI
that will be rewritten, and droppable without degrading a single feature.

So when a field here changes shape, the recovery is:

    rm ~/.research-team/interactions.db

Nothing reads an old payload, nothing migrates, and no
`test_schema_evolution.py` case guards these. Do not add one -- a contract
here would buy nothing and cost every future vocabulary change.

The stream is a browser session, and `aggregate_id` *is* the browser session
id. There is deliberately no separate `browser_session_id` field: the stored
`aggregate_id` column comes from the `StreamId` while the payload comes from
the event, so two fields that must agree are two fields that will eventually
disagree without saying so.

There is no aggregate. Nothing here enforces an invariant -- the browser
reports what happened and the server records it -- so events go straight to
the store with `ExpectedVersion.any_()`, the way
`infrastructure/knowledge/ontology_recorder.py` does. The consequence is that
publishing is this feature's own job; see that module's docstring for what
forgetting it looks like.
"""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import Field

BROWSER_SESSION_AGGREGATE_TYPE = "browser_session"
"""The stream every interaction event is appended to, named rather than
spelled at each site.

There is no `BrowserSession` aggregate to take the name from -- deliberately,
since nothing invariant is being protected -- so the constant stands in for
what would otherwise be a class attribute, and the `StreamId` category cannot
drift from the events' own default.
"""


class InteractionEvent(DomainEvent):
    """The envelope every interaction event carries.

    Not registered: it is never appended on its own. Subclasses are.
    """

    aggregate_type: str = BROWSER_SESSION_AGGREGATE_TYPE

    install_id: UUID
    """Persisted in the browser, surviving restarts, so a count can say "on
    nine separate days" rather than "in nine separate tabs".

    Pseudonymous, and the exact thing that becomes real identity if this
    product ever grows past one user. Named here so that growth is a decision
    rather than an accident.
    """

    seq: int
    """The ordering authority, monotonic within one browser session.

    Not `occurred_at`, which comes from a clock that can be skewed or moved
    mid-session, and not arrival order, which batching makes meaningless. A
    counter survives both.
    """

    view: str
    """Where the user was: a route name, or `project/<facet>` for the facets
    the project page switches between."""

    project_id: UUID | None = None
    session_id: UUID | None = None
    """What the interaction was about, where anything was. Optional because
    plenty of interaction happens with no project in scope."""

    received_at: Any | None = None
    """When the server took delivery, set at ingest.

    Kept as a cross-check rather than as truth: a batch whose client clock
    disagrees wildly with its arrival is suspect, and that is worth being able
    to notice. Typed loosely because it is set by the edge, never by a caller.
    """


@register_event
class ViewEntered(InteractionEvent):
    """A view became current."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Ids only -- which entity, which topic. Never free text."""


@register_event
class ViewExited(InteractionEvent):
    """A view stopped being current, and for how long it had been.

    Emitted on route change and on the page-hide flush, so a session that ends
    by closing the tab still gets a terminal dwell. Without that, every
    session's last view has no duration -- which is the view where friction is
    most likely.
    """

    dwell_ms: int
    """Wall time in view, from `performance.now()` rather than a wall clock:
    monotonic, so a system clock change cannot produce a negative duration."""

    hidden_ms: int = 0
    """How much of `dwell_ms` the tab was backgrounded for.

    Reported alongside rather than subtracted so the consumer chooses. Without
    it, "stalled on this view for four minutes" -- the archetypal friction
    signal -- is indistinguishable from "went to lunch", and the whole
    attention half of this log is worthless.
    """


@register_event
class AttentionLost(InteractionEvent):
    """The tab was backgrounded."""


@register_event
class AttentionRegained(InteractionEvent):
    """The tab came back."""


@register_event
class EntityOpened(InteractionEvent):
    entity_id: str
    source: str
    """How they got there: graph | search | timeline | link. The same entity
    reached three ways is three different stories about the UI."""


@register_event
class ProjectSwitched(InteractionEvent):
    to_project_id: UUID
    from_project_id: UUID | None = None


@register_event
class ExtractionQueued(InteractionEvent):
    source_id: str


@register_event
class ExtractionCancelled(InteractionEvent):
    source_id: str


@register_event
class DispatchRequested(InteractionEvent):
    topic_id: UUID
    action: str


@register_event
class SearchPerformed(InteractionEvent):
    query_text: str
    """On the content allowlist. The strongest friction signal is "nearly the
    same search again, slightly differently", and a length cannot express
    nearly-the-same."""

    result_count: int


@register_event
class AskSubmitted(InteractionEvent):
    query_text: str
    """On the content allowlist, and the most sensitive field in this system:
    a research prompt is a transcript of what someone was thinking about.

    Included for the same near-duplicate reason as `SearchPerformed`, and the
    cost is real rather than theoretical. `AGENT_INTERACTION_LOG=0` is the
    answer, and it is one variable.
    """


@register_event
class ApprovalDecided(InteractionEvent):
    """A gated tool call was decided, and how the deciding went.

    Deliberately duplicates nothing from the domain's `ToolCallDecided`, which
    already records what was decided. What this adds is UI-only and is the
    distinction `docs/direction.md` §3 turns on: a decision in 400ms without
    opening the details is click-through, and a decision after twelve seconds
    with them open is deliberation. Counting approvals without it produces a
    confident and misleading signal.
    """

    decision: str
    latency_ms: int
    expanded_details: bool
    review_id: UUID | None = None


@register_event
class ActionUndone(InteractionEvent):
    """Repair, and per §3 the strong signal -- given its own kind so it is
    never inferred from a pair of other events."""

    action_kind: str
    target_id: str | None = None


@register_event
class ActionRetried(InteractionEvent):
    action_kind: str
    attempt_number: int


@register_event
class EmptyResultEncountered(InteractionEvent):
    """Somewhere the product had nothing to show. Structural on purpose: the
    count and the place are the signal, and `SearchPerformed` already carries
    the text where text is warranted."""

    where: str
    query_length: int = 0


INTERACTION_EVENTS: tuple[type[InteractionEvent], ...] = (
    ViewEntered,
    ViewExited,
    AttentionLost,
    AttentionRegained,
    EntityOpened,
    ProjectSwitched,
    ExtractionQueued,
    ExtractionCancelled,
    DispatchRequested,
    SearchPerformed,
    AskSubmitted,
    ApprovalDecided,
    ActionUndone,
    ActionRetried,
    EmptyResultEncountered,
)
"""Every kind, in one tuple.

The ingest decoder and the projection both enumerate the vocabulary, and a
kind added to the module but not to this tuple is a kind the route rejects and
nothing records -- with no error naming the omission.
"""

TEXT_BEARING_FIELDS: dict[str, tuple[str, ...]] = {
    "SearchPerformed": ("query_text",),
    "AskSubmitted": ("query_text",),
}
"""The content allowlist, machine-readable and complete.

Everything else in this vocabulary is structure: ids, view names, counts,
durations. Free text is otherwise recorded as shape -- `query_length`,
`result_count` -- which is enough to find a zero-result search without knowing
what was searched.

Machine-readable rather than prose so a test can pin it. Widening it is a
deliberate change with a reason attached, not a judgement call at a call site.
"""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/domain/test_interaction_events.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Check the feed-coverage guards**

`tests/infrastructure/test_feed_coverage.py` and `UNROUTED_AGGREGATE_TYPES` in `research_team/infrastructure/persistence/event_store.py` enumerate aggregate types for the *sessions* store. Run the suite and see whether either now fails:

Run: `uv run pytest tests/infrastructure/test_feed_coverage.py -v`

If it fails, `browser_session` needs registering there — read what the guard is asserting before adding it, and if the guard is about `sessions.db` only, add a comment saying why `browser_session` is exempt rather than adding it to a list it does not belong in.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/domain -q
git add research_team/domain/interaction.py tests/domain/test_interaction_events.py
git commit
```

Commit message must record: no evolution contract and why (`rm interactions.db` is the recovery), why `aggregate_id` is the session id with no duplicate field, and why `ApprovalDecided` is not a duplicate of `ToolCallDecided`.

---

### Task 3: The read model and its store

**Files:**
- Create: `research_team/infrastructure/persistence/interaction_log.py`
- Test: `tests/infrastructure/test_interaction_log.py`

**Interfaces:**
- Consumes: `BROWSER_SESSION_AGGREGATE_TYPE`, `INTERACTION_EVENTS` (Task 2).
- Produces:
  - `InteractionEventRow(ReadModel)` with `__table_name__ = "interaction_events"`
  - `InteractionEventRow.row_id(browser_session_id: UUID, seq: int) -> UUID`
  - `InteractionLogStore` with `open(db_path, checkpoint_repo=None, dlq_repo=None, tracer=None)`, `events(browser_session_id)`, `count()`, `truncate()`, `close()`

Read `research_team/infrastructure/persistence/check_telemetry.py` first — it is the smallest trio in the repo and this task copies its shape.

**Derive the row id from `(browser_session_id, seq)` via `uuid5`.** That is what makes duplicate delivery idempotent: `sendBeacon` can double-deliver and a timer flush can race a page-hide flush, so duplicates are expected rather than exceptional. A random row id would store both copies.

**Do not name a column `check`, `order`, `group`, `index` or any other SQLite keyword** — the generated DDL does not quote identifiers. `check_telemetry.py:66-84` records that costing real time.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_interaction_log.py`:

```python
"""The one table this feature writes.

Every assertion here is on a stored row rather than on a call succeeding.
`eventsource.replay` counts an event no projection handles as APPLIED -- so a
test asserting that ingest returned 202, or that nothing raised, passes with
the projection deleted entirely and proves nothing.
"""

from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite

from research_team.domain.interaction import (
    AskSubmitted,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)
from research_team.infrastructure.persistence.interaction_log import (
    InteractionEventRow,
    InteractionLogStore,
)


def _view_entered(session_id, seq=1, **over):
    return ViewEntered(
        aggregate_id=session_id,
        install_id=uuid4(),
        seq=seq,
        view="project/entity",
        occurred_at=datetime.now(UTC),
        params={"entity_id": "ent_4a1f"},
        **over,
    )


async def test_a_stored_event_keeps_its_envelope_and_its_payload(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        event = _view_entered(browser_session, seq=7)

        await store.record(event)

        rows = await store.events(browser_session)
        assert len(rows) == 1
        assert rows[0].kind == "ViewEntered"
        assert rows[0].seq == 7
        assert rows[0].view == "project/entity"
        assert rows[0].payload["params"]["entity_id"] == "ent_4a1f"
    finally:
        await store.close()


async def test_the_same_sequence_number_twice_is_one_row(db_path):
    """sendBeacon can double-deliver, and a timer flush can race a page-hide
    flush. Duplicates are expected, so the row id is derived from
    (browser_session_id, seq) rather than random.

    Fails with the uuid5 derivation replaced by uuid4: two rows.
    """
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()

        await store.record(_view_entered(browser_session, seq=3))
        await store.record(_view_entered(browser_session, seq=3))

        assert len(await store.events(browser_session)) == 1
    finally:
        await store.close()


async def test_the_same_sequence_number_in_two_sessions_is_two_rows(db_path):
    """seq is monotonic *within* a browser session, so it collides across
    them. Fails if the row id is derived from seq alone."""
    store = await InteractionLogStore.open(db_path)
    try:
        first, second = uuid4(), uuid4()

        await store.record(_view_entered(first, seq=1))
        await store.record(_view_entered(second, seq=1))

        assert len(await store.events(first)) == 1
        assert len(await store.events(second)) == 1
    finally:
        await store.close()


async def test_events_come_back_in_sequence_order(db_path):
    """Ordered by seq, not by insertion: a batch can arrive out of order and
    the whole point of seq is that this survives it."""
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()

        await store.record(_view_entered(browser_session, seq=3))
        await store.record(_view_entered(browser_session, seq=1))
        await store.record(_view_entered(browser_session, seq=2))

        assert [row.seq for row in await store.events(browser_session)] == [1, 2, 3]
    finally:
        await store.close()


async def test_a_dwell_survives_the_round_trip(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(
            ViewExited(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=2,
                view="project/timeline",
                occurred_at=datetime.now(UTC),
                dwell_ms=240_000,
                hidden_ms=180_000,
            )
        )

        row = (await store.events(browser_session))[0]
        assert row.payload["dwell_ms"] == 240_000
        assert row.payload["hidden_ms"] == 180_000
    finally:
        await store.close()


async def test_text_survives_for_the_two_kinds_that_carry_it(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(
            SearchPerformed(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=1,
                view="project/entity",
                occurred_at=datetime.now(UTC),
                query_text="tetrarchy",
                result_count=0,
            )
        )
        await store.record(
            AskSubmitted(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=2,
                view="project/ask",
                occurred_at=datetime.now(UTC),
                query_text="what changed",
            )
        )

        rows = await store.events(browser_session)
        assert rows[0].payload["query_text"] == "tetrarchy"
        assert rows[1].payload["query_text"] == "what changed"
    finally:
        await store.close()


async def test_a_database_written_before_a_field_existed_gains_its_column(db_path):
    """Adding a field to a ReadModel does not add a column to a database that
    already exists -- CREATE TABLE IF NOT EXISTS does nothing to a table that
    is there. This has shipped once in this repository, as a 500 on every
    request against a table every test built from nothing.

    Here the recovery is to drop the file, but the widening still has to work
    for anyone who does not, and this proves apply_schema is being called.
    """
    connection = await aiosqlite.connect(db_path)
    try:
        await connection.execute(
            "CREATE TABLE interaction_events (id TEXT PRIMARY KEY, kind TEXT)"
        )
        await connection.commit()
    finally:
        await connection.close()

    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(_view_entered(browser_session))

        assert len(await store.events(browser_session)) == 1
    finally:
        await store.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_interaction_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.infrastructure.persistence.interaction_log'`

- [ ] **Step 3: Implement the row and the store**

Create `research_team/infrastructure/persistence/interaction_log.py`:

```python
"""One flat table holding every interaction event.

Flat, with a JSON payload column, rather than a table per kind. The
vocabulary will churn, the database is droppable, and SQLite's JSON operators
are enough for the hand queries this feature exists to enable:

    sqlite3 ~/.research-team/interactions.db \\
      "select seq, kind, view, json_extract(payload,'$.dwell_ms')
         from interaction_events where browser_session_id = '...' order by seq"

Per-kind tables would be the right call once a consumer exists and its
queries are known. Today there is no consumer, and guessing at its shape is
what this design is arranged to avoid.
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

import aiosqlite
from eventsource import DeclarativeProjection, ReadModel, handles
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository
from pydantic import Field, field_validator

from research_team.domain.interaction import (
    INTERACTION_EVENTS,
    InteractionEvent,
)
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    apply_schema,
)

INTERACTION_LOG_NAMESPACE = UUID("6f1d9b02-3e7c-4a58-9c31-0d5b7a8e4f12")


class InteractionEventRow(ReadModel):
    """One interaction, as stored.

    `id` is derived rather than random -- see `row_id`. No column is named
    after a SQLite keyword: the generated DDL does not quote identifiers, and
    `check_telemetry.py` records what that costs when you forget.
    """

    __table_name__ = "interaction_events"

    browser_session_id: UUID
    install_id: UUID
    seq: int
    kind: str
    view: str
    occurred_at: datetime
    received_at: datetime | None = None
    project_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    """Everything specific to the kind. SQLite hands this back as JSON text,
    hence the decoder below."""

    @field_validator("payload", mode="before")
    @classmethod
    def _decode_payload(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(browser_session_id: UUID, seq: int) -> UUID:
        """Derived from the pair, so a duplicate delivery overwrites rather
        than duplicating.

        `sendBeacon` can deliver twice and a timer flush can race a page-hide
        flush, so duplicates are the expected case. A random id would store
        both, and every count over this table would be quietly wrong.

        The pair rather than `seq` alone: seq is monotonic within one browser
        session and collides freely across them.
        """
        return uuid5(INTERACTION_LOG_NAMESPACE, f"{browser_session_id}:{seq}")


_ENVELOPE_FIELDS = frozenset(InteractionEvent.model_fields) | {"aggregate_id"}


def row_for(event: InteractionEvent) -> InteractionEventRow:
    """The row one event becomes.

    Split out of the projection so the store can write a row without a
    subscription, which is what makes Task 3's tests independent of Task 4.
    """
    payload = {
        name: value
        for name, value in event.model_dump(mode="json").items()
        if name not in _ENVELOPE_FIELDS and name not in {"event_id", "event_version"}
    }
    return InteractionEventRow(
        id=InteractionEventRow.row_id(event.aggregate_id, event.seq),
        browser_session_id=event.aggregate_id,
        install_id=event.install_id,
        seq=event.seq,
        kind=type(event).__name__,
        view=event.view,
        occurred_at=event.occurred_at,
        received_at=event.received_at,
        project_id=event.project_id,
        session_id=event.session_id,
        payload=payload,
    )


class InteractionLogStore:
    """The table, and the few reads worth having before a consumer exists."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[InteractionEventRow],
    ) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(
        cls,
        db_path: str,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> "InteractionLogStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, InteractionEventRow)
        # Two indexes for the two reads this log is for: a stream read, which
        # is what prefix prediction needs, and an aggregate read by kind over
        # time, which is what friction counting needs.
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interaction_events_stream "
            f"ON {InteractionEventRow.table_name()}(browser_session_id, seq)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interaction_events_kind "
            f"ON {InteractionEventRow.table_name()}(kind, occurred_at)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, InteractionEventRow, tracer)
        return cls(connection, rows)

    @property
    def rows(self) -> ReadModelRepository[InteractionEventRow]:
        return self._rows

    async def record(self, event: InteractionEvent) -> None:
        """Write one event's row, replacing any row already there for its
        (browser_session_id, seq)."""
        await self._rows.save(row_for(event))

    async def events(self, browser_session_id: UUID) -> list[InteractionEventRow]:
        found = await self._rows.find(
            Query(
                filters=[
                    Filter(
                        field="browser_session_id",
                        operator="eq",
                        value=browser_session_id,
                    )
                ]
            )
        )
        return sorted(found, key=lambda row: row.seq)

    async def count(self) -> int:
        return len(await self._rows.find(None))

    async def truncate(self) -> None:
        await self._connection.execute(
            f"DELETE FROM {InteractionEventRow.table_name()}"
        )
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()
```

Note on `Filter`: pass the real `UUID`, not `str(...)`. `check_telemetry.py:172-174` records that a stringified value matches nothing in the in-memory repository.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_interaction_log.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Prove the duplicate test red**

Temporarily change `row_id` to `return uuid4()` (add the import), run
`uv run pytest tests/infrastructure/test_interaction_log.py -k twice -v`,
confirm FAIL, then revert. This is the convention here: prove a test red
before trusting it green.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/infrastructure/test_interaction_log.py -q
git add research_team/infrastructure/persistence/interaction_log.py tests/infrastructure/test_interaction_log.py
git commit
```

---

### Task 4: The projection and its runner

**Files:**
- Modify: `research_team/infrastructure/persistence/interaction_log.py`
- Test: `tests/infrastructure/test_interaction_log.py`

**Interfaces:**
- Consumes: `InteractionEventRow`, `row_for`, `InteractionLogStore` (Task 3).
- Produces:
  - `InteractionLogProjection(DeclarativeProjection)` — `@handles` for all 15 kinds
  - `InteractionLogRunner(store, db_path, bus, tracer=None)` with `start()`, `stop()`, `caught_up(timeout=10.0)`, `failures(limit=100)`, `rebuild()`, `events(browser_session_id)`, `count()`, and `projection_name` property

Copy `CheckTelemetryRunner` (`check_telemetry.py:303-453`) for lifecycle. **Use the global-position `caught_up`** (`CorpusRunner`, `read_models.py:1429-1447`), not the aggregate-scoped one — this store holds only `browser_session`, so the store's global end is by definition a position the projection reaches. Document the precondition in the docstring.

`DeclarativeProjection` needs one `@handles` per event type; a kind with no handler is a kind nothing records, and per `replay`'s contract it still counts as APPLIED, so nothing complains.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_interaction_log.py`:

```python
from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    INTERACTION_EVENTS,
)
from research_team.infrastructure.persistence.interaction_log import (
    InteractionLogProjection,
    InteractionLogRunner,
)


def test_the_projection_handles_every_kind_in_the_vocabulary():
    """A kind with no handler is silently unrecorded: replay counts an event
    no projection handles as APPLIED, so nothing raises and the read model is
    simply missing rows.

    Fails when a kind is added to INTERACTION_EVENTS and not to the
    projection -- which is the whole point.
    """
    handled = InteractionLogProjection(
        InMemoryReadModelRepository(InteractionEventRow)
    ).subscribed_to()

    assert set(INTERACTION_EVENTS) == set(handled)


async def test_the_projection_writes_a_row():
    rows = InMemoryReadModelRepository(InteractionEventRow)
    projection = InteractionLogProjection(rows)
    browser_session = uuid4()

    await projection.handle(_view_entered(browser_session, seq=4))

    stored = await rows.find(None)
    assert len(stored) == 1
    assert stored[0].seq == 4
    assert stored[0].kind == "ViewEntered"


async def test_the_runner_follows_its_own_store(db_path, tmp_path):
    """The end-to-end shape of this feature's write path: append to the
    interaction store, publish, and find a row.

    The publish is not decoration. Appending does not deliver -- the bus is a
    wake-up signal and the store owns ordering -- so an append nobody
    publishes reaches a running projection only on restart. Drop the publish
    line and this test fails with an empty list, which is exactly how it would
    fail in production.
    """
    interaction_db = str(tmp_path / "interactions.db")
    store = SQLiteEventStore(interaction_db)
    bus = InMemoryEventBus()
    runner = InteractionLogRunner(store, interaction_db, bus)
    await runner.start()
    try:
        browser_session = uuid4()
        event = _view_entered(browser_session, seq=1)

        await store.append(
            StreamId(browser_session, BROWSER_SESSION_AGGREGATE_TYPE),
            [event],
            ExpectedVersion.any_(),
        )
        await bus.publish([event])
        await runner.caught_up()

        rows = await runner.events(browser_session)
        assert len(rows) == 1
        assert rows[0].view == "project/entity"
    finally:
        await runner.stop()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/test_interaction_log.py -k "projection or runner" -v`
Expected: FAIL — `ImportError: cannot import name 'InteractionLogProjection'`

- [ ] **Step 3: Implement the projection**

Add to `research_team/infrastructure/persistence/interaction_log.py`:

```python
class InteractionLogProjection(DeclarativeProjection):
    """Every interaction event becomes one row.

    One handler per kind rather than a single catch-all, because
    `DeclarativeProjection` routes by declared type and derives
    `subscribed_to()` from these decorators -- which is also what the live
    subscription uses to decide which bus events wake it. A kind absent from
    here is a kind that neither wakes the runner nor lands in the table, and
    nothing reports it.

    The handlers are identical because the row shape is uniform; `row_for`
    holds the one implementation.
    """

    def __init__(
        self,
        rows: ReadModelRepository[InteractionEventRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    async def _record(self, event: InteractionEvent) -> None:
        await self._rows.save(row_for(event))
```

Then one decorated method per kind. Write all fifteen explicitly — a loop
building them dynamically would defeat `subscribed_to()` and defeat the
grep-ability that makes the vocabulary auditable:

```python
    @handles(ViewEntered)
    async def _on_view_entered(self, event: ViewEntered) -> None:
        await self._record(event)

    @handles(ViewExited)
    async def _on_view_exited(self, event: ViewExited) -> None:
        await self._record(event)
```

…and the same for `AttentionLost`, `AttentionRegained`, `EntityOpened`,
`ProjectSwitched`, `ExtractionQueued`, `ExtractionCancelled`,
`DispatchRequested`, `SearchPerformed`, `AskSubmitted`, `ApprovalDecided`,
`ActionUndone`, `ActionRetried`, `EmptyResultEncountered`. Import each from
`research_team.domain.interaction`.

- [ ] **Step 4: Implement the runner**

Copy `CheckTelemetryRunner`'s structure exactly, with these differences:
`InteractionLogStore.open` instead of `CheckTelemetryStore.open`, and the
global-position `caught_up`:

```python
class InteractionLogRunner:
    """Keeps `interaction_events` following the interaction log.

    Takes its own store and its own bus. Passing the sessions store's bus
    here would give the subscription wake-ups about a log it is not reading,
    which fails as silence rather than as an error.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ) -> None:
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._log: InteractionLogStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return InteractionLogProjection.__name__

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Wait until every appended event has reached the table.

        Compares global positions rather than filtering the feed by aggregate
        type, and that is only correct because of a precondition: this store
        holds `browser_session` and nothing else. The scoped variants
        elsewhere in this repository exist because `sessions.db` is shared by
        eight aggregate types, and a global wait there never drains.

        **The moment a second category lands in this store, this must become
        the scoped form** -- see `OntologyRunner.caught_up`, which also
        filters by event type because aggregate type alone was not fine
        enough. The failure mode of getting it wrong is a 10s TimeoutError
        naming nothing about the cause.
        """
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            reached = self._subscription.last_processed_position
            if reached is not None and not reached < target:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the interaction log projection did not reach {target} within {timeout}s"
        )
```

`start()`, `stop()`, `failures()` and `rebuild()` follow `CheckTelemetryRunner`
verbatim with the type substitutions. Add delegating readers that raise when
unstarted, following `CorpusRunner`:

```python
    async def events(self, browser_session_id: UUID) -> list[InteractionEventRow]:
        if self._log is None:
            raise RuntimeError("the interaction log projection has not been started")
        return await self._log.events(browser_session_id)

    async def count(self) -> int:
        if self._log is None:
            raise RuntimeError("the interaction log projection has not been started")
        return await self._log.count()
```

Add the imports `check_telemetry.py` uses for the runner: `asyncio`,
`FeedReadOptions` (only if you end up scoping), `InMemoryEventBus`,
`SQLCheckpointRepository`, `SQLDLQRepository`, `create_async_engine`,
`SQLiteEventStore`, `SubscriptionConfig`, `SubscriptionManager`, `DLQEntry`,
`AsyncEngine`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_interaction_log.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Prove the publish test red**

Comment out `await bus.publish([event])` in
`test_the_runner_follows_its_own_store`, run it, confirm it fails with an
empty list — this is the production failure mode, and the test is worthless
if it does not catch it. Restore the line.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/infrastructure/test_interaction_log.py -q
git add research_team/infrastructure/persistence/interaction_log.py tests/infrastructure/test_interaction_log.py
git commit
```

Commit message must record: why fifteen explicit handlers rather than a loop, and why `caught_up` is the global variant plus the precondition that makes it correct.

---

### Task 5: The recorder — append and publish

**Files:**
- Create: `research_team/infrastructure/interaction/__init__.py`
- Create: `research_team/infrastructure/interaction/recorder.py`
- Test: `tests/infrastructure/test_interaction_recorder.py`

**Interfaces:**
- Consumes: `BROWSER_SESSION_AGGREGATE_TYPE`, `InteractionEvent` (Task 2).
- Produces: `EventStoreInteractionRecorder(store, publisher)` with
  `async def record(self, events: Sequence[InteractionEvent]) -> int`.

Read `research_team/infrastructure/knowledge/ontology_recorder.py` first and copy it. It is the same situation — a stream with no aggregate, appended directly — and its docstring records what forgetting the publish looked like in production.

`record` groups events by `aggregate_id` and appends one batch per stream,
because `append` takes a single `StreamId`. It publishes once, after all
appends, and returns how many events were written.

- [ ] **Step 1: Write the failing tests**

```python
"""Appending, and the publish that has to accompany it."""

from datetime import UTC, datetime
from uuid import uuid4

from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import ViewEntered
from research_team.infrastructure.interaction.recorder import (
    EventStoreInteractionRecorder,
)


def _event(browser_session, seq):
    return ViewEntered(
        aggregate_id=browser_session,
        install_id=uuid4(),
        seq=seq,
        view="home",
        occurred_at=datetime.now(UTC),
        params={},
    )


async def test_a_batch_lands_in_the_store(tmp_path):
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    bus = InMemoryEventBus()
    recorder = EventStoreInteractionRecorder(store, bus)
    browser_session = uuid4()

    written = await recorder.record(
        [_event(browser_session, 1), _event(browser_session, 2)]
    )

    assert written == 2


async def test_recording_publishes_every_event(tmp_path):
    """Appending is not delivering, and the difference is silent: a running
    projection sees an unpublished append only after a restart.

    Fails with the publish removed -- nothing else does, which is why this
    test exists rather than relying on the store assertion above.
    """
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    bus = InMemoryEventBus()
    published: list = []
    bus.subscribe(ViewEntered, lambda event: published.append(event))
    recorder = EventStoreInteractionRecorder(store, bus)
    browser_session = uuid4()

    await recorder.record([_event(browser_session, 1)])

    assert len(published) == 1


async def test_two_browser_sessions_go_to_two_streams(tmp_path):
    """One append per stream, because append takes one StreamId. A single
    call with events from two sessions would put one session's events in the
    other's stream."""
    store = SQLiteEventStore(str(tmp_path / "interactions.db"))
    recorder = EventStoreInteractionRecorder(store, InMemoryEventBus())
    first, second = uuid4(), uuid4()

    written = await recorder.record([_event(first, 1), _event(second, 1)])

    assert written == 2


async def test_an_empty_batch_writes_nothing_and_does_not_raise(tmp_path):
    """The store raises on an empty batch, and a flush can legitimately carry
    nothing once the client drops malformed events."""
    recorder = EventStoreInteractionRecorder(
        SQLiteEventStore(str(tmp_path / "interactions.db")), InMemoryEventBus()
    )

    assert await recorder.record([]) == 0
```

Check `InMemoryEventBus.subscribe`'s real signature before relying on it
(`eventsource/adapters/memory/bus.py`); if it differs, assert on publish via
a `unittest.mock.AsyncMock` wrapper around `bus.publish` instead.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/test_interaction_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
"""The only place this feature appends.

No aggregate: nothing here enforces an invariant. The browser reports what
happened and there is no rule that could reject it, so events go straight to
the store with `ExpectedVersion.any_()` rather than through a
`DeciderAggregate`. `infrastructure/knowledge/ontology_recorder.py` made the
same call for the same reason and is worth reading alongside this.

**Appending is not delivering, and the difference is silent.** The store owns
ordering; the bus is only a wake-up telling a subscription that new work may
exist. An append nobody publishes reaches a running projection on the next
restart or rebuild and not before -- so `record` publishes, every time, and
the test that proves it is
`test_recording_publishes_every_event`. Every other writer in this codebase
gets this for free from `AggregateRepository(event_publisher=...)`; a recorder
with no aggregate has to do the publishing half itself.
"""

from collections import defaultdict
from collections.abc import Sequence

from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    InteractionEvent,
)


class EventStoreInteractionRecorder:
    def __init__(
        self, store: SQLiteEventStore, publisher: InMemoryEventBus
    ) -> None:
        self._store = store
        self._publisher = publisher

    async def record(self, events: Sequence[InteractionEvent]) -> int:
        """Append a batch and publish it. Returns how many were written.

        Grouped by browser session because `append` takes one `StreamId`, and
        one flush can carry events from more than one session -- rare, but a
        second tab plus a page-hide race produces it.

        An empty batch is a no-op rather than an error: `append` rejects an
        empty sequence, and a flush that carried only malformed events
        legitimately arrives with nothing left.
        """
        if not events:
            return 0

        by_session: dict = defaultdict(list)
        for event in events:
            by_session[event.aggregate_id].append(event)

        for browser_session_id, batch in by_session.items():
            await self._store.append(
                StreamId(browser_session_id, BROWSER_SESSION_AGGREGATE_TYPE),
                batch,
                # The stream protects no invariant, so there is no version to
                # expect. A concurrent second tab appending to its own stream
                # cannot conflict with this one anyway.
                ExpectedVersion.any_(),
            )

        await self._publisher.publish(list(events))
        return len(events)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/infrastructure/test_interaction_recorder.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/infrastructure -q
git add research_team/infrastructure/interaction tests/infrastructure/test_interaction_recorder.py
git commit
```

---

### Task 6: Composition — the second store, wired and started

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/integration/test_interaction_log_wiring.py`

**Interfaces:**
- Consumes: `InteractionLogRunner` (Task 4), `EventStoreInteractionRecorder` (Task 5), `config.interaction_db_path` (Task 1).
- Produces: on `Application` — `interaction_log: InteractionLogRunner`, `interaction_recorder: EventStoreInteractionRecorder`, and `async def interaction_log_caught_up(self) -> None`.
- Also produces: a keyword-only `interaction_db_path: str | None = None` parameter on `build_application`.

**The integration test is the point of this task.** A hand-publishing unit test cannot catch a runner that is never constructed or never started — `composition.py`'s own comment says a projection wired elsewhere is a projection somebody forgets to start, and the entity-definitions work shipped exactly that: `EntityDefinitionRunner` never constructed, every request an empty cache miss, every test green.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_interaction_log_wiring.py`:

```python
"""That a composed application actually records interaction.

This test exists because the unit tests structurally cannot catch the two
ways this feature dies: a runner constructed but never started, and a
recorder appending to a store whose projection nobody subscribed. Both leave
every other test green and the table empty.
"""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.composition import build_application
from research_team.domain.interaction import ViewEntered


async def test_a_composed_application_stores_what_the_browser_reported(
    db_path, tmp_path
):
    interaction_db = str(tmp_path / "interactions.db")
    application = build_application(
        db_path=db_path, interaction_db_path=interaction_db
    )
    await application.start()
    try:
        browser_session = uuid4()

        await application.interaction_recorder.record(
            [
                ViewEntered(
                    aggregate_id=browser_session,
                    install_id=uuid4(),
                    seq=1,
                    view="project/timeline",
                    occurred_at=datetime.now(UTC),
                    params={},
                )
            ]
        )
        await application.interaction_log_caught_up()

        rows = await application.interaction_log.events(browser_session)
        assert len(rows) == 1
        assert rows[0].view == "project/timeline"
    finally:
        await application.close()


async def test_the_interaction_store_is_not_the_session_store(db_path, tmp_path):
    """Two stores, and the interaction one must not be writing into
    sessions.db. Fails if interaction_db_path is ignored and the runner is
    handed the session store."""
    import aiosqlite

    interaction_db = str(tmp_path / "interactions.db")
    application = build_application(
        db_path=db_path, interaction_db_path=interaction_db
    )
    await application.start()
    try:
        await application.interaction_recorder.record(
            [
                ViewEntered(
                    aggregate_id=uuid4(),
                    install_id=uuid4(),
                    seq=1,
                    view="home",
                    occurred_at=datetime.now(UTC),
                    params={},
                )
            ]
        )
        await application.interaction_log_caught_up()
    finally:
        await application.close()

    connection = await aiosqlite.connect(db_path)
    try:
        found = await (
            await connection.execute(
                "SELECT count(*) FROM events WHERE aggregate_type = 'browser_session'"
            )
        ).fetchone()
        assert found[0] == 0
    finally:
        await connection.close()
```

If the sessions events table is not named `events`, read
`research_team/infrastructure/persistence/event_store.py` for the real name
and fix the query.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_interaction_log_wiring.py -v`
Expected: FAIL — `TypeError: build_application() got an unexpected keyword argument 'interaction_db_path'`

- [ ] **Step 3: Implement the wiring**

In `research_team/composition.py`:

1. Add `interaction_db_path: str | None = None` to `build_application`'s
   keyword-only parameters.
2. Resolve it beside `resolved_path`:

```python
    resolved_interaction_path = (
        interaction_db_path
        if interaction_db_path is not None
        else config.interaction_db_path()
    )
```

3. Build the second store in **its own block**, after the existing runner
   block, with this comment:

```python
    # A second store, and its own bus. Not a second projection over the
    # sessions store: `eventsource` derives a store id from the database
    # string and every position carries it, so nothing can order a position
    # from one against the other -- which is the boundary this feature wants
    # rather than an obstacle to it.
    #
    # Its own `InMemoryEventBus` for the same reason. Handing this runner the
    # sessions bus would give its subscription wake-ups about a log it is not
    # reading, and that fails as silence.
    interaction_store = SQLiteEventStore(resolved_interaction_path)
    interaction_bus = InMemoryEventBus()
    interaction_log = InteractionLogRunner(
        interaction_store,
        resolved_interaction_path,
        interaction_bus,
        resolved_tracer,
    )
    interaction_recorder = EventStoreInteractionRecorder(
        interaction_store, interaction_bus
    )
```

4. Add the `Application` dataclass fields with docstrings in the house style:

```python
    interaction_log: InteractionLogRunner
    """Keeps `interaction_events` following the interaction log. Idle until
    `start()`. Its own store, so nothing here can be ordered against the
    domain log."""

    interaction_recorder: EventStoreInteractionRecorder
    """Where the ingest route writes. Appends and publishes; see its module
    docstring for why the publish is not optional."""
```

5. Pass both in the returned `Application(...)`.
6. Add to `start()`, after the existing runners:
   `await self.interaction_log.start()`
7. Add to `close()`, beside the other `stop()` calls:
   `await self.interaction_log.stop()`
8. Add the test affordance beside `check_telemetry_caught_up`:

```python
    async def interaction_log_caught_up(self) -> None:
        """Wait until `interaction_events` has seen every appended event.

        For tests. Nothing in production waits on this -- the browser is not
        told when its batch landed, and could not use the answer.
        """
        await self.interaction_log.caught_up()
```

Add the imports: `SQLiteEventStore` and `InMemoryEventBus` are likely already
imported; add `InteractionLogRunner` and `EventStoreInteractionRecorder`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_interaction_log_wiring.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Prove it red**

Comment out `await self.interaction_log.start()` in `Application.start()`.
Run the test. It must fail — that is the exact defect the entity-definitions
work shipped. Restore it.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/integration tests/infrastructure -q
git add research_team/composition.py tests/integration/test_interaction_log_wiring.py
git commit
```

---

### Task 7: The ingest route

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Test: `tests/interfaces/test_interaction_routes.py`

**Interfaces:**
- Consumes: `EventStoreInteractionRecorder` (Task 5), `INTERACTION_EVENTS` (Task 2).
- Produces: `POST /api/interactions`, module-level `InteractionBatch` and `InteractionEnvelope` pydantic models, and a new `create_app` parameter `interactions: EventStoreInteractionRecorder | None = None`.

Copy the 202 pattern from `POST /api/projects/{project_id}/topics/seed`
(`app.py:1685-1718`): module-level body model, `JSONResponse(status_code=202,
content=...)`, 503 when the collaborator is `None`.

**Partial acceptance is the design.** One malformed event does not reject the
batch. The client cannot observe a `sendBeacon` response at all, so a
whole-batch rejection would discard 199 good events silently.

Batch cap: 200 events. The client's own cap is 50, so 200 leaves room for a
page-hide flush racing a timer flush without inventing a reason to reject a
legitimate batch.

- [ ] **Step 1: Write the failing tests**

Create `tests/interfaces/test_interaction_routes.py`:

```python
"""The one route the browser posts to.

Every test here asserts a stored row, not a status code, wherever a row is
what the route is for. A 202 assertion alone passes with the projection
deleted, because replay counts an unhandled event as applied.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.interfaces.web.app import create_app


@pytest.fixture
async def application(db_path, tmp_path):
    app = build_application(
        db_path=db_path, interaction_db_path=str(tmp_path / "interactions.db")
    )
    await app.start()
    try:
        yield app
    finally:
        await app.close()


def _api(application, *, interactions=True):
    return create_app(
        application.service,
        application.feed,
        application.turns,
        interactions=application.interaction_recorder if interactions else None,
    )


def _envelope(browser_session, install, seq=1, **over):
    body = {
        "kind": "ViewEntered",
        "browser_session_id": str(browser_session),
        "install_id": str(install),
        "seq": seq,
        "view": "project/entity",
        "occurred_at": "2026-08-17T10:00:00Z",
        "payload": {"params": {"entity_id": "ent_4a1f"}},
    }
    body.update(over)
    return body


async def _client(api):
    return AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def test_a_batch_is_accepted_and_stored(application):
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions",
            json={"events": [_envelope(browser_session, install)]},
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 0}

    await application.interaction_log_caught_up()
    rows = await application.interaction_log.events(browser_session)
    assert len(rows) == 1
    assert rows[0].kind == "ViewEntered"
    assert rows[0].payload["params"]["entity_id"] == "ent_4a1f"


async def test_the_server_stamps_when_it_took_delivery(application):
    """Kept as a cross-check on a client clock that can be skewed or moved,
    not as ordering truth."""
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        await client.post(
            "/api/interactions",
            json={"events": [_envelope(browser_session, install)]},
        )

    await application.interaction_log_caught_up()
    row = (await application.interaction_log.events(browser_session))[0]
    assert row.received_at is not None


async def test_one_bad_event_does_not_lose_the_good_ones(application):
    """Partial acceptance. The client cannot see this response -- sendBeacon
    reports nothing -- so rejecting the batch would discard good events with
    no way for anyone to find out.

    Fails if the route validates the whole batch up front.
    """
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2, kind="NotAKind")
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions", json={"events": [good, bad]}
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "rejected": 1}

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_an_event_missing_a_required_field_is_rejected_alone(application):
    browser_session, install = uuid4(), uuid4()
    good = _envelope(browser_session, install, seq=1)
    bad = _envelope(browser_session, install, seq=2)
    del bad["view"]
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions", json={"events": [good, bad]}
        )

        assert response.json() == {"accepted": 1, "rejected": 1}


async def test_the_same_event_twice_is_one_row(application):
    """A page-hide flush can race a timer flush, and sendBeacon can deliver
    twice. Idempotent on (browser_session_id, seq)."""
    browser_session, install = uuid4(), uuid4()
    batch = {"events": [_envelope(browser_session, install, seq=5)]}
    async with await _client(_api(application)) as client:
        await client.post("/api/interactions", json=batch)
        await client.post("/api/interactions", json=batch)

    await application.interaction_log_caught_up()
    assert len(await application.interaction_log.events(browser_session)) == 1


async def test_an_oversized_batch_is_refused(application):
    browser_session, install = uuid4(), uuid4()
    async with await _client(_api(application)) as client:
        response = await client.post(
            "/api/interactions",
            json={
                "events": [
                    _envelope(browser_session, install, seq=n) for n in range(201)
                ]
            },
        )

        assert response.status_code == 422


async def test_an_empty_batch_is_accepted_and_writes_nothing(application):
    async with await _client(_api(application)) as client:
        response = await client.post("/api/interactions", json={"events": []})

        assert response.status_code == 202
        assert response.json() == {"accepted": 0, "rejected": 0}


async def test_the_route_is_absent_when_collection_is_off(application):
    """AGENT_INTERACTION_LOG=0 makes the entrypoint pass None, and the house
    pattern is that the dependency being absent is the switch."""
    async with await _client(_api(application, interactions=False)) as client:
        response = await client.post("/api/interactions", json={"events": []})

        assert response.status_code == 503
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/interfaces/test_interaction_routes.py -v`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'interactions'`

- [ ] **Step 3: Implement the body models**

Add at module level in `app.py`, beside the other body models:

```python
INTERACTION_BATCH_LIMIT = 200
"""Most events one POST may carry.

The client flushes at 50, so this leaves room for a page-hide flush racing a
timer flush without rejecting a batch that is merely unlucky.
"""


class InteractionEnvelope(BaseModel):
    """One reported interaction, as the browser sends it.

    Deliberately loose about `payload`: the kind decides its shape, and the
    domain event validates it. Validating twice would mean two vocabularies to
    keep in step, and the second one would drift.
    """

    kind: str
    browser_session_id: UUID
    install_id: UUID
    seq: int
    view: str
    occurred_at: datetime
    project_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InteractionBatch(BaseModel):
    """One flush.

    Capped rather than unbounded because this route takes unauthenticated
    input on a local port and the body becomes rows.
    """

    events: list[InteractionEnvelope] = Field(
        default_factory=list, max_length=INTERACTION_BATCH_LIMIT
    )
```

- [ ] **Step 4: Implement the route**

Add `interactions: EventStoreInteractionRecorder | None = None` to
`create_app`'s parameters, and the route closure:

```python
    _interaction_kinds = {
        event_type.__name__: event_type for event_type in INTERACTION_EVENTS
    }

    @app.post("/api/interactions")
    async def post_interactions(body: InteractionBatch):
        """Record what the console's user did. Capture only; nothing reads
        this back.

        Answers 202 with counts rather than rejecting a batch that contains
        one bad event. The client cannot see this response -- it is delivered
        by `sendBeacon` on page-hide, which reports nothing -- so a
        whole-batch rejection would silently discard the good events beside
        the bad one. Partial acceptance loses one event instead of fifty.

        The counts are returned anyway, for a human with curl.
        """
        if interactions is None:
            raise HTTPException(
                status_code=503, detail="the interaction log is not collecting"
            )

        received = datetime.now(UTC)
        events: list[InteractionEvent] = []
        rejected = 0
        for envelope in body.events:
            event_type = _interaction_kinds.get(envelope.kind)
            if event_type is None:
                rejected += 1
                continue
            try:
                events.append(
                    event_type(
                        aggregate_id=envelope.browser_session_id,
                        install_id=envelope.install_id,
                        seq=envelope.seq,
                        view=envelope.view,
                        occurred_at=envelope.occurred_at,
                        project_id=envelope.project_id,
                        session_id=envelope.session_id,
                        received_at=received,
                        **envelope.payload,
                    )
                )
            except ValidationError:
                # One event's payload not matching its kind. Counted, not
                # raised: see the docstring.
                rejected += 1

        accepted = await interactions.record(events)
        return JSONResponse(
            status_code=202,
            content={"accepted": accepted, "rejected": rejected},
        )
```

Add imports as needed: `ValidationError` from `pydantic`, `UTC` from
`datetime`, `INTERACTION_EVENTS` and `InteractionEvent` from
`research_team.domain.interaction`, `EventStoreInteractionRecorder`.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/interfaces/test_interaction_routes.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/interfaces -q
git add research_team/interfaces/web/app.py tests/interfaces/test_interaction_routes.py
git commit
```

Commit message must record why partial acceptance rather than 422 on the batch, and that the client cannot observe the response.

---

### Task 8: The entrypoint

**Files:**
- Modify: `web.py`
- Test: `tests/interfaces/test_web_entrypoint.py`

**Interfaces:**
- Consumes: `config.interaction_log_enabled` (Task 1), `Application.interaction_recorder` (Task 6), the `interactions` parameter (Task 7).
- Produces: nothing new.

`web.py` is the only production `create_app` call site, and three comments in
it record routes that shipped 503ing because someone added the parameter and
forgot the argument. `tests/interfaces/test_web_entrypoint.py` exists for
exactly this.

- [ ] **Step 1: Write the failing test**

Read `tests/interfaces/test_web_entrypoint.py` first and match its existing
shape. Add:

```python
def test_the_entrypoint_wires_the_interaction_log(monkeypatch):
    """create_app grows a parameter and web.py forgets the argument: the
    route exists and 503s forever. Three comments in web.py record this
    happening.

    Fails with the `interactions=` argument removed from web.py.
    """
    monkeypatch.delenv("AGENT_INTERACTION_LOG", raising=False)

    # Follow whatever inspection this file already uses for the other
    # collaborators -- do not invent a second mechanism.


def test_switching_collection_off_removes_the_route(monkeypatch):
    """The house pattern: unset means the dependency is None, not that a
    route exists and checks a flag."""
    monkeypatch.setenv("AGENT_INTERACTION_LOG", "0")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

In `web.py`'s `create_app(...)` call, following the
`research=application.research if config.research_run_over_http() else None`
precedent:

```python
            # Off means the dependency is absent, not that the route exists
            # and checks a flag -- `config.py` argues that "unset means the
            # route is not there" is the stronger promise. Default is on,
            # unlike every other flag here, because a log nobody collects is
            # worth nothing; `interaction_log_enabled` says why.
            interactions=(
                application.interaction_recorder
                if config.interaction_log_enabled()
                else None
            ),
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v`
Expected: PASS

- [ ] **Step 5: Manual check against a real server**

```bash
uv run python -m uvicorn web:app --port 8765 &
curl -s -X POST localhost:8765/api/interactions \
  -H 'Content-Type: application/json' \
  -d '{"events":[{"kind":"ViewEntered","browser_session_id":"11111111-1111-1111-1111-111111111111","install_id":"22222222-2222-2222-2222-222222222222","seq":1,"view":"home","occurred_at":"2026-08-17T10:00:00Z","payload":{"params":{}}}]}'
sqlite3 ~/.research-team/interactions.db 'select seq, kind, view from interaction_events'
```

Expected: `{"accepted":1,"rejected":0}` and one row. This is the success
criterion from the spec — a developer can open the database and see what
happened — exercised for the first time. Kill the server afterwards.

- [ ] **Step 6: Full backend gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
git add web.py tests/interfaces/test_web_entrypoint.py
git commit
```

**This is the first PR boundary.** The backend is complete and provable with
`curl` before any frontend exists. Open a PR here.

---

### Task 9: The frontend port, DTO and repository

**Files:**
- Create: `frontend/src/application/ports/interaction-log.ts`
- Create: `frontend/src/infrastructure/http/interaction-log-repository.ts`
- Modify: `frontend/src/infrastructure/http/dto.ts`
- Modify: `frontend/src/app/container.ts`
- Test: `frontend/src/infrastructure/http/interaction-log-repository.test.ts`

**Interfaces:**
- Consumes: `POST /api/interactions` (Task 7).
- Produces:
  - `InteractionEvent` type and `InteractionSink` port with
    `send(events: readonly InteractionEvent[]): Promise<void>` and
    `sendOnUnload(events: readonly InteractionEvent[]): void`
  - `HttpInteractionSink implements InteractionSink`
  - `container.interactions: InteractionSink`

Two methods rather than one because the unload path cannot use `fetch`: the
page is going away and `sendBeacon` is the only delivery the browser will
finish. They are different mechanisms with different failure modes, so the
port names both rather than hiding one behind a flag.

`sendOnUnload` returns `void`, not a promise. `sendBeacon` reports only
whether the browser queued the payload, never whether it arrived, so a
promise would be a lie.

**Match the house style exactly:** `import type` with explicit `.ts`
extensions, `@application`/`@domain` aliases, per-member doc comments
justifying the shape, no explicit return types on repository methods so the
port checks them.

- [ ] **Step 1: Write the port**

```ts
/** Reporting what the user did, for a log nobody reads back yet.
 *
 * A port because there are two delivery mechanisms with genuinely different
 * guarantees, and the difference belongs in the interface rather than inside
 * one method that picks. Everything else about this feature -- what is worth
 * recording, when to flush -- is application logic and lives above this line.
 */

export interface InteractionEvent {
  readonly kind: string
  readonly browser_session_id: string
  readonly install_id: string
  readonly seq: number
  readonly view: string
  readonly occurred_at: string
  readonly project_id?: string | null
  readonly session_id?: string | null
  readonly payload: Readonly<Record<string, unknown>>
}

export interface InteractionSink {
  /** Deliver a batch while the page is alive. Rejects on transport failure;
   *  the caller drops the batch rather than retrying, because this data is
   *  droppable by design and a retry queue would make late arrival a
   *  permanent property of the log. */
  send(events: readonly InteractionEvent[]): Promise<void>

  /** Deliver a batch while the page is going away.
   *
   *  `sendBeacon` rather than `fetch`, because an in-flight fetch is
   *  cancelled on unload and the tail of every session -- where friction
   *  lives -- would be the part that never arrives.
   *
   *  Returns nothing on purpose: the browser reports only whether it queued
   *  the payload, never whether it was received, so a promise here would
   *  promise something unknowable. */
  sendOnUnload(events: readonly InteractionEvent[]): void
}
```

- [ ] **Step 2: Write the failing repository test**

```ts
import { afterEach, expect, it, vi } from 'vitest'

import { HttpClient } from './http-client.ts'
import { HttpInteractionSink } from './interaction-log-repository.ts'

afterEach(() => vi.unstubAllGlobals())

const event = (seq: number) => ({
  kind: 'ViewEntered',
  browser_session_id: '11111111-1111-1111-1111-111111111111',
  install_id: '22222222-2222-2222-2222-222222222222',
  seq,
  view: 'home',
  occurred_at: '2026-08-17T10:00:00Z',
  payload: {},
})

it('posts a batch as one request', async () => {
  const fetchMock = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({ accepted: 2, rejected: 0 }))),
  )
  vi.stubGlobal('fetch', fetchMock)

  await new HttpInteractionSink(new HttpClient()).send([event(1), event(2)])

  expect(fetchMock).toHaveBeenCalledTimes(1)
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  expect(url).toBe('/api/interactions')
  expect(JSON.parse(init.body as string)).toEqual({ events: [event(1), event(2)] })
})

it('sends nothing when there is nothing to send', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)

  await new HttpInteractionSink(new HttpClient()).send([])

  expect(fetchMock).not.toHaveBeenCalled()
})

it('beacons a batch on unload', () => {
  /** jsdom does not implement sendBeacon, so this has to be stubbed rather
   *  than merely observed -- there is no stub for it in vitest.setup.ts. */
  const beacon = vi.fn(() => true)
  vi.stubGlobal('navigator', { sendBeacon: beacon })

  new HttpInteractionSink(new HttpClient()).sendOnUnload([event(1)])

  expect(beacon).toHaveBeenCalledTimes(1)
  const [url, payload] = beacon.mock.calls[0] as [string, Blob]
  expect(url).toBe('/api/interactions')
  expect(payload).toBeInstanceOf(Blob)
})

it('falls back to a keepalive fetch where sendBeacon is missing', () => {
  /** Not every browser this console runs in has it, and losing the tail of a
   *  session there would be invisible. */
  const fetchMock = vi.fn(() => Promise.resolve(new Response('{}')))
  vi.stubGlobal('navigator', {})
  vi.stubGlobal('fetch', fetchMock)

  new HttpInteractionSink(new HttpClient()).sendOnUnload([event(1)])

  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ keepalive: true })
})

it('does not throw when a batch is refused', async () => {
  /** The route is absent when AGENT_INTERACTION_LOG=0, and a console that
   *  broke because telemetry was switched off would be a worse bug than no
   *  telemetry. */
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response('{"detail":"not collecting"}', { status: 503 }))),
  )

  await expect(
    new HttpInteractionSink(new HttpClient()).send([event(1)]),
  ).resolves.toBeUndefined()
})
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd frontend && npx vitest run --project app src/infrastructure/http/interaction-log-repository.test.ts`
Expected: FAIL — cannot resolve `./interaction-log-repository.ts`

- [ ] **Step 4: Implement**

Add to `frontend/src/infrastructure/http/dto.ts`:

```ts
/** What the ingest route answers. Read for a human with curl rather than by
 *  this client -- the counts cannot reach the beacon path at all. */
export const interactionReceiptDto = z.object({
  accepted: z.number(),
  rejected: z.number(),
})
```

Create `frontend/src/infrastructure/http/interaction-log-repository.ts`:

```ts
import type {
  InteractionEvent,
  InteractionSink,
} from '@application/ports/interaction-log.ts'

import * as dto from './dto.ts'
import { HttpClient } from './http-client.ts'

const PATH = '/api/interactions'

export class HttpInteractionSink implements InteractionSink {
  constructor(private readonly http: HttpClient) {}

  async send(events: readonly InteractionEvent[]) {
    if (events.length === 0) return
    try {
      await this.http.post(PATH, { events }, dto.interactionReceiptDto)
    } catch {
      // Swallowed deliberately, and this is the one place in this codebase
      // that swallows an ApiError. Collection is off by one env var, which
      // makes the route answer 503 -- and a console that broke because
      // telemetry was disabled would be a far worse defect than a lost
      // batch. The data is droppable by design; that is why it has its own
      // store.
    }
  }

  sendOnUnload(events: readonly InteractionEvent[]) {
    if (events.length === 0) return
    const url = this.http.url(PATH)
    const body = JSON.stringify({ events })

    // A Blob rather than a string so the Content-Type is application/json:
    // sendBeacon sends a bare string as text/plain, which FastAPI refuses.
    const payload = new Blob([body], { type: 'application/json' })

    if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
      navigator.sendBeacon(url, payload)
      return
    }

    // Not every browser has it. `keepalive` is the nearest equivalent: it
    // asks the browser to finish the request after the document goes away.
    // Weaker than a beacon and worth having anyway, because the alternative
    // loses every session's last view, which is where friction lives.
    void fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => undefined)
  }
}
```

Register in `frontend/src/app/container.ts` — add the member and one line in
`createContainer`:

```ts
  /** Where the interaction log is reported to. Capture only; nothing reads
   *  it back, so there is no query hook and no repository beside this. */
  readonly interactions: InteractionSink
```

```ts
    interactions: new HttpInteractionSink(http),
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd frontend && npx vitest run --project app src/infrastructure/http/interaction-log-repository.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 6: Gates and commit**

```bash
cd frontend && npm run verify
cd frontend && npm run build
git add frontend/src frontend/package.json research_team/interfaces/web/static
git commit
```

`src/app/**` is excluded from coverage, so the container change cannot move
the thresholds; the repository is in `src/infrastructure/**`, which requires
52% lines, and these five tests cover it.

---

### Task 10: The emitter — buffer, batch, flush

**Files:**
- Create: `frontend/src/application/interaction-log/emitter.ts`
- Test: `frontend/src/application/interaction-log/emitter.test.ts`

**Interfaces:**
- Consumes: `InteractionSink`, `InteractionEvent` (Task 9).
- Produces:
  - `createEmitter({ sink, now, installId, browserSessionId }): Emitter`
  - `Emitter` with `record(kind: string, payload?: Record<string, unknown>): void`,
    `setContext(context: { view?: string; projectId?: string | null; sessionId?: string | null }): void`,
    `flush(): Promise<void>`, `flushOnUnload(): void`, `stop(): void`, `pending(): number`
  - `FLUSH_INTERVAL_MS = 5_000`, `FLUSH_AT = 50`

Use the **factory** zustand-adjacent style the repo uses for
dependency-injected units (`createAskStore`, `createSessionStore`) — a plain
factory here, since there is no rendered state to subscribe to. Inject `now`
rather than reaching for the clock, matching `container.now`.

`seq` is assigned here, monotonically, at `record` time — not at flush time.
That is what makes it the ordering authority: a batch can be reordered by the
network and two flushes can race, and neither disturbs a counter incremented
when the thing happened.

- [ ] **Step 1: Write the failing tests**

```ts
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { InteractionEvent } from '@application/ports/interaction-log.ts'

import { FLUSH_AT, FLUSH_INTERVAL_MS, createEmitter } from './emitter.ts'

const INSTALL = '22222222-2222-2222-2222-222222222222'
const SESSION = '11111111-1111-1111-1111-111111111111'

const sink = () => {
  const sent: InteractionEvent[][] = []
  const beaconed: InteractionEvent[][] = []
  return {
    sent,
    beaconed,
    send: vi.fn(async (events: readonly InteractionEvent[]) => {
      sent.push([...events])
    }),
    sendOnUnload: vi.fn((events: readonly InteractionEvent[]) => {
      beaconed.push([...events])
    }),
  }
}

const emitter = (transport = sink(), clock = 1_000) =>
  createEmitter({
    sink: transport,
    now: () => clock,
    installId: INSTALL,
    browserSessionId: SESSION,
  })

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

it('holds an event rather than sending it immediately', () => {
  /** One POST per click would be noisy in the network panel this console is
   *  debugged in, and would lose ordering under concurrency. */
  const transport = sink()
  const log = emitter(transport)

  log.record('ViewEntered', { params: {} })

  expect(transport.send).not.toHaveBeenCalled()
  expect(log.pending()).toBe(1)
})

it('flushes on the timer', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.record('ViewEntered', { params: {} })

  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS)

  expect(transport.sent).toHaveLength(1)
  expect(transport.sent[0]).toHaveLength(1)
  expect(log.pending()).toBe(0)
})

it('does not flush an empty buffer', async () => {
  const transport = sink()
  emitter(transport)

  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS * 3)

  expect(transport.send).not.toHaveBeenCalled()
})

it('flushes immediately once the buffer reaches its cap', async () => {
  const transport = sink()
  const log = emitter(transport)

  for (let n = 0; n < FLUSH_AT; n += 1) log.record('AttentionLost')
  await vi.advanceTimersByTimeAsync(0)

  expect(transport.sent).toHaveLength(1)
  expect(transport.sent[0]).toHaveLength(FLUSH_AT)
})

it('numbers events in the order they happened, not the order they are sent', async () => {
  /** seq is the ordering authority. Assigned at record time so that a
   *  reordered batch, a racing flush, or a moved system clock cannot disturb
   *  it. */
  const transport = sink()
  const log = emitter(transport)

  log.record('ViewEntered', { params: {} })
  log.record('EntityOpened', { entity_id: 'a', source: 'graph' })
  log.record('EntityOpened', { entity_id: 'b', source: 'search' })
  await log.flush()

  expect(transport.sent[0]?.map((event) => event.seq)).toEqual([1, 2, 3])
})

it('keeps numbering across flushes', async () => {
  const transport = sink()
  const log = emitter(transport)

  log.record('AttentionLost')
  await log.flush()
  log.record('AttentionRegained')
  await log.flush()

  expect(transport.sent[1]?.[0]?.seq).toBe(2)
})

it('stamps every event with the identity and the current context', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.setContext({ view: 'project/timeline', projectId: 'p-1', sessionId: null })

  log.record('ViewEntered', { params: {} })
  await log.flush()

  const event = transport.sent[0]?.[0]
  expect(event).toMatchObject({
    kind: 'ViewEntered',
    install_id: INSTALL,
    browser_session_id: SESSION,
    view: 'project/timeline',
    project_id: 'p-1',
    session_id: null,
  })
})

it('carries the kind-specific payload through untouched', async () => {
  const transport = sink()
  const log = emitter(transport)

  log.record('SearchPerformed', { query_text: 'tetrarchy', result_count: 0 })
  await log.flush()

  expect(transport.sent[0]?.[0]?.payload).toEqual({
    query_text: 'tetrarchy',
    result_count: 0,
  })
})

it('empties the buffer before awaiting the send, so a slow flush cannot double-send', async () => {
  /** Fails with the buffer cleared after the await: the timer fires again
   *  while the first send is in flight and the same events go twice.
   *  Idempotent server-side on (browser_session_id, seq), so the symptom
   *  would be wasted requests rather than duplicate rows -- which is
   *  precisely the kind of defect nothing would report. */
  let release = () => {}
  const transport = {
    ...sink(),
    send: vi.fn(() => new Promise<void>((resolve) => (release = resolve))),
  }
  const log = emitter(transport)
  log.record('AttentionLost')

  const flushing = log.flush()
  expect(log.pending()).toBe(0)
  release()
  await flushing

  expect(transport.send).toHaveBeenCalledTimes(1)
})

it('beacons the buffer on unload rather than posting it', () => {
  /** A batch dropped at tab close removes the end of every session, which is
   *  where friction lives. */
  const transport = sink()
  const log = emitter(transport)
  log.record('ViewExited', { dwell_ms: 4_000, hidden_ms: 0 })

  log.flushOnUnload()

  expect(transport.sendOnUnload).toHaveBeenCalledTimes(1)
  expect(transport.beaconed[0]).toHaveLength(1)
  expect(transport.send).not.toHaveBeenCalled()
  expect(log.pending()).toBe(0)
})

it('stops flushing once stopped', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.record('AttentionLost')

  log.stop()
  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS * 3)

  expect(transport.send).not.toHaveBeenCalled()
})

it('survives a sink that rejects', async () => {
  /** A dropped batch must not become an unhandled rejection: main.tsx turns
   *  those into a toast, and telemetry failing is not the user's problem. */
  const transport = { ...sink(), send: vi.fn(() => Promise.reject(new Error('nope'))) }
  const log = emitter(transport)
  log.record('AttentionLost')

  await expect(log.flush()).resolves.toBeUndefined()
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run --project app src/application/interaction-log/emitter.test.ts`
Expected: FAIL — cannot resolve `./emitter.ts`

- [ ] **Step 3: Implement**

```ts
/** The buffer between what the user did and the one POST that reports it.
 *
 * Written here rather than taken from a library, and the search that settled
 * that is worth recording: the batch-and-beacon machinery exists only inside
 * full analytics SDKs (PostHog, Snowplow, Rudderstack), each of which brings
 * its own event ontology and a server half this feature does not use. The
 * standalone prior art is patterns over `sendBeacon` and `pagehide`, not
 * packages. Taking one would have meant carrying a large dependency against
 * a bundle budget to use a few percent of it, and bending a vocabulary that
 * was designed deliberately to fit theirs.
 *
 * What is deliberately absent: any durable client-side queue. A crash loses
 * the last few seconds. Spilling to localStorage would spend real complexity
 * protecting data that is droppable by design -- the reason this log has its
 * own store -- and would make late arrival a permanent property that every
 * future reader of the log has to reason about.
 */

import type {
  InteractionEvent,
  InteractionSink,
} from '@application/ports/interaction-log.ts'

export const FLUSH_INTERVAL_MS = 5_000
/** Long enough that a busy minute is a handful of requests, short enough
 *  that a crash loses seconds rather than a session. */

export const FLUSH_AT = 50
/** Flush early at this many, so a burst does not sit in memory for the rest
 *  of the interval. The server accepts 200, leaving room for a page-hide
 *  flush racing a timer flush. */

interface Context {
  view: string
  projectId: string | null
  sessionId: string | null
}

export interface Emitter {
  record(kind: string, payload?: Readonly<Record<string, unknown>>): void
  setContext(context: Partial<Context>): void
  flush(): Promise<void>
  flushOnUnload(): void
  stop(): void
  pending(): number
}

export const createEmitter = ({
  sink,
  now,
  installId,
  browserSessionId,
}: {
  sink: InteractionSink
  now: () => number
  installId: string
  browserSessionId: string
}): Emitter => {
  let buffer: InteractionEvent[] = []
  let seq = 0
  let context: Context = { view: 'home', projectId: null, sessionId: null }
  let timer: ReturnType<typeof setInterval> | null = setInterval(() => {
    void flush()
  }, FLUSH_INTERVAL_MS)

  /** Empties the buffer *before* awaiting, so a flush still in flight when
   *  the timer fires again cannot send the same events twice. Server-side
   *  idempotency on (browser_session_id, seq) means the symptom would be
   *  wasted requests rather than duplicate rows -- a defect nothing reports. */
  const take = (): InteractionEvent[] => {
    const taken = buffer
    buffer = []
    return taken
  }

  const flush = async (): Promise<void> => {
    const batch = take()
    if (batch.length === 0) return
    try {
      await sink.send(batch)
    } catch {
      // Dropped. Never rethrown: `main.tsx` turns an unhandled rejection
      // into a toast, and telemetry failing is not the user's problem.
    }
  }

  return {
    record(kind, payload = {}) {
      seq += 1
      buffer.push({
        kind,
        browser_session_id: browserSessionId,
        install_id: installId,
        seq,
        view: context.view,
        occurred_at: new Date(now()).toISOString(),
        project_id: context.projectId,
        session_id: context.sessionId,
        payload,
      })
      if (buffer.length >= FLUSH_AT) void flush()
    },

    setContext(next) {
      context = { ...context, ...next }
    },

    flush,

    flushOnUnload() {
      const batch = take()
      if (batch.length === 0) return
      sink.sendOnUnload(batch)
    },

    stop() {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    },

    pending() {
      return buffer.length
    },
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run --project app src/application/interaction-log/emitter.test.ts`
Expected: PASS (12 tests)

- [ ] **Step 5: Prove the double-send test red**

Change `take()` so `flush` clears the buffer after the await, run
`npx vitest run --project app src/application/interaction-log/emitter.test.ts -t double-send`,
confirm FAIL, revert.

- [ ] **Step 6: Gates and commit**

```bash
cd frontend && npm run verify
git add frontend/src
git commit
```

No rebuild needed yet — nothing imports the emitter, so the bundle has not
changed. It will in Task 12.

---

### Task 11: Identity and dwell, browser-tested

**Files:**
- Create: `frontend/src/application/interaction-log/identity.ts`
- Create: `frontend/src/application/interaction-log/dwell.ts`
- Test: `frontend/src/application/interaction-log/identity.test.ts`
- Test: `frontend/src/application/interaction-log/dwell.browser.test.tsx`

**Interfaces:**
- Consumes: `Emitter` (Task 10).
- Produces:
  - `installId(storage?: Storage): string` — persisted, minted once
  - `newBrowserSessionId(): string`
  - `createDwellTracker({ emitter, clock }): DwellTracker` with
    `enter(view: string, params?: Record<string, unknown>): void`,
    `exit(): void`, `attach(): () => void`

**The dwell tests belong in the browser suite.** jsdom lays nothing out,
implements no page lifecycle, and `visibilitychange` / `pagehide` /
`performance.now()` do not behave there — CLAUDE.md's rule is that anything
whose correctness is a measurement belongs in `*.browser.test.tsx`. The
identity tests are pure storage logic and stay in jsdom.

`clock` is injected and defaults to `performance.now`. Monotonic on purpose:
a system clock moved mid-session cannot produce a negative dwell.

- [ ] **Step 1: Write the identity tests (jsdom)**

```ts
import { expect, it } from 'vitest'

import { installId, newBrowserSessionId } from './identity.ts'

const storage = (): Storage => {
  const map = new Map<string, string>()
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as Storage
}

it('mints an install id once and remembers it', () => {
  /** The only thing that lets a count say "on nine separate days" rather than
   *  "in nine separate tabs". */
  const store = storage()

  const first = installId(store)
  const second = installId(store)

  expect(first).toBe(second)
})

it('survives junk left by an older build', () => {
  /** The preference store's reasoning applies here too: storage outlives the
   *  code that wrote it. */
  const store = storage()
  store.setItem('research-team.install-id', 'not-a-uuid')

  expect(installId(store)).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  )
})

it('still returns an id when storage throws', () => {
  /** localStorage throws in private mode and where it is disabled. An install
   *  id that cannot persist is worth more than a console that cannot load. */
  const hostile = {
    getItem: () => {
      throw new Error('denied')
    },
    setItem: () => {
      throw new Error('denied')
    },
  } as unknown as Storage

  expect(installId(hostile)).toHaveLength(36)
})

it('gives every page load its own browser session id', () => {
  expect(newBrowserSessionId()).not.toBe(newBrowserSessionId())
})
```

- [ ] **Step 2: Write the dwell browser test**

```tsx
import { expect, it, vi } from 'vitest'

import { createDwellTracker } from './dwell.ts'

/** Dwell is a measurement, and jsdom measures nothing: it implements no page
 *  lifecycle, so `visibilitychange` and `pagehide` never fire, and
 *  `performance.now()` does not advance the way it does in a browser. Written
 *  as a jsdom test, every assertion below would have had to be a comment --
 *  which CLAUDE.md records happening four times in a row here.
 */

const recorder = () => {
  const events: { kind: string; payload: Record<string, unknown> }[] = []
  return {
    events,
    record: vi.fn((kind: string, payload: Record<string, unknown> = {}) => {
      events.push({ kind, payload })
    }),
    setContext: vi.fn(),
    flush: vi.fn(async () => {}),
    flushOnUnload: vi.fn(),
    stop: vi.fn(),
    pending: vi.fn(() => 0),
  }
}

it('reports a dwell that grew with real elapsed time', async () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })

  tracker.enter('project/timeline')
  await new Promise((resolve) => setTimeout(resolve, 60))
  tracker.exit()

  const exited = emitter.events.find((event) => event.kind === 'ViewExited')
  expect(exited).toBeDefined()
  expect(exited?.payload.dwell_ms as number).toBeGreaterThanOrEqual(50)
})

it('reports entering and exiting in order', () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })

  tracker.enter('home')
  tracker.enter('project/entity')

  expect(emitter.events.map((event) => event.kind)).toEqual([
    'ViewEntered',
    'ViewExited',
    'ViewEntered',
  ])
})

it('does not report an exit for a view never entered', () => {
  const emitter = recorder()

  createDwellTracker({ emitter }).exit()

  expect(emitter.events).toHaveLength(0)
})

it('counts hidden time separately from dwell', () => {
  /** Without this, "stalled here for four minutes" and "went to lunch" are
   *  the same event, and the attention half of the log is worthless. */
  const emitter = recorder()
  let time = 0
  const tracker = createDwellTracker({ emitter, clock: () => time })

  tracker.enter('project/timeline')
  time = 1_000
  document.dispatchEvent(new Event('visibilitychange'))
  time = 5_000
  tracker.exit()

  const exited = emitter.events.find((event) => event.kind === 'ViewExited')
  expect(exited?.payload.dwell_ms).toBe(5_000)
  expect(exited?.payload.hidden_ms as number).toBeGreaterThan(0)
})

it('stops listening when detached', () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })
  const detach = tracker.attach()

  detach()
  window.dispatchEvent(new Event('pagehide'))

  expect(emitter.flushOnUnload).not.toHaveBeenCalled()
})

it('flushes by beacon on pagehide', () => {
  const emitter = recorder()
  const detach = createDwellTracker({ emitter }).attach()
  try {
    window.dispatchEvent(new Event('pagehide'))

    expect(emitter.flushOnUnload).toHaveBeenCalled()
  } finally {
    detach()
  }
})
```

The hidden-time test drives `visibilitychange` directly rather than actually
backgrounding the tab, because Playwright cannot background a tab it is
driving. That is a real limit of the test, and the docstring should say so:
it pins the accounting, not the browser's own visibility behaviour.

- [ ] **Step 3: Run both to verify they fail**

Run: `cd frontend && npx vitest run --project app src/application/interaction-log/identity.test.ts`
Then: `cd frontend && npx vitest run --project browser src/application/interaction-log/dwell.browser.test.tsx`
Expected: both FAIL on unresolved imports. **Run them one at a time** — two
vitest processes at once fail spuriously.

- [ ] **Step 4: Implement identity**

```ts
/** Who and which tab, for counting distinct days rather than distinct loads.
 *
 * A module rather than a port: unlike preferences there is one
 * implementation, and the storage failure modes are handled here for the same
 * reasons `LocalPreferenceStore` handles them -- storage throws in private
 * mode, and a browser carries junk written by an older build.
 */

const INSTALL_KEY = 'research-team.install-id'

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

const mint = (): string =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : // Only for a browser without randomUUID. Not cryptographic, and does
      // not need to be: this identifies an install for counting, and nothing
      // trusts it.
      `${Date.now().toString(16).padStart(12, '0')}-0000-4000-8000-${Math.random()
        .toString(16)
        .slice(2, 14)
        .padEnd(12, '0')}`.slice(0, 36)

/** The install, across restarts.
 *
 * Pseudonymous, and the exact thing that becomes real identity if this
 * product grows past one user -- named so that growth is a decision.
 *
 * An unreadable or malformed value is replaced rather than trusted: it
 * reaches a UUID column, and a stored non-uuid would fail at ingest for
 * every event forever, which would look like the feature not working.
 */
export const installId = (storage: Storage | undefined = safeStorage()): string => {
  try {
    const stored = storage?.getItem(INSTALL_KEY)
    if (stored && UUID_PATTERN.test(stored)) return stored
    const minted = mint()
    storage?.setItem(INSTALL_KEY, minted)
    return minted
  } catch {
    // Private mode, or storage disabled. An id that does not persist still
    // groups one session's events; refusing to return one would break the
    // console over telemetry, which is the wrong trade.
    return mint()
  }
}

export const newBrowserSessionId = (): string => mint()

const safeStorage = (): Storage | undefined => {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}
```

- [ ] **Step 5: Implement dwell**

```ts
/** How long a view was current, and how much of that the tab was hidden for.
 *
 * `performance.now()` rather than `Date.now()`: monotonic, so a system clock
 * moved mid-session cannot produce a negative or absurd duration. The
 * emitter's `occurred_at` still comes from the wall clock, because that one
 * is for a human reading rows.
 */

import type { Emitter } from './emitter.ts'

export interface DwellTracker {
  enter(view: string, params?: Readonly<Record<string, unknown>>): void
  exit(): void
  /** Subscribe to the page lifecycle. Returns the unsubscribe. */
  attach(): () => void
}

export const createDwellTracker = ({
  emitter,
  clock = () => performance.now(),
}: {
  emitter: Emitter
  clock?: () => number
}): DwellTracker => {
  let view: string | null = null
  let enteredAt = 0
  let hiddenMs = 0
  let hiddenSince: number | null = null

  const exit = () => {
    if (view === null) return
    if (hiddenSince !== null) {
      hiddenMs += clock() - hiddenSince
      hiddenSince = null
    }
    emitter.record('ViewExited', {
      dwell_ms: Math.round(clock() - enteredAt),
      hidden_ms: Math.round(hiddenMs),
    })
    view = null
  }

  const onVisibility = () => {
    if (document.visibilityState === 'hidden') {
      hiddenSince = clock()
      emitter.record('AttentionLost')
      return
    }
    if (hiddenSince !== null) {
      hiddenMs += clock() - hiddenSince
      hiddenSince = null
    }
    emitter.record('AttentionRegained')
  }

  const onPageHide = () => {
    // The last view of every session ends here, and it is the view most
    // likely to be the one somebody got stuck on. Beacon rather than post:
    // an in-flight fetch is cancelled on unload.
    exit()
    emitter.flushOnUnload()
  }

  return {
    enter(next, params = {}) {
      exit()
      view = next
      enteredAt = clock()
      hiddenMs = 0
      hiddenSince = document.visibilityState === 'hidden' ? clock() : null
      emitter.setContext({ view: next })
      emitter.record('ViewEntered', { params })
    },

    exit,

    attach() {
      document.addEventListener('visibilitychange', onVisibility)
      window.addEventListener('pagehide', onPageHide)
      return () => {
        document.removeEventListener('visibilitychange', onVisibility)
        window.removeEventListener('pagehide', onPageHide)
      }
    },
  }
}
```

Note the visibility test's expectation: with the injected clock the
`visibilitychange` handler reads `document.visibilityState`, which in the
browser test is `'visible'`, so the first dispatch takes the
`AttentionRegained` branch. Adjust the test to drive the hidden branch the
way the harness allows — either by stubbing `document.visibilityState` with
`Object.defineProperty`, or by asserting the accounting through two
dispatches. **Get this test genuinely red then green rather than adjusting
the implementation to match a passing-but-wrong assertion.**

- [ ] **Step 6: Run both suites**

Run: `cd frontend && npx vitest run --project app src/application/interaction-log/identity.test.ts`
Expected: PASS (4 tests)

Then, separately: `cd frontend && npm run test:browser`
Expected: PASS, including the six dwell tests.

- [ ] **Step 7: Gates and commit**

```bash
cd frontend && npm run verify
cd frontend && npm run test:browser
git add frontend/src
git commit
```

---

### Task 12: Wiring the emitter into the shell

**Files:**
- Create: `frontend/src/app/interaction-log-provider.tsx`
- Modify: `frontend/src/app/App.tsx`
- Test: `frontend/src/app/interaction-log-provider.test.tsx`

**Interfaces:**
- Consumes: `createEmitter`, `installId`, `newBrowserSessionId`, `createDwellTracker`, `container.interactions`.
- Produces: `InteractionLogProvider`, `useInteractionLog(): Emitter`, and a
  no-op emitter for tests and headless renders.

`src/app/**` is excluded from coverage, which is the right home for this: it
is composition, and the logic it composes is tested in Tasks 10 and 11.

**View identity comes from the route.** `useRoute()` in `App.tsx` is the one
place a route change is observed, and `FACETS` in
`presentation/routing/routes.ts` is the closed set that *is* view identity on
a project page. Derive `view` as `home`, `session`, or `project/<facet>` —
never a raw hash, which carries ids and would put content in a field
documented as structural.

Provide a **no-op emitter** as the context default. Every existing component
test renders without this provider, and a hook that threw would break the
whole suite; a hook that silently records nothing is correct for a test and
for a headless render, matching `InMemoryPreferenceStore`'s reasoning.

- [ ] **Step 1: Write the failing tests**

```tsx
import { render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { InteractionLogProvider, useInteractionLog } from './interaction-log-provider.tsx'

const Probe = () => {
  const log = useInteractionLog()
  log.record('EntityOpened', { entity_id: 'a', source: 'graph' })
  return null
}

it('records nothing and throws nothing without a provider', () => {
  /** Every component test in this suite renders without the provider. A hook
   *  that threw would turn one wiring decision into hundreds of failures. */
  expect(() => render(<Probe />)).not.toThrow()
})

it('hands the emitter to anything below it', () => {
  const sink = { send: vi.fn(async () => {}), sendOnUnload: vi.fn() }

  render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <Probe />
    </InteractionLogProvider>,
  )

  expect(sink.send).not.toHaveBeenCalled()
})

it('reports the view it was given', async () => {
  const sink = { send: vi.fn(async () => {}), sendOnUnload: vi.fn() }

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/timeline">
      <Probe />
    </InteractionLogProvider>,
  )
  unmount()

  const batch = sink.send.mock.calls[0]?.[0] as { view: string }[] | undefined
  expect(batch?.some((event) => event.view === 'project/timeline')).toBe(true)
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run --project app src/app/interaction-log-provider.test.tsx`
Expected: FAIL — unresolved import

- [ ] **Step 3: Implement the provider**

```tsx
/** Where the interaction log is switched on.
 *
 * One emitter per page load, since `browser_session_id` is per load and the
 * seq counter has to be shared by everything that records. Mounted above the
 * views so a route change is observed once rather than by each view.
 */

import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'

import type { InteractionSink } from '@application/ports/interaction-log.ts'
import { createDwellTracker } from '@application/interaction-log/dwell.ts'
import { createEmitter, type Emitter } from '@application/interaction-log/emitter.ts'
import {
  installId,
  newBrowserSessionId,
} from '@application/interaction-log/identity.ts'

/** Records nothing, fails at nothing.
 *
 * The context default, because every component test renders without the
 * provider and a throwing hook would turn one composition decision into
 * hundreds of failures. `InMemoryPreferenceStore` exists for the same
 * reason.
 */
const SILENT: Emitter = {
  record: () => {},
  setContext: () => {},
  flush: async () => {},
  flushOnUnload: () => {},
  stop: () => {},
  pending: () => 0,
}

const InteractionLogContext = createContext<Emitter>(SILENT)

export const useInteractionLog = (): Emitter => useContext(InteractionLogContext)

export const InteractionLogProvider = ({
  sink,
  view,
  projectId = null,
  sessionId = null,
  children,
}: {
  sink: InteractionSink
  view: string
  projectId?: string | null
  sessionId?: string | null
  children: ReactNode
}) => {
  const emitter = useMemo(
    () =>
      createEmitter({
        sink,
        now: () => Date.now(),
        installId: installId(),
        browserSessionId: newBrowserSessionId(),
      }),
    [sink],
  )

  const dwell = useMemo(() => createDwellTracker({ emitter }), [emitter])

  useEffect(() => {
    const detach = dwell.attach()
    return () => {
      detach()
      // A last flush by beacon rather than by post: this also runs on a
      // StrictMode double-invoke in development, where a post would race the
      // remount.
      dwell.exit()
      emitter.flushOnUnload()
      emitter.stop()
      detach
    }
  }, [dwell, emitter])

  useEffect(() => {
    emitter.setContext({ projectId, sessionId })
  }, [emitter, projectId, sessionId])

  useEffect(() => {
    dwell.enter(view)
  }, [dwell, view])

  return (
    <InteractionLogContext.Provider value={emitter}>
      {children}
    </InteractionLogContext.Provider>
  )
}
```

Note: StrictMode double-invokes effects in development, so the tracker will
attach, detach and reattach on mount. That is why `exit()` guards on
`view === null` and why the flush on teardown is a beacon. Verify in the
browser that a dev-mode load produces one `ViewEntered` per view and not
three; if it produces duplicates, the fix is a ref guard in the provider, not
a change to the tracker.

- [ ] **Step 4: Wire into `App.tsx`**

Derive the view name from the route and wrap the shell's content. In
`Console`:

```tsx
  const view = viewNameOf(route)
```

with, at module level:

```tsx
/** The view, as the log names it.
 *
 * Derived from the parsed route rather than from `window.location.hash`,
 * because the hash carries ids and `view` is documented as structural. The
 * facet set is closed (`FACETS`), so this cannot grow a value nobody
 * expected.
 */
const viewNameOf = (route: Route): string => {
  if (route.name === 'session') return 'session'
  if (route.name !== 'project') return 'home'
  return `project/${route.selection?.facet ?? 'session'}`
}
```

Then wrap: `<InteractionLogProvider sink={container.interactions} view={view}
projectId={route.name === 'project' ? route.id : null}>` around the existing
`<Shell>…</Shell>`.

- [ ] **Step 5: Run the tests and the full suite**

Run: `cd frontend && npx vitest run --project app src/app/interaction-log-provider.test.tsx`
Expected: PASS (3 tests)

Then: `cd frontend && npm run verify`
Expected: PASS. If existing component tests fail, the silent default is not
being used where it should be — fix that rather than adding the provider to
every test.

- [ ] **Step 6: See it work end to end**

```bash
uv run python -m uvicorn web:app --port 8765
```

Open `http://localhost:8765`, click between a few views, close the tab, then:

```bash
sqlite3 ~/.research-team/interactions.db \
  "select seq, kind, view, json_extract(payload,'\$.dwell_ms') from interaction_events order by seq"
```

Expected: `ViewEntered`/`ViewExited` pairs with plausible dwells, and a
terminal `ViewExited` from the tab close. **This is the spec's success
criterion.** If the terminal exit is missing, the beacon path is broken and
that is the single most important thing in this feature to get right.

- [ ] **Step 7: Gates, rebuild, commit**

```bash
cd frontend && npm run verify
cd frontend && npm run test:browser
cd frontend && npm run build
git add frontend/src research_team/interfaces/web/static
git commit
```

**Second PR boundary.** Navigation and dwell are collecting; semantic actions
are not. That is a coherent, shippable slice.

---

### Task 13: The semantic emission sites

**Files:**
- Modify: `frontend/src/application/research/use-extraction-queue.ts`
- Modify: `frontend/src/application/research/use-dispatch.ts`
- Modify: `frontend/src/application/ask/ask-store.ts`
- Modify: `frontend/src/application/research/graph-store.ts`
- Modify: `frontend/src/presentation/shell/DecisionBar.tsx` (or wherever an approval is decided)
- Test: alongside each, in the existing test file for that unit

**Interfaces:**
- Consumes: `useInteractionLog()` (Task 12) in hooks; an injected `emitter`
  in the store factories.
- Produces: no new exports. Stores that gain an emitter gain a constructor
  parameter, which their existing call sites must pass.

Emit from the **application layer**, at these seams, because they already are
the semantic vocabulary — they know "an extraction was queued" in the terms
the log wants. Not from `onClick` handlers: that scatters instrumentation
across ~200 sites nobody can enumerate and puts an infrastructure concern in
the layer that should be dumb.

For **hooks**, add to the existing `onSuccess`. The mutation's success is the
moment the action is real:

```ts
  const log = useInteractionLog()

  return useMutation({
    mutationFn: (sourceId: SourceId) => documents.extract(projectId, sourceId),
    onSuccess: (_result, sourceId) => {
      log.record('ExtractionQueued', { source_id: sourceId })
      return queryClient.invalidateQueries({
        queryKey: queryKeys.extractionQueue(projectId),
      })
    },
  })
```

For **store factories**, add `emitter` to the injected dependencies,
defaulting to nothing so existing tests need no change:

```ts
export const createAskStore = ({
  ask,
  projectId,
  newChatId,
  emitter,
}: {
  ask: AskRepository
  projectId: ProjectId
  newChatId: () => string
  /** Optional so the many tests that build this store need no change. A
   *  store that records nothing is correct in a test. */
  emitter?: Pick<Emitter, 'record'>
}) => …
```

The sites to add, one per kind, with the payload each carries:

| Kind | Site | Payload |
|---|---|---|
| `EntityOpened` | `graph-store.ts`, where a selection is made | `entity_id`, `source` |
| `ExtractionQueued` | `useExtractDocument.onSuccess` | `source_id` |
| `ExtractionCancelled` | `useCancelExtraction.onSuccess` | `source_id` |
| `DispatchRequested` | `use-dispatch.ts` mutation `onSuccess` | `topic_id`, `action` |
| `AskSubmitted` | `ask-store.ts` `send`, before awaiting | `query_text` |
| `SearchPerformed` | wherever a search resolves | `query_text`, `result_count` |
| `EmptyResultEncountered` | same site, when `result_count === 0` | `where`, `query_length` |
| `ApprovalDecided` | the approval decision handler | `decision`, `latency_ms`, `expanded_details`, `review_id` |
| `ProjectSwitched` | where the project route changes | `to_project_id`, `from_project_id` |
| `ActionRetried` | `ask-store.ts` and search, on a repeat | `action_kind`, `attempt_number` |
| `ActionUndone` | wherever an undo exists | `action_kind`, `target_id` |

**Two of these need judgement, and it must be exercised rather than guessed:**

- **`ApprovalDecided.latency_ms` and `expanded_details`** are the entire
  reason this kind exists — the click-through-versus-deliberation distinction
  from `direction.md` §3. If the approval UI does not currently track when the
  request was shown or whether details were expanded, that state has to be
  added. **Do not emit a zero or a `false` placeholder**: a confident wrong
  value here produces exactly the misleading signal the design set out to
  avoid. If it cannot be measured, omit the kind, say so in the commit
  message, and file a BACKLOG entry.
- **`ActionRetried`** requires knowing the previous action was nearly the
  same. If no such comparison exists, emit it only where it is genuinely
  known (a resubmitted ask with a different prompt in the same session) and
  leave the rest out with a comment.

- [ ] **Step 1: For each site, write the failing test first**

Pattern, in the existing test file for the unit — a fake emitter and an
assertion on what it recorded:

```ts
it('records that an extraction was queued', async () => {
  const recorded: { kind: string; payload: Record<string, unknown> }[] = []
  // …render the hook with an emitter that pushes into `recorded`…

  expect(recorded).toContainEqual({
    kind: 'ExtractionQueued',
    payload: { source_id: 'notes' },
  })
})
```

- [ ] **Step 2: Run each to verify it fails, then implement, then verify it passes**

One site at a time. Run only the file you are changing:
`cd frontend && npx vitest run --project app <path>`

- [ ] **Step 3: Check the emission sites are enumerable**

```bash
cd frontend && grep -rn "\.record(" src --include=*.ts --include=*.tsx | grep -v test
```

Expected: roughly one line per kind above, all in `src/application/**` except
the approval one. Anything in `src/presentation/**` beyond the approval
handler is a site that should have been an application-layer seam — move it
or justify it in a comment.

- [ ] **Step 4: Gates, rebuild, commit**

```bash
cd frontend && npm run verify
cd frontend && npm run build
git add frontend/src research_team/interfaces/web/static
git commit
```

Commit message must list which kinds are emitted and **which are
deliberately not**, with the reason — an unemitted kind in the vocabulary is
a claim the log does not honour, and the next person needs to know it was a
decision.

---

### Task 14: Documentation and the closing sweep

**Files:**
- Modify: `README.md`
- Modify: `BACKLOG.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything.
- Produces: nothing executable.

- [ ] **Step 1: README — the two environment variables**

Add `AGENT_INTERACTION_LOG` and `AGENT_INTERACTION_DB` wherever the other
`AGENT_*` variables are documented. Say what is collected, that
`AskSubmitted` carries the research prompt, and that the switch is one
variable. A user who cannot find out that prompts are logged has not been
told.

- [ ] **Step 2: BACKLOG — what was left undone**

One entry per open item from the spec, with enough detail to pick up:

- No consumer. Both plausible families (friction: aggregate, cross-session;
  preemption: ordered prefix, within-session) are answerable from this log
  and neither is designed.
- No HTTP read route and no browser view, deliberately, mirroring B44's
  reasoning for check telemetry.
- Cross-store correlation is an application-layer join on approximate
  wall-clock; positions from two stores cannot be ordered.
- Any kind in `INTERACTION_EVENTS` that Task 13 left unemitted, with why.
- Per-kind tables, once a consumer's queries are known.

- [ ] **Step 3: CLAUDE.md — only what was learned the hard way**

Add only what cost real time during this build, in the house voice: what the
mistake looked like, and when it was measured rather than reasoned. Candidates,
if they actually bit:

- Appending to a store without publishing produces an empty read model
  silently — if this was hit, say so, since the existing note lives in
  `ontology_recorder.py` where nobody looking at a new feature reads it.
- Two stores means `caught_up` variants matter, and the failure is a 10s
  timeout naming nothing.
- The stale `~/.pyenv` `eventsource` copy that shadows the venv's.

**Do not add anything that was merely true.** This file is for the shape of
failures, and padding it makes the real entries harder to find.

- [ ] **Step 4: All gates, from a clean tree**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
cd frontend && npm run test:browser
cd frontend && npm run build
git status --short
```

`git status --short` must be empty. A dirty tree after `npm run build` means
the committed console does not match `src/` — the fifth gate, which CI reports
as a `frontend` job failure eleven lines below a successful build.

- [ ] **Step 5: Verify against a database that predates the change**

The rule applies to the new store too, even though the recovery is to drop
it:

```bash
cp ~/.research-team/interactions.db /tmp/before.db
# then run the console against it
AGENT_INTERACTION_DB=/tmp/before.db uv run python -m uvicorn web:app --port 8765
```

Confirm rows still land. Note that `local_copy` rewrites checkpoint store ids
for `sessions.db`; a plain `cp` of the interaction database is enough only if
its `projection_checkpoints` positions still name the same path — if starting
raises `PositionForeignError`, that is the same trap, and the copy needs the
same treatment.

- [ ] **Step 6: Commit and open the final PR**

```bash
git add README.md BACKLOG.md CLAUDE.md
git commit
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: name → Task 2 module naming;
scope/out-of-scope → Task 14 BACKLOG; separate store → Tasks 1, 3, 6;
boundaries → Task 6's second test; load-bearing rule and §3 constraints →
Task 2 docstrings and `ApprovalDecided`; identity → Tasks 2, 11; event shape
and `seq` authority → Tasks 2, 10; vocabulary → Task 2; content allowlist →
Task 2 with a pinning test; client emission placement → Task 13; layering →
Task 9; transport → Tasks 9, 10; dwell → Task 11; ingest → Task 7; kill
switch → Tasks 1, 8; persistence → Tasks 3, 4; testing → throughout;
costs/open → Task 14.

**Two gaps found and closed while reviewing.** The spec said "14 kinds" and
the vocabulary has 15 — Task 2 states the tuple is authoritative. The spec
never said where `received_at` is set; Task 7 sets it at ingest and Task 3
asserts it.

**One place the plan knowingly diverges from the spec** and says so at the
site: the spec's `POST /api/interactions` returns `202 {accepted, rejected}`
in all cases, but Task 7 caps the batch at 200 via pydantic `max_length`,
which produces a 422 rather than a 202. That is FastAPI validating the body
before the route runs, and reproducing partial acceptance for an oversized
batch would mean hand-parsing the body. The client's cap is 50, so a 201-event
batch is not a case that occurs.

**Type consistency checked.** `InteractionLogRunner`, `InteractionLogStore`,
`InteractionEventRow`, `InteractionLogProjection`,
`EventStoreInteractionRecorder`, `row_for`, `InteractionSink`,
`HttpInteractionSink`, `createEmitter`, `Emitter`, `createDwellTracker`,
`installId`, `newBrowserSessionId` are spelled identically at every
appearance. `record` is the method name on both the recorder (backend) and
the emitter (frontend) — same verb, different layers, no shared type.
