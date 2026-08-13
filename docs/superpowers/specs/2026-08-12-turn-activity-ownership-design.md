# Whoever runs the turn owns its activity buffer

Moving `TurnActivity`'s begin/settle lifecycle out of the HTTP route and into
`TurnSupervisor.run`, so that every turn buffers and streams its provisional
content regardless of who started it.

## The problem, stated precisely

A turn started from the course page (an auto-research run) shows as running in
the session view — the banner is correct — but shows no live output. A turn
started from the session view's composer shows both.

The banner and the output come from two different channels, and only one of
them is wired on both paths:

- **Is a turn running** comes from `GET /turns/current`, answered by
  `TurnSupervisor.running`. Every turn goes through the supervisor, so this is
  right on every path.
- **What the turn is saying** comes from `TurnActivity` — provisional frames on
  the live feed plus a catch-up buffer behind
  `GET /turns/current/activity`. That channel is opened by the *HTTP route*,
  in `interfaces/web/app.py`:

  ```python
  reporter = None
  if activity is not None:
      activity.begin(session_id)
      reporter = activity.reporter(session_id)
  outcome = await turns.run(session_id, body.input, reporter)
  ```

An auto-research round does not go through that route. `composition.py` builds
its round runner as `lambda prompt: turns.run(session_id, prompt)` — no
reporter, and no `begin`. So the round runs with `on_activity=None`: no frames
are published, and because `begin` was never called, the catch-up route returns
an empty `running` too. The frontend then does the only correct thing with what
it has — `ActivityFeed` gates on `TurnState.isBusy(turn) && activity.size > 0`
and renders nothing.

**The defect is not the missing argument at that one call site.** It is that
the lifecycle of a turn's buffer is owned by one of the two things that can
start a turn. Passing a reporter into the lambda would fix the symptom and
leave the next caller to rediscover it.

## A second defect, fixed by the same move

The route settles the buffer in the awaiter's exception handlers:

```python
except BaseException:
    if activity is not None:
        activity.settle(session_id, committed=False)
    raise
```

`TurnSupervisor.run` awaits the turn under `asyncio.shield` precisely so that a
client going away does *not* stop the turn — "half a minute of model time is not
worth throwing away because a browser tab closed", as the supervisor puts it.
But when that happens the awaiting task is cancelled, this handler runs, and the
buffer of a **still-running turn** is settled as though it had failed: its
content moves to `_discarded`, where the UI offers it as the last failed turn's
throwaway output.

It gets worse from there. The turn is still live, so its next note reaches
`TurnActivity._record`, whose `self._running.setdefault(session_id, {})`
silently opens a *second* buffer for the same turn. Nothing will ever settle
that one — the `run()` call that would have owned it already raised. It leaks
until the next `begin` on that session drops it.

Both halves are the same root cause: the buffer's lifetime is being managed by
the awaiter, and the awaiter's lifetime is not the turn's.

## The design

**Ownership moves; the class does not.** `TurnActivity` stays in
`interfaces/web`, beside `approvals.py`, `extraction.py`, `seeding.py` and
`dispatch.py` — every one of which lives in the interface layer and satisfies a
protocol declared in the application layer. That is the established shape here
and it is the right one: the class owns an SSE fan-out and speaks in wire-shaped
dicts, which is transport, while what the application needs from it is three
methods.

### 1. A port

`application/ports.py` grows `TurnActivityBuffer`, beside the `ActivityReporter`
alias it already declares:

```python
class TurnActivityBuffer(Protocol):
    def begin(self, session_id: UUID) -> None: ...
    def reporter(self, session_id: UUID) -> ActivityReporter: ...
    def settle(self, session_id: UUID, *, committed: bool) -> None: ...
```

Only the three methods the supervisor drives. `current` and `discarded` are read
by the catch-up route and stay off the protocol, because the application never
reads a buffer back — declaring them would describe a coupling that does not
exist.

### 2. The supervisor owns the lifecycle

`TurnSupervisor.__init__` takes `activity: TurnActivityBuffer | None = None`.
`None` means no buffering, which is what the REPL and most tests want.

`run` loses its third parameter. This is a **clean break** — no default
passthrough, no deprecation — and it is safe to make one because
`interfaces/web/app.py` is the only production caller that passed a reporter,
and `tests/integration/test_turn_visibility.py` is the only test that did; both
move to the buffer the supervisor now drives itself. The REPL is unaffected: it
calls `service.run_turn` directly with its own printing reporter, which remains
a legitimate second implementation of `ActivityReporter`.

