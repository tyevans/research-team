# Entity judgements: teaching the graph which names are the same thing

**Status**: design approved 2026-08-14. First of three pieces; see *Scope* below.

## Why

Consolidation reaches the adjudicator for **2 of 10** genuine duplicates.
Measured on 2026-08-14 against a real `nomic-embed-text`, scored through
redstring's own `combined_score`/`decide` at default weights, over ten
same-entity and ten different-entity pairs:

| configuration | recall | false pairs adjudicated | silent bad merges |
|---|---|---|---|
| today (`graph = 0.0` present) | **2/10** | 0/10 | 0/10 |
| graph absent (BACKLOG B58) | 7/10 | 9/10 | 0/10 |

`JFK`/`John F. Kennedy`, `IBM`/`International Business Machines`, `NASA`,
`Einstein`/`Albert Einstein` and both `Grant` pairs are all dropped before the
model is asked. B58 would lift recall to 7/10 and is worth doing, but it is an
upstream ask and it does not reach 10/10 either.

Four separate attempts to fix this by scoring failed, and they failed for one
reason. Reweighting does not fire (commit 6c2ae4a withdrew it). No nomic task
prefix separates the classes -- every margin between the weakest true pair and
the strongest false one is negative (bare -0.235, `clustering:` -0.114,
`classification:` -0.120, asymmetric -0.192). Embedding a canonical description
lowers recall; embedding the source snippet lowers it further. The common cause,
and the premise of this design:

> **Every signal derived from document context pulls true cross-document pairs
> apart**, because two documents about one entity describe *different facets* of
> it. The name is the only document-invariant signal available.

So automatic consolidation cannot close this gap, and the person reading the
graph can. This design lets a human record that judgement once, durably, in
terms that carry across documents.

## Scope

This spec covers **piece 1 of 3**: the domain and the enforcement seam. Backend
only, no HTTP, no UI, fully testable on its own. It lands first because the
other two are shaped by what it records.

- **Piece 1 (this spec)** -- judgement aggregate, `JudgedCandidates`, wiring.
- **Piece 2** -- read paths (a canonical entity's aliases with `merge_id` and
  reason; the taught set) and the first mutation routes on the graph.
- **Piece 3** -- graph view: two-node selection, context menu, aliases panel.

Out of scope here and stated so nobody adds it: any HTTP route, any frontend
change, and B58 itself. This design is independent of B58 and improves recall
whether or not it lands.

## The key: normalized name + entity type

Entity ids are deterministic but document-scoped:

```
uuid5(uuid5(uuid5(tenant_id, source_id), entity_type), normalize_name(name))
```

`source_id` is in the hash, so "Grant" in document A and "Grant" in document B
are different ids *by construction* -- which is why cross-document duplicates
exist as separate nodes at all. A judgement keyed by a pair of ids would
therefore be durable across `/rebuild` but would say nothing about the next
document, and the human would re-answer the same question per document. That is
the treadmill this feature exists to end.

So judgements are keyed by **`(normalize_name(name), entity_type)`**, the only
document-invariant key available. `normalize_name` is redstring's own, imported
rather than reimplemented, so the key matches what `find_entities(name=...)`
matches -- that method compares `normalized_name` exactly, which is what makes
lookup possible at all.

**The cost, stated plainly**: this cannot express "distinct in this context, same
in that one". A project containing both `Mercury` the planet and `Mercury` the
element cannot hold them same in one place and distinct in another. Accepted
deliberately: the per-document alternative is a treadmill, and per-id judgements
remain addable later as a second kind without changing this one.

## Domain model

A new aggregate, `EntityJudgements`, one per project, id = `project_id` --
matching `Corpus`, which is also project-scoped and takes its own id the same
way.

### `EntityKey`

```python
class EntityKey(BaseModel):
    """One name-and-type a judgement can be about. Frozen; hashable."""
    normalized_name: str    # redstring's normalize_name, applied at construction
    entity_type: str
```

