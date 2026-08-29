---
title: "The Log Is the Only Source of Truth"
area: knowledge-graph
builds_toward: "Task 1 — Fold or projection?"
---

# The Log Is the Only Source of Truth

Everything in this system is one ordered list of events. A user message, a model reply, a tool call, a file write — each is a single event appended to a stream, and the stream is the whole state. The README states the design in one line: "Every user message, model reply, tool call and file write is one ordered event stream, and all state is derived by folding it." [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

That sentence is doing more work than it looks. "Derived by folding" means the state you see at any moment is not stored — it is *recomputed* by running every event in order through a function. The log is the only thing that is actually written down. Everything else is a view you can throw away and rebuild.

## What a fold is, and why it cannot be wrong

A fold is a pure function of the log. You hand it the events, it hands back the state. Run it twice and you get the same answer, because there is no hidden state to drift. The architecture document is explicit about the consequence: "A fold is recomputed every time, so it cannot be stale and a fixed bug is retroactive." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]

"Cannot be stale" is the important half. A stale value is one that was computed once, written down, and then left behind while the world moved on. A fold has no such value — there is nothing to leave behind, because the computation is redone on every read. If you find a bug in the fold function and fix it, the fix is *retroactive*: the next time you fold, you get the corrected answer for the entire history, not just for events after the fix. There is no old, wrong result sitting in a table that you have to find and repair.

The knowledge graph, the session list, and the learning-area clusters are all folds. The graph in particular is "a projection folded from the same log, rebuilt whenever a project opens, and costing nothing to lose." [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] "Costing nothing to lose" is the payoff: because it is recomputed, deleting it is free.

## What a projection is, and the failure mode a fold does not have

A projection is the other option, and it exists for a reason. Folding on every request is correct but slow. The architecture document records the history honestly: the session list "used to be a fold over `read_category` on every request, which was the clearest possible statement of what a summary is and got linearly slower forever." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]] So they switched to a projection — a table, `session_summary_rows`, "kept up to date event by event by a `SubscriptionManager`, which replays from a persisted checkpoint on startup and then follows the live bus." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]

The trade is speed for a failure mode a fold simply cannot have. Here is the passage to keep in mind, because it is the whole of the distinction:

> "A projection is written down once: if a handler throws, the subscription carries on (one bad event must not stop the rest), the checkpoint advances past it, and the row it would have updated is wrong permanently -- a restart does not help, because catch-up resumes after the event that was never applied." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]

Read that carefully. The projection is *written down*. That is the difference. A fold is recomputed, so a bug is fixed by fixing the function. A projection is stored, so a bug is fixed by *rebuilding the table* — and the system is built so you can do exactly that. "Rebuilding is idempotent and safe to reach for on a hunch, which is the point: the log is the only source of truth, so anything computed from it can be thrown away." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]] The `/rebuild` command "drops the rows and the checkpoint together so the whole table is derived again from the log." [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]

So the projection's permanent-wrong-row failure is real, but it is *recoverable* — because the log is still there, complete and unharmed. The projection was never the truth; it was a cache of the truth. That is the entire design: you are allowed to keep a fast, written-down view, precisely because you can always discard it and re-derive it from the one thing that is authoritative.

## The command/event line that makes all of this possible

The reason the log can be the only source of truth is that it records *facts*, not *requests*. The domain code draws the line sharply. Commands are "values, not method calls: `decide` matches on the pair *(command, state)*." [[src:github-com-tyevans-research-team-blob-main-research-team-domain-commands-py-4a46b411]] And: "They are never stored. A command that `decide` refuses leaves no trace -- the log records what happened, and a rejected request did not happen. That is the difference between these and the events in `events.py`, which are frozen facts about the past and are written down forever." [[src:github-com-tyevans-research-team-blob-main-research-team-domain-commands-py-4a46b411]]

This is why the fold is trustworthy. The log contains only things that actually happened. A request that was refused is not in it, so folding the log never has to guess whether a refused request "counted." The events are "frozen facts about the past" — and one stream carries both the conversation and the filesystem, "so ordering between 'the model said X' and 'file Y changed' is total." [[src:github-com-tyevans-research-team-blob-main-research-team-domain-events-py-1ca7f951]] Total ordering is what makes a fold deterministic: there is exactly one correct answer to "what is the state after these events," because there is exactly one order they happened in.

## Meet the material

The event log is the substrate everything else in this area is built on. Open it in the project's own graph and see what it connects to:

```component:definition
id: l1-def-eventlog
entity: "event log"
entity_id: "00175572-5418-5c5f-b689-e2079a0adcdc"
```

## Check for understanding

A new requirement arrives: the system needs a "recent activity" view showing the last 50 events per session, updated in real time. The team is split on whether to implement it as a fold or a projection.

```component:mcq
id: l1-mcq
prompt: The team implements the "recent activity" view as a projection. A handler in that projection throws an exception on event 47, and the process restarts. What is the state of the view?
options:
  - text: "The view is rebuilt from scratch on restart, so it is correct again."
    correct: false
    feedback: "No. A projection is written down once; a restart does not rebuild it. Catch-up resumes after the event that was never applied."
  - text: "The handler is retried on event 47 and the row is corrected."
    correct: false
    feedback: "No. The subscription carries on past the bad event and the checkpoint advances past it; nothing retries event 47."
  - text: "The row that event 47 would have updated is wrong permanently, until someone runs a rebuild."
    correct: true
    feedback: "Yes. A projection is written down once: if a handler throws, the checkpoint advances past it and the row it would have updated is wrong permanently. A restart does not help; only a rebuild re-derives it from the log."
  - text: "The view is marked stale and hidden until it is recomputed."
    correct: false
    feedback: "No. There is no staleness mechanism for a projection. The wrong row is simply wrong, which is why the dead-letter queue and /rebuild exist."
rationale: |
  A projection is written down once: if a handler throws, the subscription carries on, the checkpoint advances past the bad event, and the row it would have updated is wrong permanently. A restart does not help because catch-up resumes after the event that was never applied. Only a rebuild re-derives the table from the log. A fold, by contrast, is recomputed every time and cannot be stale.
```

```component:cloze
id: l1-cloze
text: |
  A fold is recomputed every time, so it cannot be {{stale}} and a fixed bug is {{retroactive}}. A projection is written down once: if a handler throws, the row it would have updated is wrong {{permanently}} -- a restart does not help, because catch-up resumes after the event that was never applied.
```

## Retrieval practice

Answer from memory, then check against the corpus:

1. Why can a fold never be stale, and what does "a fixed bug is retroactive" mean?
2. What is the specific failure mode a projection has that a fold does not, and why does a restart not fix it?
3. What does `/rebuild` do, and why is it "safe to reach for on a hunch"?
4. Why does the log contain only facts and not requests? What happens to a command that `decide` refuses?
5. Why does "one stream carries both the conversation and the filesystem" matter for the fold?
