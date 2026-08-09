# Working in this repository

What the code cannot tell you. Everything here was learned by getting it
wrong; each entry says what the mistake looked like, because the shape of the
failure is the part that makes it recognisable next time.

`README.md` is for people using this project. `BACKLOG.md` is for work
deliberately deferred, with enough detail to pick up. This file is for the
rules that hold across all of it.

## Verification

**There are four gates, and passing three is not passing.**

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

They are separate CI jobs, and the two ruff commands run over the *whole
repository* rather than the files you touched. The failure mode is specific
and has happened more than once: a change is verified with `npm run verify`
and `pytest`, both pass, and CI fails on an unsorted import in a Python test.
`npm run verify` covers no Python, and `pytest` covers no formatting.

`npm run verify` chains format:check, lint, typecheck, test:coverage, build
and a bundle-size budget. Run it rather than the individual commands -- the
prettier check and the size budget are only in the chain, and they are the two
that fail in CI.

**Do not run two `vitest` processes at once.** Concurrent runs fail
spuriously, usually with a coverage temp-file error that names nothing about
the real cause. If a frontend test fails, re-run it alone before investigating
it.

**A failure under load is not evidence until it reproduces alone.** Several
tests here are timing-sensitive, and a machine running another suite (or
another project's containers) produces failures that are absent on a quiet
one. Re-run the failing test in isolation first. Then re-run the *whole
suite*, because some failures only appear in company. Two consecutive
identical results is the bar for "this is real"; one run is a sample.

**But do not file everything under flakiness.** `BACKLOG.md` B4 records a test
that was called flaky for months and was actually broken -- it established its
precondition with a `sleep` and failed against correct code. The tell was
direction: it failed in a way load could not explain. If the failure does not
fit the story you are telling about it, the story is wrong.

## Read models

**A read-model change verified only against a fresh database is unverified.**

Adding a field to a `ReadModel` does not add a column to a database that
already exists. `CREATE TABLE IF NOT EXISTS` does nothing to a table that is
already there, so the column is missing, every query against it fails, and the
endpoint answers 500 -- while every test passes, because tests build their
database from nothing.

`apply_schema` in `infrastructure/persistence/read_models.py` now reconciles
added columns, and
`test_a_database_written_before_a_field_existed_gains_its_column` fails if
anyone removes it. Both exist because this shipped once.

The general rule outlives that fix: **when you change a projection or a read
model, run it against a database that predates the change.** A copy of a real
one is best. "It works on my fresh database" is the sound of this bug.

## Events

Events already written are not rewritten, so a change to an event's shape has
to be readable against payloads an older build stored. `domain/events.py`
opens with the two supported cases and
`tests/infrastructure/test_schema_evolution.py` is what enforces them --
it writes old-shaped payloads straight into the events table and reads them
back.

Breaking that on purpose is allowed while the project is pre-release, and
`SessionStarted.project_id` is the one place it has been done. When you do it,
say so in the field's docstring, say what no longer loads, and update the
schema-evolution test to assert the *refusal* rather than deleting the case.
A deliberate break that is written down is a decision; a silent one is a bug
somebody meets years later.

## Comments and commit messages

The standard here is higher than most repositories and is worth matching.

Comments explain **why**, not what. They state costs and trade-offs plainly
rather than only benefits, they name what a test would fail on, and they say
when something was measured rather than reasoned. A comment that restates the
code is worse than no comment, because it has to be maintained.

Commit messages carry the reasoning that does not fit in a comment: what was
considered and rejected, what the change costs, what is deliberately left
undone. `git log` is a design record here, so write for someone reading it in
a year with no memory of today.

If a test would pass with the change reverted, say so in its docstring rather
than leaving it as reassurance. Proving a test red before trusting it green is
the convention.

## Parallel work

**Work in a worktree when more than one thing is in flight.** Several changes
were nearly lost by one checkout being switched while another piece of work
was live in it -- uncommitted edits carry across a branch switch and end up
sitting on the wrong base, where they look modified and are not what they
seem.

If HEAD is somewhere you did not put it, or files you did not touch show as
modified: **stop and say so** rather than reconciling it. The reconciliation
is where the work gets lost.

## Dependencies

`eventsource-py` and `redstring` are both pre-1.0 with a stated no-shim
policy, so a *minor* is where breaking renames land -- 0.12.0 carried four.
Both are capped below the next minor, and the reasoning is written above the
pins in `pyproject.toml`.

They move together: `redstring` depends on `eventsource-py` within the same
window, so bumping one alone is unresolvable rather than merely unwise. Bump
the `tracing` extra in the same commit as the core dependency -- it pins
`eventsource-py` separately, and a default install resolving to a different
minor than an `--extra tracing` install is a difference nobody sees until a
tracing run behaves unlike every other run.
