# Scouted backlog

Written 2026-08-29 by a scout agent, against `main` at `f5a98462`. Nothing here
is claimed by the seven workstreams in `docs/plans/user-system-master-plan.md`
(W-A identity, W-B tenancy/RBAC, W-C0 settings, W-C1 settings page, W-D index
page, W-E authoring under load, W-F lesson slideshow).

This is a working-tree file. It is not committed and not on a branch.

## How to read the collision column

`research_team/interfaces/web/app.py` is ~5,400 lines and is the single most
contended file in the tree. W-A adds a `CurrentUser` dependency and W-B adds a
permission decorator **over every route**, so both will rewrite large parts of
it. Anything below marked **APP.PY** should either wait for W-A and W-B to
merge, or be scoped so its edit is a handful of contiguous lines that rebase
cleanly. `research_team/composition.py` is the second-most contended file for
the same reason.

---

## Top ten

| # | Title | Size | Files | Collision |
|---|---|---|---|---|
| 1 | `SemanticPort` is a one-adapter port with no test driving both ends | M | `tests/application/`, new integration test | none |
| 2 | `embeddings_enabled()` is dead — B159, confirmed, one line | S | `config.py`, `composition.py` | composition.py (small) |
| 3 | Delete `research_team/workflows/` — orphaned bytecode, no source | S | `research_team/workflows/` | none |
| 4 | No root `ErrorBoundary`; a render throw whitens the whole console | S | `frontend/src/app/App.tsx` | W-A adds auth state that can throw |
| 5 | Rendered markdown is unstyled everywhere — B158, since 2026-08-07 | M | `frontend/src/styles/markdown.css` | none |
| 6 | Two `project-*` browser tests fail on `main` — B108 / B124 | S | 2 browser test files | none |
| 7 | Neighborhood and usages routes have no untouched-project test | S | `tests/interfaces/test_web.py` | none |
| 8 | `control-defaults.browser.test.tsx` covers only `<button>` | S | `frontend/src/styles/` | none |
| 9 | Clean the working tree: 13 uncommitted files, 4 stray PNGs | S | repo root, `.gitignore` | none |
| 10 | Prune ~230 merged branches and ~60 worktrees | S | git only | none |

---

## Ranked items

### 1. `SemanticPort` is a one-adapter port with no test driving both ends

CLAUDE.md's "Events" section records the `CoMentionPort` incident: a port, one
adapter, a projection consuming it, tuned constants and a design document, and
it produced **nothing** from the day it merged, because the adapter was tested
alone and the consumer was tested against stubs. `SemanticPort`
(`research_team/application/area_projection.py:152`) is the same shape today.
Its one production adapter is `VectorNeighbours`
(`research_team/infrastructure/knowledge/semantic_neighbours.py:57`), wired for
real only at `research_team/interfaces/web/app.py:3370-3390`.
`tests/infrastructure/test_semantic_neighbours.py` drives the adapter against an
`InMemoryVectorStore` and never calls `project_areas`;
`tests/application/test_curriculum.py` and `tests/application/test_semantic_edges.py`
drive `AreaProjection` with literal tuples and never construct `VectorNeighbours`.
No test anywhere puts the real adapter in the real loop.

This matters because the co-mention channel in that exact shape shipped dead and
stayed dead through a whole feature, and the number was rendering as 0 on screen
the entire time. The remedy already exists as a worked example:
`tests/infrastructure/test_co_mentions.py:454`
(`test_a_curriculum_built_over_a_real_ingest_counts_shared_passages`). Write its
sibling for the semantic channel over a real ingest with real embeddings, and
report what the count actually is — the honest outcome of this task may be
"the semantic channel also produces zero", which is the finding.

Effort: **medium**. Files: a new `tests/integration/` test, possibly
`tests/infrastructure/test_semantic_neighbours.py`. Collision: none.

### 2. `embeddings_enabled()` is dead — B159, confirmed

