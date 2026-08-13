# Check Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record what the check library found and what the human decided about it, so per-check fire rate, override rate and time-to-decision are queryable instead of arguable.

**Architecture:** A new session event `StageChecksEvaluated` records every *bound* check at each gate (not just the ones that fired, because a rate needs a denominator). `ToolCallDecided` gains a nullable `review_id` joining a decision back to its review. A projection over the `CodingSession` stream folds the two into one `check_outcomes` table — rows written when the review lands, decision columns filled when the decision arrives later. A read port aggregates that table into per-check statistics, surfaced by a REPL `/checks` command.

**Tech Stack:** Python 3.12+, pydantic v2, `eventsource-py` (`DomainEvent`, `ReadModel`, `DeclarativeProjection`, `SubscriptionManager`), aiosqlite/SQLAlchemy for the read model, pytest.

**Spec:** `docs/superpowers/specs/2026-08-12-check-telemetry-design.md` — read it before starting. It carries the reasoning this plan does not repeat, in particular the four honesty constraints, each of which becomes a test here.

## Global Constraints

- **Four verification gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The two ruff commands run over the **whole repository**, not the files you touched.
- **Do not run the full `pytest` suite locally.** Run only the test files your task touches, then let CI run the rest. Full-suite runs are wasteful here. Do not run `npm run verify` either — this change touches no frontend code.
- **Never run two `vitest` processes at once.** Not applicable to any task here; noted because it is a standing repository rule.
- **Layering is enforced** by `tests/test_architecture.py`: `domain` may import only `domain`; `application` may import `domain` and `application`; `infrastructure` may import all three; `interfaces` may import anything. `domain` and `application` may import `eventsource` and **no other framework** — not `aiosqlite`, not `sqlalchemy`. No module under `research_team/` may import `research_team.composition`.
- **Stage files by explicit path.** Never `git add -A` or `git add .`.
- **Commit trailer, exactly:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, say when something was measured rather than reasoned. A comment that restates the code is worse than none.
- **Prove every new test red before trusting it green.** Paste the actual failure output into your report. If a test would pass with your change reverted, say so in its docstring rather than leaving it as reassurance.
- **A read-model change verified only against a fresh database is unverified.** Task 4 must exercise `apply_schema` against a database that predates the change.

---

### Task 1: The event, the command, and the join key

**Files:**
- Modify: `research_team/domain/events.py` (add `StageChecksEvaluated`; add `review_id` to `ToolCallDecided:184`; extend `SESSION_EVENTS:216`)
- Modify: `research_team/domain/commands.py` (add `RecordStageReview` after `RecordToolDecision:125`)
- Modify: `research_team/domain/session.py` (handle both in `decide`, around the supervision block at `:247-270`)
- Test: `tests/domain/test_session.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `StageChecksEvaluated(aggregate_id: UUID, review_id: UUID, project_id: UUID, stage: str, preset: str, preset_version: str, evaluated: list[dict[str, Any]], unimplemented: list[dict[str, Any]], posed_by: str)`
  - `ToolCallDecided(..., review_id: UUID | None = None)`
  - `RecordStageReview(review_id, project_id, stage, preset, preset_version, evaluated, unimplemented, posed_by)` — a `Command`
  - `RecordToolDecision(..., review_id: UUID | None = None)`

Note both `evaluated` and `unimplemented` are lists of dicts. `evaluated` entries are `{"check": str, "severity": str, "findings": int}`; `unimplemented` entries are `{"check": str, "severity": str}`. `unimplemented` is a list of dicts rather than bare names because the read model needs the binding's declared severity for those rows, and the registry has no spec to resolve one from.

- [ ] **Step 1: Write the failing domain tests**

Add to `tests/domain/test_session.py`:

```python
def test_a_stage_review_is_recorded_as_an_audit_event() -> None:
    """`RecordStageReview` produces one event and touches no state.

    Fails if the command is unhandled, and fails differently if someone makes
    `evolve` fold it: `SessionState` tracks what the session *is*, and what a
    check found at a gate is not that.
    """
    session_id = uuid4()
    state = initial_state()
    review_id = uuid4()
    project_id = uuid4()

    events = decide(
        RecordStageReview(
            review_id=review_id,
            project_id=project_id,
            stage="analysis",
            preset="hybrid.default",
            preset_version="1",
            evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 2}],
            unimplemented=[{"check": "ubd.uncoverage", "severity": "blocking"}],
            posed_by="runner",
        ),
        state,
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, StageChecksEvaluated)
    assert event.aggregate_id == session_id or event.aggregate_id is not None
    assert event.review_id == review_id
    assert event.project_id == project_id
    assert event.stage == "analysis"
    assert event.posed_by == "runner"
    assert event.evaluated == [
        {"check": "shared.coverage", "severity": "blocking", "findings": 2}
    ]
    assert event.unimplemented == [{"check": "ubd.uncoverage", "severity": "blocking"}]
    # The audit half: nothing about the session changed.
    assert evolve(state, event) is state or evolve(state, event) == state


def test_a_tool_decision_can_name_the_review_it_answers() -> None:
    """`review_id` rides through `RecordToolDecision` onto the event.

    This is the only join between a finding and the decision that followed it;
    `ToolCallDecided` names no stage and `StageAdvanced` is on another stream
    and is not written at all when a gate is rejected.
    """
    review_id = uuid4()
    events = decide(
        RecordToolDecision(
            tool_name="advance_stage",
            args={"rationale": "3 findings"},
            decision="approve",
            decided_by="human",
            review_id=review_id,
        ),
        initial_state(),
    )
    assert events[0].review_id == review_id


def test_a_tool_decision_that_answers_no_review_says_so() -> None:
    """The default is None, which is what every non-gate tool call means."""
    events = decide(
        RecordToolDecision(
            tool_name="web_search",
            args={"query": "x"},
            decision="approve",
            decided_by="human",
        ),
        initial_state(),
    )
    assert events[0].review_id is None
```

Match the file's existing import style and its convention for building a
session id — read the top of `tests/domain/test_session.py` and follow it
rather than copying the sketch above verbatim if it differs.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_session.py -k "stage_review or names_the_review or answers_no_review" -v`
Expected: FAIL — `ImportError` / `NameError` on `RecordStageReview` and `StageChecksEvaluated`.

- [ ] **Step 3: Add the event**

In `research_team/domain/events.py`, after `ToolCallDecided`:

