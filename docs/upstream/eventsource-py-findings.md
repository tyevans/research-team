# eventsource-py: findings from a consumer

Written while building a project-scoped knowledge graph in `research-team`,
which puts `eventsource-py` under two consumers at once — this application's
own aggregates and `redstring`'s — sharing one SQLite file.

Everything here was measured against `eventsource-py 0.10.0`, not recalled.
Where a claim is an inference rather than an observation, it says so.

Ordered by how much time each would have saved.

---

## E1. The aiosqlite worker thread is non-daemon, so a forgotten `close()` hangs the process

**Severity: high. This is the one worth fixing.**

`SQLiteEventStore` holds one long-lived `aiosqlite` connection. That connection
runs a worker thread, and the thread is **non-daemon**. Measured:

| | non-main threads at exit |
|---|---|
| store used, `close()` called | none — process exits clean |
| store used, `close()` not called | `Thread-1 (_connection_worker_thread)`, `daemon=False` |

A non-daemon thread that never finishes means the interpreter parks in
`threading._shutdown` forever. So forgetting `close()` is not untidy, it is a
hang — and the hang happens *after* all work has completed successfully.

**What that cost us.** A test appeared to hang indefinitely. Machine load was
2.9 across 16 cores and the process sat at 1.2% CPU, so "slow" was already
ruled out. A `faulthandler` dump showed the test body had finished and the main
thread was in `threading._shutdown`. Deselecting that one test: the rest of the
file ran in 0.82s. Before the dump, the working hypothesis was a SQLite lock
deadlock, which was wrong and cost a detour.

**Suggested fix, cheapest first:**

1. Make the connection worker a daemon thread. A forgotten `close()` then costs
   an untidy exit instead of a hang. This alone converts the worst failure mode
   into a non-event.
2. Register a `weakref.finalize` or `atexit` hook that closes the connection,
   so the common case self-heals.
3. If neither is acceptable, emit a warning at interpreter exit naming the
   database path of any store still open. Even the warning would have collapsed
   our investigation from hours to minutes.

## E2. The failure surfaces as an error from inside asyncio, naming nothing

Related to E1 but worth separating, because it is what a user actually sees.

An unclosed store produces, at shutdown:

```
RuntimeError: Event loop is closed
  File ".../asyncio/base_events.py", line 878, in call_soon_threadsafe
  File ".../aiosqlite/core.py", line 59, in _connection_worker_thread
```

Nothing in that names `SQLiteEventStore`, the database path, or the fact that
something was left open. We had been seeing this warning in our suite for a
while and had written it off as generic teardown noise — it was in fact the
symptom of E1, and treating it as noise is exactly what a reader will do.

Anything that attaches the store's identity to that message would help.

## E3. `SQLiteEventStore` has no async context manager

`close()` exists and works. It is simply easy to forget, and E1 makes
forgetting expensive.

```python
async with SQLiteEventStore(path) as store:
    ...
```

would make the correct thing the easy thing, and would let tests stop reaching
for `try/finally` around every store they open.

**Note:** `SQLiteSnapshotStore` does **not** need this. It opens a connection
per operation via `async with aiosqlite.connect(...)` and leaves no threads
behind — verified. Its lack of a `close()` is correct for its design. (We
initially filed a bug against it; that was wrong, and the correction is in our
`BACKLOG.md` B5.)

## E4. `DomainEvent` equality can never hold between two constructed instances

`DomainEvent` defines no `__eq__`, so pydantic's field-by-field comparison
applies — including `event_id` and `occurred_at`, which differ per instance.
The consequence:

```python
assert decide(command, state) == [SomeEvent(aggregate_id=id, name="x")]
```

is not flaky. It can never pass. This is the single most natural assertion for
anyone testing a decider, and every consumer will write it once.

We hit it in our first task; the implementer diagnosed it correctly and the
codebase now asserts `isinstance` plus the fields that matter. But that is a
convention each consumer has to rediscover.

**Options, in order of preference:**

1. A documented helper — `event.payload_equals(other)`, or a `same_facts(a, b)`
   comparing everything except identity and timestamp.
2. Failing that, a prominent note in the decider/testing docs. The cost of not
   documenting it is an hour per consumer, spent on a confident-looking
   assertion that silently cannot hold.

Changing `__eq__` itself is probably wrong — two events with different ids
genuinely are different events — which is why the helper is the better shape.

## E5. Minor: `ExpectedVersion.any_()`

The trailing underscore reads as a typo at every call site. `ExpectedVersion.ANY`
as a class attribute, or a module-level `ANY_VERSION`, would be easier to write
and easier to review. Cosmetic, and not worth breaking anyone over — worth
considering only if that surface is being revised anyway.

## E6. Minor: no "global feed except this category" read

`read_category(category, options)` exists and is what we used to list one
aggregate type. The shape we needed and could not express was the inverse: a
resumable global feed *excluding* foreign categories.

Our live session feed reads the global feed from a position and turns every
envelope into a UI entry. Once `redstring`'s `Document` and `Consolidation`
streams shared the same file, those foreign events arrived as sessions that do
not exist, and we filter them out by `aggregate_type` in application code.

That filter is three lines and we are not blocked. But every consumer that
shares a store between two libraries will write the same three lines, and a
consumer who does not think of it gets a subtly wrong read model rather than an
error. A `categories=` or `exclude_categories=` option on the global feed would
push it into the library where it can be tested once.

---

## What we are NOT reporting, having checked

- **Two `SQLiteEventStore` instances over one file.** Suspected as a lock
  deadlock; measured, and it works fine — read and write both succeed across
  connections. Not a bug.
- **`SQLiteSnapshotStore` lacking `close()`.** See E3 — correct as designed.
- **`AggregateRepository` inferring category from `aggregate_type`, with the
  `aggregate_type=` override removed in 0.9.0.** This constrains how a consumer
  can lay out streams, and it is why `redstring`'s events can only live on the
  streams it derives. It looks deliberate, and we designed around it rather than
  against it — noted here as context for anyone weighing that decision again,
  not as a defect.
- **`AggregateTypeNotSetError` when a `DeciderAggregate` omits `aggregate_type`.**
  Behaves as documented; we simply had a stale assumption in a plan.
