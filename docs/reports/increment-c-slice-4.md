# Increment C, slice 4 — the picker gets thinner, and a poll earns its keep

## The headline

**The landing page's liveness chip now costs zero requests instead of `2N` per
render, re-paid every 400ms.** It reads the global roster `AgentWidget` already
fetches unconditionally on every route, and picks its project out of it. React
Query dedupes by key, so the ~16 rows a virtualizer mounts at 8 visible share one
cache entry.

**The finding that matters more is the one that stopped a change rather than
making one.** Task B was asked to replace `Workers.tsx`'s 2000ms poll with a
frame-driven refresh, on an argument the plan supplied: *if frames are sufficient
for the dock they are sufficient here, and if they are not, the dock is already
wrong.* It checked instead of assuming, and **the second branch is the true one.**

`run_turn`'s contract (`session_service.py:859`) is that all events of a turn
append atomically at the end or not at all — so a turn emits **no feed entry for
its whole duration**, while a `turn` worker sits in the roster for exactly that
interval (`turn_supervisor.py:140-142`, `:157-159`). The intervals are
complementary: a frame-driven refresh sees the roster only at moments when the
turn is already gone. **The worker is not late; it is never visible.** Extraction
has the same hole by a different route — `Extraction` frames carry no feed
position and route to `kind: 'extraction'`, and `remember` runs inside a turn.

Established rather than reasoned: `tests/integration/test_turn_visibility.py`
already pins the property from outside and passes (4 tests, run 2026-08-14).

So the poll stays, and `POLL_MS` and its `useQuery` call are byte-identical.
Only the doc comment changed — it justified the poll as "the roster is
process-local state on the server", which is true but is not the reason the
obvious replacement fails.

## Filed, not fixed

- **B58** — the roster's run worker has no rounds and no start time, which is why
  the chip degrades. Improved on the brief: `Worker.detail`'s own docstring says
  the string is composed server-side *so two front ends cannot disagree*, so a
  `rounds` integer beside a composed `detail` is the arrangement that docstring
  exists to prevent. The honest shape is to compose `round N` into `detail`.
- **B59** — the turn/extraction blindness above, now with three consumers named.
  Task B declined to file it itself because task C was editing `BACKLOG.md`
  concurrently, which is how work gets lost; it flagged it and left it.

## The degradation, decided before any code was written

`run · round N` → `run running`, no elapsed suffix. Audit 5 asked for this to be
decided up front rather than discovered mid-slice; the answer is **(a) accept
it**. Widening `Worker` is a *second* backend change in an increment whose §4 is
titled "the one backend change", and buying a number back is not worth spending
that title. The count is one click away on the project page.

## Three things the plan got wrong, all found by building it

1. **§4's design question was stale.** It offered "borrow the dock's refresh" or
   "arm a new one in `ProjectList`". Neither: `App.tsx:157` already arms
   `useTreeRefresh(route.name === 'home')`, which invalidates `allWorkers()` —
   and `runningAgents()` is `['workers','all']`, deliberately nested under that
   prefix. **Option (ii)'s substance was already built.** Adding a subscription
   would have been a third subscriber on one page, bought for nothing.
2. **"`ProjectActivity` has no test file at all" is half true.**
   `TreeView.test.tsx` had a chip test — and it was the one place `run · round 3`
   was pinned. §5's grep missed it because the test is named `marks a project
   something is running in`. A task trusting the plan would have met a red test
   in a file it did not expect to touch.
3. **My §5 sent task C to a section that does not exist.** There is no §4.1 in
   `increment-c-plan.md`; the `L-F17`/`L-F18` rows are in
   `unified-ui-proposal.md` §4.1. **And the correction was already applied there
   in four places**, in the house convention. Audit 5's "correcting it is the
   first thing a slice-4 implementer should do" had already been done by whoever
   wrote audit 5. Nothing was edited, which is the right answer — re-marking an
   already-marked correction would make the record read as wrong twice.

## The branch-ordering decision

The two-query version checked `research.current` first and **returned before it
ever read the roster**, so a project with a run and a turn drew the run. That
precedence was free and invisible. `workers[0]` would not preserve it:
`everywhere()` sorts by *project id* and says nothing about order within a
roster, so `[0]` would make the label depend on whatever order the server folded
in — a behaviour change attributable to this slice that nobody would attribute
to it. `find(kind === 'run') ?? workers[0]`, pinned by a test whose fixture puts
the turn first.

## Verification

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 230 files already formatted |
| `uv run pytest` | **2385 passed**, 9 deselected, 213s |
| `cd frontend && npm run verify` | full chain, including build, size, `deleted` (35 rules, 21 stylesheets) and `check:tailwind` |

`npm run test:browser` was **not** run and is not owed: nothing in this slice is
a computed style or a measurement. The plan said as much in advance, and no task
found itself wanting one.

**The request-count test was proved red properly, which took a second attempt.**
Restoring the old files made six of seven tests fail on the chip never appearing
— a real failure, but not one that proves what test 6 claims. A throwaway probe
gave the old code working per-project fakes so every chip rendered and only the
count could fail:

```
AssertionError: expected "vi.fn()" to be called 1 times, but got 6 times
```

Three drawn rows × two per-project reads. Measured, not argued.

### The bundle

`app` is **72.6 kB of its 80 kB budget**, against 72.7 kB at the end of slice 3b
— a subtraction of ~0.1 kB. This is the first slice in the increment that did not
spend headroom. Total 285.6 kB of 512 kB.

## What is still not measured

- **The three region widths**, for the fifth slice running — now `BACKLOG.md`
  B57 rather than a deferral, which is where slice 3b said it should end up.
- **Anything below `--bp-wide`**, for the fifth slice running.
- **The frame path itself.** Task A's coupling test invalidates
  `allWorkers()` directly rather than pushing a `log` frame through `App`, so it
  pins the **key nesting** and not App's frame filter. Closing that gap needs a
  fixture that mounts `<App />` with a fake stream. `App.test.tsx` has no
  coverage of `useTreeRefresh` today and that is unchanged.

## What is left of Increment C

**Nothing that is planned.** Slices 0, 1, 2, 3, 3a, 3b and 4 are done.

Two things the increment named and no slice owns, both now written down rather
than assumed:

- **`course.css`'s death** — it survives until QUEUE's rail, roster, extraction
  pane and autonomy panel are rewritten, and no slice in §2 does that. Slice 3b
  said this and it is still true.
- **Plan §6 open question 5 — whether the picker deserves to be a page at all.**
  §2.4 assumed it survives and said slice 4 is where it would be settled. **It is
  not settled here**, deliberately: this slice made the page cheaper, which is
  orthogonal to whether it should exist, and answering it would be a redesign
  rather than a slice.
