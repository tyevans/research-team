# The holding session, as it stands today

A map, not a design. Written as input to the spec for
`console-reimagining-roadmap.md` §2, which reworks the holding session into a
background concern. Nothing here proposes a change; everything here is what a
change would have to survive.

Load-bearing comments are quoted rather than paraphrased, because this
repository keeps its reasoning in comments and the reasoning is the part that
matters.

Read on 2026-08-27 against the `extraction-on-the-graph` branch in the
`remove-workflow-system` worktree.

---

## 1. Backend -- what "holding" is

### The aggregate (`research_team/domain/project.py`)

The module docstring states the model:

> "Sequential by construction. One session holds the project at a time,
> inherits the filesystem as the last one left it, and hands the tip back when
> it ends. That is the same shape as a fork -- inherit at a point, diverge from
> there -- which is why this aggregate stores a lineage pointer rather than
> files of its own."

`ProjectState` (`project.py:99-118`) carries three load-bearing fields:

- `active_session_id: UUID | None` -- "The session currently holding the
  project, if any." (`:113-114`)
- `tip_session_id: UUID | None` -- "Whose stream the filesystem folds from.
  None means the project is empty." (`:115-116`)
- `tip_at_event: int` -- "How far into that stream to fold." (`:117-118`)

**The refusal of a second join** is `decide`, `project.py:160-170`:

```python
case JoinProject(session_id=session_id), ProjectState(active_session_id=None):
    return [ProjectSessionJoined(..., inherited_at=state.tip_at_event)]
case JoinProject(), ProjectState(active_session_id=holder):
    # Named, not just refused: the next thing anyone asks is "which one".
    raise CommandRejectedError(f"project is held by session {holder}")
```

`DeleteProject` is refused the same way (`:155-156`), with its own reasoning at
`:151-154`:

> "Held means a session is still driving it. Releasing first is the caller's
> job, and it is a separate decision -- releasing advances the tip, which is a
> write to that session's project state, not something deletion should do
> behind the caller's back."

**`AdvanceTip` has two legal arms** (`project.py:172-196`), and this is the
part a rework must not flatten:

> "Two ways to be allowed to move the tip, and the second one is what stops
> work from detaching. The holder may move it: that is a release. And the
> session the tip *already names* may move it further along its own stream
> while nobody else holds the project: that is a catch-up, and it is the only
> route by which work done after a release rejoins the project it was done in.
> [...] What is refused is a session claiming a stream that is not the
> project's, and a tip that moves backwards: backwards is not a catch-up, it is
> a rewrite of which work counts, and there is no caller that means it."

```python
holds = state.active_session_id == session_id
catching_up = (state.active_session_id is None
               and state.tip_session_id == session_id
               and at > state.tip_at_event)
```

**`evolve`** (`:214-235`): `ProjectSessionJoined` appends to
`member_session_ids` and sets `active_session_id`; `ProjectTipAdvanced` sets
`active_session_id=None` and moves the tip. So a null holder is the *normal
resting state* of every project between sessions, not an error state.

### The application layer (`research_team/application/session_service.py`)

- `project_state(project_id)` (`:316-323`) -- "A read for front ends. 'Held by
  another session' is the single fact that decides what a user can do with a
  project next, and a UI that cannot see it can only offer an action and let it
  fail."

- `start_in_project(project_id, purpose)` (`:460-531`) -- the only way to make a
  session. The comment where `create_session` was deleted (`:452-459`) is worth
  keeping in view: a parameterised `create_session` "would sit beside
  `start_in_project` doing the same job less completely -- minting a session
  that names a project without the project having agreed to it, so no
  `JoinProject`, no holder, no inherited filesystem."

  Ordering matters (`:485-490`): "The tip is caught up *before* joining, and
  that ordering is the whole of it: `JoinProject` stamps `inherited_at` from
  the tip, and the fork copies to the same point, so a catch-up that ran
  afterwards would leave both of them naming a point that is not where anything
  was copied from."

- `_catch_up_tip(project)` (`:532-573`) -- the Tollers incident is recorded
  here: an auto-research run "started a session, stopped, released the project
  in its `after` hook, and the person kept working in the session the run had
  left them in. Four `/course` artifacts written afterwards were unreachable
  from the project the moment they were written, and the session that came next
  forked three events short of the first of them." It early-returns at `:567`:
  `if state.active_session_id is not None or state.tip_session_id is None:
  return`.

