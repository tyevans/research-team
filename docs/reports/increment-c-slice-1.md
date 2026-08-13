# Increment C, slice 1 — the `course.css` sweep, and why the file cannot die here

**Two writers produced this slice, and the sweep below stopped rather than
reconcile them.** Both were working the same brief in one worktree; the
concurrency note at the end is the contemporaneous record, kept because it is
the evidence that nothing was clobbered. The work was reviewed file by file
afterwards, the two halves turned out to be complementary rather than
conflicting, and one disagreement between them was settled against the writer
who acted — see "The `CoursePanes` disagreement".

## The headline

**`course.css` cannot be deleted in slice 1, and the plan's §2.1 is wrong about
why it thought it could.** The sweep found not one or two live selectors but
roughly nine tenths of the file still reached, from six components that outlive
both views this slice deletes.

## What the sweep enumerated, and how

Inverted, as the brief asked — walked out from the shell and from `ProjectView`
to what they mount, then asked what each component *writes*, rather than
grepping class names out of the stylesheet. The grep direction would have got
four of these wrong: `rail-${status}` (`StageRail.tsx:45`), `worker-dot-${kind}`
(`WorkerList.tsx:110`), `finding-${severity}` (`Findings.tsx:20`) and
`chip-${tone}` (`primitives.tsx`) are all composed and have no literal to find.

`course.css` declares 98 class names. The components that render after slice 1
and the selectors they still reach:

| Component | Where it renders after slice 1 | `course.css` names it reaches |
|---|---|---|
| `StageList` / `StageRail` | QUEUE | `.rail`, `.rail-item`, `.rail-row`, `.rail-dot`, `.rail-done/current/upcoming/unknown`, `.rail-index`, `.rail-name`, `.rail-count`, `.rail-count-none`, `.rail-short`, `.rail-detail`, `.rail-meta-row`, `.rail-gate`, `.rail-report`, `.rail-outputs` |
| `ArtifactList` / `Artifacts` | MATERIAL (`artifact` tab) | `.artifacts`, `.artifact`, `.artifact-top/name/type/card/note/prov`, `.prov-src`, `.chip-present`, `.chip-missing`, `.chip-inferred`, `.chip-bad` |
| `Findings` | MATERIAL (`finding` tab) | `.findings`, `.findings-head`, `.finding`, `.finding-invariant/blocking/advisory/human_gate/critic_gate`, `.finding-check`, `.finding-msg`, `.finding-fix` |
| `Workers` / `WorkerList` | QUEUE header | `.worker-head/title/sub/list/row/child/dot/kind/detail/ref`, `.worker-dot-run/turn/extraction/stage` |
| `ExtractionPane` | QUEUE header | `.extraction`, `.extraction-title/sub/stages/stage/now/line/merge-list/merge/last/summary/failed/failed-detail` |
| `AutonomyPanel` | QUEUE header | `.autonomy-panel/head/title/sub/tally/list/row/row-gate/field/tool/tool-name/levels/level/meaning`, `.autonomy-warn`, `.autonomy-error`, `.autonomy-disclosure[open] > …` |

`StageRail` also renders `Chip` with the tones `done`, `current`, `upcoming`,
`unknown`, and `Artifacts` with `present`/`missing`/`inferred`/`bad` — the eight
`.chip-*` rules the plan said "die with the slice". They do not; both components
survive.

**What genuinely dies with `CourseView` and `ResearchView`**, and it is a short
list: `.view-course`, `.course-findings`, and the three combinators
`.lay-split[data-split='course'] > .lay-pane`, `> .lay-pane > .lay-pane-body`
and `> .lay-pane.is-collapsed` (`course.css:37,48,55`). Five selectors of 98.

## Where the plan did not match the code