```python
@register_event
class StageChecksEvaluated(DomainEvent):
    """What the check library found at a gate, and what it was asked to check.

    Recorded because the findings themselves are a *file* -- one per stage
    number, overwritten by the next review of that stage -- so the only durable
    record of what the checks found describes the most recent run and nothing
    before it. A question like "does this check ever pass?" has no evidence to
    answer it from.

    **`evaluated` holds every bound check, not every finding**, and that is the
    field this event exists for. A fire rate needs a denominator, and the
    denominator is the runs where a check ran and found nothing. An event
    modelled on the findings file -- which lists only findings -- can count
    numerators forever and never produce a rate.

    No message and no `cites`: the counts are the fact, the prose is already in
    `/course/NN-check-findings.md`, and putting it here too would make every
    review permanent at the size of its worst output and fold it into every
    snapshot. `corpus.py` holds no document text for the same reason.

    `posed_by` distinguishes the two gate paths because it decides whether a
    duration means anything. On the runner path this event and the
    `ToolCallDecided` that answers it are appended separately, so their
    `occurred_at` values bracket a human's deliberation. On the tool path both
    land at `_save_turn`, milliseconds apart, and the difference measures
    serialization -- so a consumer must report no duration rather than a fast
    one. See BACKLOG.md B36 for why the tool path is like that.
    """

    aggregate_type: str = "CodingSession"
    review_id: UUID
    """Joins this review to the decision that answered it.

    A field of our own rather than the inherited `correlation_id`: that one
    belongs to whatever is tracing, and a join that borrowed it would break
    silently the first time a tracer is wired.
    """
    project_id: UUID
    stage: str
    preset: str
    preset_version: str
    evaluated: list[dict[str, Any]]
    """One entry per bound check that ran: `check`, `severity`, `findings`.

    `findings: 0` means it ran and passed. `severity` is the one `run_check`
    resolved -- a spec's `fixed_severity` where it has one, the binding's
    otherwise -- because that is the severity the finding would have carried.
    """
    unimplemented: list[dict[str, Any]]
    """One entry per binding naming no registered check: `check`, `severity`.

    Separate from `evaluated` because such a check neither ran nor passed, and
    folding it into either would make one of the two rates lie. The severity is
    the binding's own; there is no spec to resolve a fixed one from, which is
    what being unimplemented means.
    """
    posed_by: str
    """`runner` or `tool`."""
```

`UUID` and `Any` are already imported in that module — verify rather than assume.

Add `review_id` to `ToolCallDecided`, after `edited_args`:

```python
    review_id: UUID | None = None
    """The stage review this decision answered, when it answered one.

    None for every gated call that is not an `advance_stage`, and for every
    `advance_stage` decided before this field existed -- which is what its
    absence always meant. `ToolCallDecided` names no stage otherwise, and
    `StageAdvanced`, which does, is on the `Project` stream and is not written
    at all when a gate is rejected. So this is the only join.
    """
```

Add `StageChecksEvaluated` to `SESSION_EVENTS`.

- [ ] **Step 4: Add the command and the decide case**

In `research_team/domain/commands.py`, after `RecordToolDecision`:

```python
class RecordStageReview(Command):
    """The check library ran at a gate; here is what it was asked and found."""

    review_id: UUID
    project_id: UUID
    stage: str
    preset: str
    preset_version: str
    evaluated: list[dict[str, Any]]
    unimplemented: list[dict[str, Any]]
    posed_by: str
```

Add `review_id: UUID | None = None` to `RecordToolDecision`.

In `research_team/domain/session.py`, extend the supervision block. Update the
comment above it — it currently says "Both of these", and there are now three:

```python
        # ---- supervision ----
        # All three are audit records: what was decided about a tool call, how
        # a tool's autonomy level changed, and what the checks found at a gate.
        # None is a fact `SessionState` tracks, so `evolve` deliberately leaves
        # them alone. A stage review in particular is about a moment rather
        # than about the session, and folding it would put a growing list into
        # every snapshot.
        case RecordToolDecision(
            tool_name=tool_name,
            args=args,
            decision=decision,
            decided_by=decided_by,
            edited_args=edited_args,
            review_id=review_id,
        ), _:
            return [
                ToolCallDecided(
                    aggregate_id=session_id,
                    tool_name=tool_name,
                    args=args,
                    decision=decision,
                    decided_by=decided_by,
                    edited_args=edited_args,
                    review_id=review_id,
                )
            ]

        case RecordStageReview(
            review_id=review_id,
            project_id=project_id,
            stage=stage,
            preset=preset,
            preset_version=preset_version,
            evaluated=evaluated,
            unimplemented=unimplemented,
            posed_by=posed_by,
        ), _:
            return [
                StageChecksEvaluated(
                    aggregate_id=session_id,
                    review_id=review_id,
                    project_id=project_id,
                    stage=stage,
                    preset=preset,
                    preset_version=preset_version,
                    evaluated=evaluated,
                    unimplemented=unimplemented,
                    posed_by=posed_by,
                )
            ]
```

Export `StageChecksEvaluated` and `RecordStageReview` from `research_team/domain/__init__.py` if that module lists the neighbouring names — check `ToolCallDecided` and `RecordToolDecision` and follow whatever it does for them.

- [ ] **Step 5: Run the domain tests to verify they pass**

Run: `uv run pytest tests/domain/test_session.py -v`
Expected: PASS, including everything that was already there.

- [ ] **Step 6: Write the schema-evolution case, and prove it red**

`ToolCallDecided` gained a field, so an old payload must still load. Add to
`tests/infrastructure/test_schema_evolution.py`, following the file's existing
`_write_old_event` convention exactly:

```python
async def test_a_decision_written_before_review_ids_still_loads(
    repository, session_id, db_path
) -> None:
    """An old `ToolCallDecided` has no `review_id`, and None is what it meant.

    Absence means "this decision answered no stage review", which is true of
    every decision recorded before the field existed and of every gated call
    that is not an advance. Reading the field as anything else would invent a
    join that was never made.
    """
    await _write_old_event(
        db_path,
        session_id,
        version=2,
        event_type="ToolCallDecided",
        payload={
            "tool_name": "web_search",
            "args": {"query": "backward design"},
            "decision": "approve",
            "decided_by": "human",
        },
    )

    events = await repository.events_for(session_id)
    decided = [event for event in events if isinstance(event, ToolCallDecided)]
    assert decided, "the old payload did not load at all"
    assert decided[-1].review_id is None
```

Read the file's existing cases first: the `version=` to pass depends on what
`started` already wrote, and the fixtures come from `tests/conftest.py`. Adjust
to match rather than assuming the numbers above.

To prove this case is load-bearing rather than reassurance, temporarily make
`review_id` required (drop `= None`), run it, and confirm it fails with a
pydantic validation error naming the missing field. Paste that output into your
report. Then restore the default.

- [ ] **Step 7: Run the schema-evolution tests**

Run: `uv run pytest tests/infrastructure/test_schema_evolution.py -v`
Expected: PASS.

- [ ] **Step 8: Both ruff gates**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: both clean, repository-wide.

- [ ] **Step 9: Commit**

```bash
git add research_team/domain/events.py research_team/domain/commands.py \
        research_team/domain/session.py research_team/domain/__init__.py \
        tests/domain/test_session.py tests/infrastructure/test_schema_evolution.py
git commit
```

Message: say why the event carries every bound check rather than every finding,
and why `review_id` is a field of its own rather than the inherited
`correlation_id`.

---

