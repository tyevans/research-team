# Activity Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move each half of the project page's "Working now" card to the region whose question it answers — the roster to the chrome dock that already holds it, the extraction detail to the Graph tab it describes — and delete the card.

**Architecture:** Four independent slices. Two deletions (the roster and its 2s poll; the dead `replace` parameter), one obligation the deletion creates (the dock must poll while open, because a running turn produces no frames), and one move-plus-redesign (extraction becomes a float on the graph stage that renders only when it has something to say). Tasks are ordered so the suite is green at every commit.

**Tech Stack:** React 19, TypeScript, TanStack Query, zustand, Tailwind v4 utilities over `tokens.css` custom properties, vitest (jsdom) + vitest browser mode (headless Chromium), Storybook.

**Spec:** `docs/superpowers/specs/2026-08-27-activity-placement-design.md` — read it first. The plan argues from it and does not repeat its reasoning.

## Global Constraints

- **Four gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The two ruff commands run over the whole repository. This plan touches no Python, but a stray file still fails them.
- **`npm run test:browser` is a fifth command and not a gate.** It is mandatory for Tasks 5 and 7 of this plan — `CLAUDE.md`: run it "when you touch a stylesheet, a layout primitive, or anything whose correctness is a computed style or a measurement."
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **`border-solid` beside one directional width draws three unwanted sides.** Pair `border-0` with the directional width. Do NOT write `border-0` beside a non-directional `border` — that is two conflicting `border-width` utilities.
- **Check whether a `tokens.css` rule is layered before overriding it with a utility.** The global `:focus-visible` is unlayered and beats any Tailwind utility regardless of specificity. Named class in a stylesheet, not a utility, and the assertion has to be a browser measurement.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned. If a test would pass with the change reverted, say so in its docstring.
- **Commit messages carry the reasoning that does not fit in a comment** — what was considered and rejected, what the change costs, what is deliberately left undone.
- **Every commit message ends with:**
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
  ```
- **Stage and commit in one shell invocation** (`git add … && git commit …`). Another agent's commit can otherwise take your staged files.
- **Pre-release: no backwards compatibility is owed.** Break contracts rather than migrating them.

---

### Task 1: The dock polls while it is open

Done first and alone, so the roster's deletion in Task 2 never leaves a window where a running turn is invisible everywhere. Reviewable on its own: it is a bug fix the spec argues for independently.

**Files:**
- Modify: `frontend/src/presentation/agents/use-running-agents.ts:56-62` (the `roster` query)
- Test: `frontend/src/presentation/agents/use-running-agents.test.tsx` (create if absent; otherwise add to it)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ROSTER_POLL_MS` — an exported `const ROSTER_POLL_MS = 2_000` in `use-running-agents.ts`. Task 2 deletes `POLL_MS` from `Workers.tsx`; this is where that interval survives.

- [ ] **Step 1: Read the existing test file, or note that there is none**

Run: `ls frontend/src/presentation/agents/`

If `use-running-agents.test.tsx` does not exist, create it and mirror the harness in `frontend/src/presentation/project/queue/Workers.test.tsx` — a `QueryClientProvider` with `retry: false` plus a `ContainerProvider` holding a fake `workers` repository. Read that file before writing this one; do not invent a harness.

- [ ] **Step 2: Write the failing test**

Two assertions, because one of them passes today and the pair is what pins the behaviour. Create/append to `frontend/src/presentation/agents/use-running-agents.test.tsx`:

```tsx
/** The one liveness case no frame can reveal.
 *
 * `Workers.tsx` recorded this before it was deleted, with
 * `tests/integration/test_turn_visibility.py::test_a_turns_events_all_become_visible_at_once`
 * behind it: a turn's events append atomically when the turn commits, so while
 * a turn is running the feed carries nothing about it at all. A turn worker is
 * in the roster for exactly the interval in which no frame can arrive. A
 * frame-driven refresh would therefore show a turn only after it had gone.
 *
 * Open, this polls. Closed, it must not — the collapsed dock draws a count, and
 * a poll on every page of an idle console is the cost this design moved off the
 * project page rather than spreading.
 */
it('polls the roster while the dock is open and not while it is closed', async () => {
  vi.useFakeTimers()
  const everywhere = vi.fn().mockResolvedValue([])

  const { rerender } = renderHookWithContainer(({ open }: { open: boolean }) => useRunningAgents(open), {
    initialProps: { open: false },
    everywhere,
  })

  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere).toHaveBeenCalledTimes(1)

  rerender({ open: true })
  await vi.advanceTimersByTimeAsync(ROSTER_POLL_MS * 3)
  expect(everywhere.mock.calls.length).toBeGreaterThan(1)

  vi.useRealTimers()
})
```

`renderHookWithContainer` is a local helper you write in this file — `renderHook` from `@testing-library/react` with a wrapper composing `QueryClientProvider` and `ContainerProvider`. Copy the container shape from `Workers.test.tsx`; it builds a partial container and casts, which is the established pattern here.

- [ ] **Step 3: Run the test and confirm it fails**

Run: `cd frontend && npx vitest run src/presentation/agents/use-running-agents.test.tsx`
Expected: FAIL on the second assertion — `expect(1).toBeGreaterThan(1)`. The first assertion passes today, which is the point: the closed case is already correct and the test says so.

- [ ] **Step 4: Implement**

In `use-running-agents.ts`, above the hook:

```ts
/** How often the open dock re-asks who is running.
 *
 * Two seconds, inherited from the project-page roster this replaced rather than
 * chosen fresh. The interval is not tuning: it is the latency of "a new worker
 * appeared" for the one worker kind whose appearance produces no frame. A turn's
 * events append atomically when the turn commits (`session_service.run_turn`),
 * so a turn is in the roster for exactly the interval in which the feed is
 * silent about it — measured by
 * `tests/integration/test_turn_visibility.py::test_a_turns_events_all_become_visible_at_once`,
 * run rather than reasoned from.
 *
 * Gated on the panel being open, which is the whole difference from what this
 * replaced. The collapsed dock draws a count and keeps its frame-only refresh:
 * a run or a dispatch appearing does produce a frame, and only a turn does not.
 * What this costs is one request every two seconds while somebody is looking;
 * what it replaced cost that on every open project page whether anyone was
 * looking or not.
 */
export const ROSTER_POLL_MS = 2_000
```

and on the `roster` query, beside the existing `retry: false`:

```ts
    // Per observer, not per key: `ProjectActivity` reads the same cache entry
    // under `queryKeys.runningAgents()` and sets no interval, so the landing
    // page keeps costing nothing.
    refetchInterval: expanded ? ROSTER_POLL_MS : false,
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `cd frontend && npx vitest run src/presentation/agents/use-running-agents.test.tsx`
Expected: PASS, both assertions.

- [ ] **Step 6: Run the neighbours that share this hook**

Run: `cd frontend && npx vitest run src/presentation/agents src/presentation/tree`
Expected: PASS. `ProjectActivity` reads the same key; if its tests use fake timers, an interval can change their call counts.

- [ ] **Step 7: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add frontend/src/presentation/agents/ && git commit -F - <<'MSG'
The dock stops understating a running turn

`Workers.tsx` has carried the diagnosis and declined the fix: a turn's events
append atomically when the turn commits, so while one runs the feed says
nothing, and the dock's frame-only refresh can only show a turn after it has
gone. It called that "the dock's bug, not an argument for copying it here" and
kept a 2s poll on the project page instead.

The poll moves to the dock and is gated on the panel being open. Cost: one
request every two seconds while a person is actually looking at it, against
every two seconds on every open project page regardless. The collapsed dock is
unchanged and still frame-driven, which is right for the count it draws — a run
or a dispatch appearing produces a frame; only a turn does not.

The closed-case assertion passes today. It is in the test anyway: the pair is
what pins the gating, and without it a later change could poll everywhere and
still be green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 2: The roster leaves the project page

**Files:**
- Delete: `frontend/src/presentation/project/queue/Workers.tsx`
- Delete: `frontend/src/presentation/project/queue/Workers.test.tsx`
- Delete: `frontend/src/presentation/project/queue/WorkerList.tsx`
- Delete: `frontend/src/presentation/project/queue/WorkerList.test.tsx`
- Delete: `frontend/src/presentation/project/queue/WorkerList.stories.tsx`
- Modify: `frontend/src/presentation/project/queue/QueueHeader.tsx` — drop the `Workers` import, the `watching`/`onWatch` props, and unwrap the `aria-label="Working now"` section
- Modify: `frontend/src/presentation/project/ProjectView.tsx:520-527` — drop `watching`/`onWatch` from the `QueueHeader` call
- Modify: `frontend/src/presentation/project/use-project.ts:69` — drop the `queryKeys.workers` invalidation
- Modify: `frontend/src/application/queries/keys.ts` — delete the `workers` key
- Modify: `frontend/src/application/ports/repositories.ts` — delete `WorkerRepository.on`
- Modify: whichever infrastructure adapter implements `on` (find it: `grep -rn "everywhere" frontend/src/infrastructure`)
- Modify: `frontend/src/app/App.test.tsx:327+` — repoint the watched-worker test
- Test: existing files above

**Interfaces:**
- Consumes: nothing. Task 1 is independent.
- Produces: `QueueHeader` takes `{ projectId, holdingSessionId }` only. Task 3 depends on that signature.

- [ ] **Step 1: Prove the roster's card is on screen before deleting it**

Run: `cd frontend && npx vitest run src/presentation/project/queue/Workers.test.tsx src/presentation/project/queue/WorkerList.test.tsx`
Expected: PASS. Record the count. This is the baseline the deletion removes; a reviewer needs to know these were green rather than already broken.

- [ ] **Step 2: Repoint the watched-worker test in `App.test.tsx`**

Read `frontend/src/app/App.test.tsx` around line 327. The test is `puts a watched worker in the address bar under the session facet` and it clicks a button named `answering` that `WorkerList` renders.

Its comment claims it is "the only test in the repository that sees which one is written, because `Workers` takes `onWatch` as a prop and never builds an href". **That claim is stale** — `CoursePage.tsx:193` builds `projectHref(projectId, sessionSelection(...))` directly. Do not delete the assertion; move it onto a surviving producer.

Replace the test with one driving the Holding-session tab, which writes the same facet through `ProjectView.tsx:597`:

```tsx
it('puts the holding session in the address bar under the session facet', async () => {
  // Inherited from `puts a watched worker in the address bar under the session
  // facet`, which drove `WorkerList`'s per-worker button. That button is gone
  // with the roster: the dock opens a worker in a drawer and writes no URL, so
  // the project page no longer turns "a worker is running" into an address.
  //
  // The facet is not gone and neither is its grammar — `ProjectView:411`, the
  // tab below, and `CoursePage:193` all still write it. This follows the tab,
  // which is the producer a reader on this page can reach. The old comment
  // claiming this was the only test that sees the href written was already
  // stale when it was inherited; `CoursePage` builds one too.
  const user = userEvent.setup()
  window.location.hash = `#/p/${ATLAS}`
  renderApp()

  await user.click(await screen.findByRole('tab', { name: 'Holding session' }))

  expect(window.location.hash).toBe(`#/p/${ATLAS}/session/${HOLDER}`)
})
```

Check `ProjectView.tsx:597` before writing the expectation: it calls `sessionSelection(sessionId, ScrubPoint.head())`, which may append a scrub segment. Run the test and read the actual hash rather than assuming; assert what it really writes.

- [ ] **Step 3: Run it and confirm it fails**

Run: `cd frontend && npx vitest run src/app/App.test.tsx -t "holding session in the address bar"`
Expected: FAIL — the tab click may write a different hash than asserted, or the old test name still exists. Fix the expectation to the observed hash, then confirm it passes before deleting anything. A repointed test must be green *before* its subject is removed, or you cannot tell which change broke it.

- [ ] **Step 4: Delete the five files**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system/frontend/src/presentation/project/queue
git rm Workers.tsx Workers.test.tsx WorkerList.tsx WorkerList.test.tsx WorkerList.stories.tsx
```

- [ ] **Step 5: Unwrap the card in `QueueHeader.tsx`**

Remove the `Workers` import. Replace:

```tsx
    <section className={CARD} aria-label="Working now">
      <Workers projectId={projectId} watching={watching} onWatch={onWatch} />
      {/* …comment… */}
      <ExtractionPane projectId={projectId} />
    </section>
```

with nothing — `ExtractionPane` leaves this file entirely in Task 3, and leaving it here in a card of its own for one commit would be a card this plan then deletes. **Move `ExtractionPane` out in this same commit** to keep the tree honest: cut the import and the element here, and land the mount in Task 3. Between the two tasks the extraction pane is unmounted; say so in the commit message rather than hiding it.

