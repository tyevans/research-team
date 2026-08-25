# The interaction explorer

## Why

The console writes an interaction log and reads nothing back. The browser
POSTs batches to `/api/interactions`; the events land in `interactions.db`,
table `interaction_events`; no route reads them and no view shows them. To
look at the log today you open SQLite by hand.

That makes the log unfalsifiable. Every rule in `CLAUDE.md` about silent
instruments applies to it directly: a recorder that stopped, a projection that
dead-lettered a kind, an emitter that was never wired -- all three look
exactly like "the user did nothing". The log has no reader, so nothing has
ever disagreed with it.

This document specifies a reader.

## What it is for

Three questions, in the order a person asks them:

1. **Is the instrument working?** How many events, of which kinds, how
   recently, and did the projection drop any. A number on screen that nobody
   asserts on is the defect `CLAUDE.md` records under the co-mention channel;
   the health answer is first because it is the one that makes the other two
   trustworthy.
2. **What happened in one browser session?** The ordered stream, with dwell
   times, so a person can read one visit as a story.
3. **What happens across sessions?** Counts by kind and by view, dwell
   distributions per view, and the friction signals the vocabulary was built
   to carry -- undo, retry, empty results, repeated near-identical searches,
   and the approval deliberation split.

## What it is not

Not an analytics product. No charts beyond a bar per row, no saved queries, no
export. The log is one user's, on one machine, and the reader is a debugging
instrument for the console, not a dashboard for a business.

Not a second write path. Every route here is a GET.

## Scope boundary: one store, no joins