`BACKLOG.md:3238`. Verified by grep on 2026-08-29:
`research_team/infrastructure/config.py:624` defines it, and the only two reads
in the tree are `tests/infrastructure/test_embedding_config.py:44` and `:52`.
Production never calls it; `research_team/composition.py` open-codes the same
condition. (A first audit pass of this reported the entry REFUTED by counting
those two test lines as callers — they are the test of the dead function.)

It matters as the smallest possible instance of a shape this repo keeps paying
for: a named predicate that reads as the system's answer to "are embeddings on",
with the real answer written out longhand somewhere else, so the two can drift
and only the inert one has a test. Fix is to call it from the open-coded site,
or delete it and its test.

Effort: **small**. Files: `research_team/infrastructure/config.py`,
`research_team/composition.py`, `tests/infrastructure/test_embedding_config.py`.
Collision: `composition.py` is contended, but this is a one-line edit.

### 3. Delete `research_team/workflows/`

`find research_team/workflows -type f` returns four `.pyc` files
(`hybrid`, `addie`, `ubd`, `__init__`) and nothing else. The `.py` sources were
removed with the workflow system (B147, closed 2026-08-27, `BACKLOG.md:3013`),
and the compiled bytecode was left behind. Nothing in `research_team/` imports
`workflows`.

It matters because orphaned bytecode is importable: on a Python that permits
sourceless imports, or in any tooling that walks the package tree, this
directory still answers to `research_team.workflows.ubd` with the code B147
deliberately deleted. It also makes greps for the removed system return hits,
which is how B22, B38, B44, B45 and B46 in `BACKLOG.md` still read as live work
(they are not — see "Stale backlog entries" below).

Effort: **small**. Files: `research_team/workflows/`, possibly `.gitignore`.
Collision: none.

### 4. No root `ErrorBoundary`

`grep -rn "ErrorBoundary" frontend/src` returns nothing.
`frontend/src/app/App.tsx` wraps `<Console/>` in no boundary, so any render-time
throw takes the whole console to a white screen rather than one pane to an error
state. Per-pane `isError` handling is genuinely good — roughly 35 files have a
real branch (`CoursePage.tsx:115`, `TopicList.tsx:74`, `ProjectList.tsx:127`,
`InteractionsView.tsx:97`) — so this is specifically the render-throw path, not
the fetch-failure path.

It matters now rather than later because W-A introduces session state that can be
absent, expired, or malformed at render time, and W-B introduces a permission
check that can throw on a payload shape nobody anticipated. Both are exactly the
class of error that arrives during render rather than in a query. Building the
boundary before those land means their failures are visible instead of blank.
Pair it with a `window.onerror` / `onunhandledrejection` handler routed to the
existing toast store (`frontend/src/application/notifications/toast-store.ts`) —
there is no client-side error reporting of any kind today.

Effort: **small** for the boundary, **medium** with the reporting handler.
Files: `frontend/src/app/App.tsx`, one new component, `toast-store.ts`.
Collision: W-A will edit `App.tsx` to add a provider. Order this **before**
W-A merges or accept a small rebase; do not run them concurrently on that file.

### 5. Rendered markdown is unstyled everywhere — B158

`BACKLOG.md:3170`. Filed as having been broken since 2026-08-07, and confirmed
still live: `frontend/src/styles/markdown.css` defines `.md-h` and friends,
several of which the entry's own grep shows nothing emits. Every surface that
renders model prose — ask answers, lesson bodies, course text — is drawing
unstyled markup.

It matters because it is the single most user-visible defect on the list. Every
other item here is invisible or internal; this one is what a person sees when
they read anything the system wrote. It is also standalone frontend work with no
backend surface, which makes it a clean dispatch.

Note the CLAUDE.md rule: this is a stylesheet change, so `npm run test:browser`
is required, and jsdom cannot judge it.

Effort: **medium**. Files: `frontend/src/styles/markdown.css`,
`frontend/src/**/markdown.ts` and its consumers, a browser test. Collision: none.

Adjacent and cheap in the same worktree: **B154 (second)** at `BACKLOG.md:5131`
— `course.css` is named after a course but dresses `AutonomyPanel` and
`ExtractionPane` on a research tab. Rename it. Take this only if the agent has
headroom; it is not worth its own dispatch.