Then delete the `watching` and `onWatch` props from the component signature and its prop types, and add to the docstring:

```
 * **The roster is not here, and the card it shared with the extraction pane is
 * gone.** `Shell.tsx` gives chrome the test — "what is running is not a
 * property of the page you happen to be on" — and a per-project roster polled
 * every two seconds was this page answering a question the dock already
 * answers for free. What is left in this header is only what a reader *acts*
 * on: ask, be asked, run, seed, autonomy. That is the region's stated job and
 * this is the first time the header has held only that.
```

- [ ] **Step 6: Drop the props at the call site**

In `ProjectView.tsx`, the `QueueHeader` element becomes:

```tsx
        <QueueHeader projectId={projectId} holdingSessionId={holdingSessionId} />
```

Delete the `onWatch` arrow and its comment. Leave `const watching` at line 382 alone — it still feeds `sessionId` at line 388.

- [ ] **Step 7: Remove the query key and the port method**

In `use-project.ts:69`, delete the `queryKeys.workers(projectId)` invalidation line and its enclosing statement if it becomes empty. In `application/queries/keys.ts`, delete the `workers` entry. In `application/ports/repositories.ts`, delete `WorkerRepository.on` and its docstring. Then delete the implementation:

Run: `grep -rn "\bon(" frontend/src/infrastructure/*worker* frontend/src/infrastructure/**/*orker*` to find the adapter, and remove the method plus any test that drives it directly.

- [ ] **Step 8: Verify nothing still references the deleted names**

Run:
```bash
cd frontend && grep -rn "WorkerList\|WorkerListUnavailable\|queryKeys.workers\|workers\.on\b" src/ || echo "clean"
```
Expected: `clean`. Any hit is an incomplete deletion. `WorkerDrawer` must still exist and still be imported by `AgentWidget` — check that separately:
```bash
grep -rn "WorkerDrawer" src/ | head
```

- [ ] **Step 9: Typecheck and run the affected suites**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. Then:
Run: `cd frontend && npx vitest run src/app src/presentation/project`
Expected: PASS. `ProjectView.browser.test.tsx` is browser-mode and does not run here; Task 7 covers it.

- [ ] **Step 10: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
The project page stops answering a question the chrome answers

Three surfaces said what was running. `AgentWidget` says it for everything
everywhere on one shared query; `ProjectActivity` filters that same cache entry
for a landing-page row at zero additional cost; and this one polled
`workers.on(projectId)` every two seconds, forever, per open project page, to
say a subset of what the first already held. `Shell.tsx` states the test it
failed: what is running is not a property of the page you happen to be on.

Deleted: `Workers`, `WorkerList`, `WorkerListUnavailable`, their tests and
story, the `workers` query key, its invalidation, and `WorkerRepository.on`.
`WorkerDrawer` stays — the dock is its other caller and always was.

What this costs, and it is not nothing: the roster's button *navigated*, so a
watched worker was a URL and a back-button destination. The dock's row opens a
drawer and writes nothing. This deletes the only path from "a worker is
running" to "that worker's transcript is in the address bar". Three other
producers of `sessionSelection` were checked and survive, so the facet keeps
its grammar; one entry point is lost, not the destination.

`App.test.tsx`'s watched-worker test is repointed rather than deleted, onto the
Holding-session tab. Its inherited comment claimed it was the only test that
sees the href written; that was already false — `CoursePage.tsx:193` builds one.

Deliberately left undone: whether `/api/projects/{id}/workers` still has
callers is a Python-side survey with its own gates. Filed to BACKLOG rather
than guessed at from this side.

The extraction pane is unmounted by this commit and remounted by the next, on
the Graph tab. Splitting it that way keeps this commit a pure deletion; the
alternative was a card holding one panel that the following commit deletes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 3: Extraction moves to the graph stage

Mount only — no redesign. Task 4 changes what it looks like; splitting them means a reviewer can reject the placement without re-reading the drawing, and vice versa.

**Files:**
- Move: `frontend/src/presentation/project/queue/ExtractionPane.tsx` → `frontend/src/presentation/research/ExtractionPane.tsx`
- Move: `frontend/src/presentation/project/queue/ExtractionPane.test.tsx` → `frontend/src/presentation/research/ExtractionPane.test.tsx`
- Move: `frontend/src/presentation/project/queue/ExtractionView.stories.tsx` → `frontend/src/presentation/research/ExtractionView.stories.tsx`
- Modify: `frontend/src/presentation/research/GraphPane.tsx` — mount it as the first row of the top-left command column

**Interfaces:**
- Consumes: `QueueHeader` no longer imports `ExtractionPane` (Task 2).
- Produces: `ExtractionPane` and `ExtractionView` exported from `presentation/research/ExtractionPane.tsx` with unchanged signatures — `ExtractionPane({ projectId })`, `ExtractionView({ current, last })`. Task 4 changes their internals, not these.

- [ ] **Step 1: Move the three files with git**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system/frontend/src/presentation
git mv project/queue/ExtractionPane.tsx research/ExtractionPane.tsx
git mv project/queue/ExtractionPane.test.tsx research/ExtractionPane.test.tsx
git mv project/queue/ExtractionView.stories.tsx research/ExtractionView.stories.tsx
```

- [ ] **Step 2: Fix the relative imports in all three**

`ExtractionPane.tsx` moved up one directory. Its imports change:
- `from '../../common/primitives.tsx'` → `from '../common/primitives.tsx'`
- `from '../../shell/StreamProvider.tsx'` → `from '../shell/StreamProvider.tsx'`

Check every relative import in each of the three files; the `@app`, `@domain`, `@application` aliases are unaffected. `ExtractionPane.test.tsx` imports `StreamProvider` relatively — fix it, and fix its docstring, which reads "Mirrors `Workers.test.tsx`'s harness" and now names a deleted file. Replace that clause with a description of the harness rather than a pointer to one:

```
/** The pane, driven through the provider's fan-out rather than around it: a
 *  `QueryClientProvider` with retries off, a partial container, and a fake
 *  `EventStream` whose listener the test keeps so frames arrive the way the
 *  real socket delivers them.
 *
 *  This used to say it mirrored `Workers.test.tsx`, which no longer exists —
 *  the roster left the project page. Described rather than cross-referenced
 *  this time, so the next deletion does not strand it again. */
