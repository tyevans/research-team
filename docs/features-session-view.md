# The session view — exhaustive feature index

Read-and-document survey of `#/s/<id>`, the console's oldest and densest page.
Written for a synthesising agent: every feature is a numbered entry with a
fixed field set, and the classification (**reachable** / **unreachable** /
**unbuilt**) is stated on every one.

Base commit: `5a5a7cf` (`Move what-is-running into the nav bar (#86)`).

Everything below was read from code. Where a comment and the code disagree, the
code wins and the disagreement is called out. Where I am unsure, the entry says
so.

> **Historical, 2026-08-27 (B147).** This is a survey taken at a named commit,
> and the workflow system it surveys has since been removed entirely: presets,
> stages, stage artifacts, the check library and every surface that drew them.
> Banner rather than rewrite, deliberately. The body's whole claim is "read out
> of the code at `5a5a7cf`", every entry is dated to that read, and editing
> entries out would leave a document asserting a provenance it no longer has --
> a survey that has been quietly corrected is less useful than one that says
> when it was taken. **What is invalid:** every entry about stage-gate review -- the `gate_context` payload, `stage_exit.py`, `advance_stage` and its autonomy floor, and the `ApprovalRequest.context` object those filled. §13.1 and the future-work items that build on it have no subject left.

---

## 0. Method, scope and how to read this

**Scope.** The session route and everything it renders, plus the shell chrome
that is present while it is on screen, plus the backend routes and SSE frames
those depend on. `WorkerDrawer` is included where it reuses session components,
because it is the clearest evidence of what the session view is *missing*.

**Classification.**

- **Built and reachable** — a user can get to it today with mouse or keyboard.
- **Built but unreachable** — code, data or a route exists; nothing on this page
  exposes it.
- **Designed but unbuilt** — the backend ships the data or the design doc names
  it; the frontend has no code for it.

**Field set per feature.** What it does · Where it lives · How a user reaches it
· What it depends on · State model.

**Counts.** 61 distinct features indexed (F1–F61): 47 built and reachable, 9
built but unreachable, 5 designed but unbuilt. 24 dead ends / rough edges
(D1–D24).

---

## 1. Route, entry and page-level machinery

### F1. The session route is a linkable state — id, scrub point and open file

- **What** `#/s/<id>`, `#/s/<id>/at/12`, `#/s/<id>/file/docs/a.md` and
  `#/s/<id>/at/12/file/docs/a.md` are all bookmarks. The scrub position and the
  open file live in the address bar and nowhere else, so any screen can be sent
  to somebody.
- **Where** `presentation/routing/routes.ts` (`parseRoute`, `sessionHref`),
  `app/App.tsx:107`.
- **Reached by** typing/pasting a URL; every internal control navigates by
  rewriting the hash.
- **Depends on** hash routing only (the backend serves one static file; a
  history route would 404 on reload — stated in `routes.ts`).
- **State** A malformed `at` (non-integer, `< 1`) silently degrades to HEAD. A
  truncated `/file` with no path degrades to no file. A path containing `/` is
  rejoined rather than split.
- **Class** Built and reachable.

### F2. Scrub and file navigation replace rather than push history

- **What** Dragging through forty events or clicking down a file list leaves one
  history entry, so Back returns to the page you arrived from.
- **Where** `SessionView.tsx:81-93` (`selectEvent`, `openFile`, both
  `{ replace: true }`).
- **Reached by** any timeline click, arrow key, or file row click.
- **Depends on** `navigate` in `presentation/routing/use-route.ts`.
- **State** Consequence: there is **no** in-page Back through scrub history.
- **Class** Built and reachable (deliberate).

### F3. Session store opens per session and resets wholesale

- **What** Switching sessions through the shared store resets every field —
  turn, approvals, activity, log, fresh highlights — so nothing of the previous
  session leaks in.
- **Where** `application/session/session-store.ts` (`open`, `close`,
  `initialState`); store is created once in `app/App.tsx:40` and owned by the
  shell because `Breadcrumbs` needs the same head.
- **Reached by** navigating between sessions.
- **Depends on** `GET /api/sessions/{id}`, `GET /api/sessions/{id}/events`,
  `GET /api/sessions/{id}/turns/current`, `GET /api/sessions/{id}/approvals`
  (all four in one `Promise.all`; the last two are advisory and swallow errors).
- **State** empty → loading → loaded / error. A failure of head-or-log fails the
  whole page (F4); a failure of running-or-approvals is silent.
- **Class** Built and reachable.

### F4. Whole-page error state with retry

- **What** If the head read or the log read fails, the entire view is replaced
  by "Session unavailable" plus the server's message and a Retry button.
- **Where** `SessionView.tsx:150-160`, `ErrorBox` in `common/primitives.tsx`.
- **Reached by** a failing `GET /api/sessions/{id}` or `/events`.
- **Depends on** `ApiError.message`, lifted from FastAPI's `detail` by
  `HttpClient.detailOf`.
- **State** failed only. Retry calls `store.reload()`.
- **Class** Built and reachable.

### F5. Live feed subscription, shared across the app

- **What** One `EventSource` for the whole console; the session view subscribes
  and filters by `sessionId`.
- **Where** `presentation/session/use-session-stream.ts`,
  `presentation/shell/StreamProvider.tsx`, `GET /api/stream` in
  `interfaces/web/app.py:1783`.
- **Reached by** automatic on mount.
- **Depends on** SSE. Frame families ride one connection
  (`application/ports/event-stream.ts`): `log`, `approvalRequested`,
  `approvalSettled`, `activity`, plus project-addressed `extraction` /
  `seeding` / `dispatch` / `topic` / `graph` / `corpus` / `project` which this
  page ignores.
- **State** `connecting` / `open` / `down`, surfaced by `ConnectionBadge`.
- **Class** Built and reachable.

### F6. Reconnect reconciliation, with two different guarantees

- **What** Log frames replay from `Last-Event-ID`; approval and activity frames
  carry no feed position, so on reconnect the page refetches `/approvals` and
  re-asks `/turns/current` before catching up activity.
- **Where** `session-store.ts` `handleReconnect`, `catchUpActivity`,
  `refreshRunning`; server side `_sse` in `app.py:1811`.
- **Reached by** automatic.
- **Depends on** `resumable` flag from the stream adapter. `resumable: false`
  (dropped before the first frame) forces a full `load()`.
- **State** Skipped entirely while this tab owns a `sending` turn.
- **Class** Built and reachable.

### F7. Arrival highlight ("fresh") on newly-appended events

- **What** Events that just arrived get a 1.5 s highlight class, swept on a
  timer so a flash never lingers.
- **Where** `session-store.ts` `markFresh` / `sweepFresh` (`FRESH_MS = 1500`),
  `SessionView.tsx:72-76` (1600 ms timer), `Timeline.tsx` `fresh` prop,
  `.ev.fresh` in `styles/timeline.css`.
- **Reached by** passive.
- **Depends on** log frames, or a turn's reported `from`/`to` range.
- **State** Only ever additive; cleared by the sweep.
- **Class** Built and reachable.

### F8. Unhandled-error and unhandled-rejection toasts

- **What** Any uncaught render error or rejected promise becomes a red toast
  rather than a silently-stalled pane.
- **Where** `main.tsx:36-41`, `application/notifications/toast-store.ts`,
  `presentation/shell/Toasts.tsx`.