- `release_project(session_id)` (`:626-645`) -- "A no-op whenever there is
  nothing to release: a session with no `project_id`, or one whose project is
  no longer (or never was) actively held by it. That second case is ordinary,
  not exceptional [...] so this stays quiet rather than raising `AdvanceTip`'s
  'you do not hold this' rejection. That is what lets every session-switch path
  call this unconditionally, and keeps the rejection from ever escaping a
  caller's exit/cleanup path."

- `project_files(project_id)` (`:334-370`) -- **the single resolution of "which
  stream are this project's files on"**, and the most important docstring for
  §4 below:

> "A session holding the project has work in it that the tip does not yet know
> about -- the tip only advances on release -- so the holder is the newer
> answer and is asked first.
>
> With nobody holding it, the tip *session* is the truth and the tip *offset*
> is not. `at_event` is where that session was when it was released, and
> releasing neither closes the session nor stops it accepting turns, so
> anything written afterwards sits past the offset on the very stream this is
> folding. Reading to the offset is what made a project answer with an empty
> file list while four artifacts were sitting in the stream it was pointing at.
> The offset earns its keep only once something else has forked from it, and by
> then the tip names that fork rather than this session. [...]
>
> Resolved once, here, because every surface that shows a project's files needs
> the same answer -- and two of them computing it separately is two answers
> that will eventually disagree about which session was newer."

Note the asymmetry: `project_files` reads the tip session at **HEAD**
(`:369-370`, no `state_at`), while `topic_documents_view` reports the tip
**offset** to the client. They disagree deliberately; see trap (c) in §5.

### Callers of the lifecycle verbs

| Caller | Verb | File |
|---|---|---|
| `POST /api/projects/{id}/join` | `start_in_project` + `attach_project` | `interfaces/web/app.py:4188-4249` |
| `POST /api/sessions/{id}/release` | `release_project` + conditional `detach_project` | `app.py:~4155-4186` |
| `DELETE /api/projects/{id}?release_holder=` | `release_project` then `delete_project` | `app.py:1127-1179` |
| REPL `/project use` | `start_in_project` | `interfaces/cli/repl.py:302` |
| REPL every session switch | `release_project` via `_switch_to` | `repl.py:385-400` |
| `TopicSeeder.seed` | `start_in_project` ... `finally: release_project` | `application/topic_seeding.py:135-142` |
| `TopicDispatcher` (dispatch/revise/etc.) | same shape | `application/topic_dispatch.py:547-556` |

`repl.py:385-400` records why every switch releases:

> "Without it, a session that held a project keeps 'holding' it (per
> `Project.state.active_session_id`) even after nobody is driving it anymore:
> `release_project` was previously only called at REPL exit, so switching
> sessions leaked the project it held with no command able to get it back."

`topic_dispatch.py:508-516` explains an ordering constraint a rework must
preserve:

> "The topic is resolved *before* the project is joined. A refusal that had
> already taken the project would hold it for the duration of a turn that was
> never going to run -- the mirror image of the failure the `finally` below
> prevents, and worse here than for seeding because dispatches queue behind
> each other and the whole queue stalls with it."

`interfaces/web/dispatch.py:16-21` is the clearest statement that holding is
not a lock:

> "The constraint being respected is `Project.decide`'s refusal of a second
> `JoinProject`, and that refusal is not a lock protecting a race -- it is the
> filesystem model. The project stores a lineage pointer, and two concurrent
> holders would mean two divergent tips and no answer to 'what are this
> project's files'. One at a time is therefore not a limitation to be relaxed
> later; it is the property the queue exists to preserve."

### The wire

`project_detail_view` (`interfaces/web/presenters.py:314-341`) emits
`{id, name, active_session_id, tip_at_event}` -- "Identity and holder, and
nothing else." `project_view` is an alias of it (`:344-355`), and the alias's
docstring is the ask's counter-argument on the list view:

> "The holder is part of the row because it decides what the row can offer. A
> list that cannot see it has only one button to show -- join -- and no way to
> know that pressing it will fail, or that ending the holding session is what
> the user actually wants."