`interactions.db` is a separate event store from `sessions.db`. A projection
cannot span the two (`PositionForeignError`; see `CLAUDE.md`, "The interaction
log"). So the explorer resolves no project names, no session titles and no
entity labels from the domain. It shows ids.

The frontend may join on the client -- it already holds a project list -- and
that is where any naming belongs. The server does not.

## The read model already exists

`interaction_events` has: `browser_session_id`, `install_id`, `seq`, `kind`,
`view`, `occurred_at`, `received_at`, `project_id`, `session_id`, `payload`
(JSON text). Two indexes: `(browser_session_id, seq)` and `(kind,
occurred_at)`.

**No column is added and no schema changes.** That removes the whole class of
defect in `CLAUDE.md`'s "Read models" section from this work. If a later
iteration needs a column, that section applies again in full.

`InteractionLogStore` offers `events(browser_session_id)`, `count()` and
`truncate()`. Everything else the explorer needs is a new read on the same
connection.

## Routes

All under `/api/interactions`. All GET. All 503 with a named reason when the
reader is absent, matching the ingest route's precedent.

**A note on gating, because the two switches are not the same.**
`AGENT_INTERACTION_LOG=0` gates the *recorder*: nothing is written, but the
runner still starts and the table still exists. The reader is gated on the
*runner*, not on that variable. So with collection off, the explorer answers
200 with an empty log and says collection is off -- which is the honest
answer, and the one that lets a person tell "switched off" from "broken".

### `GET /api/interactions/health`

```json
{
  "collecting": true,
  "total": 12043,
  "first_at": "2026-08-19T09:12:04Z",
  "last_at": "2026-08-25T14:51:22Z",
  "kinds": {"ViewEntered": 4102, "ViewExited": 4098, "...": 0},
  "failures": [{"id": "...", "event_type": "...", "error": "...", "failed_at": "..."}],
  "install_count": 1,
  "session_count": 87
}
```

`kinds` carries **every kind in `INTERACTION_EVENTS`**, including the ones at
zero. A kind that was never emitted and a kind that does not exist must not
look the same, and a dict built from what the table happens to hold makes them
identical. This is the same shape as the checkpoint-marker rule: the vocabulary
is the authority, not the data.

`failures` comes from `InteractionLogRunner.failures()`. It is the reason this
route is first in the document.

### `GET /api/interactions/sessions`

One row per browser session, newest first.

```json
{
  "sessions": [
    {
      "browser_session_id": "...",
      "install_id": "...",
      "started_at": "...", "ended_at": "...",
      "event_count": 143,
      "max_seq": 143,
      "views": ["home", "project/catalog"],
      "project_ids": ["..."],
      "kinds": {"ViewEntered": 12, "...": 3}
    }
  ],
  "total": 87
}
```

Query: `limit` (default 50, max 500), `offset`, `install_id`, `project_id`,
`since`, `until`.

`event_count` beside `max_seq` on purpose. `seq` is the browser's own counter
and `event_count` is what arrived, so the two disagree exactly when delivery
lost something -- a gap no other surface can show, and the cheapest possible
integrity check on the transport.

### `GET /api/interactions/sessions/{browser_session_id}`

The full ordered stream, `seq` ascending, every row with its decoded payload.
404 when no row carries that id. No paging: a browser session is bounded by a
tab's life, and the largest real one is a few thousand rows.

### `GET /api/interactions/events`

The exploration workhorse.

Query: `kind` (repeatable), `view` (repeatable), `project_id`, `session_id`,
`install_id`, `browser_session_id`, `since`, `until`, `limit` (default 200,
max 1000), `offset`, `order` (`newest` default, `oldest`).

```json
{"events": [ ...rows... ], "total": 4102, "limit": 200, "offset": 0}
```

`total` is the count under the same filters, not the page length. A reader who
cannot tell 200-of-200 from 200-of-9000 cannot tell a filter that found
everything from one that hit the cap.

### `GET /api/interactions/summary`

Aggregates over a filtered window. Same time and scope filters as `/events`.

```json
{
  "by_kind": {"ViewEntered": 4102, "...": 0},
  "by_view": [{"view": "project/catalog", "entries": 812, "dwell_ms_median": 2310,
               "dwell_ms_p90": 18400, "hidden_ms_median": 0, "exits": 806}],
  "friction": {
    "undone": 14, "retried": 31, "empty_results": 96,
    "empty_by_where": [{"where": "search", "count": 61}],
    "repeat_searches": 22
  },
  "approvals": {"total": 40, "expanded": 12, "median_latency_ms": 3900,
                "median_latency_ms_expanded": 14200,
                "median_latency_ms_plain": 900,
                "by_decision": {"approved": 33, "rejected": 7}}
}
```

Definitions, because each one is a judgement and an undefined number is worse
than no number:

- `by_view.dwell_*` are over `ViewExited.dwell_ms` for that view. `entries`
  counts `ViewEntered`, `exits` counts `ViewExited`, and the two are reported
  separately because their difference is the count of views left by a route
  the page-hide flush did not catch.
- `hidden_ms` is reported beside dwell, never subtracted. `ViewExited`'s
  docstring gives the reason and it holds here: the consumer chooses.
- `repeat_searches` counts a `SearchPerformed` whose `query_text` is within a
  normalised edit distance of the immediately previous `SearchPerformed` in
  the same browser session. Normalised means lowercased and whitespace
  collapsed. The threshold is a named constant, and it is a **heuristic** --
  the number is a pointer to a stream worth reading, never a measurement.
- `approvals.expanded` counts `expanded_details == true`. That field's own
  docstring says the name overstates it; the API repeats the caveat in its
  docstring rather than renaming the number.
- Medians rather than means throughout. One backgrounded tab produces a dwell
  in the hours, and a mean over it says nothing about anybody.

**Every median is computed in Python over the filtered rows, not in SQL.**
SQLite has no median. A percentile written in SQL here would be an
approximation nobody could check.

## The reader seam

`create_app` gains one parameter, `interaction_reader: InteractionLogReader |
None`. The reader is a small class in
`infrastructure/persistence/interaction_log.py` that holds the store's
connection and answers the five reads.

**It is not the runner.** The runner owns a subscription, a checkpoint
repository and a lifecycle; the routes need none of that and passing it would
make every route test start a projection. The runner exposes the reader
(`runner.reader`), and `failures()` stays on the runner because the DLQ is the
runner's.

The rule from `CLAUDE.md` about a port with one adapter applies here and is the
main test requirement: **at least one test per route drives the real store,
written through the real ingest path, and asserts on the data.** A test that
asserts the route answered 200 passes with the projection removed.

## The console

### A route, not a project facet

`#/i` -- a new top-level `Route` variant, `{ name: 'interactions', selection }`.
Not a facet on the project page: the log spans projects and installs, and a
facet would force a project id onto a view whose whole subject is what happens
between projects.

Reached from the header, beside the brand. Not from a project.

### The view records itself

`viewNameOf` returns `interactions` for the new route, so browsing the log
writes rows to the log. Deliberate, and stated here because it will confuse
somebody: the explorer's own dwell rows are real interaction data and are not
filtered out. A person reading view counts will see `interactions` near the
top, and the honest reading is that they were the one looking.

### Panes

One page, four regions, top to bottom:

1. **Health strip.** Collecting yes/no, total, last event age, and -- when
   non-empty and only then -- a failures block. A red block that is usually
   absent is readable; a green tick that is always present is not.
2. **Filter bar.** Time window (last hour / day / week / all, plus explicit
   from-to), kind multi-select built from `INTERACTION_EVENTS` rather than
   from the data, view multi-select, project, install. Every filter is in the
   URL, following the routing grammar's own rule that a linkable state is a
   bookmark.
3. **Summary.** Counts by kind, the per-view dwell table, the friction block
   and the approval split. Each number is a link that applies itself as a
   filter to the feed below -- that is the whole "explore" affordance, and it
   is worth more than any chart.
4. **Feed.** Newest first, one row per event: time, kind, view, ids, and the
   payload rendered per kind rather than as raw JSON. `ViewExited` reads "left
   project/catalog after 2.3s (0.4s hidden)", not a dict. Raw JSON is behind a
   per-row disclosure. Clicking a row's browser session opens the **session
   drill-down**: the same feed, scoped to that session, ascending, with the
   gaps between events shown.

### Data layer

`HttpInteractionLogRepository` in `infrastructure/http/`, DTOs in `dto.ts`,
mappers to domain types in `domain/interaction/`. React Query keys under
`queryKeys.interactions`. The sink that writes stays exactly as it is and is
untouched; the reader is a separate object, because a sink that also reads is
one object with two reasons to change.

## Verification

Beyond the four gates:

- One route test per route over a store seeded through the ingest route, not
  through `store.record`. Seeding through the recorder is what makes the test
  see a decoder that stopped matching.
- A test that the health route's `kinds` dict covers `INTERACTION_EVENTS`,
  derived from the tuple by introspection. A hand-written list is the failure
  the checkpoint-marker section records.
- A test that `/events` `total` differs from the page length under a cap.
- A frontend test asserting a rendered number, not that a fetch happened.
- `npm run test:browser` is not required: no new layout primitive and no
  computed-style correctness. If the feed grows a virtualised list or a
  measured row height, it becomes required.

## Deliberately not built

- **No delete or truncate route.** `rm ~/.research-team/interactions.db` is the
  documented reset and it is one command. A destructive HTTP route on a port
  with no authentication buys convenience and costs the whole log.
- **No live tail.** The feed refetches on an interval. A websocket for a
  debugging surface is a second transport to maintain.
- **No cross-store join.** Stated above; structural, not an omission.
- **No retention or rollup.** The log is small and the machine is one laptop.
  Revisit when the table passes a million rows, which at present rates is
  years.