- **Reached by** passive. Bad toasts live 7 s, others 3.8 s.
- **Class** Built and reachable.

---

## 2. The scrub bar (top strip)

`presentation/session/ScrubBar.tsx`, styled in `styles/panes.css`.

### F9. Live/history state indicator

- **What** Two visually distinct states, not two numbers: `● live · head` (green
  dot, `--k-file`) or `● time travel` (amber, `--accent`) with the whole bar
  gaining a gradient and an inset top rule.
- **Where** `ScrubBar.tsx:41-60`, `.scrub-bar.historical` in `panes.css:18`.
- **Depends on** `state.scrub`.
- **State** head / historical.
- **Class** Built and reachable.

### F10. Head summary line

- **What** At HEAD: `N events · N turns · N files · <model name> · N failed turns`
  (failed turns omitted when zero).
- **Where** `ScrubBar.tsx:93` (`describeHead`).
- **Depends on** `session_view` fields `event_count`, `turn_index`, `files`,
  `model_name`, `failed_turns`. `totalEvents` takes `max(declared, fetched)`
  because the two can disagree mid-turn.
- **Class** Built and reachable.

### F11. Historical detail line, including a fold-in-progress marker

- **What** Scrubbed: `viewing the workspace as of event 12 of 87 — tool result
  recorded: <summary, 90 chars>`, with `…folding` appended while the snapshot
  request is in flight.
- **Where** `ScrubBar.tsx:104` (`describeHistorical`), `entryAt` in
  `domain/session/log-entry.ts` (falls back to array offset for a partial log).
- **Depends on** the fetched log and `state.loadingSnapshot`.
- **Class** Built and reachable.

### F12. Project chips: identity, graph attachment, and stale hold

- **What** Three chips: `project 3f2a…`; `graph on`/`graph off` (green/amber);
  and `not held` when another session has taken the project over. The first chip
  dims at 55 % opacity in the stale case.
- **Where** `ScrubBar.tsx:119-145` (`ProjectChips`), `.scrub-project.stale-hold`
  in `panes.css`.
- **Reached by** passive; the explanations are **title-attribute-only** (hover /
  long-press). See D3.
- **Depends on** `holds_project` and `knowledge_attached`, which `app.py:1350`
  computes as *process* facts (not log facts) per request.
- **State** Absent entirely when the session has no `project_id`.
- **Class** Built and reachable.

### F13. "End session" — hand the files back to the project

- **What** Releases the project lease and advances the project's tip to this
  session's latest event. This is the **only** way work done here reaches the
  next session in the project.
- **Where** `ScrubBar.tsx:69-77`, `SessionView.tsx:126-148`,
  `POST /api/sessions/{id}/release` (`app.py:1076`),
  `SessionService.release_project`.
- **Reached by** a button, visible **only at HEAD** and only when
  `head.projectId && head.holdsProject`.
- **Depends on** a native `window.confirm()` (see D1), then a toast, a
  `queryKeys.projects()` invalidation, and a navigate to `#/`.
- **State** 409 if a turn is running ("cancel it first"). If the session has no
  project the client shows "This session is not in a project." **Misreports:** if
  the session names a project but is not the holder, the route still answers
  `released: true` while `release_project` no-ops — the toast claims the project
  is free when nothing happened (D8).
- **Class** Built and reachable.

### F14. "Fork here" from the scrub bar

- **What** Forks a new session at the currently-scrubbed event.
- **Where** `ScrubBar.tsx:79-82`, `SessionView.tsx:114-124`,
  `POST /api/sessions/{id}/forks`.
- **Reached by** a button, visible **only while scrubbed**.
- **State** On success: toast `Forked at event N.`, `queryKeys.tree()`
  invalidated, navigate to the new session. On failure: red toast, stay put.
- **Class** Built and reachable.

### F15. "Back to live"

- **What** Returns the whole view to HEAD.
- **Where** `ScrubBar.tsx:83-86`.
- **Reached by** the accent button (scrubbed only), **or** Escape anywhere on the
  page (F16), **or** clicking the HEAD marker in the timeline (F23), **or** the
  End key with the timeline focused (F22).
- **Note** It preserves the open file — `selectEvent` closes over `openPath`.
  This was a fixed bug: the listener used to close over the first render's file
  and drop it on Escape (`SessionView.tsx:95-102`).
- **Class** Built and reachable.

---

## 3. Panes and layout

`presentation/session/Pane.tsx`, `use-panes.ts`, `styles/panes.css`,
`styles/responsive.css`.

### F16. Global Escape → back to live

- **What** Escape anywhere returns to HEAD, unless focus is in a textarea (so
  the composer is safe) and unless the timeline already handled it.
- **Where** `SessionView.tsx:103-112`; the timeline calls `stopPropagation` so
  one press never folds twice (`Timeline.tsx:88`).
- **Depends on** being currently historical.
- **Class** Built and reachable. Undiscoverable — see D5.

### F17. Three collapsible panes with sticky, per-view preference

- **What** Timeline / Workspace / Conversation, each collapsible to a 34 px
  labelled rail (title rotated vertically). The choice is stored in preferences
  under group `session` and survives reloads. Collapsing refuses to hide the last
  open pane. A collapsed pane's body is removed from the layout entirely, so a
  collapsed log is not still streaming rows into a box nobody can see.
- **Where** `use-panes.ts`, `Pane.tsx`, `.pane.collapsed` in `panes.css`.
- **Reached by** a `◂`/`▸` ghost button in each pane head.
- **Depends on** `PreferenceStore.collapsedPanes('session')`.
- **State** Attempting to collapse the third pane produces the toast
  "At least one pane has to stay open."
- **Class** Built and reachable.

### F18. Width redistribution on collapse

- **What** The width a collapsed pane gives up goes to the open ones — a fixed
  34 px track rather than a min-width. Above 1181 px the hook owns
  `grid-template-columns`; below it the hook returns `undefined` and hands the
  tracks back to the media queries, because an inline style would outrank them.
- **Where** `use-panes.ts:23,67-75`, `responsive.css`.
- **Reached by** collapsing; automatic on resize (a `matchMedia` listener).
- **Class** Built and reachable. Genuinely subtle and worth preserving.

### F19. Three responsive layouts

- **What** ≥1181 px: three columns. 821–1180 px: two columns with Conversation
  spanning full width on its own row at `max-height: 46vh`, and `:has()` rules
  taking over collapse. ≤820 px: a single scrolling column, panes stacked,
  collapsed panes become horizontal strips rather than vertical rails, `.files`
  capped at 200 px, `.pane-body` at 60 vh.
- **Where** `styles/responsive.css`.
- **Class** Built and reachable.

### F20. Pane meta lines

- **What** Each pane head carries a right-aligned meta string: `87 events`;
  `head` or `@ event 12`; `24 messages · 6 compacted · @ 12`.
- **Where** `SessionView.tsx:187,205,249-259`.
- **Class** Built and reachable.

---

## 4. The event timeline (left pane)

`presentation/session/Timeline.tsx`, `styles/timeline.css`.

### F21. The log as an ARIA grid, one row per event

- **What** `role="grid"` with `aria-rowcount`/`aria-colcount=2`, deliberately not
  a listbox, so each row can hold a focusable secondary action. Each row shows:
  index · a coloured kind rail · humanised event type · `· turn N` · optional
  path · summary (truncated to 160) · clock time. A `title` attribute carries
  the full type, the full timestamp and the untruncated summary.