```

- [ ] **Step 3: Typecheck to confirm the move is complete**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. Errors here mean a missed import path.

- [ ] **Step 4: Run the moved tests before mounting**

Run: `cd frontend && npx vitest run src/presentation/research/ExtractionPane.test.tsx`
Expected: PASS, same count as before the move. The component is unmounted from the app at this point and its own tests render it directly, so they must still be green.

- [ ] **Step 5: Mount it as the first row of the command column**

In `GraphPane.tsx`, `GraphBrowser` takes a new prop. Add to the signature and prop types:

```tsx
  /** The extraction detail, or `null` when nothing has run and there is
   *  nothing to say. A node rather than a `projectId`, so this component keeps
   *  taking everything it needs from its caller — which is what lets the
   *  browser-mode test render it against a partial container. */
  extraction: ReactNode
```

and render it first inside the existing top-left column, above the search bar:

```tsx
      <div className="lay-region-float absolute top-3 left-3 flex w-[min(320px,calc(100%_-_20px))] flex-col gap-2">
        {/* First in the column, above the search box, because a running
            extraction outranks a search for the reader's attention and is the
            only row here that is time-bounded — everything else in this stack
            is a control or a standing notice.

            In this column rather than anywhere else on the stage: bottom-left
            is `GraphLegend` and the right is `GraphDetail`'s full-height
            column whenever an entity is selected, which is most of the time a
            reader is doing anything. This column is already where every
            transient panel on this pane lives. */}
        {extraction}
        <div className={`flex gap-2 p-2 ${PANEL}`}>
```

In the `GraphPane` component above, pass it:

```tsx
      extraction={<ExtractionPane projectId={projectId} />}
```

with the import `import { ExtractionPane } from './ExtractionPane.tsx'`.

- [ ] **Step 6: Update the pane's docstring to record the arrival**

Add to `GraphBrowser`'s docstring:

```
 * The extraction float is a prop rather than a mount, for the reason the rest
 * of this component's props are: the states worth looking at — a run in
 * flight over an empty canvas, a finished run over a drawn one — are reachable
 * without a live feed or a fake extraction repository.
```

- [ ] **Step 7: Typecheck and run the graph suites**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/presentation/research`
Expected: PASS. If a `GraphBrowser` test renders it without the new prop, TypeScript fails first — add `extraction={null}` to those call sites, which is a legal state and the one they were implicitly testing.

- [ ] **Step 8: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
Extraction moves to the tab it is about

"Reading into the graph" is the story of how the graph canvas got its nodes,
and until now the two could not be on screen together: the account was in the
QUEUE header and the drawing was a tab away. A reader could watch the canvas
fill with no account of what was filling it, and watch the pane count entities
with none of them drawn.

A float on the stage rather than a band above it, which is the pane's own
stated rule — "the canvas is the layer, and the controls sit on top of it
rather than in a column above it. Stacked, every search pushed the drawing
down." First in the existing top-left column, above the search bar: a running
extraction outranks a search box, and it is the only row there that ends.

Not the other three edges. Bottom-left is the legend; the right is
`GraphDetail`'s full-height column whenever an entity is selected.

Considered and rejected: a tenth MATERIAL tab. `MATERIAL_TABS` carries the
measurement — nine tabs, a 646px floor against 837px of tabs, eleven is where
the strip stops fitting — and calls the remaining headroom deliberately unspent
with the `course` split standing for it. A float spends none of it.

Costs: the column is capped at 320px, so the merge list is narrower than it
was (it was already capped and scrolled, so this narrows a bounded list); and
the Graph tab is lazy over ~60kB of react-force-graph-2d, so watching an ingest
now pulls a canvas. Paid, because the canvas is what the ingest is building.

A prop rather than a mount inside `GraphBrowser`, for the reason its other
props are props: the interesting states are reachable without a live feed.

Move only. What it looks like is the next commit.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 4: The float renders only when it has something to say

**Files:**
- Modify: `frontend/src/presentation/research/ExtractionPane.tsx` — `ExtractionView` returns `null` when both are null
- Modify: `frontend/src/presentation/research/GraphPane.tsx` — the stage's empty state gains a third branch
- Modify: `frontend/src/presentation/research/ExtractionPane.test.tsx`
- Test: `frontend/src/presentation/research/GraphPane.test.tsx` (find the real filename with `ls frontend/src/presentation/research/`)

**Interfaces:**
- Consumes: `ExtractionView({ current, last })` and `GraphBrowser`'s `extraction` prop from Task 3.
- Produces: `GraphBrowser` gains a second prop, `extracting: boolean` — true when a run is in flight. Task 5 does not use it; Task 7 measures the element it controls.

- [ ] **Step 1: Write the two failing tests**

In `ExtractionPane.test.tsx`:

```tsx
/** Nothing to say, so nothing said.
 *
 * This used to render a heading and "No extraction has run on this project
 * yet." — the same claim the graph stage makes two elements away, in the place
 * a reader is already looking. Two elements saying it is one too many, and an
 * always-present card with a negative sentence in it is what made this widget
 * read as dead.
 *
 * Proved red by returning the old `<section>` unconditionally. */
it('renders nothing at all when no extraction has ever run', () => {
  const { container } = render(<ExtractionView current={null} last={null} />)
  expect(container).toBeEmptyDOMElement()
})
```

In the graph pane's test file:

```tsx
/** The stage must not call a project empty while it is being filled.
 *
 * The canvas has no nodes until the first `graph` frame lands, so through the
 * whole of a first ingest this said "Nothing has been extracted into this
 * project yet" — to a reader watching an extraction run. A pre-existing defect,
 * invisible until the float was moved next to it and the two contradicted each
 * other on one screen.
 *
 * Proved red on 2026-08-27 by rendering with `extracting` ignored: the heading
 * came back as "This graph is empty". */
it('does not call the graph empty while an extraction is running', () => {
  renderBrowser({ view: emptyView, extracting: true })

  expect(screen.queryByText('This graph is empty')).not.toBeInTheDocument()
  expect(screen.getByText(/extracting/i)).toBeInTheDocument()
})
```

`renderBrowser` and `emptyView` are whatever that file already uses — read it and follow it rather than inventing helpers. If no such test file exists, create one modelled on the existing `GraphDetail` or `GraphLegend` tests in the same directory.

