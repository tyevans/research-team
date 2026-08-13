# Turn Activity Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `TurnActivity`'s begin/settle lifecycle out of the HTTP route and into `TurnSupervisor.run`, so every turn buffers and streams its provisional content regardless of who started it — including auto-research rounds, which today show as running with no live output.

**Architecture:** The application layer declares a `TurnActivityBuffer` protocol; `TurnSupervisor` takes an optional implementation and drives `begin` / `reporter` / `settle` itself, settling from a done-callback on the turn's task rather than from the awaiter's `finally`. `TurnActivity` stays in `interfaces/web` and satisfies the protocol structurally, exactly as `WebApprovals` satisfies `ApprovalPort`.

**Tech Stack:** Python 3.12+, asyncio, FastAPI, pytest (`uv run pytest`), ruff.

**Spec:** `docs/superpowers/specs/2026-08-12-turn-activity-ownership-design.md`

## Global Constraints

- **Clean breaks, no shims.** `TurnSupervisor.run` loses its `on_activity` parameter outright. No default passthrough, no deprecation path, no compatibility wrapper. The project is pre-release; a caller that passed one is updated, not accommodated.
- **Four verification gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository. This change touches no frontend source, so `npm run verify` is expected to pass untouched — run it once at the end anyway.
- **Layer rule is enforced by `tests/test_architecture.py`:** `application` may not import from `interfaces`. The protocol lives in `application/ports.py`; the implementation stays in `interfaces/web/activity.py`. Never import `TurnActivity` from application code.
- **Comment standard:** comments explain *why*, not *what*; they name what a test would fail on. A comment restating the code is worse than none. Commit messages carry what was considered and rejected.
- **Test naming:** full-sentence function names in the style already in these files (`test_a_turn_runs_and_reports_where_it_landed`).
- **Prove tests red before trusting them green.** Every task below has an explicit "run it and watch it fail" step with the expected failure text.

---

### Task 1: The port and the supervisor's ownership of the lifecycle

**Files:**
- Modify: `research_team/application/ports.py` (add `TurnActivityBuffer` after the `ActivityReporter` alias, around line 247)
- Modify: `research_team/application/turn_supervisor.py` (constructor, `run`, new `_settle`)
- Modify: `research_team/application/__init__.py` (export `TurnActivityBuffer` if that module re-exports port types — check how `ActivityReporter` is handled and match it)
- Test: `tests/application/test_turn_supervisor.py` (new section at the end)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `research_team.application.ports.TurnActivityBuffer` — Protocol with `begin(session_id: UUID) -> None`, `reporter(session_id: UUID) -> ActivityReporter`, `settle(session_id: UUID, *, committed: bool) -> None`.
  - `TurnSupervisor.__init__(service, *, activity: TurnActivityBuffer | None = None, settle_timeout: float = CANCEL_SETTLE_TIMEOUT)` — note `activity` is keyword-only and precedes nothing positional.
  - `TurnSupervisor.run(session_id: UUID, user_input: str) -> TurnOutcome` — **two positional parameters only**. Task 2 relies on this signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/application/test_turn_supervisor.py`. The recording buffer goes near the top of the new section:

```python
# ---------------- the activity buffer ----------------


