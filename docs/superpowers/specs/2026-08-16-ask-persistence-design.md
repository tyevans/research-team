# Persisting an ask

A reader asks the corpus a question, gets a good answer, and closes the tab. The
answer is gone. They cannot come back to it, cannot link to it, and cannot see
what anyone else asked. The conversation lived in an in-memory `OrderedDict`
keyed by a browser-minted chat id (`application/ask.py:64-112`), bounded to 64
conversations and an hour idle, and dropped on eviction, on `forget`, or on
restart.

This is `BACKLOG.md` B48, and B49 (no forking, no time travel over an ask) is
downstream of it.

## The objection that blocked this, and why it does not survive contact

B48 records the design's reason for refusing the obvious home:

> Events are the obvious home and the one the design refused: appending them
> moves the project's tip, which is what "ephemeral" was bought with, and
> `tests/integration/test_ask_writes_nothing.py` fails the moment anything on
> that path appends.

Both halves are true and the conclusion does not follow.

**The tip is store-global, so choosing a different aggregate type buys nothing.**
`latest_position()` (`infrastructure/persistence/event_store.py:468-469`) is a
bare passthrough to the adapter's `current_position()`, which is
`SELECT MAX(global_position) FROM events` over the whole table. Streams are
scoped per `(aggregate_type, aggregate_id)`; the counter the test reads is not.
An `AskConversation` aggregate with its own id would move it exactly as a
`Session` does. **There is no free pass here and the design was right to say so.**

**But the global tip is a proxy, and the thing it stands for is already
achievable.** What "ephemeral" actually bought was that *asking a project does
not pollute the project's record* — its stream, its feed, its history. That
property has a mechanism in this codebase already, it is tested, and it is in
production use: `read_since` (`event_store.py:471-485`) is scoped by aggregate
type, admitting `FEED_AGGREGATE_TYPES` and holding back
`UNROUTED_AGGREGATE_TYPES`, with a test that a type in **neither** list fails.
`ResearchRun` and `LearnerProgress` are already aggregates whose events exist in
the same table and never reach a project feed.

So the question is not "events or a separate store". It is **which assertion is
the real one** — and `test_ask_writes_nothing.py` currently asserts the proxy.

## Ruling: events, on their own aggregate, and the test is rewritten

An `AskConversation` aggregate, its own stream per conversation, listed in
`UNROUTED_AGGREGATE_TYPES`.

`tests/integration/test_ask_writes_nothing.py` is **rewritten, not deleted**, to
assert the property that was actually being bought:

1. no events on the **project's** stream;
2. nothing new in the project's **feed** (`read_since` from the prior position);
3. the ask still yields its answer — the existing second-half assertion, kept
   verbatim, because a generator that yielded nothing would satisfy every
   position assertion perfectly.

**This is a deliberate weakening of a test and it is recorded as one.** The old
assertion was strictly stronger and cheap to keep; what it cost is this feature,
and the entry asking for this feature is in the repository. `CLAUDE.md`'s rule
for a deliberate break applies: say so in the docstring, say what no longer
holds, and assert the replacement rather than deleting the case. The docstring
must state plainly that the ask now appends, that it appends only to its own
aggregate type, and that the guarantee is now about the project's stream and
feed rather than about the store's global position.

The second test in that file —
`test_the_real_executor_opens_a_graph_and_still_appends_nothing` — is the more
valuable of the two and its *reason* survives intact: the strongest candidate
for an accidental write is a replay, consolidation or snapshot happening as a
side effect of opening the graph. That test keeps its shape and moves to the
same stream/feed-scoped assertions.

**Cost if this ruling is wrong:** asking a project becomes a write, and a write
that fails is a failed ask. The registry never had that failure mode. If the
event log turns out to be too heavy for a surface people use conversationally,
the fallback is a separate store — and the work spent on the aggregate is not
recoverable. Taken because the alternative owes an answer B48 already names
("why the project's own log is not the record of what was asked of it") and
because fork and scrub, below, are otherwise built twice.

## What this unlocks, and why it is the same design

`Session` is a pure decider. Scrub is `SessionService.state_at()` — a pure fold
of a history prefix, no writes. Fork is `SessionService.fork()` — a new
aggregate id, the events replayed onto it, and a `SessionForkedFrom` appended.

B49 wants exactly those two operations over an ask. On an event-sourced
`AskConversation` they are the same code shape as `Session`'s and cost a fold
and an append. On a bespoke store they are reimplemented from nothing. **That
is the strongest argument for this ruling and it is B49's own.**

B49 is not built here. This spec makes it cheap; it does not spend it.

## Shape

- **`AskConversation`** in `research_team/domain/`, a `DeciderAggregate`
  alongside `ResearchRun`, `Topic` and `LearnerProgress` — the codebase already
  has side aggregates with their own lifecycles and this is one more.
- **Events**: a conversation started against a project; a question asked; an
  answer recorded with its citations. Named and shaped in the plan, not here.
- **A projection** for the read side: list conversations for a project, read one
  back with its turns. **A missing projection is a silently EMPTY read model
  behind a 200**, not a refusal (`CLAUDE.md`, and `eventsource.replay`'s own
  docstring) — so its tests assert that a row exists and carries the value the
  event held, never that the request succeeded.
- **The conversation id is minted by the server, not the browser.** Today's
  `chat_id` comes from the browser (`ConversationRegistry.get` checks the
  project it was opened under "rather than trusting it, which is also what a
  guessed id deserves"). That check is adequate for a key into a bounded
  in-memory dict and is *not* adequate once the same string is an aggregate id,
  a row key and a URL segment — the identical hazard as letting a model pick an
  id, which this codebase has already ruled against once. The server mints a
  UUID on first use and returns it; the browser's string, if any, becomes a
  client-side label and never reaches storage.

- **`ConversationRegistry` stays**, in front. It is a cache with a good eviction
  policy, and reading a conversation back through a projection on every turn of
  a live chat is the stuttering-log trade this repository has already made twice
  in the other direction. The registry's contents become derivable rather than
  authoritative.

## What this does not do

- **No fork, no scrub.** B49 stays open, cheaper. Say so in its entry.
- **No steering from the chat** (B50). Writing to a project means joining it and
  joining takes exclusive hold; that is a different design and B50 already says
  the narrow-write-path question is the actual work.
- **No topic citations** (B52). `Citation.kind` stays `Literal["source"]` until a
  genuinely read-only topic reader exists. Independent of this spec.
- **No migration.** Pre-release; conversations in memory at deploy are lost, and
  that is what happens to them on every restart today.

## Testing

- The three rewritten assertions above, with the deliberate-weakening docstring.
- A conversation survives a **restart**: append through the service, build a
  fresh application over the same database, read the conversation back. This is
  the whole feature, and it is the test that fails if the projection is never
  constructed — which is the failure mode this codebase has shipped six times.
- Asking project A leaves project B's feed untouched.
- A conversation's turns come back **in order**, and the citations come back
  attached to the turn that produced them.
- **Against a database that predates the change.** `CLAUDE.md`: a read-model
  change verified only against a fresh database is unverified, and `apply_schema`
  reconciles added columns but leaves them empty on rows already there.
