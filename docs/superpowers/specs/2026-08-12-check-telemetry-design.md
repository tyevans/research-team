# Closing the loop on checks

Recording what the check library found, and what the human did about it, so
that "which of these twenty-two checks earn their place" has a mechanical
answer instead of an argument.

`docs/direction.md` §4 is the case for doing this at all and is not repeated
here. This document is the design.

## The problem, stated precisely

There are twenty-two registered checks. Nothing anywhere records how often any
of them fires, and nothing records what happened next.

The reason is structural rather than an oversight: **a finding is a file.**
`stage_exit.py` renders a `StageReview` into `/course/NN-check-findings.md` and
writes it through the session's virtual filesystem. There is one such file per
stage number and each review of that stage overwrites it. So the only durable
record of what the checks found is a document that describes the most recent
run and nothing before it.

The gate decision *is* on the log, as `ToolCallDecided` — but it carries
`tool_name`, `args`, `decision` and `decided_by`, and none of those names a
stage or a review. The one event that names a stage, `StageAdvanced`, lives on
the `Project` stream, has no session id, and **is only written on approve or
edit** — a rejected gate produces no stage-bearing event anywhere. Rejections
are exactly the signal this feature exists to measure.

So today the two halves of the question live in different places, one of them
is overwritten on every run, and there is no key that joins them.

Two entries in `BACKLOG.md` are stuck behind this and are the concrete reason
it is worth building rather than merely tidy:

- **B38** — four `matrix_density` bindings have no axes and therefore answer
  "no matrix was built for this stage" on every run of every course. That is a
  check with a 100% fire rate and a 100% override rate. Nobody notices because
  the evidence is overwritten before anyone counts it.
- **B22** — `self_review_separation` is documented as an invariant and bound
  like an option, at some stages and not others. Whether its absence costs
  anything is currently unanswerable.

## What this builds, and what it deliberately does not

**It builds the instrument, not the verdict.** The deliverable is fire rate,
override rate and time-to-decision per check, and the machinery that keeps
producing them. Acting on the numbers — rebinding B38's four matrices, deciding
B22 — is separate work needing course fixtures per methodology, and is out of
scope. A round that both measures and acts on its own measurements is a round
whose measurements nobody can check.

Out of scope, explicitly:

- Fixing B38 or B22.
- Any change to what a check *does*, or to `checks.py`'s registry.
- Any change to when a gate is posed, or to the durability analysis B36
  settled. This feature observes the gate; it does not move it.
- A browser surface. See "The read surface" below for why.

## The design

### Why the session stream, and not the project stream

The gate is posed on two paths and they have different reach:

- **The runner path** — `StageRunner._gate_and_advance`
  (`application/stage_runner.py:614`) holds a `StageWorkflow`, so it can write
  to the `Project` stream. It already does, via `AdvanceStage`.
- **The tool path** — `gate_review` in `composition.py:843` holds a
  `CodingSession` and nothing else, and the decision it leads to is settled in
  `DeepAgentTurnExecutor._decide` (`infrastructure/agent/deep_agent.py:490`),
  which holds no project anything.

A design on the `Project` stream can therefore instrument one path and not the
other, and the uninstrumented one is the path a model takes unattended. Both
paths already write to the **session** stream — `gate_review` does
`session.execute(WriteFile(...))` and `_decide` does `RecordToolDecision` — so
that is the one place where a review and the decision that followed it can be
made adjacent on both paths.

The cost of choosing the session stream is that the telemetry is keyed by
session rather than by project, and the project id has to be carried on the
event rather than inferred from the stream. That is a field, and it is cheaper
than an instrument with a hole in it exactly where nobody is watching.

### `StageChecksEvaluated`, a new session event

```python
@register_event
class StageChecksEvaluated(DomainEvent):
    aggregate_type: str = "CodingSession"
    review_id: UUID
    project_id: UUID
    stage: str
    preset: str
    preset_version: str
    evaluated: list[dict[str, Any]]     # {check, severity, findings: int}
    unimplemented: list[str]
    posed_by: str                       # "runner" | "tool"
```

Four things about this shape are load-bearing.

**It records every bound check, not every finding.** A fire rate needs a
denominator, and the denominator is "times this check ran", which includes the
runs where it found nothing. An event carrying only findings can count numerators
forever and never produce a rate. This is the single most important decision in
the design and it is the one that is invisible if you start from the findings
file, which lists only findings.

**It carries no message and no `cites`.** The counts are the fact; the prose is
already in `/course/NN-check-findings.md` and putting it on the log too would
make every review permanent at the size of its worst output. This follows
`corpus.py`'s reason for holding no document text: snapshots fold state, and a
growing list of every message ever emitted goes into each one.