Routes:

- `GET /api/projects` (`app.py:1071-1084`) -- one `project_state` fold **per
  row**.
- `GET /api/projects/{id}` (`app.py:1219-1240`) -- "Separate from the listing
  rather than 'the row you already fetched', because the console reaches a
  project page by URL as often as by a click."
- `GET /api/sessions/{id}` (`app.py:5305-5320`) -- computes `holds_project` by
  comparing. `session_view` (`presenters.py:207-223`): "`holds_project` and
  `knowledge_attached` are process facts, not log facts [...] They are reported
  on the session because they are what the *user* needs to know before typing:
  whether this session still owns the project's filesystem."
- SSE `project_change` (`presenters.py:500-540`) carries no state: "The
  lifecycle events (`ProjectSessionJoined`, `ProjectTipAdvanced`,
  `ProjectDeleted`) move the holding-session link and the project list, so a
  frame per event class would be several frame types where the client wants one
  invalidation."

**When nothing holds the project, `active_session_id` is simply `null`** on
every one of those. There is no separate "the project is free" fact and no
server-side notion of "the head session" other than `tip_session_id`, which is
**not exposed on the wire at all** -- only `tip_at_event` is.

---

## 2. Frontend -- every reader of the holder

`activeSessionId` enters at `infrastructure/http/mappers.ts:293` from
`active_session_id` (`dto.ts:248-253`, `maybe(z.string())`). The domain type is
`domain/project/project.ts:11-16`, with `isHeld` at `:29`. Its docstring
restates the list-view argument (`:3-10`).

| Consumer | File:line | What it does | Identity or existence? |
|---|---|---|---|
| `useProject` | `presentation/project/use-project.ts:32-34` | exposes `holdingSessionId` | passthrough |
| `ProjectView` | `project/ProjectView.tsx:373, 388` | `sessionId = watching ?? holdingSessionId` -- feeds `useSessionScreen`, `href`, the Holding-session tab, the Workspace tab | **identity** |
| `visibleMaterialTabs` | `ProjectView.tsx:290-297` via `has = { hasSession: sessionId !== null }` (`:474`) | shows/hides the Workspace tab | **existence only** |
| `AutonomyLock` -> `LockForProject` | `shell/AutonomyLock.tsx:53-56` | `<Lock sessionId={holdingSessionId} />`; null gives a read-only panel | **identity** (the one the roadmap flags) |
| `ProjectListRow` primary buttons | `tree/ProjectList.tsx:330-346` | `Resume <shortId>` navigates to `sessionHref(activeSessionId!)`; otherwise `Open` (join) | **identity** |
| `confirmCopy` | `ProjectList.tsx:172-186` | take-over and delete confirmations name the holder's short id | **identity** (cosmetic) |
| `remove.mutationFn` | `ProjectList.tsx:75` | `projects.delete(id, isHeld(project))` -- the `release_holder` flag | **existence only** |
| `ProjectCard` | `entity/project/ProjectCard.tsx:132-140` | renders `held by 3f2a...` via `EntityRef`, else the word `free` | **identity** |
| `SessionRow` / `SessionForest` | `ProjectList.tsx:443, 448`; `tree/SessionRow.tsx:19-29, 54-65` | a `held` chip on the matching row | **existence + which row** |
| `currentSession` | `domain/project/landing.ts:161-173` | picks which session a collapsed row previews | **identity, with a fallback** |

`currentSession` is the one place the fallback is already written down
(`landing.ts:151-160`):

> "'Where was I' resolves to a project and then to a single session, and which
> one that is deserves an answer rather than whichever happens to sort first:
> the session *holding* the project, because that is the one still open and the
> one `Resume` goes to, and the newest otherwise. A project whose holder is
> missing from the summary list falls back to the newest rather than showing
> nothing -- a row with no session reads as a project nothing has run in, which
> would be a lie."

**`AutonomyLock` names the React constraint a rework has to respect**
(`AutonomyLock.tsx:37-39`): "Two components rather than one with a conditional
hook, which React does not allow: only the project route can resolve a holding
session, and that resolution is a query." And `:46-52`:

> "The project page's holder is where a write from this lock is recorded.
> `useProject` is already mounted by `ProjectView` on this route, so this is a
> second reader of one query rather than a second request. Off the project
> route there is no holder to find and the panel renders read-only, saying so
> -- see `NO_SESSION`, which is the honest answer rather than a disabled lock."

`useProject`'s own docstring records the last time this went wrong
(`use-project.ts:9-22`):

> "Read from `/api/projects/{id}` rather than from the course, which is where
> the project page used to get all three of these. The course carries them
> because it happened to have them; a project that runs no workflow answers
> 409, and every surface resolved off `holdingSessionId` -- the transcript, the
> composer, the Workspace tab -- went dark rather than 404ing, which is a
> symptom nobody would trace back to a course request."

The refresh hook (`use-project.ts:55-81`) subscribes to *every* project SSE
frame and invalidates only `queryKeys.project(projectId)`. It deliberately does
**not** subscribe to log frames: "a turn on the holding session writes files,
and none of the three fields this hook exposes is a file." That is a live
constraint on §4 -- if the project page grows a file tree fed by this query,
that sentence stops being true.

---

## 3. The session facet and its panels

`presentation/session/panels.tsx` exports: `timelineMeta`, `workspaceMeta`,
`conversationMeta`, `TimelinePanel`, `TimelineFeed`, `WorkspacePanel`,
`ConversationPanel`, `ComposerPanel`, plus a private `MissingHere`.

The module docstring (`panels.tsx:20-35`) is the contract:

> "**Content-only, and that is the whole design constraint.** Two arrangements
> mount these: `SessionView`'s three-pane `Split` on `#/s/<id>`, where each of
> them is a `Pane` body, and the project page's HOLDER column and MATERIAL
> `workspace` tab, where none of them is inside a `Pane` at all. So a panel
> that rendered its own `Pane` would be usable by exactly one of its two
> callers, and a panel that rendered its own heading would draw a second one
> inside a pane header that already has one."

| Panel | `#/s/<id>` (`SessionView.tsx`) | Project page (`ProjectView.tsx`) |
|---|---|---|
| `ScrubBar` | above the `Split`, `:83-95` | inside the `session` TabPanel, `:657-670` |
| `TimelinePanel` | `Pane id="timeline"`, `:127-134` | `<section aria-label="Event log">`, `:696-707` |
| `TimelineFeed` | `Pane`'s `footer` slot, `:131` | last child of that section, `:706` |
| `WorkspacePanel` | `Pane id="workspace"` | the **`file` TabPanel**, `:738-741` |
| `ConversationPanel` | third `Pane` | `<section aria-label="Conversation">`, `:709-721` |
| `ComposerPanel` | `Pane`'s `footer` | pinned last, outside both scrollers, `:723-727` |
| `Confirm` (end session) | `:104-119` | `:672-689` -- **duplicated verbatim in both** |

Both arrangements share `useSessionScreen`
(`session/use-session-screen.ts`). Its docstring (`:37-44`) states the
nullability contract:

> "**`sessionId` is nullable, and that is the load-bearing part of the
> signature.** The project page calls this at the top of a component that may
> have no holding session at all, and a hook called inside the `if` that
> discovers so is a conditional hook. So every effect below tolerates `null` by
> doing nothing, and the caller decides what to draw instead. The cost is that
> `state` on a null screen is whatever the shared store last held; no caller
> reads it, because both check the id first."

And `:46-56` on `href`, the seam that keeps the project page from navigating
away:

> "`SessionView` wrote `sessionHref` for every scrub and every file open, which
> is right on `#/s/` and was wrong the moment the project page mounted it:
> clicking an event in HOLDER rewrote the address to the standalone session
> route, i.e. navigated out of the project page, discarding QUEUE and MATERIAL,
> to look at the event you just clicked. That shipped in slice 0 and was
> invisible because HOLDER was a whole session view and leaving for another one
> looked like nothing."

**Reachable only through the holder, on the project page:** the transcript, the
composer, the scrub bar, the event log, the end-session confirm, **and the
whole Workspace tab**. Every one sits behind a `sessionId === null` guard at
`ProjectView.tsx:653` and `:730`.

`ProjectView.tsx:634-655` explains why the session panel alone carries
`keepMounted`:

> "`Tabs` unmounts an inactive panel, and for a list or a graph that is right
> -- it is what makes manual activation mean something. This panel is a live
> transcript with a composer in it, and it was a permanent column until this
> slice, so a half-typed message and a scrub position had never been at risk;
> unmounting discarded both on a trip to Artifacts and back. What it costs,
> plainly: the transcript goes on subscribing behind every other tab, and
> `hidden` is `display: none`, so everything in here measures zero while it is
> away."

`MATERIAL_TABS[0]` is `{ id: 'session', label: 'Holding session' }` (`:158`),
and `DEFAULT_MATERIAL` is `'catalog'` (`:302`) -- the roadmap's premise is
already half-measured there:

> "`project/session` took **118 entries -- the second most-entered view in the
> product -- at a 2.3s median with 55% bouncing under three seconds**. Most of
> those entries are not a choice; it is the default tab, so they are arrivals
> followed by departures. Against it, `project/catalog` took 82 entries at a
> 20.6s median and **14% bounce, the lowest of any view measured**."

The first tab's own comment (`:150-157`) explicitly declines to demote it:

> "dwell measures what readers were *handed*, not what they would pick, so it
> can say the holding session is a bad default without saying it is a bad first
> tab. Costing it one click is this change; demoting it down the strip would be
> a second change nothing here has measured."

---

## 4. Project files

**There is no project-scoped file API.** `service.project_files` has exactly one
HTTP caller -- `topic_documents_view` at `app.py:2406-2410`. Everything else
reads files through the session-keyed routes:

- `GET /api/sessions/{id}/files?path=&at=` (`app.py:5335-5342`)
- `GET /api/sessions/{id}/files/history?path=` (`:5344`)
- `GET /api/sessions/{id}/files/parsed` (`:5371`)
- `GET /api/sessions/{id}/at/{at}` (`:5326-5333`) for the tree itself, which
  comes back inside `session_view`'s `files` array (`presenters.py:249-256`)

So `WorkspacePanel` needs `(sessionId, ScrubPoint)` -- `sessionId` for
`FileView` (`panels.tsx:134`) and for the invalidation key
`queryKeys.file(sessionId, openPath, screen.state.scrub)` (`:122`); the file
list itself comes off `screen.files`, the folded session projection.

**The precedent for a project-scoped view already exists and is the model to
copy.** `topic_documents_view` (`presenters.py:960-1030`) resolves
`(session_id, at)` server-side and hands the pair to the client:

> "**The `session_id` is the reason this is not just a list of paths.** Every
> reader of a file in this API -- the raw route, the parsed route with its
> components, the attempt route that grades against it -- is keyed by
> `(session_id, path)`, and a dispatch writes on a session it creates and
> releases. Nothing on the research view knows which session that was. This
> resolves it once, so a viewer reuses those three routes unchanged instead of
> a fourth project-scoped copy of each growing beside them.
>
> `at` is the scrub point that goes with it, and the two must travel together.
> A project nobody is holding has its files at the *tip*, which is a position
> in a session that may have run on past it; reading that session at HEAD would
> show files the project does not have. `None` means HEAD and is correct only
> while a holder is live, because a holder's own uncommitted work is exactly
> what the tip does not yet know about -- the same two cases `project_files`
> resolves, reported rather than applied."

The resolution itself, `presenters.py:1011-1021`:

```python
if state.active_session_id is not None:
    session_id, at = state.active_session_id, None
elif state.tip_session_id is not None and state.tip_at_event >= 1:
    session_id, at = state.tip_session_id, state.tip_at_event
else:
    session_id, at = None, None
```

The frontend mirror is `domain/research/topic-document.ts:14-32` and its
consumer `presentation/research/TopicDocuments.tsx`, whose docstring says the
same thing from the other side (`:36-43`):

> "**It reuses the session-keyed readers rather than replacing them.** The
> listing route hands back the `(sessionId, at)` pair that the project's files
> currently fold out of, and everything below that point is `FileView`'s own
> machinery unchanged -- `useLesson` for the parse, `useAttempts` for the
> grading, `readFile` for the bytes. The alternative was a project-scoped copy
> of all three, which would have had to agree with the originals about
> scrubbing, component withholding and attempt keying, and would not have."

