# Topic tracker and auto-research mode

*2026-08-06*

Two features, deliberately built in one order: a **topic tracker** that makes
"what are we researching, and what needs looking at" a thing the system holds,
and an **auto-research mode** that works a queue of such topics without a human
driving each turn.

The order is not a preference. Auto-research without a tracker has no queue to
work and no stopping rule except the agent's own claim that it is finished --
which is the one stopping rule a language model cannot be trusted with. The
tracker is independently useful; the loop is not.

## What exists already, and what this must not duplicate

- Three aggregates: `CodingSession`, `Project`, `Corpus`. There is no task
  list, agenda, or queue anywhere in the domain today.
- `Corpus` holds documents with digests, supersession by `source_id`, and
  auditable drops with a required reason. It is the closest existing thing to
  "what we have looked at".
- The knowledge graph answers "what entities do we know", per project tenant.
- `AutonomyPolicy` with `auto | ask | deny`, and `TOOL_FLOORS` putting `fetch`
  and `advance_stage` at `ask`. The `advance_stage` floor exists *because
  advancing is the review gate*.
- `TurnSupervisor` owns exactly one in-flight turn per session, runs it as its
  own task, and can cancel it. Turns are atomic: a failure discards the
  aggregate and appends a lone `TurnFailed`.
- Two projections (`SessionSummaryRunner`, `CorpusRunner`) follow the log off
  the request path, with DLQ, health, and rebuild.
- **Nothing ever initiates work.** Every turn today originates from a human
  keystroke or an HTTP POST.

