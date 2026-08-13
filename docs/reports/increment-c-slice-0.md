# Increment C, slice 0 — the page frame

Built on `increment-c-slice-0`. Two commits: the source change, and the
committed bundle on its own (`component-system-spec.md` §12's rule, so the real
diff is readable).

## What was built

**`presentation/project/use-project-panes.ts`** — `PROJECT_TRACKS` and the
group string `project`, shaped after `use-session-panes.ts` exactly: the tracks
and the group are the two halves of "this is the project's layout", and the
tracks cannot live in a component that renders from props.

**`presentation/project/ProjectView.tsx`** — one `Split id="project"` over three
`Pane`s (`queue`, `holder`, `material`), plus `regionOf`, a pure function total
over `Facet`.

- QUEUE: `Workers`, `ExtractionPane`, `RunPanel`, `AutonomyPanel`, `StageList`,
  `TopicList`.
- HOLDER: `SessionView`, or "Nothing is holding this project."
- MATERIAL: `Tabs` over `ArtifactList` / `Findings` / `DocumentList` /
  `GraphPane`.

**`app/App.tsx`** — `RESEARCH_FACETS` and the branch it fed are gone; the
`project` route renders `ProjectView` unconditionally.

**`presentation/course/use-course.ts`** — the broad `queryKeys.projects()`
invalidation removed.

Nothing was deleted. No stylesheet died. `check-deleted.mjs` was not touched and
reports "22 stylesheets stay frozen".

## Where the plan did not match the code

**1. There are three arms in `CurrentView`, not two.** The plan (and the brief)
say "delete the two-arm branch". `App.tsx:164` at the base also has
`if (selection?.facet === 'ask') return <AskView …/>`, ahead of the course
fallthrough and outside `RESEARCH_FACETS`. Rendering `ProjectView`
unconditionally would have deleted the ask page's only route. **The `ask` arm is
kept**, and the reason is argued in `regionOf`'s docstring: ask is one
conversation with no parts worth a URL and nothing to read it against, so it is
a view rather than a region. `regionOf` still maps `ask` (to `queue`) because
the function is total over `Facet` by design; the map is unreachable and says
so.

**2. "A single-row invalidation" does not exist and cannot be written here.**
The brief and §2.0 both call for replacing `queryKeys.projects()` with a
single-row invalidation. `/api/projects` answers the whole list as one response
and `queryKeys.projects()` is one cache entry for it — there is no per-project
key, and adding one means a per-project route, which is backend work outside
this slice. **So it was removed rather than narrowed**, and the reasoning is in
the comment at the call site.

The plan's cost estimate is also overstated in one direction and correct in
another, and both are worth recording. `useCourseRefresh` filters
`frame.kind === 'project'`, so it never fired "on every frame" — a token of a
turn is a `log` frame. And TanStack Query's `invalidateQueries` refetches
*active* observers only, so on a project page the entry usually had no reader at
all. The one real exposure: `use-running-agents.ts:77`, the agent dock, which is
in the shell on every route and observes `queryKeys.projects()` **while
expanded** — for project *names*, which a project frame does not move. So the
invalidation bought nothing and cost O(projects) of server-side fold whenever
the dock was open. Removing it is the right end of that trade.

What it drops, stated plainly: nothing refreshes the landing page's workflow and
stage columns while somebody else advances a stage. That was already true
everywhere except a course page left open behind an expanded dock, and the fix
belongs on the landing page rather than on this one.

**3. Component names in §2.0 do not resolve.** "QUEUE holds today's `StageRail`
and `TopicQueue`". `StageRail.tsx` exists but exports `Stage`, not `StageRail`;
the list component is `StageList` (`course/StageList.tsx:16`). `TopicQueue.tsx`
exports `TopicQueue` and `DispatchChip`, but the component that fetches and
renders the project's queue is `TopicList` (`research/TopicList.tsx:19`), which
is what `ResearchView` mounts. QUEUE holds `StageList` and `TopicList`.
Similarly "MATERIAL holds … `Artifacts`": `Artifacts.tsx` exports `Artifact` and
`CourseFileLink`; the list is `ArtifactList` (`course/ArtifactList.tsx:18`).

**4. The `file:line` citations that were checked all held.**
`use-session-panes.ts:7,21` (group and tracks), `use-course.ts:104` (the
invalidation, exactly there), `App.tsx`'s `RESEARCH_FACETS` comment,
`routes.ts:67`'s `FACETS`, `split-tracks.ts`'s `>=` note. §5.1's inventory of
`responsive.css` also held for the two entries this slice needed to know about
(`:40,55` are `[data-split='session']`, inside the 821–1180 media query).

**5. QUEUE carries more than the plan gives it, deliberately.** §2.0 names only
the stage rail and the topic queue. Taken literally, that leaves `RunPanel`,
`ExtractionPane`, `AutonomyPanel` and `Workers` with no renderer anywhere for
the length of the slice — a project would lose the only control that starts a
run and the only place that says an extraction is working. That is a functional
regression rather than an ugly page, and "the page is ugly and it works" is the
slice's own standard. They come along in the order the course page had them;
slice 1 re-parents them into a real `QueueHeader`.

## The nesting question, and the evidence

**`Split` inside `Split` works, and the mechanism is why.** `SessionView` mounts
inside HOLDER carrying its own `Split id="session"`.

- **No crosstalk.** `Split.tsx:34,89` provides `SplitContext`; `Pane.tsx:97`
  consumes it with `useContext`, which resolves to the *nearest* provider. The
  three session panes read the session split, the three region panes read the
  project split. There is no registry and no ids-in-a-flat-namespace to collide.
