# Exposure Surfaces and Redaction

**Status: findings for the backlog, not a v1 design.** This system has no user
system and no RBAC. There is therefore no "learner" principal, and any
author/learner boundary is blocked on authentication that does not exist —
which makes the whole of Part 1 long-term hardening rather than buildable work.
Part 2 is different: it is about doors that close permanently once material is
ingested, so it is worth knowing *before* the first SME transcript goes in.

Two problems were tangled in the remark *"we can filter the exposed event feed
for sensitive data I suppose."* They have different shapes and opposite correct
answers:

- **Problem 1 — answer withholding.** A read-surface problem. Filtering is the
  wrong mechanism; separation is right. Recorded here, deferred on auth.
- **Problem 2 — sensitive source material.** A write-time problem. Filtering a
  read surface erases nothing, so the remark does not address this case at all.

Line references are to the working-tree state at the time of writing. Findings
inferred from library source rather than documentation are flagged
**[unverified against docs]**. Drafted backlog entries are in Part 3.

---

## Part 1 — Answer withholding (recorded, deferred on auth)

### 1.1 The finding

Everything an author writes reaches any browser that can open a socket. There
is no authentication anywhere: a grep for auth, middleware, CORS, token, or
login across `research_team/interfaces/web/app.py` and `web.py` returns
nothing. The app is built at `app.py:85-514` with no middleware stack, no
dependency guards, no key. `/api/docs` is enabled (`app.py:101`), so the route
inventory is self-describing to anyone who reaches it.

The only control is the bind address, `research_team/infrastructure/config.py:57-58`
— loopback by default, one environment variable from every interface.

### 1.2 The surfaces, so a future reader does not rediscover them

| # | Surface | Code | What escapes |
|---|---|---|---|
| 1 | `GET /api/sessions/{id}` | `app.py:275-290`, `presenters.py:114-157` | **Full conversation** — `messages` (`presenters.py:156`) is every message body via `message_view` (`:93-103`), including content and every tool call's args. Plus `system_prompt`. Files are path + size only (`:148-155`). |
| 2 | `GET /api/sessions/{id}/events` | `app.py:292-295`, `presenters.py:89-90` | Timeline rows whose `summary` (`presenters.py:30-64`) leaks 30-char snippets of `FileEdited` old **and** new strings (`:37`, `_snippet` `:67-70`), the first 120 chars of message content (`:63`), every tool name (`:62`), and 80 chars of error text (`:55`). |
| 3 | `GET /api/sessions/{id}/at/{at}` | `app.py:297-304` | As #1, folded to any past event — the full conversation as of any moment. |
| 4 | `GET /api/sessions/{id}/files?path=&at=` | `app.py:306-324` | **Full file content**, at HEAD or as of any event, *including files deleted at HEAD*. The docstring at `:310-312` states this is intentional. Deleting an answer file does not un-expose it. |
| 5 | `GET /api/sessions/{id}/files/history?path=` | `app.py:326-329`, `presenters.py:160-180` | **The fattest leak.** Every revision of one path: full content per revision (`:170`) plus `old_string`/`new_string` per edit (`:175-178`). One request returns a file's complete authoring history — and it ignores the scrub point entirely. |
| 6 | `GET /api/stream` — SSE, three channels on one connection | `app.py:491-505`, `_sse` `:517-613` | (a) *event* frames — `feed_event` (`presenters.py:225-235`) carries every leak in #2, live, with `Last-Event-ID` replay (`app.py:500,547`). (b) *approval* frames — raw `json.dumps` (`app.py:593`) carrying pending tool-call arguments. (c) *activity* frames — same raw dump, carrying the assistant's reply **as it streams**. Channels (b) and (c) bypass `presenters.py` entirely. |
| 7 | `GET /api/sessions/{id}/turns/current/activity` | `app.py:433-449` | Catch-up for #6c. Serves `discarded` content from turns that **failed and were rolled back**. |
| 8 | `GET /api/sessions/{id}/approvals` | `app.py:451-459` | Pending gated calls with arguments. |
| 9 | `POST /api/sessions/{id}/turns` response | `app.py:393-398` | `outcome.reply` — the assistant's complete reply. |
| 10 | `GET /api/sessions` | `app.py:109-111`, `presenters.py:183-193` | `first_message` (`:189`) for **every session in the database**, rendered on the index page (`app.js:768-790`). Cross-session by default. |
| 11 | `GET /api/tree` | `app.py:271-273`, `presenters.py:196-200` | As #10, nested. |
| 12 | `GET /api/projects` | `app.py:118-132` | Project names, holder session ids. |
| 13 | `POST /api/sessions/{id}/forks` | `app.py:483-489` | Not a read leak: any caller can branch a session at any event. |
| 14 | `POST /api/summaries/rebuild` | `app.py:258-269` | Unauthenticated operational action. |
| 15 | `/` and `/static/*` | `app.py:507-512` | The console. |