**Two facts a Workspace-as-project-tab design has to reconcile:**

1. `project_files` reads the tip session at **HEAD**
   (`session_service.py:369-370` -- no `state_at`, and the docstring at
   `:344-352` argues at length that reading *to the offset* is what produced
   the empty-file-list bug). `topic_documents_view` hands the client the
   **offset**. These are two different answers to "what are the project's
   files" living in one process, and the reasoning is written down in only one
   of the two places.
2. `tip_session_id` is not on the wire. A client cannot compute the fallback
   itself from `/api/projects/{id}` today: it has `active_session_id` and
   `tip_at_event` -- an offset into a stream it cannot name.

---

## 5. The traps

### (a) `hasSession` gates the Workspace tab, and its measurement was about emptiness, not about holding

`visibleMaterialTabs` (`ProjectView.tsx:262-297`):

> "**A tab whose panel can only say 'there is nothing here' is worse than no
> tab**, because a reader cannot tell it apart from one that might have
> something until they have spent the click. Measured over
> `~/.research-team/interactions.db` on 2026-08-23 (2,476 events): Workspace
> took 14 entries at a 0.7s median and **100% bounce** -- every single visit
> under three seconds. That is not readers finding a page thin; it is what
> arriving at an `EmptyState` and leaving looks like in aggregate.
>
> **One condition, and it survives on its own terms.** A project's files belong
> to the session holding it, so the tab is dead when nothing holds the project
> -- which is true of plenty of projects."

If the workspace becomes tip-backed, the *reason* for that 100% bounce
disappears and the condition should change with it. A rework that widens
`hasSession` without changing the data source produces a tab that is present
and still empty -- the exact defect the measurement condemned.

There is also a deep-link exemption at `:293-295` (`if (tab.id === openTab)
return true`) whose failure mode is documented as silent: "dropping the tab
leaves Radix with a selected value no trigger carries, so the strip shows
nothing chosen while a panel is open below it."

### (b) `AutonomyLock` degrades silently to read-only

`Lock sessionId={null}` renders the whole panel with `disabled` rows and one
line of prose (`AutonomyPanel.tsx:103`, `NO_SESSION`). It does not throw, does
not warn, and looks like a deliberate state. If the rework changes how the
holder is resolved and this reader gets `null` where it used to get an id,
**every autonomy control goes read-only and the only symptom is a sentence
nobody reads.** This is the `silent-defaults-hide-missing-wiring` shape the
roadmap warns about, already instantiated in the code.

### (c) A `null` holder is load-bearing in four places, in four different senses

- `Project.decide`: `active_session_id=None` is the *precondition* for
  `JoinProject` (`project.py:160`) and half the precondition for a tip catch-up
  (`:188`). Making holding "background" must not make it permanent -- a project
  that always has a holder can never be joined, and `_catch_up_tip` becomes a
  permanent no-op (`session_service.py:567`), which reinstates the Tollers
  detachment silently.
- `release_project` is a quiet no-op on a non-holder (`:626-645`). Every REPL
  switch and every dispatch `finally` depends on that. A rework that made
  release raise would push `AdvanceTip`'s rejection into cleanup paths.
- `DELETE /api/projects/{id}` refuses a held project unless
  `release_holder=true` (`app.py:1152-1163`), and the frontend passes
  `isHeld(project)` for that flag (`ProjectList.tsx:75`). If the console stops
  tracking heldness, that flag becomes a guess.
- `useSessionScreen` tolerates `null` by doing nothing in every effect, and its
  docstring says explicitly that `state` on a null screen is stale data no
  caller may read (`:41-44`). Any new caller that reads `screen.state` without
  checking the id first gets the *previous* session's data with no error.

### (d) The dispatch queue is serialised by the refusal, not by a mutex

`interfaces/web/dispatch.py:16-21`, quoted in §1. Anything that makes joining
always succeed, or that keeps a long-lived "console holder" session, either
breaks the FIFO queue or starves it -- every dispatch would refuse, or wait
forever behind a holder no person is driving.

### (e) The `/join` route attaches the graph process-wide

`app.py:4204-4213`:

> "attach here, accept that the most recent join wins process-wide, and say so
> plainly rather than build isolation nothing asked for. A second tab joining a
> different project will change the tools the first tab's turns run with; that
> is a known, accepted limitation of this design, not an oversight."

