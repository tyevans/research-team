# Ask the project: an ephemeral chat over gathered material

A third project page, beside Course and Research, for asking questions about
what a project has gathered. It answers from the corpus, the knowledge graph,
the topic queue and the project's files, and it writes nothing.

## Why this is not a session

Everything the agent does today runs through `Session` -> `TurnSupervisor` ->
`SessionService`, and `SessionStarted.project_id` is required, so a session
cannot exist outside a project. Joining a project is not free: `start_in_project`
forks the previous holder's filesystem, advances the tip when the session
finishes, and takes exclusive hold -- one session holds a project at a time, by
construction.

An asking surface wants none of that. It does not write files, so it does not
need a filesystem lineage; it must not block or be blocked by the session
holding the project; and its conversations are worth less than the storage they
would occupy. Building it on `Session` would mean fighting those invariants
rather than using them.

So this is a parallel path: a new `AskService` beside `SessionService`, sharing
the composition root's project tooling and nothing else.

**Rejected: an in-memory event store.** Running a real `Session` against a
`:memory:` SQLite log would inherit transcript rendering, the activity buffer
and approvals for nearly no code. It also inherits project joining and tip
advancement, which are exactly the behaviours that make it wrong. Cheaper to
write, considerably more expensive to be correct.

**Rejected: frames on the shared `/api/stream`.** Extraction, seeding and
dispatch all multiplex onto the app-wide stream, so the precedent exists. But
those are background processes a browser discovers after the fact, and need
catch-up-over-REST for that reason. An answer is the response to a request the
browser just made. Multiplexing it would add frame addressing and a catch-up
endpoint to solve a problem this request does not have.

## Contract

The conversation is **ephemeral and server-held**. The server keeps the message
list in memory keyed by a chat id, so follow-ups work within a tab. A server
restart loses every conversation. That is the contract, not a defect, and the
page says so rather than pretending otherwise.

The agent is **read-only**. It cannot write files, mutate the knowledge graph,
record findings against topics, or reach the network.

## Backend

`research_team/application/ask.py`, a peer of `session_service.py` and not a
caller of it.

- `Conversation` -- chat id, project id, message list, last-used stamp.
- `ConversationRegistry` -- bounded map with idle TTL eviction: 64
  conversations, 60 minutes idle, least-recently-used evicted first. Purely in
  memory. Bounded so a long-lived server cannot accumulate conversations
  without limit; the numbers are guesses at a single-user console's shape, not
  measurements, and are cheap to change.
- `AskService.ask(project_id, chat_id, question)` -- async iterator of ask
  events.

### The tool set is the security boundary

Built by subtraction, not by enumeration, so that a tool added to the project
set later is excluded until someone deliberately admits it.

`composition.open_graph(project_id)` already assembles the project-bound tools.
The ask path keeps only the readers:

- `graph_search`
- `list_sources`, `read_source`
- `list_topics`, `open_topic`

and drops every mutator: `remember`, `remember_page`, `unmerge`,
`record_finding`, `record_gap`, `link_source`.

The deep agent's built-in file tools are backed by a **read-only backend** over
`SessionService.project_files`: list and read succeed, write/edit/delete raise.
They raise rather than no-op so that a prompt attempting a write fails visibly
in a test instead of appearing to succeed.

No subagents and no `task` tool -- this is single-agent by choice. `fetch` and
`web_search` are absent from the set entirely, which also means the approval-gate
machinery (`interrupt_config`, `AutonomyPolicy`) has nothing to gate and is not
wired in.

### What pins the claim

Two assertions carry the design, in the style of `test_no_network.py`:

1. A full ask against a project leaves the event store's latest position
   unchanged.
2. The tool names registered for an ask are exactly the read-only set above.

The second fails if anyone adds a mutating tool to `open_graph` without
revisiting this page. That is the intent.

### Streaming

`POST /api/projects/{project_id}/ask`, body `{chat_id, question}`, returns a
`StreamingResponse` of `text/event-stream` scoped to that one question:

- token deltas as the answer is produced,
- tool start and tool result events,
- a terminal event carrying citations.

Wire shapes come from `to_activity_delta` / `to_activity_message` in
`infrastructure/agent/deep_agent.py`, so the frontend parses shapes it already
knows.

One in-flight ask per chat id; a second returns 409. Closing the connection
cancels the task. `DELETE /api/projects/{project_id}/ask/{chat_id}` drops a
conversation, backing a "new chat" control.

### Citations are derived, not claimed

The service records what the tools actually returned during the turn -- source
ids from `read_source`, entity ids from `graph_search`, topic ids from
`open_topic` -- and emits that set as the citations. Prose is never parsed for
references.

The agent therefore cannot cite a document it did not open, because a citation
originates in the read rather than in the sentence. A confabulated title in the
answer text has no citation behind it, which is a visible difference.

## Frontend

`'ask'` joins `FACETS` in `presentation/routing/routes.ts`, giving
`#/p/<id>/ask` and href building without further work. `App.tsx` branches the
facet to `AskView` ahead of the existing Course/Research split. The page link
goes in the `.view-head-actions` row that already carries the Research <-> Course
links, so a third page does not invent a fourth navigation pattern.

Layered as the rest of the app is:

- `domain/ask/conversation.ts` -- pure. `AskMessage`, `AskTurn`, and
  `applyEvent(transcript, event)` folding stream events into a transcript. No
  React, no fetch. Streaming order is the part that goes subtly wrong, so this
  is where the interesting tests live.
- `application/ask/ask-store.ts` -- `createAskStore({ask, projectId})`, a
  zustand factory shaped like `graph-store.ts`: transcript, streaming flag,
  error, `send`, `reset`.
- `infrastructure/http/ask-repository.ts` -- the one genuinely new piece of
  infrastructure. `EventSource` cannot issue a POST, so this reads the `fetch`
  response body as a stream and parses SSE frames itself, validating each
  through zod DTOs as every other wire boundary here does.
- `presentation/ask/` -- `AskView`, `AskThread`, `AskComposer`, `CitationList`.
  Tool activity renders collapsed by default, as `Segments.tsx` collapses
  consecutive tool machinery. Citations link into the existing document and
  entity pages, so the page ends where the material already lives instead of
  duplicating it.

### Reuse deliberately declined

`Conversation.tsx` and `Composer.tsx` are bound to `session-store`'s
`TurnState`, to scrubbing, and to fork affordances. Bending them to serve an
ephemeral chat would carry session concepts into a page whose purpose is not
being a session. New, smaller components instead. The cost is some visual
duplication between the two transcripts, accepted in exchange for keeping the
two pages uncoupled.

## Verification

All four gates: `ruff check`, `ruff format --check`, `pytest`, and
`npm run verify`.

jsdom tests cover the transcript fold, the store and the view. The browser suite
is run only if a stylesheet, a layout primitive, or anything whose correctness is
a computed style gets touched -- and if that happens it is stated rather than
assumed away.

No read-model or projection changes, so the
verify-against-an-existing-database rule does not apply here. No event shape
changes, so schema evolution is untouched. Both are consequences of the page
persisting nothing.

## Deliberately not built

- Persistence, history, resumption of past chats.
- Forking or time travel over an ask.
- Directing project work from the chat (seeding topics, dispatching research).
- Subagent fan-out for wide questions.

Each is a separate decision, and each would be a reason to revisit whether this
should have been a session after all.