### 6. Two `project-*` browser tests fail on `main` — B108 and B124

`BACKLOG.md:4064` and `BACKLOG.md:4177` are the same defect filed twice, and
B124 says so ("close them together"). `project-stacked.browser.test.tsx` and
`project-tracks.browser.test.tsx` fail against `main`'s CSS. They are invisible
because `npm run test:browser` is deliberately outside CI (CLAUDE.md says why,
and that is the right call), so nothing forces anyone to see red here.

It matters because the browser suite is the only instrument this repo has for
computed styles, and a suite that is already red is a suite nobody will trust to
tell them about a new failure. Two known failures is how a browser suite stops
being run at all. Fix both, and close B108 and B124 together.

Effort: **small**. Files: the two browser test files and whatever CSS they
measure. Collision: none. Ordering: do this **before** item 5 or item 8, so
those land against a green browser suite.

### 7. Neighborhood and usages routes have no untouched-project test

CLAUDE.md's fixture rule ("a fixture that seeds through the same call the code
under test depends on cannot see that dependency go missing") produced a real
503 on the entity-definitions work, and the repo responded by adding one
untouched-project guard per route family:
`tests/interfaces/test_curriculum_routes.py:230`,
`tests/interfaces/test_web.py:3449`,
`tests/interfaces/test_document_routes.py:635`. Two graph-adjacent route
families never got theirs. `tests/interfaces/test_web.py:3314`
(`test_a_neighborhood_carries_root_entities_and_relationships`) and `:3601`
(`test_usages_returns_passages_with_offsets`) both arrange through
`_project_with_graph` (`:3250`), which calls `application.graphs.open(tenant_id)`
at `:3262` — the very call the routes at `app.py:3061` and `app.py:3111` are
responsible for making. `:3424` and `:3580` have the same shape.

It matters because this is a defect the repo has already shipped once, in this
exact form, on an adjacent route, and the fix is three tests that mirror three
tests already in the tree. If either route has the bug today, the first request
for any newly-touched project 503s and every request after it succeeds — which
reads as flakiness.

Effort: **small**. Files: `tests/interfaces/test_web.py` only. Collision: none.
It reads `app.py` but need not edit it.

### 8. `control-defaults.browser.test.tsx` covers only `<button>`

`frontend/src/styles/control-defaults.browser.test.tsx` is the standing
measurement CLAUDE.md names for the unlayered-element-selector trap. It asserts
exactly four things, all on a `<button>`: `background-color` via
`bg-transparent` (:43), `color` via `text-accent` (:56), `font-size` via
`text-xs` (:75), and one regression check that an unclassed control still gets
dressed (:95). The rule it guards covers `button, input, textarea, select`
(`tokens.css:568` and `:638`), and three of those four elements are untested.
`font-family` is also untested, which is notable because CLAUDE.md's own account
of the incident says `font: inherit` reached furthest *because it is a
shorthand* — and `font-family` is the leg of that shorthand nothing measures.

Two rules in `tokens.css` are also still genuinely unlayered and outside this
test's reach: `html, body` at `:539` and `body` at `:544` (which sets
`background`, `color`, `font-family`, `font-size`, `display`, `overflow`), and
`:focus-visible` at `:691`, which is the one CLAUDE.md says is deliberately
unlayered and opted out of via `.lay-ring-inward`. The `body` rules are inert
today only because a React SPA never renders `<body>` — that is an accident of
the current app, not a property of the rule.

Effort: **small**. Files: `frontend/src/styles/control-defaults.browser.test.tsx`.
Collision: none. Ordering: after item 6, so it runs against a green suite.

A clean negative result from the same audit, worth recording so nobody repeats
it: **`border-0` beside a non-directional `border` has zero live occurrences**
(all 57 `border-0` sites pair with a directional width or stand alone), and
**`border-solid` beside a lone directional width has zero occurrences**. Both
CLAUDE.md border rules are currently obeyed throughout `frontend/src`. Likewise,
**no dead frontend component was found** — all 151 non-test `.tsx` files are
imported by non-test code, the sole exception being
`presentation/lesson/timeline-widget-harness.tsx`, which is a deliberate shared
test fixture.