**There is no session-export endpoint.** No route emits a bundle, and
`grep -i "export\|download\|clipboard\|copy"` over `app.js` and `index.html`
finds only an unrelated comment at `app.js:2424`. Worth recording because it is
the obvious next feature and would be a sixteenth surface.

### 1.3 The conclusion, for whenever auth exists

**Filter the author surface: no. Separate deny-by-default read surface: yes.**

Three reasons, in decreasing order of how decisive they are:

1. **The transcript cannot be filtered even in principle.** Filtering assumes
   sensitive content is localized in a payload you can enumerate. The agent
   reasons in prose while authoring — "I'll make the distractor 1/4 because
   students who invert the fraction land there, so the key is B" is an
   `AssistantMessageAdded` (`events.py:60-62`) served verbatim at
   `presenters.py:156`, structurally indistinguishable from a message about
   formatting. Closing it needs per-message semantic classification with no
   ground truth, where every false negative is permanent — redaction has no
   undo on a retina.

2. **Time travel defeats state-based gating.** `/files/history` is not
   scrub-scoped (`presenters.py:160-180`) and `/files?at=` takes a
   client-supplied index (`app.py:307`). "The answer is not written until event
   400" buys nothing.

3. **The failure mode is backwards.** A filter is allow-by-default with a
   blocklist: every new route leaks until someone remembers it — and two SSE
   channels already bypass the presenter layer where a filter would live
   (`app.py:592-593`). `Last-Event-ID` replay makes a filter bug retroactively
   exploitable.

The deeper point is that the two surfaces want **opposite defaults**. The
console's entire thesis is total transparency over the log (`app.js:1-8`,
`app.py:299`). A filter makes it a worse authoring tool *and* an untrustworthy
learner tool. Two surfaces over one event store is not a compromise; it is the
only configuration where each is good at its job.

The shape when it is built: a `Publication` — an author-created allowlist of
`(path, at_event)` pairs with **pinned revisions**, served by a reader that has
no `/at/{n}`, no `/files/history`, no `/events`, no SSE, and no conversation.
Those routes cannot leak if they do not exist on that surface. The cheapest
correct version is a static export directory served by a separate process:
zero shared code, therefore zero shared failure modes.

One nuance worth preserving: a **presenter mode** that collapses message bodies
for screen-sharing with a colleague is legitimate — but as cosmetic
shoulder-surfing hygiene, labeled as such, API unchanged. The failure mode of
calling a cosmetic filter a boundary is that someone later puts a learner on
it. And note the case cutting the other way: UbD's **W** element wants learners
to see goals and evaluative criteria *early*, so some agent reasoning should be
published — a per-artifact decision an allowlist expresses and a blocklist
cannot.

---

## Part 2 — Sensitive source material

The remark does not address this. Filtering a read surface changes what is
displayed; it removes nothing from the log, the snapshots, the read models, or
the knowledge graph.

