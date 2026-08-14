# Increment C audit 2 — what QUEUE and MATERIAL actually contain

Read at `9fa6c7b` (merge of #177), against `docs/increment-c-plan.md` (written at
`f87443b`) and `docs/unified-ui-proposal.md` §3.3, §4.2, §4.3, §4.5. **Nothing
was run** — no `pytest`, no `npm run verify`, no browser suite, no build. Every
claim below is read off code or off a stylesheet; §"what I could not check"
names what that leaves open.

Method for the stylesheet sections: I enumerated the class names each stylesheet
declares, then walked out from what renders today to see which are reached,
rather than grepping the stylesheet for its own names. The four composed
families the brief named are the reason — none of them has a literal to find.

---

## Findings, most expensive first

### 1. Slice 1 shipped its header and **not its queue**, and §2.1 still reads as though it did

This is the finding with the most downstream cost, because every later slice and
the proposal's §3.3 are written against a QUEUE that exists and does not.

§2.1 promises "a `QueueList` over one row union with five sources (topic, stage,
session, dispatch, running worker), one filter across all kinds, and the four
slices rewritten as `All` / `Needs you` / `Running` / `Done`".

What is in the QUEUE pane today (`ProjectView.tsx:246-284`) is, in order:
`QueueHeader`, then `StageList`, then `TopicList`. Three sibling components, two
lists, no union, no shared filter, no shared slices. `presentation/project/queue/`
contains exactly one file, `QueueHeader.tsx`. The only filter and the only focus
slices on the page are `TopicQueue`'s own, over topics only — `.topic-search`,
`.topic-focus`, `.topic-focus-tab`, `.topic-focus-count` in `research.css`,
written from `TopicQueue.tsx`, and still labelled `All` / `Needs you` / `Live` /
`Closed` rather than the four the plan renames them to. Sessions and dispatches
are not rows at all; a running worker is a roster line inside `QueueHeader`
(`QueueHeader.tsx:108`), which is above the list rather than in it.

`QueueHeader.tsx:49` is candid about the file's own scope — "`course.css` itself
does **not** die here, which the plan's §2.1 expected it to" — but nothing in the
plan records that the *list* half of slice 1 is outstanding. Read literally,
§2.2 and §2.3 both begin from a QUEUE that was built.

**Replacement sentence for §2.1**, to be added under its own heading rather than
edited into the past tense:

> **Shipped in slice 1: the header only.** `QueueHeader` exists and holds the
> ask link, the roster, the extraction detail, the run panel, the seed control
> and the autonomy panel. The row union, the cross-kind filter and the four
> renamed slices were **not** built; QUEUE is `QueueHeader` over `StageList`
> over `TopicList`, three components with one filter between them that reaches
> only topics. This is the remaining work of slice 1 and it should be sequenced
> before slice 3, because the ordering function §6.1 wants to keep separable has
> no list to be separable from yet.

Consequence for §6 open question 1 (rank across kinds vs group by kind): it is
not merely unresolved, it is **unstarted**. The cheap resolution the plan
proposes — build the union, make the ordering a pure exported function — is
still available at full price.

### 2. `research.css` does not die in slice 3, for the same reason `course.css` did not die in slice 1

§2.3: "**Stylesheets that die: `research.css`, effectively whole.** Of its 86
class names, 79 are exclusive to `presentation/research/*`."

Both halves are now wrong, and the second is wrong in a way that hides the first.

`research.css` is 848 lines declaring **81** class names (the `.view-head`,
`.lay-pane*`, `.research-rail` and `.research-workbench` selectors §2.3 lists as
the seven survivors were deleted in slice 1, `c1fbc6c`). **All 81 are still
reached.** "Exclusive to `presentation/research/*`" is true and is not the test
that matters — the test is which *region* the reaching component now lives in,
and slice 3 only rewrites MATERIAL:

| Family | Names | Reached from | Region | Dies in slice 3? |
|---|---|---|---|---|
| `graph-*` | 36 | `GraphPane`, `GraphCanvas`, `GraphDetail`, `GraphLegend` | MATERIAL `entity` | yes |
| `document-*` | 13 | `DocumentBrowser`, `DocumentReader` | MATERIAL `doc` | yes |
| `topic-browser`, `topic-list`, `topic-search`, `topic-focus*`, `topic-dispatch*`, `is-on` | 12 | `TopicQueue.tsx` | **QUEUE** | **no** |
| `seed-*` | 5 | `SeedForm.tsx` | **QUEUE header** | **no** |
| `sub-question*`, `sub-questions` | 8 | `SubQuestions.tsx` | the topic dialog | **no** |
| `topic-status-*`, `topic-section-heading`, `topic-documents-section` | 7 | `TopicStatusDialog.tsx` | the topic dialog | **no** |

So **28 of 81 names — a third of the file — are outside slice 3's blast radius**,
and `research.css` cannot leave `STYLESHEETS`. This is the third consecutive
slice for which the plan predicted a stylesheet death that a re-parenting cannot
deliver.

**Replacement sentence for §2.3:**

> **Stylesheets that die: none, and `research.css` in particular does not.** Of
> its 81 class names, 49 belong to the graph and corpus components this slice
> rewrites; the remaining 32 belong to `TopicQueue` (now a QUEUE tenant),
> `SeedForm` (now in `QueueHeader`) and the topic dialog, none of which this
> slice touches. `research.css` leaves `STYLESHEETS` in the slice that rewrites
> the queue list and the topic surface — which is the unfinished half of slice 1
> plus the `topic` facet, not this one. Deleting the graph and corpus rules from
> inside the file is available and is worth doing in this slice; deleting the
> file is not.

The same correction, already paid for: `course.css` is 740 lines / 90 class
names, and **all 90 are still reached** — 70 literally, and 20 through the four
composed families (`rail-${status}` `StageRail.tsx:45`, `worker-dot-${kind}`
`WorkerList.tsx:110`, `finding-${severity}` `Findings.tsx:20`, `chip-${tone}`
`primitives.tsx:73`). A literal-name grep reports those twenty as unused; they
are not.

### 3. Four of the eight facets carry an id the page reads and then ignores

`FACETS` (`routes.ts:67-80`) has eight selecting facets. `regionOf`
(`ProjectView.tsx:66-95`) is total over them, so every facet reaches a region —
which is the property slice 0 shipped and it holds. But reaching a region is not
the same as being *selected*, and only four facets are actually consumed:

| Facet | Id consumed? | Where |
|---|---|---|
| `session` | yes | `ProjectView.tsx:168,174` |
| `file` | yes | `:176-181` → `WorkspacePanel` `:423` |
| `stage` | yes | `:167` → `StageList` `:274-280` |
| `entity` | yes | `:441` → `GraphPane` |
| `topic` | **no** | `TopicList` takes only `projectId` (`TopicList.tsx:19`) |
| `doc` | **no** | `DocumentList` takes only `projectId` (`DocumentList.tsx:15`) |
| `artifact` | **no** | `ArtifactList` takes only `course` (`ArtifactList.tsx:18`) |
| `finding` | **no** | `Findings` takes only `course` |

So `#/p/x/artifact/<id>`, `#/p/x/doc/<sid>` and `#/p/x/finding/<id>` open the
right MATERIAL tab and highlight nothing, and `#/p/x/topic/<tid>` lands on the
project page with the topic queue in its default state. §3.1's table row —
"`#/p/<id>/file/…`, `/artifact/…`, `/finding/…` … **parse and render nothing
about the facet** → MATERIAL `workspace` / `artifacts` / `findings`" — is
**half true**: `file` was fixed in slice 2, `artifact` and `finding` were not,
and `topic` and `doc` have the same defect and are not in the table at all.

This is the concrete content of §2.3's "one selection model". The plan says the
slice "writes no new href builder", which is true and is the easy half; the
reading half is unwritten for four facets and the plan does not say so.

**Add to §2.3:**

> **What "one selection model" actually costs here.** `projectHref` already
> builds all eight facets, but only four are *read*: `session`, `file`, `stage`
> and `entity`. `topic`, `doc`, `artifact` and `finding` parse, choose a region,
> and are then dropped — the id never reaches a component. This slice owes each
> of its facets a selected state and an empty/`not found` state for an id that
> no longer exists, which is four selection models' worth of work however few
> readers it ends up sharing.

