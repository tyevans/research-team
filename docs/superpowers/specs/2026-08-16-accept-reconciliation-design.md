# Reconciling accepted media proposals on startup

A person accepts a media proposal. The route appends `MediaProposalAccepted`,
answers 202, and hands the download to `asyncio.create_task`. If the process
dies before `MediaAcceptWorker` finishes, the proposal is `accepted` forever:
no source, no failure, no signal. The review pane shows a card that is working
and always will be.

This is `BACKLOG.md` B97. It has its own design rather than a one-line fix
because its entry says so: *"reconcile on startup" is a durable-work pattern
this codebase does not otherwise have, and inventing it in a hurry is how it
ends up per-feature.*

## What is already true, and why that makes this small

**A re-run is already safe, and the safety is already load-bearing.**
`MediaAcceptWorker`'s docstring argues it at length and the argument is not
reopened here: `source_id` is the proposal id and the blob store is
content-addressed, so a re-download of unchanged bytes lands on the same blob;
`StoreMediaProposal` against an already-`stored` proposal is *refused* rather
than made idempotent — deliberately, because `decide` cannot arbitrate between
two `source_id`s claiming to be one proposal's result — and the worker reads
that refusal back and treats "refused because already stored" as its own
success signal.

So the missing piece is not safety. **It is that nothing re-runs it.**

**The reads exist.** `MediaProposalRow` carries the state, and
`MediaProposalReadPort` already answers "one accepted proposal, by id" for the
worker. This needs one more method on the same port.

**No new events, no new column, no new state.** Reconciliation appends nothing
of its own; the worker's own `StoreMediaProposal`/`FailMediaProposal` remain the
only record that anything happened. A reconciliation that logged its own
progress into the event log would be inventing a second lifecycle beside the one
`media_proposals.py` already owns.

## Where it hangs, which is the whole decision

**In `Application.start()`, immediately after the media-proposals projection —
not in `web.py`'s lifespan.**

`web.py` is the only real entrypoint and it carries three separate comments of
the form *"Was missing: these routes have been 503ing in this entrypoint while
the test fixture wired one and passed."* `corpus`, `topic_repository` and
`editor` each shipped disconnected, each was found in production rather than by
a gate, and `tests/interfaces/test_web_entrypoint.py` exists because it happened
three times.

A reconciler wired into that call site would be the fourth. It would be
invisible to every composed test — every one of which builds its own app — and
its absence would look exactly like "no proposals needed reconciling", which is
the most common correct outcome. **A feature whose success and whose absence
render identically must not depend on a call site anyone can forget.**

`Application.start()` is the opposite: every entrypoint calls it, every composed
test calls it, and it is already where the projections are opened. Wiring there
makes the connection structural rather than remembered.

**Ruling: after `media_proposals.caught_up()`, not merely after `.start()`.** A
projection that has started but not caught up under-reports the accepted set,
and there is no second pass — a proposal missed here stays missed until the next
restart. The cost is that startup waits on the projection catching up, which it
would have to do before serving anything about proposals regardless.

## How it runs

**Scheduled as a task, not awaited inline.** An abandoned download is a download
— re-fetching an hour of video must not hold the port closed. The task reference
is held on the `Application` (a bare `create_task` is only weakly held; `app.py`
already carries this note above `create_app`'s body).

**A test can await it.** `Application` exposes the completion the way it already
exposes `summaries_caught_up()` — the codebase's existing answer to "eventually
consistent by construction, invisible to a person and maddening to a test". A
reconciliation observable only by sleeping would be untestable, and untestable
is how this feature would rot.

**Sequentially, one proposal at a time.** The set is expected to be tiny: it
takes a crash inside the download window to produce a member. Concurrency buys
throughput on a set that should usually be empty and costs a bounded-parallelism
decision, a semaphore, and a way for one download to starve another. Cost if
wrong: a genuinely large abandoned set — say a crash during a bulk accept —
takes as long to reconcile as it would have taken to run. That is acceptable and
is written here so the next person can change it on evidence rather than taste.

**One proposal's failure must not touch the others, and must never fail
startup.** Each `run` is guarded; the exception is logged with the proposal id
and the loop continues. A reconciliation that raised would turn "one asset's
host is gone" into "this install does not boot", which is strictly worse than
the defect being fixed.

## What this does not do

- **Nothing reconciles during a long-lived process.** A task that dies while the
  process survives — cancelled, or killed by an exception the worker does not
  name — waits for the next restart. A periodic sweep is the obvious extension
  and is deliberately not built here: it needs an interval, a jitter policy and
  a story about two processes sweeping at once, none of which the crash case
  needs.

  **Since built, as `BACKLOG.md` B99** — `Application._sweep_reconciliation`,
  re-using this same reconciler on a timer. The three open questions were
  answered: the interval is `AGENT_MEDIA_RECONCILE_INTERVAL`, defaulting to
  five minutes; the sleep is full jitter, a uniform draw from `[0, interval]`,
  so instances do not fall into lockstep; and two processes sweeping one
  proposal needs no locking, because `StoreMediaProposal`'s refusal of an
  already-stored proposal — the property this document already leans on — is
  what makes the loser of that race record nothing and report success. The
  sweep is scheduled after `caught_up()` for the same reason the startup pass
  is, and cancelled in `close()` alongside it.
- **No operator surface.** There is no route to trigger reconciliation and no
  count in the pane. Both are reasonable and neither is required to close the
  hole.
- **No distinction between "accepted and running" and "accepted and
  abandoned".** B97 names it as a possible fix and it is not taken: it would be
  a new column whose correctness depends on a write happening at process death,
  which is exactly the write that does not happen. Re-running the safe worker is
  cheaper than recording a state that cannot be trusted.

## Testing

- **The reconciliation is reached from `Application.start()`** — asserted
  against a composed application, not a hand-wired reconciler. This is the test
  that would have caught the three `web.py` gaps, and it is the reason this
  feature hangs where it does. It must fail if the call in `start()` is deleted.
- An accepted proposal with no source is re-run and ends `stored`.
- A proposal already `stored` is **not** re-run — the read must exclude it, and
  the assertion is that the worker was not called, not merely that the end state
  is unchanged (which is true either way).
- A proposal that is `failed` is likewise not re-run.
- One proposal whose `run` raises does not prevent the next one from running,
  and does not propagate out of `start()`.
- The empty case — no accepted proposals — completes and does nothing.
