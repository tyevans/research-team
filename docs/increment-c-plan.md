# Increment C, made startable

`unified-ui-proposal.md` §3 argued the route merge. This turns it into slices
somebody can begin on a Monday. It is a plan, not a proposal: the decision was
taken, and what follows is what to build, in what order, and what will go wrong.

## 0. What I checked, and what I did not

**Corrected on 2026-08-13 against the code at `9fa6c7b`, by the five audits in
`docs/reviews/`.** Slices 0, 1 and 2 have shipped since this plan was written,
and three of the plan's load-bearing claims were reversed by what they shipped
rather than by anyone changing their mind. Corrections below are marked
**[audit N]** and say what the plan used to say, because a plan edited to look
as though it was always right stops being evidence about planning — the same
argument `component-system-spec.md` §11 makes about phase 5. Nothing was run to
take these corrections either: no gate, no build, no browser suite. Each audit
ends with the run that would settle what it could not.

**Read out of the worktree at `f87443b`, against `unified-ui-proposal.md`, which
was written at `4a86e89` — 73 commits ago.** That gap is the single most
important fact in this document and §1 is about nothing else. Every claim below
carrying a `file:line` was opened and read at `f87443b`. The four
`docs/features-*.md` indexes were read at `5a5a7cf`, three months of frontend
work ago, and I have treated every feature id (`C-F5`, `R-F3.1`, `S-F29`…) as a
pointer to a *survey*, not as a claim about the code. Where a feature id below
carries no `file:line`, I did not re-verify it and it should be re-verified
before anyone builds against it.

**Nothing here was run.** No gate covers `docs/`, and I ran none — not `pytest`,
not `npm run verify`, not the browser suite. The combinator inventory in §5.1 is
a script over the stylesheets, which is a text measurement and not an
observation of a rendered page. The claim that a rule "stops matching" is an
inference from the selector's shape.

**One instruction in my brief was wrong and it matters.**
`research_team/infrastructure/persistence/local_copy.py` **does not exist on
`main`**. It is added by open PR **#158**, which also contains the axe sweep and
the timeline-virtualization decision. So `uv run python -m
research_team.infrastructure.persistence.local_copy` is a command that becomes
available when #158 merges, and until then the CLAUDE.md rule about verifying
against a database that predates a change has no executable form. §4 depends on
this and says so there.

---

## 1. What has already shipped, and what that does to the proposal

**Increment C is roughly half done, and the proposal does not know it.** The
work below landed between `4a86e89` and `f87443b`. This section exists so nobody
starts by rebuilding it.

**§3.1's route grammar is shipped, whole.** `presentation/routing/routes.ts:24`
declares exactly the three routes the proposal asked for. `parseRoute`
(`routes.ts:109`) and `projectHref` (`routes.ts:211`) are both there, and
`projectHref` is one builder over the whole union, so a facet added to the union
is linkable without anyone writing its href.

**[audit 1, F3] `FACETS` (`routes.ts:67-80`) is the proposal's eight plus
`ask`** — added after the proposal was written: `session`, `topic`, `stage`,
`entity`, `doc`, `file`, `artifact`, `finding`, `ask`. This paragraph used to
say "exactly its eight" and enumerate them, and proposal §3.1 still does. `ask`
selects nothing and is a facet anyway because it is a place on the project;
`App.tsx:138` intercepts it above `ProjectView`, which is the one arm of the old
two-page dispatch that survives. A plan that does not know `ask` exists cannot
describe the dispatch correctly, and §2.0 did not. (Line drift corrected in the
same pass: `parseRoute` is `:109` not `:105`, `projectHref` is `:211` not
`:207`, and the `home` fallback for an unrecognised facet is `routes.ts:130-133`
not `:126-129`.)

**[audit 1, F1] This paragraph used to end "A topic, a stage and an artifact are
already linkable states. This is not a slice; it is a precondition that is met."
Two thirds of that is false.** A stage is a linkable state *and is read*:
`ProjectView.tsx:167` derives `openStage` from the route. A topic and an
artifact are linkable in the **grammar only** — `projectHref` builds their URLs
and `parseRoute` parses them, but `TopicList`, `DocumentList`, `ArtifactList`
and `ProjectFindings` are each mounted with no selection at all
(`ProjectView.tsx:283, 435, 402, 428`) and hold their open item in component
state. **The grammar is a met precondition; reading the id back is not, and it
is unbudgeted work in slice 3.** The error was load-bearing: it is why no slice
below budgeted work for reading those ids.

It is also a shipped defect rather than only a gap. `CitationList.tsx:44` builds
`projectHref(projectId, { facet: 'doc', id: citation.id })` with a comment
saying it "keeps the reader on the project page"; following it opens the project
page with the Documents tab selected and **no document open**, because the id is
parsed, put on `selection`, and dropped. A reader who clicks a citation lands on
an unfiltered list and has to find the source by hand.

**§9's decision bar is shipped, whole.** `presentation/shell/DecisionBar.tsx`
exists and is mounted in the shell (`app/App.tsx`, above `CurrentView`).
`presentation/session/GateReview.tsx` exists with tests and stories.
`infrastructure/http/dto.ts:243,247` carry `allowed_decisions` and the optional
`context`; `domain/approval/approval.ts:21-23` carry `allowedDecisions` and a
nullable `context`. `check-deleted.mjs` phase-3 rules forbid the three old
`Approvals` call sites from coming back. §9 of the proposal should be read as
history.

**§3.2's layout promotion is shipped, and is not `use-panes.ts`.** There is no
`use-panes.ts`. There is `layout/Split.tsx`, `layout/Pane.tsx`,
`layout/split-tracks.ts` and `layout/use-split-panes.ts`, and the session,
course and research views have all migrated onto them. `panes.css` is gone;
`check-deleted.mjs` phase-C forbids every one of its class names. The
width-redistribution behaviour the proposal wanted preserved is
`splitTemplate` (`split-tracks.ts`), and the `undefined`-below-the-breakpoint
handoff is one named branch. `RailPane` is deleted and forbidden
(`check-deleted.mjs`, phase B). **§3.2's cost estimate — "promoted rather than
rewritten" — was paid and the promotion succeeded.**

**§11's strongest argument against the proposal is stale.**
`presentation/session/` had one test file when the proposal was written. It now
has twelve, including `SessionView.test.tsx`, `Timeline.test.tsx`,
`Composer.test.tsx`, `FileView.test.tsx`, `FileList.test.tsx` (plus
`FileList.browser.test.tsx`), `ScrubBar.test.tsx`, `Segments.test.tsx`,
`Conversation.test.tsx`, `FileHistory.test.tsx` and `GateReview.test.tsx`.
`presentation/common/`, which `component-system-spec.md` §14.3 correctly named as
the worse gap, now has tests for `Confirm`, `Drawer`, `Menu`, `Popover`,
`Tabs`, `Tooltip`, `TruncatedText` and `Choices`. The merge is no longer "a
redesign without a net". **This does not make it safe; it makes §11's specific
argument no longer the reason it is dangerous.** §5 is.

**§10's refusal of new primitives was overruled and the primitives exist.**
`Menu`, `Tooltip`, `Tabs`, `Popover`, `VirtualList` and `OverlayHost` are all in
`presentation/common/` and `presentation/layout/`, which is what
`component-system-spec.md` §14.2 predicted would be needed. The `⋯` menu, the
`?` overlay and the six-facet shell no longer need components invented for them.

**The stylesheet policy changed under the proposal's feet, and this is the
change with the most consequence for the slices below.**
`component-system-spec.md` §11 records that phase 5 — porting the 22 stylesheets
to utilities — was **dissolved on 2026-08-10** and replaced by a standing
policy: *new and rewritten surfaces use Tailwind utilities; existing stylesheets
are deleted, never ported*. The arithmetic given is that ~6430 lines dress
markup increment C rebuilds anyway. `check-deleted.mjs`'s `STYLESHEETS` array
freezes the 22 filenames and **fails in both directions** — a 23rd file fails as
a policy violation, and a deletion fails too, so every slice below that deletes a
stylesheet also edits that array in the same diff. That is the mechanism, and it
is the thing that makes "which stylesheets die with this slice" an answerable
question per slice rather than a hope.

**Three smaller corrections, all checked.**

- §6.5 prices the bundle at `app-` 57 / `total` 512. `frontend/scripts/check-size.mjs:62,157`
  says `app-` **80** and `total` 512, with a separate `ui-` **48**. The
  proposal's pessimism about a merged page growing `app-` is priced against a
  ceiling that has moved.
- §5.1 claims "`parseRoute` maps both onto the new grammar, so links survive".
  **It does not, deliberately.** `course` and `research` are not in `FACETS`, so
  `parseSelection` returns `null` and `parseRoute` returns `home`
  (`routes.ts:126-129`), asserted at `routes.test.ts:133`. The old URLs are
  *already* broken and already land on the picker. §3 restates the breakage
  accordingly.
- §6.2's "required rather than optional" prerequisite. **[audit 5, A6] This
  entry used to read "still not done — `use-course.ts:104` still invalidates
  `queryKeys.projects()` on every project frame". It landed in `980ebfd` (#170),
  and it did not become the single-row invalidation the proposal prescribed: the
  invalidation was *removed*.** `use-course.ts:82-101` states why in the code —
  there is no per-project row to invalidate, because `/api/projects` answers the
  whole list as one response under one cache entry, so a per-row invalidation
  needs a per-project route, which is backend work. The comment also names what
  the removal costs: nothing now refreshes the picker's workflow and stage
  columns while somebody else advances a stage. The answer to that is a
  subscription on the picker, not one on the project page. Proposal §4.1's row
  "L-F9 … gains `queryKeys.projects()` on `project` frames, closing L-R6" is
  therefore **load-bearing rather than a nicety** — it is the only thing that
  replaces what #170 removed.