### Task 2: The denominator — `StageReview.evaluated`

**Files:**
- Modify: `research_team/application/stage_exit.py` (`StageReview:76`, `review_stage:272`, `__all__:40`)
- Test: `tests/application/test_stage_exit.py`

**Interfaces:**
- Consumes: nothing from Task 1 (this task is independent of it and may run in parallel).
- Produces:
  - `EvaluatedCheck(check: str, severity: FindingSeverity, findings: int)` — frozen dataclass in `stage_exit.py`
  - `StageReview.evaluated: tuple[EvaluatedCheck, ...] = ()`
  - `StageReview.unimplemented_bindings: tuple[EvaluatedCheck, ...] = ()` — the unimplemented ones with their declared severity and `findings=0`

Keep the existing `StageReview.unimplemented: tuple[str, ...]` field exactly as
it is. `render_review` and `gate_context` both read it, and changing its type
would ripple into the findings file's rendering and the browser's gate context
for no benefit. The new field carries the extra severity alongside it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/application/test_stage_exit.py`:

```python
def test_a_review_reports_the_checks_that_passed_as_well_as_those_that_fired() -> None:
    """Without this, a fire rate has a numerator and no denominator.

    Fails against the previous `StageReview`, which reported findings and
    unimplemented names and said nothing about a binding that ran cleanly --
    so "this check has never once fired" and "this check has never run" were
    indistinguishable.
    """
    preset, stage = _preset_with_checks(
        [
            Check(check="shared.coverage", params={...}),
            Check(check="shared.orphan", params={...}),
        ]
    )
    review = review_stage(preset, stage, _files_that_satisfy_orphan_only())

    by_name = {entry.check: entry for entry in review.evaluated}
    assert set(by_name) == {"shared.coverage", "shared.orphan"}
    assert by_name["shared.orphan"].findings == 0
    assert by_name["shared.coverage"].findings > 0


def test_an_evaluated_check_carries_the_severity_the_finding_would_have() -> None:
    """A spec's `fixed_severity` wins over the binding's, as `run_check` decides.

    `shared.verdict_citation` is registered `fixed_severity="invariant"`. A
    binding that says `advisory` does not get to soften it, and a report that
    recorded the binding's word would be wrong for exactly the two checks where
    severity carries the most weight.
    """
    preset, stage = _preset_with_checks(
        [Check(check="shared.verdict_citation", params={...}, severity="advisory")]
    )
    review = review_stage(preset, stage, _files_with_an_uncited_verdict())

    entry = next(e for e in review.evaluated if e.check == "shared.verdict_citation")
    assert entry.severity == "invariant"


def test_an_unimplemented_binding_is_not_reported_as_having_passed() -> None:
    """`findings == 0` must never be readable as "ran and found nothing".

    A binding naming no registered check neither ran nor passed. It stays out
    of `evaluated` entirely and appears in `unimplemented_bindings` with the
    severity the binding declared -- there is no spec to resolve a fixed one
    from, which is what being unimplemented means.
    """
    preset, stage = _preset_with_checks(
        [Check(check="shared.no_such_check", params={}, severity="advisory")]
    )
    review = review_stage(preset, stage, {})

    assert review.evaluated == ()
    assert [e.check for e in review.unimplemented_bindings] == ["shared.no_such_check"]
    assert review.unimplemented_bindings[0].severity == "advisory"
    assert review.unimplemented == ("shared.no_such_check",)


def test_a_check_that_raises_is_recorded_as_having_fired() -> None:
    """From the gate's point of view a crashed check is a check that blocked.

    A fire rate that excluded crashes would under-report the cost of a broken
    check, which is the thing most worth surfacing. The message says it
    crashed; the count says it fired.
    """
    preset, stage = _preset_with_checks([Check(check="shared.coverage", params={...})])
    review = review_stage(preset, stage, _files_that_make_coverage_raise())

    entry = next(e for e in review.evaluated if e.check == "shared.coverage")
    assert entry.findings == 1
    assert entry.severity == "blocking"
```

**The `...` placeholders above are yours to fill from the existing file.**
`tests/application/test_stage_exit.py` already builds presets, stages and course
files for every check in the registry — find its helpers and reuse them rather
than inventing new ones. If there is no existing way to make a check raise,
monkeypatch one entry of `checks.REGISTRY` with a spec whose `run` raises, and
restore it; do not add a permanently-broken check to the registry.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/application/test_stage_exit.py -k "passed_as_well or severity_the_finding or not_reported_as_having_passed or raises_is_recorded" -v`
Expected: FAIL — `AttributeError: 'StageReview' object has no attribute 'evaluated'`.

- [ ] **Step 3: Add `EvaluatedCheck` and the two fields**

In `research_team/application/stage_exit.py`, above `StageReview`:

```python
@dataclass(frozen=True)
class EvaluatedCheck:
    """One binding, and how much it had to say.

    `findings` is a count and not the findings themselves: this record exists
    so that a rate can be computed over many reviews, and the prose is in the
    findings file. `findings == 0` means the check ran and passed, which is the
    observation the findings file structurally cannot make.
    """

    check: str
    severity: FindingSeverity
    findings: int
```

On `StageReview`:

```python
    evaluated: tuple[EvaluatedCheck, ...] = ()
    """Every binding that ran, whether or not it found anything.

    The denominator. `findings` and `unimplemented` between them say what went
    wrong; only this says what was asked, and without it "never fires" and
    "never runs" are the same observation.
    """
    unimplemented_bindings: tuple[EvaluatedCheck, ...] = ()
    """`unimplemented`, with the severity each binding declared.

    A second field rather than a wider `unimplemented`, because that one is
    read by `render_review` and `gate_context` and reaches a browser as a list
    of names. Widening it would rewrite the findings file's rendering to carry
    a severity nobody reading it needs.
    """
```

Add `EvaluatedCheck` to `__all__`.

- [ ] **Step 4: Populate them in `review_stage`**

`run_check` resolves severity as `spec.fixed_severity or binding.severity`.
Rather than duplicating that expression here — where it would drift the first
time the rule changes — count the findings the call returned and read the
severity off them, falling back to the binding when a check returned nothing:

```python
    findings: list[Finding] = []
    evaluated: list[EvaluatedCheck] = []
    unimplemented: list[str] = []
    unimplemented_bindings: list[EvaluatedCheck] = []
    for binding in stage.checks:
        try:
            produced = run_check(binding, context)
        except UnknownCheck:
            unimplemented.append(binding.check)
            unimplemented_bindings.append(
                EvaluatedCheck(check=binding.check, severity=binding.severity, findings=0)
            )
            continue
        except MalformedCheck as error:
            produced = [
                Finding(
                    check=binding.check,
                    severity="blocking",
                    message=f"{error}",
                    suggested_edit="correct the parameters this check is bound with",
                )
            ]
        except Exception as error:  # noqa: BLE001 -- see the module docstring
            produced = [
                Finding(
                    check=binding.check,
                    severity="blocking",
                    message=(
                        f"{binding.check} raised {type(error).__name__}: {error}. "
                        f"It did not run, so nothing it would have found is known."
                    ),
                    suggested_edit="report this: the check itself is broken",
                )
            ]
        findings.extend(produced)
        # Severity off the findings rather than recomputed: `run_check` owns
        # the `fixed_severity or binding.severity` rule and this would be the
        # second copy of it. A check that produced nothing has no finding to
        # read it from, and the binding's own word is right there -- a check
        # that passed did not carry a severity anywhere.
        evaluated.append(
            EvaluatedCheck(
                check=binding.check,
                severity=produced[0].severity if produced else binding.severity,
                findings=len(produced),
            )
        )
```