Normalization happens **when the key is built**, not when it is compared, so
two keys are equal iff their fields are equal and the state can use them as
dict keys directly. Built from a raw name through one constructor that applies
`normalize_name`, so no call site can store an unnormalized key -- a key that
skipped normalization would silently never match anything, which is the failure
this shape exists to prevent.

### Groups, not pairs

A held-same judgement is **transitive**: told `JFK` = `John F. Kennedy` and
later `John F. Kennedy` = `Kennedy`, all three are one thing. Modelling pairs
and computing closure at read time would put the transitive rule in every
reader. The state therefore holds *groups* -- a union-find over keys -- and
merging two groups is what a same-judgement does.

Held-distinct is **not** transitive and must not be modelled as groups. "A is
not B" and "B is not C" says nothing about A and C.

### Events

```python
@register_event
class EntitiesHeldSame(DomainEvent):
    aggregate_type: str = "EntityJudgements"
    keys: list[EntityKey]        # >= 2, the group being asserted
    reason: str                  # free-form, from the human; shown in the UI
    decided_at: datetime

@register_event
class EntitiesHeldDistinct(DomainEvent):
    aggregate_type: str = "EntityJudgements"
    left: EntityKey
    right: EntityKey
    reason: str
    decided_at: datetime

@register_event
class JudgementWithdrawn(DomainEvent):
    aggregate_type: str = "EntityJudgements"
    judgement_id: UUID           # the event id of the judgement being undone
    reason: str
    decided_at: datetime
```

`reason` is required on all three. It is what the aliases panel shows and the
only record of *why* a human decided something -- the same argument redstring's
own `AdjudicationVerdict.reason` makes for itself. B6 records that
`undo_merge` reports `reason=None`; this design does not depend on that being
fixed, because the reason lives in our event rather than redstring's.

Withdrawal is a **compensating event, not a delete**. The judgement stays in the
log and the fold stops applying it, so "what did I once believe" remains
answerable and the audit trail is intact.

`judgement_id` is the withdrawn event's own `event_id`, which is how
`MergeRecord` already identifies a merge (`report.event.event_id`). The fold
therefore keeps every judgement keyed by its event id, along with a `withdrawn`
flag -- it cannot store only the derived groups, because a withdrawal has to
name a specific past judgement and then recompute.

**Withdrawing a same-judgement means recomputing the group from scratch**, not
subtracting keys from it. Groups are a union of many judgements, and removing
one may split a group in two or leave it whole depending on what else joined
those keys -- set subtraction gets this wrong whenever two judgements overlap.
The fold replays the surviving same-judgements into a fresh union-find. Stated
because the subtractive version looks obviously right and is not.

### Commands and refusals

`HoldSame(keys, reason)`, `HoldDistinct(left, right, reason)`,
`WithdrawJudgement(judgement_id, reason)`.

The aggregate refuses a contradiction **at command time** rather than letting
`JudgedCandidates` resolve it silently at scoring time:

- `HoldSame` naming two keys already held distinct -- refuse.
- `HoldSame` whose group merge would transitively unite two keys held distinct
  -- refuse. This is the one that is easy to miss: holding `A`=`B` and `B`=`C`
  is a contradiction if `A` and `C` are held distinct, and it only appears
  after the union.
- `HoldDistinct` on two keys already in one same-group -- refuse.
- `WithdrawJudgement` naming an unknown or already-withdrawn id -- refuse.
- Either command naming a key equal to itself, or `HoldSame` with fewer than
  two distinct keys -- refuse.

Refusal is an exception carrying both keys and the conflicting judgement's id,
so a UI can offer "withdraw that one first" rather than a dead end.

## Enforcement: `JudgedCandidates`

redstring exposes `CandidateSource` as a Protocol and `Consolidator.resolve`
takes `finder=`. That is the whole seam, and it covers both directions at the
layer where "is this a candidate" is already decided:

```python
class JudgedCandidates:                       # implements CandidateSource
    async def candidates(self, subject, *, minimum_score=0.0): ...
```