### 4. Features with no home on the new page

The three regressions already shipped (`RunPanel`, `SeedPanel`, the ask page's
inbound links) were all of this shape. Walking `features-course-view.md` and
`features-research-view.md` against what renders, these are the ones left:

**C-F1 — the preset's name. Gone, with no replacement.** `CourseView.tsx:63`
rendered `course.data?.preset.name ?? 'Course'` as the page title. `preset.name`
is now read in exactly one place in `presentation/`, `NewProjectForm.tsx:122` —
the create-a-project dropdown. **A reader on a project page cannot see which
workflow the project is running.** The breadcrumb shows the project's own name
(`Breadcrumbs.tsx:35`), which is a different fact.

**C-F2 — the position subtitle, and the `position === null` sentence. Gone.**
`Stage N of M · <presetId> v<version>` was `CourseView.tsx:227-232`. `course.position`
is now read nowhere in `presentation/` (the only `.position` hit is
`TopicQueue.tsx:61`, a dispatch queue ordinal). The lost half that matters is the
other branch: *"This project's recorded stage is not part of `<presetId>`, so its
position is unknown."* That sentence was the **only** surface that told a reader
their project sits at a stage the installed preset has dropped —
`features-course-view.md` F2 records it as a real state that `composition.py`
tolerates, and D12 records that there is no way to correct it. The proposal's
§4.3 lists C-F1/C-F2 as going to "project page header, QUEUE header" with
"`position === null` sentence kept". Neither arrived.

**C-F56 — the artifact pane's `N of M written` count. Gone.** `CourseView.tsx`
gave the artifacts `Pane` a `meta` of
`${writtenCount(allArtifacts(course))} of ${allArtifacts(course).length} written`.
The MATERIAL tab is labelled `Artifacts` and carries no count
(`ProjectView.tsx:120`); `writtenCount` now survives only per-stage inside
`StageRail.tsx:24`. The QUEUE pane kept its analogous meta
(`ProjectView.tsx:249-253`), so this reads as an oversight rather than a
decision. **A `Tabs` label cannot carry a count the way a `Pane` header could,
which is the honest reason it went — and is an argument in §5 below.**

**C-F4 — "Open holding session". Gone, and defensibly so, but undocumented.**
The proposal's §4.3 explicitly drops it ("HOLDER *is* the holding session"). That
is right for reading the transcript. What it also removes is the only door from a
project to the standalone `#/s/<id>` route, which the plan's §2.2 deliberately
keeps alive as a three-pane page. Today the standalone route is reachable from
the landing page, from `WorkerDrawer.tsx:97`, from `RunPanel.tsx:193` and from
`Artifacts.tsx:161` (a file link), but **not from the project page for the
project's own holding session**. Not a regression against the proposal; worth one
sentence somewhere, because "HOLDER is the session" and "`#/s/` stays top-level
because a transcript read alone is still three panes" are both true and in
tension.

**R-F2.2 — `SeedingRun.reply`. Still unrendered.** `domain/research/seeding.ts:18`
carries it; no component reads it. The proposal's §4.2 marks it **surfaced** in
QUEUE. Not a regression (it was unreachable before too), but it is one of the
cheap unlocks the proposal counted, and slice 1 moved `SeedPanel` without taking
it.

**Not regressions, checked and cleared:**

- `RailPane`'s unmount-on-fold (R-F1.1) is preserved by `Tabs`: Radix unmounts
  the closed panel (`Tabs.tsx:96`), so `DocumentList`'s virtualizer still never
  measures a zero-height scroller. This was the specific reason `RailPane`
  unmounted rather than hid, and the replacement happens to keep it.
- `WorkerDrawer` (C-F39–F45) survives via `AgentWidget.tsx:185`, as §2.2 says it
  should.
- The topic dialog, `SubQuestions` and `TopicDocuments` (R-F4.1–F4.4) all still
  render, from `TopicList.tsx:36-40`.
- C-D7 (findings vanishing when empty) is fixed by `ProjectFindings`
  (`ProjectView.tsx:477-485`).