**`unimplemented` is separate from `evaluated`.** A check that is bound but not
registered neither ran nor passed, and folding it into either would make one of
the two rates lie. `review_stage` already distinguishes them.

**`posed_by` exists so that time-to-decision can refuse to answer.** See below.

### `review_id`, and why not `correlation_id`

`DomainEvent` already carries `correlation_id`, and using it would save a field.
Rejected: it is the framework's tracing key, set by whatever is tracing, and a
telemetry join that piggybacks on it silently breaks the first time a tracer is
wired. An explicit `review_id` says what it is for.

`ToolCallDecided` gains `review_id: UUID | None = None`. Additive with a default
that means what its absence meant — a decision that was not about a stage
review, which is every gated tool call that is not `advance_stage`, and every
`advance_stage` decision recorded before this feature existed.

### `StageReview.evaluated`, the denominator

`review_stage` (`application/stage_exit.py:272`) currently returns findings and
unimplemented names. It iterates `stage.checks` and therefore already knows
every binding it ran; it simply does not report them. `StageReview` gains:

```python
@dataclass(frozen=True)
class EvaluatedCheck:
    check: str
    severity: FindingSeverity
    findings: int

# on StageReview
evaluated: tuple[EvaluatedCheck, ...] = ()
```

The severity recorded is the one `run_check` resolved — `spec.fixed_severity or
binding.severity` — because that is the severity the finding would have carried,
and a report of "how often did an invariant fire" that used the binding's
declared severity would be wrong for exactly the two checks where it matters.

A check that raised is recorded as having run and produced its one blocking
finding, which is what the reviewer saw. The message says it crashed; the count
says it fired. That is deliberate: from the gate's point of view a crashed check
is a check that blocked, and a fire rate that excluded crashes would under-report
the cost of a broken check.

### Where the events are emitted

**Runner path.** `_gate_and_advance` already computes `review`, writes the
findings file, and calls `record_tool_decision`. It gains a
`record_stage_review` call immediately after the file write, and passes the
`review_id` through to `record_tool_decision`. Both go through `SessionService`
and append immediately, so the two `occurred_at` values bracket the human's
actual deliberation.

The `auto` branch records the decision with `decided_by="policy"` and no
`ApprovalRequest` at all. It still emits both events — a standing approval is a
real outcome and hiding it would make override rates look better than they are —
but the read surface reports it separately. See "Honesty constraints".

The `deny` branch records a rejection with `decided_by="policy"`. It emits the
review too: a check that fired at a gate nobody was allowed to open still ran.

**Tool path.** `gate_review` in `composition.py` gains a
`session.execute(RecordStageReview(...))` beside its existing `WriteFile`. It
already has everything needed: `running_workflow` returns
`(project_id, state, preset)`.

Carrying the `review_id` to `_decide` is the one piece of new plumbing. The
`GateReview` DTO (`application/ports.py:308`) gains `review_id: UUID | None`,
and `_decide` passes it into every `RecordToolDecision` it constructs on that
path — including the two refusal branches, which are decisions and are the ones
an override rate most needs.

### `RecordStageReview`, the command

A frozen dataclass in `domain/commands.py`, handled in `domain/session.py`'s
`decide` alongside `RecordToolDecision`, producing one `StageChecksEvaluated`.
`evolve` ignores it, exactly as it ignores `ToolCallDecided`: both are audit
records and neither belongs in `SessionState`. `session.py:247` already states
this rule for its existing pair; this joins them rather than inventing a policy.

`SessionService` gains `record_stage_review(...)`, mirroring
`record_tool_decision`, with the same reason for appending immediately: a review
that reached the store only if a later turn succeeded would be missing from
exactly the runs that went wrong.

### The projection and read model

One projection, `CheckTelemetryProjection`, over the `CodingSession` stream,
handling `StageChecksEvaluated` and `ToolCallDecided`. One table.

```python
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
    findings: int              # 0 means it ran and passed
    status: str                # "ran" | "unimplemented"
    posed_by: str
    evaluated_at: datetime
    decision: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
```

Row id is `uuid5(CHECK_TELEMETRY_NAMESPACE, f"{review_id}:{check}")`, following
`CorpusDocumentRow.row_id`. One row per check per review, so a stage bound to
nine checks writes nine rows.

An unimplemented binding also gets a row, with `status="unimplemented"`,
`findings=0` and the severity the *binding* declared — the registry has no spec
to resolve a fixed severity from, which is the whole reason it is unimplemented.
Its `findings=0` must never be read as "ran and passed"; `status` is the field
that separates them, and every query below filters on it.

`StageChecksEvaluated` inserts the rows with the decision columns null.
`ToolCallDecided` with a non-null `review_id` finds every row for that review and
fills them. **This fold — a decision arriving later and completing a record
written earlier — is the whole feature**, and it is the move `direction.md`'s
opening section describes.