class RecordingBuffer:
    """A `TurnActivityBuffer` that remembers what the supervisor did to it.

    A fake rather than the real `TurnActivity`: what these tests are about is
    the *order and count* of begin/settle against a turn's lifetime, and the
    real buffer answers that only indirectly, through content a fake model may
    or may not produce.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def begin(self, session_id: UUID) -> None:
        self.calls.append(("begin", session_id))

    def reporter(self, session_id: UUID):
        self.calls.append(("reporter", session_id))
        return lambda note: None

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        self.calls.append(("settle", committed))

    @property
    def settlements(self) -> list[bool]:
        return [committed for name, committed in self.calls if name == "settle"]


async def test_a_turn_opens_a_buffer_and_settles_it_as_committed(build_service, fake_model):
    service = await build_service(model=fake_model)
    buffer = RecordingBuffer()
    supervisor = TurnSupervisor(service, activity=buffer)
    session_id = await start_session(service)

    await supervisor.run(session_id, "hello")

    assert buffer.calls[0] == ("begin", session_id)
    assert buffer.settlements == [True]


async def test_a_turn_that_fails_settles_its_buffer_as_uncommitted(build_service, failing_model):
    service = await build_service(model=failing_model)
    buffer = RecordingBuffer()
    supervisor = TurnSupervisor(service, activity=buffer)
    session_id = await start_session(service)

    with pytest.raises(Exception):
        await supervisor.run(session_id, "hello")

    # Nothing reached the log, so what streamed is the only trace of this turn
    # and the UI offers it as explicitly discarded.
    assert buffer.settlements == [False]


async def test_a_refused_second_turn_leaves_the_running_turns_buffer_alone(
    build_service, slow_model
):
    """The loser of the race must not touch a buffer belonging to the winner.

    This is why `begin` lives *inside* the `is_running` guard. With it outside,
    the second request would reopen the first turn's buffer -- dropping
    everything streamed so far -- and this asserts exactly one `begin`.
    """
    service = await build_service(model=slow_model)
    buffer = RecordingBuffer()
    supervisor = TurnSupervisor(service, activity=buffer)
    session_id = await start_session(service)

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await once_inside_the_model(slow_model)
    with pytest.raises(TurnAlreadyRunning):
        await supervisor.run(session_id, "second")

    assert [name for name, _ in buffer.calls].count("begin") == 1
    assert buffer.settlements == []

    await supervisor.cancel(session_id)
    with pytest.raises((TurnCancelled, asyncio.CancelledError)):
        await running


async def test_a_cancelled_turn_settles_its_buffer_as_uncommitted(build_service, slow_model):
    service = await build_service(model=slow_model)
    buffer = RecordingBuffer()
    supervisor = TurnSupervisor(service, activity=buffer)
    session_id = await start_session(service)

    running = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await once_inside_the_model(slow_model)
    await supervisor.cancel(session_id)
    with pytest.raises((TurnCancelled, asyncio.CancelledError)):
        await running

    assert buffer.settlements == [False]


async def test_an_awaiter_going_away_settles_nothing_until_the_turn_itself_ends(
    build_service, slow_model
):
    """The buffer's lifetime is the turn's, not the awaiter's.

    `run` shields the turn precisely so a browser tab closing does not throw
    away half a minute of model time. Settling from the awaiter's unwind --
    which is what the HTTP route used to do -- files a *live* turn's content as
    a failed turn's discards, and the next note then reopens a second buffer
    that nothing will ever settle.

    Fails against the previous design: the assertion below that no settlement
    has happened yet is the one that catches it.
    """
    service = await build_service(model=slow_model)
    buffer = RecordingBuffer()
    supervisor = TurnSupervisor(service, activity=buffer)
    session_id = await start_session(service)

    awaiting = asyncio.create_task(supervisor.run(session_id, "slow one"))
    await once_inside_the_model(slow_model)
    awaiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await awaiting

    # The awaiter is gone; the turn is not.
    assert buffer.settlements == []
    assert supervisor.is_running(session_id)

    await supervisor.cancel(session_id)
    assert buffer.settlements == [False]


async def test_a_supervisor_without_a_buffer_still_runs_turns(fast_supervisor):
    """`activity=None` is the REPL's case and most tests'; it must be inert."""
    supervisor, service = fast_supervisor
    session_id = await start_session(service)

    outcome = await supervisor.run(session_id, "hello")

    assert outcome.reply == "done"
```

Two fixtures these need may not exist yet in this file:

- `slow_model` **does** exist (module fixture returning `SlowModel`), as do `once_inside_the_model` and `start_session`. Reuse them; do not redefine.
- `failing_model` — check whether the file or `tests/conftest.py` already provides a model that raises. If neither does, add this fixture next to `slow_model`:

```python
class BrokenModel(ToolAwareFakeChatModel):
    """A model that fails inside the turn, so the turn fails."""

    async def _agenerate(self, *args: Any, **kwargs: Any):
        raise RuntimeError("the model fell over")


@pytest.fixture
def failing_model() -> BrokenModel:
    return BrokenModel(responses=[AIMessage(content="unused", id="b1")])
```

Add `from uuid import UUID` to the imports at the top of the test file if it is not already there.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/application/test_turn_supervisor.py -k "buffer or awaiter" -v`

Expected: every new test fails with `TypeError: TurnSupervisor.__init__() got an unexpected keyword argument 'activity'`.

- [ ] **Step 3: Add the port**

In `research_team/application/ports.py`, directly after the `ActivityReporter` alias and its docstring (around line 247), add:

```python
class TurnActivityBuffer(Protocol):
    """Holds a turn's provisional content for as long as the turn lasts.

    Three methods rather than the whole of `TurnActivity`, and the omission is
    the point: the application drives a buffer and never reads one back.
    `current` and `discarded` are answered to an HTTP caller catching up, so
    declaring them here would describe a coupling that does not exist.

    Implemented by `interfaces/web/activity.py`. The supervisor owns the
    lifecycle because a turn's buffer lives exactly as long as the turn, and
    the supervisor is the only thing that knows that span -- an HTTP request
    awaiting a turn can go away while the turn runs on.
    """

    def begin(self, session_id: UUID) -> None:
        """Open a buffer for a turn about to start, dropping the last one's."""

    def reporter(self, session_id: UUID) -> ActivityReporter:
        """The reporter this turn's notes should be sent to."""

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        """Close the buffer. A committed turn's content is on the log and is
        dropped; an uncommitted turn's is all that survives it, and is kept
        aside as discarded."""