- [ ] **Step 2: Run both and confirm they fail**

Run: `cd frontend && npx vitest run src/presentation/research`
Expected: FAIL — the first with a non-empty container, the second finding "This graph is empty".

- [ ] **Step 3: Fold the empty state out of `ExtractionView`**

```tsx
export const ExtractionView = ({ current, last }: { current: Extraction | null; last: Extraction | null }) => {
  // Nothing has ever run, so this draws nothing. The claim it used to make —
  // "No extraction has run on this project yet." — is the same one the graph
  // stage's own empty state makes, and this now floats over that stage. Two
  // elements saying it is one too many; the stage keeps it, because that is
  // where a reader looking at an empty graph is already looking.
  if (!current && !last) return null

  return (
    <section className="extraction" aria-label="Knowledge extraction">
      {current ? <Running extraction={current} /> : null}
      {last ? <Last extraction={last} /> : null}
    </section>
  )
}
```

The `<h3>Reading into the graph</h3>` goes in Task 5, not here — Task 5 replaces it with the status line. Leave it for now.

- [ ] **Step 4: Give the stage its third branch**

In `GraphPane.tsx`, add `extracting: boolean` to `GraphBrowser`'s props with:

```tsx
  /** A run is in flight. The stage cannot tell "nothing here yet" from "being
   *  built right now" on its own — the canvas has no nodes until the first
   *  `graph` frame lands, which is minutes in. */
  extracting: boolean
```

and change the `view.nodes.length === 0` arm:

```tsx
        ) : view.nodes.length === 0 ? (
          <EmptyState
            heading={
              error
                ? 'The graph could not be read'
                : extracting
                  ? 'Extracting into this graph now'
                  : 'This graph is empty'
            }
            detail={
              error
                ? 'The project may still have entities; this page could not fetch them.'
                : extracting
                  ? 'The first entities will be drawn as they are found. The panel above follows the run.'
                  : 'Nothing has been extracted into this project yet. Ingest a document to start building it.'
            }
          />
```

In `GraphPane`, the value has to come from the extraction store. The pane currently builds `<ExtractionPane projectId={projectId} />` as an opaque node, which cannot report upward. Change `ExtractionPane` to accept an optional callback rather than hoisting its store — hoisting would mean two subscriptions or a prop-drilled store, and the store's whole design is one-per-project-per-mount:

```tsx
export const ExtractionPane = ({
  projectId,
  onRunning,
}: {
  projectId: ProjectId
  /** Called with whether a run is in flight, so the surface *behind* this
   *  float can stop calling the graph empty while it is being filled. A
   *  callback rather than hoisting the store: the store is built per project
   *  per mount by design, and lifting it would mean either two subscriptions
   *  or threading a zustand instance through a component whose other props are
   *  all plain data. */
  onRunning?: (running: boolean) => void
}) => {
```

with, after `const { current, last } = store()`:

```tsx
  useEffect(() => {
    onRunning?.(current !== null)
  }, [current, onRunning])
```

and in `GraphPane`:

```tsx
  const [extracting, setExtracting] = useState(false)
```
```tsx
      extracting={extracting}
      extraction={<ExtractionPane projectId={projectId} onRunning={setExtracting} />}
```

`setExtracting` is a stable setState identity, so the effect does not loop. Note that in a comment on the effect.

- [ ] **Step 5: Run both tests and confirm they pass**

Run: `cd frontend && npx vitest run src/presentation/research`
Expected: PASS. Add `extracting={false}` to any other `GraphBrowser` render sites TypeScript flags.

- [ ] **Step 6: Typecheck and run the whole frontend suite once**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: PASS. One run, not two concurrent ones.

- [ ] **Step 7: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
The float goes quiet, and the stage stops lying

Two fixes that are one fix, because the move put the two elements on one screen
and they contradicted each other.

The float rendered a heading and "No extraction has run on this project yet."
whenever nothing had — an always-present card whose only content was a negative
sentence, which is most of what made this widget read as dead. It is the same
claim the graph stage already makes, in the place a reader looking at an empty
graph is already looking. The float now renders nothing and the stage keeps the
sentence.

And the stage was wrong in the other direction. Its canvas has no nodes until
the first `graph` frame lands, minutes into an ingest, so through the whole of a
project's first extraction it told a reader watching that extraction that
nothing had been extracted. Pre-existing, and invisible while the two elements
were a tab apart. It takes a third branch now.

A callback rather than hoisting the extraction store into the pane: the store
is built per project per mount by design, and lifting it would mean either two
subscriptions or threading a zustand instance through a component whose other
props are all plain data.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 5: The float's drawing

**Files:**
- Modify: `frontend/src/presentation/research/ExtractionPane.tsx`
- Modify: `frontend/src/styles/course.css` — replace the `.extraction-*` block; delete the whole `workers` block
- Modify: `frontend/src/presentation/research/ExtractionView.stories.tsx`
- Test: `frontend/src/presentation/research/ExtractionPane.test.tsx`

**Interfaces:**
- Consumes: `ExtractionView` from Task 4, already folding to `null`.
- Produces: the class names `.extraction`, `.extraction-status`, `.extraction-dot`, `.extraction-trail`, `.extraction-seg`, `.extraction-seg-now`, `.extraction-line`, `.extraction-merge-list`, `.extraction-merge`, `.extraction-last`, `.extraction-summary`, `.extraction-failed`, `.extraction-failed-detail`. Task 7 measures `.extraction-seg-now` and `.extraction-dot`.

- [ ] **Step 1: Delete the dead worker styles first**

In `frontend/src/styles/course.css`, delete the entire `workers` block — the banner comment and every `.worker-*` rule (`.worker-head` through `.worker-ref`, including all five `.worker-dot-*`). Nothing writes those classes after Task 2.

Verify: `cd frontend && grep -rn "worker-" src/ --include='*.tsx' | grep -v WorkerDrawer` → expect no class-name hits.

Also check `course.css`'s own header comment, which enumerates the families it dresses (`- WorkerList (8 + worker-dot-${kind})` at line ~17). Remove that line; a manifest that lists a deleted family is worse than none.

- [ ] **Step 2: Write the failing tests**