```python
async def run(self, session_id: UUID, user_input: str) -> TurnOutcome:
    if self.is_running(session_id):
        raise TurnAlreadyRunning(session_id)

    session = await self._service.load(session_id)
    reporter = None
    if self._activity is not None:
        self._activity.begin(session_id)
        reporter = self._activity.reporter(session_id)
    task = asyncio.ensure_future(
        self._service.run_turn(session_id, user_input, reporter)
    )
    if self._activity is not None:
        task.add_done_callback(self._settle_activity(session_id))
    ...
```

Two properties of that placement carry the whole design:

**`begin` is inside the `is_running` guard.** The request that loses the race
never touches the buffer, so the careful comment in `app.py` explaining why the
`TurnAlreadyRunning` branch must *not* settle a buffer it just opened is deleted
along with the race it describes.

**`settle` hangs off the task, not the awaiter.** The done-callback reads the
task's own fate: cancelled or raised is `committed=False`, returned normally is
`committed=True`. An awaiter that goes away no longer settles anything, which is
the second defect above, fixed by construction rather than by another handler.

### 3. Wiring

`build_application` grows an `activity=` keyword and hands it to
`TurnSupervisor`, following `approvals=` / `extractions=` / `dispatches=`
exactly. `web.py` already builds one `TurnActivity()`; it now passes that same
instance to both `build_application` and `create_app`, for the same reason
`approvals` is one object on both sides of the wire — two would give the writer
and the catch-up route different answers about the same turn.

`create_app` keeps its `activity` parameter, now used only for reads: the
catch-up route and the stream. All four `activity.begin` / `activity.settle`
calls come out of `run_turn`, and the route becomes what it should have been —
a caller of `turns.run` that translates outcomes into status codes.

### 4. What falls out for free

`composition.py`'s `lambda prompt: turns.run(session_id, prompt)` needs no
change. Auto-research rounds get buffering, live frames and catch-up because
every turn now does. Each round begins and settles its own buffer, so the pane
clears between rounds, and a round that fails leaves discarded content exactly
as a person's failed turn does.

The frontend needs no change either. Once the buffer fills, `ActivityFeed`'s
existing `isBusy && size > 0` gate is satisfied by the `watching` turn state
that `applyRunning` already sets from `/turns/current`.

The same is true of `topic_seeding.py:137` and `stage_runner.py:567` — they
call `run` on the same shared supervisor, so their turns now open and settle
buffers and publish frames on the SSE stream too. This is a decision, not just
an auto-research side effect: it is consistent (a seeding or stage run is a
turn like any other) and safe (buffers are keyed per session, so concurrent
turns do not collide), and it costs extra frames on the stream during a
seeding or stage run that nothing currently reads. Nothing consumes them
today, but nothing has to change for that to become true later.

## Testing

The gap this closes was invisible because no test crossed the seam it lives on:
the supervisor's tests never had a buffer, and the auto-research tests never
looked at one.

**At the seam that was empty** — an auto-research round leaves live content
where a tab can catch up on it. Start a run through the HTTP app, and assert
`GET /turns/current/activity` reports non-empty `running` while a round is in
flight. This is the regression test for the reported defect and it fails against
`main`.

**At the supervisor** — over a fake buffer recording calls:

- a turn begins its buffer and settles it `committed=True`
- a turn that raises settles `committed=False`
- a cancelled turn settles `committed=False`
- a second turn refused by `TurnAlreadyRunning` neither begins nor settles —
  the losing request leaves the running turn's buffer untouched
- **an awaiter that goes away settles nothing until the turn itself finishes,
  and then settles it once, with the turn's own outcome.** This is the test for
  the second defect; it fails against `main`, where the buffer is settled early
  as discarded and a leaked second buffer is never settled at all.

**At the route** — the existing turn-endpoint tests should keep passing
unchanged. They are the evidence that moving the lifecycle did not change what a
person sending a turn from the composer observes.

## What this deliberately does not do

- **It does not move `TurnActivity` into the application layer.** The SSE
  fan-out is transport and belongs where its siblings are. Ownership of the
  lifecycle is the thing that was in the wrong place.
- **It does not link the course page to the run's holding session.** Reaching
  the session view is already possible and is how the defect was reported;
  making that a one-click affordance is a separate, frontend-only change.
- **It does not give the auto-research driver its own activity channel.** Rounds
  are turns, and they should stream as turns do. A parallel channel would be a
  second thing to keep correct.
