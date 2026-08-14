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

**There is a fifth command, and it is not a gate.**

```
cd frontend && npm run test:browser
```

Headless Chromium via vitest's browser mode, over `src/**/*.browser.test.tsx`.
It is deliberately outside `verify` and outside CI, so nothing forces you to
run it -- **run it when you touch a stylesheet, a layout primitive, or
anything whose correctness is a computed style or a measurement.**

The reason it exists: jsdom lays nothing out and applies no stylesheet, so
`scrollHeight` is 0 everywhere, `getComputedStyle` returns only what an inline
style said, and a selector that matches nothing is indistinguishable from one
that matches. Four findings in a row had their real assertion written as a
comment for that reason, and the fifth -- a chosen control drawing in the
unchosen colour, because a `Tooltip` and a `RadioGroup` both wrote
`data-state` to one element -- shipped past a fully green suite and was caught
by eye.

What it is not: a replacement for the jsdom suite (923 tests to its handful),
or a place for anything jsdom can already judge. Roles, focus order, keyboard
routing and rendered text belong in `*.test.tsx`, where they run in a second
rather than a minute.

Two things learned writing the first tests, both of which cost half an hour:
the viewport is set in `vite.config.ts` and a media query reads *that*, not
the width of the wrapper a test renders into; and `vitest.setup.browser.ts` is
a separate file from `vitest.setup.ts` on purpose, because the jsdom setup
pins `offsetWidth`/`offsetHeight` to constants and would blind the one suite
whose job is measuring.

**`border-solid` beside one directional width draws three unwanted sides.**
This build imports no Tailwind preflight, so the browser's own defaults are
what's left where Tailwind sets nothing. `.border-solid` is the shorthand —
`border-style: solid` on all four sides at once. Pair it with a directional
width like `border-t` and no `border-0`, and the three sides that get a
style but no explicit width fall back to the browser's `medium` (~3px)
rather than 0: a rule meant for one edge draws a box. The fix is both halves
together — `border-0` to zero the three sides you don't want, then the
directional width for the one you do. No gate catches it.

**A directional width *alone* is fine, and this entry used to say the
opposite.** It said `border-t` without `border-solid` "draws nothing at all,
because every side's style is still `none`". That is not true of this build,
and it is the half the repository had been acting on — `BACKLOG.md` B55 was
filed entirely on it and is now withdrawn. Tailwind v4 emits the style
longhand *with* the width (`border-b` → `border-bottom-style:
var(--tw-border-style); border-bottom-width: 1px`) and registers
`--tw-border-style` with `initial-value: solid`, so a directional width alone
resolves to solid and draws. `border-style:none` appears zero times in the
built `index.css`. **Verified against the built stylesheet on 2026-08-13, not
reasoned** — and the repository already held the measurement: `Drawer.tsx:162`
writes `border-l border-line` with no `border-solid`, and
`shell-reached-dressing.browser.test.tsx:157-158` asserts that element's
`borderLeftStyle === 'solid'`.

The remaining honesty: this entry said the defect was caught by eye in
Storybook "twice, in both directions", and only one direction is explained by
the current build. The other observation has not been re-taken.
`frontend/src/styles/border-style-default.browser.test.tsx` exists to settle
it and has not been run.

**An unlayered rule in `tokens.css` beats any utility, so a utility meant to
override one is inert — and looks exactly like a utility that worked.** The
global `:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px }`
(`tokens.css`, near the end) is written outside any `@layer`. Tailwind emits its
utilities into `@layer utilities`, and **an unlayered normal declaration beats a
layered one regardless of specificity** — so `focus-visible:outline-offset-[-2px]`
at (0,2,0) still loses to a bare `:focus-visible` at (0,1,0). The class is in the
attribute and the rule is in the bundle; only the computed value disagrees.

This is how the inward focus ring shipped broken. Slice 3a moved three working
stylesheet rules onto a `RING_INWARD` utility constant, reported the geometry as
carried across unchanged, and clipped the document row's ring on every row for a
whole slice; two agents rediscovered it independently a slice later, each by
measuring. Measured in Chromium at 1440×900: with the constant absent and with
the constant present, the ring's reach is **byte-identical**.

The fix is a named class in a stylesheet — `.lay-ring-inward` in `layout.css`,
(0,2,0) against the global's (0,1,0), both unlayered, so the comparison is one
the cascade will actually make. A trailing `!` also works, and was rejected: it
leaves every future inward ring one forgotten character from the same silent
failure, and there is nowhere for the measurement to live.

The general rule outlives the ring: **before overriding anything declared in
`tokens.css` with a utility, check whether the rule is layered.** If it is not,
the utility will not win, and no gate will tell you — jsdom returns only what an
inline style said, so the assertion has to be a browser measurement.

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

It reconciles two ways, and the split is the part to know before editing it.
The `ALTER`s come from the library's `generate_additive_migration`, which is
pure and refuses the whole set up front if any column is required with no
default -- so the table is never left half-widened. But it refuses that
*categorically*, where SQLite only refuses it on a table that has rows, and the
incident above is a required column added to a table that is usually empty. So
an empty table is dropped and recreated instead, and a populated one re-raises;
`/rebuild` is the answer there and a loud error is how anyone finds out.

The general rule outlives that fix: **when you change a projection or a read
model, run it against a database that predates the change.** A copy of a real
one is best. "It works on my fresh database" is the sound of this bug.

**A copy of a real one does not open where you put it.** Copy
`~/.research-team/sessions.db` anywhere else and nothing starts:

```
PositionForeignError: cannot order positions from
'sqlite:/home/you/.research-team/sessions.db' and 'sqlite:/tmp/copy.db'
```

`eventsource` derives a store's id from the database string it was handed --
`f"sqlite:{database}"` -- and every row in `projection_checkpoints` carries
that id inside its position token. A position from one store cannot be ordered
against a position from another, so the subscription fails to transition and
`start()` raises before a single event is replayed. The path is the only thing
that changed, and it is enough.

```
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
```

That copies the database (`VACUUM INTO`, from a read-only connection, so the
`-wal` comes with it and nothing can write to a database you are still using)
and rewrites the store id in each checkpoint to the copy's own path. It prints
the `AGENT_DB=` line to run against it.

**Deleting the checkpoints also gets it up, and quietly defeats the rule.** It
is the obvious fix -- an empty `projection_checkpoints` has no foreign position
to compare -- but a projection with no checkpoint replays the whole log and
rewrites every row, which is `/rebuild` by another name. The half of the bug
that survives `apply_schema` is the half it hides: `apply_schema` widens the
table but leaves the new column empty in the rows already there, and against a
real database the projection resumes near the end of the log and never
backfills them. That is what the endpoint is wrong about. Measured, on
2026-08-13, by emptying `session_summary_rows` in two copies of the real
database and starting each: the copy with its checkpoints cleared came back
with all four rows, the copy with them rebound came back with none. The rebound
one is the honest reproduction.

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