**What is left is genuinely the merge and nothing else.** `app/App.tsx` says so
itself: `RESEARCH_FACETS` is documented in place as "a *temporary* fact — §3.2 of
the proposal deletes both views into one page, and at that point this set and
the branch it feeds both go", and it records that `file`, `artifact` and
`finding` "parse and they are linkable, and the region that renders them is a
later slice". The plan below is that later slice, written down.

---

## 2. The slices

`ui-foundations.md` §4.1 states the rule these slices obey and states it better
than I would: **"A slice is defined by its entities and its regions, not by its
route."** Its corollary is what makes this tractable — with `Split`, `Pane` and
the entity contract in place, moving the run panel from the course page to a
QUEUE header "is a re-parent" rather than a rewrite.

### The order to read these in, which is not their numbering

The slice numbers below are kept as written, because they are cited from commit
messages, from `check-deleted.mjs` phase labels (`C1`) and from the two slice
reports in `docs/reports/`, and renumbering them would silently break those
references. But the numbers no longer describe the order of the remaining work.
**[audits 1 and 2] The real sequence from here is:**

1. **§2.1b — the queue list.** Slice 1 shipped its *header* and not its *list*
   (§2.1). This is outstanding work and it comes **before** slice 3: QUEUE is
   the region the whole merge is named for, §6's open question 1 is unstarted
   rather than unresolved, and `research.css` cannot die until the topic
   surfaces move (§2.3).
2. **§2.3-pre — the shared-selection rule.** A `routes.ts` change, a
   **prerequisite** of slice 3 rather than a detail inside it (§3.3).
3. **§2.3 — MATERIAL becomes one reader**, minus `topic`, which is QUEUE
   (§2.3).
4. **§2.4 — the picker**, which is no longer pure subtraction (§2.4).

Two defects filed against already-shipped slices are not slices and should not
wait for one: HOLDER has no region-level error state (§2.2) and
`Breadcrumbs.tsx:90-92` still offers two dead names for one destination (§3.3).

### 2.0 Slice 0 — the page frame, and the invalidation fix

**This is not in the task's list and I am arguing it in.** QUEUE cannot ship
first because there is no page for it to ship into: today `App.tsx` dispatches a
project route to one of two whole-page components, and there is no three-region
container. A slice that built QUEUE and the container together would be the
largest slice in the plan and the one with no independent verification.

**Creates.** `presentation/project/ProjectView.tsx` — a `Split` with
`PROJECT_TRACKS` and three `Pane`s (`queue`, `holder`, `material`), and
`presentation/project/use-project-panes.ts` holding `PROJECT_TRACKS` and the
group string, following `use-session-panes.ts:21,7` exactly.

**Changes.** `app/App.tsx`: delete `RESEARCH_FACETS` and the branch that chose
between the course and research views. **[audit 1, F4] This bullet used to say
"delete the two-arm branch … `ProjectView` unconditionally"; the branch has
three arms and the shipped code says so.** The `project` route renders
`ProjectView` for every facet **except `ask`**, which `CurrentView` intercepts
above the project page (`App.tsx:138`) because the ask page is one conversation
with no parts and nothing to read it against. That interception is deliberate
and survives the increment; `regionOf` maps `ask` to `queue` anyway, so the map
stays total. `ProjectView.tsx:60-64` already names the plan's error in a
comment.

`use-course.ts`'s per-frame `queryKeys.projects()` invalidation. **[audit 5, A6]
This bullet used to prescribe replacing it with a single-row invalidation, and
call that a prerequisite. It shipped in `980ebfd` as a deletion instead**, for
the reason §1 now records: a single-row invalidation is not expressible against
a listing that is one cache entry. The prerequisite is discharged; what it left
behind is a picker that goes stale, and that is proposal §4.1's L-F9 row.

**Tenants, initially unchanged.** QUEUE holds today's `StageRail` and
`TopicQueue`; HOLDER holds `SessionView`; MATERIAL holds `GraphPane`,
`Artifacts` and `DocumentList` behind `Tabs`. Nothing is rewritten. The page is
ugly and it works.

**Independently shippable because** it is verifiable by navigation alone: every
facet in `FACETS` reaches a region, and the three facets that reach nothing
today (`file`, `artifact`, `finding`) get their first renderer even if it is the
existing one.

**[audit 1, F8] That verification was weaker than this sentence claims, and the
gap is the reason slice 3 has to assert reachability rather than assume it.**
What shipped is `ProjectView.test.tsx:16-23`, a test over `regionOf` — a pure
map from facet to region. It cannot see whether a renderer receives the id
(F1), and it cannot see whether any control on the page *leads* to the facet.
Enumerated by grep over `projectHref`/`sessionSelection`/`facet:` in non-test
sources, the facets with no inbound control today are: **`topic` entirely**, and
`artifact`, `finding` and `file` at the id level — their tabs are clickable, but
no click anywhere writes one of their ids. `#/p/<id>/file/<path>` and
`#/p/<id>/artifact/<id>` are typed-URL-only entrances. This is the blind spot
`8fe734c` named after the ask page lost both its doors: "a suite that only
teleports cannot notice the stairs are gone."

**Stylesheets that die: none.** This slice deletes no markup.

### 2.1 Slice 1 — QUEUE

Per the task, and I agree it is first among the region slices.

#### 2.1a Shipped in slice 1: the header only

**[audit 2, finding 1] This is the correction with the most downstream cost,
because slices 2 and 3 and the proposal's §3.3 are all written against a QUEUE
that exists and does not.** `QueueHeader` exists and holds the ask link, the
roster, the extraction detail, the run panel, the seed control and the autonomy
panel. **The row union, the cross-kind filter and the four renamed slices were
not built.** QUEUE today is `QueueHeader` over `StageList` over `TopicList`
(`ProjectView.tsx:246-284`) — three sibling components, two lists, no union, no
shared filter, no shared slices. `presentation/project/queue/` contains exactly
one file, `QueueHeader.tsx`. The only filter on the page is `TopicQueue`'s own,
over topics only, still labelled `All` / `Needs you` / `Live` / `Closed` rather
than the four this section renames them to. Sessions and dispatches are not rows
at all; a running worker is a roster line inside `QueueHeader`
(`QueueHeader.tsx:108`), above the list rather than in it.

`QueueHeader.tsx:49` is candid about its own scope — "`course.css` itself does
**not** die here, which the plan's §2.1 expected it to" — but nothing recorded
that the *list* half was outstanding, and read literally §2.2 and §2.3 both
begin from a QUEUE that was built.

#### 2.1b The remaining work of slice 1, sequenced before slice 3

Everything under "Creates" below except `QueueHeader` is still owed. **Sequence
it before slice 3**, for three reasons that compound: QUEUE is the region the
merge is named for; the ordering function §6.1 wants to keep separable has no
list to be separable from yet; and `research.css`'s 32 surviving topic-and-seed
rules (§2.3) cannot leave until the surfaces that write them are rewritten,
which is this work.

**Creates.** `presentation/project/queue/` — a `QueueList` over one row union
with five sources (topic, stage, session, dispatch, running worker), one filter
across all kinds, and the four slices rewritten as `All` / `Needs you` /
`Running` / `Done`. A `QueueHeader` holding the run panel, the dispatch bar and
the seed control.

**Changes.** `RunPanel.tsx`, `SeedPanel.tsx`, `ExtractionPane.tsx` re-parent into
`QueueHeader` and lose their own chrome. `TopicRow` (`entity/topic/TopicRow.tsx`)
is already the entity-contract row and becomes one arm of the union rather than
being rewritten.

**Deletes.** `course/CourseView.tsx`, `course/StageRail.tsx`,
`course/StageList.tsx`, `course/use-course.ts`'s `COURSE_TRACKS` and
`COURSE_GROUP`, `research/TopicList.tsx`, `research/use-topic-queue.ts`'s
per-view filter if the unified one subsumes it.

**Stylesheets that die: none. `course.css` did not die** — **[audit 2, findings
2 and 5]** this section used to predict it would, and `QueueHeader.tsx:49`
concedes it did not. All 90 of its class names are still reached: 70 literally,
and 20 through the four composed families below. It cannot leave `STYLESHEETS`
until the markup that writes those names is rewritten, which is §2.1b plus
whatever slice rewrites the stage rail. **Two of its combinators survive at
`:452` and `:467`, both `.autonomy-disclosure[open] >`** — the `AutonomyPanel`
passenger this section warned about, which moved into `QueueHeader` without its
rules. That move is still owed and is the one live instance of the trap below.

The chip passenger was rescued before the file was touched: `course.css:325-326`
is now a comment recording where the five severity rules went. That half of this
section is **done**, and is left standing below because the trap it describes is
the one the repository keeps re-meeting.

The two passengers, as originally written:

Its combinators split cleanly:
`.lay-split[data-split='course'] > …` at `course.css:37,48,55` died with
`CourseView` in slice 1, and `.autonomy-disclosure[open] > …` — now at `:452`
and `:467`, not the `:689,705` this line first cited — belong to
`AutonomyPanel`, which is **not** a QUEUE tenant — those, plus `.autonomy-warn`
and `.autonomy-error`, must move with the panel or it loses its chrome silently.
`check-deleted.mjs`'s phase-5 rule was written for exactly this trap when
`AutonomyAllowAll` moved into the shell, and its comment names `course.css` as
"a file on the die-with-its-screen list". Read that comment before deleting the
file.

