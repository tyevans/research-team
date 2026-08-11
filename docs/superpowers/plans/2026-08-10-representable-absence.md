# Representable Absence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a research agent record that it looked for something and did not find it, so the attempt is written down instead of being re-derived by every later run — and bound fruitless searching within a turn.

**Architecture:** A gap is recorded against a `Topic`, as the twin of a finding: `TopicGapRecorded(looking_for, tried)` beside `TopicFindingRecorded`. Topics already *are* open questions, so nothing new is built in the knowledge graph and redstring is untouched. `TopicInvestigated` gains an `outcome` so a crashed round stops reading like a fruitless one. `web_search` counts its own consecutive empty results per turn and degrades in band, pointing at `record_gap`.

**Tech Stack:** Python 3.13, `uv`, pytest, eventsource-py (`DeciderAggregate`, `register_event`), pydantic, langchain `@tool`. No new dependencies.

## Global Constraints

- **A gap must never close a topic or silence a trigger.** `TopicPort` has no `close_topic` deliberately (`application/topics.py:94-102`): "an autonomous run that could close its own topics could empty its queue without answering anything." Nothing in this plan may emit `TopicTriggerAcknowledged` or change `TopicStatus`. There is a test whose only job is to fail if that stops being true.
- **`_rework_thrash`'s FIRING CONDITION does not change** (`application/topic_attention.py:347-369`). Only its message changes. A condition depending on `outcome` would report differently about one topic depending on when its rounds happened, because history predates the field.
- **`TopicInvestigated.outcome` defaults to `None`**, not to any real value. This is an event already written; see `CLAUDE.md` on events and `tests/infrastructure/test_schema_evolution.py`.
- **No permission changes.** `TOOL_FLOORS`, `GATED_TOOLS` and `AutonomyPolicy` are untouched. B24 rejects counting as a permission mechanism by name. The search bound is an in-band refusal the model can act on, not a gate.
- **Do not run the full test suite** except where a task says to. Run only the files named in each task. CI runs the suite at PR time.
- **Both ruff gates run over the whole repository**: `uv run ruff check .` and `uv run ruff format --check .`.
- **House style:** docstrings and comments carry the REASONING behind a decision, not a restatement of the code. State costs plainly. Name what a test would fail on.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Stage by explicit path. NEVER `git add -A`** — this repository is worked in concurrently.

## File Structure

| File | Responsibility |
|---|---|
| `research_team/domain/topic.py` | `TopicGapRecorded`, `RecordGap`, decide/evolve arms, `gaps`/`last_gap_at` on state, `TopicInvestigated.outcome` |
| `research_team/application/topics.py` | `record_gap` on `TopicPort` |
| `research_team/infrastructure/agent/topic_tools.py` | the `record_gap` tool, `RepositoryTopics.record_gap`, prompt |
| `research_team/application/topic_attention.py` | `_rework_thrash` message names what was tried |
| `research_team/application/auto_research.py` | `_record_look` passes `outcome` |
| `research_team/infrastructure/agent/search.py` | `SearchAttempts`, the in-band bound |
| `research_team/infrastructure/agent/search_middleware.py` | **New.** Resets the counter at the turn boundary |
| `research_team/composition.py` | wiring |
| `tests/domain/test_topic.py` | domain tests |
| `tests/infrastructure/test_schema_evolution.py` | the old `TopicInvestigated` payload |
| `tests/infrastructure/test_topic_tools.py` | the tool |
| `tests/application/test_topic_attention.py` | the trigger message |
| `tests/infrastructure/test_search.py` | the bound |

---

### Task 1: A gap is recorded against a topic

**Files:**
- Modify: `research_team/domain/topic.py` — event beside `TopicFindingRecorded` (:151-161), command beside `RecordFinding` (:265-268), the `TopicCommand` union (~:305), a `decide` arm after `RecordFinding`'s (:484-491), an `evolve` arm after `TopicFindingRecorded`'s (:631-632), and `TopicState` (:333-390)
- Test: `tests/domain/test_topic.py`

