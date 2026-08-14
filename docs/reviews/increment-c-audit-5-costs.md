# Increment C audit 5 — the landing page, the costs, and the one backend change

Read-only audit at `9fa6c7b` (merged `main`, includes #175/#176/#177). Nothing
was run: no gate, no build, no browser. Every `file:line` below was opened and
read at that commit. Where a claim can only be settled by executing something it
is recorded as UNVERIFIABLE and §C names the run that would settle it.

Scope: proposal §3.5, §4.1, §6.1, §6.2, §6.3, §6.4; plan §2.4 and §4;
`features-landing-page.md` and `design/landing-page.md`.

---

## A. Findings, most expensive first

### A1. §4.1 drops L-F17 **and** L-F18, and doing that today would re-open the regression #176/#177 just closed

`unified-ui-proposal.md:378-379` reads:

| L-F17 Course button | DROPPED | one destination |
| L-F18 Research button | DROPPED | one destination |

The premise ("one destination") is true of *those two buttons* and false of the
row. #177 (`162dff5`) did not delete the two slots; it re-pointed them. The row
now offers **Project** → `#/p/<id>` (`ProjectList.tsx:371-379`) and **Ask** →
`#/p/<id>/ask` (`ProjectList.tsx:387-398`). Ask is not a MATERIAL facet — `App.tsx`
intercepts it above `ProjectView` — so a reader who opens the project and clicks
through the tabs never reaches it. Deleting the overflow slot per §4.1 removes
the *only* non-typed-URL door to the ask page, which is precisely the defect
#176 and #177 were written to repair (`8fe734c`, `162dff5`).

This is the most costly claim in my domain to get wrong, because §4.1 is the
table an implementer works down, and the sentence in it is currently an
instruction to reintroduce a shipped regression.

**Classification: WRONG (and STALE).** Replacement rows for `§4.1`:

> | L-F17 Course button | PICKER, re-pointed | became **Project** → `projectHref(id)`; the `aria-disabled`-without-a-workflow guard is deliberately gone (#177) — QUEUE renders `get_course`'s 409 as an empty state |
> | L-F18 Research button | PICKER, re-pointed | became **Ask** → `projectHref(id, {facet:'ask'})`; **not** droppable — `App.tsx` intercepts `ask` above `ProjectView`, so the row is the only door |

And the surrounding prose in §4.1's L-R4 paragraph — "the 'course button on an
unshipped preset' case closes because there is no course button" — should read:
the case closes because the button no longer guards on the workflow at all; an
unshipped preset now lands on a project page whose QUEUE region is empty and
says why.

### A2. §6.3's inventory of what `/api/capabilities` replaces is missing the ask route, and the ask route is the one #177 just put a button on

Plan §4 enumerates the 503s and 404s the capability map would replace. Its line
citations were **exactly right at its own base `f87443b`** (verified by
`git show f87443b:…/app.py`), and `app.py` has grown 176 lines since, so every
one of them is now shifted: corpus `:706`, topics `:758`, seeding `:789`,
dispatch `:886` and `:949`, topic write model `:986`, graph `:1092`; the 404s at
`:1331`, `:1409` (autonomous runs), `:1359`, `:1376` (worker roster).

The substantive gap is not the shift. **`asking is not configured` — 503 at
`app.py:1451` and `app.py:1523` — did not exist at `f87443b`** (the ask route
landed in `e212efb`, after the plan's base; `git merge-base --is-ancestor`
confirms). Two other unwired-feature 404s are also absent from both documents:
`app.py:1858` ("approvals are not wired up") and `app.py:1886` ("the autonomy
policy is not wired up").

Why the ask one costs more than the others: #177 gave **every project row** a
button to the ask page. In a build with `ask=None`, that button now opens a page
that draws fine and fails only after the reader types and submits a question —
`AskPage.tsx:47-50` renders the 503 in a generic `role="alert"` box at the
bottom of the thread. That is §6.3's own argument ("a page needs to know which
of its regions can exist before it draws them") with a new and better example
than any it lists.

**Classification: STALE (citations) + INCOMPLETE (inventory).** Replacement
sentence for plan §4's list:

> The 503s are `app.py:706` (corpus), `:758` (topics), `:789` (seeding), `:886`
> and `:949` (dispatch), `:986` (topic write model), `:1092` (graph), and
> `:1451`/`:1523` (**ask** — added after this plan's base, and now reachable
> from a button on every landing row, so a build without it fails at the end of
> a question rather than at the door). The 404s are `:1331` and `:1409`
> (autonomous runs), `:1359` and `:1376` (worker roster), `:1858` (approvals)
> and `:1886` (the autonomy policy).

Everything else in plan §4 holds: **no capabilities route exists** anywhere in
`research_team` or `frontend/src` (grepped), it touches no read model, and the
`saysDisabled` regex is one line — `project-repository.ts:83`, used at `:95` and
`:107` (the plan says `:94`, `:105-107`, `:117-119`; the file has moved by ~10
lines, and there are two use sites, not three). Its answer to "is it still one
backend change?" is **yes**, and "has any of it landed?" is **no**.

### A3. `2N` is right, and the plan was right to doubt the *framing*: it is `2N` **per refresh**, not `2N` per page load

The figure itself: **VERIFIED**. `useProjectActivity` issues exactly two queries
per call — `research.current(projectId)` →
`GET /api/projects/{id}/auto-research` (`project-repository.ts:88-90`) and
`workers.on(projectId)` → `GET /api/projects/{id}/workers`
(`project-repository.ts:127-128`) — at `ProjectActivity.tsx:37-48`. It is called
once per drawn row, at `ProjectList.tsx:254`, with `enabled` hardcoded `true`;
the bound is mounting, not the flag.

Two corrections to §6.1's arithmetic, both making the cost larger:

1. **"Drawn" is wider than "visible."** `ProjectRows.tsx:112` passes
   `overscan={4}` to `VirtualList`, and the virtualized array interleaves
   recency headings with project rows (`withHeadings`, `ProjectRows.tsx:41-57`).
   So at 8 visible project rows the mounted count is 8 plus up to 8 overscan
   items — up to ~16 project rows, i.e. up to ~32 per-row requests, not 16.
   §6.1's `D = 8 → 21` is the floor, not the figure.
2. **The `2N` is re-paid on every debounced log burst.** `useTreeRefresh`
   invalidates the `allWorkers()` and `allRuns()` *prefixes* (`App.tsx:172-173`),
   and the per-row keys sit under them (`keys.ts:29-30, 38-39`). Every 400ms
   window in which any log frame arrives refetches all `2N`. On an idle console
   that is nothing; while anything is running it is `2N` per burst, forever, on
   the page a reader leaves open. This is the strongest argument for §3.5 and
   neither document makes it.

**Replacement sentence for §6.1:**

> Today, with `D` drawn rows — where "drawn" is the virtualizer's window plus
> `overscan={4}` on each side, so `D` exceeds what is on screen: five fixed
> requests (`/api/projects`, `/api/tree`, `/api/sessions`, `/api/health`,
> `/api/workers`) plus **two per drawn row**, and the two-per-row are refetched
> in full on every debounced log burst because `useTreeRefresh` invalidates the
> `['workers']` and `['run']` prefixes rather than named keys.

### A4. §6.1 is wrong that `/api/workers` costs anything conditional on the dock — and that makes §3.5 *more* true than it claims

§6.1 lists `/api/workers` as costing a request "once the dock has ever been
opened". It is not gated. `useRunningAgents` runs the roster query
unconditionally at `use-running-agents.ts:58-62`; only the **project names**
query is `enabled: expanded` (`:76-81`). `AgentWidget` is mounted in the shell on
every route (`App.tsx:94`).

So the roster is already fetched on every landing-page load, unconditionally.
§3.5's "one request replaces `2N`" is therefore an overstatement in the client's
favour: the replacement costs **zero** additional requests, because the one
request is already being made and shares a cache entry
(`queryKeys.runningAgents()` is deliberately under the `allWorkers()` prefix —
`keys.ts:40-46`). The five fixed requests in §6.1 are five in both the current
and the proposed world.

**Classification: WRONG.** Replacement sentence:

> `/api/workers` is already fetched on every page, unconditionally — the dock's
> roster query is not gated on `expanded` (`use-running-agents.ts:58-62`); only
> the project-names read is. Re-sourcing the chip from it therefore adds nothing
> at all, rather than trading `2N` for one.

### A5. The roster genuinely contains the kinds — but **not** the run's round counter, so the chip's best label degrades

§3.5 claims "every worker kind the chip cares about is in it". **VERIFIED, and
by construction**: `WorkerRoster.everywhere()` returns
`tuple([await self.on(project_id) for project_id in sorted(active)])`
(`workers.py:420`) — literally the same fold the per-project route uses, so the
two responses are identical in shape and content. `on()` emits `run`, `stage`,
`dispatch`, `turn`, `extraction` (`workers.py:293-365`), and `roster_view`
carries them whole (`presenters.py:994-1000`). `/api/workers` is 404-when-unwired
in exactly the same way as the per-project route (`app.py:1359` vs `:1376`), so
the failure semantics do not change either.

What is **not** in the roster is the thing the chip's first branch draws.
`useProjectActivity` prefers a live run and labels it `run · round N` from
`run.data?.progress?.rounds` (`ProjectActivity.tsx:50-54`). The roster's `run`
worker carries `detail="autonomous run"` and **`started_at=None`**
(`workers.py:296-303`) — no rounds, no start time. Re-sourced from the roster,
the same live run would read `run running` with no round and no elapsed.

That is a real product regression hidden inside a cost saving, and it is not
mentioned in §3.5, §6.1, or plan §2.4. It has three honest answers, and the plan
should pick one rather than discover it mid-slice:

- **(a) Accept the degradation.** Cheapest; the chip's job is "something is
  happening", and the round count is available one click away.
- **(b) Widen `Worker`** so a `run` kind carries `rounds` and a real
  `started_at`. Small backend change, but it is a *second* backend change in an
  increment whose §6.3 is titled "the one backend change" — say so if you take it.
- **(c) Keep `/auto-research` for the run only.** Halves `2N` to `N` and keeps
  the label. Worst of the three: it retains the per-row N+1 and the
  `saysDisabled` regex that §6.3 exists to delete.

**Recommendation: (a) for slice 4, with (b) filed.** The label's precision is
worth less than the request count, and (b) is a clean follow-up that does not
block the merge.

### A6. §6.2's "required rather than optional" prerequisite has already landed — and was solved by the opposite of what the proposal prescribed

§6.2 ends: "`useCourseRefresh` invalidates `queryKeys.projects()` on every
project frame … It **must** become a single-row invalidation before this merge,
and that is a prerequisite, not a follow-up."

It landed in `980ebfd` (#170, slice 0/1) and it did **not** become a single-row
invalidation. The invalidation was **removed**, and `use-course.ts:82-101` states
why in the code: there is no per-project row to invalidate, because
`/api/projects` answers the whole list as one response under one cache entry, so
a per-row invalidation needs a per-project route — backend work. The comment
also names what the removal costs: nothing refreshes the landing page's workflow
and stage columns while somebody else advances a stage.

**Classification: STALE (satisfied) + the prescription was WRONG.** Replacement
sentence for §6.2:

> `useCourseRefresh`'s `queryKeys.projects()` invalidation is gone as of #170.
> It was deleted rather than narrowed: a single-row invalidation is not
> expressible against a listing that is one cache entry, and the reader it was
> serving (the dock, while expanded, for project *names*) is not one a project
> frame moves. What it drops is stated at `use-course.ts:98-101` — the picker's
> workflow and stage columns go stale while another page advances a stage — and
> the answer is a subscription on the picker, not one on the project page.

Note the interaction with `features-landing-page.md` F9's recorded gap and
L-R6: `queryKeys.projects()` is now invalidated by **nothing** on a log frame
(`useTreeRefresh`, `App.tsx:160-174`, invalidates `tree`, `sessions`, `allRuns`,
`allWorkers` and not `projects`). §4.1's row "L-F9 … gains `queryKeys.projects()`
on `project` frames, closing L-R6" is therefore now **load-bearing** rather than
a nicety, and should be re-marked as such — it is the only thing that replaces
what #170 removed.

### A7. §6.2's "two polls die" — one of them did not, and it moved onto the page that is left open all day

§6.2: "Two polls die. `Workers.tsx` polls every 2000ms and `RunPanel` polls
every 2000ms while a run is live … The roster's poll is replaced by the dock's
frame-driven refresh, which already exists."

Both polls still exist and **both are now mounted on the merged project page**.
`QueueHeader.tsx:6-7` imports `RunPanel` and `Workers` from `presentation/course/`;
`Workers.tsx:36` still sets `refetchInterval: POLL_MS` with `POLL_MS = 2_000`
(`Workers.tsx:9`), unconditionally — not gated on liveness the way `RunPanel`'s
is (`RunPanel.tsx:55`).

So the poll §6.2 said would die is instead running every two seconds on the page
§6.2 itself identifies as "the page you leave open all day". This is a concrete,
cheap slice-4 (or earlier) task that no slice currently owns.

**Classification: WRONG.** Replacement sentence:

> One poll dies and one has not. `RunPanel`'s 2000ms poll stays and is correct
> to stay — a run's counters are folded from its own aggregate and are not on
> the stream. `Workers.tsx`'s unconditional 2000ms poll (`Workers.tsx:9, 36`)
> was supposed to be replaced by the dock's frame-driven refresh; it was not,
> and #170 carried it onto the merged page via `QueueHeader`. Replacing it with
> a `useFrameRefresh` on `queryKeys.workers(projectId)` is unowned work and
> belongs in a slice.

### A8. §6.2's first-paint figure of ~11 is unverified and now unverifiable from the proposal's list

§6.2 lists ten endpoint names and calls it "about 11". Slices 0–2 changed the
page's composition substantially — `QueueHeader` now mounts `AutonomyPanel`,
`ExtractionPane`, `RunPanel`, `Workers` and `SeedPanel` in one band
(`QueueHeader.tsx:1-8`), HOLDER mounts a transcript, and MATERIAL mounts one
facet. A count taken by reading imports will disagree with a count taken from the
network panel, because react-query dedupes shared keys (`queryKeys.projects()` is
requested by `TreeView.tsx:29-32`, `ProjectList.tsx:49` and the dock, and is one
request).

**Classification: UNVERIFIABLE.** §C1 says what settles it. Until then the plan
should not carry "11" as a number; "the union of what the two pages cost, minus
what they shared" is the honest form.

### A9. Smaller, still worth fixing

- **§3.5, "the row's `⟳` chip costs two requests per drawn row (L-F13)"** —
  VERIFIED; `features-landing-page.md` F13's own account matches the code
  line-for-line, including `retry: false` on both and "only the first worker"
  (`ProjectActivity.tsx:59`).
- **§3.5, "a live project sorts first regardless of timestamp (L-F7) becomes a
  sort key"** — VERIFIED as newly possible: the roster names every active
  project in one response (`workers.py:395-420`), and nothing on the picker
  currently consumes it. Unbuilt; correctly scoped as future work.
- **§4.1 L-F13 "shows *all* workers, closing L-R11"** — buildable; the roster
  carries the full tuple and only `ProjectActivity.tsx:59`'s `workers[0]`
  discards it.
- **§4.1 L-F22 "'nothing has run' now points at the project page"** — unbuilt;
  still a plain `<p>` at `ProjectList.tsx:451`. Fine as future work, noted so
  nobody records it as done.
- **§4.1's claim that the "sessions predating projects" empty state is stale
  copy** — the copy is still there, `ProjectList.tsx:106-109`, and still claims
  such sessions exist and are unreachable. If `SessionStarted.project_id` is
  required (per the proposal, since #65), this is a paragraph telling readers
  their data is stranded when it cannot be. Cheap deletion, unowned.
- **Plan §2.4's sequencing argument — "the only slice that is pure
  subtraction"** — no longer true. Half of slice 4 shipped as #177 and was a
  *re-pointing*, not a subtraction; what remains (re-sourcing the chip) is a
  swap with the behavioural cost in A5. It can still be dropped safely, but the
  reason given is no longer the reason.
- **§6.4's table** — the `GET /api/capabilities` row survives (A2); the
  `GateReview` row and the rest are outside my scope and deferred to the other
  audits.

---

## B. Classification table

| # | Claim | Source | Verdict | Evidence |
|---|---|---|---|---|
| 1 | L-F17 and L-F18 are both DROPPED | proposal §4.1:378-379 | **WRONG / STALE** | `ProjectList.tsx:371-398`; #177 `162dff5` |
| 2 | `/api/capabilities` is one change, doesn't exist, touches no read model | plan §4 | **VERIFIED** | grep; `read_models.py` |
| 3 | The 503/404 line citations | plan §4 | **STALE** | correct at `f87443b`; `app.py` +176 lines since |
| 4 | The list of routes it replaces is complete | plan §4 / proposal §6.3 | **WRONG** | misses `app.py:1451`, `:1523` (ask), `:1858`, `:1886` |
| 5 | `saysDisabled` is one line at `:94`, used at `:105-107`/`:117-119` | plan §4 | **STALE** | now `:83`, used at `:95` and `:107` — two sites |
| 6 | Two requests per drawn row | proposal §3.5, §6.1 | **VERIFIED** | `ProjectActivity.tsx:37-48`; `ProjectList.tsx:254` |
| 7 | `D = 8` → 21 requests | proposal §6.1 | **WRONG (floor, not figure)** | `overscan={4}`, `ProjectRows.tsx:112` |
| 8 | The `2N` is paid once per load | implied, proposal §6.1 | **WRONG** | prefix invalidation, `App.tsx:172-173`; `keys.ts:29-30,38-39` |
| 9 | `/api/workers` costs a request "once the dock has been opened" | proposal §6.1 | **WRONG** | ungated, `use-running-agents.ts:58-62`; `App.tsx:94` |
| 10 | Every worker kind the chip needs is in `/api/workers` | proposal §3.5 | **VERIFIED** | `workers.py:420` — same fold as `on()` |
| 11 | One request replaces `2N` | proposal §3.5 | **VERIFIED, understated** | the one request is already being made — A4 |
| 12 | The re-sourced chip is behaviour-preserving | implied, §3.5 / plan §2.4 | **WRONG** | no `rounds`, `started_at=None` — `workers.py:296-303` |
| 13 | `/api/workers` 404s when unwired, distinguishably | proposal §6.1 caveat | **VERIFIED** | `app.py:1359` matches `:1376` verbatim |
| 14 | The roster is process-local, empty after restart | proposal §6.1 caveat | **VERIFIED** | `workers.py:395-418`; `ProjectActivity.tsx:56-58` |
| 15 | `useCourseRefresh` must become a single-row invalidation, pre-merge | proposal §6.2 | **STALE + prescription WRONG** | `use-course.ts:82-101`; `980ebfd` |
| 16 | Two polls die | proposal §6.2 | **WRONG** | `Workers.tsx:9,36`; `QueueHeader.tsx:6-7` |
| 17 | First paint ≈ 11 requests | proposal §6.2 | **UNVERIFIABLE** | §C1 |
| 18 | `/api/projects`'s O(projects) fold is unfixed | proposal §6.1 | **VERIFIED** | unchanged; and now *more* pressing — A6 |
| 19 | L-F7 "live sorts first" becomes buildable | proposal §3.5 | **VERIFIED (unbuilt)** | `workers.py:395-420` |
| 20 | L-F13 F13 inventory entry matches the code | `features-landing-page.md` | **VERIFIED** | `ProjectActivity.tsx` throughout |
| 21 | F17/F18 inventory entries | `features-landing-page.md:280-291` | **STALE** | superseded by #177 |
| 22 | `design/landing-page.md` §"Reaching the four routes" | `landing-page.md:242-259` | **STALE** | four routes are now two pages + sessions |
| 23 | `landing-page.md`'s one backend change (`project_id` on summaries) | `landing-page.md:543-549` | **VERIFIED, shipped** | L-F32; distinct from §6.3's |
| 24 | Slice 4 is pure subtraction | plan §2.4 | **STALE** | half shipped as a re-pointing |
| 25 | Bundle: the picker's subtraction shrinks `app-` | proposal §6.5 | **UNDECIDED** | shared seam; §C4 — but the picker's own delta is ~0, #177 was a relabel |

---

## C. What I could not check without running anything

Each item is a measurement, with the command that takes it. All of these are
gates-or-network work and none of them ran.

**C1. The project page's real first-paint request count (A8).**
```
cd frontend && npm run dev          # then, in the browser
# open #/p/<id> with an empty cache, DevTools → Network → filter /api/
# count distinct requests; repeat with the dock expanded and collapsed
```
The number to record is *distinct requests*, not distinct query keys —
react-query dedupes `queryKeys.projects()` across three callers.

**C2. The picker's real request count at a given viewport (A3).**
```
cd frontend && npm run dev
# open #/ against a database with ≥ 20 projects, Network → filter /api/
# count /auto-research + /workers; then divide by the number of rows on screen
```
This is the only way to settle how much `overscan={4}` actually costs, because
the answer depends on row height against viewport height and jsdom lays nothing
out. A browser test would also do it:
`frontend/src/presentation/tree/ProjectRows.browser.test.tsx` is the file it
belongs in, and `cd frontend && npm run test:browser` runs it.

**C3. The `2N`-per-burst refetch (A3, point 2).**
```
cd frontend && npm run dev
# open #/ with a run live in some project; Network → filter /api/
# watch for 400ms-spaced bursts of N×2 requests as log frames arrive
```
Reasoned from `App.tsx:172-173` and `keys.ts:38-39`; not observed.

**C4. Whether slice 4 moves the bundle at all (table row 25).**
```
cd frontend && npm run verify        # the size budget is only in this chain
```
My reading is that #177 was a relabel and the remaining chip re-sourcing deletes
one repository call — so the `app-` delta is approximately zero and the budget
is not at risk from *this* slice. Shared seam with the component-spec audit;
neither of us can settle it without the build.

**C5. Everything in this document that is a Python-side claim.**
```
uv run ruff check . && uv run ruff format --check . && uv run pytest
```
I read `app.py`, `workers.py` and `presenters.py` and ran none of it. In
particular, "`everywhere()` is the same fold as `on()`" (A5) is read off
`workers.py:420` and would be settled by
`uv run pytest tests/ -k "everywhere or roster"`.

**C6. Whether a capabilities parameter breaks the entrypoint tests as plan §4
predicts.**
```
uv run pytest tests/interfaces/test_web_entrypoint.py
```
Only meaningful once the parameter exists; recorded so whoever builds it knows
the prediction is untested and that a *red* run there is the expected first
result.

**C7. The ask-page 503 path (A2).** There is no local way to see it without an
`ask=None` build:
```
# start the server with the ask dependency unwired, then from #/ click "Ask"
# on any row and submit a question; the 503 should appear in AskPage's alert box
```
Read off `app.py:1451` and `AskPage.tsx:47-50`; not observed.

---

## D. The three things a slice-4 implementer should change in the plan first

1. **Delete the DROPPED verdict on L-F17/L-F18** and replace it with A1's two
   rows. Everything else in slice 4 is recoverable; this one ships a regression.
2. **Decide A5's (a)/(b)/(c)** before touching `ProjectActivity.tsx`. The
   recommendation is (a), with (b) filed — but the plan currently does not know
   the question exists.
3. **Add the ask 503 to §6.3's inventory** (A2) and re-date every line citation
   in plan §4, which is correct at `f87443b` and wrong at `HEAD`.
