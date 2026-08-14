# Audit 4 — HOLDER, the session, stored preferences, and behaviour

Read-only, at `9fa6c7b` (merged `main`, after #175/#176/#177). Nothing was run:
no gate, no build, no browser suite. Every `file:line` below was opened.

Against `docs/unified-ui-proposal.md` §4.4, §5.2, §5.3, §5.4;
`docs/increment-c-plan.md` §2.2, §3.2, §3.3; `docs/features-session-view.md`.

---

## Findings, most expensive first

### 1. One selection slot serves three regions, so a click in one region silently resets another

This is the same defect slice 2 found and fixed one layer down, and it is still
live one layer up. `docs/reports/increment-c-slice-2.md` §4 records that
`SessionView` wrote `sessionHref` for every scrub, so a click in HOLDER
navigated off the project page. The fix threaded `href` through
`useSessionScreen` (`use-session-screen.ts:98`) so HOLDER writes a `session`
selection instead. But the route carries **one** selection for the whole page
(`ProjectView.tsx:166`), and all three regions derive their state from it:

- `ProjectView.tsx:204` — HOLDER's scrub point is `selection.at` **only when the
  selection is a session**, otherwise `ScrubPoint.head()`.
- `ProjectView.tsx:176-181` — MATERIAL's open file is `selection.id` on a `file`
  selection, `selection.path` on a `session` one, otherwise `null`.
- `ProjectView.tsx:221-226` — MATERIAL's open tab is `file` for a session
  selection carrying a path, the selected facet if it is a MATERIAL facet, and
  otherwise `DEFAULT_MATERIAL` (`:127`, `artifact`).

The consequences follow mechanically and none of them is written down anywhere:

- **Clicking any event in HOLDER closes whatever MATERIAL tab the reader was
  on.** `screen.selectEvent` navigates to `href(point, openPath)`
  (`use-session-screen.ts:133-138`), and `href` writes
  `sessionSelection(sessionId, at, path)` (`ProjectView.tsx:193-199`). If the
  reader was on Findings, Documents or Graph, `openPath` is `null`, so the new
  selection is a session selection with a null path — which falls to the third
  arm of `materialTab` and snaps MATERIAL back to **Artifacts**. Scrubbing the
  log while reading a document closes the document.
- **The same keypress does it from anywhere on the page.** The Escape-to-live
  listener is `document`-level and registered whenever `sessionId` is non-null
  (`use-session-screen.ts:155-165`), so a reader scrubbed to event 12 who presses
  Escape while reading the graph gets the graph tab replaced by Artifacts.
- **Selecting a stage in QUEUE discards HOLDER's scrub point and MATERIAL's open
  file.** `select({ facet: 'stage', … })` (`ProjectView.tsx:277-279`) produces a
  selection that is neither `session` nor `file`, so `:204` hands HOLDER
  `ScrubPoint.head()` and `:176` hands MATERIAL `null`. A reader folded back to
  event 12 with a file open loses both by opening a stage row.

`ProjectView.tsx:216-220`'s comment reasons carefully about the *first* arm of
`materialTab` (a session selection with a path must not close the Workspace tab)
and does not notice that the *third* arm has the same shape of failure with a
null path. The plan's §3.3 lists four behaviour changes and this is not among
them; the proposal's §5.2 does not raise it either.

**Replacement text for plan §3.3, as a fifth bullet:**

> **Three regions share one selection, so selecting in one region resets the
> other two.** A scrub or an Escape in HOLDER writes a `session` selection with
> a null path, which returns MATERIAL to its default tab; selecting a stage in
> QUEUE returns HOLDER to head and closes MATERIAL's open file. This is the
> route grammar working as specified — `Selection` is one value
> (`routes.ts:96-104`) — and it is a real cost of the merge that neither page it
> replaces paid, because neither page had a second region to disturb. The
> options are a selection *per region* in the URL, or a rule that a
> region-internal move never rewrites the facet. Slice 3 must decide which,
> because it is the slice that gives MATERIAL five tabs worth losing.

Recommended arm: keep one `Selection` but stop HOLDER's scrub from rewriting the
facet — carry `at` as a query-ish suffix on whatever facet is current rather than
forcing `facet: 'session'`. That is a `routes.ts` change and therefore a slice-3
prerequisite, not a slice-3 detail.

### 2. Four facets reach a region and none of them reaches an item

Plan §3.1's URL table promises `#/p/<id>/topic/<tid>` → "MATERIAL `topic`",
`/doc/<sid>` → "MATERIAL `corpus`", `/artifact/…` and `/finding/…` → their
facets. What ships:

| URL | Region reached | Item selected |
|---|---|---|
| `/topic/<tid>` | **QUEUE** (`ProjectView.tsx:71-73`) | no — `TopicList` takes `projectId` only (`TopicList.tsx:19`, mounted at `ProjectView.tsx:283`) |
| `/doc/<sid>` | MATERIAL, Documents tab | no — `DocumentList.tsx:15` takes `projectId` only |
| `/artifact/<id>` | MATERIAL, Artifacts tab | no — `ArtifactList.tsx:18` takes `course` only |
| `/finding/<id>` | MATERIAL, Findings tab | no — `ProjectFindings` (`ProjectView.tsx:477`) takes `course` only |
| `/entity/<eid>` | MATERIAL, Graph tab | **yes** (`ProjectView.tsx:441`) |
| `/file/<path>` | MATERIAL, Workspace tab | **yes** (`ProjectView.tsx:176-181, 423`) |
| `/session/<sid>[/at/n][/file/p]` | HOLDER | **yes** (`:168, 204`) |
| `/stage/<sid>` | QUEUE | **yes** (`:167, 277`) |

`topic` is the sharp one: the plan's §3.1 says MATERIAL and the code says QUEUE
(`ProjectView.tsx:71-73`), `topic` is absent from `MATERIAL_TABS`
(`ProjectView.tsx:119-125`), and nothing on the page reads a topic id at all. So
`#/p/x/topic/abc` today lands on a project page indistinguishable from
`#/p/x`. That is the "parse and render nothing about the facet" state plan §3.1
says increment C ends, still true for one facet and half-true for three more.

**Replacement rows for plan §3.1** (the "After" column):

> | `#/p/<id>/topic/<tid>` | QUEUE, topic row selected — **not built; the id is
> parsed and ignored** |
> | `#/p/<id>/doc/<sid>`, `/artifact/…`, `/finding/…` | MATERIAL, correct tab
> open, **item not selected — slice 3 owes the selection, not the tab** |

### 3. S-F4's region-level error state does not exist, and HOLDER fails silently

Proposal §4.4 promises: *"S-F4 whole-page error → HOLDER: becomes region-level:
one failed session read must not blank a project page."* Half of that shipped.
`SessionView.tsx:72-82` still returns the whole-page `ErrorBox`, correctly, for
`#/s/`. `ProjectView` **never reads `screen.state.error`** — grep finds no
occurrence in the file. So a failed `GET /api/sessions/{id}` on the project page
renders HOLDER's ordinary tree: a `ScrubBar` over an empty log, an empty
transcript and a live composer, with no message and no Retry.

The project page does not blank, which is the half that shipped; the reader is
also never told the session read failed, which is worse than the state it
replaced. `state.snapshotError` is handled — but only inside `WorkspacePanel`
(`panels.tsx:101-109`), i.e. in MATERIAL, and only for folds.

**Sentence for the plan, in §2.2's "Changes":** *`SessionView` keeps its
whole-page error arm; HOLDER owes a region-level one, and does not have it —
`ProjectView` reads neither `screen.state.error` nor `screen.state.snapshotError`,
so a failed session read draws an empty but operable HOLDER.* File it as a
defect against slice 2 rather than as slice 3 scope.

### 4. The topic dialog is still a modal, and it is now a modal inside QUEUE

Plan §3.3 bullet 1 and proposal §5.2 open with *"the topic dialog stops being a
modal and becomes the MATERIAL `topic` facet."* Not shipped, and the code now
points the other way: `TopicList.tsx:42` still renders `TopicStatusDialog`, and
it is mounted on the project page at `ProjectView.tsx:283`. So the dialog moved
*onto* the merged page unchanged rather than dissolving into it. Combined with
finding 2 (`regionOf('topic') === 'queue'`), the plan's premise — that a topic's
detail becomes a linkable MATERIAL facet — has no code path toward it as
currently shipped.

**Replacement for plan §3.3 bullet 1:** *The topic dialog is unchanged and still
a modal, now mounted in QUEUE via `TopicList` (`TopicList.tsx:42`,
`ProjectView.tsx:283`). `regionOf` puts `topic` in QUEUE
(`ProjectView.tsx:71-73`), not MATERIAL, so making the detail a linkable facet
is now a change to `regionOf` and `MATERIAL_TABS` as well as to the dialog. If
that is still wanted, it is slice 3 work and it is larger than "the dialog stops
being modal". If it is not, say so and delete the §5.2 paragraph — a five-tab
MATERIAL with a sixth facet living in QUEUE is a defensible answer, but it must
be an answer rather than a leftover.*

### 5. `WorkerDrawer` survives for every dock row, not for foreign-project rows

Plan §2.2's "Deletes" and proposal §5.2 both say the drawer "survives for the
dock's foreign-project rows". No such narrowing exists in code:
`AgentWidget.tsx:183-189` opens `WorkerDrawer` for whatever row was clicked,
with no comparison against the project currently on screen — indeed `AgentWidget`
is shell chrome and has no notion of the current project. So for a row belonging
to *this* project the reader has two ways to watch the same session, one of which
(the drawer) is a focus-trapping overlay over the page that already shows it in
HOLDER.

This is a documentation error rather than a defect — nothing is broken — but it
matters because the plan uses the sentence to explain why the drawer is *not*
deleted, and the sentence describes filtering nobody has written.

**Replacement for plan §2.2:** *`course/WorkerDrawer.tsx` survives whole and
unfiltered: `AgentWidget.tsx:183` opens it for every dock row, including rows
belonging to the project on screen. The proposal's "survives for foreign-project
rows" describes a narrowing that would have to be built — the dock is shell
chrome and does not know which project is open. Either build it (the dock would
need the current project id) or accept two ways to watch one session and record
that as the accepted cost.*

### 6. Stored preferences: two keys are now orphaned, and the `>=` reasoning is narrower than stated

Plan §3.2's table is accurate about mechanism and stale about fates. Current
state, verified by grep for `useSplitPanes(`/`collapsedPanes`:

| Key | Written today by | Ids | State |
|---|---|---|---|
| `rt.collapsedPanes.session` | `useSessionPanes` (`use-session-panes.ts:37`), only from `SessionView.tsx:58` | `timeline`, `workspace`, `conversation` (`:21-25`) | **survives**, `#/s/` only — as §3.2 predicted |
| `rt.collapsedPanes.project` | `useProjectPanes` (`use-project-panes.ts:52`), from `ProjectView.tsx:165` | `queue`, `holder`, `material` (`:42-46`) | **new, not in the plan's table** |
| `rt.collapsedPanes.course` | **nobody** — `CourseView` is deleted | `stages`, `artifacts` | **orphaned now**, not "dies with slice 1" |
| `rt.collapsedPanes.research` | **nobody** — `ResearchView` is deleted | `seeding`, `topics`, `documents` | **orphaned now**, not "dies with slice 3" |
| `rt.collapsedPanes.agents` | `AgentWidget.tsx:49` | inverted (`popover` means open) | untouched, and §5.3's un-inversion is still not done |

So slice 3 has no preference work left to do: slice 1 orphaned `course` and the
`ResearchView` deletion orphaned `research` ahead of schedule. The plan's advice
— a new group string, keys left behind rather than migrated — was taken and is
recorded in `use-project-panes.ts:4-18`. **VERIFIED and shipped.**

**But §3.2's supporting argument about `>=` is half right and should be
corrected, because it will be reused.** `toggleCollapsed`'s `>=`
(`split-tracks.ts:98`) does prevent a stale entry letting the last real pane
close. It does **not** make a stale set harmless: stale names stay in the set and
count toward `tracks.length`, so a group carrying two stale ids against three
tracks refuses *every* collapse the reader asks for, with the toast "At least one
pane has to stay open." (`use-split-panes.ts:43`) — a sentence that is false in
that state. Nothing filters `collapsed` to known track ids on the way in
(`use-split-panes.ts:30-32`), and `splitTemplate` (`split-tracks.ts:50-56`)
ignores unknown ids only when *emitting*, not when counting.

This does not bite today, precisely because the group string is new and no reader
has a `project` set. It would have bitten had `course` been reused, which is the
plan's own recommendation vindicated for a reason the plan does not give.

**Replacement sentence for plan §3.2:** *A stale set cannot lock a reader out of
the page — `toggleCollapsed` uses `>=` (`split-tracks.ts:98`) so the last real
pane cannot close on a stale entry. It can, however, lock them out of collapsing
**anything**: stale ids are never filtered (`use-split-panes.ts:30-32`) and count
toward `tracks.length`, so two stale names against three tracks refuse every
toggle while telling the reader one pane must stay open. That is the sharper
argument for the new `project` key, and it is why reuse of `course` would have
been a live defect rather than a cosmetic one.*

### 7. What the shared hook does *not* hold, and therefore what can drift

The brief asks what is duplicated. `useSessionScreen` holds the effects, the
store lifecycle, the Escape listener and the four callbacks
(`use-session-screen.ts:104-201`), and `panels.tsx` holds the contents and the
three meta strings. What each arrangement writes for itself:

- **The end-session `Confirm` block is duplicated verbatim**, heading, both
  sentences and confirm label: `SessionView.tsx:106-120` and
  `ProjectView.tsx:319-333`. `features-session-view.md` F13 calls this wording
  the part that matters, because "end this session" sounds destructive and these
  two sentences are what say it is not. Two copies of load-bearing copy is the
  drift the hook exists to prevent, and it is the one thing the hook did not
  take. **Cheapest fix in the plan: export an `EndSessionConfirm` from
  `panels.tsx` taking `screen`, and delete both copies.** It is a slice-3-sized
  five-line change and it removes the highest-probability divergence on the page.
- **The `ScrubBar` wiring is duplicated** (`SessionView.tsx:86-96` vs
  `ProjectView.tsx:307-317`) — five props, identical, including the `historical`
  guard on `onFork`. Lower risk than the copy above, same shape.
- **`workspaceMeta` is now written by one caller only.** It is exported from
  `panels.tsx:46` and used at `SessionView.tsx:142`; `ProjectView` imports the
  other two meta helpers (`:26-32`) and not this one. Consequence for feature
  parity: **on the project page nothing in MATERIAL says which point the file
  tree is folded to.** On `#/s/` the Workspace pane header reads `@ event 12`
  (F20/F31); in MATERIAL's Workspace tab there is no such string, and the only
  indication is the `ScrubBar` in HOLDER — a *different region*, which the reader
  may have collapsed. This is the clearest instance of the two arrangements
  diverging by accident, and it is a one-line fix into `TabList`'s row or the
  panel's head.
- **The whole-page error arm** — finding 3.

Everything else in `features-session-view.md`'s §2–§8 reaches the project page:
F9–F15 via `ScrubBar`, F16 and F21–F28 via `TimelinePanel`/`TimelineFeed`,
F29–F41 via `WorkspacePanel` (including `FileHistory`, which `FileView.tsx:137`
mounts, so F35–F39 come along), F42–F49 via `ConversationPanel`, F52–F58 via
`ComposerPanel`. F50/F51 (approvals) are the shell's `DecisionBar.tsx:61` on
every route. No session feature is *unreachable* from the project page; the two
that behave differently are the workspace's scrub indicator and the error state.

### 8. §5.2's behaviour claims, one by one

- **"The run panel and the extraction pane move off the course page"** —
  **VERIFIED and shipped**, and further than described: `QueueHeader.tsx:107-125`
  holds `Workers`, `ExtractionPane`, `RunPanel`, `SeedPanel` **and**
  `AutonomyPanel`. The last is a departure the plan does not record — proposal
  §4.3 routes C-F30–F38 (autonomy) to the DECISION BAR, and `DecisionBar.tsx:69`
  does render `AutonomyAllowAll`, so autonomy is now in two places: the allow-all
  control in the bar and the per-tool panel in QUEUE. That is defensible (they
  are different controls) but it is not what §4.3 says. **Add a row to plan
  §3.3:** *the per-tool autonomy panel moves to the QUEUE header
  (`QueueHeader.tsx:123-125`), not to the decision bar; the bar keeps
  `AutonomyAllowAll` only.*
- **"The worker drawer stops being how you watch a worker in this project"** —
  half shipped. Selecting in QUEUE does open HOLDER (`QueueHeader.tsx:108`,
  `ProjectView.tsx:263`, pushed rather than replaced, correctly). The drawer does
  not stop being the other way — finding 5.
- **"`SessionView` stops owning a `Split` on the project route while keeping one
  on `#/s/`"** — **VERIFIED**: `SessionView.tsx:122-170` keeps it,
  `ProjectView.tsx:299` is a bare `Pane` with `scroll="regions"`. The plan's
  honesty about the complexity cost is warranted, and the cost landed exactly
  where §6.4 predicted: the two arrangements now differ in four places
  (finding 7), not in zero.
- **The topic dialog** — finding 4.

### 9. Uncertainty 4 of plan §6 is now settled, and should be marked so

*"Whether `SessionView` can serve two layout owners cleanly. I did not prototype
it. If it cannot, slice 2 grows a duplicate transcript component, which would be
the worst outcome in this plan."* It can, and it did not: one hook, one panels
module, two arrangements (`use-session-screen.ts:26-56`, `panels.tsx:20-35`). The
duplication that remains is four small call sites, not a component. **Mark §6.4
resolved rather than leaving it as an open risk to slice 3.**

Conversely §6.3 (`PROJECT_TRACKS` unmeasured) is **still open** and
`use-project-panes.ts:22-41` says so in its own docstring. Slice 2's report
defers it to slice 3 on the grounds that HOLDER now has real content. That is the
right slice; the plan should name it as slice 3 scope rather than as a standing
uncertainty, or it will be deferred a third time.

---

## Classification table

| # | Claim | Source | Verdict | Evidence |
|---|---|---|---|---|
| 1 | Three regions share one `Selection`; cross-region resets | not claimed anywhere | **WRONG by omission** | `ProjectView.tsx:176-181, 204, 221-226` |
| 2 | `#/p/<id>/topic/<tid>` lands on MATERIAL `topic` | plan §3.1 | **WRONG** | `ProjectView.tsx:71-73, 119-125`; `TopicList.tsx:19` |
| 3 | `/doc`, `/artifact`, `/finding` select their item | plan §3.1 | **WRONG** (tab opens, id ignored) | `DocumentList.tsx:15`, `ArtifactList.tsx:18`, `ProjectView.tsx:477` |
| 4 | S-F4 becomes a region-level error | proposal §4.4 | **NOT BUILT** | no `state.error` read in `ProjectView.tsx` |
| 5 | The topic dialog stops being a modal | plan §3.3, proposal §5.2 | **NOT DONE** | `TopicList.tsx:42`, `ProjectView.tsx:283` |
| 6 | `WorkerDrawer` survives for foreign-project rows | plan §2.2, proposal §5.2 | **WRONG** — survives for all rows | `AgentWidget.tsx:183-189` |
| 7 | `rt.collapsedPanes.session` survives for `#/s/` only | plan §3.2 | **VERIFIED** | `use-session-panes.ts:37`, `SessionView.tsx:58` |
| 8 | `course` dies with slice 1, `research` with slice 3 | plan §3.2 | **STALE** — both orphaned already | no `useSplitPanes` caller for either |
| 9 | A new group string `project` rather than reuse | plan §3.2 | **VERIFIED and shipped** | `use-project-panes.ts:19` |
| 10 | A stale key is harmless because of `>=` | plan §3.2 | **PARTLY WRONG** | `split-tracks.ts:98`, `use-split-panes.ts:30-32` |
| 11 | `SESSION_TRACKS` / the `session` group survive slice 2 | plan §2.2 | **VERIFIED** | `use-session-panes.ts:21-37` |
| 12 | The run panel and extraction pane move | plan §3.3, proposal §5.2 | **VERIFIED** | `QueueHeader.tsx:107-121` |
| 13 | Autonomy goes to the decision bar | proposal §4.3 (C-F30–F38) | **PARTLY WRONG** — per-tool panel is in QUEUE | `QueueHeader.tsx:123-125`, `DecisionBar.tsx:69` |
| 14 | Selecting a worker in QUEUE opens it in HOLDER | plan §3.3 | **VERIFIED** | `ProjectView.tsx:263`, `:168-174` |
| 15 | `SessionView` keeps its `Split`, HOLDER does not | plan §3.3, §2.2 | **VERIFIED** | `SessionView.tsx:122`, `ProjectView.tsx:299` |
| 16 | Approvals answered in one place (decision bar) | proposal §4.4 S-F50/51 | **VERIFIED** | `DecisionBar.tsx:61` |
| 17 | S-D1 `window.confirm` replaced by `Confirm` | proposal §4.4 | **VERIFIED**, in both arrangements | `SessionView.tsx:106`, `ProjectView.tsx:320` |
| 18 | Can `SessionView` serve two layout owners? | plan §6.4 | **RESOLVED — yes** | `use-session-screen.ts`, `panels.tsx` |
| 19 | `PROJECT_TRACKS` needs measuring | plan §6.3 | **STILL OPEN** | `use-project-panes.ts:22-41` |
| 20 | S-D19 (no autonomy where you answer approvals) closes | proposal §4.4 | **VERIFIED** for the project page | `QueueHeader.tsx:124`, `DecisionBar.tsx:69` |
| 21 | Every session feature reaches the project page | implied by plan §2.2 | **VERIFIED with two exceptions** | finding 7 |
| 22 | `#/s/<id>` behaviour unchanged | plan §3.1 | **VERIFIED** structurally | `SessionView.tsx:44-172`; see below |
| 23 | The workspace's scrub point is visible in MATERIAL | implied by §4.4 S-F29–F41 | **WRONG** — no meta rendered | `panels.tsx:46` used only at `SessionView.tsx:142` |
| 24 | Event shapes unchanged | plan §3.4 | **VERIFIED** — nothing in slice 2 touches Python | no backend diff in the slice-2 report |

---

## What I could not check without running anything

- **Whether `#/s/<id>` still behaves identically** (row 22). The structure is
  unchanged and the hook is shared, but `useSessionScreen` now takes `href` as a
  memoised callback and `SessionView.tsx:64-67` re-creates it on `sessionId`
  change; whether the Escape listener re-subscription rate changed in practice is
  a runtime observation. Settled by `npm run test:browser` plus
  `SessionView.test.tsx`, or by watching listener churn in devtools.
- **Findings 1's user-visible severity.** I read the code paths; I did not click
  them. Settled by opening a project page, selecting the Findings tab, clicking a
  timeline row, and observing whether the tab reverts to Artifacts. This is a
  five-second manual check and it should be done before slice 3 designs around
  the current behaviour.
- **HOLDER below `--bp-wide`.** Slice 2's report says every browser assertion was
  taken at 1440×900 and the stacked column has never been seen in the 821–1180px
  band or below 820px, where `layout.css` stacks the panes. `responsive.css`
  rules naming `[data-split='session']` no longer reach the project page at all,
  so HOLDER's column has no responsive rules of its own. Settled by a browser
  test at each of the three widths, which is what plan §5.3 already asks for and
  which no slice has yet written.
- **Focus rings in HOLDER's two new scrollers** (`ProjectView.tsx:354` and the
  MATERIAL tab panels). Slice 2 argues the gap is unchanged rather than widened
  because the content's own rings are drawn inward. That is a measurement claim
  and only `npm run test:browser` at 1440×900 can hold it.
- **Whether the orphaned `course`/`research` preference keys are actually present
  in any real reader's `localStorage`.** Only devtools on a browser that used the
  old pages settles it. It changes nothing — nothing reads them — but it is the
  difference between "orphaned" and "never written".