**Interfaces:**
- Produces: `TopicGapRecorded(aggregate_type="Topic", looking_for: str, tried: list[str])`; `RecordGap(looking_for: str, tried: list[str])`; `TopicState.gaps: int = 0`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/domain/test_topic.py`, following the file's existing arrangement (read how its other `decide`/`evolve` tests are written and match them — do not invent a new harness):

```python
def test_a_gap_records_what_was_looked_for_and_what_was_tried() -> None:
    """The twin of a finding. A run that searched five ways and found nothing
    otherwise leaves only the free text "nothing recorded", which every later
    run has to re-derive the absence from."""
    state = _an_open_topic()

    events = decide(
        RecordGap(looking_for="a critique of backward design", tried=["backward design critique", "wiggins mctighe criticism"]),
        state,
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, TopicGapRecorded)
    assert event.looking_for == "a critique of backward design"
    assert event.tried == ["backward design critique", "wiggins mctighe criticism"]


def test_a_gap_with_nothing_tried_is_refused() -> None:
    """A gap with an empty `tried` is indistinguishable from never having
    looked, which is the exact confusion this event exists to remove."""
    state = _an_open_topic()

    with pytest.raises(CommandRejectedError, match="tried"):
        decide(RecordGap(looking_for="a critique", tried=[]), state)


def test_a_gap_with_nothing_looked_for_is_refused() -> None:
    state = _an_open_topic()

    with pytest.raises(CommandRejectedError):
        decide(RecordGap(looking_for="  ", tried=["something"]), state)


def test_a_recorded_gap_counts_but_changes_nothing_else() -> None:
    """Specifically: it does not change status. A run that could mark its own
    questions unanswerable could empty its queue without answering anything,
    which is what `TopicPort` having no `close_topic` exists to prevent."""
    state = _an_open_topic()

    after = evolve(state, TopicGapRecorded(aggregate_id=state.topic_id, looking_for="x", tried=["y"]))

    assert after.gaps == state.gaps + 1
    assert after.status == state.status
    assert after.findings == state.findings
    assert after.sub_questions == state.sub_questions
```

Import `RecordGap` and `TopicGapRecorded` alongside the file's existing imports. `_an_open_topic()` stands for however this file already builds an open topic — find it and use the real one.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/domain/test_topic.py -v -k gap`
Expected: FAIL — `ImportError` / `cannot import name 'RecordGap'`.

- [ ] **Step 3: Add the event**

In `research_team/domain/topic.py`, after `TopicFindingRecorded` (:161):

```python
@register_event
class TopicGapRecorded(DomainEvent):
    """Something was looked for and not found. The unit of ruled-out effort.

    The twin of `TopicFindingRecorded`, and recorded for the same reason: a
    round that produced nothing otherwise leaves only free text, so every later
    run re-derives the same absence from nothing.

    `tried` is what the agent says it attempted, not what the search instance
    was asked -- `format_results` flattens the payload to text at receipt and
    nothing downstream can map a snippet back to its query. It is a claim,
    useful because it tells the next reader what not to repeat, and it should
    not be read as a record of requests actually made.

    Recording a gap does not change status and does not silence anything. It is
    evidence a person decides from.
    """

    aggregate_type: str = "Topic"
    looking_for: str
    tried: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Add the command, the union arm, decide and evolve**

Command, after `RecordFinding` (:268):

```python
@dataclass(frozen=True)
class RecordGap:
    looking_for: str
    tried: list[str] = field(default_factory=list)
```

Add `| RecordGap` to the `TopicCommand` union (~:305), beside `RecordFinding`.

`decide` arm, after `RecordFinding`'s (:491):

```python
        case RecordGap(looking_for=looking_for, tried=tried), _:
            if not looking_for.strip():
                raise CommandRejectedError("a gap needs to say what was looked for")
            if not [item for item in tried if item.strip()]:
                # Both required, for `TopicOpened`'s reason. A gap with nothing
                # tried says only "we do not know", which the topic already
                # said by being open.
                raise CommandRejectedError("a gap needs to say what was tried")
            return [
                TopicGapRecorded(
                    aggregate_id=topic_id, looking_for=looking_for, tried=list(tried)
                )
            ]