- The `chip-${tone}` gate-severity passenger §2.1 warns about was rescued before
  the file was touched — `course.css:325-326` is now a comment recording where
  the five rules went.

### 5. §2.3's division is the wrong shape now, because MATERIAL already has five tabs

§2.3 is written as "MATERIAL's remaining five facets: `artifact`, `doc`
(corpus), `entity` (graph), `finding`, `topic`. One reader, one selection model,
one filter, one URL segment." Three things have moved under it:

1. **`topic` is not a MATERIAL facet.** `regionOf('topic')` returns `queue`
   (`ProjectView.tsx:70-73`), with an argument — a topic is a work item, like a
   stage. `MATERIAL_TABS` (`:119-125`) is `artifact`, `file`, `finding`, `doc`,
   `entity`. So the slice's five are not the plan's five: `file` arrived early in
   slice 2 and `topic` left. The proposal's §3.3 table and §4.2's
   "R-F3.7 Manage dialog → MATERIAL `topic`" are both overtaken.
2. **The tabs exist and are populated.** Nothing in slice 3 is a greenfield
   facet; each of the five already renders the old page's component. The slice is
   therefore *not* "build five facets" — it is "replace five tenants with one
   reader", which is a much easier thing to get wrong quietly, because at no
   point does the page look broken.
3. **The order-within-the-slice argument is spent.** §2.3 says "`graph` last"
   because the default facet is a bundle decision only checkable once the others
   are in place. The default is already `artifact` and already argued as a bundle
   decision (`ProjectView.tsx:99-107`), and `GraphPane` already renders in a tab.
   `npm run verify`'s size budget can be read against the real page **today**.

**Recommended reshape**, stated as the replacement opening for §2.3:

> ### 2.3 Slice 3 — MATERIAL becomes one reader
>
> MATERIAL already has five tabs and five tenants: `artifact`, `file`,
> `finding`, `doc`, `entity` (`ProjectView.tsx:119-125`). `topic` is **not**
> among them — it is a QUEUE row (`regionOf`, `:70`), and the topic dialog is
> still a dialog. So this slice is a replacement, not a construction: one reader
> and one selection model behind five tabs that already draw.
>
> Take it in two halves, because they fail differently. **(a) Selection**: give
> `artifact`, `doc` and `finding` the selected state their URLs already promise
> (finding 3 above), which is verifiable by pasting a link. **(b) The reader**:
> collapse `DocumentReader`'s drawer, `Artifacts`' row detail and
> `TopicDocuments`' inline render onto one component. (b) is where the silent
> failures are, because a half-replaced reader still renders.
>
> Leave the `topic` facet out of this slice entirely. It belongs with the queue
> list — the unfinished half of slice 1 — because the surfaces that would feed a
> topic reader (`TopicStatusDialog`, `SubQuestions`, `TopicDocuments`) are the
> ones the queue rewrite touches.

One more thing this slice should be told to decide, because the shipped code
raised it and no document has: **`Tabs` cannot carry per-facet counts.** The old
`Pane` headers carried `N of M written` and `N of M left behind`; QUEUE kept its
meta and MATERIAL lost its (finding 4). §6 open question 2 asks `Tabs` vs a
listbox and answers "not resolvable without seeing a real project's material" —
it is now partly resolvable: `Tabs` is shipped, works, and has cost one visible
count. Either the tab labels grow counts or a meta line goes above the tab list.

### 6. §5.1's combinator table is stale in the direction that matters

Measured at `9fa6c7b`, comments stripped, `>` in a selector position only:

| File | Plan's count | Actual now | Note |
|---|---|---|---|
| `research.css` | 7 | **0** | all seven deleted in slice 1 with the views |
| `course.css` | 4 | **2** | `:452`, `:467` — both `.autonomy-disclosure[open] >`, i.e. §2.1's `AutonomyPanel` passenger, which moved into `QueueHeader` and still needs its rules to move with it |
| `responsive.css` | 6 | **3** | `:12`, `:25` (`[data-split='session'] > [data-pane='conversation']`), `:73` (`ul.tree ul > li`) |
| `conversation.css` | 7 | 7 | unchanged — slice 2 re-parented and rewrote nothing here |
| `timeline.css` | 2 | 2 | `:41`, `:212` |
| `composer.css` | 1 | 1 | `:77` |
| `workspace.css` | 1 | 1 | `:18` |

