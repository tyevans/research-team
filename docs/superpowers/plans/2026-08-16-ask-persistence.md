# Ask Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A question asked of a project survives a restart, and can be read back with its answers and citations.

**Architecture:** An `AskConversation` event-sourced aggregate with its own stream per conversation, kept off the live feed by listing it in `UNROUTED_AGGREGATE_TYPES`. `AskService` appends on success where it currently only writes to an in-memory registry; the registry stays in front as a cache. A projection answers "conversations for a project" and "one conversation with its turns".

**Tech Stack:** Python 3.13, `eventsource-py`, SQLAlchemy async, FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-16-ask-persistence-design.md` — **read it before Task 1.** Its central ruling deliberately weakens an existing test, and Task 3 is that change.

## Scope

This plan is the **backend** half: the aggregate, persistence, the projection, the routes, and the restart test. The frontend — a history list, linking to a past answer, resuming a conversation — is a second plan against the same spec. Splitting there is not arbitrary: a persisted conversation readable over HTTP is working, testable software on its own, and the UI needs design work (where history lives in the shell, what a conversation card shows) that this plan does not do.

Explicitly **not** in either half, per the spec: fork and scrub (B49), steering from the chat (B50), topic citations (B52).

## Global Constraints

- **Four gates:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The ruff commands cover the whole repository. This plan touches no frontend code; run `verify` anyway before the final commit, because it is a gate and "should be unaffected" is a prediction.
- **Run `ruff format .` BEFORE committing, not after.** On the previous branch an agent ran it afterwards, reported the gate as passing, and left the formatter's edits uncommitted — the committed state failed CI. Format, stage, commit, then re-check.
- **An event no projection handles counts as APPLIED, not rejected.** A missing projection produces a silently EMPTY read model behind a 200. Every test here asserts on **data** — a row exists, a field carries the value the event held — never that a call returned or a request succeeded.
- **A read-model change verified only against a fresh database is unverified.** `apply_schema` reconciles added columns but leaves them empty on rows that already existed. Task 6 is that check and is not optional.
- `tests/test_architecture.py` is a gate: `research_team/application/` may not import `research_team/infrastructure/`.
- **Commit in a single invocation** with explicit paths: `git add <paths> && git commit -F <file>`. Never `git add -A`. Never bare `git stash` — the stack is shared with every other worktree; use a throwaway WIP commit.
- Comments explain why, not what. Say when something was measured rather than reasoned.
- Prove each test red before trusting it green. If a test would pass with the change reverted, say so in its docstring.
- Pre-release: no backwards compatibility is owed, but a deliberate break is documented in the field's docstring.

---

## Task 1: The `AskConversation` aggregate

**Files:**
- Create: `research_team/domain/ask_conversation.py`
- Modify: `research_team/domain/events.py` (register the new events)
- Test: `tests/domain/test_ask_conversation.py`

**Interfaces:**
- Produces: `AskConversation(DeciderAggregate[...])` with `aggregate_type = "AskConversation"`.
- Commands: `StartAskConversation(conversation_id, project_id, opened_at)`, `RecordAskTurn(conversation_id, question, answer, citations)`.
- Events: `AskConversationStarted(conversation_id, project_id, opened_at)`, `AskTurnRecorded(conversation_id, question, answer, citations)`.

Read `research_team/domain/research_run.py` first — the spec names it the closest existing shape (a short-lived, run-shaped thing with its own id living beside a project) and this should look like its neighbours, not like a new idea.

A pure decider: `initial_state`, `decide`, `evolve`, all static, no I/O.

**Rulings already taken, do not re-litigate:**
- `conversation_id` is a `UUID` **minted by the server**. The spec's reasoning: today's `chat_id` is browser-minted, and the registry's project check is proportionate for a key into a bounded in-memory dict but not for something that becomes an aggregate id, a row key and a URL segment.
- `citations` is a tuple of `(kind, id)` pairs with `kind` currently only `"source"`. Do **not** widen it — B52 is the entry that widens it, and a branch nothing can emit cannot be tested.

**Guards `decide` must make:** `RecordAskTurn` against a conversation that was never started is refused; `StartAskConversation` against one already started is refused. Both with `CommandRejectedError`, as every other aggregate here does.

- [ ] **Step 1: Write the failing tests** — start then record, and the two refusals. Assert on the events `decide` returns and the state `evolve` folds to.
- [ ] **Step 2: Run to verify they fail.** **Step 3: Implement.** **Step 4: Green. Step 5: Commit.**

---

## Task 2: Keep it off the feed, and satisfy the guard

**Files:**
- Modify: `research_team/infrastructure/persistence/event_store.py` (`UNROUTED_AGGREGATE_TYPES`, ~line 71)
- Test: the existing `test_every_aggregate_type_is_routed_or_deliberately_not` should already fail — find it first.

That guard exists because `Topic`, the graph, `Corpus` and `Project` each went a release with a live path that carried nothing, and being *absent* from `FEED_AGGREGATE_TYPES` is not a decision anybody wrote down. A new aggregate type must be in one list or the other or the guard fails.

**Ruling: unrouted.** The argument is `LearnerProgress`'s, and it is exact: the asking client is already receiving its answer through the ask's own stream, so a feed frame would arrive at the one client that does not need telling. Write that reasoning into the docstring beside the others, in their voice — including what it costs (a second tab watching a conversation someone else is having does not repaint) and when to revisit (a history pane left open while another tab asks).

- [ ] **Step 1: Run the guard test and watch it fail** with the new aggregate type in neither list. Paste the output — this is the one task whose red-proof arrives for free.
- [ ] **Step 2:** Add the type to `UNROUTED_AGGREGATE_TYPES` with its paragraph. **Step 3:** Green. **Step 4: Commit.**

---

## Task 3: Rewrite the test that forbade this

**Files:**
- Modify: `tests/integration/test_ask_writes_nothing.py`
- Test: itself

**This task is the spec's central ruling and the one to get exactly right.** Read the spec's "Ruling" section before touching the file.

Both tests currently assert `await application.service._repository.latest_position() == before` — the store's **global** `MAX(global_position)`. That is a proxy. What "ephemeral" bought was that asking a project does not pollute the *project's* record.

Replace the global assertion in **both** tests with:
1. no new events on the **project's own stream**;
2. nothing new in the project's **feed** — `read_since` from the position captured before the ask, asserted empty;
3. the existing content assertions, **kept verbatim** — a generator that yielded nothing would satisfy every position assertion perfectly.

**The docstrings must say what changed and why**, per `CLAUDE.md`'s rule for a deliberate break: that the ask now appends, that it appends only to its own aggregate type, that the guarantee is now about the project's stream and feed rather than the store's global position, and that a write bypassing `eventsource` entirely would not be caught by either form.

Keep `test_the_real_executor_opens_a_graph_and_still_appends_nothing` and its whole reason intact — it is the more valuable of the two, because the strongest candidate for an accidental write is a replay, consolidation or snapshot happening as a side effect of opening the graph.

- [ ] **Step 1:** Rewrite both tests. They should **pass** at this point (nothing appends yet) — say so in the report; this is the one task with no red phase, and Task 4 is what makes them meaningful.
- [ ] **Step 2:** Prove the new assertions bite: temporarily append a `Project` event inside the ask path, confirm the stream/feed assertions fail, revert. Paste the output.
- [ ] **Step 3: Commit.**

---

## Task 4: Persist on a successful ask

**Files:**
- Modify: `research_team/application/ask.py`
- Test: `tests/application/test_ask_persistence.py`

**Interfaces:**
- Consumes: an `AggregateRepository[AskConversation]`, injected — `AskService` may not import infrastructure.
- Produces: `AskService.ask` gains a server-minted conversation id; `AskService` appends `StartAskConversation` on first turn and `RecordAskTurn` per successful turn.

The append goes **exactly where `self._conversations.put(...)` already is** — on success, before the final `yield answer`, and for the reason the existing 14-line comment gives: there is no suspension point between those two statements, and recording after the yield loses an exchange the reader did see. Read that comment before moving anything; it records an experiment already run.

**The registry stays.** It is a cache with a good eviction policy, and reading a conversation back through a projection on every turn of a live chat is the stuttering trade this repository has already refused twice. Its contents become derivable rather than authoritative.

**A failed append fails the ask.** The spec takes this cost explicitly: asking becomes a write, and the in-memory registry could not fail this way. Do not swallow it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_successful_ask_appends_a_turn():
    """Asserts the events on the conversation's own stream, not that ask()
    returned -- an event no projection handles still counts as applied."""


async def test_a_failed_ask_appends_nothing():
    """The executor raises; no conversation is started and no turn recorded."""


async def test_the_conversation_id_is_not_the_browser_s_chat_id():
    """The spec's ruling: a browser-minted string must not become an aggregate
    id. Fails if `chat_id` is threaded straight through."""
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5: Commit.**

---

## Task 5: The projection and its read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_ask_read_model.py`