Handlers load-then-mutate-then-save rather than blind-insert, so a replay from a
stale checkpoint is idempotent, following `CorpusProjection._on_stored`.

A `ToolCallDecided` whose `review_id` names no rows is ignored rather than
raising. It is not a poison event: it is a decision recorded before the
projection was rebuilt, or a review whose events a truncated rebuild has not
reached yet.

Store and runner follow `CorpusStore` / `CorpusRunner` exactly: `open` with
`apply_schema` per model plus hand-made indexes on `project_id` and on `check`,
`truncate`, `close`, and a runner with `start`, `stop`, `rebuild`, `failures`,
`caught_up`. Because this projection is scoped to one aggregate type in a store
holding many, `caught_up` must follow `SessionSummaryRunner`'s form — reading
remaining work with `FeedReadOptions(aggregate_type=...)` — and not
`CorpusRunner`'s global-position comparison, which would never converge.

### The read surface

A port in `application/`, an adapter in `infrastructure/persistence/`, and a
REPL command. This is the `CorpusReadPort` / `ProjectCorpusReader` pair, which
is the smallest existing template.

```python
@dataclass(frozen=True)
class CheckStat:
    check: str
    evaluated: int          # reviews in which this check ran
    fired: int              # of those, how many produced >= 1 finding
    findings: int           # total findings produced
    unimplemented: int      # reviews where it was bound but not registered
    decided: int            # reviews with a recorded decision
    overridden: int         # fired, and the gate was approved or edited anyway
    refused: int            # fired, and the gate was rejected
    auto_approved: int      # of `overridden`, how many by decided_by="policy"
    median_seconds_to_decision: float | None
```

`/checks` in the REPL renders these as a table, ordered by fire rate descending,
because the check that always fires is the one the feature exists to surface.

**No HTTP route and no browser view, deliberately.** These numbers are a
maintainer's instrument for deciding which checks earn their place — a decision
made once in a while, by the person who can change the check library — and not a
per-project surface a course author needs. A JSON route with no UI behind it is
a route nobody calls, and building the UI is a frontend round that should be
justified by someone actually wanting it. `CorpusRunner` and `TopicRunner`
already set the precedent of a projection whose `rebuild()` has no HTTP surface.

The trigger to revisit: someone asking for these numbers who is not editing
`checks.py`.

## Honesty constraints

Four ways this instrument could lie, and what each costs to prevent. Each is
worth a test rather than a comment.

**Time-to-decision is not measurable on the tool path.** There, the review and
the decision both reach the store at `_save_turn`, so their `occurred_at` values
are commit timestamps a few milliseconds apart and the difference measures
serialization, not deliberation. `posed_by == "tool"` therefore contributes
**null**, not zero, to `median_seconds_to_decision`. Recording zero would be a
number that looks like an instant approval and is actually an absence of
measurement. This is B36's open half showing up as a measurement limit, and it
is the reason `posed_by` is on the event at all.

**A policy approval is not an override.** `decided_by == "policy"` means
`advance_stage` was set to `auto` and no human saw anything. Counting those in
the override rate would report a system that ignores its checks when what
happened is that nobody was asked. They are counted in `auto_approved` and
reported beside the rate, not inside it.

**Two checks always fire by construction.** `ubd.uncoverage` and
`addie.expert_gap_flag` are registered with `run=None` and a gate reason; they
emit a standing finding on every run and can never pass. A 100% fire rate for
those two is the design, not a defect, and the read surface must not present
them in the same column as a check that chose to fire. They are recognisable
from the registry (`human_gate` / `critic_gate` non-null) rather than from a
hardcoded list, so a third one added later is handled without an edit here.

**`course_progress` recomputes findings on read and must not be counted.**
`application/course.py:331` calls `review_stage` on every course view to show
live findings. Nothing is emitted there, because emission is at the gate and not
in `review_stage`. This is why the event is raised by the two gate paths rather
than by the function that computes the review — a design that instrumented
`review_stage` itself would count page refreshes as check runs. Worth a test
that pins it: a course view emits no telemetry.

## Verification

All four gates, because passing three is not passing:

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Beyond the gates, two requirements specific to this change:

**A read-model change verified only against a fresh database is unverified.**
This adds a table, which `CREATE TABLE IF NOT EXISTS` handles, and `apply_schema`
reconciles added columns. Both must be exercised against a database that
predates the change, not only against one built from nothing.

**A new event needs a schema-evolution case.** `ToolCallDecided` gains a field,
so `tests/infrastructure/test_schema_evolution.py` must gain a case writing an
old-shaped `ToolCallDecided` payload — one with no `review_id` — straight into
the events table and reading it back with the field defaulted to `None`.
</content>
</invoke>
