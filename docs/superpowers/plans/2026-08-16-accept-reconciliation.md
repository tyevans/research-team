# Accept Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A media proposal accepted before a crash is downloaded and stored on the next start, instead of staying `accepted` forever.

**Architecture:** One new read (`accepted proposals, all projects`), one new application service that loops the existing `MediaAcceptWorker` over them, and one call in `Application.start()` after the projection has caught up. No new events, no new column, no change to the worker.

**Tech Stack:** Python 3.13, `eventsource-py`, SQLAlchemy async, FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md` — read it before Task 1. It is short and every ruling in it is load-bearing.

## Global Constraints

- **Four gates:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The ruff commands cover the whole repository. This plan touches no frontend code, so `verify` should be unaffected — run it anyway before the final commit, because it is a gate and "should be unaffected" is a prediction.
- **`tests/test_architecture.py` is a real gate.** `research_team/application/` may not import `research_team/infrastructure/`. The new service defines a `Protocol` port; the runner satisfies it structurally, as `MediaProposalReadPort` already does.
- **Never use bare `git stash` / `git stash pop`** — the stash stack is shared with every other worktree. Use a throwaway WIP commit.
- **Commit in a single invocation** with explicit paths: `git add <paths> && git commit -F <file>`. Never `git add -A`.
- Comments explain why, not what. Say when something was measured rather than reasoned.
- Prove each test red before trusting it green. If a test would pass with the change reverted, say so in its docstring.
- **An event no projection handles counts as APPLIED, not rejected.** An assertion that "start() succeeded" is worthless as a test of this feature; assert on the *data* — a source row exists, the proposal's status changed.

---

## Task 1: The read — accepted proposals, across all projects

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (`MediaProposalStore` and `MediaProposalRunner`, near `get_by_proposal_id` at ~2693 and `get` at ~2802)
- Test: `tests/infrastructure/test_media_proposal_reads.py` (or the existing file that covers `MediaProposalStore` — find it first with `grep -rln MediaProposalStore tests/`)

**Interfaces:**
- Produces: `MediaProposalStore.accepted() -> list[MediaProposalRow]` and `MediaProposalRunner.accepted_proposal_ids() -> list[str]`.

Every other read on this store is scoped to one project. **This one is not, deliberately:** reconciliation runs once per process, before anything has asked about a particular project, and an accepted proposal in a project nobody opens this session is exactly the one most likely to have been abandoned. Say that in the method's docstring.

Order the results — by `proposal_id` is enough. An unordered read makes the reconciler's own test order-dependent for no benefit.

- [ ] **Step 1: Write the failing tests.** Three rows: one `accepted`, one `stored`, one `failed`, at least two of them in *different projects*. Assert the read returns exactly the accepted one, and assert the cross-project case explicitly — a `WHERE project_id = ?` that crept in would otherwise pass.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Follow `for_project`'s shape exactly.
- [ ] **Step 4: Green. Step 5: Commit.**

---

## Task 2: `caught_up` on the media-proposal runner

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (`MediaProposalRunner`)
- Test: alongside Task 1's

**Interfaces:**
- Produces: `MediaProposalRunner.caught_up(timeout: float = 10.0) -> None`

The runner does not have one; `SessionSummaryRunner`, and the runners at lines ~1367, ~1739 and ~2253 all do. **Copy the nearest one's implementation and its reasoning, including the timeout default** — do not invent a new shape for a method that exists four times.

The spec requires reconciliation to run after the projection has *caught up*, not merely started: a projection mid-replay under-reports the accepted set and there is no second pass.

- [ ] **Step 1: Write the failing test** — append a `MediaProposed`/`MediaProposalAccepted` pair, `await runner.caught_up()`, and assert the row is readable immediately after, with no sleep. **A `sleep` in this test's arrange phase makes it worthless** (`BACKLOG.md` B4 is the entry about a test that did exactly that for months).
- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5: Commit.**

---

## Task 3: The reconciler

**Files:**
- Modify: `research_team/application/media_acquisition.py` (beside `MediaAcceptWorker`)
- Test: `tests/application/test_media_acquisition.py`

**Interfaces:**
- Consumes: `MediaAcceptWorker.run(proposal_id: str) -> None`, unchanged.
- Produces:

```python
class AcceptedProposalListPort(Protocol):
    """The accepted-but-unfinished set, across every project."""

    async def accepted_proposal_ids(self) -> list[str]: ...


class MediaAcceptReconciler:
    def __init__(self, *, reads: AcceptedProposalListPort, worker: MediaAcceptWorker) -> None: ...
    async def run(self) -> None: ...
