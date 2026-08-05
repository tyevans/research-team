# Backlog

Deferred work. Every deficiency found and not fixed on the spot lands here,
with enough detail that picking it up does not require rediscovering it.

The `B` numbers are stable handles, not a taxonomy. Closed entries are deleted;
if tracked code cites one by name, say where its reasoning went before deleting.

## Code quality

### B1. `Project`'s class docstring says little that its module does not

`research_team/domain/project.py`. The class docstring is near-verbatim from
`CodingSession`'s — "the imperative shell, holds no rules, delegates all
three" — and the `Project`-specific reasoning it might add is already in the
module docstring above it. Not wrong, just thin: a reader who came for the
difference between the two aggregates does not find it here.

Found in the Task 1 review of the projects/redstring work and deferred as
Minor, because the docstring convention is satisfied and nothing is
misleading.

### B3. No type checking

`mypy` is not configured and has never run against this codebase. The CI gate
added alongside the projects/redstring work covers `ruff check`, `ruff format`
and the test suites, and deliberately stops there.

Deferred on measurement rather than principle: ~40 modules have never been
type-checked, so `mypy --strict` is an open-ended migration whose size is
unknown until it is run, and starting one in the middle of a feature was the
wrong trade. The sibling project (`redstring`) gates on `mypy --strict` and is
the model to copy when this is picked up.

Do not add mypy in permissive mode as a stepping stone. A gate that starts
permissive tends to stay permissive, and it costs the honesty of saying
plainly, as this entry does, that there is no type checking today.

### B4. Two tests flake under machine load

Both surfaced during the projects/redstring work, each failing once and passing
on an isolated re-run, on a machine running several other projects' containers:

- `tests/interfaces/test_web.py::test_stream_reaches_a_real_browser_over_a_real_socket`
  — waits up to 10s on a real socket for an SSE frame.
- A cancel-settle test in `tests/application/test_turn_supervisor.py` with
  `settle_timeout=0.1`.

Both are wall-clock races against a loaded scheduler, not logic faults, and
both are testing something worth testing — a real socket and a real timeout
are the point. The fix is not a longer sleep: it is making the wait
condition-driven, or making the timeout injectable so the test names its own.

Left alone for now because they pass reliably on an unloaded machine and the
CI runner is quieter than the machine they flaked on. If CI proves otherwise,
this moves up.

### B5. `SQLiteSnapshotStore` cannot be closed, and its thread outlives the process

`eventsource.adapters.sqlite.snapshots.SQLiteSnapshotStore` has no `close()`.
`SQLiteEventStore` does. Each opens an `aiosqlite` connection, and aiosqlite
runs one non-daemon worker thread per connection — so a snapshot store that has
been used keeps a thread alive that nothing can release, and a non-daemon thread
blocks interpreter shutdown.

Found the expensive way: a test that opened a second snapshot store over the
same file appeared to hang forever. It was not hanging — the test body
completed in under a second and the process then parked in
`threading._shutdown` waiting on two aiosqlite workers. A `faulthandler` dump is
what distinguished the two, and nothing short of that would have.

**This is not only a test problem.** `build_aggregate_repository` in
`research_team/infrastructure/persistence/event_store.py` constructs a
`SQLiteSnapshotStore(db_path)` that nothing closes, and composition will
construct another for the knowledge adapter. Long-lived processes are fine
because the connection is wanted for the process's life; anything that builds an
application and then expects a clean exit is not.

Two fixes, and the first is upstream: give `SQLiteSnapshotStore` a `close()` (or
make its worker a daemon thread) in `eventsource-py`. Then have
`EventStoreSessionRepository.close()` and `Application.close()` call it. Until
then, tests must reuse one snapshot store instance rather than opening a second.

Also the likely explanation for the pre-existing aiosqlite "Event loop is
closed" teardown warning noted during this work — same family, same cause.

### B6. `undo_merge` always reports `reason=None`

`RedstringKnowledge.undo_merge` builds its `MergeRecord` from
`ConsolidationReport.reason`, and `Consolidator.undo` documents that field as
`None` for an undo — the reason belongs to the merge, not to its reversal. So
the `reason` on an undo's record is always empty, and a caller reading it sees
nothing rather than the reason the original merge was made.

Nothing is wrong today: `unmerge`'s tool output does not print it. It becomes a
papercut the moment something wants to say "this merge, made because X, was
reversed". The fix is either to say so in the docstring and leave it, or to read
the original `EntitiesMerged` off the consolidation stream and carry its reason
through. Deferred rather than guessed at, because which one is right depends on
whether any caller ever wants that string.

### B7. One weak assertion in the knowledge-tools tests

`tests/infrastructure/test_knowledge_tools.py::test_remember_reports_counts_and_confidence`
asserts `"7" in result and "4" in result` — bare digits, which could appear
incidentally inside a UUID or another number in the same output. It should
assert the whole informative phrase instead.

It came from the plan's own test code, and the surrounding assertions (the
domain name, the confidence disambiguation) make a false pass unlikely in
practice — which is why it was not worth a fix round on its own. Worth
correcting the next time that file is touched.

### B8. Two accessors reach through private attributes

- `Application.turns_tools()` in `research_team/composition.py` reads
  `service._executor._tools`, so a test can inspect which tools were registered.
- `_project_repository` in `research_team/interfaces/cli/repl.py` reads
  `service._repository`, to reach the `Project` aggregate repository.

Each is documented inline and each works. The concern is drift: the second one
was written *because* the first established the precedent, which is how an
expedient becomes a convention nobody chose. The cleaner shapes are a public
`tools` property on the executor, and a real port method for project access
rather than reaching past `SessionService`.

Deferred twice because both alternatives widen a public surface that was not
the task's business. **If a third case appears, stop and fix the pattern rather
than adding to it** — at that point it is the codebase's convention whether
anyone decided so or not.

## Waiting on redstring

### B2. Two workarounds to unwind when redstring closes R3 and R4

`research_team/infrastructure/knowledge/rebuild.py` carries two workarounds,
both commented in place, both recorded as R3 and R4 in
`docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`:

- **R3** — `redstring.projections.project` folds the *global* feed with no
  stream or category argument, so rebuilding one project's graph reads every
  session event in the store too. Scoping is by `tenant_filter` on the
  projection instead. Correct, but the scan is O(whole log) per project open,
  and that is the first thing to hurt as a store grows.
- **R4** — `ReplayReport.failed` is a count rather than a raise, so a poison
  event is swallowed and the graph comes up quietly incomplete. Project open
  checks the count by hand and refuses. A strict mode upstream would replace
  that check.

Three further redstring gaps (R1 embedding provider, R2 identifying
unconsolidated entities, R5 an understated eventsource floor) are recorded in
the same spec section. R1 is why there is no vector search and no
`AGENT_VECTOR_STORE`; R2 is why the repair path is keyed by `source_id` here
rather than asking the library what is unconsolidated.