```

- [ ] **Step 4: Give the supervisor the lifecycle**

In `research_team/application/turn_supervisor.py`:

Import the port alongside `ActivityReporter`:

```python
from research_team.application.ports import ActivityReporter, TurnActivityBuffer
```

(`ActivityReporter` remains imported — it is the reporter's type in `_settle`'s neighbourhood and in `run`. If ruff reports it unused after the edit, remove it.)

Constructor:

```python
    def __init__(
        self,
        service: SessionService,
        *,
        activity: TurnActivityBuffer | None = None,
        settle_timeout: float = CANCEL_SETTLE_TIMEOUT,
    ) -> None:
        self._service = service
        self._activity = activity
        self._settle_timeout = settle_timeout
        self._running: dict[UUID, asyncio.Task[TurnOutcome]] = {}
        self._started: dict[UUID, RunningTurn] = {}
```

Replace `run`'s signature and opening (keep the rest of the method — the `try/except asyncio.CancelledError/finally` block — exactly as it is):

```python
    async def run(self, session_id: UUID, user_input: str) -> TurnOutcome:
        """Run one turn, refusing to start a second on the same session.

        The turn runs as its own task so that cancelling it cancels the turn
        rather than whoever happens to be awaiting it -- an HTTP client that
        disconnects mid-turn must not silently abandon work the log will still
        record.

        The activity buffer opens here rather than in the caller, and it opens
        *after* the guard above: a caller that loses the race never touches a
        buffer belonging to the turn that won. It closes from a done-callback
        on the task for the same reason the turn is shielded -- the awaiter's
        fate is not the turn's, and settling on the awaiter's unwind files a
        live turn's content as a failed one's.
        """
        if self.is_running(session_id):
            raise TurnAlreadyRunning(session_id)

        session = await self._service.load(session_id)
        reporter: ActivityReporter | None = None
        if self._activity is not None:
            self._activity.begin(session_id)
            reporter = self._activity.reporter(session_id)
        task = asyncio.ensure_future(
            self._service.run_turn(session_id, user_input, reporter)
        )
        if self._activity is not None:
            task.add_done_callback(self._settle(session_id))
        self._running[session_id] = task
        self._started[session_id] = RunningTurn(
            session_id=session_id,
            turn_index=session.state.turn_index + 1,
            started_at=datetime.now(UTC),
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                # Someone called cancel() on the turn itself.
                raise TurnCancelled(session_id) from None
            # We were cancelled, not the turn -- the caller went away. Let the
            # turn finish: it is atomic, and half a minute of model time is not
            # worth throwing away because a browser tab closed.
            raise
        finally:
            if self._running.get(session_id) is task and task.done():
                del self._running[session_id]
                self._started.pop(session_id, None)
```

Add `_settle` as a private method below `run`:

```python
    def _settle(self, session_id: UUID) -> Callable[[asyncio.Task[TurnOutcome]], None]:
        """A done-callback that closes the buffer from the turn's own fate.

        `cancelled()` is checked before `exception()` because asking a
        cancelled task for its exception raises rather than answers.
        """

        def settled(task: asyncio.Task[TurnOutcome]) -> None:
            if self._activity is None:  # pragma: no cover -- only registered when set
                return
            committed = not task.cancelled() and task.exception() is None
            self._activity.settle(session_id, committed=committed)

        return settled
```

Add `from collections.abc import Callable` to the module's imports.

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/application/test_turn_supervisor.py -v`

Expected: PASS, including every pre-existing test in the file unchanged.

- [ ] **Step 6: Confirm the layer rule still holds**

Run: `uv run pytest tests/test_architecture.py -v`

Expected: PASS. If it fails, `turn_supervisor.py` or `ports.py` imported something from `interfaces` — the protocol must be structural, with no import of `TurnActivity`.

- [ ] **Step 7: Commit**

```bash
git add research_team/application/ports.py research_team/application/turn_supervisor.py research_team/application/__init__.py tests/application/test_turn_supervisor.py
git commit -m "The supervisor owns the turn's activity buffer

A turn's buffer lives exactly as long as the turn, and the supervisor is
the only thing that knows that span. begin moves inside the is_running
guard, so a caller losing the race no longer reopens the winner's buffer,
and settle moves onto a done-callback on the task, so an awaiter going
away no longer files a live turn's content as a failed turn's discards.

run loses its on_activity parameter outright rather than keeping it as a
passthrough: one caller passed it, no test did, and a parameter that
exists only so the old shape still typechecks is the shim this project
does not keep."
```

---

### Task 2: Wire the buffer through composition and strip the route

**Files:**
- Modify: `research_team/composition.py` (`build_application` signature ~line 484, docstring, and `turns = TurnSupervisor(service)` at ~line 1202)
- Modify: `web.py` (the `build_application(...)` call, ~line 48)
- Modify: `research_team/interfaces/web/app.py` (`run_turn` route, ~lines 1606-1645)
- Test: `tests/interfaces/test_web.py` (the `activity_app` fixture at ~line 1620)

**Interfaces:**
- Consumes: `TurnSupervisor(service, *, activity=...)` and the two-argument `run` from Task 1.
- Produces: `build_application(..., activity: TurnActivityBuffer | None = None)` — a new keyword-only parameter. Task 3 passes it.

- [ ] **Step 1: Point the existing activity test at the new wiring, and watch it fail**

In `tests/interfaces/test_web.py`, the `activity_app` fixture currently builds the application without the buffer and passes it only to `create_app`. One instance must now reach both:

```python
@pytest.fixture
async def activity_app(db_path, fake_model):
    """One `TurnActivity` on both sides of the wire.

    The supervisor writes into it and the catch-up route reads out of it; two
    instances would give the route a different answer about the same turn than
    the turn itself has.
    """
    activity = TurnActivity()
    application = await _started(model=fake_model, db_path=db_path, activity=activity)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        activity=activity,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client, activity
    await application.close()
```

Run: `uv run pytest tests/interfaces/test_web.py -k activity -v`

Expected: FAIL with `TypeError: build_application() got an unexpected keyword argument 'activity'`.

- [ ] **Step 2: Add the parameter to `build_application`**

In `research_team/composition.py`, import the port with the others from `research_team.application` (match the existing import style in that file), add the parameter to the signature after `grants`:

```python
    grants: GrantRegistry | None = None,
    activity: TurnActivityBuffer | None = None,
) -> Application:
```

Add to the docstring, after the `grants` paragraph:

```
    `activity` is the buffer every turn's provisional content flows through,
    and it arrives here for the same reason `approvals` does: `web.py` builds
    one `TurnActivity` and both halves of the channel must be that instance.
    The supervisor writes into it; the catch-up route reads out of it. `None`
    is the REPL's case and most tests' -- turns then run unbuffered, which is
    what happened on every path but the web one before this was wired.
```

And at line ~1202:

```python
    turns = TurnSupervisor(service, activity=activity)
```

- [ ] **Step 3: Pass it in `web.py`**

`web.py` already constructs `activity = TurnActivity()` before `build_application`. Extend the call:

```python
    application = build_application(
        approvals=approvals,
        extractions=extraction,
        dispatches=dispatch,
        grants=grants,
        # Both sides of one channel, like `approvals` above: the supervisor
        # opens and fills this buffer, the catch-up route below reads it.
        activity=activity,
    )
```

- [ ] **Step 4: Strip the lifecycle out of the route**

In `research_team/interfaces/web/app.py`'s `run_turn`, delete the three-line `reporter = None` block and every `activity.settle(...)` call, and drop the reporter argument. The handler's exception arms keep their status codes and their comments about *why those codes*; only the buffer bookkeeping goes:

```python
        try:
            outcome = await turns.run(session_id, body.input)
        except TurnAlreadyRunning as error:
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        return {
            "reply": outcome.reply,
            "turn_index": outcome.turn_index,
            "from_index": outcome.from_index,
            "to_index": outcome.to_index,
        }
```

Note what disappears with it: the `except BaseException` arm existed only to settle the buffer and must go, and the long comment on the `TurnAlreadyRunning` arm explaining why the loser must *not* settle goes with the race it described — `begin` now happens inside the supervisor's guard, so the loser never opens a buffer.

`create_app` keeps its `activity` parameter: the catch-up route at `/turns/current/activity` and the SSE stream still read it. Do not remove it, and do not remove `activity.current` / `activity.discarded`.

- [ ] **Step 5: Run the web tests**

Run: `uv run pytest tests/interfaces/test_web.py -v`

Expected: PASS, including `test_a_turn_reports_activity_into_the_buffer` and `test_activity_catch_up_route_is_empty_before_a_turn` unchanged. They are the evidence that moving the lifecycle did not change what a person sending a turn from the composer observes.

If a test fails because some *other* fixture builds an app whose `create_app` gets an `activity` that `build_application` did not, that fixture is now describing a wiring that cannot happen in `web.py`. Fix it the same way `activity_app` was fixed: one instance, passed to both.

- [ ] **Step 6: Run the whole Python suite**

Run: `uv run pytest`

Expected: PASS. Pay attention to `tests/application/test_topic_seeding.py`, which constructs `TurnSupervisor(service)` — positional, no buffer, still valid.

- [ ] **Step 7: Commit**

```bash
git add research_team/composition.py research_team/interfaces/web/app.py web.py tests/interfaces/test_web.py
git commit -m "Wire the activity buffer where every turn passes, not one route

build_application grows an activity= keyword and hands it to the
supervisor, following approvals/extractions/dispatches exactly; web.py
passes the TurnActivity it already builds to both halves of the channel.

The turns route loses all four settle calls, the reporter it used to
build, and the except BaseException arm that existed only to settle --
along with the comment explaining why a refused second turn must not
settle a buffer it had already opened. It no longer opens one."
```

---

### Task 3: The regression test at the seam that was empty

**Files:**
- Test: `tests/interfaces/test_web.py` (new test beside the auto-research tests, after `test_starting_a_run_answers_with_its_ids_before_it_has_finished` at ~line 2617)

**Interfaces:**
- Consumes: `build_application(activity=...)` from Task 2; the `research_client` fixture's shape at ~line 2591.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

This is the test for the reported defect: a run started from the course page must leave live content where the session view can find it.

It asserts against a recording buffer rather than a real `TurnActivity` on purpose, and the reason is worth stating in the test: with the real buffer, `current()` returns `[]` both for a buffer that was opened and has no content yet *and* for one that was never opened — the two cases the fix is about are indistinguishable through that API. Whether a fake model produces any streamed content is a fact about the fake, not about this wiring.

```python
class RecordingBuffer:
    """A `TurnActivityBuffer` that records the lifecycle driven against it.

    `TurnActivity.current()` answers `[]` both for a buffer that was opened
    and is still empty and for one that was never opened at all -- which are
    exactly the two cases this test exists to tell apart.
    """

    def __init__(self) -> None:
        self.begun: list[UUID] = []

    def begin(self, session_id: UUID) -> None:
        self.begun.append(session_id)

    def reporter(self, session_id: UUID):
        return lambda note: None

    def settle(self, session_id: UUID, *, committed: bool) -> None:
        pass


async def test_a_rounds_turn_opens_an_activity_buffer_like_a_persons_does(
    db_path, fake_model
):
    """A run started from the course page leaves live output to catch up on.

    The defect this covers: rounds were driven by `turns.run(session_id,
    prompt)` from `composition.py` while only the HTTP route opened a buffer,
    so the session view knew a turn was running -- `/turns/current` goes
    through the supervisor, which every turn does -- and had nothing to show
    for it. Fails against a build where the lifecycle lives in the route.
    """
    buffer = RecordingBuffer()
    application = await _started(model=fake_model, db_path=db_path, activity=buffer)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        research=application.research,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
        started = await http.post(
            f"/api/projects/{project_id}/auto-research", json={"max_rounds": 1}
        )
        assert started.status_code == 202
        session_id = UUID(started.json()["session_id"])
        await application.research.wait(UUID(project_id))

    assert session_id in buffer.begun
    await application.close()
```

- [ ] **Step 2: Run it and watch it fail against the old wiring**

Run: `uv run pytest tests/interfaces/test_web.py -k rounds_turn_opens -v`

Expected on the current branch: PASS (Tasks 1 and 2 are already in). To prove the test is real, stash it against `main` instead:

```bash
git stash push -u -m "activity-seam-test-redcheck"
git stash list --format='%H %gs'   # capture the SHA of that entry
```

Then check out `main` in a scratch worktree, apply only this test, and watch it fail with `AssertionError` on `session_id in buffer.begun` — the buffer is never begun for a round. Restore with `git stash apply <sha>` (never `pop`; the stash stack is shared) and drop the entry afterwards by re-finding it by tag.

If that round trip is more ceremony than it is worth, the cheaper proof is equivalent and local: temporarily revert `composition.py:1202` to `TurnSupervisor(service)`, run the test, watch it fail, restore the line.

Record in the commit message which proof was used.

- [ ] **Step 3: If a run with no topics never takes a turn, make the test honest**

An auto-research run over a project with an empty topic queue may complete without running a single round — in which case `buffer.begun` is empty for a reason that has nothing to do with this fix, and the test would fail for the wrong cause.

Check first: run the test and read the failure. If `buffer.begun` is empty even with the fix in place, the run drained an empty queue. Seed the project with a topic the way the neighbouring auto-research tests do — look at how `test_a_started_run_reports_its_own_fold` and the topic tests around line 2640 arrange for a round to happen, and follow that. Do not assert on an empty run; a test that passes because nothing ran is worse than no test.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`

Expected: PASS.

- [ ] **Step 5: Run every gate**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Expected: all four pass. The frontend is untouched by this change; `npm run verify` is run because three of four gates passing is not passing.

- [ ] **Step 6: Commit**

```bash
git add tests/interfaces/test_web.py
git commit -m "A round's turn streams like a person's, and a test that says so

The regression test for the reported defect: a run started from the
course page showed as running in the session view with no live output.

Asserts against a recording buffer rather than a real TurnActivity
because current() answers [] both for a buffer that was opened and is
still empty and for one that was never opened -- the two cases this is
about. Proved red by <the proof used>."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §The design 1 — the `TurnActivityBuffer` port | Task 1, Step 3 |
| §The design 2 — supervisor owns lifecycle, `run` loses its parameter, `begin` inside the guard, settle on the done-callback | Task 1, Steps 4-5 |
| §The design 3 — wiring through `build_application` and `web.py`, route stripped | Task 2 |
| §The design 4 — auto-research gets it for free (no code change) | Task 3 verifies it |
| §A second defect — awaiter going away | Task 1, `test_an_awaiter_going_away_settles_nothing_until_the_turn_itself_ends` |
| §Testing — supervisor-level cases | Task 1, Step 1 (all five) |
| §Testing — the seam that was empty | Task 3 |
| §Testing — route tests keep passing unchanged | Task 2, Step 5 |
| §What this does not do — no file move, no course-page link, no separate channel | No task; nothing to do is the point |

**Type consistency:** `TurnActivityBuffer` has the same three methods in the port (Task 1 Step 3), both fakes (Task 1 Step 1, Task 3 Step 1) and the real `TurnActivity` as it already exists. `settle`'s `committed` is keyword-only everywhere. `run(session_id, user_input)` is two-positional in the supervisor (Task 1), the route (Task 2) and `composition.py`'s round lambda (unchanged).

**Frontend:** no task, deliberately. `ActivityFeed`'s `isBusy && size > 0` gate is already satisfied once the buffer fills, and `applyRunning` already sets `watching` from `/turns/current`.
