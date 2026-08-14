# Increment C audit 1 — routes, regions, and the URL grammar

Scope: proposal §3.1, §3.3, §3.4, §5.1; plan §2.0–§2.4 region assignments, §3.1,
§3.4. Against `presentation/routing/routes.ts`, `use-route.ts`, `app/App.tsx`,
`presentation/project/ProjectView.tsx` and the tests beside them, at `9fa6c7b`
(merged `main`, PRs #175/#176/#177 in).

No command was run. Every claim below is a read of the file at the cited line.

---

## Findings, most expensive first

### F1. Four facets are linkable, click-reachable *and inert* — the id changes nothing on screen

This is the defect class the lead named, in its third variant. It is not "no
renderer" (slice 0 fixed that) and not "no entrance" (#176/#177 fixed that for
`ask`). It is: the facet reaches a region, the region draws a component, and the
component **never receives the selected id**, so the URL says one thing and the
page shows another.

`ProjectView` threads a selection id into exactly four tenants:

- `session` → `sessionId` (`ProjectView.tsx:168,174`)
- `stage` → `openStage` (`:167`, consumed at `:277`)
- `file` → `openPath` (`:176-181`, consumed at `:423`)
- `entity` → `GraphPane entity=` (`:441`)

The remaining four MATERIAL/QUEUE tenants are mounted with `projectId` or
`course` alone and no selection at all:

| Facet | Renderer, mounted at | What it is given | What it does with the id |
|---|---|---|---|
| `topic` | `TopicList` (`ProjectView.tsx:283`) | `projectId` only | nothing — the open topic is `useState` (`use-topic-queue.ts:31`) |
| `doc` | `DocumentList` (`:435`) | `projectId` only | nothing — the open document is component state (`DocumentList.tsx:31`, `reading`) |
| `artifact` | `ArtifactList` (`:402`) | `course` only | nothing — `ArtifactList.tsx:18` takes `{ course }` |
| `finding` | `ProjectFindings` (`:428`) | `course` only | nothing — `ProjectView.tsx:477` takes `{ course }` |

Consequences, in order of how much they cost:

1. **`presentation/ask/CitationList.tsx:44` is a live broken link today.** It
   builds `projectHref(projectId, { facet: 'doc', id: citation.id })`, and its
   own comment says "The project's document facet, not a bare id: the reader is
   on the project page already, and this keeps them on it." Following it opens
   the project page with the **Documents tab selected and no document open** —
   the id is parsed, put on `selection`, and dropped. A reader who clicks a
   citation lands on an unfiltered list and has to find the source by hand. This
   is the only shipped link in the console that points at an id nothing reads.
2. Proposal §3.1's three headline properties are **one-third delivered**.
   "A stage is linkable" — VERIFIED (`ProjectView.tsx:167,277`). "A topic is
   linkable" and "an artifact is linkable" — the *href* exists, the *state* does
   not; `Manage` is still component state, which is the exact condition §3.1 says
   the merge removes.
3. Plan §1 repeats this as settled: "A topic, a stage and an artifact are already
   linkable states. **This is not a slice; it is a precondition that is met.**"
   Two thirds of that sentence is false, and it is load-bearing — it is why no
   slice below §1 budgets work for reading those ids.