The load-bearing correction is `responsive.css`. §5.1 calls it "the dangerous
one" and names `.lay-split[data-split='course'] > …`, `.research-workbench > …`
and `.research-rail > …` as rules slices 1–3 would silently void. **Slice 1
deleted all three**, and `check-deleted.mjs` phase C0 (`:346-356`) now forbids
their return. What is left in `responsive.css` is two session rules and one tree
rule; **slice 3 voids none of them**. The instruction — grep `responsive.css` for
the view's selector before deleting a view — is still right, and it now has
nothing to find for the research view.

The plan's own `+`-combinator correction stands: still zero `+` combinators in
`src/styles/`.

### 7. A fifth composed family, dead in the other direction

`StageRail.tsx:27` writes `` `rail-item rail-item-${stage.status}` ``. `.rail-item`
is declared (`course.css:54`); **`.rail-item-done`, `-current`, `-upcoming` and
`-unknown` are declared nowhere in `src/styles/`.** Four class names written on
every stage row that dress nothing. Harmless today, and exactly the kind of thing
that gets "rescued" into a new stylesheet during a rewrite because it looks
load-bearing. Worth one line in whatever slice rewrites the rail: delete the
composition, do not port it.

---

## Classification table

| # | Claim | Where | Verdict |
|---|---|---|---|
| 1 | §2.1: QUEUE is one list, one filter, four slices | plan §2.1 | **WRONG** — `ProjectView.tsx:246-284` is header + `StageList` + `TopicList`; only filter is `TopicQueue`'s, topics only |
| 2 | §2.1: `course.css` dies in slice 1 | plan §2.1 | **WRONG** (already conceded in `QueueHeader.tsx:49`) — all 90 names still reached |
| 3 | §2.1: `chip-invariant`…`chip-critic_gate` must be rescued before deletion | plan §2.1 | **STALE** — done; `course.css:325-326` records the move |
| 4 | §2.1: `rail-${status}`, `worker-dot-${kind}`, `finding-${severity}` are invisible to a literal grep | plan §2.1 | **VERIFIED** — `StageRail.tsx:45`, `WorkerList.tsx:110`, `Findings.tsx:20`; my own literal sweep reported all 20 composed names as unused |
| 5 | §2.1: `AutonomyPanel`'s rules must move with it | plan §2.1 | **VERIFIED and outstanding** — panel is at `QueueHeader.tsx:124`, rules still at `course.css:452,467` |
| 6 | §2.3: `research.css` dies, effectively whole; 79 of 86 exclusive | plan §2.3 | **WRONG** — 81 names, all reached, 28 outside slice 3's scope |
| 7 | §2.3: seven `.research-rail`/`.research-workbench` combinators die with slice 3 | plan §2.3 | **STALE** — all seven died in slice 1 (`c1fbc6c`); `research.css` has zero combinators now |
| 8 | §2.3: deletes `ResearchView.tsx`, `use-research-panes.ts` | plan §2.3 | **STALE** — both deleted in slice 1; neither file exists |
| 9 | §2.3: the five facets are `artifact`, `doc`, `entity`, `finding`, `topic` | plan §2.3 | **WRONG** — shipped set is `artifact`, `file`, `finding`, `doc`, `entity`; `topic` is a QUEUE facet (`ProjectView.tsx:70`) |
| 10 | §2.3: "route grammar names all five, so no new href builder" | plan §2.3 | **VERIFIED but misleading** — builder is done; four facets' ids are never *read* |
| 11 | §2.3: `graph` last, because the default-facet bundle call is only checkable then | plan §2.3 | **STALE** — default is already `artifact` (`ProjectView.tsx:127`) and `GraphPane` already renders; measurable now |
| 12 | §3.1: `file`/`artifact`/`finding` "start rendering something" | plan §3.1 | **PARTLY WRONG** — `file` yes (slice 2); `artifact`/`finding` open a tab and select nothing; `topic`/`doc` have the same gap and are absent from the table |
| 13 | §3.2: use a new group string `project` | plan §3.2 | **VERIFIED** — `use-project-panes.ts:19`, with the reasoning restated |
| 14 | §3.3: the topic dialog stops being a modal | plan §3.3 | **UNDECIDED** — still a modal (`TopicList.tsx:36-40`). Options: (a) make `topic` a MATERIAL facet as the proposal says, contradicting `regionOf`'s argument; (b) keep it a dialog opened from a QUEUE row. **Recommend (b)** — `regionOf`'s reasoning (a topic is a work item) is better than §3.3's, and the dialog's keyboard contract is already correct |
| 15 | §2.0: `use-course.ts:104` invalidates `queryKeys.projects()` per frame | plan §2.0 | **STALE** — fixed; `use-course.ts:82` records the removal |
| 16 | §5.1: `responsive.css` has 6 combinators, three of them course/research | plan §5.1 | **STALE** — 3 remain, none course/research; forbidden by `check-deleted.mjs:346` |
| 17 | §5.1: no `+` combinators anywhere in `src/styles/` | plan §5.1 | **VERIFIED** |
| 18 | §6.3: `PROJECT_TRACKS` is unmeasured | plan §6.3 | **VERIFIED and outstanding** — `use-project-panes.ts` says so itself: "chosen, not measured" |
| 19 | proposal §3.3: header carries preset name and position (C-F1, C-F2) | proposal | **WRONG / regression** — neither renders anywhere; `course.position` is read nowhere in `presentation/` |
| 20 | proposal §4.3: C-F56's `N of M written` survives on the artifacts facet | proposal | **WRONG / regression** — `Tabs` label carries no count |
| 21 | proposal §4.2: R-F2.2 `SeedingRun.reply` surfaced | proposal | **WRONG** — still unrendered; `seeding.ts:18` |
| 22 | proposal §4.2: R-F1.1 rail folding replaced, virtualizer safe | proposal | **VERIFIED** — Radix unmounts closed panels (`Tabs.tsx:96`) |
| 23 | proposal §4.5: "nothing is unplaced" | proposal | **WRONG** — C-F1, C-F2 and C-F56 are placed in the document and absent from the page; the `position === null` sentence is explicitly named as kept and is gone |
| 24 | `.rail-item-${status}` | `StageRail.tsx:27` | **WRONG** (code, not plan) — no such rules exist in `src/styles/` |
| 25 | Breadcrumbs label the two facets `course` and `research` | `Breadcrumbs.tsx:87-90` | **STALE copy** — both pages are gone; the crumbs point at `#/p/<id>` and the `entity` facet of the same page |

