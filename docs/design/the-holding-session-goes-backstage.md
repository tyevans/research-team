# The holding session goes backstage

Item 2 of `console-reimagining-roadmap.md`. Written against
`holding-session-map.md`, which was produced first and deliberately proposes
nothing — read that for the ground truth this argues over, including the line
numbers, which are not repeated here.

## 0. The ask

> we should just accept that for the most part we always just want to see the
> head state — make current holding session type stuff a background concern,
> not something the user manages, on the project list view and the detail
> views. also we should be able to see the project files from the main project
> view (the one with the tabs that we've been revising). chat with an active
> session should be unobtrusive.

## 1. The one thing this must not do

**Holding does not become permanent, and nothing joins implicitly.**

This is the whole risk of the ask, and it is worth stating before the design
rather than in a caveat at the end. "Make it a background concern" reads, to a
naive implementation, as "always have a holder". The map's trap (c) is why
that is wrong, and it is wrong in four independent ways at once:

- `active_session_id is None` is the *precondition* for `JoinProject`. A
  project that always has a holder can never be joined.
- It is half the precondition for the tip catch-up. `_catch_up_tip` becomes a
  permanent no-op, which silently reinstates the filesystem-detachment bug it
  was written to prevent — work done after a release never rejoins the project
  it was done in.
- The dispatch queue is serialised *by that refusal*, not by a mutex. A
  long-lived console holder starves every dispatch: they wait forever behind a
  holder no person is driving.
- `/join` attaches the graph process-wide and says so plainly. Joining
  implicitly on page open means opening a project in a second tab silently
  re-points the attachment under a running turn in the first.

So: **the server's holding model is not touched.** Nothing in this document
changes `Project.decide`, `start_in_project`, `release_project` or
`_catch_up_tip`. What changes is that the console stops asking a person to
know about any of it.

The distinction to hold onto: *holding* is about where the next write goes.
*Reading the head state* is a different question, it has an answer whether or
not anybody is holding, and the console has been conflating the two.

## 2. The head state has an answer already, and it is not new machinery

`topic_documents_view` resolves it, server-side. This is the shape it had
when this document was written; §2.1 records what the measurement then did to
the `at` half of it, and the surviving version is simpler:

```python
if state.active_session_id is not None:
    session_id, at = state.active_session_id, None
elif state.tip_session_id is not None and state.tip_at_event >= 1:
    session_id, at = state.tip_session_id, state.tip_at_event
else:
    session_id, at = None, None
```

and its docstring already contains this design's central argument, written for
a different feature:

> The `session_id` is the reason this is not just a list of paths. Every reader
> of a file in this API […] is keyed by `(session_id, path)`, and a dispatch
> writes on a session it creates and releases. Nothing on the research view
> knows which session that was. This resolves it once, so a viewer reuses those
> three routes unchanged instead of a fourth project-scoped copy of each
> growing beside them.

**The proposal is to lift that resolution out of the topic-documents presenter
and put it on the project view itself**, as one named pair — call it the
project's *reading head*: the session to read through and the point to read it
at. `None`/`None` when the project has never had a tip, which is a real state
and reads as "nothing written yet".

Everything downstream then reuses the session-keyed readers unchanged, which
is the property the quoted docstring is protecting. No project-scoped copies of
the file, parse or history routes. `regionOf`'s `file` case has already made
this argument from the routing side — "the routing already treats a file as
project-shaped; only the data source is still session-shaped" (map, trap i).

### 2.1 SETTLED, 2026-08-27, and by something better than a tiebreak

**The conflict below was real, was measured, and the measurement found a third
thing: the response contradicted itself.** `topic_documents_view` built its
`documents` array from `project_files` — HEAD — while reporting `at` as
`tip_at_event`. So a file written after release was *listed*, and
`GET /api/sessions/{id}/files?path=…&at=<that offset>` — the exact route the
`at` exists to feed — answered `404 … not found as of event 7`. One response,
two resolutions, and the pair was unusable.

HEAD survived, on the domain's own criterion rather than the presenter's:
`_catch_up_tip` exists to drag a stale tip up to `len(history)`, and its
docstring calls work stranded past a release "unreachable from the project the
moment they were written" — a bug, already settled by a test. **An offset below
HEAD is never a statement about what a project *has*; it is a pointer the next
join will move.** Its real job is as a fork point (`inherited_at`,
`_fork_files_from`), which is a different question.

Notable for anyone re-checking this: the real database *cannot* separate the
two resolutions, because `_catch_up_tip` runs on every join and every live
project's `tip_at_event` equals its tip session's stream length exactly. The
one project whose tip ran on after release did so by a single `TurnFailed`,
which touches no file. The divergence had to be reproduced synthetically, and
the report says so rather than implying the case is common.

`topic_documents_view`'s offset is deleted and `at` is now `None` in every
branch. Two consequences this document inherits:

- **`at` now carries no information** and should be dropped from the frontend
  DTO, `toTopicDocuments`, and the `TopicDocuments` domain type. That is
  frontend work and belongs in step 2 of §7.
- **`_catch_up_tip` still only runs on join**, so `tip_at_event` remains stale
  between a release and the next join. That is now unobservable through this
  route, but any *future* reader of `tip_at_event` inherits the same trap and
  nothing forbids one. The reading head in §2 must not become that reader.

What follows is the original statement of the conflict, kept because the
reasoning on both sides is what made it worth measuring rather than arguing.

### 2.1a The conflict as it stood

There are **two different answers to "what are this project's files" live in
one process**, and only one of them has its reasoning written down:

- `project_files` reads the tip session at **HEAD**, and its docstring argues
  at length that reading *to the offset* is what produced an empty-file-list
  bug.
- `topic_documents_view` hands the client the **offset**, and argues that
  reading the tip session at HEAD "would show files the project does not have"
  because that session may have run on past the tip.

Both arguments are coherent and they contradict each other. This design cannot
pick one by reasoning, because both were arrived at by reasoning and one of
them is wrong.

This was resolved by measurement rather than by argument — §2.1 has the answer.
Building the reading head on top of an unresolved contradiction would have put
a third answer in the process.

## 3. What leaves the interface

### 3.1 The "Holding session" tab

Gone as a *tab*. A person does not pick which session to read a project
through; the reading head answers it. The transcript remains reachable — see
§4 — but not as a peer of Curriculum and Graph in a strip of things to look at.

Note the map's trap (g) while doing this: the tab's click behaviour **has
already broken silently once**, bouncing readers to Curriculum for a whole
slice, and "the one file that clicks this tab is in the browser project,
outside CI". Anything asserted about tab clicks that jsdom can judge — which
is the href, the selected value, and which panel renders — belongs in the
jsdom suite, in CI. Leave in the browser suite only what is genuinely a
measurement.

### 3.2 The Workspace tab's gate

`visibleMaterialTabs` hides Workspace when nothing holds the project, and that
condition was earned honestly: 14 visits, 0.7s median, **100% bounce**, which
is what arriving at an `EmptyState` and leaving looks like in aggregate.

**Do not widen the gate. Remove the cause.** A tip-backed workspace has files
whether or not anyone is holding, so the tab stops being dead — and the
condition changes from "is somebody holding" to "does the reading head resolve
to anything". A rework that widened `hasSession` without moving the data source
produces a tab that is present and still empty, which is precisely the defect
the measurement condemned.

The deep-link exemption stays and keeps its comment: dropping a tab while its
panel is open leaves Radix with a selected value no trigger carries, and the
strip shows nothing chosen above an open panel.

### 3.3 The holder on the project list

The index page owns this half and is being built in parallel; it is named here
only so the boundary is explicit. One thing crosses: `DELETE /api/projects/{id}`
refuses a held project unless `release_holder=true`, and the console passes
`isHeld(project)` for that flag. **If the console stops tracking heldness, that
flag becomes a guess.** Either the route stops needing the client's opinion, or
the client keeps the fact without displaying it. It must not keep displaying it
because the delete button needs it — that is the tail wagging the dog, and it
is how a "background concern" stays on screen forever.

## 4. Chat becomes unobtrusive

Today the transcript, composer, scrub bar and event log are all behind
`sessionId === null` guards, and when there *is* a session they are a whole
tab's worth of page. Both halves are wrong for the same reason: a conversation
with a project is something you do *while* looking at something else, not
instead of.

The direction, to be designed properly against the primitives available: a
persistent, collapsed-by-default surface that is present when a session is
live, that does not take a third of the page to say nothing, and that does not
require navigating away from what you were reading to say something. The
session's *full* view — timeline, scrub, event log, forking — stays where it
is, at the session route, which is where somebody who wants to study a run
goes.

This is the part of the item with the most latitude and the least prior art in
the tree, and the user's bar is "immaculate". Lean on the installed
primitives rather than hand-rolling a docked panel.

## 5. `AutonomyLock`, which will break silently if this is done carelessly

The lock records a policy write against the holding session, and with a `null`
session it renders **the entire panel read-only with one line of prose**. No
throw, no warning, indistinguishable from working. It is the
`silent-defaults-hide-missing-wiring` shape already instantiated in the code,
sitting directly downstream of the thing this document is changing.

Two acceptable outcomes, and one unacceptable one:

- **Acceptable:** the audit record lands against the reading head's session,
  resolved exactly as files are. Consistent with everything else here, and the
  lock stops caring about holding at all.
- **Acceptable:** the read-only state becomes loud — it is a real state and it
  can say so where a reader will see it.
- **Unacceptable:** the lock quietly receives `null` more often than it used
  to and nobody notices for a slice.

A test has to distinguish these. Per `CLAUDE.md`, the assertion is that the
write *reached the sink* with the expected session id — never that nothing
threw.

## 6. Things that will bite, collected

From the map, the ones that constrain this work rather than merely inform it:

- **`useSessionScreen` tolerates `null` by doing nothing**, and its own
  docstring says `state` on a null screen is stale data no caller may read. A
  new caller that reads `screen.state` without checking the id first gets the
  *previous* session's data, with no error.
- **`endSession` invalidates the listing, not the detail.** The detail is kept
  fresh only by the SSE `project` frame. Change that subscription or that query
  key and ending a session leaves a stale holder id on the page with no error.
- **`GET /api/projects` folds one aggregate per row.** Adding a per-project
  head session or file count to the *listing* pays that cost again, on a
  listing that already defers a feature for exactly this reason. The reading
  head belongs on the project *detail*, not on the listing, unless somebody
  measures the listing and finds room.
- **Deleted projects 404 on reads as of 2026-08-27.** Any new project-scoped
  route goes through `_require_project` or it inherits the bug that route
  family already had once.

## 7. Sequencing

1. ~~Settle §2.1 by measurement.~~ **Done, 2026-08-27** — HEAD survived, and
   the measurement found a self-contradicting response rather than a tiebreak.
   The frontend half (dropping the now-constant `at`) falls into step 2.
2. Reading head on the project detail view, server-side, with the resolution
   lifted out of `topic_documents_view` so there is one copy.
3. Workspace as a project tab over the reading head; the gate's condition
   changes with its data source, not before it.
4. The holding-session tab goes; tab-click assertions move into CI.
5. `AutonomyLock` re-pointed, with a test that asserts the recorded write.
6. Chat, unobtrusive. Last, because it is the most design and the least
   plumbing, and because it is the one a person will judge by looking.