```

`run` loops the ids sequentially, calling `worker.run(id)` on each inside a
`try/except Exception`, logging the proposal id and continuing. **Nothing
propagates out of `run`** — the spec's reasoning is that a reconciliation which
raised would turn "one asset's host is gone" into "this install does not boot",
which is worse than the defect being fixed. Put that sentence in the docstring.

Do not re-derive re-run safety here. `MediaAcceptWorker`'s docstring already
argues it (content-addressed blobs; an already-`stored` refusal read back as the
worker's own success signal) — cross-reference it rather than restating it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_every_accepted_proposal_is_re_run():
    ...
    assert worker.calls == ["p1", "p2"]


async def test_one_proposal_failing_does_not_abandon_the_rest():
    """The reconciler must be total. Fails if the `except` is removed: the
    first raise would end the loop and `p2` would never be attempted."""
    worker.raise_on = "p1"
    await reconciler.run()
    assert worker.calls == ["p1", "p2"]


async def test_nothing_accepted_is_not_an_error():
    ...
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5: Commit.**

---

## Task 4: Wire it into `Application.start()` — the task the whole plan exists for

**Files:**
- Modify: `research_team/composition.py` (`Application` dataclass, `Application.start` at ~512, and the construction site near `media_accept_worker` at ~1792)
- Test: a composed-application test — find where `build_application` is exercised (`grep -rln build_application tests/`) and add there.

**Interfaces:**
- Produces: `Application.reconciled() -> None` — awaits the reconciliation task, mirroring `Application.summaries_caught_up()`.

The spec's central ruling: this hangs in `Application.start()`, **not** in
`web.py`'s lifespan. `web.py` carries three separate "was missing — these routes
have been 503ing in this entrypoint while the test fixture wired one and passed"
comments, and `tests/interfaces/test_web_entrypoint.py` exists because that
happened three times. A reconciler wired at that call site would be the fourth,
and worse: **a reconciliation that never ran and one that found nothing to do
render identically.**

In `start()`, after `await self.media_proposals.start()`:
1. `await self.media_proposals.caught_up()`
2. schedule the reconciler's `run()` with `asyncio.create_task` and **hold the
   task reference on the `Application`** — `create_task` only weakly holds its
   task, a point `app.py` already makes above `create_app`'s body.

`reconciled()` awaits that task (and returns immediately if there is none).
Scheduled rather than awaited inline because an abandoned download is a
download: re-fetching an hour of video must not hold the port closed.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_accepted_proposal_is_reconciled_when_the_application_starts():
    """The test the three `web.py` gaps would have been caught by. Asserts
    against a composed application, not a hand-wired reconciler -- it must
    fail if the call in `Application.start` is deleted, which a test that
    built its own `MediaAcceptReconciler` would not."""
    # Append MediaProposed + MediaProposalAccepted, with a mock transport
    # serving the asset. Then:
    await application.start()
    await application.reconciled()
    # Assert on the DATA: a source now exists for that proposal id, and the
    # proposal's status is `stored`. Not that start() returned.


async def test_a_stored_proposal_is_not_re_run():
    """Asserts the worker was NOT called, not merely that the end state is
    unchanged -- which is true either way and so proves nothing."""
```

Use an `httpx.MockTransport` through `build_application`'s `media_http_client`
parameter. **`build_application` promises no network by default** and
`BACKLOG.md` B92 is the entry about a composed test that broke that promise —
do not add a second.

- [ ] **Step 2:** Verify red, **and prove the strong form**: with the new call in `start()` deleted, `test_an_accepted_proposal_is_reconciled_when_the_application_starts` must fail. Paste that output.
- [ ] **Step 3:** Implement. **Step 4:** Green. **Step 5: Commit.**

---

## Task 5: Close B97

**Files:**
- Modify: `BACKLOG.md`

- [ ] Delete B97, per the file's own header rule ("Closed entries are deleted; if tracked code cites one by name, say where its reasoning went before deleting").
- [ ] **`CorpusEditor._store_derived`'s comment cross-references B93, not B97 — check anyway.** Run `grep -rn "B97" research_team tests frontend` and, for every hit, redirect it at the spec rather than leaving a dangling handle.
- [ ] Add a `BACKLOG.md` entry for what the spec explicitly deferred: **no periodic sweep during a long-lived process.** A task that dies while the process survives waits for the next restart. Record that it needs an interval, a jitter policy, and a story about two processes sweeping at once — none of which the crash case needs.
- [ ] **Commit.**

---

## Self-Review

**Spec coverage.** The read → Task 1. "After caught_up, not merely started" → Task 2 provides the method, Task 4 calls it. Sequential, total, non-raising → Task 3. Where it hangs, the task reference, and the awaitable seam for tests → Task 4. The deferrals → Task 5.

**Gap found while reviewing:** the spec's testing section requires that a `stored` proposal is not re-run *and that the assertion is about the worker not being called*. Task 1 tests the read excludes it and Task 4 tests the worker is not called — both are needed, because the read could be right while the reconciler ignored it, or the reverse.

**Known thin spot:** Task 4's test needs a composed application with a mock transport and two appended events, which is the heaviest fixture in this plan. If an existing composed test already has that scaffolding, extend it rather than building a second — and say which you did.