Then pass `evaluated=tuple(evaluated)` and
`unimplemented_bindings=tuple(unimplemented_bindings)` into the returned
`StageReview`, keeping every existing field unchanged.

Note the restructuring: `run_check`'s result is now bound to `produced` in every
branch instead of being extended inline, so that the count is available. Verify
by reading the existing function that no other behaviour shifted — in
particular that a `MalformedCheck` still yields exactly one blocking finding and
that `UnknownCheck` still `continue`s without adding to `findings`.

- [ ] **Step 5: Run the whole file**

Run: `uv run pytest tests/application/test_stage_exit.py -v`
Expected: PASS, all of it. The existing tests are the regression surface for
the restructuring in Step 4; if any of them fails, the restructuring is wrong,
not the test.

- [ ] **Step 6: Run the neighbouring suites that consume a `StageReview`**

Run: `uv run pytest tests/application/test_stage_runner.py tests/application/test_course.py -v`
Expected: PASS. (If `test_course.py` is named otherwise, find it — `course.py`
calls `review_stage` on every course view.)

- [ ] **Step 7: Both ruff gates, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/stage_exit.py tests/application/test_stage_exit.py
git commit
```

Message: the denominator argument, and why severity is read off the produced
findings rather than recomputed.

---

### Task 3: Emitting at both gates

**Files:**
- Modify: `research_team/application/session_service.py` (add `record_stage_review` beside `record_tool_decision:694`; add `review_id` to `record_tool_decision`)
- Modify: `research_team/application/stage_runner.py` (`_gate_and_advance:614`)
- Modify: `research_team/application/ports.py` (`GateReview:308`)
- Modify: `research_team/composition.py` (`gate_review:843`)
- Modify: `research_team/infrastructure/agent/deep_agent.py` (`_decide:490`, `_apply:566`)
- Test: `tests/application/test_stage_runner.py`, `tests/integration/test_advance_stage_gate.py`

**Interfaces:**
- Consumes: `RecordStageReview`, `StageChecksEvaluated`, `ToolCallDecided.review_id` (Task 1); `StageReview.evaluated`, `StageReview.unimplemented_bindings`, `EvaluatedCheck` (Task 2). **Both must be committed before this task starts.**
- Produces:
  - `SessionService.record_stage_review(session_id: UUID, review_id: UUID, project_id: UUID, stage: str, preset: str, preset_version: str, evaluated: tuple[EvaluatedCheck, ...], unimplemented: tuple[EvaluatedCheck, ...], posed_by: str) -> None`
  - `SessionService.record_tool_decision(..., review_id: UUID | None = None)`
  - `GateReview(context: dict, refusal: str | None = None, review_id: UUID | None = None)`

- [ ] **Step 1: Write the failing runner tests**

Add to `tests/application/test_stage_runner.py`:

```python
async def test_the_gate_records_what_the_checks_were_asked(...) -> None:
    """Every bound check reaches the log, not only the ones that fired."""
    # drive a run to a gate that is approved; then:
    reviews = [e for e in await service.history(session_id) if isinstance(e, StageChecksEvaluated)]
    assert len(reviews) == 1
    assert reviews[0].posed_by == "runner"
    assert {entry["check"] for entry in reviews[0].evaluated} == set(bound_check_names)


async def test_the_decision_names_the_review_it_answered(...) -> None:
    """The join. Fails if `review_id` is dropped anywhere along the path."""
    events = await service.history(session_id)
    review = next(e for e in events if isinstance(e, StageChecksEvaluated))
    decision = next(
        e for e in events
        if isinstance(e, ToolCallDecided) and e.tool_name == "advance_stage"
    )
    assert decision.review_id == review.review_id


async def test_a_rejected_gate_still_records_both(...) -> None:
    """Rejections are the signal an override rate is measured against.

    They are also the case with no `StageAdvanced` behind them -- the project
    stream records nothing at all when a gate is refused -- so if this pair is
    missing, the most interesting outcome is the one that leaves no trace.
    """
    # drive a run to a gate and reject it; then assert both events exist and
    # that the decision's review_id matches, and that decision == "reject".


async def test_a_gate_nobody_was_asked_to_open_is_recorded_as_policy(...) -> None:
    """`advance_stage: auto` emits both events with decided_by="policy".

    Recorded rather than skipped, because a standing approval is a real
    outcome; reported separately by the read surface, because counting it as
    an override would describe a system ignoring its checks when what happened
    is that nobody was asked.
    """


async def test_a_denied_gate_records_the_review_it_refused(...) -> None:
    """`advance_stage: deny` never poses anything, and the checks still ran."""