Any design that joins *implicitly* -- on opening a project page, say --
multiplies that: opening a project in a second tab would silently re-point the
attachment under a running turn in the first.

### (f) `GET /api/projects` folds one aggregate per row

`app.py:1071-1084` calls `service.project_state` in a loop. `landing.ts:108-119`
already defers a feature on exactly this cost:

> "Sorting a live project to the top means knowing whether every project is
> live, including the four hundred nobody has scrolled to, and that is a request
> per project on a listing that already folds one aggregate per row
> server-side."

Adding a per-project "head session" or file count to the listing pays that cost
again.

### (g) This surface's tab-click behaviour has already broken once, silently

`ProjectView.tsx:576-596`:

> "**It wrote `select(null)` and that had silently stopped working.** The
> argument was that `null` lands back on this tab through `DEFAULT_MATERIAL`,
> which was true while the default was `session`. The default moved to
> `catalog` on the interaction log's dwell figures (#286) and this arm was not
> moved with it, so clicking Holding session wrote `#/p/<id>`, which resolves
> to the catalog -- the tab bounced the reader to Curriculum. Nothing caught
> it: the jsdom suite asserts the strip and the panels, and the one file that
> clicks this tab is in the browser project, outside CI."

That is the coverage gap standing today: the tab-click behaviour of this exact
surface is asserted only in `*.browser.test.tsx`, which is not in CI.

### (h) `endSession` invalidates the listing, not the detail

`use-session-screen.ts:186-198` invalidates `queryKeys.projects()` (the
listing) but not `queryKeys.project(projectId)` -- the detail that `useProject`
and `AutonomyLock` read. Today the detail is refreshed by the SSE `project`
frame via `useProjectRefresh`. If the rework changes that subscription or the
query key, ending a session leaves a stale holder id on the page with no error.

### (i) `regionOf`'s `file` case already anticipates this work

`ProjectView.tsx:113-124`:

> "A file is **not**, and this is the one mapping slice 2 reverses. It read
> `holder` because a project file is a file in the holding session's workspace,
> which is true and is about where the bytes come from -- not about which
> question the reader is asking. The regions are named for questions, and 'what
> has this project produced' is the one a file answers: the workspace tree
> beside the artifacts is the live half of the same shelf."

The routing already treats a file as project-shaped; only the data source is
still session-shaped. `regionOf` is total over `Facet` on purpose (`:33-39`) --
"a facet added to `FACETS` should fail to compile here rather than silently
land in QUEUE" -- so a new facet is one of the few things in this area that
fails loudly.

### (j) Deleted projects 404 on reads as of 2026-08-27

`app.py:1181-1218` records that this was wrong for a long time and cost nothing
visible: "nothing could be *changed* through those routes, so nothing broke,
and a retired project simply kept answering questions about itself." Any new
project-scoped route must go through `_require_project`, or it inherits that
bug.

---

## Files that matter

Backend:

- `research_team/domain/project.py`
- `research_team/application/session_service.py`
- `research_team/application/topic_dispatch.py`
- `research_team/application/topic_seeding.py`
- `research_team/interfaces/web/app.py`
- `research_team/interfaces/web/presenters.py`
- `research_team/interfaces/web/dispatch.py`
- `research_team/interfaces/cli/repl.py`

Frontend:

- `frontend/src/presentation/project/use-project.ts`
- `frontend/src/presentation/project/ProjectView.tsx`
- `frontend/src/presentation/session/panels.tsx`
- `frontend/src/presentation/session/use-session-screen.ts`
- `frontend/src/presentation/session/SessionView.tsx`
- `frontend/src/presentation/shell/AutonomyLock.tsx`
- `frontend/src/presentation/tree/ProjectList.tsx`
- `frontend/src/presentation/entity/project/ProjectCard.tsx`
- `frontend/src/presentation/research/TopicDocuments.tsx`
- `frontend/src/domain/project/project.ts`
- `frontend/src/domain/project/landing.ts`
- `frontend/src/domain/research/topic-document.ts`
- `frontend/src/infrastructure/http/dto.ts`
- `frontend/src/infrastructure/http/mappers.ts`