**Interfaces:**
- Produces: `AskConversationRow` and `AskTurnRow`; an `AskConversationProjection`; a runner with `start`, `caught_up`, `rebuild`, `for_project(project_id)` and `get(conversation_id)`.

Follow `MediaProposalStore`/`MediaProposalRunner` exactly — same shape, same `start` (touch the event store first so `projection_checkpoints` exists), same `rebuild`. Do not invent a new arrangement for the sixth instance of one.

**Turn order is a stored column, not an accident of insertion.** A turn carries its index; `get` returns turns ordered by it. A read that relies on rowid ordering is a read that a rebuild can reorder.

- [ ] **Step 1: Write the failing tests** — a conversation with three turns comes back with all three **in order** and with each turn's citations attached to the turn that produced them; `for_project` does not return another project's conversations; `get` on an unknown id returns `None`.
- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5: Commit.**

---

## Task 6: Wire it, and prove it survives a restart

**Files:**
- Modify: `research_team/composition.py` (build the repository, the runner, start it in `Application.start()`), `research_team/interfaces/web/app.py` (two routes), `web.py` (pass them through)
- Test: `tests/integration/test_ask_survives_a_restart.py`, plus route tests

**This is the task the plan exists for, and the one this codebase has got wrong six times: a component built, tested green, and connected to nothing.** `web.py` carries three separate "was missing — these routes have been 503ing in this entrypoint while the test fixture wired one and passed" comments. Wire the runner in `Application.start()` beside the other projections, and pass the routes' dependencies from `application.*` rather than constructing a second instance at the call site.