**Replacement text for plan §1** (the paragraph ending "a precondition that is
met"):

> A stage is a linkable state and is read: `ProjectView.tsx:167` derives
> `openStage` from the route. A topic and an artifact are linkable in the
> *grammar* only — `projectHref` builds their URLs and `parseRoute` parses them,
> but `TopicList`, `DocumentList`, `ArtifactList` and `ProjectFindings` are each
> mounted with no selection (`ProjectView.tsx:283,435,402,428`) and hold their
> open item in component state. **The grammar is a met precondition; reading the
> id back is not, and is unbudgeted work in slice 3.** `CitationList.tsx:44`
> already emits a `doc` id that nothing reads, so this is a shipped defect and
> not only a gap.

**Slice 3 must be widened** to include: pass `selection.id` into all four
tenants, and add a test per facet asserting the *id* reaches the renderer, not
only that the region mounts. `ProjectView.test.tsx` currently asserts region
membership over `regionOf` only (`:16-58`), which cannot see any of this.

### F2. The breadcrumb still offers "course" and "research" — the exact shape #176 removed from `AskHead`, one file over, still live

`presentation/shell/Breadcrumbs.tsx:90-92`:

```tsx
<a href={projectHref(projectId)}>course</a>
<span className="sep">·</span>
<a href={projectHref(projectId, { facet: 'entity', id: null })}>research</a>
```

Two links, two names the console no longer uses, one destination — differing only
in which MATERIAL tab opens. `8fe734c`'s message states the reasoning for
deleting precisely this from `AskHead`: "Offering one destination twice, under
names the console no longer uses, describes a shape that no longer exists." The
same three lines survived in the breadcrumb because the fix was scoped to the
ask page's own nav. It renders on the standalone `#/s/<id>` route
(`Breadcrumbs.tsx:88`, gated on `projectId` from the session), which is why no
project-page test sees it.

Classification: **WRONG** against plan §3.3's "the run panel and extraction pane
move off the course page" framing — the plan nowhere records that a *course*
link survives. Not stale: it is current code.

**Add to plan §3.3:**

> `Breadcrumbs.tsx:90-92` still offers `course` and `research` as two links to
> one destination, on the `#/s/` route. This is `8fe734c`'s finding surviving in
> a second file. Collapse to one `project` link in the slice that touches the
> breadcrumb; the entity facet is one MATERIAL tab away.

### F3. `FACETS` has nine members, not eight, and the plan says eight twice

`routes.ts:67-80` lists nine: `session`, `topic`, `stage`, `entity`, `doc`,
`file`, `artifact`, `finding`, **`ask`**. Plan §1:44-45 says "`FACETS`
(`routes.ts:67`) is exactly its eight" and enumerates the eight; proposal
§3.1:216 likewise enumerates eight. `ask` was added after the proposal and the
plan did not pick it up.

This matters beyond arithmetic: `ask` is the one facet whose renderer is **not**
`ProjectView` (`App.tsx:138` intercepts it), so a plan that does not know it
exists cannot describe the dispatch correctly — and §2.0 does not (see F4).

**Replacement for plan §1's sentence:**

> `FACETS` (`routes.ts:67-80`) is the proposal's eight plus `ask`, added after
> the proposal was written: `session`, `topic`, `stage`, `entity`, `doc`, `file`,
> `artifact`, `finding`, `ask`. `ask` selects nothing and is a facet anyway
> because it is a place on the project; `App.tsx:138` intercepts it above
> `ProjectView`, which is the one arm of the old two-page dispatch that survives.

Line-number drift in the same paragraph, worth correcting while there: `parseRoute`
is `routes.ts:109` (plan says `:105`), `projectHref` is `routes.ts:211` (plan says
`:207`), the `home` fallback for an unrecognised facet is `routes.ts:130-133`
(plan §1 and §3.1 both say `:126-129`).

### F4. Plan §2.0's "delete the two-arm branch; render `ProjectView` unconditionally" describes a branch that has three arms — and the code says so

Plan §2.0: "`app/App.tsx`: delete `RESEARCH_FACETS` and the two-arm branch in
`CurrentView`; the `project` route renders `ProjectView` unconditionally."

Shipped `App.tsx:127-147` has three arms: `session` → `SessionView`, non-project
→ `TreeView`, and — inside the project route — `selection?.facet === 'ask'` →
`AskView`, *then* `ProjectView`. So `ProjectView` is **not** rendered
unconditionally for the project route. `ProjectView.tsx:60-64` names the plan's
error explicitly: "the plan's §2.0 describes a two-arm branch, and there are
three arms in the code it was written against."

Classification: **WRONG**, and already known to the code but not to the document.
Since slice 0 shipped, this is history rather than instruction, but it is history
a reader of §2.0 will take as a description of the end state.

**Replacement for plan §2.0's Changes bullet:**

> `app/App.tsx`: delete `RESEARCH_FACETS` and the branch that chose between the
> course and research views. The `project` route renders `ProjectView` for every
> facet **except `ask`**, which `CurrentView` intercepts above the project page
> (`App.tsx:138`) because the ask page is one conversation with no parts and
> nothing to read it against. That interception is deliberate and survives the
> increment; `regionOf` maps `ask` to `queue` anyway so the map stays total.

### F5. `topic`'s region is genuinely undecided — the code says QUEUE, the plan says MATERIAL, and both are written down as settled

- Code: `regionOf('topic')` returns `'queue'` (`ProjectView.tsx:69-73`), asserted
  by `ProjectView.test.tsx:57-58` ("`expect(regionOf('stage')).toBe(regionOf('topic'))`").
  `TopicList` is mounted in the QUEUE pane (`ProjectView.tsx:283`).
- Plan §2.3 lists `topic` among "MATERIAL's remaining five facets"; plan §3.1's
  table maps `#/p/<id>/topic/<tid>` → "MATERIAL `topic`"; plan §3.3 says the
  topic dialog "becomes the MATERIAL `topic` facet".
- Proposal §3.3's MATERIAL table also lists `topic` ("a selected topic's detail").

Classification: **UNDECIDED.** Both readings are coherent, and the code's is the
better one:

- *Option A (code, QUEUE).* A topic is a work item — something the project owes
  somebody — which is `regionOf`'s stated test for QUEUE, and it is the same
  argument that puts `stage` there. `TopicList` is already in QUEUE and shipped.
- *Option B (plan, MATERIAL).* A topic's **detail** is material to read, and
  MATERIAL is where the "one reader, one selection model" lives.

**Recommendation: A, with the seam named.** The two documents are conflating a
topic *row* (QUEUE) with a topic *detail* (a reader). Moving the row to MATERIAL
would take the queue's most-used row kind out of the region defined as "what is
there to do", and would contradict a shipped, tested assertion. The detail can be
a `Drawer` or a `Confirm`-style panel opened from the QUEUE row, which is what
`TopicStatusDialog` already is (`TopicList.tsx:38-40`).

**Replacement for plan §2.3's opening line and §3.1's topic row:**

> §2.3: `artifact`, `doc` (corpus), `entity` (graph), `finding` — four facets,
> not five. `topic` is **QUEUE**, not MATERIAL: `regionOf` (`ProjectView.tsx:69`)
> answers `queue` for it on the argument that a topic is a work item, and
> `ProjectView.test.tsx:57` asserts `regionOf('topic') === regionOf('stage')`.
> What MATERIAL was going to hold is a topic's *detail*, and that stays a panel
> opened from the QUEUE row.
>
> §3.1 table: | `#/p/<id>/topic/<tid>` | the research view | **QUEUE, topic row
> selected** |

### F6. `file` — the plan and the code agree, and the plan's §3.1 label is the stale half

`regionOf('file')` returns `'material'` (`ProjectView.tsx:87-88`), with a
comment recording that slice 2 reversed it from `holder`. Plan §2.2's title
("HOLDER **and** MATERIAL `file`") and §3.1's table row (`file` → "MATERIAL
`workspace`") both already say MATERIAL. So there is **no disagreement on the
region** — only on the *name*: the plan and proposal call the MATERIAL facet
`workspace`, the code calls it `file` and labels the tab "Workspace"
(`MATERIAL_TABS`, `ProjectView.tsx:121`). Classification: **VERIFIED** for the
region, **STALE** for the vocabulary — proposal §3.3's facet table uses
`workspace`/`artifacts`/`corpus`/`graph`/`findings`, none of which are URL
segments. The URL segments are `file`/`artifact`/`doc`/`entity`/`finding`.

**Add to plan §3.1, under the table:**

> The proposal's §3.3 facet names (`workspace`, `artifacts`, `corpus`, `graph`,
> `findings`) are tab labels, not URL segments. The segments are `file`,
> `artifact`, `doc`, `entity`, `finding` (`routes.ts:67-80`), and
> `MATERIAL_TABS` (`ProjectView.tsx:119-125`) is where the two vocabularies are
> mapped. Wherever the two documents differ, the code's segment wins.