**The second passenger is not recorded anywhere and I would not have predicted
it.** `course.css:327-345` declares `.chip-invariant`, `.chip-blocking`,
`.chip-advisory`, `.chip-human_gate` and `.chip-critic_gate` — the severity
tones of the shared `Chip` primitive (`common/primitives.tsx:35` composes
`` `chip-${tone}` ``). **`session/GateReview.tsx:126` renders `<Chip
tone={severity}>` with that same vocabulary**, so the decision bar's finding
chips are coloured from the course page's stylesheet. Deleting `course.css` in
slice 1 strips the colour from a component in the *shell*, on every route, with
no test failure and no error — the `AutonomyAllowAll` trap again, one file
later. **Move those five rules to `components.css` or to utilities in
`GateReview.tsx` before slice 1 deletes anything.** The neighbouring
`.chip-done`, `.chip-current`, `.chip-upcoming`, `.chip-unknown`,
`.chip-present`, `.chip-missing`, `.chip-inferred` and `.chip-bad` are fed only
by `StageRail.tsx:64` and `Artifacts.tsx:46` and do die with the slice.

Three further families in `course.css` are composed from template literals and
so are invisible to a grep for the class name — `rail-${status}` (`:100-112`,
from `StageRail.tsx:45`), `worker-dot-${kind}` (`:413-422`, from
`WorkerList.tsx:110`) and `finding-${severity}` (`:298-312`, from
`Findings.tsx:20`). All three are course-exclusive and die, but a slice that
audits by grepping literal class names will conclude they are unused rather than
conclude they are dynamic. **[audit 2, finding 4] Verified by a literal sweep
that reported all twenty composed names as unused. They are not.** `chip-${tone}`
(`primitives.tsx:73`) is the fourth family and the one that reaches the shell.

**[audit 2, finding 7] There is a fifth composed family, and it is dead in the
other direction.** `StageRail.tsx:27` writes `` `rail-item rail-item-${stage.status}` ``.
`.rail-item` is declared (`course.css:54`); `.rail-item-done`, `-current`,
`-upcoming` and `-unknown` are declared **nowhere in `src/styles/`**. Four class
names on every stage row that dress nothing. Harmless today, and exactly the
kind of thing that gets "rescued" into a new stylesheet during a rewrite because
it looks load-bearing. Whatever slice rewrites the rail should delete the
composition rather than port it.

**`check-deleted.mjs` gains:** `'course.css'` removed from `STYLESHEETS` (which
fails the check until it is), plus a rule over `styles` forbidding
`/^\.course-/m` and `/\[data-split='course'\]/`, and a rule over
`presentation/course` forbidding `/\bCourseView\b/` and `/\bCOURSE_TRACKS\b/`.

**Visibly different afterwards:** the stage rail, the topic queue, the session
list and the dispatch deque are one list. `Needs you` spans a blocked topic, a
posed gate and a pending approval for the first time.

**Independently shippable because** a half-built QUEUE is a list missing row
kinds — loudly wrong, which is the property the task's slicing rule exists to
preserve.

### 2.2 Slice 2 — HOLDER **and** MATERIAL `file`, together

**Here I disagree with the task's order, and this is the substantive
disagreement.** The task lists HOLDER as slice 2 and MATERIAL's six facets as
slice 3. But HOLDER is not "`SessionView` in place". `SessionView.tsx:208-315`
is itself a `Split id="session"` with three panes — `timeline`, `workspace`,
`conversation` (`use-session-panes.ts:21`). Under §3.3 of the proposal, timeline
and conversation are HOLDER and **the `workspace` pane is MATERIAL's `file`
facet**. So the slice that dissolves `SessionView`'s Split is the same slice that
gives MATERIAL its first real tenant. Splitting them means shipping either a
nested `Split` inside a `Pane` — two persistence groups, two last-open rules, and
`splitTemplate`'s inline `grid-template-columns` written twice on one page — or
a `SessionView` temporarily missing its workspace. Both are worse than one
larger slice.

**The rest of the task's ordering survives this** and its reasoning survives
intact: a half-migrated region is loudly broken. HOLDER-plus-`file` is still one
region boundary, still loud.

**Creates.** `presentation/project/holder/` — the scrub bar, timeline,
conversation and composer as direct children of the HOLDER pane; and the
"nothing is holding this project" state with a `Join` button, which is the four
degradations `C-D2`/`C-P5` describe *(from the dated course survey; verify
against `CourseView` before building)*.

**Changes.** `SessionView.tsx` loses its `Split` and becomes a component that
renders into a region. The standalone `#/s/<id>` route keeps its own `Split` —
it must, because a transcript read on its own is still three panes, and
`routes.ts:29-34` argues that route stays top-level.

**[audit 4, finding 3] Filed as a defect against this slice rather than as
slice-3 scope: `SessionView` kept its whole-page error arm and HOLDER never
gained a region-level one.** Proposal §4.4 promised "S-F4 whole-page error →
HOLDER: becomes region-level: one failed session read must not blank a project
page." Half shipped. `SessionView.tsx:72-82` still returns the whole-page
`ErrorBox` for `#/s/`, correctly. `ProjectView` reads neither
`screen.state.error` nor `screen.state.snapshotError` — grep finds no occurrence
— so a failed `GET /api/sessions/{id}` on the project page draws HOLDER's
ordinary tree: a `ScrubBar` over an empty log, an empty transcript and a live
composer, with no message and no Retry. The project page does not blank, which
is the half that shipped; the reader is also never told the read failed, which
is **worse than the state it replaced**. `state.snapshotError` is handled, but
only inside `WorkspacePanel` (`panels.tsx:101-109`), i.e. in MATERIAL, and only
for folds.

**[audit 4, finding 7] Four small duplications survive between the two
arrangements, and one of them is load-bearing copy.** The end-session `Confirm`
block is duplicated verbatim — heading, both sentences and confirm label —
between `SessionView.tsx:106-120` and `ProjectView.tsx:319-333`.
`features-session-view.md` F13 records that this wording is the part that
matters, because "end this session" sounds destructive and those two sentences
are what say it is not. **Export an `EndSessionConfirm` from `panels.tsx` taking
`screen`, and delete both copies** — a five-line change that removes the
highest-probability divergence on the page. The `ScrubBar` wiring is duplicated
the same way (`SessionView.tsx:86-96` vs `ProjectView.tsx:307-317`), lower risk.
And `workspaceMeta` (`panels.tsx:46`) is now used by one caller only
(`SessionView.tsx:142`), so **on the project page nothing in MATERIAL says which
point the file tree is folded to** — on `#/s/` the Workspace pane header reads
`@ event 12` (F20/F31); in MATERIAL's Workspace tab there is no such string, and
the only indication is the `ScrubBar` in a *different region* the reader may have
collapsed.

**Deletes.** `use-session-panes.ts`'s `SESSION_TRACKS` only if the standalone
route stops using it; it does not, so **this file survives and the group
`session` survives with it**. `course/WorkerDrawer.tsx` survives.

**[audit 4, finding 5] It survives whole and *unfiltered*, which is not what this
bullet used to say.** It said the drawer "mostly dissolves but survives for the
dock's foreign-project rows (proposal §5.2)". No such narrowing exists:
`AgentWidget.tsx:183-189` opens `WorkerDrawer` for whatever row was clicked,
with no comparison against the project on screen — and `AgentWidget` is shell
chrome with no notion of the current project. So for a row belonging to *this*
project there are two ways to watch the same session, one of them a
focus-trapping overlay over the page that already shows it in HOLDER. Nothing is
broken; the sentence described filtering nobody has written, and it was the
sentence explaining why the drawer is not deleted. Either build the narrowing —
the dock would need the current project id — or accept two ways to watch one
session and record that as the accepted cost.

**Stylesheets that die: `conversation.css`, `timeline.css`, `composer.css`,
`workspace.css`, `scrub-bar.css`** — but only the ones whose markup this slice
actually rewrites. `conversation.css` carries **eight** combinators, the most of
any file, and six of them (`.run > .disc-head`, `.discarded > .disc-head`,
`.msg-body > .md`, and the `:has(> .md)`) are claims about markup this slice
moves. This is the file to grep first.

**`check-deleted.mjs` gains:** removals from `STYLESHEETS` for each file
actually deleted, plus a `styles` rule forbidding `/^\.msg-body\b/m`,
`/^\.run\s*>/m` and `/^\.files\b/m`.

### 2.3 Slice 3 — MATERIAL becomes one reader

**[audits 1, 2 and 4] This section used to open: "`artifact`, `doc` (corpus),
`entity` (graph), `finding`, `topic`. One reader, one selection model, one
filter, one URL segment — and the route grammar already names all five, so this
slice writes no new href builder." Three of those five words about the facet set
are wrong, and the last clause is true in a way that hides the work.**

MATERIAL already has five tabs and five tenants, and they are not the five above:
`artifact`, `file`, `finding`, `doc`, `entity` (`MATERIAL_TABS`,
`ProjectView.tsx:119-125`). `file` arrived early in slice 2 and `topic` was never
there. So **this slice is a replacement, not a construction**: one reader and one
selection model behind five tabs that already draw. That is a much easier thing
to get wrong quietly, because at no point does the page look broken.

#### `topic` is QUEUE, and this is now decided

`regionOf('topic')` returns `'queue'` (`ProjectView.tsx:69-73`), and
`ProjectView.test.tsx:57` asserts `regionOf('topic') === regionOf('stage')`.
This section, §3.1's table, §3.3 and proposal §3.3 all said MATERIAL. **Both
readings were coherent and both documents wrote theirs down as settled; the
decision is QUEUE**, for the reason `regionOf` gives and this plan did not: a
stage and a topic are both work items the project owes somebody, which is what
the regions are named for. Moving the topic row to MATERIAL would take the
queue's most-used row kind out of the region defined as "what is there to do",
and would contradict a shipped, tested assertion.

The two documents were conflating a topic **row** (QUEUE) with a topic
**detail** (a reader). What §3.3 actually wants is the topic dialog
demodalised — a change to the dialog, not to `regionOf` — and that belongs with
§2.1b, because the surfaces feeding it (`TopicStatusDialog`, `SubQuestions`,
`TopicDocuments`) are the ones the queue rewrite touches. **Leave the `topic`
facet out of this slice entirely.**

#### Take it in two halves, because they fail differently