```

`evolve` arm, after `TopicFindingRecorded`'s (:632):

```python
        case TopicGapRecorded():
            # Counts, and nothing else. Deliberately does not touch status:
            # see the event's docstring.
            return state.model_copy(update={"gaps": state.gaps + 1})
```

`TopicState` (:333-390) gains, beside `findings`:

```python
    gaps: int = 0
    """Looks that were written down as having found nothing.

    A count, like `findings`, and not a reason to stop: a topic with twenty
    gaps stays live and stays in the queue. Every response to that is a
    person's."""
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/domain/test_topic.py -v`
Expected: PASS, including every pre-existing topic test.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/domain/topic.py tests/domain/test_topic.py
uv run ruff check .
uv run ruff format --check .
git add research_team/domain/topic.py tests/domain/test_topic.py
git commit -m "$(cat <<'EOF'
Record a gap: what was looked for, and what was tried

The twin of `TopicFindingRecorded`. A round that searched five ways and found
nothing left only the free text "nothing recorded" in `TopicInvestigated`, so
the attempt was never written down and every later run re-derived the same
absence from nothing.

Both fields are required. A gap with an empty `tried` is indistinguishable from
never having looked, which is the confusion this exists to remove -- and a topic
that is open already says "we do not know".

`tried` is the agent's claim about what it attempted, not a record of requests
made: `format_results` flattens the search payload to text at receipt, so
nothing downstream can map a snippet back to its query. The docstring says so,
because a field that reads like evidence and is testimony is worse than one
that admits it.

Counts and changes nothing else -- specifically not status. A run that could
mark its own questions unanswerable could empty its queue without answering
anything, which is why `TopicPort` has no `close_topic`.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: A crashed round stops reading like a fruitless one

**Files:**
- Modify: `research_team/domain/topic.py` — `TopicInvestigated` (:131-150), `RecordInvestigation` (:259-263), the `decide` arm (:475-482)
- Modify: `research_team/application/auto_research.py` — `_record_look` (:255-276), and its callers at :239 and :299-310
- Test: `tests/domain/test_topic.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Produces: `TopicInvestigated.outcome: str | None = None`; `RecordInvestigation.outcome: str | None = None`.

- [ ] **Step 1: Write the failing tests**

In `tests/domain/test_topic.py`:

```python
def test_an_investigation_can_say_how_it_ended() -> None:
    """"nothing recorded" and "failed" were the same field with different
    English, so nothing downstream could tell a fruitless round from a broken
    one."""
    state = _an_open_topic()

    events = decide(RecordInvestigation(at_position="000000000042", outcome="failed"), state)

    assert events[0].outcome == "failed"


def test_an_investigation_that_does_not_say_leaves_it_unset() -> None:
    """None means "written before this was recorded", and is not one of the
    three outcomes. Defaulting to a real value would assert something about
    rounds nobody observed."""
    state = _an_open_topic()

    events = decide(RecordInvestigation(at_position="000000000042"), state)

    assert events[0].outcome is None
```

In `tests/infrastructure/test_schema_evolution.py`, following that file's existing pattern of writing an old-shaped payload straight into the events table and reading it back:

```python
async def test_an_investigation_written_before_outcome_existed_still_loads() -> None:
    """Reads back with `outcome` absent, not defaulted to a real value. A
    default of "produced" would claim every historic round found something."""
```

Write the body in the file's established style — read the tests already there and match them exactly.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/domain/test_topic.py tests/infrastructure/test_schema_evolution.py -v -k outcome`
Expected: FAIL — unexpected keyword argument `outcome`.

- [ ] **Step 3: Add the field**

`TopicInvestigated` (:131-150) gains:

```python
    outcome: str | None = None
    """How the round ended: "produced", "nothing", or "failed".

    `None` means the round predates this field, and is deliberately not one of
    the three. Defaulting to "produced" would quietly stop `_rework_thrash`
    counting historic fruitless rounds; defaulting to "nothing" would claim
    every past round found nothing. Neither is a thing anybody observed.

    `summary` stays free text for a person to read. This is the part something
    can branch on -- and what nothing branches on today is exactly why a
    crashed round and a fruitless one were indistinguishable.
    """
```

`RecordInvestigation` (:259-263) gains `outcome: str | None = None`, and the `decide` arm (:475-482) passes it through.

- [ ] **Step 4: Populate it from the driver**

In `research_team/application/auto_research.py`, `_record_look` takes the outcome and passes it. Its two call sites already know which case they are in: the one at `:239` is the failure path (`outcome="failed"`), and the one that uses `_summarize` passes `"nothing"` when `outcome.produced_nothing` and `"produced"` otherwise.

Do NOT change `_summarize`'s text — `summary` stays as it is.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/domain/test_topic.py tests/infrastructure/test_schema_evolution.py tests/application/test_auto_research.py -v`
Expected: PASS. If `tests/application/test_auto_research.py` is not the real filename, find the auto-research tests and run those.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/domain/topic.py research_team/application/auto_research.py tests/domain/test_topic.py tests/infrastructure/test_schema_evolution.py
uv run ruff check .
uv run ruff format --check .
git add research_team/domain/topic.py research_team/application/auto_research.py tests/domain/test_topic.py tests/infrastructure/test_schema_evolution.py
git commit -m "$(cat <<'EOF'
Say how a round ended, rather than implying it in English

`_summarize` wrote "nothing recorded" when a round produced nothing and
`_record_look` wrote "failed" when it raised -- into the same free-text field.
So a fruitless round and a broken one were one event with different English,
and `_rework_thrash`, which counts looks, counted them alike: a topic whose
rounds kept crashing read as one that kept finding nothing.

`outcome` defaults to None, meaning "written before this was recorded", and is
deliberately not one of the three values. "produced" would quietly stop the
thrash trigger counting historic fruitless rounds; "nothing" would claim every
past round found nothing. Neither is a thing anybody observed.

`summary` is untouched. It is for a person to read; this is the part something
can branch on.

The schema-evolution test gains the old payload, per CLAUDE.md: an event
already written must still load.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The `record_gap` tool

**Files:**
- Modify: `research_team/application/topics.py` — `TopicPort` (:94-102)
- Modify: `research_team/infrastructure/agent/topic_tools.py` — `RepositoryTopics`, `build_topic_tools` (:209), `TOPICS_PROMPT` (in `application/topics.py:146`)
- Test: `tests/infrastructure/test_topic_tools.py`

**Interfaces:**
- Consumes: `RecordGap` (Task 1).
- Produces: `TopicPort.record_gap(topic_id: UUID, looking_for: str, tried: list[str]) -> None`; a `record_gap` tool.

- [ ] **Step 1: Write the failing tests**

```python
def test_record_gap_writes_what_was_tried() -> None:
    ...
    assert recorded.looking_for == "a critique of backward design"
    assert recorded.tried == ["backward design critique", "wiggins criticism"]


def test_record_gap_does_not_change_the_topic_status() -> None:
    """The hazard this whole design is shaped around. A tool that let an agent
    declare a question unanswerable is `close_topic` arriving by a side door."""


def test_record_gap_does_not_acknowledge_any_trigger() -> None:
    """`TopicTriggerAcknowledged` is the silencing mechanism and nothing emits
    it from an agent tool. Wiring gaps to it would hand an autonomous run the
    ability to mute its own alarms. This test exists only to fail if that
    changes."""
    ...
    assert not [e for e in events if isinstance(e, TopicTriggerAcknowledged)]


def test_a_gap_the_domain_refuses_comes_back_as_text() -> None:
    """As every other topic tool does: a tool that raises turns a rejection
    into a broken turn."""
```