```

Fill these in from the file's existing fixtures — it already drives
`StageRunner` to a gate with a stub `ApprovalPort` for approve, reject and the
autonomy levels. Reuse those; do not build new harnesses.

Also add to `tests/application/test_course.py` (or wherever `course_progress`
is tested) the honesty test the spec requires:

```python
async def test_viewing_a_course_records_no_telemetry() -> None:
    """`course_progress` recomputes findings on every view and must not count.

    Emission is at the gate, not in `review_stage`, precisely so that a page
    refresh is not a check run. Fails if anyone moves the event into
    `review_stage`, which is the obvious-looking place for it.
    """
    before = await service.history(session_id)
    await course_progress(...)
    after = await service.history(session_id)
    assert [e for e in after if isinstance(e, StageChecksEvaluated)] == [
        e for e in before if isinstance(e, StageChecksEvaluated)
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/application/test_stage_runner.py -k "checks_were_asked or names_the_review or rejected_gate_still or nobody_was_asked or denied_gate_records" -v`
Expected: FAIL — no `StageChecksEvaluated` in the history.

- [ ] **Step 3: Add the service method**

In `research_team/application/session_service.py`, after `record_tool_decision`:

```python
    async def record_stage_review(
        self,
        session_id: UUID,
        review_id: UUID,
        project_id: UUID,
        stage: str,
        preset: str,
        preset_version: str,
        evaluated: tuple[EvaluatedCheck, ...],
        unimplemented: tuple[EvaluatedCheck, ...],
        posed_by: str,
    ) -> None:
        """Note what the checks were asked at a gate, and what they answered.

        Appends immediately, for `record_tool_decision`'s reason and one of its
        own: the decision that answers this review is appended separately a
        moment later, and the gap between the two `occurred_at` values is the
        only measurement of how long a reviewer took. Deferring either to a
        turn would collapse that gap into a commit boundary.
        """
        aggregate = await self._repository.load(session_id)
        aggregate.execute(
            RecordStageReview(
                review_id=review_id,
                project_id=project_id,
                stage=stage,
                preset=preset,
                preset_version=preset_version,
                evaluated=[
                    {"check": e.check, "severity": e.severity, "findings": e.findings}
                    for e in evaluated
                ],
                unimplemented=[
                    {"check": e.check, "severity": e.severity} for e in unimplemented
                ],
                posed_by=posed_by,
            )
        )
        await self._repository.save(aggregate)
```

Add `review_id: UUID | None = None` to `record_tool_decision`'s signature and
pass it into `RecordToolDecision`.

- [ ] **Step 4: Wire the runner path**

In `_gate_and_advance`, after the existing `write_file` call:

```python
        review_id = uuid4()
        await self._session.record_stage_review(
            session_id,
            review_id=review_id,
            project_id=workflow.project_id,
            stage=stage.id,
            preset=preset.id,
            preset_version=str(preset.version),
            evaluated=review.evaluated,
            unimplemented=review.unimplemented_bindings,
            posed_by="runner",
        )
```

Then pass `review_id=review_id` to **both** `record_tool_decision` calls in the
function — the `deny` branch at the top as well as the main one. The deny branch
is a decision and is exactly the kind an override rate must not silently drop.

`workflow.project_id` may not exist on `StageWorkflow`. Check the port
(`application/ports.py`) and its adapter
(`infrastructure/persistence/project_workflow.py`). If there is no project id
available, add a read-only `project_id` property to the port and its adapter
rather than threading a new parameter through `_gate_and_advance` — the runner
already holds the workflow and the id is a property of it.

Add a comment above the `record_stage_review` call saying why it is here rather
than inside `review_stage`: `course_progress` calls `review_stage` on every
course view, and instrumenting the computation would count page refreshes as
check runs.

- [ ] **Step 5: Wire the tool path**

`research_team/application/ports.py` — add to `GateReview`:

```python
    review_id: UUID | None = None
    """The review recorded on the session stream, for the decision to name.

    None when there was no review to record, which is every tool that is not
    an advance. It is on this DTO because the reviewer and the decider are
    different functions in different layers, and the id has to cross between
    them; nothing else about the review does.
    """
```

`research_team/composition.py` — in `gate_review`, beside the existing
`WriteFile`:

```python
        review_id = uuid4()
        session.execute(
            RecordStageReview(
                review_id=review_id,
                project_id=project_id,
                stage=stage.id,
                preset=preset.id,
                preset_version=str(preset.version),
                evaluated=[
                    {"check": e.check, "severity": e.severity, "findings": e.findings}
                    for e in review.evaluated
                ],
                unimplemented=[
                    {"check": e.check, "severity": e.severity}
                    for e in review.unimplemented_bindings
                ],
                posed_by="tool",
            )
        )
        return GateReview(
            context=gate_context(review, path), refusal=refusal(review), review_id=review_id
        )
```

`project_id` is the first element of the `running_workflow` tuple, currently
discarded as `_`. Bind it.

`research_team/infrastructure/agent/deep_agent.py` — in `_decide`, the `gate` is
obtained before the two refusal branches that construct a `RecordToolDecision`.
Pass `review_id=gate.review_id if gate is not None else None` into **every**
`RecordToolDecision` constructed on this path: the harness refusal, the
`ApprovalRefused` branch, and both branches of `_apply`. `_apply` does not
currently receive the gate — thread the `review_id` to it as a parameter rather
than re-running the reviewer, which would emit a second review event.

The two `RecordToolDecision` calls that happen *before* `_review_gate` runs (the
`deny` / no-approvals-port branch at the top) get no `review_id` and should not:
no review was run, so there is nothing to name.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/application/test_stage_runner.py tests/integration/test_advance_stage_gate.py -v`
Expected: PASS.

- [ ] **Step 7: Run the course test and the deep-agent tests**

Run: `uv run pytest tests/application/test_course.py tests/infrastructure/test_deep_agent.py -v`
Expected: PASS, including the "viewing a course records no telemetry" test.
(Find the real filenames; adjust.)

- [ ] **Step 8: Both ruff gates, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/session_service.py research_team/application/stage_runner.py \
        research_team/application/ports.py research_team/composition.py \
        research_team/infrastructure/agent/deep_agent.py \
        tests/application/test_stage_runner.py tests/application/test_course.py \
        tests/integration/test_advance_stage_gate.py
git commit
```

Message: why emission is at the two gates rather than in `review_stage`, and
why the deny and refusal branches emit too.

---

### Task 4: The projection and the read model

**Files:**
- Create: `research_team/infrastructure/persistence/check_telemetry.py`
- Test: `tests/infrastructure/test_check_telemetry.py`

**Interfaces:**
- Consumes: `StageChecksEvaluated`, `ToolCallDecided` (Task 1). Task 1 must be committed; Tasks 2 and 3 need not be.
- Produces:
  - `CheckOutcomeRow` (ReadModel, `__table_name__ = "check_outcomes"`), with `row_id(review_id: UUID, check: str) -> UUID`
  - `CheckTelemetryProjection(rows, checkpoint_repo=None, dlq_repo=None, tracer=None)`
  - `CheckTelemetryStore.open(db_path, checkpoint_repo=None, dlq_repo=None, tracer=None)`, `.truncate()`, `.close()`, `.projection`
  - `CheckTelemetryRunner(store: SQLiteEventStore, db_path: str, bus: InMemoryEventBus, tracer=None)` with `start`, `stop`, `rebuild`, `failures`, `caught_up`, `projection_name`, and `async def outcomes(project_id: UUID) -> list[CheckOutcomeRow]`

**Read `research_team/infrastructure/persistence/read_models.py` first.**
`CorpusProjection:632`, `CorpusStore:707` and `CorpusRunner:815` are the template
and this task is largely a transposition of them. Two deliberate divergences are
called out below; everything else should match.

- [ ] **Step 1: Write the failing projection tests**

Create `tests/infrastructure/test_check_telemetry.py`. Follow
`tests/infrastructure/test_corpus_read_model.py`'s conventions: drive the real
aggregate to produce events rather than hand-building them where practical, and
use `InMemoryReadModelRepository` for the projection tests where a database is
not the point.

```python
async def test_a_review_writes_one_row_per_bound_check() -> None:
    """Nine bound checks, nine rows, decision columns empty until it is made."""


async def test_a_check_that_passed_is_stored_with_no_findings() -> None:
    """`findings == 0` and `status == "ran"` -- the denominator, in a row."""


async def test_an_unimplemented_binding_is_stored_as_unimplemented() -> None:
    """`status == "unimplemented"`, so `findings == 0` cannot be misread.

    Fails if the projection stores unimplemented bindings with status "ran",
    which would make every unimplemented check look like a check that passed.
    """


async def test_a_decision_fills_every_row_of_its_review() -> None:
    """The fold: a decision arriving later completes records written earlier.

    This is the whole feature. A review of nine checks followed by one approval
    leaves nine rows all carrying that approval, which is what makes "how often
    was this check overridden" a query rather than a join across two streams.
    """


async def test_a_decision_naming_no_review_is_ignored() -> None:
    """Not a poison event.

    A `ToolCallDecided` with `review_id=None` is every ordinary gated tool
    call. One with a `review_id` matching no row is a decision whose review a
    truncated rebuild has not replayed yet. Neither may raise -- a projection
    that dies on either stops updating every other row too.
    """


async def test_replaying_a_review_twice_leaves_one_row_per_check() -> None:
    """Idempotent under replay from a stale checkpoint.

    Load-then-mutate-then-save, not blind insert. Fails with a uniqueness error
    or a doubled count if someone inserts.
    """


async def test_a_decision_replayed_after_its_review_is_rewritten_is_still_applied() -> None:
    """Order within a rebuild is stream order, so the review always precedes.

    Pinned because the opposite ordering is what a naive test fixture produces,
    and a projection that only worked in fixture order would pass the suite and
    fail on a real rebuild.
    """
```

Plus the database-level test the repository's rules require:

```python
async def test_a_database_written_before_check_outcomes_existed_gains_the_table(tmp_path) -> None:
    """A read-model change verified only against a fresh database is unverified.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that is already there
    -- and does the right thing when it is not. This opens a database that
    predates the table, applies the schema, and writes a row.
    """
    db_path = str(tmp_path / "old.db")
    # Create a database with some other table in it and close it, then:
    store = await CheckTelemetryStore.open(db_path)
    # ... write and read back a row, then close.
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/infrastructure/test_check_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: research_team.infrastructure.persistence.check_telemetry`.

- [ ] **Step 3: Write the row and the projection**

Create `research_team/infrastructure/persistence/check_telemetry.py`. Module
docstring must say what the table is for and why it is one table rather than
two: a review's rows and the decision that completes them are read together on
every query, and a projection that handled only one of the two event types
would never advance its checkpoint past the other.

```python
CHECK_TELEMETRY_NAMESPACE = UUID("...")  # generate a fresh uuid4 and hardcode it


class CheckOutcomeRow(ReadModel):
    __table_name__ = "check_outcomes"

    review_id: UUID
    project_id: UUID
    session_id: UUID
    stage: str
    preset: str
    preset_version: str
    check: str
    severity: str
    findings: int
    status: str
    posed_by: str
    evaluated_at: datetime
    decision: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    @staticmethod
    def row_id(review_id: UUID, check: str) -> UUID:
        return uuid5(CHECK_TELEMETRY_NAMESPACE, f"{review_id}:{check}")
```

```python
class CheckTelemetryProjection(DeclarativeProjection):
    def __init__(self, rows, checkpoint_repo=None, dlq_repo=None, tracer=None) -> None:
        self._rows = rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(StageChecksEvaluated)
    async def _on_evaluated(self, event: StageChecksEvaluated) -> None:
        for entry in event.evaluated:
            await self._upsert(event, entry["check"], entry["severity"], entry["findings"], "ran")
        for entry in event.unimplemented:
            await self._upsert(event, entry["check"], entry["severity"], 0, "unimplemented")

    @handles(ToolCallDecided)
    async def _on_decided(self, event: ToolCallDecided) -> None:
        if event.review_id is None:
            return
        # Not a poison event when it matches nothing: it is a decision whose
        # review a truncated rebuild has not replayed yet, or one recorded
        # before this projection existed. Raising would stop every other row
        # updating too.
        found = await self._rows.find(
            Query(filters=[Filter(field="review_id", operator="eq", value=str(event.review_id))])
        )
        for row in found:
            row.decision = event.decision
            row.decided_by = event.decided_by
            row.decided_at = event.occurred_at
            await self._rows.save(row)
```

`_upsert` loads by `row_id`, creates when absent and mutates when present,
following `CorpusProjection._on_stored:679-685`. Blind insert is wrong: a replay
from a stale checkpoint must not double rows.

`LOCAL_RETRY_POLICY`, `Query` and `Filter` are importable from
`read_models.py` / `eventsource` — check how `read_models.py` imports them and
match. If `LOCAL_RETRY_POLICY` lives in `read_models.py`, import it from there
rather than redefining it; `topics.py` takes it as a constructor argument for
that reason, and either spelling is acceptable so long as there is one policy.

- [ ] **Step 4: Write the store**

`CheckTelemetryStore`, following `CorpusStore:707`. Use **`apply_schema`**, not
raw `executescript` — `read_models.py:729` still uses the raw form and
`topics.py:430-445` records that `apply_schema` is the required path. Add hand-
made indexes after the schema, because the generated one covers only
`deleted_at`:

```python
        for column in ("project_id", "check", "review_id"):
            await connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_check_outcomes_{column} "
                f"ON check_outcomes({column})"
            )
        await connection.commit()