**(a) Selection.** **[audit 1, F1; audit 2, finding 3] This is the unbudgeted
work, and it is the concrete content of "one selection model".** `projectHref`
builds all nine facets — that is the easy half, and it is what "writes no new
href builder" was true about. Only four facets are *read*: `session`
(`ProjectView.tsx:168,174`), `file` (`:176-181` → `:423`), `stage` (`:167` →
`:277`) and `entity` (`:441`). `topic`, `doc`, `artifact` and `finding` parse,
choose a region, and are then dropped — the id never reaches a component. So
`#/p/x/artifact/<id>`, `#/p/x/doc/<sid>` and `#/p/x/finding/<id>` open the right
tab and highlight nothing.

This slice owes each of its facets a selected state **and** an empty/`not found`
state for an id that no longer exists — four selection models' worth of work
however few readers they end up sharing. It is verifiable by pasting a link,
which is why it goes first.

**(b) The reader.** Collapse `DocumentReader`'s drawer, `Artifacts`' row detail
and `TopicDocuments`' inline render onto one component. This is where the silent
failures are, because a half-replaced reader still renders.

**Reachability, asserted rather than assumed.** For each facet this slice
touches, `App.test.tsx` gains a test that finds the *inbound control* by role and
name and clicks it, rather than assigning `window.location.hash`. `8fe734c`
established that distinction after the ask page lost both its doors, and
§2.0 records why `ProjectView.test.tsx`'s `regionOf` coverage cannot replace it.
`CitationList.tsx:44` is the one shipped link that already emits an id nothing
reads, so it is both the first test and the first fix.

**Order within the slice: the `graph`-last argument is spent.** **[audit 2,
finding 11]** This section used to put `graph` last because the default-facet
bundle decision "only becomes checkable once the other facets are in place". The
default is already `artifact` and already argued as a bundle decision
(`ProjectView.tsx:99-107`), and `GraphPane` already renders in a tab, so `npm
run verify`'s size budget can be read against the real page **today**. Order the
slice by (a)-then-(b) instead.

**The default MATERIAL facet is `artifact`, not `workspace`.** **[audit 1, F7]**
`DEFAULT_MATERIAL = 'artifact'` (`ProjectView.tsx:127`) and `MATERIAL_TABS` puts
it first (`:120`). Proposal §3.3 states "the default facet is `workspace`, not
`graph`" and this section used to repeat it. Slice 2 shipped `artifact` and the
choice is defensible: artifacts are what a stage declared it produced and the
workspace is the tree those declarations are made of, so artifacts-then-workspace
reads in that order. §3.3's bundle *argument* is unaffected — it rules out
`entity` as the default, and both `artifact` and `file` satisfy it, since
`FileList`/`FileView` are already in the main chunk. One knock-on: the comment at
`ProjectView.tsx:101-102` says "the plan's §2.3 makes the same call", which it
did not; correct that comment when the file is next touched.

**Deletes.** `research/DocumentBrowser.tsx` if the shared reader subsumes it,
`course/Artifacts.tsx`'s page chrome. **[audit 2, finding 8]**
`research/ResearchView.tsx` and `research/use-research-panes.ts` were listed here
and are **already gone** — both were deleted in slice 1, and the `research`
preference group was orphaned with them (§3.2).

**Stylesheets that die: none, and `research.css` in particular does not.**
**[audit 2, finding 2] This section used to say "`research.css`, effectively
whole. Of its 86 class names, 79 are exclusive to `presentation/research/*`."
Both halves are wrong, and the second is wrong in a way that hides the first.**
The file is 848 lines declaring **81** class names — the seven survivors it
listed (`.view-head`, the `.lay-pane*` corrections, `.research-rail`,
`.research-workbench`) were deleted in slice 1 with the views — and **all 81 are
still reached**. "Exclusive to `presentation/research/*`" is true and is not the
test that matters; the test is which *region* the reaching component now lives
in, and this slice only rewrites MATERIAL:

| Family | Names | Reached from | Region | Dies here? |
|---|---|---|---|---|
| `graph-*` | 36 | `GraphPane`, `GraphCanvas`, `GraphDetail`, `GraphLegend` | MATERIAL `entity` | yes |
| `document-*` | 13 | `DocumentBrowser`, `DocumentReader` | MATERIAL `doc` | yes |
| `topic-browser`, `topic-list`, `topic-search`, `topic-focus*`, `topic-dispatch*`, `is-on` | 12 | `TopicQueue.tsx` | **QUEUE** | **no** |
| `seed-*` | 5 | `SeedForm.tsx` | **QUEUE header** | **no** |
| `sub-question*`, `sub-questions` | 8 | `SubQuestions.tsx` | the topic dialog | **no** |
| `topic-status-*`, `topic-section-heading`, `topic-documents-section` | 7 | `TopicStatusDialog.tsx` | the topic dialog | **no** |

**32 of 81 names — a third of the file — are outside this slice's blast
radius**, so `research.css` cannot leave `STYLESHEETS`. It leaves in the slice
that rewrites the queue list and the topic surface, which is §2.1b. Deleting the
graph and corpus rules from *inside* the file is available and worth doing here;
deleting the file is not. **This is the third consecutive slice for which this
plan predicted a stylesheet death that a re-parenting cannot deliver** — the
pattern, not the arithmetic, is the thing to carry forward.

Its seven `.research-rail > …` / `.research-workbench > …` combinators, which
this section called the hazard, **all died in slice 1** (`c1fbc6c`);
`research.css` has zero combinators now and `check-deleted.mjs` phase C0
(`:346-356`) forbids their return.

**`check-deleted.mjs` gains:** a `styles` rule forbidding `/^\.document-row/m`
and `/^\.graph-/m` once those rules are deleted from inside the file. The
`'research.css'` removal from `STYLESHEETS` and the `/\.research-rail/`,
`/\.research-workbench/`, `/\bResearchView\b/`, `/\buseResearchPanes\b/` rules
listed here have **already landed** with slice 1.

**One thing this slice must decide that no document has asked: `Tabs` cannot
carry per-facet counts.** **[audit 2, findings 4 and 5]** The old `Pane` headers
carried `N of M written` and `N of M left behind`. QUEUE kept its meta
(`ProjectView.tsx:249-253`); MATERIAL lost its, because a `Tabs` label is not a
`Pane` header. §6 open question 2 asks `Tabs` versus a listbox and answers "not
resolvable without seeing a real project's material" — it is now partly
resolvable: `Tabs` is shipped, works, and has cost one visible count. Either the
tab labels grow counts or a meta line goes above the tab list.

### 2.4 Slice 4 — the picker gets thinner

**[audit 5] This section used to read: "`#/` loses its two destination buttons
and … re-sources its liveness chip from the dock's roster … it is the only slice
that is pure subtraction." Half of it shipped as a re-pointing rather than a
subtraction, and the half that is left carries a behavioural cost the plan did
not know about.**

**The two destination buttons are not dropped, and dropping them now would
re-open the regression #176/#177 just closed.** Proposal §4.1 marks L-F17
(Course) and L-F18 (Research) `DROPPED — one destination`. That premise is true
of those two *buttons* and false of the *row*. #177 (`162dff5`) re-pointed the
slots rather than deleting them: the row now offers **Project** →
`#/p/<id>` (`ProjectList.tsx:371-379`) and **Ask** → `#/p/<id>/ask`
(`ProjectList.tsx:387-398`). Ask is not a MATERIAL facet — `App.tsx:138`
intercepts it above `ProjectView` — so a reader who opens the project and clicks
through the tabs never reaches it. **The overflow slot is the only
non-typed-URL door to the ask page.** §4.1 as written is an instruction to
reintroduce a shipped regression, and correcting it is the first thing a slice-4
implementer should do.

**Re-sourcing the chip is a swap, not a subtraction, and it degrades one
label.** `2N` is verified: `useProjectActivity` issues exactly two queries per
drawn row (`ProjectActivity.tsx:37-48`, called at `ProjectList.tsx:254` with
`enabled` hardcoded `true`). The roster genuinely carries every worker kind the
chip cares about, by construction — `WorkerRoster.everywhere()` is literally the
same fold as the per-project route (`workers.py:420`). What it does **not**
carry is the thing the chip's first branch draws: the roster's `run` worker has
`detail="autonomous run"` and `started_at=None` (`workers.py:296-303`), no
rounds and no start time, so `run · round N` becomes `run running`.

**Decide this before touching `ProjectActivity.tsx` rather than discovering it
mid-slice.** Three honest answers: (a) accept the degradation — the chip's job
is "something is happening" and the round count is one click away; (b) widen
`Worker` so a `run` kind carries `rounds` and a real `started_at`, which is a
**second** backend change in an increment whose §4 is titled "the one backend
change", and must be said out loud if taken; (c) keep `/auto-research` for the
run only, halving `2N` to `N` — worst of the three, because it retains the
per-row N+1 and the `saysDisabled` regex §4 exists to delete. **Recommendation:
(a) for this slice, with (b) filed.**

**Two corrections to the cost arithmetic, both making the current cost larger,
and one making the saving smaller.**

- **"Drawn" is wider than "visible."** `ProjectRows.tsx:112` passes
  `overscan={4}` and the virtualized array interleaves recency headings with
  rows (`ProjectRows.tsx:41-57`). At 8 visible rows the mounted count is up to
  ~16, i.e. up to ~32 per-row requests. Proposal §6.1's `D = 8 → 21` is a floor.
- **The `2N` is re-paid on every debounced log burst**, not once per load.
  `useTreeRefresh` invalidates the `allWorkers()` and `allRuns()` *prefixes*
  (`App.tsx:172-173`) and the per-row keys sit under them (`keys.ts:29-30,
  38-39`). While anything is running, that is `2N` every 400ms window, forever,
  on a page a reader leaves open. This is the strongest argument for the swap and
  neither document makes it.