Routes: `GET /api/projects/{project_id}/asks` (list) and `GET /api/projects/{project_id}/asks/{conversation_id}` (one, with turns). 404 for an unknown conversation.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_conversation_survives_a_restart():
    """The whole feature. Two applications over one db_path: the first asks,
    the second is the restart. Asserts the turns come back, in order, with
    their citations -- not that start() returned."""
```

Build the crash-shaped fixture the way `tests/integration/test_accept_reconciliation.py` does on the media branch if it is available to you; otherwise two `build_application` calls over one `tmp_path` database.

- [ ] **Step 2: Verify red, and prove the strong form** — with the runner's `start()` call removed from `Application.start()`, the restart test must fail. Paste that output. If it still passes, the projection is not wired and the task is not done.
- [ ] **Step 3: Implement.** **Step 4: Green.**
- [ ] **Step 5: Verify against a database that predates the change.** Copy a real database with `uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db` (it rewrites the store id in each checkpoint, which a plain `cp` does not — a copied database otherwise raises `PositionForeignError` and starts nothing), point the application at it, and confirm the new tables are created and the endpoint answers. **Do not delete the checkpoints to make it start** — that replays the whole log and is `/rebuild` by another name, which hides exactly the half of the bug that matters.
- [ ] **Step 6:** Four gates. **Step 7: Commit.**

---

## Task 7: Close B48, and record what is left

**Files:**
- Modify: `BACKLOG.md`

- [ ] Delete **B48**, per the file's header rule; run `grep -rn "B48" research_team tests frontend` and redirect any citing comment at the spec rather than leaving a dangling handle. **Note that `B48` appears twice in this file** as two different entries (the ask one, and one about `infer_relations`) — read before deleting.
- [ ] **Amend B49** (fork and time travel) to say it is now cheap: the conversation is an event-sourced aggregate, so scrub is a pure fold of a prefix and fork is a new id plus a replay plus one event — the same shape `SessionService.state_at` and `.fork` already have. That is the point of doing it this way and it should be written where the next person will look.
- [ ] Add an entry for the **frontend half** — history list, linking to a past answer, resuming a conversation — naming this plan's backend as done and the UI design as the open work.
- [ ] Add an entry for **the cost this took**: a failed append is now a failed ask, which the in-memory registry could not do. If that turns out to bite, the fallback is a separate store and the aggregate work is not recoverable.
- [ ] **Commit.**

---

## Self-Review

**Spec coverage.** The aggregate → Task 1. Keeping it off the feed → Task 2. The rewritten test, which is the spec's central ruling → Task 3. Server-minted id → Task 1 (shape) and Task 4 (behaviour, with its own test). The registry staying in front → Task 4. The projection and its "assert on data" requirement → Task 5. Restart, wiring, and the predates-the-change database → Task 6. Deferrals → Task 7.

**Gap found while reviewing:** the spec's testing section asks that asking project A leaves project B's feed untouched, and no task listed it. It is now part of Task 3's feed assertion and Task 5's `for_project` test — both are needed, because the feed could be correctly scoped while the read model was not.

**Second gap:** the spec says turns come back in order, and nothing made ordering a stored fact. Task 5 now requires an explicit index column, because a read that leans on insertion order is a read a rebuild can reorder — and a rebuild is a supported operation here.

**Known thin spot:** Task 6 does four things (compose, route, restart-test, old-database check) where earlier tasks do one. They are one deliverable — a route that works against a real database — and splitting them would produce a task whose test cannot fail. An executor should expand the steps rather than read the brevity as permission to skip the Step 5 check, which is the one most easily dropped and the one `CLAUDE.md` has a whole section about.