```

`check` is a SQL keyword in some dialects; quote the column name in the index
DDL if SQLite complains, and if it does, note it in a comment.

Include `truncate()` (hard `DELETE`, matching `CorpusStore`) and `close()`.

- [ ] **Step 5: Write the runner**

`CheckTelemetryRunner`, following `CorpusRunner:815` for `start`, `stop`,
`rebuild`, `failures` and `projection_name`.

**One deliberate divergence, and it matters:** `caught_up` must follow
`SessionSummaryRunner.caught_up:500-543`, not `CorpusRunner`'s. This projection
subscribes to one aggregate type (`CodingSession`) in a store holding many, so
comparing `last_processed_position` against the store's *global* position never
converges — the projection will never process the corpus and topic events that
advance it. Read `SessionSummaryRunner.caught_up` and copy its
`FeedReadOptions(aggregate_type=...)` form. Say in a comment why, naming the
symptom (a `TimeoutError` from `caught_up` on a store with any non-session
events in it) so nobody simplifies it back.

Add one read method:

```python
    async def outcomes(self, project_id: UUID) -> list[CheckOutcomeRow]:
        if self._telemetry is None:
            raise RuntimeError("the check telemetry projection has not been started")
        ...
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/infrastructure/test_check_telemetry.py -v`
Expected: PASS.

- [ ] **Step 7: Run the neighbouring read-model tests**

Run: `uv run pytest tests/infrastructure/test_read_model.py tests/infrastructure/test_corpus_read_model.py tests/infrastructure/test_topic_read_model.py -v`
Expected: PASS. Nothing here should have touched them; this is the check that
nothing did.

- [ ] **Step 8: Both ruff gates, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/infrastructure/persistence/check_telemetry.py \
        tests/infrastructure/test_check_telemetry.py
git commit
```