- **The saving is larger than "one request replaces `2N`", because the one
  request is already being made.** Proposal §6.1 says `/api/workers` costs a
  request "once the dock has ever been opened". It is not gated:
  `use-running-agents.ts:58-62` runs the roster query unconditionally and
  `AgentWidget` is mounted in the shell on every route (`App.tsx:94`); only the
  project-*names* query is `enabled: expanded` (`:76-81`). It also shares a cache
  entry — `queryKeys.runningAgents()` sits under the `allWorkers()` prefix
  deliberately (`keys.ts:40-46`). So re-sourcing the chip adds **zero** requests.

**Also unowned, and cheap:** `Workers.tsx`'s unconditional 2000ms poll
(`Workers.tsx:9, 36`) was supposed to die with the merge per proposal §6.2. It
did not, and #170 carried it onto the merged page via `QueueHeader.tsx:6-7` — so
the poll runs every two seconds on the page §6.2 itself calls "the page you leave
open all day". `RunPanel`'s 2000ms poll is correct to stay: a run's counters are
folded from its own aggregate and are not on the stream. Replacing `Workers`'
with a `useFrameRefresh` on `queryKeys.workers(projectId)` belongs in a slice and
is currently in none.

**Sequenced last, but no longer because it is pure subtraction.** It can still
be dropped safely without leaving anything half-built; the reason given is no
longer the reason.

---

## 3. What breaks, precisely

### 3.1 URLs

**[audit 1, F9] The middle column used to be headed "Today, at `f87443b`" and
described the pre-slice-0 world; that commit is now six merges back and four of
the "After" states have shipped. Re-headed and rewritten at `9fa6c7b`, with the
missing `ask` row added.** Leaving a "Today" column dated to a commit nobody is
on is how this plan was wrong three times before.

| Pattern | At `9fa6c7b` | Still owed |
|---|---|---|
| `#/p/<id>/course` | **already dead** — `home` (`routes.ts:130-133`, asserted `routes.test.ts:133`) | nothing: still `home` |
| `#/p/<id>/research` | **already dead** — `home` | nothing: still `home` |
| `#/p/<id>` | `ProjectView`, no selection, MATERIAL on `artifact` (`App.tsx:145`, `ProjectView.tsx:127`) | **shipped** |
| `#/p/<id>/ask` | intercepted above `ProjectView`, renders `AskView` (`App.tsx:138`) | **shipped** — absent from this table until now |
| `#/p/<id>/entity/<eid>` | MATERIAL Graph tab, entity selected (`ProjectView.tsx:438-447`) | **shipped** |
| `#/p/<id>/stage/<sid>` | QUEUE, stage open (`:277`) | **shipped** |
| `#/p/<id>/session/<sid>` | HOLDER (`:299-383`) | **shipped**; a region-level error state (§2.2) |
| `#/p/<id>/file/<path>` | MATERIAL Workspace, path open (`:411-425`) | **shipped** as an entrance; no click writes a `file` selection (§2.0) |
| `#/p/<id>/topic/<tid>` | **QUEUE**, topic row *not* selected | the row selection — §2.1b, not slice 3. This row used to say "MATERIAL `topic`" |
| `#/p/<id>/doc/<sid>` | MATERIAL Documents tab, document *not* selected | the selection — slice 3 owes the item, not the tab |
| `#/p/<id>/artifact/…`, `/finding/…` | MATERIAL tab opens, **id ignored** | the selection — slice 3 |
| `#/s/<id>[/at/n][/file/p]` | the session view | **unchanged** (`routes.ts:116-119, 193-204`) |

**The proposal's §3.3 facet names are tab labels, not URL segments.** `workspace`,
`artifacts`, `corpus`, `graph` and `findings` appear nowhere in a URL; the
segments are `file`, `artifact`, `doc`, `entity`, `finding` (`routes.ts:67-80`),
and `MATERIAL_TABS` (`ProjectView.tsx:119-125`) is where the two vocabularies are
mapped. **Wherever the two documents differ, the code's segment wins.**