### 2.1 What happens today

**The event store is strictly append-only and offers no redaction.** The
`EventStore` protocol in `eventsource` 0.5.0
(`eventsource/stores/interface.py`) declares exactly: `append_events` (`:329`),
`get_events` (`:377`), `get_events_by_type` (`:417`), `event_exists` (`:454`),
`get_stream_version` (`:473`), `read_stream` (`:494`), `read_all` (`:564`),
`get_global_position` (`:608`). **No delete, no update, no redact.** A
repository-wide grep finds deletion only on read models, snapshots, the DLQ,
and migration routing — never on the log.

Everything derived is deletable, and the codebase leans on that deliberately:

| Layer | Deletable? | Where |
|---|---|---|
| Event log | **No** | `eventsource/stores/interface.py` — no such method |
| Snapshots | Yes | `eventsource/snapshots/sqlite.py:230`, `:315` |
| Read models | Yes | `eventsource/readmodels/sqlite.py:258`; `read_models.py:254-262` |
| DLQ | Yes | `eventsource/repositories/dlq.py:208` |
| `/sessions` projection | Rebuildable | `read_models.py:368-400` |
| Knowledge graph | Rebuildable | `knowledge/rebuild.py:38` |

**Snapshots are a second, non-obvious copy of every payload.**
`SNAPSHOT_THRESHOLD = 50` (`event_store.py:22`), `snapshot_mode="background"`
(`:81`). Every 50 events the folded `CodingSession` state is serialized — and
that state holds `state.files` (full contents, per `presenters.py:148-155`) and
`state.messages` (the whole conversation). A redaction that forgets snapshots
leaves plaintext behind and looks like it worked. They are cheap to delete and
free to rebuild, but they must be *remembered*.

**Where material lands:**

| Path in | Event | Field |
|---|---|---|
| Transcript pasted into a turn | `UserMessageSent` | `message` — `events.py:55-56` |
| Agent quotes it back | `AssistantMessageAdded` | `message` — `events.py:61-62` |
| Tool reads a file containing it | `ToolResultRecorded` | `message` — `events.py:67-68` |
| Agent writes it to a file | `FileWritten` | `file_data` — `events.py:147-148` |
| Agent edits that file | `FileEdited` | `file_data` **and** `old_string` **and** `new_string` — `events.py:160-164`. **One edit stores the payload three times.** |
| Gated tool call carrying it | `ToolCallDecided` | `args`, `edited_args` — `events.py:186-192` |
| Compaction summarizes it | `ConversationCompacted` | `summary` — `events.py:115` |
| `remember(text, …)` | redstring `Document` stream | full source text — `knowledge_tools.py:81`, `redstring_adapter.py:117-143` |
| Derived index | `SessionSummaryRow.first_message` | `read_models.py:80,159` — rendered for every session on the index page |

And redstring's streams live in **the same SQLite file**. `event_store.py:229-247`
documents it: the `read_since` filter exists precisely because "redstring's
`Document` and `Consolidation` streams live in the same file." `remember()`
does not put corpus material somewhere separable.

### 2.2 The central property

**Files fold out of the session stream. There is no filesystem on disk to
consult.** `state_at(session_id, at)` replays the first *N* events to
reconstruct `state.files`; `GET /files` (`app.py:306-324`) reads that folded
dict. File content exists *only* as event payloads plus snapshots. This is what
makes scrub-to-N work, and it is what makes every redaction technique below
more disruptive here than in a system where the log sits beside a real
database.

### 2.3 The four erasure patterns against this system

#### Crypto-shredding — encrypt per subject, delete the key

