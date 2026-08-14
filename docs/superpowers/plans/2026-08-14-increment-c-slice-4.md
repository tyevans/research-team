# Increment C, slice 4 — the picker gets thinner

Written 2026-08-14, against `dbb0b65` (`main`, with slice 3b merged).

## 0. What this slice is, after audit 5 rewrote it

The plan's §2.4 as originally written said the picker "loses its two destination
buttons and re-sources its liveness chip from the dock's roster … the only slice
that is pure subtraction". Audit 5 found both halves wrong:

- **The two destination buttons must not be dropped.** #177 (`162dff5`)
  re-pointed the slots rather than deleting them — the row now offers **Project**
  → `#/p/<id>` and **Ask** → `#/p/<id>/ask`. `App.tsx:138` intercepts `ask`
  above `ProjectView`, so no tab reaches it: **the overflow slot is the only
  non-typed-URL door to the ask page**. Deleting it re-opens the regression
  #176/#177 just closed. Proposal §4.1's `DROPPED — one destination` is an
  instruction to reintroduce a shipped bug, and correcting the document is task C.
- **Re-sourcing the chip is a swap, not a subtraction**, and it degrades one
  label.

So this slice is one real change (the chip), one unowned cheap change adjacent to
it (a 2s poll), and two document corrections. It remains the slice that can be
dropped without leaving anything half-built.

## 1. What the survey found that the plan did not know

Three things, all making the change smaller and better than §2.4 describes.

**1. The file is `presentation/tree/ProjectActivity.tsx`**, not
`presentation/project/`. §2.4 names the wrong directory throughout.

**2. The degradation is smaller than "one label" — the roster branch already
writes the replacement string.** The hook has two branches
(`ProjectActivity.tsx:50-63`). Branch 1 reads `research.current(projectId)` and
draws `run · round N`. Branch 2 reads the per-project roster and draws
`` `${worker.kind} running` `` — which for a `run` worker is already exactly
`run running`, the string audit 5 predicts as the degraded output, because
`workers.py` gives the roster's run worker `started_at=None` so no `· elapsed`
suffix is appended either.

**So the change is not "rewrite the label logic". It is: delete branch 1, and
point branch 2 at the global roster instead of the per-project one.** The
surviving code is unmodified.

**3. Neither query key dies, so no endpoint or error path can be deleted.**
`queryKeys.run()` keeps `RunPanel.tsx:51`; `queryKeys.workers(projectId)` keeps
`Workers.tsx:34` and `use-course.ts:81`. In particular `saysDisabled`
(`project-repository.ts:83`) — which §4 wanted deleted — stays, because
`research.current` still has a caller. **Any report claiming this slice deletes
the research-disabled regex is wrong.**

## 2. The decision taken before any code is written

Audit 5 asks for one decision up front. **Answer (a): accept the degradation.**

`run · round N` becomes `run running`. The chip's job is "something is happening
here"; the round count is one click away on the project page, and it is the only
thing in the chip that is not also in the roster. Option (b) — widen `Worker` so
a `run` kind carries `rounds` and a real `started_at` — is a **second** backend
change in an increment whose §4 is titled "the one backend change", and buying a
number back is not worth spending that title. **It is filed as a backlog entry
by task C rather than dropped silently.** Option (c) is refused for audit 5's
reason: it keeps the per-row N+1.

## 3. Why the swap is worth making — the numbers, restated

The saving is larger than "one request replaces `2N`", because the replacement
request is already being made:

- `use-running-agents.ts:58-62` runs `workers.everywhere()` **unconditionally** —
  no `enabled` — and `AgentWidget` is mounted in the shell on every route
  (`App.tsx:94`). Only the project-*names* query is gated (`:76-81`).
- `queryKeys.runningAgents()` is `['workers','all']`, deliberately nested under
  the `allWorkers()` prefix (`keys.ts:40-46`), so it shares a cache entry with
  the invalidation the landing page already performs.

**Re-sourcing the chip therefore adds zero requests.** What it removes: up to
~32 per-row requests per landing-page render (`overscan={4}` on a virtualizer
interleaving recency headings, `ProjectRows.tsx:41-57,112` — so ~16 mounted rows
at 8 visible, × 2), **re-paid on every debounced log burst**, because
`useTreeRefresh` invalidates the `allWorkers()` and `allRuns()` prefixes
(`App.tsx:172-173`) and the per-row keys sit under them (`keys.ts:29-30,38-39`).
That is `2N` every 400ms window, forever, on a page a reader leaves open.

## 4. The one design question, and the preferred answer

`everywhere()` returns `readonly Roster[]` — **one entry per project that has
something running; projects with nothing running are absent entirely**
(`workers.py:374`ff, sorted by project id). So the chip becomes a lookup:
find this project's roster in the array, or draw nothing.

The query itself is free to duplicate — React Query dedupes by key. **The
refresh is not.** `useRunningAgents` arms a `useFrameRefresh` (`:64-68`); if
`ProjectActivity` armed one too it would arm ~16 of them, i.e. 16 stream
subscriptions and 16 debounce timers to invalidate one key.

Two ways out, and the second is preferred:

- **(i) Rely on `AgentWidget`'s shell-mounted refresh.** Costs nothing and is
  already true. The objection: the picker's chip would then go stale if anyone
  ever unmounted the dock, and nothing would say so — an invisible cross-page
  coupling.
- **(ii) `ProjectList` — one mount, not N — arms the refresh for the roster key
  itself.** Costs one redundant invalidation path alongside the dock's. Both
  target the same key, so React Query coalesces the refetch; the honest cost is
  that two independently-debounced subscribers can produce two refetches per
  burst instead of one. **Two requests against thirty-two is the trade, and it
  buys the page ownership of its own freshness.**

Take (ii) unless building it turns up a reason not to; if (i) is taken instead,
the coupling must be asserted by a test, not by a comment.

## 5. Tasks

Three, disjoint in files, runnable in parallel.

### Task A — the chip reads the roster the dock already fetched

Files: `presentation/tree/ProjectActivity.tsx`, `presentation/tree/ProjectList.tsx`,
and wherever the shared roster query lands.

1. Delete branch 1 and the `research`/`isLive` imports it needed.
2. Source `workers` from `queryKeys.runningAgents()` / `workers.everywhere()`,
   selecting this project's roster. Keep `retry: false` and the comment at
   `:33-36` explaining why a failed liveness read must not degrade the row.
3. Resolve §4 (prefer (ii)).
4. **Preserve the branch order the two-query version had**: a run outranked
   everything, because it was checked first. `workers[0]` is not that ordering.
   Decide deliberately whether to prefer the `run` worker when the roster holds
   several, and say which you chose and why — including "kept `[0]`" if that is
   the answer.
5. **Update the doc comment at `:12-25`.** It currently says "Two requests per
   rendered row … The right fix is an `activity` object on `/api/projects`,
   which is a larger piece of work than a landing page." Half of that is now
   false and the other half is a fix that was *not* taken. Say what was taken
   and what it costs.

**`ProjectActivity` has no test file at all** — grep for `activity|ActivityChip`
in `presentation/tree/` returns nothing. So this task writes the first ones.
jsdom is the right home: the assertions are rendered text and request counts,
not geometry. Cover at minimum: the label for each worker kind; a project absent
from the roster drawing no chip; a rejected roster drawing no chip rather than
an error; and **the one that justifies the slice — that N rows issue one
request, not 2N.**

### Task B — `Workers.tsx` stops polling every two seconds

File: `presentation/course/Workers.tsx` (and its tests).

`Workers.tsx:9,33-42` polls `queryKeys.workers(projectId)` every 2000ms. Proposal
§6.2 expected it to die with the merge; it did not, and #170 carried it onto the
merged page via `QueueHeader.tsx:7` — so it runs every two seconds on the page
§6.2 itself calls "the page you leave open all day". No slice owns it.

Replace the interval with `useFrameRefresh` on the same key. `RunPanel`'s 2000ms
poll is **correct to stay** and is out of scope: a run's counters are folded from
its own aggregate and are not on the stream.

**The argument you are asked to check, not assume.** `Workers.tsx:11-21`
justifies its poll on the grounds that the roster is process-local server state
that cannot be pushed. But `use-running-agents.ts:64-68` already refreshes the
*global* roster — the same fold, `everywhere()` is literally `on()` per project
— from `log`/`dispatch` frames with no poll at all. **If frames are sufficient
for the dock they are sufficient here, and if they are not, the dock is already
wrong.** Verify that symmetry actually holds before relying on it.

**Reporting "the poll should stay" is an acceptable outcome** if you find a
roster transition no frame accompanies. Say which transition, and leave the poll.

### Task C — the two documents

Markdown only; touches no code.

1. **`docs/increment-c-plan.md` §4.1** (or wherever the `L-F17`/`L-F18`
   `DROPPED — one destination` rows live): correct them. The premise is true of
   the two *buttons* and false of the *row* — #177 re-pointed the slots to
   Project and Ask, and **Ask has no other non-typed-URL door**. Follow the
   house convention the rest of this plan uses: correct in place with a marked
   note saying what it used to say and why it was wrong, rather than rewriting
   history silently.
2. **`BACKLOG.md`**: file option (b) — widen `Worker` so a `run` kind carries
   `rounds` and a real `started_at` (`workers.py:296-303` sets
   `detail="autonomous run"`, `started_at=None`), which would restore
   `run · round N` on the picker chip. Record that it is a *backend* change, that
   §4 of the increment is titled "the one backend change", and that the chip is
   deliberately degraded in the meantime.

## 6. What this slice does not do

- **It does not delete the destination buttons.** See §0.
- **It does not touch `RunPanel`'s poll.** See task B.
- **It does not settle whether the picker deserves to be a page at all.**
  Plan §6 open question 5 says slice 4 is where that would be settled. It is not
  settled here: this slice makes the page cheaper, which is orthogonal to whether
  it should exist, and answering it would be a redesign rather than a slice.
- **`course.css` remains unowned** — as slice 3b reported, no slice in §2
  allocates its death.

## 7. Verification

All four gates. `npm run test:browser` is **not** expected to be needed: nothing
here is a computed style or a measurement. If a task finds itself wanting a
browser test, that is a signal it has strayed out of scope.

Run gates once, serially — the machine has been under load, and per `CLAUDE.md` a
failure under load is not evidence until it reproduces alone.