**A bookmark to `#/p/x/course` already lands on the picker today** and has since
`cebc89a` (#127). Increment C does not break it further. A bookmark to
`#/p/x/entity/abc` survives the merge and lands on the same entity in a
different container. **The three facets that parsed and rendered nothing when
this was written have become one facet that does (`file`, slice 2) and two that
open a tab and select nothing** — which is halfway from silent to correct, and
is still the only URL behaviour in this table that improves.

### 3.2 Stored pane preferences

Four keys exist today, all under `rt.collapsedPanes.<group>`
(`infrastructure/storage/preference-store.ts:6`), all holding a JSON array of
pane ids, all read through a `try`/`catch` that returns `[]` on anything
unexpected (`:16-25`).

| Key | Written by | Ids | Fate |
|---|---|---|---|
**[audit 4, finding 6] Mechanism accurate, fates stale. Re-measured at
`9fa6c7b`; there are five keys, not four.**

| Key | Written today by | Ids | State |
|---|---|---|---|
| `rt.collapsedPanes.session` | `useSessionPanes` (`use-session-panes.ts:37`), only from `SessionView.tsx:58` | `timeline`, `workspace`, `conversation` (`:21-25`) | **survives**, `#/s/` only — as predicted |
| `rt.collapsedPanes.project` | `useProjectPanes` (`use-project-panes.ts:52`), from `ProjectView.tsx:165` | `queue`, `holder`, `material` (`:42-46`) | **new** — not in this table when it was written |
| `rt.collapsedPanes.course` | **nobody** — `CourseView` is deleted | `stages`, `artifacts` | **orphaned now**, not "dies with slice 1" |
| `rt.collapsedPanes.research` | **nobody** — `ResearchView` is deleted | `seeding`, `topics`, `documents` | **orphaned now**, not "dies with slice 3" |
| `rt.collapsedPanes.agents` | `AgentWidget.tsx:49` | inverted — a stored name means *open* | untouched; proposal §5.3's un-inversion is still undone |

**So slice 3 has no preference work left**: slice 1 orphaned `course` and the
`ResearchView` deletion orphaned `research` ahead of schedule. The advice below —
a new group string, keys left behind rather than migrated — was taken, and
`use-project-panes.ts:4-18` records it.

**What a reader with stored preferences experiences: their panes open once, and
nothing else.** A stale key naming ids the new page does not have is not merely
harmless, it is *specifically* handled: `toggleCollapsed` uses `>=` rather than
`===` on purpose, "because a caller can hand in a collapsed set naming a pane
that no longer exists, and an equality check would let the last real pane close
on the strength of a stale entry" (`split-tracks.ts:98`). So a stale `course` set
cannot lock a reader out of the new page.

**[audit 4, finding 6] That argument is half right, and the missing half is the
sharper one — worth correcting because it will be reused.** A stale set cannot
lock a reader out of the *page*. It can lock them out of collapsing
**anything**: stale ids are never filtered on the way in
(`use-split-panes.ts:30-32`) and they count toward `tracks.length`, while
`splitTemplate` (`split-tracks.ts:50-56`) ignores unknown ids only when
*emitting*, not when counting. So a group carrying two stale names against three
tracks refuses **every** collapse the reader asks for, with the toast "At least
one pane has to stay open." (`use-split-panes.ts:43`) — a sentence that is false
in that state. This does not bite today precisely because the `project` group
string is new and no reader has a set under it. It would have bitten had
`course` been reused, which makes the recommendation below right for a reason it
did not give: reuse would have been a **live defect**, not a cosmetic one.

**Even so, use a new group string for the project page — `project` — rather than
reusing `course` or `session`.** The proposal's §5.3 asks for "a deliberate key
rename rather than a silent reinterpretation, so a stale value reads as absent
rather than as its opposite", and that reasoning is right and free here.
Deleting the dead keys is not worth code: `preference-store.ts:3-5` already
records the precedent — the old single `rt.collapsedPanes` key was "left behind
rather than migrated", because it holds a pane layout and the project is
pre-release.

### 3.3 Behaviour

- **The topic dialog stops being a modal.** **[audits 1 and 4] It does not
  "become the MATERIAL `topic` facet" — that half is withdrawn; `topic` is
  QUEUE and that is now decided (§2.3).** The dialog is still a modal and is now
  a modal *inside* QUEUE: `TopicList.tsx:42` renders `TopicStatusDialog`,
  mounted at `ProjectView.tsx:283`, so it moved onto the merged page unchanged
  rather than dissolving into it. What is still wanted is demodalising it — a
  change to the dialog, opened from a QUEUE row, not a change to `regionOf` and
  `MATERIAL_TABS`. Phase-1 of `check-deleted.mjs` records that its hand-rolled
  focus trap was already deleted in favour of the overlay host, so the loss is
  smaller than proposal §5.2 priced it: what goes is modality, not the keyboard
  contract. **The mandatory-justification form should stay a `Confirm` inside
  the pane**, and this work belongs with §2.1b.
- **Three regions share one selection, so selecting in one region resets the
  other two.** **[audit 4, finding 1] Not previously recorded anywhere, and it
  is a real cost of the merge that neither page it replaces paid, because
  neither had a second region to disturb.** `Selection` is one value
  (`routes.ts:96-104`) and all three regions derive from it: HOLDER's scrub point
  is `selection.at` only on a `session` selection (`ProjectView.tsx:204`),
  MATERIAL's open file is `selection.id` or `selection.path`
  (`:176-181`), and MATERIAL's open tab falls through to `DEFAULT_MATERIAL`
  (`:221-226`). Mechanically: **clicking any event in HOLDER closes whatever
  MATERIAL tab the reader was on** — `screen.selectEvent` writes
  `sessionSelection(sessionId, at, path)` with a null `path`
  (`use-session-screen.ts:133-138`, `ProjectView.tsx:193-199`), which snaps
  MATERIAL back to Artifacts. **The same keypress does it from anywhere**, since
  the Escape-to-live listener is `document`-level (`use-session-screen.ts:155-165`).
  **And selecting a stage in QUEUE discards HOLDER's scrub point and MATERIAL's
  open file** (`:277-279` produces a selection that is neither `session` nor
  `file`). `ProjectView.tsx:216-220` reasons carefully about the *first* arm of
  `materialTab` and does not notice the third has the same shape of failure.

  **Resolved: a region-internal move never rewrites the facet.** Carry the scrub
  point on whatever facet is current rather than forcing `facet: 'session'`.
  That is a `routes.ts` change, so it is a **prerequisite of slice 3 and not a
  detail inside it** (§2's ordering) — slice 3 is the slice that gives MATERIAL
  five tabs worth losing. The rejected alternative was a selection *per region*
  in the URL; it was rejected because keeping the grammar one value costs one
  change here rather than a change to every parser, builder and test that reads
  `Selection`, and nobody has asked for two regions addressed independently in
  one link.
- **The worker drawer stops being how you watch a worker in this project.**
  Selecting it in QUEUE opens it in HOLDER — shipped, and pushed rather than
  replaced, correctly (`QueueHeader.tsx:108`, `ProjectView.tsx:263`). The drawer
  does **not** stop being the other way: see §2.2 on the narrowing that was
  never built.
- **The run panel and extraction pane move off the course page.** Shipped, and
  further than described: `QueueHeader.tsx:107-125` holds `Workers`,
  `ExtractionPane`, `RunPanel`, `SeedPanel` **and `AutonomyPanel`**. Muscle
  memory is the cost; §8.2 and §8.3 of the research survey are the benefit.
- **The per-tool autonomy panel went to QUEUE, not to the decision bar, and
  proposal §3.4 is therefore half shipped.** **[audit 1, F11; audit 4, finding
  8]** Approvals did move into the shell — `DecisionBar` is mounted in `Console`
  above `CurrentView` (`App.tsx:112`), on every route, with §3.4's argument
  carried verbatim in the comment at `:107-111`. Autonomy did not: only
  `AutonomyAllowAll` reached the shell (`DecisionBar.tsx:69`), which is the
  per-approval button, and `AutonomyPanel` — the instance-wide policy control —
  is a QUEUE card (`QueueHeader.tsx:123-124`), on one project's page. That
  contradicts §3.4's own argument that "a policy that governs every session in
  the process sitting inside one project's page is a scope claim contradicted by
  its own placement", and it leaves §3.4's stated seam open: the two halves are
  now in two regions of two components, which is the same duplication at a
  longer distance. **Decide before slice 3: move the panel to the shell beside
  `DecisionBar`, or strike §3.4's autonomy paragraph.** This is genuinely the
  owner's call and it is recorded here as open rather than resolved — but do not
  leave both texts standing. `QueueHeader:124` gates the panel on
  `holdingSessionId`, which makes it read as a control on *this holder*, which
  is not what `AutonomyPolicy` is.
- **The breadcrumb still offers `course` and `research`.** **[audit 1, F2]**
  `Breadcrumbs.tsx:90-92` renders two links to one destination under two names
  the console no longer uses, differing only in which MATERIAL tab opens. This is
  `8fe734c`'s finding — "offering one destination twice, under names the console
  no longer uses, describes a shape that no longer exists" — surviving in a
  second file, because that fix was scoped to the ask page's own nav. It renders
  on the standalone `#/s/` route (`:88`, gated on the session's `projectId`),
  which is why no project-page test sees it. Collapse to one `project` link in
  the slice that touches the breadcrumb; the entity facet is one tab away.
- **`SessionView` stops owning a `Split` on the project route** while keeping one
  on `#/s/`. Two renderings of one component with different layout ownership is
  a real complexity cost and I would not pretend otherwise; the alternative is a
  nested `Split`, which is worse for the reasons in §2.2.

### 3.3b Features that lost their home, found by walking the surveys

**[audit 2, finding 4] Proposal §4.5 says "nothing is unplaced". Four things
were placed in the document and are absent from the page, and the three
regressions already shipped and repaired (`RunPanel`, `SeedPanel`, the ask
page's inbound links) were all of this shape.** Recorded here rather than only
in an audit, because the next slice is the cheapest place to fix them:

- **C-F1 — the preset's name. Gone, with no replacement.** `CourseView.tsx:63`
  rendered `course.data?.preset.name ?? 'Course'` as the page title.
  `preset.name` is now read in exactly one place in `presentation/`,
  `NewProjectForm.tsx:122` — the create-a-project dropdown. **A reader on a
  project page cannot see which workflow the project is running.** The
  breadcrumb shows the project's own name (`Breadcrumbs.tsx:35`), a different
  fact.
- **C-F2 — the position subtitle, and the `position === null` sentence. Gone.**
  `Stage N of M · <presetId> v<version>` was `CourseView.tsx:227-232`;
  `course.position` is read nowhere in `presentation/` now. The lost half that
  matters is the other branch — *"This project's recorded stage is not part of
  `<presetId>`, so its position is unknown."* That sentence was the **only**
  surface telling a reader their project sits at a stage the installed preset
  has dropped, a state `composition.py` tolerates and which
  `features-course-view.md` D12 records as uncorrectable. Proposal §4.3 lists it
  as explicitly kept.
- **C-F56 — the artifact pane's `N of M written` count. Gone**, and the honest
  reason is that a `Tabs` label cannot carry a count the way a `Pane` header
  could (§2.3). QUEUE kept its analogous meta (`ProjectView.tsx:249-253`), so
  this reads as an oversight rather than a decision.
- **R-F2.2 — `SeedingRun.reply`. Still unrendered.**
  `domain/research/seeding.ts:18` carries it and no component reads it.
  Proposal §4.2 marks it *surfaced* in QUEUE. Not a regression — it was
  unreachable before too — but it is one of the cheap unlocks the proposal
  counted, and slice 1 moved `SeedPanel` without taking it.
- **C-F4 — "Open holding session". Gone, defensibly, and undocumented.**
  Proposal §4.3 drops it ("HOLDER *is* the holding session"), which is right for
  reading the transcript. What it also removes is the only door from a project to
  the standalone `#/s/<id>` route that §2.2 deliberately keeps alive. That route
  is still reachable from the landing page, `WorkerDrawer.tsx:97`,
  `RunPanel.tsx:193` and `Artifacts.tsx:161` — but not from the project page for
  the project's own holding session. "HOLDER is the session" and "`#/s/` stays
  top-level because a transcript read alone is still three panes" are both true
  and in tension; this is where the tension shows.

**Checked and cleared, so nobody re-files them:** `RailPane`'s unmount-on-fold
(R-F1.1) is preserved, because Radix unmounts the closed panel (`Tabs.tsx:96`)
and `DocumentList`'s virtualizer still never measures a zero-height scroller;
`WorkerDrawer` (C-F39–F45) survives via `AgentWidget.tsx:185`; the topic dialog,
`SubQuestions` and `TopicDocuments` (R-F4.1–F4.4) all still render from
`TopicList.tsx:36-40`; C-D7 (findings vanishing when empty) is fixed by
`ProjectFindings` (`ProjectView.tsx:477-485`); and the `chip-${tone}` passenger
was rescued before `course.css` was touched (§2.1).

### 3.4 Event shapes

**Nothing.** The proposal's §5.5 claim holds and I re-verified the part that
could have drifted: `domain/approval/approval.ts` and `dto.ts` already carry the
two fields that were the only contract widening the proposal asked for, and they
landed as an additive change. `CLAUDE.md`'s schema-evolution rule is not in play
for any slice here.

---

## 4. §6.3's one backend change

**It is `GET /api/capabilities`, it does not exist, and it touches no event and
no read model.**

Verified, and still true: no capabilities route exists anywhere in
`research_team` or `frontend/src`, and none of it has landed.

**[audit 5, A2] Every line citation in this section was correct at this plan's
base `f87443b` and is wrong at `HEAD` — `app.py` has grown 176 lines since — and
the inventory was incomplete in one place that costs more than the drift.**
Re-measured at `9fa6c7b`:

> The 503s are `app.py:706` (corpus), `:758` (topics), `:789` (seeding), `:886`
> and `:949` (dispatch), `:986` (topic write model), `:1092` (graph), and
> `:1451`/`:1523` (**ask**). The 404s are `:1331` and `:1409` (autonomous runs),
> `:1359` and `:1376` (worker roster), `:1858` (approvals) and `:1886` (the
> autonomy policy).

**The ask 503s are the addition that matters.** They did not exist at `f87443b`
— the ask route landed in `e212efb`, after this plan's base — and #177 has since
given **every project row a button to the ask page**. In a build with
`ask=None`, that button now opens a page that draws fine and fails only after
the reader types and submits a question: `AskPage.tsx:47-50` renders the 503 in
a generic `role="alert"` box at the bottom of the thread. That is proposal
§6.3's own argument — "a page needs to know which of its regions can exist
before it draws them" — with a better example than any it lists. The approvals
and autonomy-policy 404s were missing from both documents too.

The client-side hack it replaces is one line, now at
`infrastructure/http/project-repository.ts:83` (this section said `:94`):

```ts
const saysDisabled = (message: string): boolean => /not enabled|AGENT_RESEARCH_RUN/.test(message)
```

used at `:95` and `:107` — **two sites, not the three** this section listed at
`:105-107` and `:117-119`. Note that this regex would also match the
worker-roster message if that detail ever reached the same call path — which is
the argument for the route stated more sharply than the proposal states it.

**It touches no read model.** `read_models.py` holds only the session-summary
and corpus projections; a capabilities answer is a pure function of which
`create_app` parameters are non-`None` (`app.py:379-398` lists fifteen such).
**So CLAUDE.md's rule about verifying against a database that predates the change
does not bind this work.** I flag it anyway because the brief asked me to and
because getting the *reason* right matters: the rule is dormant here not because
anyone judged the risk low but because there is no schema in the change. If a
later slice adds a column — and none of the slices in §2 do — the rule binds, and
its executable form is `uv run python -m
research_team.infrastructure.persistence.local_copy`, **available once PR #158
merges and not before** (§0).

**What will bite when it is built:** `tests/interfaces/test_web_entrypoint.py`
parses `web.py` with `ast` and asserts that every `create_app` parameter is
passed at the entrypoint, and separately that no argument is a literal `None`. A
new `capabilities` parameter fails both tests until `web.py` passes it as
something other than a bare `None`. That is the test working, and it is exactly
the "wrong in `main.py` and green everywhere" failure the proposal's §6.3
anticipated.

---

## 5. The hazards this repository has already paid for

### 5.1 The combinator hazard, applied

`component-system-spec.md` §11 states it: a `>` or `+` selector is a claim about
DOM shape, and rewriting markup to utilities while leaving the stylesheet in
place breaks that claim **with no test failure and no error**. Its actionable
form is "grep a stylesheet for `>` and `+` before touching the markup it
dresses". The spec's counts (research 10, responsive 9, conversation 8, course
6, tree 3) are from an earlier commit. **Here is the current inventory, measured
at `f87443b` by a script over the CSS with comments stripped** — and the
disagreement with the spec is worth noting rather than smoothing over:

**[audits 2 and 3] Re-measured at `9fa6c7b`, comments stripped, `>`/`+`/`~` in
selector preludes only. The `f87443b` table it replaces is kept beside it,
because the direction of the drift is the finding: slices 1 and 2 deleted their
own hazards and slice 3's headline hazard no longer exists.** Two internal
inconsistencies in the old table are corrected in passing — the
`conversation.css` row printed 7 against 8 line numbers and the `course.css` row
printed 4 against 5.

| File | Said at `f87443b` | Actual at `9fa6c7b` | Which slice invalidates them |
|---|---|---|---|
| `conversation.css` | 7 | **8**, at `:48, 53, 56, 184, 190, 193, 309, 317` | **slice 2** — `.msg-body > .md`, `.run > .disc-head`, `.discarded > .disc-head` |
| `research.css` | 7 | **0** | none — all seven went with `ResearchView` in slice 1 (`c1fbc6c`) |
| `responsive.css` | 6 | **3**, at `:12, 25, 73` | **slice 2 only** — see below |
| `course.css` | 4 | **2**, at `:452, 467` | both `.autonomy-disclosure[open] >`, i.e. the `AutonomyPanel` passenger, which moved without them |
| `timeline.css` `:41, 212`; `tree.css` `:293, 303`; `components.css`, `structure.css` | 2 each | 2 each | `timeline.css` in slice 2; the rest survive |
| `composer.css` `:77`, `markdown.css`, `workspace.css` `:18` | 1 each | 1 each | `composer.css` and `workspace.css` in slice 2 |
| `layout.css`, `entity.css`, `states.css`, `agents.css`, `shell.css`, `tokens.css`, `theme.css` | 0 | 0 | — |
| **total** | — | **24** | |

**One correction to the spec's own measurement, since a plan that inherits a
wrong number propagates it.** `component-system-spec.md` §11 says "`+` is nearly
absent, one each in `states.css` and `agents.css`". There is **not a single `+`
combinator in the directory** — every count above is `>` only. The spec's
higher per-file counts (research 10, conversation 8, course 6) are `>`
characters inside comment prose and inside `@media (width >= 821px)` range
syntax, which a naive grep cannot tell from a combinator. The hazard is real and
the instruction — grep before touching the markup — is right; the numbers are
smaller than stated.

**`responsive.css` is the dangerous one and it is dangerous for a reason no
count expresses.** It is the one shared file coupled to view-specific class
names, and its combinators name *another* view's markup from inside a media
query. **[audit 3, F3] This paragraph used to name five such rules and conclude
"each of slices 1, 2 and 3 silently voids a rule in a file it is not touching".
Slices 1 and 3's exposures are gone — slice 1 deleted
`.lay-split[data-split='course'] > …`, `.research-workbench > [data-pane='graph']`
and `.research-rail > …` along with the views, and `check-deleted.mjs` phase C0
(`:346-356`) now forbids their return.** What remains is three:
`.lay-split[data-split='session'] > [data-pane='conversation']` at `:12` and
`:25`, inside `@media (width >= 821px) and (width < 1181px)`, and the tree's
`ul.tree ul > li:last-child::after` at `:73`. **Only slice 2 voids anything
here, and it voids both session rules at once** — at a viewport no default window
is at, which is why the grep is the whole mitigation. A browser test at the
default viewport cannot catch it, because `vite.config.ts` sets the viewport and
the media query reads *that*. The instruction is unchanged and still right:
every slice that deletes a view greps `responsive.css` for that view's selector
first. There is no test that will do it.

`check-deleted.mjs` cites `.extraction-failed > .extraction-summary` as this
failure having already happened once, "no test, no error, just a rule that
quietly stopped applying". This is not a hypothetical hazard in this repository.

### 5.2 The clipped focus ring

The global `:focus-visible` is 2px at `outline-offset: 1px`
(`tokens.css:340-341`; this section cited `:294`) — three pixels *outside* the border box. A child that fills an
unpadded scroller has its border box coincide with the scroller's padding box,
and `overflow` clips at the padding box, so **the entire ring is thrown away**.

This has been paid for three times and each fix carries its measurement:
`workspace.css:10-25` (the file list, "measured, not reasoned —
`FileList.browser.test.tsx` is the measurement"; at 1440×900 not one pixel of
the ring was inside the clip), `research.css:502-521` (the document row; every
row lost its sides, the first kept a 2px line along its bottom), and
`agents.css:198`. All three fixes are the same: `outline-offset: -2px`, drawn
inward.

**Where it bites in these slices:** MATERIAL is by construction a pane holding
a scroller holding full-width selectable rows — six times over. Every one of the
six facets reproduces the exact geometry that produced the defect three times,
and slice 3 builds five of them at once. QUEUE reproduces it once, with five row
kinds in it. **Any full-width focusable row inside a region's scroller needs
`outline-offset: -2px` at the point it is written, not after somebody notices.**

**And the geometry is already inherited rather than chosen.**
`layout.css:221-225` declares `.lay-pane-body { overflow: auto }` with **no
padding**, and that is the primitive under every region of every view — so the
project page's three panes start life as three unpadded scrollers.

**[audit 3, F5] The two exposures this section named are real files with real
`padding: 0`, and neither is the full-width-row shape the three fixes above
measured. The description was wrong even though the mechanism is right.**
`.topic-list` is at `research.css:81-92` (cited here as `:203-214`) and its rows'
only tab stop is an inline `<a>` inside `.ent-topic-question`
(`TopicRow.tsx:109-126`; the `<li>` itself is not focusable). An inline link is
text-width, so the horizontal clipping the prior fixes measured does not apply
the same way — the plausible loss is the vertical ring on the first and last
row. `.extraction-merge-list` is at `course.css:479-488` (cited here as
`:509-518`) and has **no focusable child at all**: `ExtractionPane.tsx:159-167`
renders `<li className="extraction-merge">{line}</li>` with no link, no button
and no `tabIndex`. What it exposes instead is the Chromium
focusable-scroll-container trap that `research.css:337-347` records, which is a
different defect whose fix is an inward ring on the *scroller*, not on a row.
**Both are unmeasured, and the fourth prior fix — `research.css:337-347`, the
scroll-container trap, measured at 1440×900 — should be counted alongside the
three above.** The instruction that matters for the slices ahead is unchanged
and correct: any full-width focusable row inside a region's scroller needs
`outline-offset: -2px` at the point it is written. Two more exposures are
marginal rather than broken —
`.graph-results-panel` (`research.css:678-684`) and `.graph-detail-edges`
(`:853-861`) both carry `padding: 4px` against a 3px ring, a 1px margin with no
slack.

### 5.3 jsdom lays nothing out

`CLAUDE.md` is explicit: `scrollHeight` is 0 everywhere, `getComputedStyle`
returns only what an inline style said, and a selector matching nothing is
indistinguishable from one matching. `npm run test:browser` is outside `verify`
and outside CI, so nothing forces anyone to run it.

**Everything in §5.1 and §5.2 is a measurement, so none of it is judgeable in
`vitest`'s jsdom suite.** So is `splitTemplate`'s output — a test can assert the
string and never that the grid it describes is right (`split-tracks.ts` says so
itself). **Every slice in §2 must run `npm run test:browser`, and slices 1, 2 and
3 should each add a browser test**: a focus-ring measurement per new scroller,
following `FileList.browser.test.tsx`, and a region-width assertion at each of
the three responsive layouts. Two things learned the hard way and recorded in
`CLAUDE.md` will cost half an hour each otherwise: the viewport is set in
`vite.config.ts`, not by the wrapper a test renders into; and
`vitest.setup.browser.ts` is a separate file because the jsdom setup pins
`offsetWidth`/`offsetHeight` to constants.

### 5.4 Two hazards specific to this work

**The committed bundle.** `ui-foundations.md` §4.3 records that the built output
is committed to this repository (`vite.config.ts` builds into
`research_team/interfaces/web/static`), so every slice lands a large committed
diff. Land it in its own commit, the way `component-system-spec.md` §12
recommends for the Prettier reflow, or the real change is invisible in review.

**No presentation coverage floor.** `ui-foundations.md` §4.3 records that
`src/presentation/**` has no per-layer coverage threshold, deliberately. **So
the ratchets will not notice a slice that adds components without tests.** The
net that §1 says now exists under `presentation/session/` will not extend itself
to `presentation/project/`; somebody has to write it.

---

## 6. What is genuinely uncertain

Separated from the decided, because a plan that hides its unknowns is worse than
one that lists them.

1. **Whether QUEUE ranks across row kinds or groups by kind.** The proposal's
   §11 open question 3 takes the ranked arm and says it is the part of §3.3 it is
   least sure of, "because there is no evidence about which one a real queue of
   forty topics and fifteen stages reads better". I have no evidence either. The
   cheap resolution is that the *row union* and the *ordering function* are
   separable — build the union in slice 1, make the ordering a pure exported
   function with a test, and the question becomes a one-file change rather than
   a design commitment. **[audit 2] Still open, and it is not merely unresolved
   — it is unstarted: the union was never built (§2.1a). The cheap resolution is
   still available at full price, which is the one good thing about the delay.**
2. **Whether MATERIAL's five facets are `Tabs` or a listbox.** `Tabs` exists and
   has both a jsdom and a browser test, so it is the cheap answer, but five tabs
   with one of them lazy-loading 60 kB is not obviously what `Tabs` is for.
   **[audit 2] Partly resolved by shipping: `Tabs` is in, it works, and it has
   cost one visible count (§2.3's last paragraph) because a tab label is not a
   `Pane` header. The remaining question is not `Tabs` versus listbox, it is
   where the per-facet meta goes.** ("Six facets" was this plan's count when
   `topic` was thought to be MATERIAL's; it is five.)
3. **What `PROJECT_TRACKS` should be.** I have no measurement. Three peer
   columns is what `SESSION_TRACKS` uses, but QUEUE is a list, HOLDER is prose
   and MATERIAL is documents, and there is no reason to think they want equal
   weight. **This is exactly the kind of number that must be measured in the
   browser suite rather than reasoned about**, and `split-tracks.ts`'s own
   docstring is a record of what happens when two declarations of three columns
   are never read side by side. **[audit 4] Still open, and
   `use-project-panes.ts:22-41` says so in its own docstring ("chosen, not
   measured"). Slice 2's report deferred it to slice 3 on the grounds that
   HOLDER now has real content; that is the right slice, so it is named here as
   slice-3 scope rather than left as a standing uncertainty. Deferred a third
   time, it will be deferred a fourth.**

   **ANSWERED 2026-08-14, on the sixth attempt — and the answer arrived with a
   defect attached.** The deferrals above are kept rather than tidied away,
   because the shape of this one is the argument for measuring anything: five
   slices each judged the measurement worth doing later, and what it found was
   not a number that could have gone either way.

   At **1181px** — the narrowest viewport where a `Split` writes a template at
   all — the fr shares were 337 / 506 / 337. MATERIAL's 337 had to hold a
   five-tab strip that is **351px wide and neither wraps nor scrolls**, so the
   Graph tab was painted past the pane's right edge: **present and
   unclickable**. QUEUE's 317px seeding form went the same way 14px later. The
   page had only ever been looked at at 1440, and 1440 was never the width that
   was wrong — which is why five deferrals cost nothing visible and the sixth
   found a shipped defect.

   `PROJECT_TRACKS` is now **`queue 344 / holder 342 / material 352`**, measured
   in Chromium on 2026-08-14, replacing 280 / 320 / 280 — the session view's
   floors, adopted here without measurement. **1440 is pixel-identical before
   and after**; only the bottom of the wide band moves. Reweighting was rejected
   as buying the same clearance by reshaping every width above 1181 to fix its
   narrowest 60px. HOLDER's 342 does not bind today and is recorded anyway.

   So this question's own framing — "three peer columns, or not" — is answered
   sideways: the weights were never what was wrong, and they are **still
   reasoned rather than observed**. The floors say where a region breaks; they
   say nothing about where it is good. `use-project-panes.ts`'s docstring now
   states which half is which, in the shape `SESSION_TRACKS` uses. What remains
   open is in `BACKLOG.md` B57, which is kept rather than closed for that
   reason. Reports: `docs/reports/measured-task-b.md` (widths) and
   `docs/reports/measured-task-a.md` (the 821–1180 band, which turned out to
   have no layout at all).
4. **Whether `SessionView` can serve two layout owners cleanly.** §2.2 assumed it
   could — that the `Split` lifts out and the component renders into whatever
   region it is given. I did not prototype it. If it could not, slice 2 would
   have grown a duplicate transcript component, which would have been the worst
   outcome in this plan. **[audit 4] RESOLVED — it can, and it did not.** One
   hook, one panels module, two arrangements (`use-session-screen.ts:26-56`,
   `panels.tsx:20-35`). What remains is four small call sites of duplication,
   not a component, and §2.2 lists them — including the one that matters, the
   verbatim end-session `Confirm` copy.
5. **Whether the picker survives at all.** The proposal's §11 open question 2
   asks whether `#/` deserves a page or should be a shell-level switcher. §2.4
   assumes it survives. I have not tried to settle it and slice 4 is where it
   would be settled.
6. **Whether the dated feature surveys still describe the code.** Every `C-F*`,
   `R-F*`, `S-F*` and `L-F*` id in §2 came from documents read at `5a5a7cf`. §1
   demonstrates that three months of that survey has already gone stale in ways
   that mattered. **Re-verify any feature id before building against it**, which
   is the same instruction §0 gives and the one most likely to be skipped.

---

## 7. What this plan does not decide

- **A route to `StageRunner`.** Unchanged from proposal §10: `Worker.kind`
  already includes `'stage'` and QUEUE renders workers, so the seat is reserved
  and no frontend work is owed the day a route exists.
- **`send_back` and `halt` as answerable decisions.** Declined in proposal §5.4
  because three of five `Decision` values cannot be written to the log. The
  decision bar already renders them as named-and-unavailable; nothing here
  changes that.
- **The timeline/conversation merge.** Proposal §11 open question 4 suspects it
  deserves its own document, and §6.4 prices it as a rewrite of
  `segmentTranscript` and `Timeline`. **It is not in any slice above**, and slice
  2 should re-parent both without merging them. Merging them inside the slice
  that also dissolves a `Split` would be two rewrites verified as one.
- **Timeline virtualization.** Open PR #158 declines it on evidence — the longest
  real log measured was 195 rows against a virtualizer that starts paying in the
  thousands. Proposal §6.4 lists it as work that must be built; **that entry is
  superseded** and should not be planned for.
- **`/api/projects`'s O(projects) fold.** Still the standing cost, still not
  fixed here. §2.0's invalidation fix makes it survivable on a long-lived page;
  it does not make it cheap.

---

## 8. There is no increment D — what follows C, and who owns it (2026-08-14)

Increment C is complete: slices 0, 1, 2, 3, 3a, 3b and 4 have all shipped and
merged. **A reader arriving here looking for the next increment will not find
one, and that is a fact about the corpus rather than a gap in this document.**
The overhaul defines increments only to C — A is the decision bar
(`unified-ui-proposal.md` §9), B is the floating layer (the component-system
spec's phase 3), C is the route merge, which is this plan. Nothing anywhere
defines a D.

Recorded here rather than in the proposal because the proposal is the design
argument, frozen at its own date and already annotated by §1 above; this is the
plan a reader finishes, and the question "what now?" is asked at the end of it.

**Do not invent an increment D to hold the list below.** Naming the residue is
the point. It is ungrouped on purpose: these items do not share a theme, a
surface or a budget, and grouping them would manufacture a plan that no survey
supports. Each is a slice-sized decision for whoever picks it up.

**A decoy, flagged because an audit already lost time to it.**
`ui-foundations.md:1014` and `:1021` say "Phase D — the course surface" and
"Phase E — the session surface". Those belong to the *foundations* phase scheme,
not to the increment scheme. One letter, two vocabularies.

The residue, as surveyed on 2026-08-14 — verified against the code on that
date, so re-check citations before building:

- ~~**`BACKLOG.md` B57 — the project page's three region widths.**~~ **Measured
  on 2026-08-14** by the slice
  `docs/superpowers/plans/2026-08-14-the-page-nobody-measured.md`, which also
  answered §6 question 3 above and found a shipped defect doing it. **Partly
  residue still:** nothing below 821px was measured, the wrapped row's 46vh cap
  is inherited rather than derived, and the weights remain reasoned. B57 is kept
  open for those three.
- ~~**B56 — `TruncatedText`'s three inert `focus-visible:` utilities.**~~
  **Settled on 2026-08-14 by that slice's task B: deleted, not repaired**, after
  measuring the ring with and without them and finding it byte-identical.
- **New, filed by that slice and unowned: `BACKLOG.md` B60 and B61.** B60 is the
  session view's copy of a both-flanks-collapsed bug the project view had fixed —
  the reason the two `responsive.css` blocks are not the duplication they look
  like. B61 is the graph canvas's stale frame after a resize, filed as an
  observation and as the reason a test on this page must poll.
- **B58, B59 and §4's `GET /api/capabilities` all want the same backend
  budget.** They are three entries and one decision; whoever takes any of them
  should read all three before spending it.
- **`Workers.tsx`'s unconditional 2s poll (audit 5).** *Audit 5's framing is
  superseded.* Slice 4 established the poll is **correct** and must stay until a
  server frame reports roster changes — a turn's events append atomically at
  commit, so a frame-driven refresh would see a `turn` worker only after it was
  gone. The reasoning and its measurement are in `Workers.tsx:11-42` and B59.
  What remains is the cost, not a defect.
- **The selection-reading defect.** Topic and artifact ids are linkable in the
  URL grammar only; the shipped symptom is `CitationList.tsx:44`, which links
  a citation id to the `doc` facet.
- **`Breadcrumbs.tsx:90,92` — two dead names for one destination.** "course" and
  "research" are still offered as separate crumbs; both resolve to the project
  page, differing only in facet.
- **HOLDER has no region-level error state.**
- **`course.css`'s death.** Unowned. It survives until QUEUE's rail, the roster,
  the extraction pane and the autonomy panel are rewritten; nothing schedules
  that.
- **§6's open questions 1, 5 and 6.** QUEUE's ranking (1) is unstarted rather
  than merely unresolved; whether the picker deserves a page (5) was declined by
  slice 4 as a redesign; and whether the dated feature surveys still describe the
  code (6) is the one that silently invalidates the others.