### F7. The default MATERIAL facet is `artifact`, not `workspace` — and the code's comment misquotes the plan about it

`DEFAULT_MATERIAL = 'artifact'` (`ProjectView.tsx:127`); `MATERIAL_TABS` puts
`artifact` first (`:120`). Proposal §3.3 states "**The default facet is
`workspace`, not `graph`**", and plan §2.3 repeats it: "§3.3's decision that the
default facet is `workspace` rather than `graph`".

`ProjectView.tsx:99-102` says "The plan's §2.3 makes the same call" — it does
not; §2.3 says `workspace`. The bundle *argument* is the same (keep `entity` out
of the default so the ~60 kB `react-force-graph-2d` chunk is not pulled), and
that argument survives either choice, but the chosen default differs.

Classification: **WRONG** in both documents (the code shipped a different default
and is defensible); **WRONG** in the code comment's characterisation of the plan.

**Replacement for plan §2.3's ordering paragraph:**

> The default MATERIAL facet is **`artifact`**, not `workspace`
> (`ProjectView.tsx:127`), and slice 2 shipped it that way: artifacts are what a
> stage declared it produced and the workspace is the tree those declarations are
> made of, so artifacts-then-workspace reads in that order. §3.3's bundle
> argument is unaffected — it rules out `entity` as the default, and both
> `artifact` and `file` satisfy it, since `FileList`/`FileView` are already in
> the main chunk.

