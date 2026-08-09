# The landing page

Read out of the working tree at `frontend/src/presentation/tree/`,
`frontend/src/styles/`, and `research_team/interfaces/web/` on branch `main`
(after `3e6a366`). Line numbers are pointers, not contracts.

The owner's complaint is that this page is "so difficult to use". This document
is an attempt to say *why*, against the actual components, and then to propose
one layout rather than a menu of them. Where a recommendation is non-obvious it
says what would falsify it.

---

## 1. What this software is

**research-team runs a coding-and-research agent whose entire session — every
message you send, every reply, every tool call, every file it writes — is one
ordered event log, and everything you see is folded back out of that log.**
That is not an implementation detail you can ignore, because it is the whole
product: you can scrub a session back to any moment and watch the workspace
refold to how it was, fork from that moment into a parallel branch, read the
full provenance of any file the agent touched, and pick a session back up days
later in a different process. Work that outlives one conversation lives in a
**project** — a shared virtual filesystem and knowledge graph that successive
sessions inherit, one holder at a time — and a project can be given a
**workflow**, a staged course-design methodology with artifacts it owes at each
stage, or worked as a **research** queue of topics, documents and an extracted
knowledge graph.

The landing page has to make that legible without saying it. Today it says
almost none of it.

## 2. Who uses it, and what they want first

There is one user, and the environment tells us a lot about them. There is no
authentication (`README.md`, B18), the server binds `127.0.0.1` by default
(`AGENT_WEB_HOST`), the model endpoint defaults to `localhost:8080`, and the
console shares a SQLite file with a terminal REPL. So: **a single operator on
their own machine, running a local model, who also uses the CLI.** Not a team,
not a tenant, not a visitor. Everything below assumes that, and a good deal of
it would be wrong for a hosted multi-user build — see §7.

### First run — nothing exists

The database is empty. What this person needs, in order:

1. **Confirmation that the thing is alive and connected.** Already served by
   `ConnectionBadge` in the topbar, and it is the one part of the current page
   that is not a problem.
2. **A sentence saying what this is.** They may have just typed `uv run web.py`
   after cloning. The current page offers `Every session is an event log. Forks
   branch from an event index.` — which is true, and is a sentence you can only
   parse if you have already read the README.
3. **One action.** Not two.

The single most likely next action is **create a project**, and it is worth
being firm about why, because the current page's default is the opposite. A
bare session has no filesystem lineage, no knowledge graph, no course, no topic
queue, and cannot be given any of them later — `NewProjectForm`'s own docstring
records that the workflow choice is available only at creation because the
aggregate refuses a second selection. A session created from the tree page is
therefore a dead end for every feature the last four merges added. It is the
right tool for "try a prompt", which is not what a first-run user is doing.

*What would falsify this:* if telemetry (or the owner) showed that most first
sessions really are throwaway prompt tests, then "New session" deserves parity.
There is no telemetry, so this is a judgement, and it is reversible — it is one
button's tone.

The information hierarchy that follows: **statement of purpose → one primary
action → a quiet second path (bare session, or the CLI, which is genuinely
easier for a first prompt).**

### Returning — many projects, more sessions

Sessions accumulate much faster than projects: every `/project use`, every
take-over, and every fork mints one. So the returning user's ratio is
lopsided — a handful of projects against dozens or hundreds of sessions. Their
question is almost never "which of my 140 sessions"; it is **"where was I"**,
which resolves to one project, and then to one of that project's four
destinations (its holding session, its course, its research page, or a new
session in it).

The single most likely next action is **resume the most recently active
project.** Second is **look at what an autonomous run did while I was away** —
the `AutoResearchDriver` is explicitly designed to run unattended for a long
time, so "come back and check" is a first-class arrival.

The hierarchy that follows: **most-recent project, with its current state
readable without a click → its four destinations → everything else, ranked by
recency and searchable → loose sessions last.**

## 3. What is wrong with the page today

### 3.1 It is named after the wrong thing, three times

`TreeView.tsx:41` renders `<h1>Sessions</h1>`. `Breadcrumbs.tsx:52` renders
`fork tree` for this route. The brand link and every "back" link call
`treeHref()`. The route is `{ name: 'tree' }`. Four names, none of them
"projects", for a page whose most consequential content is projects.

That is not a copy nit. It sets the page's subject, and the layout follows it:
sessions get `<h1>` and the top of the document, projects get `<h2>` and
whatever is left. The durable unit is below the ephemeral one.

