# The explorer component

The five resolved components each show one view the *author* chose. `explorer`
is the first where the **reader** chooses: the model embeds a parameterised
query, and the reader re-runs it with different parameters. An answer stops
being an artifact and becomes a small app.

This spec is deliberately smaller than that sentence. What follows is the
largest honest version buildable with no new server work, and the reason every
larger version is not.

## 1. What the corpus can actually be asked

Measured against the routes, not reasoned:

- **`GET /timeline`** takes `entity_type`, `from`, `to`, `limit`.
- **`GET /graph/entities`** takes `name`, `entity_type`, `limit`, `after`.
- **`GET /topics`** takes nothing at all.
- **`GET /sources`** takes only `include_dropped`. `kind` — the axis a reader
  would actually want — is not a parameter.

So there are exactly two routes with a reader-varyable axis, and only one of
them can offer that axis honestly. **The blocker is vocabulary: no route
enumerates the known `entity_type` values.** `entity_type` appears in `app.py`
only as an input filter. The console's `knownTypes` is client-side residue in
both stores, and the two stores differ in a way that decides this design:
`timeline-store.ts:68-73` populates it from an *unfiltered* load, so it is
complete; `graph-store.ts:28-34` accumulates it across searches, so a widget
mounted cold has no vocabulary to offer at all.

**Therefore `explorer` is a timeline explorer, and its first release has one
backing read.** One request gives the widget both its initial view and its full
picker vocabulary. A graph explorer would need either a new route enumerating
entity types or a picker populated by whatever the reader happened to search
for, and the second is worse than no picker.

## 2. Why this is a distinct type and not a flag on `timeline`

The cheaper design is `timeline` plus a `controls:` field. Rejected, on intent
rather than mechanism: `timeline` is a view the author chose and is answering
*with*, and its craft notes tell the model to choose a window that makes a
point. `explorer` is an invitation to look for something the author did not
name. A model writing one is doing a different thing from a model writing the
other, and the registry's craft notes are the only place that difference can be
taught. Folding them into one type means one set of notes for two intents,
which is how a model ends up writing an explorer where a timeline was wanted.

The cost is a second registry entry over largely shared widget internals, and
it is paid once.

## 3. Shape

```component:explorer
over: timeline
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
vary: [entity_type, window]
prompt: |
  Narrow to Emperors and pull the window back to see how much of the
  century the reigns actually cover.
```

`over` is required and its only accepted value today is `timeline`. It exists
so that adding a second backing read later is a registry change rather than a
new component type, and so that the failure when someone writes `over: graph`
is a validation warning naming what is supported rather than silence.

`vary` names which axes the reader may change; the rest are fixed by the
author. Defaulting `vary` to everything was rejected — an author who set a
window deliberately and an author who did not are indistinguishable to the
reader unless the author says which.

`prompt` is the invitation. It is prose, and it is the one field that makes an
explorer worth more than a timeline: without it a reader is handed controls
with no reason to touch them.

## 4. The constraints the widget must respect

**Every reader interaction costs a full pass over the tenant's entity set,
twice.** `GET /timeline` is two full passes (`timeline_reader.py:108-115`) and
is deliberately uncached, and `limit` is not passed to the store
(`graph_reader.py:294-299`) so it does not govern that cost. Wave A's
`timeline` widget already holds its result with a non-trivial `staleTime` and
does not refetch on focus or mount, for exactly this reason. An explorer makes
the problem worse in kind, not degree: a reader dragging a date control can
issue a request per frame.

So: **the window control commits on release, not on change, and every distinct
parameter set is cached for the session.** A reader returning to a setting they
already tried must not pay for it twice. This is the widget's main engineering
content and it is not optional.

**`from`/`to` 422 on an unparseable date**, where nearly everything else in
this codebase clamps. Wave A's timeline widget already renders that as prose.
An explorer must additionally *prevent* it where it can — the control produces
the format the route accepts rather than accepting free text and reporting the
refusal.

**`undated_count` and `truncated` are rendered on every result**, as in
`timeline`. In an explorer they matter more: a reader narrowing a filter and
watching bands vanish needs to know which vanished because they were excluded
and which because the response was capped.

## 5. What the reader cannot do, and must not appear able to

- **Link to what they found.** No serialisable query state exists anywhere in
  this app: the only query string it carries is `?t=<seconds>` for a media seek
  (`routes.ts:130-140`), and nothing syncs filter state to a URL. So a reader
  can explore and cannot share the result. The widget must not grow a "share"
  affordance that does not work; a reader who wants to keep a view screenshots
  it, and saying so in the UI is better than implying otherwise.
- **Bound the cost.** `limit` bounds the response, not the server's work. The
  craft notes must say so, as `timeline`'s already do.

## 6. Out of scope

- **A graph explorer.** Needs an entity-type vocabulary route that does not
  exist. `over:` is the seam it would arrive through.
- **`GET /graph/entities`' `limit` is unbounded** — no clamp and no 422
  anywhere. It is the one axis here that would need server work *before*
  exposure, for response size rather than query cost. Another reason the first
  explorer is not a graph one.
- **Persisting what a reader chose.** An explorer resets on unmount, the same
  gap as BACKLOG B33: per-occurrence state does not exist and an ask has no
  session to hang it on.
- **Topic and source axes.** Neither route takes a parameter worth varying.

## 7. Testing

The four gates, plus the fifth: `research_team/interfaces/web/static` is a
committed build artefact, so any `frontend/src` change ends with
`npm run build` and a commit of the rebuilt assets.

- **Python**: registry shape; `over` accepting only `timeline` and warning by
  name otherwise; `vary` rejecting an unknown axis; projection identity in both
  views, as for every resolved type.
- **jsdom**: each control changes the query the repository is called with;
  an unknown `over` renders as prose; the counts render on every result.
- **Browser**: the box has a measured non-zero height in a markdown flow — the
  same assertion `graph` and `timeline` needed, for the same reason.
- **The cost behaviour is the test that matters**: a test proving the window
  control issues ONE request on release rather than one per change, and that
  revisiting a parameter set issues none. Write it first; it is the
  requirement most likely to be quietly lost in a later refactor.