Message: the fold (a decision completing rows written earlier) as the point of
the projection, why one table, why a mismatched `review_id` is ignored rather
than raised, and why `caught_up` cannot use the global position.

---

### Task 5: The read surface

**Files:**
- Create: `research_team/application/check_telemetry_read.py`
- Create: `research_team/infrastructure/persistence/check_telemetry_reader.py`
- Modify: `research_team/composition.py` (field on `Application`, construct, start, stop, caught-up delegator, reader factory)
- Modify: `research_team/interfaces/cli/repl.py` (`/checks` command, help text, dispatch, `run()` signature)
- Modify: `research_team/interfaces/cli/formatters.py` (rendering)
- Modify: `research_team/main.py` (pass the reader into `run`)
- Modify: `research_team/interfaces/web/web.py` — **only if** `tests/interfaces/test_web_entrypoint.py` fails; see Step 7
- Test: `tests/application/test_check_telemetry_read.py`, `tests/interfaces/test_repl.py`

**Interfaces:**
- Consumes: `CheckTelemetryRunner`, `CheckOutcomeRow` (Task 4). Task 4 must be committed.
- Produces:
  - `CheckStat` — frozen dataclass, fields exactly as in the spec
  - `CheckTelemetryReadPort` — Protocol with `async def stats(self) -> list[CheckStat]`
  - `ProjectCheckTelemetryReader(runner, project_id)` implementing it
  - `CheckTelemetryReadError`

`application/check_telemetry_read.py` must import **no** infrastructure and no
`aiosqlite`/`sqlalchemy` — `tests/test_architecture.py` enforces the first and
the house style enforces the second. It is a Protocol, a dataclass, an
exception, and the pure aggregation function below.

- [ ] **Step 1: Write the failing aggregation tests**

The aggregation is a pure function over rows and is where every honesty
constraint lives, so test it directly rather than through a database. Create
`tests/application/test_check_telemetry_read.py`:

```python
def test_fire_rate_counts_the_runs_a_check_passed() -> None:
    """Three runs, one finding: fired 1, evaluated 3. Not fired 1 of 1."""


def test_an_unimplemented_binding_is_not_a_run() -> None:
    """It appears in `unimplemented` and in neither `evaluated` nor `fired`.

    Counting it as a run would report a check with a 0% fire rate that has
    never executed a line.
    """


def test_a_policy_approval_is_not_an_override() -> None:
    """`decided_by == "policy"` means nobody was asked.

    Counted in `auto_approved` and excluded from `overridden`. Reporting it as
    an override would describe a system that ignores its checks, when what
    happened is that `advance_stage` was set to `auto`.
    """


def test_the_tool_path_contributes_no_duration() -> None:
    """`posed_by == "tool"` gives null, never zero.

    Both events commit at `_save_turn` there, so their timestamps are
    milliseconds apart and measure serialization rather than deliberation. Zero
    would look like an instant approval; the truth is an absent measurement.
    Fails if someone computes the delta unconditionally -- which reads as
    correct and produces a median near zero for any tool-heavy project.
    """
    rows = [_row(posed_by="tool", evaluated_at=T, decided_at=T + timedelta(milliseconds=3))]
    assert _stats(rows)[0].median_seconds_to_decision is None


def test_a_median_is_taken_over_the_runner_rows_that_remain() -> None:
    """A mix of paths reports the runner ones and drops the rest."""


def test_an_undecided_review_is_counted_but_not_timed() -> None:
    """A gate posed and never answered -- the process died, or it is open now.

    `decided` excludes it; `evaluated` includes it. The check ran.
    """


def test_a_standing_gate_is_marked_as_one() -> None:
    """`ubd.uncoverage` and `addie.expert_gap_flag` fire on every run by design.

    Registered with `run=None`, they emit a standing finding and can never
    pass, so a 100% fire rate is their specification. Reported in a column of
    their own so they are not read beside a check that chose to fire.

    Recognised from the registry -- `human_gate` or `critic_gate` non-null --
    and not from a list here, so a third one added later needs no edit.
    """
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/application/test_check_telemetry_read.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the port, the DTO and the aggregation**

`research_team/application/check_telemetry_read.py`:

```python
@dataclass(frozen=True)
class CheckStat:
    check: str
    evaluated: int
    fired: int
    findings: int
    unimplemented: int
    decided: int
    overridden: int
    refused: int
    auto_approved: int
    standing_gate: bool
    median_seconds_to_decision: float | None
```

Plus a module-level pure function the adapter calls:

```python
def summarise(outcomes: Iterable[CheckOutcome]) -> list[CheckStat]:
    """Fold raw outcomes into one statistic per check, ordered by fire rate.

    Ordered by fire rate descending because the check that always fires is the
    one this whole feature exists to surface, and a table sorted by name buries
    it among twenty-one others.
    """
```

`CheckOutcome` is a frozen dataclass in this module mirroring the row's fields
— the port must not name a `ReadModel`. The adapter maps rows to it.

Each honesty constraint gets its guard here, each with the comment its test
docstring states in shorter form. In particular, the duration:

```python
        # A tool-path review and its decision both reach the store at
        # `_save_turn`, so their timestamps differ by however long serialization
        # took. Excluded rather than counted as fast: zero would be a number
        # that looks like an instant approval and is an absent measurement.
        durations = [
            (row.decided_at - row.evaluated_at).total_seconds()
            for row in rows
            if row.posed_by == "runner" and row.decided_at is not None
        ]
```

`standing_gate` is read from `checks.REGISTRY` — `spec.human_gate is not None or
spec.critic_gate is not None` — with a comment saying why it is derived rather
than listed.

- [ ] **Step 4: Run the aggregation tests**

Run: `uv run pytest tests/application/test_check_telemetry_read.py -v`
Expected: PASS.

- [ ] **Step 5: Write the adapter**

`research_team/infrastructure/persistence/check_telemetry_reader.py`, following
`corpus_reader.py:25-39` exactly — project bound at construction, never passed
as an argument, and `RuntimeError` from the unstarted runner translated into
`CheckTelemetryReadError`.

- [ ] **Step 6: Wire composition**

In `research_team/composition.py`, following what `corpus` and `topics` do at
`:570-577`, `:157-168`, `:325`, `:384`, `:347-355` and `:1131-1141`:

- construct `CheckTelemetryRunner` beside the others,
- add a field to `Application` with a docstring saying why it is a field,
- start it in `start()`, stop it in `close()`,
- add a `check_telemetry_caught_up()` delegator,
- add a `check_telemetry_readers: Callable[[UUID], CheckTelemetryReadPort]`
  factory, built the way `topic_reader` is.

- [ ] **Step 7: Wire the REPL, and check the entrypoint guard**

`repl.py`: add `/checks` to the help text under "Event log", add it to
`_WITHOUT_A_SESSION` only if it works without one (it does not — it needs a
project — so leave it out), add the dispatch branch beside `/health:538`, and
add a parameter to `run()`. `main.py` passes it.

Rendering goes in `formatters.py` beside `format_summary_health`, as a plain
aligned table. Columns: check, ran, fired, fire %, overridden, refused, auto,
median s. Standing gates get a marker on the name and a footnote line saying
what it means; do not silently exclude them.

Then run `uv run pytest tests/interfaces/test_web_entrypoint.py -v`. That test
reads `inspect.signature(create_app)` and fails when a dependency is added and
not wired. This task adds no `create_app` parameter — there is no HTTP surface,
deliberately — so it should pass untouched. **If it fails, do not add an HTTP
route to satisfy it**; report it instead, because that would mean the guard is
detecting something this plan did not anticipate.

- [ ] **Step 8: Run the interface tests**

Run: `uv run pytest tests/interfaces/test_repl.py tests/interfaces/test_web_entrypoint.py -v`
Expected: PASS.

- [ ] **Step 9: Both ruff gates, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/check_telemetry_read.py \
        research_team/infrastructure/persistence/check_telemetry_reader.py \
        research_team/composition.py research_team/main.py \
        research_team/interfaces/cli/repl.py research_team/interfaces/cli/formatters.py \
        tests/application/test_check_telemetry_read.py tests/interfaces/test_repl.py
git commit
```

