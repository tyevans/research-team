# Task 1: `SearchAttempts` is per-turn in truth

Committed as `5c0aa55` on `worktree-defects-and-decisions`.

**The stop condition was not hit.** langgraph does not install a fresh context
per tool call in a way that defeats this design; the concurrency test passes
with contextvars, so the fallback (keying counters off a run identifier in
middleware state) was not needed and was not written.

## What changed

`research_team/infrastructure/agent/search.py`

- New `_Counter` dataclass (a single `empty: int` field) — one turn's streak.
- `SearchAttempts.__init__` no longer holds `self._empty`. It holds a
  per-instance `ContextVar[_Counter | None]` and a `self._unwired` fallback
  counter.
- New `SearchAttempts.begin_turn()` — installs a fresh `_Counter` into the var.
  This is the method the middleware uses, so nothing pokes at attributes.
- `record_empty()`, `reset()`, `exhausted()` keep their signatures and meaning
  exactly; they now read `self._current()` instead of `self._empty`.
- `_current()` returns the installed counter, or `self._unwired` when no
  middleware has run.
- The paragraph beginning "This instance is process-wide, not per-turn" is
  deleted. Two shorter paragraphs replace it: one saying the instance is
  process-wide but the count is not and naming the test that enforces it, and
  one recording that the var must hold a **mutable object and never a bare
  `int`**, with the child-task-copies-context reasoning.
- The trailing "See BACKLOG.md" went with that paragraph.

`research_team/infrastructure/agent/search_middleware.py`

- `before_agent` calls `begin_turn()` rather than `reset()`, with a docstring
  saying why the distinction matters: `reset()` clears whatever counter the
  current context can see, which under concurrency is another live turn's.
- Module docstring updated — installing the counter here is also what scopes it
  to the turn at all.

`BACKLOG.md`

- B41 deleted entirely (CLAUDE.md: closed entries are deleted, not marked).
  Its reasoning now lives in the `SearchAttempts` docstring.

`tests/infrastructure/test_search.py` — four new tests, no existing test edited.

## One deviation from the plan, and why

The design documents both say the counter lives in "the var's default" for the
unwired case. Ruff rejects that:

```
B039 Do not use mutable data structures for `ContextVar` defaults
   --> research_team/infrastructure/agent/search.py:99:54
```

It is right in general — a default is evaluated once and shared across every
context, which is precisely the intent here and a bug nearly everywhere else.
The semantics the plan asked for are preserved exactly by making the fallback
an instance field consulted by `_current()` when the var is unset. Behaviour is
identical: an unwired tool is unbounded-per-process, not raising. The reason is
in a comment on the field so nobody re-introduces the default.

### Disagreement with the directed `# noqa: B039`

The team lead directed `# noqa: B039` with the reasoning in a comment, rather
than a code change, and asked for disagreement in the report rather than a
quiet switch. I had already committed the field-based fallback before that
message arrived, and on inspection I think it should stand. **This is the
lead's call, not mine — the swap is two lines in either direction and I will
make it on request.**

The objection given was that the alternative "installs a `_Counter()` on first
use", and that a lazy `.set()` inside a child task is invisible to the parent
and siblings. That is entirely correct, and it is not what is committed.
**There is no lazy `.set()`.** `.set()` is called in exactly one place,
`begin_turn()`. The unwired path never sets the var at all; `_current()` reads
`self._unwired`, one object held on the instance, which is the *same* single
shared object a mutable default would have handed every context. The two
resolutions are behaviourally identical, and neither has the hazard described.

Confirmed rather than argued:

```
unwired, counted across 3 child tasks -> exhausted: True
wired, child-task mutations visible to the turn: True
```

Three `record_empty()` calls made from three separate child tasks, with no
middleware, accumulate to the bound — the unwired path does not lose counts
across tasks. The second line is the load-bearing wired case.

Given identical behaviour, the field is preferable to the suppression on two
counts: a `noqa` is a standing claim that the rule does not apply, which a
future reader has to re-derive to trust, whereas the field cannot be
misconfigured; and the rule's premise *does* partly hold — the danger B039
names is a mutable object shared across contexts, and the fallback is exactly
that. It is safe here only because the unwired path is a documented
single-process-counter path. That is worth expressing as a named field called
`_unwired` rather than as an exception to a lint rule.

## Red, then green

Written first, run against the shared-instance code. Actual output:

```
        a_result, b_result = await asyncio.gather(turn_a(), turn_b())

        # A tried three times and nothing was there, so A is told to stop.
        assert "record_gap" in a_result
        # B has tried nothing. Its first search must reach the instance.
>       assert b_result == "No results."
E       AssertionError: assert 'web_search h...rching again.' == 'No results.'
E
E         - No results.
E         + web_search has returned no results 3 times in a row this turn. Searching again is unlikely to find something the last 3 attempts did not. If you looked and did not find it, call `record_gap` to say so rather than searching again.

tests/infrastructure/test_search.py:429: AssertionError
=========================== short test summary info ============================
FAILED tests/infrastructure/test_search.py::test_two_concurrent_turns_do_not_bound_each_other
================== 1 failed, 3 passed, 25 deselected in 0.51s ==================
```

That is the right failure: turn B, which had searched nothing, was handed turn
A's exhausted-notice. Not a fixture error — A's own assertion passed first, and
the two turns are pinned into a deterministic interleaving by three
`asyncio.Event`s (both turns start, A exhausts, then B searches), so this is
not a race that happened to land.

The other three new tests passed against the old code and are stated as such
where relevant: `test_exhausted_turns_true_exactly_at_the_bound` and
`test_a_tool_built_without_middleware_still_counts` are guards on behaviour the
change had to preserve, not evidence for it.
`test_a_turn_starts_at_zero_however_the_last_one_ended` fails if the middleware
hook is reverted to a no-op.

Green after the change:

```
tests/infrastructure/test_search.py .............................        [ 65%]
tests/infrastructure/test_stage_middleware.py ...............            [100%]
============================== 44 passed in 0.72s ==============================
```

## Test files run

Only these two, per the constraint. No full suite, no vitest.

- `tests/infrastructure/test_search.py` — 29 passed
- `tests/infrastructure/test_stage_middleware.py` — 15 passed

There is no separate test file for the search middleware; its coverage lives in
`test_search.py` (`test_the_counter_resets_at_the_turn_boundary`, which passes
unchanged). `test_stage_middleware.py` was run because it is the nearest
middleware file, not because it was touched.

## Ruff

Both gates pass over the whole repository, run immediately before the commit:

```
uv run ruff check .        -> All checks passed!
uv run ruff format --check .  -> 211 files already formatted
```

## Things worth flagging

- **The plan's `ContextVar` default is not implementable as written** under
  this repo's ruff configuration. Resolved as above; the plan should say
  "a fallback counter consulted when the var is unset" rather than "the var's
  default".
- **Another agent's in-progress edit to `research_team/application/checks.py`
  broke `tests/conftest.py` mid-run** (`TypeError: BaseModel.__init__() takes 1
  positional argument but 2 were given` from
  `TypeFilter("CriterionDocument")`). It was transient and resolved without
  intervention; I waited on `import research_team.composition` succeeding
  rather than touching their file. Noting it only because it means any pytest
  run in this worktree can fail for reasons unrelated to the task.
- `docs/direction.md` shows as modified in my working tree. It is not mine and
  was not staged.
- The `build_search_tool` docstring still says `attempts` is "optional --
  nothing wires it into the application yet; that is Task 6", which is stale
  (`composition.py:542` wires it). Left alone: out of this task's scope, and it
  is prose in a file Task 2 is about to take.
