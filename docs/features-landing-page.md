# The landing page — complete feature index

Indexed from `origin/main` at `5a5a7cf` ("Move what-is-running into the nav bar", #86).
Read-only survey; no production code was changed.

Scope: route `home` (`#/`), rendered by `TreeView`, plus the application shell
that is present on this page (topbar, breadcrumbs, connection and drift badges,
agent dock, toasts). Every claim below is taken from code. Where a comment and
the code disagree, the code wins and the disagreement is called out.

Status vocabulary used throughout:

- **BUILT** — built and reachable by a user.
- **UNREACHABLE** — code exists, no user can get to it on this page.
- **UNBUILT** — designed in `docs/design/landing-page.md`, not implemented.

---

## 0. Component and route map

| Layer | File |
|---|---|
| Page root | `frontend/src/presentation/tree/TreeView.tsx` |
| Project list + rows + virtualizer | `frontend/src/presentation/tree/ProjectList.tsx` |
| Session row / fork forest | `frontend/src/presentation/tree/SessionRow.tsx` |
| Two-source session read | `frontend/src/presentation/tree/SessionTree.tsx` |
| Per-project liveness | `frontend/src/presentation/tree/ProjectActivity.tsx` |
| Drift banner (in-page) | `frontend/src/presentation/tree/DriftBanner.tsx` |
| Create project + workflow | `frontend/src/presentation/tree/NewProjectForm.tsx` |
| Loading placeholders | `frontend/src/presentation/tree/Skeletons.tsx` |
| Pure model | `frontend/src/domain/project/landing.ts`, `frontend/src/domain/project/project.ts` |
| Shell | `frontend/src/app/App.tsx`, `presentation/shell/*` |
| Agent dock | `frontend/src/presentation/agents/AgentWidget.tsx`, `use-running-agents.ts` |
| Routes (client) | `frontend/src/presentation/routing/routes.ts` |
| HTTP ports | `frontend/src/infrastructure/http/project-repository.ts`, `session-repository.ts` |
| Routes (server) | `research_team/interfaces/web/app.py`, `presenters.py` |
| Fork tree (server) | `research_team/application/summaries.py` (`build_fork_tree`, `summarize_sessions`) |

Backend endpoints this page touches, all in `app.py`:
`GET /api/projects` (410), `GET /api/sessions` (376), `GET /api/tree` (1346),
`GET /api/workflows` (427), `POST /api/projects` (442),
`POST /api/projects/{id}/workflow` (527), `POST /api/projects/{id}/join` (1105),
`DELETE /api/projects/{id}` (465), `GET /api/projects/{id}/auto-research` (1221),
`GET /api/projects/{id}/workers` (1261), `GET /api/workers` (1239),
`GET /api/health` (1315), `POST /api/summaries/rebuild` (1333),
`GET /api/stream` (1783).

---

## 1. Page-level features

### F1. Purpose sentence — BUILT
- **What** One non-dismissible line explaining what an agent session and a project
  are: *"An agent whose whole session is one event log. A project is where that work
  outlives one conversation — a filesystem and a knowledge graph its sessions share."*
- **Where** `TreeView.tsx:72-75` (`.purpose`).
- **Reached by** Always visible on the populated page. A second, longer two-paragraph
  variant appears on the first-run page (`TreeView.tsx:118-125`).
- **Depends on** Nothing. Static copy.
- **States** One. Deliberately not dismissible (comment at `TreeView.tsx:68-71`).

### F2. First-run page — BUILT
- **What** When the database has no projects *and* no sessions, the whole page is
  replaced by an explanation, a create-project form, and a CLI pointer.
- **Where** `TreeView.tsx:54-61` (the predicate), `TreeView.tsx:115-140` (`FirstRun`).
- **Reached by** Loading `#/` against an empty database.
- **Depends on** Both `/api/projects` and the session forest having *resolved*. The
  predicate requires `!projectsQuery.isPending && !projectsQuery.isError &&
  data.length === 0 && !sessionsPending && sessionRows.length === 0`. The guard is
  explicitly there so a returning user is never told their work is gone mid-load.
- **States** Terminal — it is either shown or not.
- **Rough edge** `sessionsPending` is `tree.isPending` only (`SessionTree.tsx:55`). If
  `/api/tree` **and** `/api/sessions` both error while `/api/projects` returns an
  empty list, `sessionRows` is `[]`, `isPending` is false, and the first-run page is
  shown during a partial outage. Narrow, but it is exactly the failure the guard was
  written to prevent.
- **Note** The first-run copy states you can start from `uv run main.py` and that
  both front ends share one database. §8 records this survived the removal of bare
  sessions; only the "try a prompt without a project" claim was dropped.

### F3. Search across projects and sessions — BUILT
- **What** A single free-text box that filters project rows. A project matches if its
  *name* contains the query, or if **any session inside it** has a `firstMessage`
  containing it.
- **Where** control `TreeView.tsx:81-89`; predicate `landing.ts:179-186` (`matches`);
  applied `ProjectList.tsx:83`.
- **Reached by** Typing in the box, or pressing `/` anywhere on the page.
- **Depends on** Purely client-side over the React Query cache — no search endpoint.
  Therefore it can only search sessions the two session reads already returned.
- **States** Empty query returns everything; no match renders
  `EmptyState title={'Nothing matches "…"'}` with **no detail line and no way to
  clear** (`ProjectList.tsx:112-114`).
- **Gaps** Case-insensitive substring only — no fuzzy, no field qualifiers, no regex.
  Not in the URL, so a search is not linkable and does not survive reload. Sessions
  are searched *only* by first message: not by id, not by any later message, not by
  file path. Project ids are not searched even though `shortId` is displayed.

### F4. `/` keyboard shortcut — BUILT
- **What** Pressing `/` focuses the search box.
- **Where** `TreeView.tsx:38-48`.
- **Reached by** `/` with no modifier, while focus is *not* in an `<input>` or
  `<textarea>`. Modifier-held `/` is ignored so browser shortcuts survive.
- **Not discoverable except** via the placeholder `search projects and sessions  ( / )`.
- **Gap** This is the page's *only* keyboard affordance. There is no `n` for new
  project, no `j`/`k` list traversal, no Escape-to-clear-search, no `?` help.

### F5. New-project disclosure — BUILT
- **What** A `+ New project` button toggles the creation form open and closed.
- **Where** `TreeView.tsx:78-80`, `TreeView.tsx:92`.
- **Reached by** Clicking the accent button. `aria-expanded` is set correctly.
- **Depends on** Local `creating` state only. Closes itself on successful creation
  via `onCreated` (`TreeView.tsx:92`).
- **Gap** The toggle is a plain toggle — clicking it again while the form has text
  discards the text with no warning.

### F6. Recency headings — BUILT
- **What** Project rows are grouped under `Today`, `This week`, `Older`, and
  `Nothing in them yet`, each with a count badge.
- **Where** `ProjectList.tsx:196-226` (`withHeadings`, `HEADINGS`), `landing.ts:163-171`
  (`recencyOf`).
- **Depends on** `now()` from the DI container, deliberately not `Date.now()` in
  render, so tests can pin the clock (`ProjectList.tsx:84-87`).
- **States** A heading only appears when a project falls into it. Headings are
  emitted inline in the flat virtualized array, not as nested groups.
- **Detail** Thresholds are raw milliseconds (`<24h`, `<7d`) — calendar-agnostic on
  purpose. A project with `lastActivity === null` is `empty`; an unparseable
  timestamp degrades to `older`.
- **Subtlety** `lastActivity` is the **newest session *start*** in the project
  (`landing.ts:120-126`), not the last turn. `SessionSummary` carries no later
  timestamp. So a project with a run that has been going for three days still reads
  "3d ago" and sorts under `Older`. `ProjectRollup.lastActivity`'s own docstring says
  this plainly; the *row* does not.

### F7. Ranking — BUILT
- **What** Projects sort by `lastActivity` descending; projects with no sessions sort
  last.
- **Where** `landing.ts:129`.
- **Not built** §8 records that "a live project sorts first regardless of timestamp"
  (§5 of the design) was **not implemented**, because knowing liveness for every
  project means a request per project including ones nobody scrolled to. The live
  marker appears wherever the project happens to sort. **UNBUILT, deliberately.**

### F8. Virtualized project list — BUILT
- **What** Only the rows in view (plus 4 overscan) are in the DOM.
- **Where** `ProjectList.tsx:282-300` (`useVirtualizer`), rendered `302-348`.
- **Depends on** `@tanstack/react-virtual`; the scroll container is the page
  `<section>` (`TreeView.tsx:64`), passed down as `scrollRef`.
- **Load-bearing details, all recorded because they broke once**
  - `getItemKey` keys by project id / `h-<recency>`, not array index. §8: measurements
    cached against an index followed the wrong row and left a **122px hole** at three
    projects (`ProjectList.tsx:231-241`).
  - `scrollMargin: listTop`, re-measured in a `useLayoutEffect` with **no dependency
    array** (`ProjectList.tsx:266-276`), because nothing observable captures "the
    layout above me changed". Invisible at three projects, draws the wrong rows at
    fifty.
  - Every row is *measured* (`measureElement`), not trusted to the estimate, because
    an expanded row is variable height. §8 records that §5's "rows are fixed-height,
    which is what makes this cheap" stopped being true the moment a row carried a
    disclosure.
  - React Compiler is opted out for this component (`eslint-disable
    react-hooks/incompatible-library`) — it cannot memoize the virtualizer's returned
    functions.

### F9. Live refresh from the event stream — BUILT
- **What** The page re-reads itself when the log moves, without polling.
- **Where** `App.tsx:145-163` (`useTreeRefresh`), `shell/use-frame-refresh.ts`.
- **Depends on** the single app-wide `EventSource` (`StreamProvider.tsx`), `GET
  /api/stream`. Only frames of `kind === 'log'` count. Debounced **400ms**
  (`FRAME_DEBOUNCE_MS`) so a burst of a dozen events causes one refetch.
- **Invalidates** `tree`, `sessions`, `allRuns`, `allWorkers`.
- **Active only while** `route.name === 'home'` — a session view has its own finer
  subscription.
- **Gap** `queryKeys.projects()` is **not** invalidated by log frames. A project
  created or deleted by the CLI, or a project's holder changing out from under you,
  does not appear until something else invalidates it. In practice `/api/projects` is
  only invalidated by this page's own mutations (join, delete, create).

---

## 2. The project row

Everything below lives in `ProjectRow` (`ProjectList.tsx:358-514`).

### F10. Project name — BUILT
Plain text (`ProjectList.tsx:383`). **Not a link.** There is no "project page"; the
row's buttons are the only way in.

### F11. Workflow chip — BUILT
- **What** The preset name and progress: `Hybrid · 4/15`.
- **Where** `WorkflowChip`, `ProjectList.tsx:520-542`.
- **Three states**
  - No preset → chip reads `no workflow`, title *"No workflow selected. Projects
    choose one when they are created."*
  - Preset known to this build → `${workflow.name} · ${stage.index}/${stage.of}`,
    title naming the stage id.
  - Preset the build does not ship → chip shows the raw id as the name, no
    progress, title *"Workflow <id> is not available in this build"*. Server-side
    this is `_workflow_of` (`app.py:380-408`), which reports the workflow and a null
    stage rather than 500ing a whole listing over one unknown preset.
- **Design note** "4 of 15" was chosen over the stage id alone because the id says
  nothing about progress.

### F12. Held / free chip — BUILT
`held by <shortId>` (tone `held`, full session id in the title) when
`project.activeSessionId` is set, else `free` (tone `ok`) — `ProjectList.tsx:385-391`.
Per §8 answer 4, this is **informational only**; no person's name is attached, because
the app assumes a single user.

### F13. Live activity chip — BUILT
- **What** An amber `⟳ run · round 3` / `⟳ turn running · 2m` chip when something is
  running in that project.
- **Where** `ProjectActivity.tsx` (`useProjectActivity`, `ActivityChip`); used at
  `ProjectList.tsx:378, 392`.
- **Depends on** two requests per drawn row: `GET /api/projects/{id}/auto-research`
  (`ResearchRepository.current`) and `GET /api/projects/{id}/workers`
  (`WorkerRepository.on`). Refreshed off log frames (F9), never a timer.
- **Precedence** A live run wins and labels `run · round N` (or bare `run` when the
  202 body has no progress yet — `isLive` in `domain/research/run.ts:52-56` treats a
  progress-less run as live on purpose). Otherwise the first worker in the roster
  labels `turn running · <elapsed>` or `<kind> running · <elapsed>`.
- **Failure** `retry: false` on both; a failed read renders **no chip**, never an
  error. `/api/workers` and `/api/projects/{id}/workers` 404 when the roster is not
  wired, and `/auto-research` 404s both for "nothing running" and "feature disabled"
  (told apart by matching `not enabled|AGENT_AUTO_RESEARCH` in the detail text —
  `project-repository.ts:95`). A `ResearchDisabledError` propagates and simply
  produces no chip.
- **Cost** This is the page's N+1. It is bounded to *drawn* rows only, which is why
  the virtualizer matters for correctness of cost, not just of layout. §8 answer 1:
  liveness was judged worth the requests; the `activity` object on `/api/projects` is
  "still the right fix and is still not done".
- **Only the first worker is shown.** `roster.data?.workers[0]` — a project with
  three workers running says nothing about the other two on this page.

### F14. Stat line — BUILT
`ProjectList.tsx:395-404`. Four fields:
- `N sessions` — count of summaries grouped under the project.
- `N files` — **the sum of each session's live-file count**, not distinct files.
  `landing.ts:21-29` is explicit: sessions share a filesystem, so a path two sessions
  touched is counted twice. The row does not say so. The honest number needs a fold
  `/api/projects` does not do.
- relative time of `lastActivity`, with `fullTime` in the `title`; or `no sessions yet`
  with title *"nothing has run in this project"*.
- `shortId(project.id)`, full id in the `title`.

### F15. Resume / New session / Open — BUILT
`ProjectList.tsx:406-433`. The row offers different controls depending on holding:

- **Held** → two buttons.
  - `Resume <shortId>` navigates directly to the holding session
    (`sessionHref`). No request.
  - `New session` (accent) opens the take-over confirmation.
- **Free** → one button, `Open`, which calls `projects.join(id, takeOver: false)` →
  `POST /api/projects/{id}/join` and navigates to the returned session.

Design note (`ProjectList.tsx:407-409`): a held project gets two honest choices rather
than one button that fails. Previously "Join" was offered unconditionally and 409'd.

- **Join warning path** `join.onSuccess` — if the server returns a non-null `warning`
  (the graph attachment failed but the session was created, `app.py:1149-1156`), a
  **bad**-toned toast reads `Joined, but <warning>` and navigation still happens.
- **Join failure** toast `Could not join project: <message>`.
- **Server-side** `join` 409s if the project is already held, and (on take-over) 409s
  with *"the holding session has a turn running; cancel it first"*. There is **no
  control on this page to cancel that turn** — the user must navigate into the session.
- **Process-wide side effect, invisible here** `join` calls `service.attach_project`,
  and `app.py:1115-1126` states plainly that the most recent join wins process-wide:
  a second tab joining a different project changes the tools the first tab's turns run
  with. Nothing on the landing page hints at this.

### F16. Take-over confirmation — BUILT
`ProjectList.tsx:165-190` (`confirmCopy`), rendered via `Confirm`
(`presentation/common/Confirm.tsx`), which is built on `Drawer` and therefore traps
focus, closes on Escape, and returns focus.
- Title: `End session <shortId> and start a new one in <name>?`
- Body: *"Its files carry over to the new session. Its conversation does not."*
- Confirm label: `End it and start a new session`, accent tone.
The wording is kept **verbatim** from the `window.confirm` calls it replaced; only the
container changed.

### F17. Course button — BUILT (conditionally disabled)
`ProjectList.tsx:442-453`. Navigates to `courseHref(project.id)`. **Disabled when
`project.workflow` is null**, with the title *"this project runs no workflow"* — the
server's own 409 sentence from `get_course`. When enabled the title is *"Every stage
of this workflow, and every artifact it owes"*. This directly fixes design §3.4: a
button labelled "Research" used to navigate to the *course* page.

### F18. Research button — BUILT
`ProjectList.tsx:454-460`. Always enabled. Navigates to `researchHref(project.id)`.
Title: *"Topics, documents and the knowledge graph for this project"*. Per the row's
docstring, all four console routes are one click from here.

### F19. Overflow menu → Delete — BUILT
`ProjectList.tsx:464-479`. A `Disclosure` labelled `⋯` (`aria-label="More actions for
<name>"`) containing exactly one control: a danger-toned `Delete`, title *"Retire this
project"*.
- **Confirmation** (`ProjectList.tsx:174-189`): title `Delete project "<name>"?`;
  a first line only when held — `Session <shortId> is still holding it and will be
  ended first.`; then *"Its sessions keep their own logs, files and history — they
  just cannot rejoin. The knowledge graph's contents are left in place."*
- **Request** `DELETE /api/projects/{id}` with `release_holder=true` **only when the
  project is held** (`project-repository.ts:68-74` — sending `false` against a free
  project "reads as a decision that was never made").
- **Server** `app.py:465-503`. 404 for an unknown or never-written project; 409 if
  held without `release_holder`; **409 "the holding session has a turn running; cancel
  it first"** — again with no control here to do that.
- **Result** Success toast `Deleted project <name>.`; failure toast `Could not delete
  project: <message>`. Either way `queryKeys.projects()` is invalidated.
- **The menu holds one item.** It exists so the row's default reading is "ways in"
  rather than "ways to lose things" — but as a one-item menu it is a click that buys
  only concealment.

### F20. Current-session preview — BUILT
`ProjectList.tsx:491-493`. When the fold is closed and a session exists, exactly one
`SessionRow` is shown.
- **Which one** `currentSession` (`landing.ts:142-154`): the session *holding* the
  project if it is present in the summary list, else the newest by `startedAt`. If the
  holder is missing from the summaries it falls back to newest rather than showing
  nothing — a row with no session would read as "nothing has run here", which would be
  a lie.
- **§8 supersession** The design's "the most recent project's sessions are expanded on
  load" was tried and reversed: one project's history pushed every other project off
  the screen. This one-line preview is what replaced it.

### F21. Session fold (fork forest) — BUILT
`ProjectList.tsx:495-504`. Rendered **only when `sessionCount > 1`** — a project with
one session shows it above and a fold offering nothing new is a click that changes
nothing (`ProjectList.tsx:506-508`).
- Label: `all N sessions` closed, `sessions (N)` open.
- Opening replaces the preview (it does not sit above the forest — the current session
  is *in* the forest and showing it twice reads as a duplicate).
- Contents: `SessionForest` (`SessionRow.tsx:57-76`), a recursive `<ul>` preserving
  fork lineage, with `heldBy` threaded down so the holding session gets its `held` chip.
- **Open set is per-project, local, and starts empty** (`ProjectList.tsx:61`). Not
  persisted to `PreferenceStore`, not in the URL — every reload collapses everything.

### F22. "Nothing has run in this project yet" — BUILT
`ProjectList.tsx:509-511`. A bare sentence when `sessionCount === 0`. It does not say
what to do next; the row's `Open` button is the answer but the sentence does not point
at it.

---

## 3. The session row

`SessionRow.tsx:19-48`. Used both as the preview (F20) and inside the forest (F21).

### F23. First message as the headline — BUILT
Truncated to 120 chars via `truncate`. When there is none, the row reads
`no messages yet` in a muted style. This is the deliberate inversion of the old row,
which led with the hex id in the page's only accent colour.

### F24. Fork chip — BUILT
`forked @ <eventIndex>` when `session.forkedAt !== null`. This is the collapsed form
of lineage: inside the fold, lineage is nesting; on a single row it is this chip.

### F25. Failed-turn chip — BUILT
`N failed turns` (tone `fail`) when `session.failedTurns` is truthy. Count only — no
link to the failure, no reason, no way to see which turns.

### F26. Held chip — BUILT
`held`, title *"This session is holding its project"*, when the id matches the
project's `activeSessionId`.

### F27. Short id — BUILT
`shortId(session.id)` as trailing metadata, full id in the `title`.

### F28. Turn / file / age stats — BUILT
`<b>N</b> turns`, `<b>N</b> files`, and `relativeTime(startedAt)` with `fullTime` in
the title. Both counts default to `0` when null.

### F29. Navigate to the session — BUILT
The whole row is a `<button>` calling `navigate(sessionHref(session.id))`.
- **Rough edge, significant** It is a button, not an `<a href>`. No middle-click, no
  ⌘-click into a new tab, no "copy link address", no browser status-bar preview. The
  same is true of every project-row action button (`Resume`, `Course`, `Research`,
  `Open`) — they all call `navigate()`. Only the breadcrumb and the brand mark are
  real anchors. The design doc calls routes "linkable states" and the routing module
  is built entirely around that idea; the landing page does not honour it.

---

## 4. Data sourcing and the two-source fallback

### F30. Two session reads, deliberately — BUILT
`SessionTree.tsx:17-59`.
- `GET /api/tree` gives the **shape** (fork nesting, server-built by
  `build_fork_tree` in `application/summaries.py:77`).
- `GET /api/sessions` gives the flat per-row detail **and the fallback**.
- If the tree projection has drifted and answers empty while sessions plainly exist,
  the flat list is rebuilt into a forest client-side (`summariesAsForest`) and rendered.
  *"A truthful degradation beats a 'no sessions yet' that is a lie."*
- `all` takes whichever source has **more rows** (`SessionTree.tsx:47-50`), because the
  two projections can disagree about *membership*, not only about a field — otherwise a
  project whose only session the tree missed would read "0 sessions" beside a visible
  session list.
- Covered by test `falls back to the session list when the tree projection has drifted
  empty` (`TreeView.test.tsx:203`).

### F31. Per-project forest rebuild — BUILT
`landing.ts:56-84` (`forest`). The browser's copy of `build_fork_tree`, existing for
the same reason: a session whose parent is absent is a **root**, not a session that
vanishes. Here "absent" is the common case, because each partition is one project's
sessions and a fork made from a session in a *different project* must be a root of this
one rather than dragging a foreign parent in.
- Roots sort newest-first (scanned); children sort oldest-first (read as a story).

### F32. `project_id` on every session summary — BUILT (this was the one backend change)
`presenters.py:238-256`. §7 asked for it; without it there is no key to group sessions
under projects at all. §8 records the cost: `SessionSummaryRow` gaining the column
**did** change a stored shape, `CREATE TABLE IF NOT EXISTS` did nothing to the existing
table, and `/api/sessions` and `/api/tree` answered **500 on the only database anybody
had** while a fresh one and the whole test suite were fine. `apply_schema` now
reconciles added columns. This is the origin of the `CLAUDE.md` read-model rule.

---

## 5. Drift, health, and the shell

### F33. In-page drift banner — BUILT
`tree/DriftBanner.tsx`, rendered `TreeView.tsx:99`, directly under the `Projects`
heading and above the list.
- **Depends on** `GET /api/health` → `summaries.{healthy,following,failed_events}`.
  `retry: false`, `refetchOnWindowFocus: false`.
- **Hidden entirely when healthy** or when the health read has not answered.
- **Two states**
  - *Drifted but following*: `The session list has drifted: N events did not apply.`
    plus an explanation and a **`Rebuild the list`** button → `POST
    /api/summaries/rebuild`, which invalidates health, tree and sessions on settle.
  - *Not following*: `The session list has stopped updating.` and, deliberately, **no
    button** — a stopped projection needs a server restart, which a browser cannot do,
    so the banner offers nothing rather than a control that would quietly fail.
- **Rationale** The topbar badge is right-sized on every other page, but this is the
  page whose entire content is that list.
- Test: `says the session list may be lying, in the page rather than only in the
  topbar` (`TreeView.test.tsx:307`).

### F34. Topbar drift badge — BUILT (and duplicated on this page)
`shell/ConnectionBadge.tsx:36-93` (`DriftBadge`), rendered `App.tsx:82`.
Same query, same rebuild mutation, compact wording (`list drifted (N)` /
`list not updating`) and a `rebuild` button. Additionally it **invalidates health on
every stream reconnect** (`ConnectionBadge.tsx:62-68`) — the reasoning being that a
reconnect is exactly when a projection might have failed to come back.
- **On the landing page both F33 and F34 are on screen simultaneously**, reporting the
  same fact with two rebuild buttons. Intentional per the banner's docstring, but it is
  a genuine duplication a redesign should decide about consciously. Note the reconnect
  re-check lives only in the badge, not the banner.

### F35. Connection badge — BUILT
`shell/ConnectionBadge.tsx:17-30`. Three labels: `connecting` / `live` /
`reconnecting`, driven by `StreamProvider`'s `ConnectionState`.
`role="status" aria-live="polite" aria-atomic`, `title="event stream"`, and a
`data-state` of `init|open|down` for CSS.

### F36. Breadcrumbs — BUILT, degenerate on this page
`shell/Breadcrumbs.tsx`. On `home` the trail is a **non-link `<span>` reading
`projects`** (`Breadcrumbs.tsx:47-53`). The brand mark (`App.tsx:60-63`) is the actual
`href="#/"` anchor. On every other route the first crumb *is* a link back here.

### F37. Toasts — BUILT
`shell/Toasts.tsx`. `aria-live="polite"` region; each toast is dismissed by **clicking
it**, with no visible close affordance and no keyboard route to dismiss (it is a
`<div>` with an `onClick`). Tones: `good` / `bad` / `neutral`. Every mutation on this
page reports through it.

### F38. Single application-wide SSE connection — BUILT
`shell/StreamProvider.tsx`. One `EventSource` for the whole app, fanned out to frame
and reconnect listeners. One rather than one per view because the feed is global — a
frame for another session still matters to the tree.

---

## 6. The agent dock (present on this page, #79 then #86)

`presentation/agents/AgentWidget.tsx` + `use-running-agents.ts`, rendered in the topbar
at `App.tsx:81`, to the **left** of the drift and connection badges (the badges describe
the connection, this describes the work).

### F39. Collapsed count — BUILT
A toggle showing a coloured dot and `N running`, or `agents unknown` on failure.
- **Draws nothing at all** when collapsed, `count === 0`, and not failed
  (`AgentWidget.tsx:125`) — on an idle console it takes no width and the breadcrumb
  gets it back. Once open it stays rendered even when the last agent finishes.
- `aria-live="polite"` on the count alone; the full sentence lives on the button's
  `aria-label` (`"3 running. Show what is running."`).
- The word "running" is dropped by CSS at 420px, narrowing the announcement to the
  numeral. The failure wording is never abbreviated.

### F40. Popover with one row per running agent — BUILT
- **Opened by** clicking the toggle.
- **Dismissed by** Escape (returns focus to the toggle) **or a `pointerdown` anywhere
  outside** — `pointerdown` rather than `click` so the popover is gone before the press
  lands and that press still does its job. Not a focus trap, on purpose: the page
  behind must stay usable, since the point is to watch agents while doing something
  else. Both listeners are suppressed while a `WorkerDrawer` is open, because the
  drawer is in front and owns Escape.
- **Focus** moves into the panel's first `<button>` on open, else the panel itself
  (`tabIndex={-1}`). The panel follows the toggle in the DOM so tab order works forward.
- **Persistence** The open/closed choice is stored in `PreferenceStore` under group
  `agents`, pane name `popover`. **The stored name means *open*, inverting the port's
  sense** (`AgentWidget.tsx:18-30`) — a deliberate trade so the default (empty list) is
  *closed*, because a popover over page content must not appear unbidden. A reader
  inspecting `rt.collapsedPanes.agents` in devtools sees a reversed name.

### F41. Agent row fields — BUILT
`AgentWidget.tsx:251-301`. Kind dot (coloured by worker kind, reusing the timeline's
event-kind tokens), kind, project name (or short id while `/api/projects` has not
resolved), elapsed, the transcript sample (`say`), and the last tool call.
- Progressive drop by width: tool call at 560px, elapsed at 420px. Nothing wraps and no
  row changes height, so a row never moves under the cursor.
- The accessible name is one whole sentence rather than the dozen truncated fragments.
- **An extraction has no session**, so its row is a flat `<div>` with title *"This has
  no transcript to open."* rather than a button opening an empty drawer.

### F42. Open a running agent's feed — BUILT
Clicking a readable row opens `WorkerDrawer` (`presentation/course/WorkerDrawer.tsx`)
— a focus-trapping drawer — titled `<detail> · <project name or short id>`, which is a
better name than the drawer's own `Watching 3f2a…` for a reader who arrived from here.
**This is the only cross-project way into a live transcript in the console.**

### F43. Roster sourcing — BUILT
`use-running-agents.ts`.
- **One request**: `GET /api/workers`, which folds only projects its supervisors named
  (`app.py:1239-1259`). A widget on every page cannot cost more.
- Refreshed off frames of kind `log` **or `dispatch`**, via `useFrameRefresh` (400ms
  debounce) — never a timer.
- Project **names** cost `GET /api/projects` and are fetched **only when the widget is
  open** (`enabled: expanded`). On the landing page it is already cached and free.
- Transcript tails are folded from raw `log` frames **only while open**, subscribed
  *without* the debounce — debouncing would drop every frame but the last of a burst
  and the sample would skip whole tool calls. Bounded by `MAX_TRACKED` inside
  `remember`, not by filtering against the roster (filtering needs the roster, which
  resolves after the first frames arrive, and doing it that way left rows blank).
- **`failed` is only a rejection.** An empty array is the ordinary answer and is never
  drawn as an error, or an idle console would carry a red box on every page.
- **What counts as running** is `Roster.workers` and nothing else — run, dispatch, turn
  and extraction all count; a session merely *attached* to a project counts for nothing.

### F44. Dock empty / failed states — BUILT
Open with nothing running: `Nothing is running right now.` Open after a rejection:
`Could not read what is running.` Neither offers a retry; the next frame asks again.

---

## 7. Creating a project

`tree/NewProjectForm.tsx`. Used twice — inline on the populated page (F5) and
unconditionally on the first-run page.

### F45. Name field — BUILT
`aria-label="Project name"`, placeholder `project name`. **Enter submits**
(`NewProjectForm.tsx:100-102`) because the form is three controls and someone who has
typed a name has already made every decision it asks.
- Empty/whitespace name → bad toast `Enter a project name first.` and no request.
- Duplicate name → server 409 `project 'X' already exists (<id>)` (`app.py:453-459`),
  surfaced as a toast.

### F46. Workflow select — BUILT
- **Options** every preset from `GET /api/workflows`, in the server's deliberate
  recommendation order (`app.py:427-440` — the hybrid is first because it is the one
  that does not require expertise the user came here without), plus a trailing
  `no workflow` option with value `""`.
- **The default is the first preset**, not `no workflow` — §8 answer 2. The old default
  quietly foreclosed the course view for anyone who never opened the menu.
- **`chosen === null` means "nobody has touched the select"**, distinct from having
  chosen `no workflow`, so the default can follow the server's ordering once presets
  arrive (`NewProjectForm.tsx:49-53`).
- **Why here and only here** A project may choose a workflow **once**; the aggregate
  refuses a second selection because a run's audit trail is gated by one preset's stage
  list (`app.py:527-555`). Creation is the moment the choice is free.

### F47. Visible preset label — BUILT
`NewProjectForm.tsx:122`. The server's `preset_label` — a whole function whose job is to
say what a preset produces and where it stops — is rendered **under** the control for
the current selection, because inside an `<option>` it was invisible until the menu
opened and gone the moment it closed. Selecting `no workflow` shows its cost instead:
*"No course view for this project. Research and sessions still work."*

### F48. Two-call creation — BUILT, with a comment/code disagreement
`POST /api/projects` then `POST /api/projects/{id}/workflow`.
- Success toast: `Created project X running Y.` or `Created project X.`
- The docstring at `NewProjectForm.tsx:60-62` says *"this reports the halves
  separately: a user told creation failed would try again and hit the duplicate-name
  409."* **The code does not do this.** There is a single `onError` handler
  (`NewProjectForm.tsx:76`) emitting `Could not create project: <message>`. If the
  *workflow* call fails, the project exists, permanently workflow-less, and the user
  is told creation failed — the exact trap the comment claims to have avoided. Retrying
  then hits the 409. **This is a real defect and a documented case of prose outrunning
  code.**
- Presets query is `retry: false`; a failure costs the choice, not the page — the select
  degrades to its single `no workflow` option, silently.

---

## 8. Loading, empty, and error states — full matrix

| Region | Loading | Empty | Error |
|---|---|---|---|
| Whole page | Falls through to `ProjectList`'s skeletons; the purpose line, actions and heading render immediately | `FirstRun` (F2) | none of its own |
| Project list | `SkeletonRows count={4}` — blocks of the right size, **not** a "loading…" line, because every log frame invalidates this page and a text line appearing/vanishing is what makes a live page feel unstable (`Skeletons.tsx`) | `EmptyState "No projects yet."` with a detail explaining that pre-project sessions cannot be reached from here | `ErrorBox "Could not load projects"` **with a Retry** calling `query.refetch()` |
| Search result | — | `EmptyState "Nothing matches "…""`, **no detail, no clear button** | — |
| Session forest | no skeleton of its own | preview absent; `Nothing has run in this project yet.` | **silent** — a failed `/api/tree` renders nothing and says nothing (`useSessionForest` returns `error` and **no caller reads it**) |
| Activity chip | no chip while pending | no chip | no chip, no retry |
| Drift banner | hidden | hidden when healthy | hidden — a failed `/api/health` is indistinguishable from healthy |
| Agent dock | not drawn when idle and closed | `Nothing is running right now.` | `agents unknown` / `Could not read what is running.` |
| New-project presets | select renders with only `no workflow` | same | same, silently |
| Toasts | — | — | every mutation failure lands here |

Mid-stream behaviour: rows update in place off debounced log frames; skeletons do not
reappear on refetch (React Query keeps previous data), so the page does not flash.

---

## 9. Dead ends and rough edges

1. **`/api/projects` folds one aggregate per project, on every load.**
   `app.py:410-425` loops `service.project_state(project_id)` for every project. The
   landing page's first paint pays this, and the agent dock pays it again whenever it is
   opened on another page. `landing.ts:96-99` and §8 answer 1 both name it; the
   `activity` object that would fix it is **still not built**.
2. **Two more requests per drawn row** for the liveness chip (F13) on top of that
   listing. Bounded to drawn rows, which makes it survivable, not cheap.
3. **Nothing on the page is a link.** Every navigation is a `<button>` calling
   `navigate()`. No ⌘-click, no middle-click, no copy-link, no status-bar preview —
   on a page whose entire job is navigation, in an app whose routing module is built
   around linkable state.
4. **Controls that can fail with no remedy here.**
   - `New session` / `Delete` on a project whose holder has a turn running → 409
     *"cancel it first"*, with no cancel control on this page.
   - `Course` on a project whose preset this build does not ship: the button is
     *enabled* (`project.workflow` is non-null) but the course page has no stage list.
     Only the disabled-for-no-workflow case is handled.
   - `Delete` → 404 for an already-deleted project; the row stays until the invalidation
     lands.
   - The dock's roster and both liveness endpoints 404 when unwired; `/auto-research`
     404s for "disabled" and "nothing running" alike, told apart by string-matching the
     detail text.
   - The drift banner's *not following* state is an explicit dead end by design: the
     server must restart, and the page says so.
5. **Empty states that do not say what to do next.** `Nothing matches "…"` (no clear
   control); `Nothing has run in this project yet.` (does not point at `Open`);
   `Nothing is running right now.`
6. **Things that need a manual refresh.** `queryKeys.projects()` is invalidated only by
   this page's own mutations — a project created, renamed or deleted by the CLI, or a
   holder released elsewhere, does not appear until you act or reload. Log frames
   refresh sessions and liveness but not the project list.
7. **`fileCount` double-counts** shared paths across sessions (F14) and the row never
   says so.
8. **`lastActivity` is session *start*, not last turn** (F6) — a long-running project
   can read "3d ago" under `Older` while a run is live in it, with the live chip right
   beside the stale timestamp.
9. **The workflow-creation error message is wrong** (F48) and will send users into a
   duplicate-name 409.
10. **Search and fold state are ephemeral** — not in the URL, not in `PreferenceStore`.
    Every reload collapses everything and clears the search.
11. **Only the first worker per project** is reported by the row chip (F13).
12. **`failedTurns` is a dead-end count** — no link, no reason, no drill-in.
13. **Toasts dismiss on click only**, with no keyboard route and no visible close.
14. **Two drift reporters on screen at once** (F33 + F34).
15. **The `⋯` menu holds exactly one item.**
16. **First-run can be shown during a partial outage** (F2).
17. **A failed `/api/tree` is entirely silent** — `useSessionForest` exposes `error` and
    `refetch` and **nobody consumes either**. UNREACHABLE code.

---

## 10. What a power user cannot do that the model would support

- **Rename a project.** `Project` has a name; there is no rename command exposed and no
  control. Names are the only human handle on a project.
- **Open a project's *page*.** There is no project route. `#/p/{id}/course` and
  `#/p/{id}/research` exist; a plain project view does not, so the row is the only place
  a project's own facts appear.
- **Select or change a workflow after creation.** `POST /api/projects/{id}/workflow`
  and `GET .../workflow` both exist and the *first* selection on an unset project would
  succeed — but the form is only reachable at creation. A project created without a
  workflow can never gain one through this UI, even though the aggregate would accept
  it. **BUILT server-side, UNREACHABLE from the landing page.**
- **Release a project without deleting it or taking it over.** `POST
  /api/sessions/{id}/release` exists (`session-repository.ts:46`, `app.py:1076`) and is
  not offered here — the only ways to free a held project are take-over or delete.
- **Cancel a running turn or run from the landing page.** `POST
  .../auto-research/cancel` and `.../turns/cancel` both exist; §7 scoped run control to
  the course page. This is why the two 409s in §9.4 are dead ends.
- **Start a run from here.** `ResearchRepository.start` exists and is not wired to this
  page.
- **Fork a session from the list.** `POST /api/sessions/{id}/forks` exists; forking is
  only available inside the session view. The forest *displays* lineage but cannot
  create any.
- **Sort or filter by anything but recency and substring.** No sort by name, size,
  workflow, stage, or liveness; no "held only", "live only", "has failed turns" filters.
  Every field is already client-side.
- **Bulk anything.** No multi-select, no bulk delete or archive.
- **Archive rather than delete.** Delete is the only lifecycle verb.
- **See or reach sessions predating projects.** The empty state admits they exist and
  are unreachable; nothing lists them. `SessionStarted.project_id` became required in
  #65, which is what made this honest.
- **Search a session by anything but its first message**, including its id — which is
  the thing the row displays.
- **Link to a filtered view**, or to an expanded project.
- **See per-project distinct file counts, or true last-turn time** — both need server
  folds that do not exist.

---

## 11. Where this page's model of the world disagrees with the other pages'

This is the entry point, so what it implies the app *is* frames everything after it.

1. **It implies a project is a row; every other page implies a project is a place.**
   Course and research are full project-scoped views at `#/p/{id}/...`. The landing
   page has no project route to hand off to — it hands off to *one of a project's two
   sub-views*, so a user's mental model of "the project" is assembled from a row and
   two destinations that never introduce themselves as parts of one thing.

2. **It implies sessions live inside projects; the session view implies sessions are
   the document.** `SessionView` is the deepest, richest surface — scrub, files,
   approvals, turns, forks — and its breadcrumb (`Breadcrumbs.tsx:68-91`) names the
   project only by **short id**, because *"a transcript knows which project it belongs
   to, but not what that project is called"* and fetching the name would delay every
   session load. So the landing page names projects and the session page cannot. A
   user who navigates in loses the vocabulary they arrived with.

3. **It implies "activity" is a chip; the course page implies activity is a workspace.**
   The row's `⟳ run · round 3` is derived from the same `ResearchRepository.current` and
   `WorkerRepository.on` the course page uses to *steer* a run. §7 fixed this boundary
   ("this page reports that a run exists; it does not steer one") — but the effect is
   that the page which tells you something is happening is the one page that can do
   nothing about it.

4. **It implies a workflow is a chip with progress; the course page implies a workflow
   is the spine of everything.** `Hybrid · 4/15` is the only mention of stages on the
   landing page. A project with `no workflow` reads here as a project missing one small
   chip, and reads on the course page as a permanently 409'd view.

5. **It implies the fork tree is a per-project detail; `/api/tree` still models it as
   global.** `build_fork_tree` builds one forest across all sessions; `landing.ts`
   deliberately re-partitions it per project and makes cross-project forks into roots.
   So the server's structure and the page's structure are genuinely different trees, and
   a fork whose parent lives in another project silently loses its parent here while the
   session page's breadcrumb still shows `← forked from`. **Two views disagree about a
   session's ancestry, and both are "right".**

6. **It implies research is a per-project destination; the agent dock implies work is
   global.** The dock is the only cross-project surface in the console — it aggregates
   every running agent everywhere, and its rows open transcripts across project
   boundaries. Nothing else in the app admits that more than one project can be doing
   something at once. On the landing page these two models sit inches apart in the same
   viewport.

7. **It implies the session list may be lying; no other page says so in its content.**
   Drift is a page-level banner here and a corner badge elsewhere. Course, research and
   session views are equally projection-backed in places and say nothing.

8. **It implies a single user.** "held by 3f2a…" is informational, take-over attaches no
   name (§8 answer 4), and `join` changes the attached project **process-wide**
   (`app.py:1115-1126`). A second browser tab is an unmodelled entity everywhere, and
   the landing page — the page with a "held by" chip on every row — is where that
   assumption is most visible and least stated.

9. **It implies the CLI is a first-run alternative.** The `uv run main.py` pointer
   appears only on the empty page (§8 answer 5). A returning user is never told the two
   front ends share one database, which is exactly when a session appearing from nowhere
   needs explaining.

---

## 12. Confidence notes

- Everything marked BUILT was read in source on `5a5a7cf`. Nothing was exercised in a
  browser; layout, responsive breakpoints and CSS-driven behaviour (e.g. the dock's
  560px/420px drops, whether `.view-home` is genuinely the scroll container) are taken
  from comments and class names, not verified visually.
- The F48 defect is read from code and is confident; I did not write a test to prove it.
- §9.6 (projects not invalidated by log frames) is from `App.tsx:145-163` — I grepped
  for other invalidators of `queryKeys.projects()` and found only this page's own
  mutations and `NewProjectForm`. Reasonably confident, not exhaustive.
- The §11 claims are interpretation, not code facts, and are the part most worth a
  second reader.