```tsx
/** The stage in flight is marked by something other than a colour.
 *
 * jsdom cannot judge the colour — it applies no stylesheet — so this asserts
 * the hook a browser test measures against, and the browser suite asserts the
 * computed value. Both are needed: this one fails fast in CI if the attribute
 * is dropped, and that one fails if the attribute is present and inert.
 *
 * Proved red by rendering every segment with the same class. */
it('marks the stage in flight, and only that one', () => {
  render(<ExtractionView current={running(['storing', 'extracting'], 'extracting')} last={null} />)

  const marked = screen.getAllByRole('listitem').filter((li) => li.getAttribute('aria-current') === 'step')
  expect(marked).toHaveLength(1)
  expect(marked[0]).toHaveTextContent('extracting')
})

/** The status line says the stage, once, without a heading over it.
 *
 * The heading was "Reading into the graph" over a pane that is now a float on
 * the graph itself, where it restated its own container. Proved red by keeping
 * the `<h3>`. */
it('names the stage on one status line and renders no heading', () => {
  render(<ExtractionView current={running(['extracting'], 'extracting')} last={null} />)

  expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  expect(screen.getByText('extracting')).toBeInTheDocument()
})
```

`running(stages, now)` is a local builder you write in this file over the existing `Extraction` shape — `{ sourceId: 'notes', stage: now, stages: stages.map((stage) => ({ stage, detail: '' })), entities: null, relationships: null, domain: null, domainConfidence: null, index: null, total: null, modelCalls: null, merges: [], failed: false }`. Check `domain/knowledge/extraction.ts` for `emptyExtraction` and build on it if it fits.

- [ ] **Step 3: Run and confirm they fail**

Run: `cd frontend && npx vitest run src/presentation/research/ExtractionPane.test.tsx`
Expected: FAIL — a heading is present, and the segment assertion depends on markup that does not exist yet.

- [ ] **Step 4: Rewrite `Running`'s head as a status line and trail**

Replace the `<h3>` (in `ExtractionView`) and the `<ol className="extraction-stages">` (in `Running`) with:

```tsx
      <p className="extraction-status">
        <span className="extraction-dot" aria-hidden="true" />
        <span className="extraction-stage-name">{extraction.stage ?? 'starting'}</span>
        {extraction.total !== null ? (
          <span className="extraction-count">
            {extraction.index ?? 0}/{extraction.total}
          </span>
        ) : null}
      </p>

      {/* A trail, not a track: `Extraction.stages` is the stages *reached*,
          appended as frames arrive, and there is no declared pipeline to draw
          the rest of. `ExtractionStage` carries perception's two alongside
          extraction's five plus `failed`, which can follow any of them — so a
          fixed set of segments would draw a transcription as an extraction
          that had skipped four steps. It grows rather than fills, and it still
          measures nothing: a bar over stages of unequal length would be a
          made-up number, which is what the pill list this replaces was already
          right about. */}
      <ol className="extraction-trail">
        {extraction.stages.map((entry) => {
          const now = entry.stage === extraction.stage
          return (
            <li
              key={entry.stage}
              className={now ? 'extraction-seg extraction-seg-now' : 'extraction-seg'}
              aria-current={now ? 'step' : undefined}
            >
              {entry.stage}
            </li>
          )
        })}
      </ol>
```

Keep the `modelCalls` line, the `counted` line and the `consolidating` block exactly as they are — the counts were never the complaint. Remove the now-duplicated `consolidating {index}/{total}` line only if the status line already shows the same pair; if `total` is set outside `consolidating`, keep both and say why in a comment.

- [ ] **Step 5: Write the stylesheet**

Replace `course.css`'s `.extraction-title`, `.extraction-sub`, `.extraction-stages`, `.extraction-stage` and `.extraction-now` with:

```css
/* The float over the graph stage. Not indented behind a rule any more: it used
 * to hang under a roster row as its detail, and there is no row now — it sits
 * on the canvas as one of that pane's floating panels, so it carries their
 * border and fill rather than a left rule. */
.extraction {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg-panel);
  box-shadow: var(--shadow-1);
}

.extraction-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: var(--t-sm);
}

.extraction-stage-name {
  font-weight: 600;
}

/* Right-aligned by taking the slack, so the count sits on the far edge of a
 * line whose left is the stage name however long that name is. */
.extraction-count {
  margin-left: auto;
  font-family: var(--mono);
  font-size: var(--t-xs);
  color: var(--fg-dim);
  font-variant-numeric: tabular-nums;
}

/* `--k-tool` because that is the colour `.worker-dot-extraction` gave an
 * extraction in the roster and `agents.css` gives it in the dock. The roster is
 * gone; the agreement between the dock and this is the half worth keeping. */
.extraction-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: var(--k-tool);
  animation: extraction-pulse 2.4s ease-in-out infinite;
}

.extraction-trail {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  font-family: var(--mono);
  font-size: var(--t-xs);
}

/* Segments touch rather than sitting apart, which is the whole difference from
 * the pill list this replaces: a gap between them read as five unrelated tags,
 * and a reader had to know the order to see one. Only the first and last carry
 * a radius, so a wrapped row still reads as one run. */
.extraction-seg {
  color: var(--fg-faint);
  padding: 1px 6px;
  border: 1px solid var(--line-soft);
  border-right-width: 0;
}
.extraction-seg:first-child {
  border-radius: var(--radius) 0 0 var(--radius);
}
.extraction-seg:last-child {
  border-right-width: 1px;
  border-radius: 0 var(--radius) var(--radius) 0;
}

/* Carried by colour *and* by a border, so it survives being read by somebody
 * who cannot tell the two greys apart — the rule the pill list already had and
 * the one thing about it that was right. */
.extraction-seg-now {
  color: var(--accent);
  border-color: var(--accent-dim);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  animation: extraction-shimmer 2.4s ease-in-out infinite;
}

@keyframes extraction-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

@keyframes extraction-shimmer {
  0%,
  100% {
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  50% {
    background: color-mix(in srgb, var(--accent) 26%, transparent);
  }
}

/* Both animations off, not slowed. Neither carries information — the dot's
 * colour and the segment's border say everything the motion says — so there is
 * nothing to preserve at a reduced amplitude. */
@media (prefers-reduced-motion: reduce) {
  .extraction-dot,
  .extraction-seg-now {
    animation: none;
  }
}
```

Leave `.extraction-line`, `.extraction-merge-list`, `.extraction-merge`, `.extraction-last`, `.extraction-summary`, `.extraction-failed*` untouched.