### 3.2 The two lists have no visible relationship

A project row can name the one session holding it (`activeSessionId`). A
session row cannot name its project — because the data is not there.
`summary_view` (`presenters.py:229`) returns `id`, `started_at`, `turns`,
`files`, `first_message`, `forked_from`, `forked_at`, `failed_turns`, and no
`project_id`, even though `session_view` (`presenters.py:181`) has one and
`SessionProjection` carries it. `/api/tree` inherits the same shape
(`presenters.py:242`).

So the fork tree is a flat pile of anonymous ids, and the project list is a
second pile that happens to point at one member of the first. A reader cannot
answer "which of these sessions belong to atlas?" from this page at all. This
is the single largest structural defect, and it is *four lines of Python* to
fix.

### 3.3 Rows lead with the one thing nobody recognises

`SessionNode` puts `shortId(node.id)` first, in `.node-id`, which `tree.css:80`
colours `var(--accent)` — the page's only accent, spent on a hex string. The
first user message, the only field a human wrote, is the subordinate
`.node-msg` beside it, truncated to 120 characters and `white-space: nowrap`
(`tree.css:87`), so it is clipped further by whatever width is left after
chips. Scanning for "the one where I asked about spaced repetition" means
reading the second column of every row.

### 3.4 The research view cannot be reached from here

`ProjectList.tsx:150-166` renders one button whose label switches on
`project.workflow` — `Course` if there is a workflow, `Research` if not — and
whose `onClick` is `navigate(courseHref(project.id))` in **both** cases.
`researchHref` is never imported by any file under `presentation/tree/`.

So the button labelled "Research" navigates to the course page. That page does
handle it gracefully — `CourseView` renders `RunPanel` above the course and
relays the 409 from `get_course` (`app.py:524`) as an honest "No course to
show" — and the run panel is arguably what someone pressing "Research" wants.
But the *research view* (`#/p/:id/research`: topics, seeding, documents, the
knowledge graph — the whole of the 2026-08-08 design) is reachable only by
going to the course page first and pressing "Research" there. One of the
console's four routes has no entry point on the console's landing page.

### 3.5 The most important control on the page is unstyled

`grep -rn "view-head-actions" frontend/src/styles/*.css` returns nothing.
`grep -rn "node-actions"` returns nothing. Both classes are used —
`view-head-actions` by `TreeView`, `NewProjectForm`, `CourseView` and
`ResearchView`; `node-actions` by `ProjectList` — and neither has a rule in any
of the seventeen stylesheets.

Concretely: the project-creation row is a text input, a `<select>` and a button
laid out as raw inline-block elements with no gap, no alignment and no wrap
behaviour, and the four buttons on every project row butt directly against each
other. Creating a project is the most consequential thing this page does and it
looks like an accident, next to a "New session" button that gets the full
`.btn-accent` treatment.

### 3.6 A permanent choice is offered as an unlabelled default-off dropdown

