# Increment C, made startable

`unified-ui-proposal.md` §3 argued the route merge. This turns it into slices
somebody can begin on a Monday. It is a plan, not a proposal: the decision was
taken, and what follows is what to build, in what order, and what will go wrong.

## 0. What I checked, and what I did not

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
declares exactly the three routes the proposal asked for, and `FACETS`
(`routes.ts:67`) is exactly its eight: `session`, `topic`, `stage`, `entity`,
`doc`, `file`, `artifact`, `finding`. `parseRoute` (`routes.ts:105`) and
`projectHref` (`routes.ts:207`) are both there, and `projectHref` is one builder
over all eight, so a facet added to the union is linkable without anyone writing
its href. A topic, a stage and an artifact are already linkable states. **This
is not a slice; it is a precondition that is met.**

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
- §6.2's "required rather than optional" prerequisite is **still not done**.
  `use-course.ts:104` still invalidates `queryKeys.projects()` on every project
  frame. See §3.0.

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

**Changes.** `app/App.tsx`: delete `RESEARCH_FACETS` and the two-arm branch in
`CurrentView`; the `project` route renders `ProjectView` unconditionally.
`use-course.ts:104`: replace `invalidateQueries({ queryKey: queryKeys.projects() })`
with a single-row invalidation. **That last one is a prerequisite and not a
follow-up**, for the reason §6.2 of the proposal gives and which the merge makes
sharp: `/api/projects` folds one aggregate per project server-side
(`app.py:list_projects`, taken from the proposal's §0 and not re-verified by me),
and the course page is a page you visit while the project page is a page you
leave open. A busy project would re-fold the whole project list per frame,
indefinitely.

**Tenants, initially unchanged.** QUEUE holds today's `StageRail` and
`TopicQueue`; HOLDER holds `SessionView`; MATERIAL holds `GraphPane`,
`Artifacts` and `DocumentList` behind `Tabs`. Nothing is rewritten. The page is
ugly and it works.

**Independently shippable because** it is verifiable by navigation alone: every
facet in `FACETS` reaches a region, and the three facets that reach nothing
today (`file`, `artifact`, `finding`) get their first renderer even if it is the
existing one.

**Stylesheets that die: none.** This slice deletes no markup.

### 2.1 Slice 1 — QUEUE

Per the task, and I agree it is first among the region slices.

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

**Stylesheets that die: `course.css`** — and it has two passengers that must be
rescued first.

Its combinators split cleanly:
`.lay-split[data-split='course'] > …` at `course.css:37,48,55` die with
`CourseView`, and `.autonomy-disclosure[open] > …` at `:689,705` belong to
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
conclude they are dynamic.

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

**Deletes.** `use-session-panes.ts`'s `SESSION_TRACKS` only if the standalone
route stops using it; it does not, so **this file survives and the group
`session` survives with it**. `course/WorkerDrawer.tsx` mostly dissolves but
survives for the dock's foreign-project rows (proposal §5.2), so its deletion is
**not** in this slice.

**Stylesheets that die: `conversation.css`, `timeline.css`, `composer.css`,
`workspace.css`, `scrub-bar.css`** — but only the ones whose markup this slice
actually rewrites. `conversation.css` carries **eight** combinators, the most of
any file, and six of them (`.run > .disc-head`, `.discarded > .disc-head`,
`.msg-body > .md`, and the `:has(> .md)`) are claims about markup this slice
moves. This is the file to grep first.

**`check-deleted.mjs` gains:** removals from `STYLESHEETS` for each file
actually deleted, plus a `styles` rule forbidding `/^\.msg-body\b/m`,
`/^\.run\s*>/m` and `/^\.files\b/m`.

### 2.3 Slice 3 — MATERIAL's remaining five facets

`artifact`, `doc` (corpus), `entity` (graph), `finding`, `topic`. One reader,
one selection model, one filter, one URL segment — and the route grammar
already names all five, so this slice writes no new href builder.

**Order within the slice, and the reason.** `graph` last. `GraphCanvas` is
`React.lazy` over ~60 kB of `react-force-graph-2d`, and §3.3's decision that the
default facet is `workspace` rather than `graph` is a bundle decision that only
becomes checkable once the other facets are in place and `npm run verify`'s size
budget can be read against a page that has them.

**Deletes.** `research/ResearchView.tsx`, `research/use-research-panes.ts` and
its `research` preference group, `research/DocumentBrowser.tsx` if the shared
reader subsumes it, `course/Artifacts.tsx`'s page chrome.

**Stylesheets that die: `research.css`, effectively whole.** Of its 86 class
names, 79 are exclusive to `presentation/research/*`; the survivors are
`.view-head`, the three `.lay-pane*` corrections, `.topic-dispatch*` and
`.sub-questions`, all of which are shared selectors that other files also
declare. Its seven combinator selectors (`research.css:68, 86, 97, 122, 132,
138`) are **all** `.research-rail > …` / `.research-workbench > …` — every one a
claim about `ResearchView`'s markup, and every one silently void the moment that
markup goes.

**`check-deleted.mjs` gains:** `'research.css'` removed from `STYLESHEETS`, and
a `styles` rule forbidding `/\.research-rail/`, `/\.research-workbench/` and
`/^\.document-row/m`. A `presentation/research` rule forbidding
`/\bResearchView\b/` and `/\buseResearchPanes\b/`.

### 2.4 Slice 4 — the picker gets thinner

`#/` loses its two destination buttons and, if §3.5's claim holds, re-sources
its liveness chip from the dock's single `GET /api/workers` roster instead of
two requests per drawn row. **I did not re-verify the `2N` figure or the roster's
contents** — both are the proposal's, from `landing-page.md`. Sequenced last
deliberately: it is the only slice that is pure subtraction, so it is the only
one that can be dropped without leaving anything half-built.

---

## 3. What breaks, precisely

### 3.1 URLs

| Pattern | Today, at `f87443b` | After |
|---|---|---|
| `#/p/<id>/course` | **already dead** — `home` (`routes.ts:126-129`, asserted `routes.test.ts:133`) | unchanged: still `home` |
| `#/p/<id>/research` | **already dead** — `home` | unchanged: still `home` |
| `#/p/<id>` | the course view (`App.tsx`'s fallback arm) | the project page, default selection |
| `#/p/<id>/entity/<eid>` | the research view, entity selected | MATERIAL `graph`, entity selected |
| `#/p/<id>/topic/<tid>` | the research view | MATERIAL `topic` |
| `#/p/<id>/doc/<sid>` | the research view | MATERIAL `corpus` |
| `#/p/<id>/stage/<sid>` | the course view, stage open | QUEUE, stage row selected |
| `#/p/<id>/session/<sid>` | the course view, worker drawer | HOLDER |
| `#/p/<id>/file/…`, `/artifact/…`, `/finding/…` | parse, land on the course view, render nothing about the facet | MATERIAL `workspace` / `artifacts` / `findings` |
| `#/s/<id>[/at/n][/file/p]` | the session view | **unchanged** |

**A bookmark to `#/p/x/course` already lands on the picker today** and has since
`cebc89a` (#127). Increment C does not break it further. A bookmark to
`#/p/x/entity/abc` survives the merge and lands on the same entity in a
different container. **The three facets that parse and render nothing today
start rendering something — which is a change from silent to correct, and is the
only URL behaviour in this table that improves.**

### 3.2 Stored pane preferences

Four keys exist today, all under `rt.collapsedPanes.<group>`
(`infrastructure/storage/preference-store.ts:6`), all holding a JSON array of
pane ids, all read through a `try`/`catch` that returns `[]` on anything
unexpected (`:16-25`).

| Key | Written by | Ids | Fate |
|---|---|---|---|
| `rt.collapsedPanes.session` | `useSessionPanes` (`use-session-panes.ts:7`) | `timeline`, `workspace`, `conversation` (`:21`) | **survives**, for the standalone `#/s/` route only |
| `rt.collapsedPanes.course` | `useSplitPanes(COURSE_GROUP)` (`CourseView.tsx:49`) | `stages`, `artifacts` (`use-course.ts:28-31`) | **dies with slice 1** |
| `rt.collapsedPanes.research` | `useResearchPanes` (`use-research-panes.ts:7`) | `seeding`, `topics`, `documents` (`:16`) | **dies with slice 3** |
| `rt.collapsedPanes.agents` | `AgentWidget.tsx:49` | inverted — a stored name means *open* | untouched by these slices |

**What a reader with stored preferences experiences: their panes open once, and
nothing else.** A stale key naming ids the new page does not have is not merely
harmless, it is *specifically* handled: `toggleCollapsed` uses `>=` rather than
`===` on purpose, "because a caller can hand in a collapsed set naming a pane
that no longer exists, and an equality check would let the last real pane close
on the strength of a stale entry" (`split-tracks.ts`). So a stale `course` set
cannot lock a reader out of the new page.

**Even so, use a new group string for the project page — `project` — rather than
reusing `course` or `session`.** The proposal's §5.3 asks for "a deliberate key
rename rather than a silent reinterpretation, so a stale value reads as absent
rather than as its opposite", and that reasoning is right and free here.
Deleting the dead keys is not worth code: `preference-store.ts:3-5` already
records the precedent — the old single `rt.collapsedPanes` key was "left behind
rather than migrated", because it holds a pane layout and the project is
pre-release.

### 3.3 Behaviour

- **The topic dialog stops being a modal** and becomes the MATERIAL `topic`
  facet. `TopicStatusDialog.tsx` exists and phase-1 of `check-deleted.mjs`
  records that its hand-rolled focus trap was already deleted in favour of the
  overlay host, so the loss is smaller than §5.2 priced it: what goes is
  modality, not the keyboard contract. **The mandatory-justification form should
  stay a `Confirm` inside the pane** rather than the pane becoming a dialog
  again — §5.2's own conclusion, and `Confirm` exists.
- **The worker drawer stops being how you watch a worker in this project.**
  Selecting it in QUEUE opens it in HOLDER. The drawer survives for the dock's
  foreign-project rows.
- **The run panel and extraction pane move off the course page.** Muscle memory
  is the cost; §8.2 and §8.3 of the research survey are the benefit.
- **`SessionView` stops owning a `Split` on the project route** while keeping one
  on `#/s/`. Two renderings of one component with different layout ownership is
  a real complexity cost and I would not pretend otherwise; the alternative is a
  nested `Split`, which is worse for the reasons in §2.2.

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

Verified: no capabilities route exists anywhere in `research_team` or
`frontend/src`. The routes it would replace are the `503`s in
`interfaces/web/app.py` at `:653` (corpus), `:705` (topics), `:736` (seeding),
`:833` and `:896` (dispatch), `:933` (topic write model), `:1039` (graph) — plus,
and the proposal misses this, several unwired features answer **404**, not 503:
`:1226`, `:1278`, `:1356` ("autonomous runs are not enabled") and `:1306`,
`:1323` ("the worker roster is not enabled"). The client-side hack it replaces is
one line, `infrastructure/http/project-repository.ts:94`:

```ts
const saysDisabled = (message: string): boolean => /not enabled|AGENT_RESEARCH_RUN/.test(message)
```

used at `:105-107` and `:117-119`. Note that this regex would also match the
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

| File | Combinator selectors | Which slice invalidates them |
|---|---|---|
| `conversation.css` | 7, at `:56, 60, 64, 194, 200, 203, 340, 348` | **slice 2** — `.msg-body > .md`, `.run > .disc-head`, `.discarded > .disc-head` |
| `research.css` | 7, at `:68, 86, 97, 122, 132, 138` | **slice 3** — all of them `.research-rail > …` / `.research-workbench > …` |
| `responsive.css` | 6, at `:40, 55, 116, 171, 180, 195` — **all inside media queries** | **slices 1, 2 and 3** — see below |
| `course.css` | 4, at `:37, 48, 55, 689, 705` | **slice 1** — three are `.lay-split[data-split='course'] > …`; `:689,705` belong to `AutonomyPanel` and must move with it |
| `timeline.css` `:80, 265`; `tree.css` `:357, 367`; `components.css`, `structure.css` | 2 each | `timeline.css` in slice 2; the rest survive |
| `composer.css`, `markdown.css`, `workspace.css` `:54` | 1 each | `composer.css` and `workspace.css` in slice 2 |
| `layout.css`, `entity.css`, `states.css`, `agents.css`, `shell.css`, `tokens.css`, `theme.css` | 0 | — |

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
names, and every one of its six combinators names *another* view's markup from
inside a media query:
`.lay-split[data-split='session'] > [data-pane='conversation']` (`:40`, `:55`,
inside `@media (width >= 821px) and (width < 1181px)` opened at `:35`),
`.lay-split[data-split='course'] > .lay-pane > .lay-pane-body` (`:116`),
`.research-workbench > [data-pane='graph']` (`:171`),
`.research-rail > .lay-pane > .lay-pane-body` (`:180`), and the tree's
`ul.tree ul > li` pair (`:195`). **So each of slices 1, 2 and 3 silently voids a
rule in a file it is not touching, and the void only manifests at a viewport
nobody's default window is at.** A browser test at the default viewport cannot catch it, because
`vite.config.ts` sets the viewport and the media query reads *that*. Every slice
that deletes a view must grep `responsive.css` for that view's selector, and the
grep is the whole mitigation — there is no test that will do it.

`check-deleted.mjs` cites `.extraction-failed > .extraction-summary` as this
failure having already happened once, "no test, no error, just a rule that
quietly stopped applying". This is not a hypothetical hazard in this repository.

### 5.2 The clipped focus ring

The global `:focus-visible` is 2px at `outline-offset: 1px`
(`tokens.css:294`) — three pixels *outside* the border box. A child that fills an
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
project page's three panes start life as three unpadded scrollers. Two live
exposures already exist under it and neither has an inward-ring fix:
`.topic-list` (`research.css:203-214`, `padding: 0` at `:206`, whose topic rows
fall through to the global outward ring) and `.extraction-merge-list`
(`course.css:509-518`, `padding: 0` at `:512`). Both are inside markup slices 1
and 3 rewrite, so the fix is free if it is made during the rewrite and is a
separate bug report if it is not. Two more are marginal rather than broken —
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
   a design commitment.
2. **Whether MATERIAL's six facets are `Tabs` or a listbox.** `Tabs` exists and
   has both a jsdom and a browser test, so it is the cheap answer, but six tabs
   with one of them lazy-loading 60 kB is not obviously what `Tabs` is for. Not
   resolvable without seeing a real project's material.
3. **What `PROJECT_TRACKS` should be.** I have no measurement. Three peer
   columns is what `SESSION_TRACKS` uses, but QUEUE is a list, HOLDER is prose
   and MATERIAL is documents, and there is no reason to think they want equal
   weight. **This is exactly the kind of number that must be measured in the
   browser suite rather than reasoned about**, and `split-tracks.ts`'s own
   docstring is a record of what happens when two declarations of three columns
   are never read side by side.
4. **Whether `SessionView` can serve two layout owners cleanly.** §2.2 assumes it
   can — that the `Split` lifts out and the component renders into whatever
   region it is given. I did not prototype it. If it cannot, slice 2 grows a
   duplicate transcript component, which would be the worst outcome in this plan.
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