**Check first whether these rules are inside an `@layer`** and whether anything in `tokens.css` targets the same elements unlayered. If `tokens.css` has an unlayered rule that would beat these, say so and stop rather than reaching for `!`.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd frontend && npx vitest run src/presentation/research/ExtractionPane.test.tsx`
Expected: PASS.

- [ ] **Step 7: Update the stories**

`ExtractionView.stories.tsx` has stories per state. The "nothing has run" story now renders nothing — either delete it or keep it with a docstring saying the empty render *is* the story. Add a story with three or more stages so the trail is visible, and one with `perceiving`/`perceived` so the perception path is on screen somewhere.

- [ ] **Step 8: Run the whole verify chain**

Run: `cd frontend && npm run verify`
Expected: PASS — this is the first point in the plan where prettier's Tailwind class sort and the bundle-size budget get a look at the change.

- [ ] **Step 9: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
One line, one trail, and no heading over either

The float was two headings, a wrapped row of unconnected pills and a paragraph,
in a box that was there whether or not anything was happening. It is a status
line — dot, stage, count — over a connected trail of the stages reached.

A trail rather than a progress track, and the first draft of the design was
wrong about this: `Extraction.stages` is the stages *reached*, appended as
frames arrive, not a declared pipeline. Drawing greyed future segments needs an
order, and there is no single order — `ExtractionStage` carries perception's
`perceiving`/`perceived` beside extraction's five, plus `failed`, which can
follow any of them. A fixed track would draw a transcription as an extraction
that had skipped four steps. So it grows rather than fills, and it still
measures nothing.

The heading went because the float now sits on the graph it was named after;
"Reading into the graph" over the graph restated its container.

The dot takes `--k-tool` because that is what the roster's extraction dot took
and what the dock still gives it. The roster is gone and the agreement with the
dock is the half worth keeping.

Both animations are off under `prefers-reduced-motion`, off rather than slowed:
neither carries information the colour and border do not already carry, so
there is nothing to preserve at a reduced amplitude.

`course.css` loses the whole `workers` block — eight rules and five dot
colours, written by nothing since the roster was deleted — and the line in its
own header manifest that listed them.

jsdom can see the `aria-current` and cannot see the colour. The browser suite
takes the second half; this commit's tests take the first, and the pair is
deliberate — the failure this shape has produced here before is an attribute
that is present and inert.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 6: `select`'s dead parameter

Small, and separate on purpose: it is a consequence of Task 2 rather than part of it, and a reviewer should be able to reject it without touching the move.

**Files:**
- Modify: `frontend/src/presentation/project/ProjectView.tsx:493-501`

**Interfaces:**
- Consumes: Task 2 removed the only caller passing `replace = false`.
- Produces: `select(next: Selection | null): void`.

- [ ] **Step 1: Confirm the parameter is dead**

Run:
```bash
cd frontend && grep -n "select(" src/presentation/project/ProjectView.tsx
```
Expected: every call site passes one argument. If any passes two, **stop and report** — the parameter is not dead and this task is void.

- [ ] **Step 2: Remove it**

```tsx
  /** Replaced, never pushed: a selection on this page is a glance, and forty
   *  glances in the back stack make the back button useless.
   *
   *  This took a `replace` flag until the roster left the page. Its one caller
   *  passing `false` was the worker row — opening a worker's transcript was a
   *  destination rather than a glance, and worth a back-button entry. The dock
   *  opens a worker in a drawer and writes no URL, so there is no longer a
   *  selection on this page that is a destination, and a flag with one legal
   *  value is a decision nobody is making. */
  const select = (next: Selection | null) => {
    navigate(projectHref(projectId, next), { replace: true })
  }
```

- [ ] **Step 3: Typecheck and run**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/presentation/project src/app`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
`select` loses a flag with one legal value

The `replace` parameter existed for exactly one caller: the roster's worker row
passed `false`, because opening a worker's transcript was a destination rather
than a glance and was worth a back-button entry. The roster is gone and the
dock's drawer writes no URL, so every selection this page makes is a glance.

Kept as a flag it would be a decision nobody is making, on a function whose
docstring would go on arguing a distinction the page no longer has.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 7: The measurements jsdom cannot take

**Files:**
- Create: `frontend/src/presentation/research/extraction-float.browser.test.tsx`
- Modify: `frontend/src/presentation/project/ProjectView.browser.test.tsx` — the QUEUE region's measurement changed

**Interfaces:**
- Consumes: the class names Task 5 produced, and `GraphBrowser`'s `extraction`/`extracting` props from Tasks 3 and 4.
- Produces: nothing.

- [ ] **Step 1: Read an existing browser test first**

Run: `cat frontend/src/presentation/common/shell-reached-dressing.browser.test.tsx`

Note the setup: `vitest.setup.browser.ts` is a *separate* file from `vitest.setup.ts` on purpose, because the jsdom setup pins `offsetWidth`/`offsetHeight` to constants and would blind a suite whose job is measuring. The viewport is set in `vite.config.ts` and a media query reads that, not the width of the wrapper a test renders into.

- [ ] **Step 2: Write the three measurements**

```tsx
/** The float does not sit on top of the search bar.
 *
 * It is the first row of a `flex-col` column, so this should be true by
 * construction — and "should be true by construction" is what the last
 * positioned element in this repository was also said to be. jsdom lays nothing
 * out, so nothing else in the suite can tell a float that stacks from one that
 * overlaps. Measured, not reasoned. */
it('the extraction float clears the search bar', async () => {
  render(<GraphBrowser {...props} extracting extraction={<ExtractionView current={running} last={null} />} />)

  const float = document.querySelector('.extraction')!.getBoundingClientRect()
  const search = screen.getByRole('searchbox').getBoundingClientRect()

  expect(float.bottom).toBeLessThanOrEqual(search.top)
})

/** And `GraphDetail`'s column does not reach it.
 *
 * The detail panel is `inset-y-3 right-3` and appears whenever an entity is
 * selected, which is most of the time a reader is doing anything — so this is
 * the collision the float's position was chosen to avoid, and the one worth
 * asserting rather than assuming. */
it('the extraction float clears the detail column', async () => {
  render(<GraphBrowser {...props} entity="e1" extracting extraction={<ExtractionView current={running} last={null} />} />)

  const float = document.querySelector('.extraction')!.getBoundingClientRect()
  const detail = document.querySelector('[class*="inset-y-3"]')!.getBoundingClientRect()

  expect(float.right).toBeLessThanOrEqual(detail.left)
})

/** The stage in flight computes a different colour from its neighbours.
 *
 * The `aria-current` assertion in the jsdom suite proves the attribute is
 * written; it cannot prove the rule keyed to it produces anything. This
 * repository has shipped exactly that — a chosen control drawing in the
 * unchosen colour past a fully green suite, caught by eye — so the computed
 * value is asserted here and the attribute there.
 *
 * Proved red by deleting `.extraction-seg-now`'s `color`. */
it('the stage in flight draws in a different colour', async () => {
  render(<ExtractionView current={running} last={null} />)

  const segments = [...document.querySelectorAll('.extraction-seg')]
  const now = document.querySelector('.extraction-seg-now')!
  const others = segments.filter((seg) => seg !== now)

  expect(others.length).toBeGreaterThan(0)
  for (const other of others) {
    expect(getComputedStyle(now).color).not.toBe(getComputedStyle(other).color)
  }
})
```