1. **§2.1's "stylesheets that die: `course.css`" is wrong, and its own slice
   contents say so.** §2.1 lists the deletions as `CourseView`, `StageRail`,
   `StageList` and `TopicList` — but it also puts `ArtifactList`, `Findings`,
   `Workers`, `ExtractionPane` and `AutonomyPanel` in MATERIAL and in the queue
   header, alive. Those five alone hold about 60 of the file's 98 names. Even
   the *full* §2.1, with a real `QueueList` replacing the rail, leaves the
   majority of `course.css` reached. Under the brief's narrower slice 1 — a
   header re-parenting, not a list rewrite — `StageList` survives too and the
   rail rules go with it.

2. **§2.1's two named passengers are both already handled, and it names the
   wrong ones as the risk.** PR #169 moved `.chip-invariant/blocking/advisory/
   human_gate/critic_gate` to `SEVERITY_DRESS` in `GateReview.tsx`; `course.css`
   :339 records the move. `.autonomy-warn`/`.autonomy-error` are utilities on
   `AutonomyAllowAll.tsx`. The passengers that actually block the deletion are
   the ones §2.1 lists as dying.

3. **Confirmed as the brief asked: `.chip-fail` is in `tree.css:378`**, not
   `course.css`, and `tree.css` survives this slice. `GateReview.tsx:40` renders
   `<Chip tone="fail">blocked</Chip>`. That coupling is real but is not this
   slice's problem.

4. **`SeedPanel` is orphaned by deleting `ResearchView`, and no document
   mentions it.** `ResearchView.tsx:88` is its only mount. Deleting that view
   without re-parenting it deletes the only way to seed a project — the same
   functional-regression shape slice 0 caught with `RunPanel`. It belongs in the
   queue header (§2.1 says "the seed control", so the plan wants it there; it
   just does not say that deleting `ResearchView` is what forces the issue).

5. **`responsive.css` holds six rules that go void this slice, in a file the
   slice does not touch** — §5.1's hazard, live: `:84`, `:87`, `:90`, `:116`
   (`[data-split='course']`), and `:158`, `:163`, `:168`, `:171`, `:180`
   (`.view-research`, `.research-workbench`, `.research-rail`). `ResearchView`
   is the only writer of the research three, so all of them stop matching the
   moment these two views go, at viewports nobody's default window is at.
   `research.css:68,132`'s `.research-rail > [data-pane='seeding']` pair goes
   void the same way.

6. **The `research` pane-preference group dies now, not in slice 3.** §3.2 puts
   `rt.collapsedPanes.research` with slice 3, but `useResearchPanes` has one
   caller and it is `ResearchView`.

## What "delete anything they alone reached" covers

`CourseView.tsx` + `.test.tsx`; `ResearchView.tsx`; `use-research-panes.ts` +
`.test.tsx`; `COURSE_TRACKS` and `COURSE_GROUP` in `use-course.ts`;
`.view-course` and `.course-findings` in `course.css`; the three
`[data-split='course']` combinators; the nine `responsive.css` rules above.

`CoursePanes.stories.tsx` / `.test.tsx` reach `COURSE_TRACKS` but are *not*
about `CourseView` — they are the only coverage of `StageList` and
`ArtifactList` rendering real content without a container. Deleting them loses
five real assertions to remove one import. They should keep their tests and
declare their two tracks locally, as a workbench for the pair rather than as the
page that is gone.

## What I did not do, and why

- **Did not delete `course.css`.** Not a workaround and not a deferral: doing it
  would mean porting ~700 lines onto six components that slices 2 and 3 rewrite
  anyway, which is precisely the work the standing policy ("deleted, never
  ported", `check-deleted.mjs`'s `STYLESHEETS` docstring) was written to
  prevent. The earliest slice `course.css` can honestly die in is the one that
  rewrites the rail, the artifact list and the findings list — slice 3 by the
  plan's own division, or a slice 1 widened to include `QueueList`.
- **Did not touch `STYLESHEETS`.** It stays at 22. The array is only edited in
  the commit that removes the file, which is the mechanism working.

## The `CoursePanes` disagreement

The sweep argued for keeping `CoursePanes.stories.tsx` and `.test.tsx`; the
other writer deleted them. Settled by keeping them, and the reason is the one
the sweep gave: they are the only place `StageList` and `ArtifactList` render
real content side by side with no `QueryClientProvider`, which is a property of
*those two components* and not of the page that mounted them. They were deleted
because they imported `COURSE_TRACKS`, which dies here — so they declare the two
tracks locally now, with the same numbers, and `.view-course` comes off the
wrapper because that rule is gone. Five assertions kept at the cost of one
constant.

## Verification

`npm run verify` green. Bundle **283.3 kB** of 512 gzipped, against 283.5 kB
before the slice — a net 0.2 kB down, which is roughly nothing and is the
honest number: two whole views left, and their contents did not.
`check-deleted` holds at 33 rules (three added here) with the 22 stylesheets
still frozen. `npm run test:browser` green at 14 files / 42 tests.

Two things worth recording rather than smoothing over:

- **`course.css` was left syntactically broken** by the deletion of
  `.course-findings`, which took the *next* rule's selector line with it and
  left `.findings-head`'s body dangling after a `}`. Prettier caught it on the
  first `verify`; nothing else would have, because a stylesheet that fails to
  parse loses everything after the error and `.findings` sits directly below.
  Fixed by restoring the selector — `.findings-head` is live, `Findings` writes
  it.
- **The jsdom suite failed differently on two consecutive full runs** — five
  tests the first time, four unrelated ones the second, every one a 5-second
  timeout, and each passing alone. That is CLAUDE.md's load signature and not a
  regression; two peer sessions were working this machine. Called as load
  rather than investigated, on the evidence that the failing set moved.

The claim-4 browser test below is the one place this slice measures itself, and
its first assertion had to be thrown away — see the test's own docstring. The
short version: "nothing is clipped" passes whether or not the header is a
scroller, because the fixture is not tall enough to overflow. It asserts the
computed `overflow-y` and `flex-grow` now, which is a thing jsdom cannot answer
at all.

## What is still not measured

Focus rings against §5.2's geometry. The plan flags them and three panes now
reproduce the shape it warns about; `QueueHeader`'s docstring argues its way out
for the header specifically (it is not a scroller, so nothing in it can be
clipped by one) but the rows in the list below it are exactly the case §5.2
describes, and they are unchanged from where they already lived. Slice 2 or 3
rewrites that markup and should measure it then rather than inheriting the
argument.

## Concurrency — the contemporaneous record

At 13:27:05 local, `frontend/src/presentation/project/ProjectView.tsx` was
rewritten by something other than this agent, to import
`./queue/QueueHeader.tsx` — a file that did not exist at that moment. At
13:27:11 the index gained seven staged deletions (`CourseView.tsx` + test,
`CoursePanes.stories/test`, `ResearchView.tsx`, `use-research-panes.ts` +
test) and `use-course.ts` lost `COURSE_TRACKS`/`COURSE_GROUP`. None of that was
mine. I wrote `queue/QueueHeader.tsx` at 13:28:15; the directory's mtime is that
same second, so it was created rather than overwritten and no other agent's file
was clobbered.

HEAD is where the brief put it (`190bff1`) and has not moved.

CLAUDE.md: "If HEAD is somewhere you did not put it, or files you did not touch
show as modified: **stop and say so** rather than reconciling it. The
reconciliation is where the work gets lost." So this is said rather than
reconciled, and nothing is committed.

**What happened next**, added afterwards: the tree sat untouched for seven hours
with both writers stopped and HEAD still where it was put, so nothing was lost
and the rule did its job. It was then reviewed file by file — every diff read
against what it claimed — rather than accepted on either writer's word. Three
claims turned out not to hold: `QueueHeader`'s docstring said three duplicate
card rules were deleted and they were (a stale grep of mine said otherwise
first), `check-deleted.mjs` recorded `CoursePanes` as deleted when the decision
went the other way, and `course.css` did not parse. All three are fixed above.
The lesson is the cheap one: two agents on one brief in one worktree is not
parallelism, it is a merge nobody planned, and the only reason it cost an
afternoon rather than the work is that the second writer stopped and wrote this
section instead of reconciling.