---

## What I could not check without running anything

- **Whether any of the lost text is visible elsewhere at runtime.** I established
  that `preset.name`, `course.position` and `writtenCount`-over-`allArtifacts`
  have no reader in `presentation/`. A rendered page is the only thing that
  proves nothing else prints them. `npm run dev` and one project page settles it.
- **Whether the 28 surviving `research.css` names are all still *drawing*.** I
  established they are written by a component that renders. A rule can be written
  and overridden, or scoped to an ancestor that changed. `npm run test:browser`
  with a computed-style assertion per family, or Storybook by eye, settles it;
  jsdom cannot, per `CLAUDE.md`.
- **Whether `PROJECT_TRACKS`'s 1 / 1.5 / 1 is usable.** Unmeasured by its own
  docstring. Needs the browser suite at each of the three responsive layouts.
- **Whether MATERIAL's five tabs reproduce the clipped-focus-ring geometry**
  (plan §5.2). `.lay-pane-body` is an unpadded scroller and three of the five
  panels add `overflow-auto` (`ProjectView.tsx:401,427`); whether the rows inside
  lose their rings is a measurement. `FileList.browser.test.tsx` is the pattern.
- **The bundle budget against a five-tab MATERIAL** (§2.3's `graph`-last
  argument). `npm run verify` reads `app-` 80 / `ui-` 48 / `total` 512; I ran
  nothing.
- **Anything in `features-*.md` §2 (backend routes) and the `G*`/`P*`
  sections.** Those are server claims dated `5a5a7cf`; I audited only the
  frontend-visible half, and per the plan's §0 every feature id without a
  `file:line` should be re-verified before it is built against.
