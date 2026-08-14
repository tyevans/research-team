# Increment C, slice 4 — task A: the chip reads the roster

Written 2026-08-14, on branch `increment-c-slice-4` in the
`gate-review-tooltip` worktree.

## What changed

Five files, all mine; nothing touched in `presentation/course/` (task B) or in
the markdown task C owns.

- **`frontend/src/presentation/tree/ProjectActivity.tsx`** — branch 1 deleted
  along with the `isLive` import and the `research` port. The surviving branch
  now reads `queryKeys.runningAgents()` / `workers.everywhere()` and selects
  this project's roster out of the array. `retry: false` and the comment
  explaining it are kept. The `:12-25` doc comment is rewritten.
- **`frontend/src/presentation/tree/ProjectList.tsx`** — the call site loses its
  `enabled` argument, and the `ProjectListRow` doc comment's claim that the
  request count is "**unchanged**: still two per drawn row" is replaced with what
  is now true.
- **`frontend/src/presentation/tree/ProjectActivity.test.tsx`** — new, 7 tests.
- **`frontend/src/presentation/tree/TreeView.test.tsx`** — the container fake
  answers `workers.everywhere` instead of `workers.on`, and the existing
  `marks a project something is running in` test is rewritten (see below).
- **`frontend/src/app/App.tsx`** — comment only, at `useTreeRefresh`. It said the
  landing page "already asks two per drawn row", which is now false, and it did
  not say why `allWorkers()` is the invalidation that keeps the chip fresh.

The hook signature lost its second parameter. With one shared cache entry an
`enabled` flag on one of sixteen subscribers does not gate anything — React
Query runs the query if any observer wants it — so keeping it would have left an
inert knob that reads like a control.

## The design question (§4): neither (i) nor (ii), because (ii) already exists

**§4 missed that the landing page already owns this refresh.** `App.tsx:157`
arms `useTreeRefresh(route.name === 'home')`, which on a `log` frame invalidates
`queryKeys.allWorkers()` — `['workers']`. `queryKeys.runningAgents()` is
`['workers', 'all']`, deliberately nested under that prefix (`keys.ts:40-46`).
So the chip is already refreshed by a subscription that is armed exactly when the
landing page is on screen, one mount, not N, and not the dock's.

That is option (ii)'s substance — *the page owns its own freshness* — already
built. Adding a `useFrameRefresh` inside `ProjectList` as §4 literally asks
would have been a **third** subscriber on the same page (App's, the dock's, and
the new one), a second debounce timer, and the "two refetches per burst instead
of one" cost §4 was willing to pay — bought for nothing, since the thing it buys
was already there.

Two consequences I took seriously rather than assumed away:

- §4's objection to (i) does not apply. The coupling is not cross-page to
  `AgentWidget`; it is same-page, to the landing route's own refresh, whose
  comment already says it exists for "the landing page's live markers".
- §4 says a coupling that is relied on must be **asserted by a test, not by a
  comment**. Done: `refreshes off the invalidation the landing page already
  fires` invalidates `queryKeys.allWorkers()` — the exact key `App.tsx:173`
  passes — and asserts the roster refetches. It fails the moment anyone moves
  `runningAgents()` out from under the prefix, which is a change that would
  otherwise freeze every chip on the page until a reload with nothing to
  notice.

The honest weakness: that test invalidates the key directly rather than pushing
a `log` frame through `App`, so it pins the **key nesting** and not App's frame
filter. Closing that gap means a test that mounts `<App />` with a fake stream,
which is a heavier fixture than this slice justified. `App.test.tsx` has no
coverage of `useTreeRefresh` at all today, and that is unchanged.

## Branch ordering (§5 A item 4): prefer `run`, not `[0]`

The two-query version checked `research.current` first and **returned before it
ever read the roster**, so a project with a run and a turn drew the run. That
precedence was free and invisible.

`workers[0]` would not preserve it. `everywhere()` sorts *by project id*
(`workers.py:374`ff) and says nothing about order within a roster, so `[0]`
would make the label depend on whatever order the server happened to fold in —
a behaviour change attributable to this slice that no gate and no reader would
attribute to it. I chose `find(kind === 'run') ?? workers[0]`: the old
precedence, kept deliberately and pinned by a test whose fixture puts the turn
first, so it fails if anyone simplifies it back to `[0]`.