### 9. Clean the working tree

`git status` at the repo root shows 13 uncommitted paths. Recommended
disposition, but **confirm with the orchestrator before deleting anything** —
some of these are other agents' in-flight state:

- `course-full.png`, `course-new.png`, `course-widgets-fixed.png`,
  `export-graph.png`, `interactions-explorer.png` — five stray screenshots at
  the repo root, untracked. These are verification artifacts from visual checks.
  **Add `*.png` at the repo root to `.gitignore`** (scoped, so `frontend/` art
  assets are unaffected) and delete them. Do not commit them.
- `.claude/tackline/memory/sessions/*.md` — two deleted, three new, one
  modified. This is session memory being written by the live session. **Leave
  it entirely alone**; it is not project state and committing it mid-session
  will fight whatever is writing it.
- `frontend/.claude/` — untracked agent config in a subdirectory. Determine
  whether it is intended to be shared; if not, gitignore it.
- `docs/deck/` — untracked. This is almost certainly W-F's (lesson slideshow)
  working directory. **Leave it**; ask W-F.

It matters because a dirty root is how the "HEAD is somewhere you did not put
it" failure in CLAUDE.md's "Parallel work" section starts — the noise makes a
real anomaly unreadable.

Effort: **small**. Files: `.gitignore`. Collision: none, but coordinate.

### 10. Prune merged branches and worktrees

`git worktree list` shows 70 entries; `git branch --list` shows 245 local
branches. `gh pr list --state open` returns **zero open PRs**, and cross-
referencing `git branch --merged main` against 290 merged-PR source branches
leaves roughly 15 branches unaccounted for. Of those, the following hold no work
worth recovering:

- Zero commits ahead of main (safe prune): `bump-redstring-0.6.0`,
  `fix/ask-crypto-randomuuid`, `verify-main`,
  `worktree-agent-a1ce2fc0254eb444d`.