Read `tests/infrastructure/test_topic_tools.py` and reuse its real fixtures; do not invent parallel doubles.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/test_topic_tools.py -v -k gap`
Expected: FAIL — no `record_gap` tool.

- [ ] **Step 3: Implement**

Add `record_gap` to `TopicPort` with a docstring saying what it must not do (close, silence). Implement it on `RepositoryTopics` following `record_finding`'s shape exactly. Add the tool to `build_topic_tools` beside the existing four, ungated like them:

```python
    @tool(RECORD_GAP_TOOL)
    async def record_gap(topic_id: str, looking_for: str, tried: list[str]) -> str:
        """Record that you looked for something and did not find it."""
```

Errors come back as text, as the other topic tools do.

- [ ] **Step 4: Extend `TOPICS_PROMPT`**

Add to `TOPICS_PROMPT` (`application/topics.py:146`), in the file's voice:

- `record_gap` is for when you looked and found nothing: say what an answer would have looked like and what you actually tried.
- A gap is not a way to close a question. The topic stays open and stays in the queue; what a gap does is stop the next session repeating your searches.
- Recording nothing when you found nothing is the thing that costs later work.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/infrastructure/test_topic_tools.py tests/application/test_topics.py -v`

- [ ] **Step 6: Format, lint, commit** (message in the style of Tasks 1-2: why the tool is ungated, why it cannot close, what it costs.)

---

### Task 4: The thrash trigger names what was tried

**Files:**
- Modify: `research_team/application/topic_attention.py` — `_rework_thrash` (:347-369)
- Test: `tests/application/test_topic_attention.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_thrash_names_what_was_already_tried() -> None:
    """"Change what you are asking" is unactionable unless it says what not to
    repeat."""


def test_thrash_fires_on_exactly_the_same_condition_as_before() -> None:
    """The firing condition is deliberately untouched. A condition depending on
    `outcome` or on gaps would report differently about one topic depending on
    when its rounds happened, because history predates both fields. This test
    fails if the condition is ever made to depend on them."""


def test_thrash_still_fires_with_its_old_message_when_no_gaps_are_recorded() -> None:
```

- [ ] **Step 2: Run to verify they fail.** Run: `uv run pytest tests/application/test_topic_attention.py -v -k thrash`

- [ ] **Step 3: Implement.** Change only the message and suggestion. The `if state.investigations < looks` / `if state.findings > state.findings_at_last_investigation` condition stays byte-identical. Add a comment saying the condition is deliberately independent of `gaps` and `outcome`, and why.

**Note:** `TopicState` carries no gap *text* — only the `gaps` count (Task 1), because `TopicState`'s docstring says "Deliberately absent: any finding text". If the message needs the actual `tried` strings, they must come from the trigger's context rather than from state; if that context is not available, report the count and say so plainly rather than widening `TopicState`. Decide which, and record the choice in the commit message.

- [ ] **Step 4: Run to verify they pass.** Run: `uv run pytest tests/application/test_topic_attention.py -v`

- [ ] **Step 5: Format, lint, commit.**

---

### Task 5: Search bounds itself in band

**Files:**
- Modify: `research_team/infrastructure/agent/search.py`
- Create: `research_team/infrastructure/agent/search_middleware.py`
- Test: `tests/infrastructure/test_search.py`

**Interfaces:**
- Produces: `SearchAttempts` with `record_empty() -> int`, `reset() -> None`, `exhausted() -> bool`; `build_search_tool(..., attempts: SearchAttempts | None = None)`; `SearchAttemptsMiddleware`.

- [ ] **Step 1: Write the failing tests**

```python
def test_search_stops_after_repeated_empty_results() -> None:
    """Not a permission change: the agent is allowed to search. It is being
    told that searching again will not help, in the shape `fetch` already uses
    for a page that will never render."""
    ...
    assert "record_gap" in result


def test_the_counter_resets_on_any_result() -> None:
    """An intermittently productive search is never bounded."""


def test_the_counter_resets_at_the_turn_boundary() -> None:
    """A turn does not inherit the previous turn's misses."""


def test_the_bound_does_not_touch_the_autonomy_policy() -> None:
    """B24 rejects counting as a permission mechanism by name. This test fails
    if the bound is ever implemented as a gate."""
    from research_team.application.autonomy import GATED_TOOLS, TOOL_FLOORS
    assert TOOL_FLOORS == {"fetch": "ask", "advance_stage": "ask"}
```