- **Two persistence groups, independent.** `useSplitPanes(group)`
  (`use-split-panes.ts:28`) closes over its group string; `project` and
  `session` are different keys under `rt.collapsedPanes.<group>`.
- **Two last-open rules, independent.** `toggleCollapsed`
  (`split-tracks.ts:80`) takes `tracks` as an argument, so each `Split` refuses
  against its own three.
- **Two `grid-template-columns`, on two different elements.** `Split.tsx:99`
  writes the inline style on its own `.lay-split`, and there are two such
  elements. Neither can outrank the other. `responsive.css:36,40,49,52,55`'s
  `[data-split='session']` rules still match the inner one, because the
  attribute is on the element those selectors name.
- **One thing that had to be got right:** the HOLDER pane is `scroll="regions"`.
  `layout.css:234` makes such a body `display: flex; flex-direction: column;
  overflow: hidden`, which is what lets the nested split's `flex: 1 1 auto`
  (`layout.css:124`) take the height. With the default `scroll="body"` the body
  is an `overflow: auto` block and the result is a box scrolling around a
  transcript that already scrolls — `Pane.tsx`'s own documented failure.

So the answer is: nesting does not need a workaround, and the slice order does
not have to change. **What it costs is cosmetic and real** — a pane header
inside a pane header, and a session heading inside a pane that already has a
label. Slice 2 removes it by lifting the inner `Split` out, as §2.2 plans.

**The limit of this evidence.** All of the above is read from source and
confirmed by the jsdom suite passing. jsdom lays nothing out, so *how the nested
grid actually sizes* is not verified by anything I ran — see "not verified"
below.

## Pane preferences dropped

The new group is `project`, so `rt.collapsedPanes.project` starts empty for
everyone. Nothing is migrated and nothing is deleted:

- `rt.collapsedPanes.course` (`stages`, `artifacts`) — no longer read, because
  `CourseView` is no longer rendered by any route. The key is left on disk.
- `rt.collapsedPanes.research` (`seeding`, `topics`, `documents`) — same.
- `rt.collapsedPanes.session` — **survives**, and is now read in two places: the
  standalone `#/s/` route and the nested split inside HOLDER. A reader who
  folded the timeline on a standalone transcript meets it folded inside the
  project page too. That is arguably right and was not designed; it is a
  consequence of `SessionView` keeping its group.

A reader who had folded the course page's stage rail meets the project page
fully open, once. §3.2's reasoning applies and `preference-store.ts:3-5` records
the same trade being taken before.

## Commands run, with results

| Command | Result |
|---|---|
| `npx tsc --noEmit` | clean |
| `npx vitest run --project app src/presentation/project/ProjectView.test.tsx src/app/App.test.tsx` | 12 passed |
| `cd frontend && npm run verify` | **passed end to end** on the second run |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 230 files already formatted |

`npm run verify`'s numbers: 1008 tests across 102 files; bundle 283.5 kB of
512 kB total, `app` 70.3 kB of 80 kB; `check-deleted` 30 rules hold and 22
stylesheets frozen; `check-tailwind` 46 utilities, all emitting a rule.

**One failure, and it did not reproduce.** The first `verify` run failed
`App.test.tsx > opens a dialog, which needs the overlay host the shell mounts`
with a 5 s timeout. Re-run alone: 9 passed. Re-run as the whole chain: passed.
That is CLAUDE.md's bar — two consecutive identical results — and the direction
fits load rather than breakage: the test exercises the landing page's row menu
on hash `''`, which this change does not touch.

## What I could not verify

- **Anything that is a measurement.** `PROJECT_TRACKS`'s three numbers are
  reasoned, not measured, and the file says so in place. §6.3 of the plan names
  this as browser-suite work and I agree; measuring the widths of three regions
  currently holding other views' markup would be measuring the wrong page.
- **I did not run `npm run test:browser`.** CLAUDE.md's rule is to run it when
  you touch a stylesheet, a layout primitive, or anything whose correctness is a
  computed style. This slice touches no stylesheet and no primitive — but it
  does compose a `Split` inside a `Split` for the first time, which is a layout
  claim jsdom cannot judge. **This is the honest gap in the verification** and
  the one thing I would want looked at before this is called finished; §5.3 asks
  every slice to run it.
- **No focus-ring check.** §5.2 warns that a full-width focusable row in an
  unpadded pane scroller loses its entire ring. This slice adds three such
  scrollers, but every row inside them is a row that already existed in a pane
  scroller, so the geometry is unchanged rather than new. Not measured.
- **`app.py:list_projects` folding one aggregate per project** is the plan's
  claim, taken from the proposal, and I did not re-verify it. The client-side
  half of the argument I did verify, and it is above.

## Anomaly worth reporting

**HEAD moved under this worktree while I was working, and the source commit was
not made by me.** I started at `29ad8d7`. During the run, `54f10a3` ("Four shell
components were dressed by stylesheets about to be deleted (#169)", author
*Tyler* Evans) landed, and then my working tree was committed as `5160732` at
13:09:36 by something other than this agent — with a message I did not write.
The content is my change and the tree matches, and `npm run verify` ran at 13:03
with `54f10a3` already present, so the verified state is the committed state.
CLAUDE.md says to stop and say so rather than reconcile, so this is said rather
than reconciled. Only the bundle commit (`2dcbeb1`) is mine.

Also untracked in this worktree and not mine: `.claude/tackline/memory/sessions/`
and `docs/superpowers/plans/projectlist-split-plan.md`.