- Superseded by merged work: `worktree-redstring-0-10-0` (superseded by
  `redstring-0.10`), `consolidation-aliases` and `curriculum-naming` (both
  superseded by the merged `input-quality` work, PR #241).
- The 2026-08-11 UI generation, stale for 18 days, never opened a PR, and
  superseded by the merged `ui/direction-*` series: `ui/floating-layer`,
  `ui/route-grammar`, `ui/decision-bar`, `merge/floating-layer`,
  `merge/route-grammar`.
- `feat/context-management` — one commit, 2026-08-02, four weeks stale.

**Nothing was found that holds unmerged work worth recovering.** Five worktrees
(`agent-a312316014b24dd42`, `-aad61fab41dfcc0da`, `-abba20d78ce18fab8`,
`-adc23c5f066304087`, `-aed70a717392e5005`) all point at `f5a98462` and are
locked — these are the *active* dispatch worktrees for the master plan. Do not
touch them.

It matters because CLAUDE.md's "Parallel work" section says work has already
been nearly lost to worktree confusion, and 70 worktrees against 7 live
workstreams is the condition that causes it.

Effort: **small**. Files: git only, no source. Collision: none. **Do not run
this concurrently with any other dispatch** — pruning worktrees while agents
hold them is exactly the loss this is meant to prevent.

---

### 11. `/api/projects/{project_id}/workers` is dead — B153 (second), confirmed

`BACKLOG.md:5118` filed this as a suspicion; it is confirmed.
`research_team/interfaces/web/app.py:4423` declares the per-project route. The
console calls only the cross-project `/api/workers` (`app.py:4401`), from
`frontend/src/infrastructure/http/project-repository.ts:67`. There is a doc
comment at `frontend/src/application/.../use-running-agents.ts:30` explaining
why the per-project route is deliberately not used. It has backend tests
(`tests/interfaces/test_web.py:2863-2982`), so this is dead-but-tested.

Two other routes are also uncalled by any frontend code:
`POST /api/corpus/rebuild` (`app.py:5314`, tested at
`tests/interfaces/test_web.py:1385`) and
`POST /api/projects/{project_id}/sources/reindex` (`app.py:1604`, tested at
`tests/interfaces/test_extraction_routes.py:294`). Both are plausibly deliberate
operator routes rather than defects — B153's own framing is "a survey, not a
deletion", and that framing should hold here too.

It matters mostly as a decision rather than a defect: three tested routes with
no caller are three routes W-B will have to put a permission decorator on, and
deciding now whether they are operator surfaces or dead code is cheaper than
deciding it inside W-B's diff.

Effort: **small**. Files: `research_team/interfaces/web/app.py`,
`tests/interfaces/`. Collision: **APP.PY**. Because it is a deletion rather than
an edit, running it against W-B's in-flight decorator work is a near-certain
conflict. **Do this before W-B starts, or after it merges — not during.**

### 12. `mark_stale` is read-modify-write — B74

`BACKLOG.md:1809`. `research_team/infrastructure/persistence/read_models.py`
reads a row, mutates it and writes it back where a single
`UPDATE ... SET stale = 1` would do. Confirmed the file and the symbol still
exist.

It matters as a correctness question rather than a performance one: a
read-modify-write over a read model is a lost update waiting for two writers,
and the entity-definitions work already has a documented browser-edit-versus-
agent-write race (B79, `BACKLOG.md:1553`).

Effort: **small**. Files:
`research_team/infrastructure/persistence/read_models.py` and its test.
Collision: none.

### 13. `apply_schema`'s drop-table branch has no test — B47, and its widening
path has never run against the two dialogue tables — B112

`BACKLOG.md:484` and `BACKLOG.md:556`. Both are about
`research_team/infrastructure/persistence/read_models.py:315`. CLAUDE.md's
"Read models" section is the longest incident record in the file, and it ends by
saying the drop-and-recreate branch exists because a required column with no
default was added to a usually-empty table. That branch is the one with no test
naming it.

It matters because this is the one function in the tree whose failure mode is
"every query 500s against a real database while every test passes", and it has
an untested branch. B112 is the same function against the dialogue tables.
They are one dispatch.

Note the memory rule and CLAUDE.md agree: **verify against a copy of a real
database**, via
`uv run python -m research_team.infrastructure.persistence.local_copy`.

Effort: **small-medium**. Files:
`research_team/infrastructure/persistence/read_models.py`,
`tests/infrastructure/`. Collision: none.

### 14. `build_application` leaks on a partial build — B100

`BACKLOG.md:3947`. `research_team/composition.py:1560`. If construction fails
partway, the event store, blob store and every projection runner built so far
are dropped without being closed. B5 (`BACKLOG.md:156`) records that an unclosed
`SQLiteEventStore` blocks interpreter shutdown, so the two are related: a
partial build can hang the process rather than raise cleanly.

It matters more once W-A and W-C0 land, because both add constructors to this
function — an identity client and a settings store — and both can fail on
misconfiguration, which is precisely the partial-build case.

Effort: **medium**. Files: `research_team/composition.py`. Collision:
**composition.py is contended**. W-A and W-C0 both add wiring here. Sequence
this after them, or accept the rebase.

### 15. `Application.close()` can skip `detach_project` — B10

`BACKLOG.md:261`. Same file, same theme as item 14, and could be one dispatch
with it if an agent has headroom. Kept separate because the collision cost of
`composition.py` is paid once either way.

Effort: **small**. Files: `research_team/composition.py`. Collision:
composition.py.

### 16. Duplicate backlog ids — B116, and worse than B116 says

`BACKLOG.md:4288` lists ten duplicated ids (B36, B54, B58, B59, B60, B62, B63,
B79, B80, B81). The scan for this document found three more pairs inside the
2900-5185 range alone that B116 does not enumerate: **B122** (`:4139`
`componentBlock` vs `:4546` `AGENT_CONSOLIDATION_BATCH`), **B153** (`:3054`
coverage grid vs `:5118` the workers route), and **B154** (`:3075` authoring
checkpoint denominators vs `:5131` `course.css`). At least thirteen ids are
ambiguous, and B116 itself says one commit message cites a duplicated id.

It matters because every reference to a backlog id in a commit message, a
design document or a CLAUDE.md entry is now potentially ambiguous, and `git log`
is explicitly a design record in this repo. The fix is a small script that
fails on a duplicate `### B<N>.` heading, plus a renumbering pass.

Effort: **small**. Files: `BACKLOG.md`, a new check script. Collision: none,
but it rewrites `BACKLOG.md` wholesale — **any other agent editing `BACKLOG.md`
in the same window will conflict**, and most workstreams close a backlog entry
when they finish. Schedule this in a quiet window or accept manual merges.

### 17. Ten `as unknown as Container` casts in browser fixtures — B90

`BACKLOG.md:3818` filed six; grep on 2026-08-29 finds **ten** occurrences in
`frontend/src`. The count has grown since filing, which is the finding: the
cast is being copied into new fixtures.

It matters because the cast is what defeats type checking in exactly the suite
whose job is measurement, and each copy makes the eventual fix larger. Fixing
it now is cheaper than fixing it at twenty.

Effort: **small-medium**. Files: browser test fixtures under `frontend/src`.
Collision: none, but overlaps item 6's files — do item 6 first or combine them.

### 18. `test:browser` is not in CI, and B140 / B145 / B144 are why that costs

Four frontend defects sit behind the browser suite: B140 (`:645`, the tab-strip
measurement CI cannot reach), B145 (`:688`, scrubbed-past timeline rows at
1.7:1 contrast — an accessibility failure, WCAG AA wants 4.5:1), B144 (`:733`,
a toast makes the material tabs unclickable), and B141 (`:815`, nothing ranks
the material tabs). B145 and B144 are real user-facing defects, not test debt.

B144 in particular is the shape CLAUDE.md's "check pixels, not the DOM" entry
describes — an overlay intercepting clicks — and is likely diagnosable in one
`document.elementFromPoint` call.

It matters because B145 is a straightforward accessibility defect that will be
someone's compliance question once there are real users, and B144 makes a
primary navigation control unusable while a toast is up.

Effort: **small** each; **medium** as a bundle. Files:
`frontend/src/presentation/shell/Toasts.tsx`, tab strip components, browser
tests. Collision: none between them; they are one agent's afternoon.

### 19. Interaction log: no consumer, and dead plumbing — B107 and B110

`BACKLOG.md:4042` and `BACKLOG.md:4100`. The interaction log writes and has no
reader; `GraphState.select(id, source)` and `EntityTreePane`'s emitter are
plumbing kept alive for a consumer that does not exist. B146 (`:591`) adds that
the browser-to-store seam has no standing test — and CLAUDE.md's "interaction
log" section records that the silent-default emitter makes "never wired" and
"working" indistinguishable, measured by deleting the provider from `App.tsx`
and watching all 19 tests stay green.

B146 is the dispatchable half and should go first: a test that a recorded event
**reaches the sink**, never that nothing threw. B107 is a large feature (a read
API and an aggregation surface) and should not be dispatched as scouted work —
it wants a design decision about what the log is for.

Effort: B146 **small**; B107 **large**, not recommended for dispatch. Files:
`frontend/src/app/App.tsx`, `tests/interfaces/test_interaction_routes.py`.
Collision: `App.tsx` overlaps item 4 and W-A.

### 20. Onboarding copy is tenant-naive

`frontend/src/presentation/tree/TreeView.tsx:126-152` (`FirstRun`) is a good
zero-projects state: it explains the mental model, offers "+ New project", and
gives a CLI escape hatch. It fires on projects-and-sessions-both-empty, and says
nothing about an organisation or a workspace, because neither exists yet.

Once W-B lands, "a brand-new tenant with no projects" and "a new user joining a
tenant that has projects they cannot see" render the identical screen, and the
second one is actively misleading — it invites the user to create a project when
the real answer is "ask someone for access".

This is flagged rather than dispatched: **it should be W-B's, not an independent
agent's**, because the correct copy depends on decisions W-B has not made yet.
Listed so it is not forgotten.

Effort: **small-medium**. Files:
`frontend/src/presentation/tree/TreeView.tsx`, `NewProjectForm.tsx`.
Collision: W-B owns this.

---

## Stale backlog entries — close without doing the work

These read as live in `BACKLOG.md` and are not. The workflow system was removed
in `bb53f66f` (B147, `BACKLOG.md:3013`), and the pre-React console
(`research_team/interfaces/web/static/app.js`) no longer exists. A dispatch
against any of these would waste an agent.

- **B22** (`:337`), **B38** (`:370`), **B44** (`:404`), **B45** (`:432`),
  **B46** (`:461`), **B36** (`:894`) — all name `checks.py`, `coverage.py`,
  `matrix_density`, `self_review_separation`, or `ubd.py`/`addie.py`/`hybrid.py`.
  None exist.
- **B26** (`:1012`) — half stale. The `checks.py` side is gone; the
  `topic_attention.py` side may still be real. Needs a re-read, not a dispatch.
- **B11** (`:272`) and **B17** (`:305`) — both cite `static/app.js`. The
  underlying questions ("last join wins swaps tools under an open tab", "the
  browser offers only approve and reject though edit works end to end") may
  still be true of the React console, but the entries as written are unactionable.
  Re-verify before re-filing.
- **B128** (`:4622`) — the need is real (an authored course is never checked
  against the area it teaches) but its proposed implementation reuses
  `coverage.matrix_from_links`, and `application/coverage.py` is deleted and
  B147 says it should stay deleted. The entry needs rewriting before anyone
  picks it up.
- **B2** (`:3544`) — superseded by the "closed by redstring 0.3.0" block later
  in the same file.

Recommend one small dispatch that **edits `BACKLOG.md` only**, marking these
closed-as-stale with the reason. Note the collision warning in item 16: this
and the renumbering pass are the same file and should be one agent, not two.

## Blocked on upstream — do not dispatch

`redstring` owns the fix for all of these, and CLAUDE.md's "Dependencies"
section explains why bumping it is not a local decision. Listed so nobody
mistakes them for available work: **B58** (`:3276`), **B86** (`:3585`),
**B87** (`:3705`), **B88** (`:3769`, blocked on B87), **B132** (`:4690`),
**B136** and **B137** (`:4747`, `:4772` — B136 is blocked on B137, and B137
needs a corpus that does not exist). The memory note "BC dates are an upstream
change" applies to the B87 cluster.

## Wants a decision, not an agent

**B50** (`:2943`, the chat cannot steer the project), **B81** (`:3663`, purging
a dropped document's graph contributions — blocked on provenance design),
**B121** (`:4476`, ending a dialogue a reader walked away from — the entry
explicitly refuses a timer-based fix), **B107** (see item 19), and **B150**
(`:4943`, the authoring-subagents branch owes a live run — this is an
investigation requiring a real model run, not parallelisable). **B104**
(`:2929`), **B109** (`:4082`), **B115** (`:4261`) are recorded reasoning with
nothing to implement; they should not be dispatched at all.

## Collision summary

Ordering constraints, stated once:

- **Item 6 before items 5, 8 and 17** — get the browser suite green before
  adding to it or measuring against it.
- **Item 4 before W-A merges**, or after — `App.tsx` conflict. Item 19's B146
  touches the same file; run items 4 and 19 as one dispatch or in sequence.
- **Item 11 before W-B starts, or after it merges** — a route deletion against
  an in-flight per-route decorator is a near-certain conflict.
- **Items 2, 14 and 15 all edit `composition.py`** — one agent, or sequence
  them. W-A and W-C0 also add wiring there.
- **Item 16 and the stale-closure dispatch both rewrite `BACKLOG.md`** — one
  agent. Most workstreams also close an entry when they finish, so schedule this
  when few are landing.
- **Item 10 must not run concurrently with anything** — pruning worktrees while
  agents hold them is the loss it exists to prevent.
- Items 1, 3, 7, 12, 13, 18 have **no collisions** and can go out immediately,
  in parallel, today.