Reuse `tests/infrastructure/test_search.py`'s real stub client.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement `SearchAttempts` and the bound.** Count only results equal to `"No results."`; reset on anything else. Past `MAX_EMPTY_SEARCHES` (a module constant, default 3), return the notice instead of searching. The notice names the count and `record_gap`. Errors are NOT counted — an unreachable instance is not an absent answer, and counting it would tell the model to record a gap it has no evidence for.

- [ ] **Step 4: Reset at the turn boundary.** A small `AgentMiddleware` following `StageMiddleware`'s shape (`infrastructure/agent/stage_middleware.py:117`), including its explicit `name` property — `factory.py` raises on two middleware sharing a name.

- [ ] **Step 5: Run to verify they pass.** Run: `uv run pytest tests/infrastructure/test_search.py -v`

- [ ] **Step 6: Format, lint, commit.**

---

### Task 6: Wire it, and run all four gates

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/integration/` — the file that asserts a project's tool set

- [ ] **Step 1: Write the failing test** — a project registers `record_gap`; the search tool is built with a `SearchAttempts`; the middleware is installed.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Wire.** One `SearchAttempts`, handed to `build_search_tool` and to the middleware — the same object, or the reset never reaches the counter the tool reads. That is this task's silent-failure mode, exactly as the shared `PageMemo` was in the last plan.

- [ ] **Step 4: All four gates.**

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Do not run two vitest processes at once. Report actual output; do not claim a gate passed without showing it. Expect prompt assertions to fail — `TOPICS_PROMPT` changed in Task 3, and the prompts are now pinned by tests added in the previous feature. Update them to the new text; do NOT weaken them to substrings that pass either way.

- [ ] **Step 5: Commit by explicit path.**

---

## Self-Review

**Spec coverage.** §1 (a gap is the twin of a finding) → Tasks 1 and 3. §2 (never closes, never silences) → Task 1's `test_a_recorded_gap_counts_but_changes_nothing_else` and Task 3's two hazard tests. §3 (thrash names what was tried) → Task 4. §4 (search bounds itself in band) → Task 5, including the rejected-permission alternative as an explicit test. §5 (`outcome`) → Task 2, with the schema-evolution case. Every spec "Testing" bullet maps to a named test above.

**Placeholders.** Tasks 1 and 2 carry complete code. Tasks 3-6 carry test names, docstrings and precise instructions rather than full bodies, because each is a small edit shaped by a file's existing fixtures that the implementer must read anyway — the previous plan's placeholder helper names caused three separate adaptations, and prescribing bodies here would cause more. Every such step names the real file and the real function to copy from. Task 4 Step 3 contains a genuine open decision (where the `tried` text comes from) stated as a decision to make and record, not as a gap to fill silently.

**Type consistency.** `tried` is `list[str]` on the command, the event and the tool. `looking_for` is `str` everywhere. `outcome` is `str | None` on both `RecordInvestigation` and `TopicInvestigated`, never a bare `str`, and never defaulted to a real value. `gaps` is `int` on `TopicState`, matching `findings`.

**Ordering hazard.** Tasks 1, 2 and 5 are inert. Task 3 makes the gap reachable by an agent, and Task 6 is the first point where the whole thing is exercised. Task 6 is the only task that runs the full suite and all four gates.

**One thing an executor will be tempted to do and must not.** Task 4's trigger message is easier to write if `_rework_thrash` branches on `gaps` or `outcome`. It must not — the firing condition stays byte-identical, and a test exists to enforce it. A topic's history predates both fields, so a condition reading them reports differently about the same topic depending on when its rounds happened.