The check library on `feat/check-library` (PR #21, unmerged) establishes a
registry contract this design deliberately mirrors -- model-free, parameterized,
returning findings rather than scores, with `run=None` for gaps that cannot be
honestly automated. **This work does not import it**, because depending on 6350
unmerged lines would couple two reviews together. The two registries should be
unified once that lands; the shapes are intentionally compatible.

## Feature A: the topic tracker

### A topic is an aggregate; attention is a projection

`Topic` gets its own stream, `StreamId(topic_id, "Topic")`, owned by a project.
Folded state holds the question, its status, what sources and entities it is
linked to, its sub-questions, and a cursor recording how far the log had
advanced when it was last investigated.

**State holds no findings and no needs-attention flag.** Attention is computed
on read from the state plus the corpus, exactly as `CorpusState` keeps document
text out of the fold and pushes retrieval into a read model. A stored flag is a
second source of truth that goes stale silently; a computed one cannot.

Rejected: a topic as a markdown file under `/topics/`, which would make "who
changed this status and why" a diff-archaeology problem instead of an event.
Rejected: topic status as graph entities, which would give a derived store
authoritative mutable state.

### Attention triggers

A registry in the same shape as the check library: named, namespaced `topic.*`,
parameterized, returning `Finding` lists with a severity per binding, and
never a score. The triggers that ship are all **Tier 1 -- computable from the
event log alone, no model call**:

| Trigger | Fires when |
|---|---|
| `topic.never_investigated` | no investigation has ever been recorded |
| `topic.unanswered` | open sub-questions remain |
| `topic.low_coverage` | fewer than `minimum` linked live sources |
| `topic.source_dropped` | a linked source was dropped from the corpus |
| `topic.source_superseded` | a linked source's bytes changed after the last look |
| `topic.new_material` | a source arrived after the last look that the topic does not link |
| `topic.contested` | recorded contradictions remain unresolved |
| `topic.rework_thrash` | investigations recorded with no finding between them |

Two rules carried over from the check library, both load-bearing:

- **The instrument rule.** A trigger reports when the instrument it was handed
  is missing, and passes when only its domain is empty. A topic with no linked
  sources is a finding; a topic whose linked sources contain no contradiction
  is a pass.
- **If a finding's only possible response is to dismiss it, the trigger should
  not exist.** Alert fatigue is the defining failure of every monitoring system
  in the prior art, and it comes from firing on conditions nobody would act on.

**No confidence decay.** A per-topic float that decays with time is the most
tempting mechanism here and the least defensible: nobody can re-derive it, its
decay rate is unfalsifiable, and thresholding on it invents precision. Staleness
here is *evidence-based* -- a topic is stale because a specific event happened,
and the finding names that event.

### Hysteresis and acknowledgement

Two borrowings from monitoring prior art:

- **Hysteresis by event count, not wall clock.** Ingesting ten documents at once
  should raise a topic once, not ten times.
- **Acknowledgement with an expiry.** `until_position` is required, because an
  acknowledgement that never expires is a permanently silenced alarm nobody
  remembers muting. The reason is required for the same argument that makes
  `SourceDocumentDropped.reason` required.

Status vocabulary is borrowed from VEX rather than `open/closed`:
`open | investigating | answered | not_pursuing | superseded`, with a required
justification on every transition.

## Feature B: auto-research mode

### One round is one turn

The driver sits *above* `TurnSupervisor` and holds no state that is not in the
log. Each round: read the ready queue, claim a topic, run one turn scoped to it,
record what it produced, evaluate the stop conditions, record the evaluation.

Rejected: a single long turn that loops internally. It defeats atomicity (all or
nothing over an hour is worthless), defeats cancellation granularity, and makes
context exhaustion inevitable. Rejected: a background thread holding state in
memory, because the interesting failure is the process dying at round 40.

### Termination is multi-signal, and every evaluation is recorded

| Reason | Meaning |
|---|---|
| `queue_empty` | no topic has findings. The good ending. |
| `budget_exhausted` | rounds, or turns, spent |
| `no_new_findings` | N consecutive rounds produced nothing new |
| `max_rounds` | the universal backstop |
| `error_rate` | M consecutive failed turns |
| `cancelled` | a human stopped it |

**"Done" must be a fold, never a claim.** The agent may not terminate by
asserting completion in prose; the loop terminates when a computed condition
holds, and the event names which one. A model asked whether it is finished says
yes fluently, which is exactly the failure the check library's
`self_review_separation` invariant exists to prevent, one level up.

**Progress is measured in artifacts, not narration.** A round that recorded no
finding, linked no source, and opened no sub-question is provably empty however
well it described itself.

**A run that stops with unexamined topics says so on its face.** Borrowed from
`FieldGate`: emit the result with its gates explicitly unsatisfied rather than
reporting success.

### The approval interaction, which is the hard part

`fetch` floors at `ask`. An unattended loop that hits it either deadlocks (the
web approval port parks a future forever) or hard-rejects (with no approval port
at all). That is not a bug to route around -- it is the security posture working.

**The default is read-only.** Auto-research works over the corpus and graph the
project already holds. This needs no new machinery, is honest about what it is,
and is genuinely most of the value: coverage, contradiction, linkage and
staleness are all questions about material already in hand.

**The loop reads the autonomy policy and never writes it.** A loop that can
lower its own floors makes `TOOL_FLOORS` advisory, and the structural guarantee
is worth more than the convenience.

**Auto-research runs within a stage and never across one.** `advance_stage` is
the review gate; a loop that crosses a stage boundary unattended is precisely
the silent-progress failure the staging design exists to prevent.

## Auditability

Two invariants, asserted by tests rather than documented:

- **No round without a reason.** Every round names the triggers that put its
  topic in the queue.
- **No stop without evidence.** Every stop reason is recomputable from the
  events preceding it.

`AutoRunStarted` snapshots the autonomy policy, because the policy is mutable
mid-turn and "was it allowed to do that" has to stay answerable later.

Attention is *not* appended every tick -- that is a firehose that grows without
bound and is fully recomputable. Only entering and leaving the queue is
recorded, and `TopicAttentionRaised` carries the ids of the events that raised
it. That last part is the crux: a reason string is a claim, and an event id is
a citation.

## Scope of this change

Built: the `Topic` aggregate, the trigger registry, a topic read model and
projection, agent-facing topic tools, the `AutoResearchRun` aggregate, the
driver, and composition wiring.

Not built, deliberately: model-backed contradiction *detection* (registered as a
human gate instead), scoped fetch pre-authorization, and any HTTP surface for
starting a run. Each is a separate decision with its own review.