([Verraes](https://verraes.net/2019/05/eventsourcing-patterns-throw-away-the-key/),
[Event-Driven.io](https://event-driven.io/en/gdpr_in_event_driven_architecture/))

1. **The fold becomes lossy in a way the domain does not express.**
   `apply(FileWritten)` must produce *something* for `state.files[path]` when
   the payload no longer decrypts. `session_view` computes
   `len(data.get("content",""))` (`presenters.py:151`), `get_file` returns
   `entry.get("content","")` (`app.py:324`), `file_history` reads
   `file_data.content` (`presenters.py:170`) — all three would report an empty
   file rather than a redacted one.

2. **Scrub-to-N over a shredded range shows a filesystem that never existed**,
   with no marker.

3. **`FileEdited` is a delta, and crypto-shredding does not survive delta
   encoding.** This is the finding specific to this codebase and it is
   decisive. `events.py:160-164` stores `old_string`/`new_string`; the fold
   applies the substitution to current content. Shred revision 3 of a path and
   revision 4 is an edit whose `old_string` matched revision 3's text — **the
   fold of revision 4 is undefined**, and corruption propagates to every later
   revision of that path. Crypto-shredding write-ups assume whole-value events;
   half this log is deltas.

4. **Key granularity does not match the data.** A key's unit is a data subject;
   an event's unit is a file write that may quote six people from one
   transcript. Per-subject field-level encryption would require the authoring
   step to segment content by subject, which nothing does or could do.

5. Legal footnote, non-decisive for a local tool: GDPR treats encrypted
   personal data as still personal data, so key destruction as erasure is
   [contested](https://granit-fx.dev/dotnet/compliance/crypto-shredding/).

**Verdict: disqualified here.** Point 3 alone settles it.

#### Forgettable payloads — log holds a reference, payload in a deletable store

([Verraes](https://verraes.net/2019/05/eventsourcing-patterns-forgettable-payloads/))

- **Least disruptive to the fold**: `state.files[path] = {ref}` folds fine,
  resolution happens at read time.
- **But it breaks the system's stated central claim.** `event_store.py:85-98`
  and `read_models.py:1-11` both rest on the log being the sole source of truth
  and everything else being derived and disposable — which is exactly why
  `rebuild_summaries` and `rebuild_graph` are safe. A blob store is a second
  store that is *not* derivable and *must not* be lost. Losing it does not
  degrade a projection; it destroys content.
- **It breaks forks quietly.** A fork shares the source session's events
  (`events.py:132-142`), therefore shares refs. Deleting a blob silently
  empties every fork that inherited it.

**Verdict: right for ingested corpus material and identifiers, wrong for
authored file payloads.** Applying it to files guts time travel; applying it to
the corpus is what §2.4 recommends.

#### Stream rewriting / copy-and-transform

- **Library support is partial and not what it looks like.**
  `eventsource/migration/` has `BulkCopier`, `DualWriteInterceptor`,
  `CutoverManager` — but per `migration/__init__.py:1-20` these exist for
  multi-tenant *store-to-store* migration, not content transformation. I found
  **no upcaster or transform hook** anywhere in the library, so this would be
  hand-rolled. **[unverified against docs — inferred from reading
  `eventsource/migration/` and grepping for upcast/transform classes]**
- **Positions are invalidated, and that is fine.** `decode_position`
  (`event_store.py:253-269`) already rejects a cursor from a different
  `store_id` and treats it as no cursor. Browser `Last-Event-ID` values,
  checkpoints and DLQ entries all become meaningless, and the code handles it.
- **Snapshots must be dropped and rebuilt.** Supported.
- **Hard constraint: rewrite in place, never delete.**
  `SessionForkedFrom.at_event` (`events.py:141`) is an *index into the source
  stream*, resolved positionally by `service.fork` (`app.py:483-489`). Dropping
  events renumbers everything after them, so every fork in the database
  silently re-points to a different moment. Preserve event count and order;
  replace payloads with tombstones.
- **It is the only technique that can fix the delta problem**, because a
  rewrite pass sees the whole stream and can re-derive an affected path's
  content consistently — or collapse its history into one redacted
  `FileWritten`.

**Verdict: the break-glass tool.** Not routine, but the only thing that
produces a coherent post-erasure log. Worth knowing it exists and roughly what
it costs before needing it.

#### Tombstone + rebuild

- **Does not erase.** The payload is still in SQLite pages. Against disk
  imaging, backups, or a lost laptop it does nothing.
- **But it costs almost nothing and composes.** It records that redaction was
  requested, gives the UI a legitimate `[redacted]` instead of a confusing
  empty file, and is the natural input to a later rewrite pass.
- SQLite footnote: freed pages retain data until `VACUUM`, and the WAL plus any
  backups hold their own copies.

**Verdict: adopt the event type early**, even before anything emits it.

### 2.4 Where the control should sit — intake, decisively

**Read time — no.** That is the Problem-1 mechanism. It changes display and
erases nothing; the material is still in the log, snapshots, read models and
graph, and still on disk when the laptop is lost. Treating it as an answer here
is exactly the conflation in the original remark.

**Write time (classify and route) — no, and this is the tempting wrong
answer.** There is no ground truth for "sensitive"; a false negative writes
plaintext to an append-only log, so **the error is permanent and the classifier
is the last line of defense**; and by write time the material has already been
through the model's context.

**Intake — yes.** Four reasons:

1. **It is the only cheap decision.** Every downstream option costs a full
   stream rewrite, and one of them is outright broken over deltas. Append-only
   means intake is the last moment anything is free.
2. **A human already stands there.** `synthesis-generic-workflow.md` §0 puts
   corpus intake at spine position [0] with a mandatory human gate on the
   routing coverage report; `tyler-model.md` Step 0 requires human review of
   claim routing before objectives are drafted. Redaction is another output of
   a gate that already exists.
3. **The `Exclusion` artifact already has a place to record it.** All three
   methodologies produce a cut list and the synthesis canonicalized it.
   "Withheld: transcript §4, performance judgments about a named individual" is
   an `Exclusion` with a reason, reviewable where every other scope decision is.
4. **Pseudonymization at intake gives real erasure at near-zero cost.** Replace
   identifiers with stable tokens (`P-07`, `ACCT-3`) before anything reaches a
   turn; keep the mapping in a sidecar **outside** the event store. This is
   forgettable-payloads applied only to *identifiers*: it does not touch the
   fold, creates no must-not-lose content store, and deleting the sidecar
   leaves a log holding only tokens. It is **retroactively impossible**.

### 2.5 The redstring interaction

**The graph is derived, so deleting it is free and meaningless.**
`rebuild.py:38-56` folds it from the log at project open; the docstring at
`:1-5` says the store is kept in memory precisely because "losing it costs a
fold rather than data."

**The source of truth is redstring's `Document` events in the same SQLite
file** (`event_store.py:236-238`). Erasure happens there or nowhere.

**Extraction and consolidation make it materially harder, in two ways:**

1. **A person named once becomes a node whose label is their name.**
   `remember(text, source_id)` (`knowledge_tools.py:81`) hands up to 200,000
   characters (`redstring_adapter.py:47-48`) to `build_graph`, which extracts
   entities.

2. **Consolidation then merges that node with mentions from other documents**
   (`redstring_adapter.py:166-182`), and per the module docstring at `:15-18`
   **`Consolidator.resolve` appends its own merge event**. So the identity is
   aggregated across sources — the re-identification-through-association risk
   the forgettable-payloads write-up names as unsolved — and the association is
   recorded as an `EntitiesMerged` event **independent of any single document**.

**Erasure in the graph is therefore not a per-document operation.** It needs
the document events *and* every consolidation event referencing the entity,
rewritten and refolded — and if two documents mentioned the person, deleting
one accomplishes nothing. The name likely survives inside the merge payload
even after the transcript is gone.

**With intake pseudonymization**: the transcript says `P-07`, the node is
`P-07`, the merges are over `P-07`, and deleting one sidecar line erases the
person from the graph **without touching a single event**. Structure and
analytical value are preserved. This is the case for §2.4 in one paragraph.

### 2.6 Cheap now, expensive later

**Threat model, honestly.** Local, single-user, loopback-bound, no auth, no
external users, no regulatory obligation. Realistic risks in order: an
accidental non-loopback bind or port-forward; the `.db` reaching a git repo,
backup or shared drive; a lost laptop; and **future regret** — ingesting real
SME transcripts now and wanting them gone later, when the only remedy is a
hand-rolled stream rewrite. Only the last justifies acting before there is a
reason to.

**Do not build a compliance program.** No KMS, no per-subject key management,
no blob store, no DSAR workflow, no crypto-shredding.

**Cheap now, mostly impossible later:**

| Action | Cost | Why now |
|---|---|---|
| Pseudonymize identifiers at intake; mapping in a sidecar outside the store | A convention plus one file | **Retroactively impossible.** Once the name is in `UserMessageSent.message`, only a rewrite removes it — and after `remember()`, a rewrite plus consolidation surgery. |
| Route corpus material by reference, not by paste | A habit | A pasted transcript is in the log permanently; a referenced one may never enter it. |
| Treat the `.db` as sensitive — gitignore, no shared backups | Free | The most likely real exposure, trivially prevented. |
| Guard non-loopback binds | ~10 lines | Turns the most likely accident into a deliberate act. |
| Add a `ContentRedacted` event type, even with no emitter | One class | Establishes the vocabulary so presenters are *written* to expect a redacted payload. Retrofitting `presenters.py:151,170` and `app.py:324` later is the expensive part, not the event. |
| Record that snapshots and read models hold copies | A comment | A redaction that misses snapshots leaves plaintext and looks successful. |

**Doors that close on ingest:**

1. Any raw payload in the log is permanent absent a full rewrite — the door
   shuts per document, at ingest, not at some later threshold.
2. `FileEdited` delta encoding compounds: every revision makes per-path
   redaction harder.
3. Every fork multiplies reachability and pins positional indices a rewrite
   must preserve.
4. Redstring consolidation spreads identity — each new document mentioning a
   person adds another `EntitiesMerged` referencing them, with no per-document
   undo.
5. Snapshots accumulate folded plaintext every 50 events.

**If erasure is ever genuinely required**, the sequence is: append
`ContentRedacted` tombstones → offline **in-place** stream rewrite into a fresh
store, preserving event count and order and re-deriving affected `FileEdited`
chains → drop and rebuild snapshots (`snapshots/sqlite.py:315`) →
`rebuild_summaries` (`read_models.py:368`) → `rebuild_graph` (`rebuild.py:38`)
→ `VACUUM` → destroy the old `.db`, WAL and every backup. Assume a day, and
treat browser cursors and checkpoints as expendable.

---

## Part 3 — Drafted backlog entries

Four entries rather than the three guessed at. The split is by *what unblocks
them*, which is what makes them independently pickup-able: the boundary work is
blocked on auth; the intake convention is blocked on nothing but a decision;
the redstring concern has a distinct location and a distinct upstream question;
and the bind guard is small, independent, and the only one actionable today —
keeping it separate stops the cheap fix being buried under the blocked one.

All go under `## Code quality` except where noted. B-numbers left for the lead.

---

### BN. The web app has no user system, so the console cannot be shown to anyone but its author

`research_team/interfaces/web/app.py`. There is no authentication, no
principal, and no RBAC — `create_app` builds the router with no middleware, no
dependency guards and no key, and `/api/docs` is enabled. Every route is
reachable by anything that can open a socket, and the routes serve everything
an author writes.

The surfaces, so this does not have to be rediscovered:

- `GET /api/sessions/{id}` and `/at/{at}` — the **full conversation**
  (`presenters.py:156`), including every tool call's arguments, at HEAD or as
  of any past event.
- `GET /api/sessions/{id}/files?path=&at=` — **full file content** at any point,
  including files deleted at HEAD. The docstring at `app.py:310-312` says that
  is the point of time travel.
- `GET /api/sessions/{id}/files/history?path=` — every revision's full content
  plus `old_string`/`new_string` per edit (`presenters.py:160-180`), and it
  ignores the scrub point.
- `GET /api/sessions/{id}/events` — timeline summaries leaking 30-char edit
  snippets, 120 chars of message content, and every tool name
  (`presenters.py:30-64`).
- `GET /api/stream` — the same rows live with `Last-Event-ID` replay, plus two
  channels that bypass `presenters.py` entirely and `json.dumps` raw
  (`app.py:592-593`): pending approval arguments, and the assistant's reply as
  it streams.
- `GET /api/sessions/{id}/turns/current/activity` — including `discarded`
  content from turns that failed and were rolled back.
- `GET /api/sessions` and `/api/tree` — `first_message` for **every** session in
  the database, on the index page.

There is no export endpoint today; adding one would be a sixteenth surface.

**Deferred because it is blocked on a user system that does not exist, not
because the exposure is acceptable.** Until there is a principal there is no
boundary to enforce, and the tool is single-user on loopback.

**When it is picked up, do not filter the author console.** Three reasons, and
the first is not an effort argument: the agent discusses answers in prose while
authoring, so `AssistantMessageAdded` bodies carry the solutions and are
structurally indistinguishable from messages about formatting — filtering them
means per-message semantic classification with no ground truth, where every
false negative is permanent. Second, `/files/history` is not scrub-scoped and
`/files?at=` takes a client-supplied index, so state-based gating does not
hold. Third, a filter is allow-by-default: every new route leaks until someone
remembers it, and two SSE channels already bypass the layer a filter would live
in.

The console's value *is* total transparency over the log (`app.js:1-8`); a
filter would make it a worse authoring tool and an untrustworthy reader at the
same time. The shape is a second, deny-by-default surface serving an
author-created allowlist of `(path, at_event)` pairs with pinned revisions, on
which `/at/{n}`, `/files/history`, `/events` and the SSE stream simply do not
exist. The cheapest correct version is a static export directory served by a
separate process — zero shared code, therefore zero shared failure modes.

---

### BN. Sensitive material entering the event log cannot be removed, and the cheap decision is at intake

The `EventStore` protocol in `eventsource` 0.5.0
(`eventsource/stores/interface.py`) offers `append_events`, `get_events`,
`get_events_by_type`, `event_exists`, `get_stream_version`, `read_stream`,
`read_all`, `get_global_position` — **no delete, no update, no redact**.
Snapshots, read models and the DLQ are deletable; the log is not.

This matters as soon as real SME interview transcripts, confidential documents
or PII are ingested for course-design work, because everything derived from
them is copied further: `UserMessageSent.message`, `FileWritten.file_data`,
`FileEdited` (which stores the payload **three times** — `file_data`,
`old_string`, `new_string`, `events.py:160-164`), `ToolCallDecided.args`,
`ConversationCompacted.summary`, `SessionSummaryRow.first_message`
(`read_models.py:80`, shown for every session on the index page), and a folded
snapshot of files-plus-conversation every 50 events (`event_store.py:22`).

Of the four standard erasure patterns, **crypto-shredding is specifically
disqualified here**: `FileEdited` is delta-encoded, so a shredded revision
leaves every later revision of that path undefined — the fold cannot apply an
`old_string` that is no longer there. Forgettable payloads are right for
corpus material and wrong for authored files, because a blob store is a second
store that is not derivable and must not be lost, which is precisely the
property `rebuild_summaries` and `rebuild_graph` depend on not needing.
Tombstones record intent but erase nothing. **An in-place stream rewrite is the
only remedy that produces a coherent log**, and it must rewrite rather than
delete, because `SessionForkedFrom.at_event` (`events.py:141`) is a positional
index and dropping events silently re-points every fork in the database.

**Deferred because the threat model does not currently justify machinery:**
local, single-user, loopback, no regulatory obligation. What does not wait is
the intake decision, because it is the only cheap one — every downstream option
costs a hand-rolled rewrite, and one of them is broken outright.

The recommendation, when corpus ingestion starts: **pseudonymize identifiers at
intake** (names, account references → stable tokens) and keep the mapping in a
sidecar file outside the event store. It costs a convention, does not touch the
fold, creates no must-not-lose content store, and deleting the sidecar leaves a
log holding only tokens. It is retroactively impossible — once a name is in
`UserMessageSent.message`, only a rewrite removes it. Prefer routing sensitive
sources by reference over pasting them into a turn, for the same reason.

Two small things worth doing whenever this area is next touched: add a
`ContentRedacted` event type even with no emitter, so presenters are *written*
to expect a redacted payload rather than retrofitted at
`presenters.py:151,170` and `app.py:324`; and note near `SNAPSHOT_THRESHOLD`
that snapshots hold folded plaintext, because a redaction that forgets them
leaves the material behind and looks successful.

---

### BN. Erasing a person from the knowledge graph is not a per-document operation

`research_team/infrastructure/knowledge/redstring_adapter.py`. The graph store
itself is derived and free to discard — `rebuild_graph` (`rebuild.py:38`) folds
it from the log at project open, which is why the default install keeps it in
memory. The material is in redstring's `Document` and `Consolidation` streams,
which live in **the same SQLite file** as session events (`event_store.py:236-238`).

Two properties make removal harder than deleting a document:

- `remember(text, source_id)` (`knowledge_tools.py:81`) passes up to 200,000
  characters to `build_graph`, which extracts entities. A person named once in
  a transcript becomes a node whose label is their name.
- `Consolidator.resolve` then merges that node with mentions from other
  documents and — per the module docstring at `redstring_adapter.py:15-18` —
  **appends its own merge event**. So the identity is aggregated across
  sources, and the association is recorded as an `EntitiesMerged` event
  independent of any single document.

Consequently, deleting one document's events removes neither the entity (if
another document also mentioned them) nor the merge record, and the name likely
survives inside the merge payload. Cost grows with corpus size and there is no
per-document undo.

**Deferred because nothing sensitive has been ingested yet**, which is also why
it is worth recording now: the mitigation is upstream of the problem, not a fix
for it. Intake pseudonymization makes this entry moot — the node is `P-07`, the
merges are over `P-07`, and deleting one sidecar line erases the person while
leaving the graph's structure intact.

Worth an upstream question when redstring is next discussed: whether it offers,
or would consider, any per-document retraction that also unwinds the
consolidations referencing the retracted entities. Today the answer appears to
be no, and `unmerge` (`redstring_adapter.py:166-182`) reverses a merge without
removing anything.

---

### BN. Nothing objects when the web app is told to bind a public interface

`research_team/infrastructure/config.py:57-58`. `web_host()` returns
`AGENT_WEB_HOST` or `127.0.0.1`, and `web.py:39` hands it straight to
`uvicorn.run`. There is no check that the resolved host is loopback and no
warning when it is not — so a single environment variable puts an
unauthenticated API serving full file contents, full conversations and a live
event stream on every interface.

The default is right and the surrounding design is deliberate: this is a local
single-user tool, and `app.py`'s join route already says so. The gap is only
that the one control which exists has no guard around it, and the failure is
silent and total rather than gradual.

**Deferred as small rather than blocked** — unlike the boundary work, this needs
no user system. The fix is a check in `web_host()` or `web.py`: if the resolved
host is not loopback, require a second explicit opt-in variable, and log a
warning naming what is exposed. Worth doing the next time either file is
touched, and worth doing before anyone demos this over a network.