## Tests, and which were proved red

Seven new tests in `ProjectActivity.test.tsx`, rendered through `TreeView` so
the mounting is the real virtualizer's:

1. a chip per worker kind, in the roster's words (`run running`, `turn running`,
   `extraction running`)
2. the `· 30s` elapsed suffix when `startedAt` is set
3. **`run` preferred over a turn listed before it**
4. a project absent from the roster draws no chip
5. a rejected roster draws no chip and no error
6. **N drawn rows issue one request** — the assertion the slice exists for
7. invalidating `allWorkers()` refetches the roster

**All seven were proved red**, by restoring the previous `ProjectActivity.tsx`
and `ProjectList.tsx` from `HEAD` and re-running. Six failed on the chip never
appearing, because the old code never calls `everywhere` at all — a real failure,
but a cheap one that does not prove what test 6 claims.

**So test 6 was re-proved properly.** A throwaway copy of the test file gave the
container fakes for `research.current` and `workers.on` that answered per
project, so every chip rendered under the old code and only the count could
fail. It did:

```
AssertionError: expected "vi.fn()" to be called 1 times, but got 6 times
```

Three drawn rows × two per-project reads. That is the number measured, not
argued, and it is the direct evidence that the request-count test would fail
against the two-query implementation. The probe file was deleted afterwards.

One existing test had to change: `TreeView.test.tsx`'s `marks a project
something is running in` asserted `/run · round 3/` and is the one place the
round count was pinned. It is rewritten against the roster (`run running`) with
a docstring saying what it used to assert and why. Rewritten rather than
deleted, because it is the only assertion that the chip reaches the *card* —
`ProjectActivity.test.tsx` is about the hook, and a slot wired to nothing would
pass all seven of its tests.

## Verification run

Only my files, serially, one vitest process at a time:

- `vitest run src/presentation/tree/ src/presentation/agents/ src/presentation/entity/project/` — 52 passed
- `vitest run src/app/` — 12 passed
- `tsc --noEmit` — clean
- `eslint src/presentation/tree src/app/App.tsx` — clean
- `prettier --write` on the five files

I did not run the whole suite or `npm run verify`; the parent agent runs the
gates. No browser test: nothing here is a computed style or a measurement.

## The honest cost

- **`run · round N` is gone.** A run now draws `run running` with no elapsed
  suffix, because the roster's run worker is `detail="autonomous run"` with
  `started_at=None`. This is the accepted degradation of §2; task C files the
  backlog entry.
- **A cross-file coupling.** `ProjectActivity` is fresh because `App.tsx`
  invalidates a prefix its key sits under. That is now asserted, but the
  assertion is over the key relationship, not over the frame path.
- **`useProjectActivity` is no longer independently gateable.** Nothing wants
  that today (one caller, always on), and it is worth knowing before someone
  tries to reuse the hook somewhere the roster should not be fetched.
- **`research.current` still has a caller** (`RunPanel.tsx:51`), so `saysDisabled`
  and `queryKeys.run()` are untouched, exactly as §1.3 warned. This slice
  deletes no endpoint and no error path.

## What the plan got wrong

1. **§4 is stale about the refresh** — the landing page already arms one via
   `App.tsx`'s `useTreeRefresh`, gated on the home route, invalidating the very
   prefix `runningAgents()` sits under. §4 presents (i) "borrow the dock's" and
   (ii) "build the page's own" as the only choices; (ii) was already built. I
   took what exists and asserted it, which is (ii)'s outcome at (i)'s price.
2. **"`ProjectActivity` has no test file at all … So this task writes the first
   ones" is half true.** No file named for it, correct — but `TreeView.test.tsx`
   has a chip test, and it is the one that pinned `run · round 3`. §5's grep
   (`activity|ActivityChip` in `presentation/tree/`) misses it because the test
   is named `marks a project something is running in` and asserts the label
   text. A task that trusted the plan here would have been surprised by a red
   test in a file it did not expect to touch.
3. **`TreeView.test.tsx`'s container fake needed updating regardless.** It
   answered `workers.on` and not `workers.everywhere`, so every test in the file
   would have had the chip query reject on a missing method. Not a defect in the
   plan's reasoning, but it is work §5 does not mention.

Everything else in §1 held: the file is in `presentation/tree/`, the roster
branch already writes the replacement string, and no query key died.
