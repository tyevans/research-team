# Slice 4, task B — the 2s poll in `Workers.tsx` stays

Written 2026-08-14, in the `gate-review-tooltip` worktree on `increment-c-slice-4`.

## Verdict

**The poll stays.** The symmetry the plan asked me to check does not hold, and
the asymmetry is a deliberate guarantee rather than an oversight. The plan
explicitly allows this outcome (§5, task B: "Reporting 'the poll should stay' is
an acceptable outcome if you find a roster transition no frame accompanies").

## The transition no frame accompanies: a turn while it is running

`research_team/application/session_service.py:859` states it as the contract of
`run_turn`:

> One user turn. **All events append atomically at the end, or not at all.**

A turn therefore emits **no feed entry at all** for its whole duration. The
front end's `log` frame is the default branch of
`frontend/src/infrastructure/sse/event-stream.ts:222-236` — it is a session
event, and there are none until the turn commits.

A `turn` worker is in the roster for exactly that interval:
`turn_supervisor.py:140-142` writes `_started[session_id]` at task creation, and
the `finally` at `:157-159` removes it when the task is done.
`workers.py:340-350` folds `_started` into the roster.

So the two intervals are complementary. A frame-driven refresh sees the roster
only at moments when the turn is already gone: **a `turn` worker would never be
visible**, rather than merely being visible late. With the 2s poll it appears
within 2s of starting and stays for the turn.

### How this was established

Read, then measured — not reasoned from the docstring alone.
`tests/integration/test_turn_visibility.py::test_a_turns_events_all_become_visible_at_once`
already pins the property from outside: it counts feed entries before a turn and
again from inside the model, and asserts `during_turn == before_turn`, "a turn
must not be visible while it runs". Run on 2026-08-14:

```
uv run pytest tests/integration/test_turn_visibility.py -q
4 passed in 8.03s
```

The whole file is about this: its module docstring says a watcher "never sees a
turn in progress".

### A second, independent case: extraction

`interfaces/web/extraction.py` reports extraction progress on `Extraction`
frames, which its own docstring says "carry no feed position" — the front end
routes them to `kind: 'extraction'` (`event-stream.ts:167-174`), not `log`.
`remember` runs *inside* a turn, so the atomic-append property above means an
extraction lasting minutes produces zero `log` frames too. The `extraction`
worker (`workers.py:352-365`) has the same problem as the `turn` worker, reached
by a different route.

### What *is* covered by frames, for completeness

- `dispatch` — its own frame kind, in the dock's filter already.
- `stage` — a stage runner runs turns, so it is covered only as well as turns
  are; its *entry* into the roster (`stage_runner.py:464`) is a `project` frame,
  which `use-course.ts:81` already invalidates `queryKeys.workers(projectId)`
  on. That path exists today and is unaffected by anything here.
- `run` — `ResearchRunStarted` is a `ResearchRun` aggregate event and the feed is
  unfiltered (`live_feed.follow`), so it reaches the browser through
  `feed_event` and is parsed as a `log` frame addressed to the run id as if it
  were a session. That is accidental coverage of run start, and it does not
  rescue the turn or extraction cases.

## What this says about the dock

The plan's own framing was "if frames are sufficient for the dock they are
sufficient here, and if they are not, the dock is already wrong." The second
branch is the true one. `use-running-agents.ts:64-68` refreshes on `log` /
`dispatch` only, so the agent dock understates turn and extraction liveness in
exactly the way described above.

**I have not touched `use-running-agents.ts`** — it belongs to task A, and I was
told to read it and leave it. Flagging it here is the whole of my action on it.
It is worth a backlog entry; I did not file one, because `BACKLOG.md` is being
edited by task C in this same worktree and a concurrent edit is how work gets
lost.

## What I changed

One file of code and one of tests, both in `presentation/course/`:

- `frontend/src/presentation/course/Workers.tsx` — the doc comment only. It
  previously justified the poll as "the roster is process-local state on the
  server", which is true but is not the reason the obvious replacement fails.
  It now names the atomic-append guarantee, cites the test that measures it and
  the date it was run, states the cost of the poll plainly (one request per two
  seconds per open course page, mostly to be told nothing changed), and records
  that the dock's frame-only refresh is the dock's bug rather than a precedent.
  **`POLL_MS` and the `useQuery` call are byte-identical.** No behaviour change.
- `frontend/src/presentation/course/Workers.test.tsx` — one new test,
  `re-reads the roster with no frame of any kind arriving`. It renders with no
  `StreamProvider` at all (so a frame-driven refresh could not even be
  constructed), waits for the first read, advances fake timers past the
  interval, and asserts a second read happened. It asserts a *second call*
  rather than the constant, so raising `POLL_MS` is a deliberate edit here
  rather than a silent pass.

## What I deliberately did not change

- The interval itself. That is the finding.
- `RunPanel`'s poll — out of scope by the plan.
- `use-running-agents.ts`, `ProjectActivity.tsx`, `ProjectList.tsx` — task A's.
- `BACKLOG.md` — task C's, per the note above.

## Risk

Near zero, because no behaviour changed. The residual risk of the *decision* is
the cost that stays: one request per two seconds per open course page. If that
ever needs to go, the fix is not a frame filter on the client — it is a server
frame emitted when the roster changes (turn begin/end, extraction begin/end),
which is backend work and is precisely what §4's "the one backend change" title
is already spent on.

## Tests proved red

`re-reads the roster with no frame of any kind arriving`, proved red by
temporarily deleting the `refetchInterval: POLL_MS` line — the exact change task
B was asked to consider:

```
AssertionError: expected 1 to be greater than 1
 ❯ src/presentation/course/Workers.test.tsx:72:40
 Tests  1 failed | 6 passed (7)
```

Restored, and green: `Tests 7 passed (7)`.

## Gates

Run over the files I touched, serially, one vitest process at a time:

- `npx vitest run src/presentation/course/Workers.test.tsx` — 7 passed.
- `npx prettier --check` on both files — clean.
- `npx eslint` on both files — clean.
- `npx tsc --noEmit` — clean.
- `uv run pytest tests/integration/test_turn_visibility.py` — 4 passed (as
  evidence, not as a gate; I changed no Python).

I did not run the full suite or `npm run verify`, per the instruction to run
only the files I touched and not to contend with the two agents working in
parallel in this worktree. `npm run test:browser` is not relevant: nothing here
is a computed style or a measurement.