`props` and `running` are locals you build in this file. `GraphBrowser` takes everything it needs as props specifically so a browser test can render it against a partial container — its docstring says so; follow it.

- [ ] **Step 3: Run the browser suite**

Run: `cd frontend && npm run test:browser`
Expected: PASS. This is slow (a minute or so) and must not run beside another vitest process.

- [ ] **Step 4: Prove the colour test red before trusting it green**

Comment out `color: var(--accent);` in `.extraction-seg-now`, re-run `npm run test:browser`, confirm the third test fails, then restore it and re-run. **Do not use `git checkout` on the stylesheet to restore it** — that discards every other uncommitted edit in the file. Edit it back by hand.

- [ ] **Step 5: Fix `ProjectView.browser.test.tsx`**

That file measures the QUEUE region, whose content lost a card. Run it, read the failure, and update the expected measurement — do not relax the assertion into one that would pass at any height. If it asserts the header is not a scroller, that claim is unchanged and should stay exactly as it is.

Run: `cd frontend && npm run test:browser`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add -A frontend/src && git commit -F - <<'MSG'
The three assertions jsdom cannot make

A float's position, a neighbouring column's edge, and a computed colour. jsdom
lays nothing out and applies no stylesheet, so `scrollHeight` is 0 everywhere,
`getComputedStyle` returns only what an inline style said, and a rule that
matches nothing is indistinguishable from one that works.

The colour one is the one with a history. A chosen control drawing in the
unchosen colour shipped past a fully green suite here and was caught by eye,
because the attribute was written and the rule keyed to it was inert. The
attribute is asserted in the jsdom suite and the computed value here; either
alone admits that failure.

Proved red by deleting `.extraction-seg-now`'s `color` and restoring it by
hand rather than by checkout, which would have discarded the rest of the file.

`ProjectView.browser.test.tsx` measured a QUEUE region that has lost a card.
The number is updated rather than the assertion loosened — a measurement that
passes at any height measures nothing.

Outside CI by design, and so is this file. Run it when you touch a stylesheet
or a layout primitive; nothing forces you to.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

### Task 8: BACKLOG and the final gates

**Files:**
- Modify: `BACKLOG.md`

- [ ] **Step 1: File the backend survey**

Append to `BACKLOG.md`, following the file's existing entry format (read the last three entries and match them):

```markdown
## B160: `/api/projects/{id}/workers` may have no callers left

The console's last frontend consumer went with the project-page roster
(2026-08-27) — `WorkerRepository.on` is deleted and only `everywhere()`
remains. Whether the route itself is now dead is a Python-side question this
change did not open: it has its own gates, its own tests, and the answer may be
"an external caller depends on it", which nothing on the frontend can see.

The work is a survey, not a deletion: grep the route's handler for references,
check `tests/interfaces/` for what drives it, and decide. Filed rather than
guessed at, because deleting a route on the strength of one client's disuse is
how a public surface disappears.
```

Use the next free number — check the file rather than trusting B160.

- [ ] **Step 2: Run all four gates**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

Expected: PASS on all. `uv run pytest` is the fourth — **do not run it locally**; it is ~10 minutes here against ~2 on CI, and this change touches no Python. Push and let CI run it.

- [ ] **Step 3: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/remove-workflow-system
git add BACKLOG.md && git commit -F - <<'MSG'
BACKLOG: the workers route may have outlived its last caller

`WorkerRepository.on` is gone with the project-page roster, so the console asks
`/api/projects/{id}/workers` from nowhere. That is not the same as the route
being dead, and the difference is a Python-side survey with its own gates —
filed rather than settled from the client side, because "our client stopped
calling it" is weak evidence about a public surface.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016rsnC5kfREzG6M4ukh7Wd8
MSG
```

---

## Self-Review

**Spec coverage.** §1 → Tasks 2 and 6. §2 → Task 1. §3 → Task 3. §4 → Task 4. §5 → Task 5. §6 → Task 2 (the card is unwrapped there). "Deliberately not done" → Task 8 files the backend survey; no task adds a MATERIAL tab, restyles the dock, or touches `WorkerDrawer`. Verification items 1–8 → Task 4 (1, 2), Task 1 (3), Task 2 step 8 (4), Task 7 (5, 6), Task 5 step 5 + Task 7 (7), Task 2 step 2 (8).

**Placeholders.** Two steps deliberately say "read the existing file and follow it" rather than showing code — Task 1 step 1 (the hook-test harness) and Task 4 step 1 (`renderBrowser`). Both are cases where inventing a harness would be worse than copying the established one, and both name the exact file to copy from. Task 2 step 7 gives a grep instead of a path because the adapter's filename was not verified while planning; that is a lookup, not a decision.

**Type consistency.** `ROSTER_POLL_MS` (Task 1) is the only new exported value. `GraphBrowser` gains `extraction: ReactNode` (Task 3) then `extracting: boolean` (Task 4); both appear in every later render site. `ExtractionPane` gains `onRunning?: (running: boolean) => void` in Task 4 and keeps it. `select` drops its second parameter in Task 6 only. The class names Task 5 produces are the ones Task 7 queries: `.extraction`, `.extraction-seg`, `.extraction-seg-now`.

**Known gap, deliberately left to the executor.** Task 2 step 7 does not name the file implementing `WorkerRepository.on`, and Task 4's second test does not name the graph pane's test file. Both are one `ls`/`grep` away and neither changes the shape of the work; naming a path I had not opened would be the worse error.