- **held-distinct** -- drop the candidate before it is scored. Never scored,
  never adjudicated, never auto-merged. This closes the `>= HIGH_SIMILARITY`
  bypass too: a veto placed on the adjudicator instead would be skipped
  entirely by a pair scoring 0.92+, which is unreachable cross-document today
  but becomes reachable if B58 lands (`Retriever`/`Retrievers` scores 0.968).
  Dropping at the candidate stage is correct under both.
- **held-same** -- inject the counterpart as a `ScoredCandidate` at score 1.0.
  It lands above `HIGH_SIMILARITY` and merges with no model call.

Injection rather than score adjustment is the point. `JFK`/`John F. Kennedy`
scores 0.609 and is never a candidate today; no reweighting brings it into
range, and `CandidateFinder` blocks candidates by a prefix key those two names
do not share. Injection sidesteps scoring entirely, which is the only mechanism
that works for the cases this feature exists for.

Counterparts are found with `find_entities(name=...)` per key in the subject's
group, which matches `normalized_name` exactly.

**Ordering contract.** `CandidateSource` requires descending score with ties
broken by a further total order -- `CandidateFinder` uses ascending entity id as
a string -- so that a cutoff inside a tie is decided identically on every run.
Injected candidates all score exactly 1.0 and so are all in one tie; they are
sorted by entity id as a string to match. A test asserts the merged list is
ordered, because an unstable order here makes consolidation non-reproducible and
nothing else would catch it.

`minimum_score` is `resolve`'s `low` passed through. Injected candidates at 1.0
clear any threshold; dropped candidates are dropped regardless of it.

With an empty judgement table this class is a pure passthrough, which is the
property that makes it safe to wire in before any UI exists.

## Wiring

`RedstringKnowledge.__init__` gains an optional `judgements:
AggregateRepository[EntityJudgements] | None = None`. `_consolidate` passes
`finder=JudgedCandidates(...)` to `resolve` when it is present and omits it
otherwise, so every existing construction site and test keeps today's behaviour
untouched.

The judgement state is loaded **once per `_consolidate` call**, not per entity.
An ingest resolves every extracted entity in a loop; reloading the aggregate per
entity would be one event-store read per entity to re-learn something that
cannot change mid-loop.

Being handed the repository rather than a snapshot is deliberate: `reconsolidate`
is a separate entry point and must see judgements made since the last ingest.

## Testing

The four gates, and `test:browser` is not relevant -- nothing here computes a
style.

Behaviours to pin, each of which fails for a distinct reason:

1. A held-same pair merges even though its score is far below `LOW_SIMILARITY`
   -- the `JFK` case, and the reason injection exists. Use two names whose
   score is genuinely low, not a near-duplicate that would merge anyway, or the
   test passes with the feature removed.
2. A held-distinct pair does not merge even at score 1.0 -- assert it is
   dropped rather than adjudicated, by running with **no adjudicator** so an
   adjudicated pair would be rejected for the wrong reason and the test would
   pass dishonestly.
3. A withdrawn judgement stops applying, and the pair returns to ordinary
   scoring.
4. Transitive closure: `A`=`B`, `B`=`C`, then `A` and `C` merge.
5. Each refusal in *Commands and refusals*, including the transitive one.
6. An empty table changes nothing -- the same fixture as an existing
   consolidation test, asserting the identical outcome.
7. Judgements survive a rebuild: fold the stream twice and compare state.
8. Injected candidates are ordered by entity id within their tie.

Schema evolution: three new events go in
`tests/infrastructure/test_schema_evolution.py`.

The suite currently has **no fixture setting `description`** (BACKLOG B60), so
adjudicator prompts under test do not resemble production's. Not fixed here;
noted because tests in this area inherit it.

## What this does not do

- It does not improve automatic consolidation. Recall stays 2/10 for anything
  no human has judged. This is a manual override, and B58 remains the fix for
  the automatic path.
- It does not express context-dependent identity (the `Mercury` case).
- It does not touch the agent's tools. Judgements are a human's to make; whether
  an agent may record one is a later decision, deliberately not taken here.