Also worth a one-line correction inside `ProjectView.tsx:101-102` when that file
is next touched, since it currently attributes a choice to the plan that the plan
does not make.

### F8. `#/p/<id>/file/<path>` and `#/p/<id>/artifact/<id>` are typed-URL-only entrances

Enumerating what a reader can reach **by clicking** (grep over `projectHref` /
`sessionSelection` / `facet:` in non-test sources — 15 call sites, listed in the
table below):

| Facet | Reachable by click? | Where |
|---|---|---|
| `ask` | yes, two doors | `QueueHeader.tsx:99`, `ProjectList.tsx:394` |
| `session` | yes | `QueueHeader` `onWatch` → `ProjectView.tsx:263` |
| `stage` | yes | `StageList` `onToggleStage` → `ProjectView.tsx:277-279` |
| `entity` | yes, id and all | `GraphPane` `onEntity` → `ProjectView.tsx:446`; tab → `:396` |
| `doc` | tab only (id null) | `:396`; an *id* only from `CitationList.tsx:44`, and see F1 |
| `artifact` | tab only (id null) | `:396` — **no click anywhere writes an artifact id** |
| `finding` | tab only (id null) | `:396` — **no click anywhere writes a finding id** |
| `file` | tab only (id null) | `:396`. Opening a file in `WorkspacePanel` writes a **`session`** selection carrying `path` (`ProjectView.tsx:193-199`), not a `file` selection — `#/p/<id>/file/<path>` is a linkable *entry point* only (`:220`) |
| `topic` | **no** | nothing writes a `topic` selection; see F1 |