- **Where** `Timeline.tsx:106-240`; `humaniseEventType` and `classifyEventType`
  in `domain/session/event-kind.ts` (substring rules, so an event type added
  later still gets a colour rather than vanishing into a default); server
  summaries from `presenters.py:event_summary`.
- **Depends on** `GET /api/sessions/{id}/events` and live `log` frames.
- **State** Empty log → `EmptyState` "The log is empty." with a next action
  ("Send a turn below — every message, tool call and file write lands here in
  order.").
- **Class** Built and reachable.

### F22. Keyboard scrubbing (roving tabindex, vi keys)

- **What** With a row focused: `↓`/`j` next, `↑`/`k` previous, `Home` first,
  `End` last, `Escape` HEAD. HEAD sits one past the last event so it is reachable
  by the same keys. Exactly one row is in the tab order at a time.
- **Where** `Timeline.tsx:50-93`, `tabIndex={selected ? 0 : -1}`.
- **State** All of it is a no-op on an empty log.
- **Class** Built and reachable. **Entirely undocumented on screen except for a
  one-line composer hint** (`↑/↓ in the log to scrub`) that never mentions
  `j`/`k`, `Home`, `End` or the fork column. See D6.

### F23. HEAD marker row

- **What** A row past the last event reading `● HEAD — live` or `○ HEAD — click
  to return to live`.
- **Where** `Timeline.tsx:134-148`.
- **Reached by** click or keyboard.
- **Class** Built and reachable.

### F24. Per-row "fork here" — the hidden second column

- **What** Every row carries a `fork here` button that creates a new session
  replaying the log up to and including that event.
- **Where** `Timeline.tsx:221-234`, `.ev-fork` in `timeline.css:136-153`.
- **Reached by** hovering the row, or selecting it (the button is
  `visibility: hidden` and revealed on `:hover`, `.selected` and
  `:focus-within`), then clicking. **Keyboard route:** focus a row, press `→` to
  move the invisible column cursor, then `Enter`/`Space`.
- **Depends on** `POST /api/sessions/{id}/forks`.
- **State** The `column` state has **no visual representation whatsoever** — no
  class, no `aria-colindex`, no focus ring. `.ev-fork` is permanently
  `tabIndex={-1}`, so `.ev-fork:focus-visible` (which the stylesheet defines) can
  never fire, and the comment "revealed on focus-within so keyboard users can see
  what they reached" describes the *row* being focused, not the button. A
  keyboard user has no way to know whether `Enter` will scrub or fork. See D7.
- **Class** Built and reachable, but the keyboard path is effectively secret.

### F25. Kind colouring, error rows, cancellation rows and "future" dimming

- **What** Eight kind buckets (`compaction`, `failure`, `session`, `tool`,
  `file`, `message`, `turn`, `other`) plus `cancelled`. A deliberate
  cancellation arrives as `TurnFailed` carrying `cancelled: true` and is drawn as
  an outcome, never as a failure. While scrubbed, events *after* the scrub point
  get a `future` class.
- **Where** `Timeline.tsx:181-188`, `kindOf`/`isCancellation` in `log-entry.ts`,
  `presenters.py:event_row` (`cancelled` sent separately from `type` precisely
  so the client can tell them apart without reading prose).
- **Class** Built and reachable.

### F26. Discarded-content disclosure on a failed turn

- **What** Under a `TurnFailed` row, a `<details>` labelled `discarded — not
  recorded` holds everything that streamed in before the failure. Each entry is
  tagged `in progress — not yet recorded`. Ephemeral: gone on reload, which the
  summary says.
- **Where** `Timeline.tsx:247-257` (`Discarded`), populated in
  `session-store.ts` `handleFrame` on a `TurnFailed` frame and by
  `catchUpActivity` (which pins the server's index-less `discarded` buffer to
  `lastFailedTurnIndex(log)`).
- **Depends on** `GET /api/sessions/{id}/turns/current/activity`.
- **State** Only on failure; success drops provisional content because the real
  events supersede it. Uses a raw `<details>`, unlike every other fold on the
  page (D14).
- **Class** Built and reachable. Very easy to miss.

### F27. Auto-scroll to the selected row

- **What** The selected row scrolls into view (`block: 'nearest'`), including
  when the log arrives *after* first render — the common mount case, where HEAD
  is the last row.
- **Where** `Timeline.tsx:44-46`, keyed on `[scrub, log.length]`.
- **Class** Built and reachable.

### F28. Live activity feed under the timeline

- **What** While a turn is in flight, provisional bubbles show what the model is
  producing — each tagged `in progress — not yet recorded`. A tool-calling
  message renders as `→ name, name`, matching the timeline row it is about to
  become.
- **Where** `presentation/session/ActivityFeed.tsx`, `domain/activity/activity.ts`
  (`activityBody`), server `interfaces/web/activity.py`.
- **Reached by** passive, rendered as the timeline pane's footer.
- **Depends on** `activity` SSE frames plus the catch-up route. Gated on
  `TurnState.isBusy` as well as on having entries, so a bubble cannot outlive the
  turn.
- **State** Each frame carries the *full* prose so far, not a delta, so a frame
  replaces rather than appends. An activity frame arriving while the store thinks
  nothing is running triggers a `refreshRunning()` rather than being trusted —
  activity and log frames are pumped by two independent tasks and a straggler
  would otherwise resurrect an ended turn.
- **Class** Built and reachable.

---

## 5. The workspace pane (middle)

### F29. File list at the selected point

- **What** A listbox of every file in the workspace as of the scrub point, with
  path, revision count (`r3`) and size (`1.2 KB`).
- **Where** `presentation/session/FileList.tsx`, `presenters.py:session_view`
  (`_revision_counts` slices `events[:at]` for a scrubbed view, so revision
  counts are point-correct).
- **Reached by** click, or keyboard: the list container is `tabIndex={0}` with
  `aria-activedescendant`; `↑`/`↓` move, `Enter` opens.
- **State** Empty → "No files." with wording that differs by point ("The
  workspace was empty at event 12." vs "The agent has not written anything yet.").
- **Class** Built and reachable.

### F30. Enter-to-re-read the already-open file

- **What** Pressing `Enter` on the file that is already selected re-reads it —
  the escape hatch when a file looks stale.
- **Where** `FileList.tsx:62`, `SessionView.tsx:223-229` invalidating
  `queryKeys.file(sessionId, openPath, scrub)`.
- **Reached by** keyboard **only**. There is no button, no context menu, and no
  hint anywhere on the page. See D9 — it is also incomplete: it does not
  invalidate `queryKeys.lesson`, so a rendered markdown lesson stays stale.
- **Class** Built and reachable, but effectively secret.

### F31. File viewer — raw contents at the scrub point

- **What** The open file's bytes, folded to the selected event server-side, in a
  line-numbered code block.
- **Where** `presentation/session/FileView.tsx` (`Contents`),
  `common/content.tsx` (`CodeBlock`), `GET /api/sessions/{id}/files?path=&at=`.
- **Depends on** react-query with `placeholderData: previous`, so a previous
  point's contents stay up (with a `.stale` class) while a newer fold is in
  flight rather than flashing empty.
- **State** empty file → `(empty file)`; 404 → an `EmptyState` worded by point
  ("did not exist at event 12" vs "is not in the workspace at HEAD") and
  **deliberately not retried** (a 404 here is information, not a failure); other
  errors → `ErrorBox` with Retry; loading → `loading file…`.
- **Class** Built and reachable.

### F32. Markdown rendered/source toggle

- **What** For `.md`/`.markdown`/`.mdown`/`.mkd`, a two-tab group switching
  between sanitised rendered markdown and raw source.
- **Where** `FileView.tsx:72-81`, `FilePath.isMarkdown`, `Markdown` in
  `common/content.tsx` (the single `dangerouslySetInnerHTML` in the app, fed
  through DOMPurify with a closed allow-list, and memoised on the source so a
  streaming conversation does not re-parse every message per frame).
- **State** Defaults to `rendered`. **Not** keyed to the path, unlike `tab`, so
  it persists across file changes — inconsistent (D10).
- **Class** Built and reachable.

### F33. Author/learner audience toggle for interactive documents

- **What** For a markdown file that contains lesson components, a toggle between
  the author view (everything, including answer keys and authoring warnings) and
  a learner preview (answers and rationales withheld server-side).
- **Where** `FileView.tsx:83-107`, `application/lesson/use-lesson.ts`,
  `GET /api/sessions/{id}/files/parsed?view=`.
- **Reached by** appears **only** when the file is markdown, in rendered mode,
  *and* the parse reports components. The explanations are title-only.
- **Depends on** the parsed route; `view` is a FastAPI `Literal`, so a typo is a
  422 rather than a silent fallback to the answer key.
- **State** Defaults to `author` ("this console's reader is the person building
  the course"). Switching refetches rather than filters, because which fields
  exist is the server's decision.
- **Class** Built and reachable.

### F34. Interactive lesson widgets in the file viewer

- **What** Four widget types render live inside the file viewer and can be
  operated: flashcards (with `←`/`→`/`Enter`/`Space` keyboard control), MCQ,
  cloze (Enter to submit), and a persistent checklist. Attempts post to the
  server, which grades — the browser was never given the key. An "answers
  withheld" badge appears on components whose key was stripped.
- **Where** `presentation/lesson/*`, `application/lesson/use-attempts.ts`,
  `POST /api/sessions/{id}/attempts`,
  `POST /api/sessions/{id}/progress/checklist`, `GET .../progress`.
- **Reached by** open a markdown artifact containing components, rendered mode.
- **State** Per-file, keyed and reset on path change (deliberately — answers to
  one document are not answers to the next). Unknown component type → labelled
  code block; a component with parse errors → its source plus a field-level error
  panel; neither takes the document down. Prior progress folds back in, with
  local edits winning. A parse failure silently falls back to plain markdown.
- **Class** Built and reachable. Almost certainly not something anyone expects to
  find on the *session* page.

### F35. File history tab, with diffs

- **What** A second tab per file listing every recorded change to that path,
  oldest first, expanded by default ("a revision list nobody opens is a list of
  timestamps"), each with a unified diff.
- **Where** `presentation/session/FileHistory.tsx`, `DiffView` in
  `common/content.tsx`, `GET /api/sessions/{id}/files/history?path=`,
  `presenters.py:file_history`.
- **Reached by** the `history` tab in the file header.
- **State** loading → `loading history…`; error → `ErrorBox` with Retry; empty →
  "No recorded revisions. Nothing in the log touched this path."
- **Class** Built and reachable.

### F36. History is the whole log, not a fold to the scrub point

- **What** Deliberate: a revision list that stopped where the reader is standing
  would hide the very edits they scrubbed back to understand.
- **Where** `FileHistory.tsx:16-20` docstring; the route takes no `at`.
- **State** Consequence: while scrubbed to event 5 you can read a diff from event
  90. There is nothing on screen saying so (D11).
- **Class** Built and reachable.

### F37. Recorded edit intent vs reconstructed diff

- **What** A `FileEdited` event carries the agent's own `old_string`/`new_string`
  — the intent as recorded — and that is diffed directly. A `FileWritten` or
  `FileDeleted` records no intent, so the previous revision stands in for
  "before" and the result is annotated `created — full contents:` or `removed`.
  A `replace_all` edit gets a chip. The type distinction is what stops a
  reconstruction being presented as something the log actually said.
- **Where** `domain/workspace/workspace-file.ts` (`diffSubject`),
  `presenters.py:file_history`.
- **Class** Built and reachable. A genuinely good distinction that the UI barely
  explains.

### F38. Diff elision with labelled gaps

- **What** Unchanged runs are collapsed and labelled ("17 unchanged lines") so a
  gap reads as context rather than as a rendering failure. `(no textual change)`
  when a revision changed nothing.
- **Where** `infrastructure/rendering/diff.ts`, `DiffView`.
- **Class** Built and reachable.

### F39. Per-revision collapse

- **What** Each revision's diff can be folded away.
- **Where** `FileHistory.tsx:85-93`.
- **Reached by** clicking the revision header — a bare `<div onClick>`. Not
  focusable, no `role`, no keyboard route (D12).
- **Class** Built and reachable by mouse only.

### F40. "Not in the workspace here" guard

- **What** If the open file does not exist at the selected point, the viewer says
  so by name and index rather than showing another point's bytes.
- **Where** `SessionView.tsx:235-236, 289-294` (`MissingHere`), plus the 404
  branch in `FileView.tsx:165-176` — two implementations of nearly the same
  message (D13).
- **Class** Built and reachable.

### F41. Tab state is stamped with its file

- **What** Opening a different file starts on its contents rather than inheriting
  the last file's `history` tab, and this is true on the render that changes
  files rather than one paint later.
- **Where** `FileView.tsx:38-47`.
- **Class** Built and reachable.

---

## 6. The conversation pane (right)

### F42. Transcript with machinery folded into tool runs

- **What** Consecutive "machinery" messages (tool results, and wordless
  assistant turns that only dispatched calls) collapse into one closed
  disclosure reading `6 tool calls · Read ×3, Bash, Grep`, in first-run order. A
  message carrying prose is never folded, however many calls it also made.
- **Where** `domain/conversation/transcript.ts` (`segmentTranscript`,
  `tallyTools`), `domain/conversation/message.ts` (`isToolActivity`),
  `presentation/session/Segments.tsx`.
- **State** A run containing an errored message gets an `error` chip on the
  closed fold. A run with no calls at all (possible on a replay starting
  mid-turn) counts messages instead.
- **Class** Built and reachable.

### F43. Role-aware rendering

- **What** Assistant prose renders as sanitised markdown. Tool results render
  monospace and literal, truncated at 4000 chars. User messages stay literal
  ("what was typed is what was sent"). An errored assistant turn stays literal
  too, since a raw failure is easier to read than a half-parsed one.
  `(no content)` for an empty message with no calls. Unrecognised content shapes
  render as JSON rather than `[object Object]`.
- **Where** `Segments.tsx:137-154`, `contentText`/`safeJson` in `message.ts`.
- **Class** Built and reachable.

### F44. Tool-call argument summaries with full JSON on hover

- **What** Each call shows `name  path=src/a.ts  +3`, preferring the argument
  that identifies *what* was acted on (`path`, `file_path`, `filename`,
  `pattern`, `command`, `query`), falling back to the first key. The full
  pretty-printed JSON is in a `title` attribute.
- **Where** `Segments.tsx:117-128`, `summariseArgs`/`safeJson` in `message.ts`.
- **Reached by** hover only for the full args (D3).
- **Class** Built and reachable.

### F45. A message with both prose and calls gets its own nested fold

- **What** So the prose is what you see first. Inside an already-folded run the
  extra fold is suppressed.
- **Where** `Segments.tsx:156-177`.
- **Class** Built and reachable.

### F46. Compaction panel

- **What** When context has been compacted, a bordered section explains that
  nothing was deleted — the log still holds every message, and so does this pane
  — and that what changed is what the *model* is shown. It contains: a headline
  (`context compacted — the model sees a summary of the first N messages`), the
  summary itself in a fold that is **open by default**, a second fold holding the
  superseded messages (rendered through the same segmenter), and a
  `context boundary · everything below is sent verbatim` rule.
- **Where** `presentation/session/Compaction.tsx`,
  `domain/session/session.ts` (`compactedThrough`, clamped to the messages
  actually held so a stale or oversized count from a scrubbed fold can never
  swallow the transcript).
- **Depends on** `compacted_through` and `compaction_summary` on the session
  view.
- **State** No summary text → `no summary text was returned with this session.`
- **Class** Built and reachable. One of the best-explained things on the page and
  one of the least likely to be seen.

### F47. Sticky-to-bottom scrolling that respects a reader who scrolled up

- **What** The pane follows new content only if it was already within 80 px of
  the bottom.
- **Where** `Conversation.tsx:40-48`.
- **Class** Built and reachable.

### F48. Open/closed fold state survives refetches

- **What** All disclosure state lives in one `Set<string>` keyed by absolute
  message index, so a tool run stays open while the conversation refetches
  around it (which it does on every turn end). `Disclosure` is a real
  `<button>` + `aria-controls` region rather than `<details>` precisely so the
  state can be owned from outside.
- **Where** `Conversation.tsx:36`, `segmentTranscript(messages, offset)`,
  `common/primitives.tsx`.
- **State** Reset on session change (component remount). **Not** in the URL, so a
  shared link cannot reproduce which folds were open.
- **Class** Built and reachable.

### F49. Conversation empty and error states

- **What** `No conversation yet.` with detail worded by point ("Nothing had been
  said by event 12." vs "Send the first turn below."). `Unavailable` + the
  snapshot error if the fold failed. The empty wording is a prop, overridden by
  `WorkerDrawer`, which has no composer to point at.
- **Where** `Conversation.tsx:62-70`.
- **Class** Built and reachable.

---

## 7. Approvals

### F50. Pending approval cards

- **What** Each gated call renders a card: `wants to run <toolName>`, an optional
  description, the full arguments as pretty JSON, and Approve / Reject.
- **Where** `presentation/session/Approvals.tsx`, rendered above the composer as
  part of the conversation pane's footer.
- **Depends on** `GET /api/sessions/{id}/approvals` (catch-up for a tab that
  arrived mid-turn), `approvalRequested` / `approvalSettled` SSE frames,
  `POST /api/sessions/{id}/approvals/{approval_id}`. The approvals feed queue is
  **seeded on subscribe**, so a browser connecting a moment after a call was
  gated still sees it.
- **State** A card is taken down by `ApprovalSettled`, **not** by the click
  handler — which is what makes answering in the REPL, in another tab, or here
  all work. Both buttons disable while `deciding === approval.id`. A 404 (someone
  else answered first) is swallowed silently. A cancelled turn frees its parked
  approvals via a `finally`, which also emits `ApprovalSettled`.
- **Class** Built and reachable.

### F51. Approvals are answerable from three places

- **What** The session view, the REPL, and the agent-dock's `WorkerDrawer`
  (F60) all render the same component against their own store.
- **Where** `Approvals.tsx` docstring, `presentation/course/WorkerDrawer.tsx`.
- **Class** Built and reachable.

---

## 8. The composer

`presentation/session/Composer.tsx`, `styles/composer.css`.

### F52. Send a turn

- **What** A two-row textarea; submit by button or `Ctrl+Enter` / `Cmd+Enter`.
  Placeholder states the shortcut. Blank/whitespace input is refused silently.
- **Where** `Composer.tsx:35-58`, `POST /api/sessions/{id}/turns`.
- **State** Disabled whenever a turn is busy. The button label tracks state:
  `Send turn` / `Running…` (ours) / `Turn running` (foreign). After a turn ends,
  the whole session is reloaded rather than trusting mid-flight frames, because
  a turn is atomic.
- **Class** Built and reachable.

### F53. Turn-in-flight reporting with a live elapsed clock

- **What** A spinner plus `turn in flight · 47s — events appear when it
  completes`, ticking every second. The wording is deliberate: a turn saves
  atomically, so **nothing** reaches the event stream while it runs and there is
  no per-tool progress that could honestly be shown.
- **Where** `Composer.tsx:143-163`, `useTick` (display only; issues no requests).
- **Class** Built and reachable.

### F54. Watching a turn started elsewhere

- **What** A turn started in the REPL, another tab, an auto-research round or a
  stage runner is detected and reported: `turn 3 · started 2m ago, elsewhere ·
  events appear when it completes`. When it ends, a note says whether it
  finished, failed or was cancelled, with a range chip on success.
- **Where** `Composer.tsx:152` (`watchedLabel`), `session-store.ts`
  `applyRunning` / `refreshRunning` / `foreignTurnEnded`,
  `GET /api/sessions/{id}/turns/current`.
- **Depends on** `TurnEndLedger`, which discards a stale `running: true` answer
  by two independent checks (a sequence counter and the server-clock
  `lastEndedAt`) — because the server clears its tracker and emits the event as
  two separate steps, and a `TurnFailed` reuses its turn index so index
  comparison was wrong.
- **Class** Built and reachable. Substantial hidden machinery.

### F55. Cancel a turn, including one started elsewhere

- **What** A `Cancel turn` button appears while busy. `Cancelling…` while the
  request is out. Distinguishes a settled cancel (`turn cancelled — its events
  were discarded`) from an unsettled one (`cancel delivered — the turn is still
  unwinding`), and clears the latter when the closing frame arrives.
- **Where** `Composer.tsx:62-71`, `session-store.ts` `cancel` /
  `awaitingUnwind`, `POST /api/sessions/{id}/turns/cancel`.
- **State** A cancelled turn returns 499, which is treated as an outcome — no
  red, no toast. "nothing was running" when the cancel found nothing. Cancel
  failure → a warn note with a `re-check` button plus a red toast.
- **Class** Built and reachable.

### F56. The turn note — outcome, range chip, and re-check

- **What** After a turn, a toned note sits beside the composer: `turn complete`
  with a clickable chip `turn 3 · events 14–21` that **scrubs to where the turn
  began**; or a warning with a `re-check` button that re-asks `/turns/current`;
  or a calm cancellation note. Tone is set explicitly, never derived from text —
  a cancellation arrives as a `TurnFailed` and would otherwise read as a failure.
- **Where** `Composer.tsx:85-141`, `domain/session/turn.ts` (`turnNote`),
  `session-store.ts`.
- **Reached by** the chip and the `re-check` button are inline text buttons,
  visually indistinct from the note prose.
- **State** Dismissed the moment you start typing the next turn.
- **Class** Built and reachable. The range chip is a real time-travel entry point
  that nothing labels as one.

### F57. 409 handling — "a turn is already running", with a re-check

- **What** A conflict (another writer got there first, or a turn is already
  running) surfaces the server's own sentence and offers `re-check`.
- **Where** `session-store.ts:358`, `app.py:1531-1560`. Optimistic-lock conflicts
  also land here as "another turn was recorded on this session first; reload and
  retry" — mostly mitigated by #69's save-retry, which re-applies a turn's
  already-produced events onto a freshly loaded aggregate rather than re-running
  the model, and refuses to rebase over anything except `AutonomyChanged`.
- **Class** Built and reachable.

### F58. Historical-mode composer warning

- **What** While scrubbed, the hint reads `viewing history — a turn appends to
  HEAD; fork to branch from here` in a warn tone.
- **Where** `Composer.tsx:135`.
- **State** The composer is **not** disabled while scrubbed — sending from a
  historical view is allowed and appends at HEAD (D15).
- **Class** Built and reachable.

---

## 9. Shell chrome present on this page

### F59. Breadcrumbs with fork lineage and project links

- **What** `projects / 3f2a… ← forked from 91bd… @42 / course · research`. The
  fork origin is a link, and it is in the trail rather than in a panel because
  "what did this come from and where did it diverge" is a navigation question.
  The project's course and research pages are linked, which is the only way back
  from a transcript to the project.
- **Where** `presentation/shell/Breadcrumbs.tsx`, `forkOrigin` in `session.ts`.
- **Note** The project is named by its id, never by name — deliberately, to avoid
  a request on every session load.
- **Class** Built and reachable.

### F60. Agent dock ("N running") in the nav bar

- **What** A popover listing everything running anywhere, with a kind dot reusing
  the timeline's event-kind colours, project, elapsed, the agent's latest
  statement and last tool call (fields dropped progressively at 560 px and
  420 px, never wrapping). Opening a row opens a `WorkerDrawer` — a
  focus-trapping drawer showing that session's *pending approvals*, an autonomy
  "stop being asked" control, its live conversation and its activity feed, plus
  an "Open the session" link. Extraction rows are flat text, since they have no
  transcript.
- **Where** `presentation/agents/AgentWidget.tsx`,
  `presentation/course/WorkerDrawer.tsx`, `presentation/course/AutonomyAllowAll.tsx`,
  `GET /api/workers`.
- **Reached by** the topbar toggle; hidden entirely when nothing is running and
  it has never been opened. Escape closes and returns focus (not a trap — the
  page behind stays usable); a pointerdown anywhere else dismisses. Open/closed
  persists under preference group `agents` with an inverted key name (`popover`
  means *open*). Focus lands in the panel on open.
- **Class** Built and reachable — **and it is the single biggest source of
  session-view feature envy**: it shows approvals *and* an autonomy control the
  session view itself does not have (D19). It is also the one place in the
  codebase whose comment names `Pane.tsx`'s glyph labels as a known bug.

### F61. Connection and drift badges

- **What** `connecting` / `live` / `reconnecting`, with `role="status"` and
  `aria-live="polite"`. And a drift badge that appears only when the session-list
  projection is untrustworthy, with a `rebuild` button when the projection is
  still following (a stopped projection needs a restart, which a browser cannot
  do). Re-checked on every reconnect.
- **Where** `presentation/shell/ConnectionBadge.tsx`, `GET /api/health`,
  `POST /api/summaries/rebuild`.
- **Class** Built and reachable.

---

## 10. Dead ends and rough edges

### D1. `window.confirm` for ending a session

`SessionView.tsx:127`. The only native modal in the console; unstyled, not
theme-aware, not testable, and out of step with `common/Confirm.tsx` which
already exists.

### D2. Pane toggles announce as "◂"/"▸" — **known bug**

`Pane.tsx:44`. The button's accessible name is a glyph. `aria-expanded` and
`title` are set, but the name a screen reader reads is a punctuation character.
`AgentWidget.tsx:130-133` explicitly cites this as a bug it declines to spread.

### D3. Nine explanations exist only as `title` attributes

Not reachable by keyboard, not readable on touch, and not announced consistently:
the project chip's holder explanation and the graph-on/off explanation
(`ScrubBar.tsx:126-138`), the pane toggle (`Pane.tsx:41`), each timeline row's
full type/time/summary (`Timeline.tsx:195`), each tool call's full JSON args
(`Segments.tsx:120`), the author/learner tab explanations (`FileView.tsx:92-99`),
the file path (`FileList.tsx:88`), the revision timestamp
(`FileHistory.tsx:90`), and the fork button (`Timeline.tsx:227`).

### D4. `.files { outline: none }` in `workspace.css:9`

The focusable element is the listbox *inside* `.files`, so the rule targets the
wrong node — but it shows the author believed the container was the tab stop.
The listbox itself has no styled focus ring; it falls back to the UA default,
unlike the timeline which has an explicit one.

### D5. Escape-to-live is invisible

F16 is the most useful shortcut on the page and appears nowhere in the UI. The
composer hint mentions `↑/↓` and `Ctrl+Enter`, never Escape.

### D6. The keyboard model is undocumented and inconsistent

Timeline: `↑↓jk`, `Home`, `End`, `Escape`, `←→`, `Enter`/`Space`. File list:
`↑↓` and `Enter` only — no `jk`, no `Home`/`End`, no `Escape`. Flashcards:
`←→`, `Enter`/`Space`. Cloze: `Enter`. Nothing lists any of it. There is no
help overlay, no `?` shortcut, no legend.

### D7. The timeline's fork column has no visual state

The `column` state in `Timeline.tsx:37` is invisible. Pressing `→` changes what
`Enter` does — scrub becomes fork, an irreversible action creating a new session
— with zero feedback. `aria-colcount={2}` is declared but no cell ever carries
`aria-colindex`, and `.ev-fork:focus-visible` is dead CSS because the button is
permanently `tabIndex={-1}`. Also: `Enter` at column 0 calls `onSelect(scrub)`,
which re-navigates to where you already are — a no-op that costs a render.

### D8. "End session" can misreport success

`POST /release` answers `released: true` whenever the session names a project,
but `SessionService.release_project` silently no-ops when this session is not
the holder. The UI then toasts `Session ended. 3f2a… is free.` — a lie in the
stale-hold case. (The `not held` chip is the only contradicting signal, and the
button is hidden in that case, so this is reachable mainly via a stale page
whose `holds_project` has since flipped.) `BACKLOG.md` around line 243 records
the underlying ambiguity: a session that correctly is not the holder and one
that *should* be but lost `active_session_id` look identical.

### D9. Enter-to-re-read does not refresh the rendered view

`SessionView.tsx:225` invalidates `queryKeys.file` only. `queryKeys.lesson` and
`queryKeys.lessonProgress` are **never invalidated anywhere in the codebase**, so
re-reading a rendered markdown lesson refetches bytes nobody is showing.

### D10. The open file goes stale after a turn, with no refresh

`queryKeys.file` is invalidated in exactly one place (D9's keyboard-only path).
`queryKeys.fileHistory` and `queryKeys.lesson` are invalidated nowhere. React
Query is configured `refetchOnWindowFocus: false`, `staleTime: 5000` — and
`FileView` stays mounted across a turn, so nothing triggers a refetch. **A file
the agent just rewrote continues to show its old contents until you press Enter
on it or reload.** The file *list* (sizes, revision counts) does update, because
the store reloads the whole session on turn end. So the list can say `r4` while
the viewer shows revision 3. This is the most consequential defect I found.

*(Related but separate: `FileView`'s `mode` state persists across files while
`tab` is keyed to the path — see F32.)*

### D11. File history silently ignores the scrub point

F36 is a deliberate and defensible choice with nothing on screen to explain it.
While scrubbed to event 5, the history tab happily shows a diff from event 90.
`BACKLOG.md` line 822 lists `/files/history` as "ignores the scrub point" in its
own inventory.

### D12. Revision headers are not keyboard-operable

`FileHistory.tsx:85` is a `<div onClick>` with no `role`, `tabIndex` or key
handler. Every other fold on the page uses `Disclosure`, which is a real button.

### D13. Two different "file not here" messages

`MissingHere` (`SessionView.tsx:289`) fires when the file list is non-empty and
lacks the path; `Contents`' 404 branch (`FileView.tsx:165`) fires otherwise. Same
situation, two wordings, two code paths.

### D14. `Discarded` uses a raw `<details>`

`Timeline.tsx:248`, unlike everything else, which uses `Disclosure`. Its state is
owned by the DOM and is lost on any re-render that unmounts it.

### D15. Sending a turn while scrubbed is allowed, and only warned about

The composer stays enabled in history mode (`Composer.tsx:47` disables on `busy`
only). The turn appends at HEAD, and the reader — still pinned at event 12 —
sees nothing happen in the visible panes. The warning is a line of grey text.

### D16. Pane collapse and conversation fold state are not in the URL

The route claims to make "the exact thing I am looking at" linkable, and it does
for the scrub point and the file. It does not for pane layout (a preference,
sticky per-browser) or which tool runs / compaction folds are open (component
state, lost on session change).

### D17. Failure of `/turns/current` or `/approvals` at load is silent

`session-store.ts:252-253` catches both to `null`/`[]`. A session with a parked
approval and a broken approvals subsystem loads looking idle.

### D18. `catchUpActivity` swallows every error

`session-store.ts:223` — best-effort by design, but a tab that reloads mid-turn
and fails this shows an empty activity feed indistinguishable from a quiet turn.

### D19. There is no autonomy control on the session view

`AutonomyAllowAll` is rendered in `WorkerDrawer` (reachable from the agent dock
and the course page) and the full per-tool panel is on the course page. The
session view — the surface where you are *actually* answering approvals
repeatedly — has neither. Answering the same approval five times here has no
"stop asking me" affordance at all. `AutonomyAllowAll`'s own docstring says it
exists so nobody has to navigate to a settings surface; the session view is the
one place that lesson did not reach.

### D20. Approval cards drop `context` and `allowed_decisions`

`dto.ts:208` parses only `id`, `session_id`, `tool_name`, `description`, `args`.
The server sends `allowed_decisions` (which may include `edit` and `respond`) and,
for a stage gate, a whole `context` object with findings, severities, citations,
the findings-report path and the stage's artifact paths. See §13.1.

### D21. `system_prompt` is fetched, mapped, and rendered nowhere

`sessionDto.system_prompt` → `SessionProjection.systemPrompt`. Grep finds no
renderer. The REPL's `/state` shows it. Dead data on this page.

### D22. Stale comment: `responsive.css:23` refers to `app.js`

No such file exists; the tracks are driven by `use-panes.ts`.

### D23. The densest page in the console has essentially no presentation tests

`presentation/session/` contains exactly one test file, `use-panes.test.tsx`.
There is no test for `SessionView`, `Timeline`, `ScrubBar`, `Composer`,
`Conversation`, `Segments`, `Compaction`, `Approvals`, `FileList`, `FileView`,
`FileHistory` or `ActivityFeed`. By contrast `presentation/research/` has ten and
`presentation/course/` five. `session-store.test.ts` covers the state machine
well; nothing covers what is drawn from it. **Any redesign here is a redesign
without a net.**

### D24. `compaction:summary:closed` is an inverted key

`Compaction.tsx:35-36` stores "closed" in a set whose every other member means
"open", and reads it as `open={!open.has(...)}`. Works; will confuse the next
person to touch it.

---

## 11. Time travel and forking — what is actually possible

This is the page's most powerful capability and the most under-surfaced.

**Scrubbing** is a pure server-side fold: `state_at` replays the first `at`
events onto a fresh aggregate and writes nothing (`session_service.py:409`).
Selecting event *N* re-projects, in one response, **all** of:

- the workspace file list, with per-file **revision counts recomputed for that
  prefix** (`_revision_counts(events[:at])`);
- the whole conversation as of that moment;
- the compaction boundary and summary as they stood then;
- `turn_index`, `failed_turns`, `model_name`.

The open file's contents are folded separately and independently
(`GET /files?path=&at=`), and the lesson parse and the attempt-grading route
*also* take `at` — so a learner answering a question is graded against the
version of the lesson that existed at that point, and an author diffing two
revisions of a question gets both to parse. `_read_file` is deliberately shared
by the raw, parsed and attempt routes so the three cannot drift on what "not
found at this point" means. That is a genuinely unusual capability and nothing
in the UI surfaces it.

Out-of-range folds are a 400 from `state_at` and surface as a dedicated
`ErrorBox` in the workspace pane, `Could not fold to event N`, with Retry.

**Ways to reach a historical point** (five, four of them undiscoverable):
1. Click a timeline row.
2. Arrow/`jk`/`Home`/`End` in the timeline.
3. Edit the URL (`/at/12`).
4. Click the turn-range chip in the composer note (`turn 3 · events 14–21`) —
   jumps to where that turn *began*.
5. Browser Back/Forward across a session boundary (within a session, scrubs
   replace rather than push, so Back does not step through them).

**Ways back to live** (four): the accent button, Escape, the HEAD marker row,
`End` in the timeline.

**Forking.** `POST /forks` replays the first `at` events onto a brand-new
stream — **the whole log, not just files** — then records `RecordForkSource`.
So a fork inherits the conversation, the files, the model and the project id.
Nothing is destroyed; the source session is untouched. (A *project join* uses a
different, narrower replay, `_fork_files_from`, which copies only file events —
that path is not reachable from this page.)

- Two entry points: the per-row `fork here` button (hover- or selection-revealed;
  keyboard only through the invisible column, D7), and the scrub bar's `Fork
  here` (scrubbed only).
- On success: a toast, a tree invalidation, and an **immediate navigation away**
  to the new session. There is no confirmation and no undo, and the transition is
  the only feedback.
- The forked session's lineage appears in the new session's breadcrumb as
  `← forked from 3f2a… @42`, which is the only place forks are visible from a
  session. The full tree is on the landing page.
- **Not surfaced:** the forked session inherits `project_id` but does *not* hold
  the project, so it lands showing the `not held` chip and no `End session`
  button. Nothing warns about this before or after the fork.
- The REPL distinguishes `/fork` (fork and stay) from `/rewind` (fork and
  switch); the web only implements the latter shape.

**File history** is the third time-travel surface and the one that ignores the
scrub point entirely (F36/D11). Combined with `diffSubject`'s
recorded-intent-vs-reconstructed distinction (F37), it is the only place the log
is shown as a *causal* record rather than a positional one.

---

## 12. Built but unreachable

1. **`system_prompt`** — fetched and mapped, rendered nowhere (D21).
2. **`allowed_decisions` on an approval** — sent by the server, dropped by the
   DTO. The UI hardcodes Approve/Reject for every gate.
3. **Approval `edit` and `respond` decisions** — `ApprovalDecision`
   (`application/ports.py:294`), the HTTP `Decision` body (with `edited_args`
   and `message`) and the terminal port all support four decision types. The web
   client can express two, and sends only `{type}`.
4. **Approval `context`** — a whole findings report crosses to the browser and is
   discarded at the schema boundary (D20).
5. **`AutonomyAllowAll` on this page** — the component exists and is wired to
   an instance-wide policy; the session view does not render it (D19).
6. **`SessionSummary.firstMessage`, `startedAt`** — exposed on `/api/sessions`
   and used by the tree; the session page never shows when a session started.
7. **`project_change` frames carrying `decision`** — `presenters.py:616` states
   plainly "Nothing on the page renders it yet."
8. **`Confirm.tsx`** — a styled confirmation primitive exists; `endSession` uses
   `window.confirm` anyway (D1).
9. **`fileContentDto`'s `at` echo** — the server echoes the point it folded to;
   the client discards it and trusts its own scrub state.

## 13. Designed but unbuilt

1. **A UI for stage-gate review.** `gate_context` (`stage_exit.py:462`) ships
   `stage`, `findings_artifact`, `artifact_paths`, `blocked`,
   `artifacts_reviewed`, `links_reviewed`, `unimplemented_checks`,
   `unreadable_artifacts` and a full findings list with check names, severities,
   messages, citations and suggested edits — and its docstring says outright that
   it is "deliberately not a rendered string: what a UI shows and how it groups
   it is a decision nobody has enough use to make yet. Shipping prose would close
   it." Today a reviewer being asked to cross a stage boundary sees
   `wants to run advance_stage` plus raw JSON args. **This is the largest
   designed-but-unbuilt surface touching this page, and PR #74 left it
   explicitly open.**
2. **Per-tool autonomy on the session view** — the panel exists on the course
   page and the allow-all control in the drawer; neither is here.
3. **`docs/design/landing-page.md`'s design language** — tokens, region-level
   empty/loading/error treatment, and the "nothing on the page is happening"
   critique (§3.7) were applied to the landing page and never back-ported here.
   The session view predates all of it: `panes.css` uses ad-hoc `7px`/`12px`/
   `34px` rather than the `--space-*` scale, and there are three separately-worded
   empty states for what is arguably one situation.
4. **B18/B30** — there is no authentication, so the "learner" audience toggle is
   a presentation affordance and is documented as one in three places. Any
   redesign that makes it look like a permission boundary is a regression.
5. **B36's tool path** — a hand-driven `advance_stage` still poses its gate
   before anything is durable, so `artifact_paths` is empty there. A UI that
   offered "open the artifacts" from a gate must handle that case rather than
   render links that 404.

---

## 14. What a power user cannot do, that the data model plainly supports

1. **Compare two points of the same file side by side.** Both folds are
   addressable (`/files?path=&at=`), the diff engine exists, and the history view
   already diffs adjacent revisions — but there is no way to pick two arbitrary
   points.
2. **Diff two arbitrary events' whole workspaces.** `state_at` gives the full
   file list at any two points; nothing composes them.
3. **Search or filter the log.** No text filter, no kind filter, no jump-to-turn.
   `classifyEventType` already buckets every row into eight kinds and
   `turn_index` is on every row. A session with a thousand events is a thousand
   rows to scroll (and the timeline is not virtualised, unlike the landing page).
4. **Search the conversation.** No find, no jump to a message, no permalink to a
   message. `segmentTranscript` already assigns every message a stable absolute
   index that is used as a fold key and would serve as an anchor.
5. **Copy anything.** No copy button on a file, a diff, a tool result, a message,
   an approval's arguments, or the session id.
6. **See the system prompt** (D21) or the context strategy — both available;
   the REPL's `/state` shows both.
7. **Edit a tool call's arguments before approving**, or reject with a message.
   Both are first-class in the port and the HTTP body (§12.3).
8. **See what a stage gate found** before approving it (§13.1).
9. **Stop being asked** from the surface that does the asking (D19).
10. **Fork without leaving.** `POST /forks` returns an id; the client always
    navigates. "Fork and keep reading here" is a one-line change and is the
    REPL's `/fork` semantics.
11. **Name or annotate a session or a fork.** No field exists server-side either
    — this one is a real feature, not a wiring gap. The landing page falls back to
    `first_message`.
12. **Restart, re-run or edit-and-resend a turn.** `UserMessageSent` is in the
    log with its text; there is no "resend this" or "fork here and change the
    prompt", which is the obvious composition of fork + send and is the single
    most-requested shape for a tool like this.
13. **Delete or hide a file from the workspace view**, or sort/filter the file
    list. It is sorted by path server-side, unconfigurably. No tree view, no
    directory grouping, however deep the paths.
14. **Download a file, or export the transcript.**
15. **Jump from a conversation message to its timeline event.** The two panes
    describe the same log and share no cross-references at all — the timeline's
    `turn_index` and the conversation's message index are never joined. This is
    arguably the single largest missed affordance on the page.
16. **See the raw event payload** for a timeline row. The summary is a
    server-side one-liner; the underlying event is not exposed at all
    (`/events` returns rows, not payloads).
17. **Follow a turn's tool calls as they happen in the *conversation* pane.**
    Provisional content appears only under the timeline (F28) and vanishes when
    the turn commits, at which point the conversation jumps a whole turn at once.
18. **Know when the open file went stale** (D10). There is a `.stale` class, but
    it applies only to a placeholder during a scrub, never to genuinely outdated
    HEAD contents.
19. **Reach the research or course page's live work from here.** The breadcrumb
    links to both, but nothing on this page says whether a dispatch, a seeding
    run or an extraction is happening on this session's project — that lives
    only in the agent dock.

---

## 15. Where I am unsure

- **Live frame indices.** `_sse` builds a live log frame from
  `getattr(event, "aggregate_version", None)` while `/events` numbers rows by
  `enumerate(..., start=1)`. These should agree for a single-stream aggregate,
  and `appendEntry` dedupes by index so a mismatch would show as duplicate or
  missing rows rather than a crash. I did not verify the equality.
- **`FileView`'s `mode` (rendered/source) persistence across files** — I read it
  as *not* keyed to the path (unlike `tab`), so it persists. Worth confirming
  with a test, since the adjacent `tabFor` mechanism exists precisely to prevent
  that class of bug.
- **Whether the drift badge ever appears while this route is open** — it is
  driven by session-list projection health, which the session view does not read.
- **Preference storage backend** — I read `PreferenceStore` only through its port
  (`application/ports/preferences.ts`) and the `rt.collapsedPanes.*` key names
  quoted in `AgentWidget`; I did not read the adapter.
- **Approval `context` reaching the wire in practice.** I verified
  `stage_runner.py:700` passes `artifact_paths` and `composition.py:736` does
  not; I did not run either path.
- **I did not install dependencies or run any test suite** — this was a
  read-only survey, and nothing here was executed.