Message: why the honesty constraints are guards in the aggregation rather than
notes in a docstring, and why there is no HTTP route.

---

### Task 6: The record

**Files:**
- Modify: `docs/direction.md` (§4, "Closing the loop on checks")
- Modify: `BACKLOG.md` (B22 and B38 gain a note; a new entry for the browser surface)
- Modify: `README.md` — only if it lists REPL commands; check

**Interfaces:** consumes everything; produces nothing code depends on.

- [ ] **Step 1: Rewrite direction.md §4**

It currently argues for building this. Rewrite it as what was built and what was
learned, keeping the generalizable part — that is what the "Defects and
unfinished decisions" section does for its closed items and is the house style.

The lesson worth keeping is the denominator: **a record modelled on the report
you already have will measure the thing that report already shows.** The
findings file lists findings, so an event modelled on it counts numerators
forever and never produces a rate. Recording every bound check — including the
ones that passed silently — is what makes "does this check ever fire?" and "does
this check ever run?" different questions.

Say plainly what is measured and what is not: no duration on the tool path, and
policy approvals reported beside the override rate rather than inside it.

- [ ] **Step 2: Note the two backlog entries this now answers**

B22 and B38 each get one sentence saying the numbers exist now and where to
read them (`/checks`), and that acting on them is still the open work. Do not
close either — nothing was fixed.

- [ ] **Step 3: Add the backlog entry for the deferred surface**

A new entry recording that there is no HTTP route and no browser view, with the
spec's reasoning and its named trigger: someone wanting these numbers who is not
editing `checks.py`. A deferral without a trigger is a rationalisation.

- [ ] **Step 4: Both ruff gates, then commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add docs/direction.md BACKLOG.md
git commit
```

---

## Self-review

**Spec coverage.** Session-stream choice → Task 1 and 3. `StageChecksEvaluated`
shape → Task 1. `review_id` over `correlation_id` → Task 1. `StageReview.
evaluated` denominator → Task 2. Both emission paths, including deny/refuse →
Task 3. `RecordStageReview` command → Task 1, service method → Task 3.
Projection, one table, unimplemented rows, ignored mismatches, `caught_up`
divergence → Task 4. Port, adapter, `CheckStat`, REPL, no HTTP → Task 5. All
four honesty constraints → Task 5 Step 1 (three of them) and Task 3 Step 1 (the
`course_progress` one, which has to be tested where the call site is). Old-DB
verification → Task 4 Step 1. Schema evolution → Task 1 Step 6. Docs → Task 6.

**Dependencies.** Task 1 and Task 2 are independent and may run in parallel.
Task 3 needs both. Task 4 needs only Task 1 and may run in parallel with Task 3.
Task 5 needs Task 4. Task 6 is last.

**Two things a worker will hit that this plan cannot resolve in advance**, both
flagged in place rather than guessed at: whether `StageWorkflow` exposes a
`project_id` (Task 3 Step 4), and whether `check` needs quoting as a column name
in the index DDL (Task 4 Step 4). Both have a stated fallback.
</content>

---

## Corrections found in execution

Appended rather than repaired in place, so the record shows what the plan
actually said when it was handed over. Each entry is a place a worker was right
and the plan was wrong.

### The test sketches name helpers that do not exist

The single recurring defect, hit by Tasks 1 and 2 independently. Every task's
Step 1 sketches test code, and those sketches invent helper names —
`_preset_with_checks`, `_files_that_satisfy_orphan_only`,
`_files_that_make_coverage_raise` — that read as if they were real functions in
the file. They are not, and nothing close to them exists.

The real helpers in `tests/application/test_stage_exit.py` are
`specify(stage_id, *checks)`, `preset_of(*stages)`, `artifact_file(**frontmatter)`,
`file(content)` and `break_check(monkeypatch, name)`. The plan flagged the `...`
bodies as the worker's to fill but did not flag the *names* as guesses, which is
the half that misleads: a placeholder announces itself and an invented identifier
does not.

**The general form: a plan that sketches test code is making claims about the
test file's API, and those claims are as checkable as any other.** Either verify
them or mark them as guesses. This plan did neither.

### Two assertions in Task 1's sketch could not fail

```python
assert event.aggregate_id == session_id or event.aggregate_id is not None
assert evolve(state, event) is state or evolve(state, event) == state
```

The first also references a `session_id` the sketch never binds. Both were
written as belt-and-braces and are the opposite: an `or` between a strict claim
and a weak one asserts only the weak one. The real claims are
`event.aggregate_id == state.session_id` and `evolve(state, event) == state`,
and Task 1 substituted them.

Worth noticing that these would have passed. A test that cannot fail is not
caught by running it, which is why "prove it red first" is a repository rule and
why it caught this.

### Task 1's tests belong in `test_decider.py`

The plan says `tests/domain/test_session.py`. That file's docstring reserves
itself for tests needing an aggregate or a store and sends everything else next
door. All three new tests are pure `decide` calls. Task 1 followed the file.

The plan also sketched `decide(..., initial_state())`, which produces an event
with `aggregate_id=None`; `test_decider.py` has a `started()` helper that every
neighbouring supervision test uses.

### `EvaluatedCheck.severity` and `Check.severity` are different types

`EvaluatedCheck.severity` is `FindingSeverity` (five values) and must be, since
it holds an `invariant` resolved from a spec's `fixed_severity`.
`Check.severity` is `Severity` (two values). The narrowing direction is safe, so
the `binding.severity` fallback type-checks — but the plan used both in adjacent
code without noting they differ.

### A convention the plan contradicted

The plan's unimplemented-binding test used `shared.no_such_check`. The existing
test for that behaviour uses `addie.no_such_check` and carries a comment
explaining the choice. Task 2 followed the existing spelling. One repository, one
name for the same fictional check.