The workflow `<select>` has no visible label — only `title="Workflow this
project runs"` — and defaults to `no workflow`. Per `NewProjectForm`'s own
comment, the aggregate refuses a second selection, so this default permanently
forecloses the course view for that project (`get_course` 409s: "this project
runs no workflow"). `WorkflowPreset` carries `terminatesAt`, `produces` and
`hasValueFilter` precisely because choosing wrong is expensive, and
`preset_label` on the server exists to spend a whole line explaining each
option — and the UI renders that carefully written line inside an `<option>`,
where it is invisible until the menu is open and gone the moment it closes.

### 3.7 Nothing on the page is happening

`useTreeRefresh` (`App.tsx:118`) invalidates the tree and session queries on
every log frame, debounced 400ms. So rows *do* change under the reader — turn
counts tick, file counts tick — with nothing to say why, and nothing that says
"a turn is running in this session right now". `TurnRepository.current`,
`WorkerRepository.on` and `ResearchRepository.current` all exist and are all
read by the course page; none is read here. The page that shows you everything
is the one page that cannot show you what is in flight — which matters most for
exactly the returning user of §2, who left a run going.

### 3.8 It has no answer for scale, and no tests

`SessionTree` renders `TreeLevel` recursively over every node the server
returns; `ProjectList` maps every project. No search, no filter, no sort
control, no pagination, no virtualization — though `@tanstack/react-virtual` is
already a dependency and already used, with a good comment about why, in
`research/DocumentList.tsx:26`.

Ordering is worth a note of its own: `summarize_sessions` sorts newest-first,
and then `build_fork_tree` nests, so a fork made this morning sits under a
parent from March, arbitrarily deep in the document. Recency and lineage are
fighting, and lineage wins.

And `frontend/src/presentation/tree/` is the only directory under
`presentation/` with **no test file at all** — `course/`, `research/`,
`session/`, `shell/` and `routing/` all have them. Everything asserted above is
unpinned, and so is everything below.

### 3.9 Smaller things, listed rather than argued

- Two `window.confirm` dialogs (`confirmTakeOver`, `confirmDelete`). The
  *wording* is excellent and should survive verbatim; the native modal in an
  app that ships `Drawer.tsx` and a toast system should not.
- The tree page has two responsive rules in total (`responsive.css:56-66`):
  padding, and stacking `.view-head`. Nothing else adapts.
- `DriftBadge` — the only signal that the session list may be lying — is a
  small badge in the topbar, on the one page whose entire content is that list.
- `EmptyState` for sessions suggests running `uv run main.py`. Good instinct,
  wrong place: it is the first-run answer, buried inside a component that only
  renders when the first-run answer is needed and is then followed by a second
  empty state for projects saying something different.

## 4. The proposed layout

**Projects are the page. Sessions are a detail of a project.** That is the one
decision everything else follows from, and it is the inversion of what is there
now.

Four regions, top to bottom:

1. **Purpose line** — one sentence, always present, `--fg-dim`, `--t-sm`. Not a
   dismissible banner: it costs one line and it is the only thing telling a
   returning user's colleague what they are looking at.
2. **Action bar** — `New project` (accent), a search field, `New session`
   (quiet). Search is present from the start but only *useful* later; see §5.
3. **Projects** — one row per project, ordered by last activity, each carrying
   its state and all four of its destinations. Its sessions live inside it, in
   a `Disclosure` (the primitive already exists in `common/primitives.tsx`),
   collapsed by default.
4. **Loose sessions** — sessions belonging to no project, as the fork tree they
   are today, under a heading that says what they are.

Above the fold, at 1440×900: the purpose line, the action bar, and roughly the
first five project rows. That is the intended budget. A returning user should
see their project without scrolling; a first-run user should see the whole page.

### Reaching the four routes

Every route becomes reachable in one click from a project row:

| Destination | Control | Route |
|---|---|---|
| the holding session | `Resume` (or `Open` when free) | `sessionHref` |
| a new session in it | `New session` (take-over confirm) | `sessionHref` |
| the course | `Course` — disabled with a reason when there is no workflow | `courseHref` |
| the research page | `Research` | `researchHref` |

Two rules make that honest. **`Course` is disabled, with the server's own
reason as its title, when `project.workflow` is null** — rather than being
relabelled "Research" and sent somewhere else. **`Research` always goes to
`researchHref`**, because that is what the word means everywhere else in this
console. The autonomous-run controls stay on the course page where they are;
the project row surfaces a *run* as state (§ below), not as a control.

### What a project row shows

Name (the headline, `--fg`, `--t-lg`), then, in one dim monospace stat line
below it: workflow and stage (`hybrid · 4/15`), holder state, session count,
last activity. Chips carry only the two things you want to notice *before*
clicking: `held by 3f2a…` and, when something is in flight, a live marker.

The live marker is the one genuinely new read on this page. A project row
should say `run · round 3` or `turn running · 2m` when there is one, sourced
from `ResearchRepository.current` and `WorkerRepository.on` — the same ports
the course page already uses. This is the fix for §3.7 and it is what makes the
page worth leaving open.

*Cost, stated plainly:* that is two extra requests per project on a page that
already does one fold per project server-side (§5). It should be one request —
see the open question in §7.

### First run

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ▪ research-team                              fork tree            ● live │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                                                                          │
│              An agent whose whole session is one event log:              │
│              every message, tool call and file write, in order.          │
│              Scrub it back, fork it, and pick it up later.               │
│                                                                          │
│              A project is where work outlives one conversation —         │
│              a filesystem and a knowledge graph its sessions share.      │
│                                                                          │
│              ┌──────────────────────────────────────────────┐            │
│              │ project name                                 │            │
│              ├──────────────────────────────────────────────┤            │
│              │ Workflow ▾  hybrid — design + materials      │            │
│              │             ends at v1.build (spine 11)      │            │
│              ├──────────────────────────────────────────────┤            │
│              │                          [ Create project ]  │            │
│              └──────────────────────────────────────────────┘            │
│                                                                          │
│              Only trying a prompt?  Start a bare session  ·  or          │
│              run  uv run main.py  in a terminal — both front             │
│              ends share one database.                                    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

The form is the page, not a row in a header. The workflow select carries its
`preset_label` text *visibly* under the control for the current selection,
which is what that server-side function was written for. `no workflow` remains
selectable and remains honest about what it costs — "no course view; research
and sessions still work" — but it is no longer the default. The default is the
first preset, which `list_workflows` already orders deliberately ("the hybrid
is first because it is the one that does not require that judgement").

*What would falsify defaulting to a preset:* if most real projects turn out not
to be course-design projects at all, defaulting to a course workflow is worse
than defaulting to none. The owner knows this and I do not; it is one line.

### Populated

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ▪ research-team                              projects             ● live │
├──────────────────────────────────────────────────────────────────────────┤
│ An agent whose whole session is one event log. A project is where that   │
│ work outlives one conversation.                                          │
│                                                                          │
│ [ + New project ]   [ search projects and sessions        ]  New session │
│                                                                          │
│ PROJECTS                                                       4 · 1 run │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ atlas                          hybrid · 4/15   ⟳ run · round 3       │ │
│ │ 6 sessions · 41 files · active just now                              │ │
│ │ [ Resume 3f2a ] [ New session ]   [ Course ] [ Research ]        [⋯] │ │
│ │ ▸ sessions (6)                                                       │ │
│ ├──────────────────────────────────────────────────────────────────────┤ │
│ │ retention-review               addie · 9/12    held by 91cc          │ │
│ │ 3 sessions · 12 files · 2h ago                                       │ │
│ │ [ Resume 91cc ] [ New session ]   [ Course ] [ Research ]        [⋯] │ │
│ │ ▾ sessions (3)                                                       │ │
│ │   ┌────────────────────────────────────────────────────────────────┐ │ │
│ │   │ How does spacing interval affect retention?          91cc·held │ │ │
│ │   │ 14 turns · 12 files · 2h ago                                   │ │ │
│ │   ├────────────────────────────────────────────────────────────────┤ │ │
│ │   │ └ Draft the assessment spec              forked @ 31    6b0e    │ │ │
│ │   │   4 turns · 3 files · 1d ago                     1 failed turn  │ │ │
│ │   └────────────────────────────────────────────────────────────────┘ │ │
│ ├──────────────────────────────────────────────────────────────────────┤ │
│ │ sandbox                        no workflow     free                  │ │
│ │ 1 session · 2 files · 6d ago                                         │ │
│ │ [ Open ]                          [ Course ]* [ Research ]       [⋯] │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│                        * disabled: this project runs no workflow          │
│                                                                          │
│ SESSIONS OUTSIDE ANY PROJECT                                    2 · older │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ try the fizzbuzz thing                                    a91f       │ │
│ │ 2 turns · 1 file · 3d ago                                            │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

Note what moved. The session's first message is now the headline and the id is
the trailing, dim, monospace field — the inverse of §3.3. Fork lineage survives
inside the disclosure, where it is a *relationship between three rows* rather
than a top-level document structure. `[⋯]` holds Delete and anything else
destructive, so the row's default reading is "ways in", not "ways to lose
things".

### Narrow (≤ 820px)

```
┌────────────────────────────────┐
│ ▪ research-team         ● live │
├────────────────────────────────┤
│ An agent whose whole session   │
│ is one event log.              │
│                                │
│ [ + New project ]              │
│ [ search                     ] │
│                                │
│ PROJECTS              4 · 1 run│
│ ┌────────────────────────────┐ │
│ │ atlas                      │ │
│ │ hybrid · 4/15              │ │
│ │ ⟳ run · round 3            │ │
│ │ 6 sessions · just now      │ │
│ │ [ Resume 3f2a ]            │ │
│ │ [ Course ] [ Research ]    │ │
│ │ ▸ sessions (6)         [⋯] │ │
│ └────────────────────────────┘ │
│ ┌────────────────────────────┐ │
│ │ retention-review           │ │
│ │ addie · 9/12 · held by 91cc│ │
│ …                              │
```

One column, the row's stat line wraps to its own lines, secondary actions wrap
below primary, and `New session` moves into the `[⋯]` menu. The nested session
list loses its indent guides below 560px — the tree rules in `tree.css:38-70`
cost 32px per level and there are only ~300px to spend.

### Empty, loading, error — per region

The current page has one empty state per list and they contradict each other.
The proposal:

- **Everything empty** → the first-run page above. Not "No projects yet." in a
  box under a heading; the whole page changes.
- **Projects empty, sessions exist** (someone has been using the CLI without
  `/project new`) → a project section that says exactly that and offers
  creation, with the loose sessions below it doing their normal job.
- **Loading** → skeleton rows at the row's real height, not `loading projects…`.
  This page is polled and invalidated constantly (`useTreeRefresh`); text that
  appears and disappears where content will be is the thing that makes a live
  page feel unstable. Keep `Loading` for panes inside other views.
- **Error, projects** → `ErrorBox` with retry, in place of the list. Unchanged
  behaviour, and correct today.
- **Error, one project's live state** → nothing. A failed `current` read must
  not degrade the row; the row is still a working link. Render no marker rather
  than an error, and let the query's own retry handle it.
- **Drift** → when `HealthRepository.summaries()` reports unhealthy, the
  session regions get an inline banner *in the page*, not only the topbar badge
  (§3.9), carrying the existing rebuild action.
- **The tree/list fallback in `SessionTree`** (a drifted `/api/tree` answering
  empty while `/api/sessions` has rows) is genuinely good and must survive the
  restructure verbatim, including its comment.

## 5. How it stays clean

The page has to degrade along two axes independently: projects, which grow
slowly, and sessions, which grow fast.

**Ranking.** Projects sort by last activity, descending — a project with a run
in flight sorts first regardless. Sessions *within* a project keep fork lineage
(that structure is the product) but the roots sort newest-first. Loose sessions
sort newest-first, flat, and lineage among them is shown as a `forked @` chip
rather than as nesting, because a pile of orphans is not a forest.

**5 projects.** Everything renders. Sessions collapsed except the most recent
project's, which is expanded on load. Search present but visually quiet.

**50 projects.** Group by recency with sticky sub-headings — `Active now`,
`Today`, `This week`, `Older` — computed client-side from the same timestamp
the row shows. No pagination: 50 rows at ~64px is 3200px, which is a scroll,
not a problem. Search becomes the primary way in and gets keyboard focus on
`/`. Search is client-side substring over project name plus, when a project is
expanded, its sessions' `first_message` — the data is already in the query
cache and a server-side search endpoint for 50 rows would be a request nobody
needs.

**500 projects.** Two different walls, and only one of them is the browser's.

- *Rendering:* virtualize the project list with `useVirtualizer`, following
  `research/DocumentList.tsx` — which already established the pattern here and
  documents why it was worth trying. Rows are fixed-height, which is what makes
  this cheap; the disclosure's expanded content is the one variable-height
  thing, and it is measured rather than estimated.
- *The server:* `list_projects` (`app.py:375`) calls `service.project_state()`
  once per project inside its loop, so listing 500 projects folds 500
  aggregates on every request — and this page invalidates that query on project
  mutations and refetches on focus. This is the actual 500-project wall and no
  amount of frontend work moves it. It wants the same treatment `/api/sessions`
  got: a projection kept current by a subscription, with the fold left in place
  as the definition. Out of scope here, flagged as the blocker.
- Sessions at that scale are already handled: they are never listed globally
  except for the loose ones, and those virtualize the same way.

*What would falsify all of this:* if the realistic ceiling is 20 projects and
200 sessions forever — plausible for a single-operator local tool — then
grouping is worth building and virtualization is not. Virtualization is the
part to defer until a real database gets slow.

## 6. Visual direction

Work entirely inside `styles/tokens.css`. The console's look — dark, dense,
monospace-forward, one accent — is right and is not up for renegotiation here.
Three specific moves:

**Spend the accent on actions, not on identifiers.** `--accent` (`#e2a457`)
currently colours `.node-id`, a hex string, on every row of the page — so the
eye is drawn to the least useful field, dozens of times. Move it to the primary
action (`.btn-accent` already uses it) and to the `chip-held` marker
(`--accent`/`--accent-dim`, which is the correct use: "someone has this"). Ids
go to `--fg-faint` in `--mono` at `--t-xs`, where they read as metadata.

**Let the event-kind colours do their existing job.** The token file's own
comment says event kinds carry the only other colour in the UI. That extends
here without adding anything: `--k-file` (`#5ec98a`) for a healthy/free
project, reusing the `.chip-ok` treatment already in `tree.css:151`;
`--k-failure` (`#f4736b`) for failed turns, via the existing `.chip-fail`;
`--k-session` (`#a78bfa`) for fork lineage, via `.chip-fork`. A running turn or
run uses `--k-tool` (`#e2a457`, the same amber) — which is honest, since a run
*is* tool activity, and it means live-ness reads as the same colour the
timeline uses for it.

**Type and rhythm.** Project name at `--t-lg` (15.5px) in `--sans`; section
headings at `--t-sm` uppercase in `--fg-dim`, not at `--t-2xl` — the current
`<h1>Sessions</h1>` at 23px is the largest text in the console and it labels a
list. Stat lines at `--t-xs` in `--mono`, matching `.node-stats`. Rows keep
`--bg-panel` on `--line` at `--radius`, hovering to `--bg-panel-2`, exactly as
`.node` does now.

### Tokens that are genuinely missing

These are gaps, not preferences — each one is currently a hardcoded literal in
a stylesheet that claims a second literal hex would be a second palette:

| Token | Why | What it replaces today |
|---|---|---|
| `--line-strong` | hover and focus borders | `#34404e` in `.node:hover` (`tree.css:76`) |
| `--tint-session`, `--tint-fail`, `--tint-held`, `--tint-ok` | chip backgrounds and their borders | eight literals across `.chip-fork/-fail/-held/-ok/-warn` (`tree.css:118-162`) and the same values again in `.error-box` (`states.css:22`) |
| `--shadow-1` | the one elevation this UI has | `0 6px 20px rgba(0,0,0,.5)` in `.toast`, and needed again for a `[⋯]` menu |
| `--space-1` … `--space-6` | every gap and pad | literal px everywhere; the proposed row has four nested levels of padding and would otherwise add a dozen more |

And two classes that need rules rather than tokens, because they have none at
all (§3.5): `.view-head-actions` and `.node-actions`. Whatever else is done,
those two should be written.

No new dependencies. No new design system. `Button`, `Chip`, `EmptyState`,
`ErrorBox`, `Loading` and `Disclosure` in `common/primitives.tsx` cover every
control in the wireframes except the `[⋯]` menu, which is a `Disclosure` with
different chrome.

## 7. What this does not change, and what I cannot decide

### Not changing

- **The layering.** Rows read through the existing ports in
  `application/ports/repositories.ts`; no component gains an HTTP import.
- **The routes.** All four keep their shapes. `treeHref()` stays `#/` — only
  the page's *name* changes, and `{ name: 'tree' }` should be renamed to
  `{ name: 'home' }` for honesty, which is a rename and nothing more.
- **The confirmation wording.** `confirmTakeOver` and `confirmDelete` say
  exactly the right things about what survives a take-over and a delete. The
  container changes; the sentences do not.
- **`SessionTree`'s two-source fallback**, and its comment.
- **The course, research and session views.** Nothing here reaches into them.
- **Autonomy, approvals, run controls.** They belong to the course page. This
  page reports that a run exists; it does not steer one.

### The one backend change this asks for

`summary_view` gains `project_id` (`presenters.py:229`), and `SessionSummary`
(`application/summaries.py:26`) gains the field the fold already sees. Without
it §3.2 cannot be fixed at all — grouping sessions under projects has no key.
Pre-release, no stored shape changes: it is a projection column and
`/rebuild` already exists to derive it.

### Open questions for the owner

1. **Is a run's liveness worth N+1 requests?** The row marker in §4 needs
   per-project run and worker state. `/api/projects` could carry a small
   `activity` object per row instead, which is one request but pushes work into
   a listing that is already O(projects) folds. Or the SSE stream could carry a
   project-scoped frame. I would pick extending `/api/projects` and fixing its
   fold problem at the same time, but that is a bigger piece of work than a
   landing page and I do not want to smuggle it in.
2. **Default workflow: hybrid, or none?** §4 argues for hybrid; you know what
   projects actually get created.
3. **Do bare, project-less sessions deserve to keep existing?** Every feature
   built since projects landed is project-scoped. If the answer is "they are
   for quick prompt tests", the current design is right and `New session`
   stays. If the answer is "nobody uses them", the fourth region of the page
   and one of its three actions both disappear, which is a much cleaner page.
4. **Is this ever served to more than one person?** Everything above assumes
   not. If it is, "who holds this project" stops being informational and
   becomes social, and the take-over button needs a name attached to it.
5. **Should the CLI be visible here?** Both front ends share one database and
   the CLI is genuinely faster for a first prompt. The current empty state says
   so; the proposal keeps that on the first-run page only. It may deserve to be
   permanent.

## 8. What was decided

Appended 2026-08-09, after the fact, by the agent that implemented this
document — across #57 (the layout), #58 (folding a project's sessions away)
and #59 (removing the fourth region). Everything above is left exactly as it
was written, including the parts implementation proved wrong; the point of
keeping it is the reasoning, and a document quietly edited to agree with
what shipped is worth nothing to the next person. This section is the only
place the two are reconciled.

### The open questions in §7, answered

1. **Liveness is worth the requests, for rows that exist.** The marker is
   built, off `ResearchRepository.current` and `WorkerRepository.on` as
   proposed, but only for rows the virtualizer has actually drawn — a
   project scrolled past is not polled — and it refreshes off the log frames
   the page already invalidates on rather than a timer of its own. A failed
   read renders no marker rather than degrading the row. The `activity`
   object on `/api/projects` is still the right fix and is still not done.
2. **The default workflow is the first preset, not `no workflow`.** As §4
   argued. `list_workflows` already orders them deliberately, so "first" is
   a decision the server had made and the browser was throwing away.
   Choosing no workflow at all stays possible, and now states its cost where
   it is chosen.
3. **Bare sessions do not deserve to keep existing — the owner's call, taken
   later.** So the fourth region and the third action are both gone, which
   §7 predicted would be "a much cleaner page" and was right about. The rule
   itself is `SessionStarted.project_id` becoming required (#65), which is
   what made removing the region honest rather than merely tidier.
4. **One person.** No name is attached to a take-over; "held by 3f2a…" stays
   informational.
5. **The CLI is on the first-run page only**, as proposed — and it survived
   answering question 3. Only the claim that you can start *without* a
   project went; the sentence about both front ends sharing one database did
   not.

### Where this document was wrong

**"Pre-release, no stored shape changes: it is a projection column"** (§7)
is true of the event log and false of the database. `SessionSummaryRow`
gaining `project_id` did change a stored shape: `CREATE TABLE IF NOT EXISTS`
does nothing to a table that already exists, so the column never appeared,
every read against it failed, and `/api/sessions` and `/api/tree` answered
500 — on the only database anybody had, while a fresh one was fine and the
whole suite passed. `/rebuild` does not help, because it re-derives rows and
not columns. `apply_schema` in `read_models.py` now reconciles added
columns, and a test drops the column and reopens so it fails if that is
removed. The general form is the more useful thing: a read-model change
verified only against a fresh database is unverified.

**"Rows are fixed-height, which is what makes this cheap"** (§5) stopped
being true the moment a row carried a disclosure. Rows are measured, and
measurement needs two things §5 does not mention: a stable `getItemKey`,
because measurements cached against an array index follow the wrong row as
soon as the list shifts, and a `scrollMargin`, because the list does not
start at the top of its scroll container. Without the first there was a
122px hole in the list at three projects.

**A live project sorting first, regardless of timestamp** (§5) was not
built. Doing it means knowing whether every project is live, including the
ones nobody has scrolled to, which is exactly the per-project request §7's
first question warns about. Projects rank by last activity; the marker
appears wherever the project sorts. Worth revisiting when `/api/projects`
carries activity itself.

### What superseded it

**A project's sessions are folded away by default, and the row shows one.**
§5's "sessions collapsed except the most recent project's, which is expanded
on load" was tried and was wrong in the direction this whole document
argues: sessions accumulate far faster than projects, so one project's
history pushed every other project off the screen. The row names the session
holding the project, or the newest if none does, and the fold opens the full
forest only when there is more than one to see.

**The fourth region is gone entirely**, so §5's ranking rule for loose
sessions and §4's fourth region describe a page that no longer exists. The
session-creating method on the repository went with them.

Two things outside this document's scope moved to make room for it: the
bundle budget (`app-` 55 → 57 for the page's own weight, and `total` 232 →
512 at the owner's instruction), and the route rename §7 asked for — the
tree route is now the home route, and the breadcrumb reads `projects`.