Classification: **UNVERIFIED-in-the-plan.** Plan §2.0's "Independently shippable
because it is verifiable by navigation alone: every facet in `FACETS` reaches a
region" was satisfied by a test over `regionOf`, which is a pure function and
cannot see an entrance. That is the same blind spot `8fe734c` names ("no test
asserts that a route is reachable... a suite that only teleports cannot notice
the stairs are gone").

**Add to plan §2.3 as an explicit deliverable:**

> **Reachability, asserted rather than assumed.** For each facet slice 3 touches,
> `App.test.tsx` gains a test that finds the *inbound control* by role and name
> and clicks it, rather than assigning `window.location.hash`. `8fe734c`
> established that distinction after the ask page lost both its doors;
> `ProjectView.test.tsx`'s `regionOf` coverage is a map test and cannot replace
> it. Facets with no inbound control today: `topic`, and `artifact`/`finding`/
> `file` at the id level.

### F9. Plan §3.1's URL table: the "Today" column is stale by three slices, the "After" column is now half-shipped

The table is headed "Today, at `f87443b`" and that commit is now six merges back.
Every row's middle column describes the pre-slice-0 world. Rows that have since
changed:

| Row | Plan's "Today" | Actually, at `9fa6c7b` |
|---|---|---|
| `#/p/<id>` | "the course view (`App.tsx`'s fallback arm)" | `ProjectView`, no selection, MATERIAL on `artifact` (`App.tsx:145`, `ProjectView.tsx:127`) |
| `#/p/<id>/entity/<eid>` | "the research view, entity selected" | MATERIAL Graph tab, entity selected — **the "After" state, shipped** (`ProjectView.tsx:438-447`) |
| `#/p/<id>/topic/<tid>` | "the research view" | QUEUE, topic **not** selected (F1, F5) |
| `#/p/<id>/doc/<sid>` | "the research view" | MATERIAL Documents tab, document **not** selected (F1) |
| `#/p/<id>/stage/<sid>` | "the course view, stage open" | QUEUE, stage open — **shipped** (`ProjectView.tsx:277`) |
| `#/p/<id>/session/<sid>` | "the course view, worker drawer" | HOLDER — **shipped** (`ProjectView.tsx:299-383`) |
| `#/p/<id>/file/…` | "parse, land on the course view, render nothing" | MATERIAL Workspace, path open — **shipped** (`:411-425`) |
| `#/p/<id>/artifact/…`, `/finding/…` | same | MATERIAL tab opens, **id ignored** (F1) |
| `#/p/<id>/ask` | *absent from the table* | intercepted above `ProjectView`, renders `AskView` (`App.tsx:138`) |

The two rows the plan calls "already dead" are **VERIFIED**: `course` and
`research` are not in `FACETS`, `parseSelection` returns `null`, `parseRoute`
returns `home` (`routes.ts:130-133`), asserted at `routes.test.ts:133`. Both the
proposal's §5.1 claim that "`parseRoute` maps both onto the new grammar, so links
survive" and the plan's correction of it stand as written — the plan is right and
the proposal is wrong.

**Recommendation:** re-head the middle column "At `9fa6c7b`" and rewrite it from
the table above, add the missing `ask` row, and mark the four shipped rows as
done so the remaining slices are not re-planned against them. Leaving a "Today"
column dated to a commit nobody is on is how the plan was wrong three times
before.

### F10. `regionOf`, checked one by one — the map itself is sound

Every entry, against `ProjectView.tsx:66-95`:

| Facet | `regionOf` | Plan's assignment | Verdict |
|---|---|---|---|
| `stage` | queue | QUEUE (§3.1) | VERIFIED |
| `topic` | queue | MATERIAL (§2.3, §3.1, §3.3) | **UNDECIDED — F5** |
| `ask` | queue | not assigned (§2.0 does not know it) | **WRONG in the plan — F3/F4** |
| `session` | holder | HOLDER (§2.2, §3.1) | VERIFIED |
| `file` | material | MATERIAL (§2.2, §3.1) | VERIFIED — F6 |
| `entity` | material | MATERIAL (§2.3) | VERIFIED |
| `doc` | material | MATERIAL (§2.3) | VERIFIED |
| `artifact` | material | MATERIAL (§2.3, §3.1) | VERIFIED |
| `finding` | material | MATERIAL (§2.3, §3.1) | VERIFIED |

The function is total over `Facet` by exhaustive `switch` with no `default`
(`:67-94`), so a tenth facet fails to compile rather than silently landing in
QUEUE — which is the property `ProjectView.tsx:56-58` claims and the compiler,
not the test, enforces. `ProjectView.test.tsx:22-23` re-asserts it at runtime
against `FACETS` itself.

`regionOf` is the healthiest thing in this domain. Its weakness is what it cannot
see: it answers "which region" and nothing about renderers, ids or entrances
(F1, F8).

### F11. Proposal §3.4 "Decisions leave the page" — half shipped, half contradicted

- **Approvals move into the shell: VERIFIED.** `DecisionBar` is mounted in
  `Console` above `CurrentView` (`App.tsx:112`), inside the surface, on every
  route. The comment at `:107-111` carries §3.4's argument verbatim.
- **Autonomy moves into the shell: WRONG.** §3.4: "This is also the only honest
  place for autonomy... A policy that governs every session in the process
  sitting inside one project's page is a scope claim contradicted by its own
  placement." Shipped: `AutonomyPanel` is mounted **inside QUEUE**, on one
  project's page (`QueueHeader.tsx:4,123-124`). Only `AutonomyAllowAll` reached
  the shell (`DecisionBar.tsx:1,69`), and that is the per-approval button, not the
  instance-wide policy control.

So §3.4's stated seam — "the duplication between `AutonomyPanel` and
`AutonomyAllowAll`" — is not closed; the two are now in two different regions of
two different components, which is the same duplication with a longer distance
between the halves.

Classification: **UNDECIDED**, and it is a scope question the plan never asked.

- *Option A:* move `AutonomyPanel` to the shell as §3.4 asks. Honest about the
  instance-wide scope; costs a shell control that is meaningless when no session
  is holding anything.
- *Option B:* keep it in QUEUE and drop §3.4's autonomy paragraph. `QueueHeader`
  already gates it on `holdingSessionId` (`:124`), which makes it read as a
  control on *this holder* — which is not what `AutonomyPolicy` is.

**Recommendation: A**, because §3.4's argument is about a scope claim a reader
infers from placement, and B leaves that claim wrong for the sake of a null
check. But this is genuinely the owner's call, and the plan should say so out
loud rather than leave §3.4 reading as shipped.

**Add to plan §3.3:**

> **§3.4 is half shipped.** `DecisionBar` is in the shell (`App.tsx:112`);
> `AutonomyPanel` is not — it is a QUEUE card (`QueueHeader.tsx:123-124`), which
> contradicts §3.4's own argument that an instance-wide policy sitting on one
> project's page is a scope claim its placement denies. Decide before slice 3:
> either move the panel to the shell beside `DecisionBar`, or strike §3.4's
> autonomy paragraph. Do not leave both texts standing.

### F12. Plan §3.4 (Event shapes) — VERIFIED, nothing to change

"Nothing. ... `domain/approval/approval.ts` and `dto.ts` already carry the two
fields". Confirmed present as described by plan §1's own citations
(`dto.ts:243,247`, `approval.ts:21-23`). Nothing in the routing or region work
touches an event, an aggregate or a read model — routes are hash strings parsed
client-side (`routes.ts:109`), and `use-route.ts` is `wouter`'s hash location and
`window.history`. Proposal §5.5's claim likewise stands. `CLAUDE.md`'s
schema-evolution rule is not in play for this domain.

---

## Classification table

| # | Claim | Where | Class |
|---|---|---|---|
| F1 | "A topic, a stage and an artifact are already linkable states" | plan §1 | **WRONG** — only `stage` is read (`ProjectView.tsx:167`); topic/doc/artifact/finding ids are dropped (`:283,435,402,428`) |
| F1 | Citation links keep the reader on the source | `CitationList.tsx:41-44` | **WRONG** — the `doc` id is parsed and ignored; live defect |
| F2 | Breadcrumb offers one destination under two dead names | `Breadcrumbs.tsx:90-92` | **WRONG** — `8fe734c`'s finding surviving in a second file |
| F3 | "`FACETS` is exactly its eight" | plan §1, proposal §3.1 | **WRONG** — nine; `ask` (`routes.ts:79`) |
| F3 | `parseRoute` at `:105`, `projectHref` at `:207`, fallback `:126-129` | plan §1, §3.1 | **STALE** — `:109`, `:211`, `:130-133` |
| F4 | "delete the two-arm branch; `ProjectView` unconditionally" | plan §2.0 | **WRONG** — three arms; `ask` intercepted (`App.tsx:138`) |
| F5 | `topic` is a MATERIAL facet | plan §2.3, §3.1, §3.3; proposal §3.3 | **UNDECIDED** — `regionOf` says `queue` (`ProjectView.tsx:69`), asserted `ProjectView.test.tsx:57`. Recommend QUEUE |
| F6 | `file` is MATERIAL | plan §2.2, §3.1 | **VERIFIED** (`ProjectView.tsx:87-88`) |
| F6 | Facet names `workspace`/`artifacts`/`corpus`/`graph`/`findings` | proposal §3.3 | **STALE** — tab labels, not URL segments (`MATERIAL_TABS`, `:119-125`) |
| F7 | Default MATERIAL facet is `workspace` | proposal §3.3, plan §2.3 | **WRONG** — `artifact` (`ProjectView.tsx:127`) |
| F7 | "The plan's §2.3 makes the same call" | `ProjectView.tsx:101-102` | **WRONG** — §2.3 says `workspace` |
| F8 | "verifiable by navigation alone: every facet reaches a region" | plan §2.0 | **WRONG as verification** — the test is over `regionOf`, a pure map (`ProjectView.test.tsx:16-23`); it cannot see an entrance |
| F8 | `topic`, and ids for `artifact`/`finding`/`file` | code | **WRONG** — no click writes them; typed-URL only |
| F9 | §3.1 URL table, "Today, at `f87443b`" column | plan §3.1 | **STALE** — six merges back; four "After" rows are shipped, `ask` row missing |
| F9 | `#/p/<id>/course` and `/research` already dead → `home` | plan §3.1, §1 | **VERIFIED** (`routes.ts:130-133`, `routes.test.ts:133`) |
| F9 | "`parseRoute` maps both onto the new grammar, so links survive" | proposal §5.1 | **WRONG** — the plan's own §1 correction is right |
| F9 | `#/s/<id>[/at/n][/file/p]` unchanged | proposal §5.1, plan §3.1 | **VERIFIED** (`routes.ts:116-119,193-204`) |
| F10 | `regionOf` total over `Facet`, exported | plan §2.0's spirit | **VERIFIED** — exhaustive switch, no default (`ProjectView.tsx:66-95`) |
| F10 | `session` → HOLDER, exactly one facet | plan §2.2 | **VERIFIED** (`:83`, `ProjectView.test.tsx:49`) |
| F11 | Approvals move into the shell | proposal §3.4 | **VERIFIED** (`App.tsx:112`) |
| F11 | Autonomy moves into the shell | proposal §3.4 | **WRONG / UNDECIDED** — `AutonomyPanel` is a QUEUE card (`QueueHeader.tsx:123-124`); only `AutonomyAllowAll` reached the shell (`DecisionBar.tsx:69`) |
| F12 | Event shapes: nothing | plan §3.4, proposal §5.5 | **VERIFIED** — no event, aggregate or read model in this domain |
| — | Selection is not mirrored into state; address bar is the source of truth | proposal §3.1, `ProjectView.tsx:152-155` | **VERIFIED for the four facets that are read; vacuous for the four that are not** (F1) |
| — | Scrub/file writes replace rather than push | plan §3.3 | **VERIFIED** (`ProjectView.tsx:233-235`, `use-route.ts:23-37`); watching a worker pushes (`:263`) |

---

## What I could not check without running anything

1. **Whether `#/p/<id>/topic/<t1>` visibly does nothing.** I read that
   `TopicList` receives no selection (`ProjectView.tsx:283`) and holds `managing`
   in `useState` (`use-topic-queue.ts:31`). I did not confirm that no ancestor or
   effect reads the route and calls `setManaging`. **Settled by:** `cd frontend
   && npx vitest run src/app/App.test.tsx` with a new case navigating to
   `#/p/x/topic/t1` and asserting the topic dialog is absent — or present, which
   would refute F1's topic half.
2. **Whether `CitationList`'s link is inert in a running app.** Same shape: the
   read says the `doc` id reaches `selection` and no consumer. **Settled by:** a
   test that renders `AskView`, clicks a citation, and asserts the Documents tab
   opens with that source's reader open.
3. **Whether the four inert facets have any test that would go red when they are
   wired.** I read `ProjectView.test.tsx` and `routes.test.ts`; I did not read
   the other ~20 files under `presentation/project` and `presentation/research`.
   **Settled by:** `npx vitest run src/presentation/project src/presentation/research`
   before and after wiring.
4. **The bundle claim under F7.** Whether defaulting to `artifact` versus `file`
   changes the `app-` chunk at all is a `check-size.mjs` question. Neither
   default pulls `react-force-graph-2d`, so I expect no difference, but that is
   reasoning and not measurement. **Settled by:** `cd frontend && npm run verify`
   (the size budget runs only inside the chain).
5. **Whether the breadcrumb's two links render at all in practice.** They are
   gated on `session?.projectId` (`Breadcrumbs.tsx:72,88`), which is populated
   from the session store's head. If a project id is never present on a session
   head, F2 is dead code rather than a live defect — still worth deleting, but
   cheaper. **Settled by:** `npx vitest run src/presentation/shell/Breadcrumbs.test.tsx`,
   or opening `#/s/<id>` for a session in a project.
6. **Nothing in this domain requires a database, a projection, or a real-browser
   run.** Routes are pure string parsing and regions are component composition;
   `CLAUDE.md`'s read-model and browser-suite rules are not engaged by any finding
   above.
