# Entity Judgements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a human record durable "these names are the same thing" / "these names are never the same thing" judgements that consolidation obeys across every document in a project.

**Architecture:** A new project-scoped `DeciderAggregate` (`EntityJudgements`) keyed by normalized name + entity type, plus a `JudgedCandidates` class implementing redstring's `CandidateSource` protocol that injects held-same counterparts at score 1.0 and drops held-distinct candidates before scoring. Wired optionally into `RedstringKnowledge._consolidate` via `resolve(finder=...)`, so an absent repository leaves today's behaviour byte-identical.

**Tech Stack:** Python 3.13, pydantic, `eventsource-py` (`DeciderAggregate`, `register_event`, `CommandRejectedError`), `redstring` 0.9.1 (`CandidateSource`, `ScoredCandidate`, `SimilarityFeatures`, `normalize_name`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-entity-judgements-design.md`

## Global Constraints

- **Four gates, all of them.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository. This plan touches no frontend file, so `npm run verify` is not expected to be affected — but the two ruff gates cover Python tests and are the ones that fail in CI on work like this.
- **Never run two `pytest` processes at once.** Concurrent runs fail spuriously.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, say when something was measured rather than reasoned. A comment restating the code is worse than none.
- **If a test would pass with the change reverted, say so in its docstring.** Proving a test red before trusting it green is the convention here.
- **No backwards compatibility required.** Pre-release; break data, events, and contracts rather than migrating. Do not write migration shims.
- **Do not change `_WEIGHTS`, thresholds, or `use_graph_signal`.** Commit 6c2ae4a withdrew a reweight for lack of evidence; this feature is independent of scoring and must not quietly retune it.
- **`normalize_name` is redstring's**, imported from `redstring.domain.similarity`. Never reimplement it — the key must match what `find_entities(name=...)` compares against.
- Exact key: `(normalize_name(name), entity_type)`. `entity_type` is **not** normalized (redstring does not normalize it either).

---

### Task 1: `EntityKey` and the three events

**Files:**
- Create: `research_team/domain/judgements.py`
- Test: `tests/domain/test_judgements.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EntityKey` (frozen pydantic model, fields `normalized_name: str`, `entity_type: str`; classmethod `EntityKey.of(name: str, entity_type: str) -> EntityKey`); events `EntitiesHeldSame(keys: list[EntityKey], reason: str)`, `EntitiesHeldDistinct(left: EntityKey, right: EntityKey, reason: str)`, `JudgementWithdrawn(judgement_id: UUID, reason: str)`. All three carry `aggregate_type: str = "EntityJudgements"`.

- [ ] **Step 1: Write the failing test**

```python
"""The value types a judgement is expressed in."""

import pytest
from pydantic import ValidationError

from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    JudgementWithdrawn,
)


def test_a_key_normalises_the_name_when_it_is_built():
    """Normalised at construction, so equality is plain field equality.

    A key that skipped normalisation would silently never match anything --
    `find_entities(name=...)` compares `normalized_name` exactly -- and the
    failure would look like "the judgement did nothing" rather than like a
    bug. `of` is the only constructor call sites use, for that reason.
    """
    assert EntityKey.of("Dr. Grant", "person") == EntityKey.of("  dr. grant ", "person")
    assert EntityKey.of("Grant", "person") != EntityKey.of("Grant", "organisation")


def test_a_key_is_hashable_so_the_state_can_index_by_it():
    """The fold keys dicts and sets by this, so frozen-and-hashable is load-bearing."""
    assert len({EntityKey.of("Grant", "person"), EntityKey.of("grant", "person")}) == 1


def test_a_key_is_frozen():
    key = EntityKey.of("Grant", "person")
    with pytest.raises(ValidationError):
        key.normalized_name = "other"


def test_the_events_carry_their_aggregate_type():
    """Bound here rather than at every construction site; the repository reads it."""
    same = EntitiesHeldSame(
        aggregate_id=None,
        keys=[EntityKey.of("JFK", "person"), EntityKey.of("John F. Kennedy", "person")],
        reason="same president",
    )
    assert same.aggregate_type == "EntityJudgements"
    distinct = EntitiesHeldDistinct(
        aggregate_id=None,
        left=EntityKey.of("Iran", "place"),
        right=EntityKey.of("Iraq", "place"),
        reason="different countries",
    )
    assert distinct.aggregate_type == "EntityJudgements"
    withdrawn = JudgementWithdrawn(
        aggregate_id=None, judgement_id=same.event_id, reason="mistake"
    )
    assert withdrawn.aggregate_type == "EntityJudgements"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.domain.judgements'`

- [ ] **Step 3: Write minimal implementation**

Create `research_team/domain/judgements.py`:

```python
"""What a human has decided about which names are the same thing.

Consolidation reaches the adjudicator for 2 of 10 genuine duplicates --
measured on 2026-08-14 against a real `nomic-embed-text`, and recorded in
BACKLOG B58 with the table. Four attempts to close that by scoring failed for
one reason: every signal derived from document context (graph neighbours,
descriptions, source snippets) pulls true cross-document pairs apart, because
two documents about one entity describe *different facets* of it. The name is
the only document-invariant signal there is.

So this aggregate is the manual override, and its key is the only key that can
carry across documents. Entity ids cannot: they are
`uuid5(uuid5(uuid5(tenant_id, source_id), entity_type), normalize_name(name))`,
so `source_id` is in the hash and "Grant" in two documents is two ids by
construction -- which is why cross-document duplicates exist as separate nodes
at all. An id-keyed judgement would survive `/rebuild` and still say nothing
about the next document, leaving a human to re-answer the same question per
document. That treadmill is what this exists to end.

**The cost, stated because it is real.** A name-keyed judgement cannot express
"distinct here, same there". A project holding both `Mercury` the planet and
`Mercury` the element cannot keep them apart in one place and together in
another. Accepted deliberately; per-id judgements remain addable later as a
second kind without disturbing this one.
"""

from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import BaseModel, ConfigDict
from redstring.domain.similarity import normalize_name


class EntityKey(BaseModel):
    """One name-and-type a judgement can be about.

    Frozen and hashable because the fold indexes dicts and sets by it.
    """

    model_config = ConfigDict(frozen=True)

    normalized_name: str
    entity_type: str

    @classmethod
    def of(cls, name: str, entity_type: str) -> "EntityKey":
        """Build a key, normalising the name exactly as redstring does.

        The only constructor call sites should use. Constructing the model
        directly with an unnormalised name yields a key that matches nothing,
        and the symptom is a judgement that appears to do nothing rather than
        an error.
        """
        return cls(normalized_name=normalize_name(name), entity_type=entity_type)


@register_event
class EntitiesHeldSame(DomainEvent):
    """A human said these names denote one thing."""

    aggregate_type: str = "EntityJudgements"
    keys: list[EntityKey]
    reason: str


@register_event
class EntitiesHeldDistinct(DomainEvent):
    """A human said these two names never denote one thing."""

    aggregate_type: str = "EntityJudgements"
    left: EntityKey
    right: EntityKey
    reason: str


@register_event
class JudgementWithdrawn(DomainEvent):
    """A human took back an earlier judgement.

    Compensating rather than a delete: the judgement stays in the log and the
    fold stops applying it, so "what did I once believe" is still answerable.
    """

    aggregate_type: str = "EntityJudgements"
    judgement_id: UUID
    reason: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the ruff gates**

Run: `uv run ruff check . && uv run ruff format .`
Expected: "All checks passed!" — commit any reformatting with the task.

- [ ] **Step 6: Commit**

```bash
git add research_team/domain/judgements.py tests/domain/test_judgements.py
git commit -m "Entity judgements: the key, and the three facts a human can state

Keyed by normalized name and entity type because entity ids hash source_id
and so are document-scoped -- an id-keyed judgement survives rebuild and
still says nothing about the next document. The cost is that
context-dependent identity cannot be expressed; written down in the module
docstring rather than discovered later."
```

---

### Task 2: State and fold

**Files:**
- Modify: `research_team/domain/judgements.py`
- Test: `tests/domain/test_judgements.py`

**Interfaces:**
- Consumes: `EntityKey`, `EntitiesHeldSame`, `EntitiesHeldDistinct`, `JudgementWithdrawn` from Task 1.
- Produces: `JudgementRecord` (pydantic model: `kind: Literal["same","distinct"]`, `keys: list[EntityKey]`, `reason: str`, `withdrawn_reason: str | None = None`); `JudgementsState` with fields `judgements_id: UUID | None`, `judgements: dict[UUID, JudgementRecord]`, and methods `group_for(key) -> frozenset[EntityKey]` and `are_held_distinct(a, b) -> bool`; `initial_state() -> JudgementsState`; `evolve(state, event) -> JudgementsState`.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/test_judgements.py`:

```python
from research_team.domain.judgements import evolve, initial_state

JFK = EntityKey.of("JFK", "person")
JOHN = EntityKey.of("John F. Kennedy", "person")
KENNEDY = EntityKey.of("Kennedy", "person")
IRAN = EntityKey.of("Iran", "place")
IRAQ = EntityKey.of("Iraq", "place")


def _fold(*events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_a_same_judgement_puts_both_keys_in_one_group():
    state = _fold(EntitiesHeldSame(aggregate_id=None, keys=[JFK, JOHN], reason="r"))

    assert state.group_for(JFK) == frozenset({JFK, JOHN})
    assert state.group_for(JOHN) == frozenset({JFK, JOHN})


def test_a_key_nobody_judged_is_alone_in_its_group():
    """Alone rather than absent, so callers need no None branch."""
    assert initial_state().group_for(JFK) == frozenset({JFK})


def test_same_judgements_are_transitive():
    """A=B and B=C makes one group of three, which is why groups beat pairs.

    Modelling pairs would put this closure in every reader instead.
    """
    state = _fold(
        EntitiesHeldSame(aggregate_id=None, keys=[JFK, JOHN], reason="r"),
        EntitiesHeldSame(aggregate_id=None, keys=[JOHN, KENNEDY], reason="r"),
    )

    assert state.group_for(JFK) == frozenset({JFK, JOHN, KENNEDY})


def test_distinct_judgements_are_not_transitive():
    """A!=B and B!=C says nothing about A and C, so distinctness is pairwise."""
    a, b, c = JFK, JOHN, KENNEDY
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=None, left=a, right=b, reason="r"),
        EntitiesHeldDistinct(aggregate_id=None, left=b, right=c, reason="r"),
    )

    assert state.are_held_distinct(a, b)
    assert not state.are_held_distinct(a, c)


def test_distinctness_is_symmetric():
    state = _fold(EntitiesHeldDistinct(aggregate_id=None, left=IRAN, right=IRAQ, reason="r"))

    assert state.are_held_distinct(IRAN, IRAQ)
    assert state.are_held_distinct(IRAQ, IRAN)


def test_withdrawing_a_same_judgement_splits_only_what_it_joined():
    """Recomputed from the survivors, not subtracted -- the subtractive version
    is wrong whenever two judgements overlap, and looks obviously right.

    Here A=B and B=C both hold; withdrawing A=B must leave B and C together
    and drop A, rather than dissolving the whole group.
    """
    first = EntitiesHeldSame(aggregate_id=None, keys=[JFK, JOHN], reason="r")
    second = EntitiesHeldSame(aggregate_id=None, keys=[JOHN, KENNEDY], reason="r")
    state = _fold(
        first,
        second,
        JudgementWithdrawn(aggregate_id=None, judgement_id=first.event_id, reason="w"),
    )

    assert state.group_for(JFK) == frozenset({JFK})
    assert state.group_for(JOHN) == frozenset({JOHN, KENNEDY})


def test_withdrawing_a_distinct_judgement_releases_the_pair():
    held = EntitiesHeldDistinct(aggregate_id=None, left=IRAN, right=IRAQ, reason="r")
    state = _fold(
        held, JudgementWithdrawn(aggregate_id=None, judgement_id=held.event_id, reason="w")
    )

    assert not state.are_held_distinct(IRAN, IRAQ)


def test_a_withdrawn_judgement_is_kept_with_its_reason():
    """A compensating event, not a delete: the audit trail survives."""
    held = EntitiesHeldSame(aggregate_id=None, keys=[JFK, JOHN], reason="same man")
    state = _fold(
        held, JudgementWithdrawn(aggregate_id=None, judgement_id=held.event_id, reason="wrong")
    )

    record = state.judgements[held.event_id]
    assert record.reason == "same man"
    assert record.withdrawn_reason == "wrong"


def test_an_unknown_event_leaves_the_state_alone():
    """Total on purpose, so a stream carrying an event this build does not know
    still replays instead of failing halfway through."""
    state = _fold(EntitiesHeldSame(aggregate_id=None, keys=[JFK, JOHN], reason="r"))

    assert evolve(state, CorpusDocumentStored(
        aggregate_id=uuid4(), source_id="s", text="t", sha256="d"
    )) == state
```

Add these imports at the top of the test file:

```python
from uuid import uuid4

from research_team.domain.corpus import CorpusDocumentStored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: FAIL — `ImportError: cannot import name 'evolve'`

- [ ] **Step 3: Write minimal implementation**

Append to `research_team/domain/judgements.py` (add `Literal` to the `typing` import and `Field` to the pydantic import):

```python
class JudgementRecord(BaseModel):
    """One judgement as the fold keeps it, live or withdrawn."""

    kind: Literal["same", "distinct"]
    keys: list[EntityKey]
    reason: str
    withdrawn_reason: str | None = None
    """Set means the fold no longer applies it. The record stays, so the
    decision and its retraction both remain auditable."""


class JudgementsState(BaseModel):
    """Everything derivable from this project's judgement stream.

    Holds the judgements and derives groups on demand rather than caching
    them. Withdrawal makes a cache the harder half: removing one judgement can
    split a group, leave it whole, or do nothing, depending on what else joined
    those keys, so the honest incremental update is a recompute anyway. The set
    is human-authored and small.
    """

    judgements_id: UUID | None = None
    judgements: dict[UUID, JudgementRecord] = Field(default_factory=dict)

    def _live(self, kind: str) -> list[JudgementRecord]:
        return [
            record
            for record in self.judgements.values()
            if record.kind == kind and record.withdrawn_reason is None
        ]

    def group_for(self, key: EntityKey) -> frozenset[EntityKey]:
        """Every key held to denote the same thing as `key`, including itself.

        A key nobody has judged comes back alone rather than empty, so callers
        need no None branch and "no judgement" reads as "a group of one".
        """
        group = {key}
        # Fixed point rather than one pass: A=B recorded after B=C still has to
        # pull A into C's group, and the records are in event order, not
        # dependency order.
        changed = True
        while changed:
            changed = False
            for record in self._live("same"):
                members = set(record.keys)
                if members & group and not members <= group:
                    group |= members
                    changed = True
        return frozenset(group)

    def are_held_distinct(self, left: EntityKey, right: EntityKey) -> bool:
        """Whether a human has said these two are never the same thing.

        Pairwise and symmetric, and deliberately **not** transitive: "A is not
        B" and "B is not C" says nothing whatever about A and C.
        """
        pair = {left, right}
        return any(set(record.keys) == pair for record in self._live("distinct"))


def initial_state() -> JudgementsState:
    return JudgementsState()


def evolve(state: JudgementsState, event: DomainEvent) -> JudgementsState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case EntitiesHeldSame():
            record = JudgementRecord(kind="same", keys=list(event.keys), reason=event.reason)
            return state.model_copy(
                update={
                    "judgements_id": state.judgements_id or event.aggregate_id,
                    "judgements": {**state.judgements, event.event_id: record},
                }
            )

        case EntitiesHeldDistinct():
            record = JudgementRecord(
                kind="distinct", keys=[event.left, event.right], reason=event.reason
            )
            return state.model_copy(
                update={
                    "judgements_id": state.judgements_id or event.aggregate_id,
                    "judgements": {**state.judgements, event.event_id: record},
                }
            )

        case JudgementWithdrawn():
            existing = state.judgements.get(event.judgement_id)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "judgements": {
                        **state.judgements,
                        event.judgement_id: existing.model_copy(
                            update={"withdrawn_reason": event.reason}
                        ),
                    }
                }
            )

        case _:
            return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the ruff gates and commit**

```bash
uv run ruff check . && uv run ruff format .
git add research_team/domain/judgements.py tests/domain/test_judgements.py
git commit -m "Entity judgements: the fold, with groups derived rather than cached

Same-judgements are transitive and distinct-judgements are not, so groups are
a union over the live same-records and distinctness stays pairwise.

Withdrawal recomputes from the survivors instead of subtracting keys from a
cached group. Subtraction is wrong whenever two judgements overlap -- A=B and
B=C, withdraw A=B, and B must stay with C -- and it is the version that looks
obviously right, so the test names the case."
```

---

### Task 3: Commands and refusals

**Files:**
- Modify: `research_team/domain/judgements.py`
- Test: `tests/domain/test_judgements.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: frozen dataclasses `HoldSame(judgements_id: UUID, keys: list[EntityKey], reason: str)`, `HoldDistinct(judgements_id: UUID, left: EntityKey, right: EntityKey, reason: str)`, `WithdrawJudgement(judgement_id: UUID, reason: str)`; union `JudgementCommand`; `decide(command, state) -> list[DomainEvent]`.

Note `HoldSame`/`HoldDistinct` carry `judgements_id` because either may be the creation command — mirroring `StoreSourceDocument.corpus_id`, whose comment explains the same thing. `WithdrawJudgement` does not, because it can only follow one.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/test_judgements.py`:

```python
from eventsource import CommandRejectedError

from research_team.domain.judgements import (
    HoldDistinct,
    HoldSame,
    WithdrawJudgement,
    decide,
)

PROJECT = uuid4()


def test_holding_two_names_same_produces_one_event():
    events = decide(
        HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="same president"),
        initial_state(),
    )

    assert len(events) == 1
    assert events[0].keys == [JFK, JOHN]
    assert events[0].aggregate_id == PROJECT


def test_every_judgement_requires_a_reason():
    """The reason is what the aliases panel shows and the only record of why a
    human decided something. Blank is refused rather than stored empty."""
    for command in (
        HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="  "),
        HoldDistinct(judgements_id=PROJECT, left=IRAN, right=IRAQ, reason=""),
    ):
        with pytest.raises(CommandRejectedError, match="reason"):
            decide(command, initial_state())


def test_holding_fewer_than_two_distinct_keys_same_is_refused():
    with pytest.raises(CommandRejectedError, match="two"):
        decide(HoldSame(judgements_id=PROJECT, keys=[JFK], reason="r"), initial_state())
    with pytest.raises(CommandRejectedError, match="two"):
        decide(HoldSame(judgements_id=PROJECT, keys=[JFK, JFK], reason="r"), initial_state())


def test_holding_a_key_distinct_from_itself_is_refused():
    with pytest.raises(CommandRejectedError, match="itself"):
        decide(
            HoldDistinct(judgements_id=PROJECT, left=JFK, right=JFK, reason="r"),
            initial_state(),
        )


def test_holding_same_what_is_already_held_distinct_is_refused():
    state = _fold(EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r"))

    with pytest.raises(CommandRejectedError, match="held distinct"):
        decide(HoldSame(judgements_id=PROJECT, keys=[IRAN, IRAQ], reason="r"), state)


def test_holding_distinct_what_is_already_one_group_is_refused():
    state = _fold(EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    with pytest.raises(CommandRejectedError, match="held same"):
        decide(HoldDistinct(judgements_id=PROJECT, left=JFK, right=JOHN, reason="r"), state)


def test_a_same_judgement_that_would_transitively_unite_a_distinct_pair_is_refused():
    """The refusal that is easy to miss, and the reason it is checked on the
    prospective *group* rather than on the command's own keys.

    A and C are held distinct. Holding A=B is legal on its face, but B is
    already grouped with C, so the union would put A and C together -- and the
    contradiction only appears after the merge. Would pass with the naive
    check that only compares the command's own key pairs.
    """
    a, b, c = JFK, JOHN, KENNEDY
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=a, right=c, reason="r"),
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[b, c], reason="r"),
    )

    with pytest.raises(CommandRejectedError, match="held distinct"):
        decide(HoldSame(judgements_id=PROJECT, keys=[a, b], reason="r"), state)


def test_withdrawing_an_unknown_judgement_is_refused():
    with pytest.raises(CommandRejectedError, match="unknown"):
        decide(WithdrawJudgement(judgement_id=uuid4(), reason="r"), initial_state())


def test_withdrawing_twice_is_refused():
    held = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r")
    state = _fold(
        held, JudgementWithdrawn(aggregate_id=PROJECT, judgement_id=held.event_id, reason="w")
    )

    with pytest.raises(CommandRejectedError, match="already withdrawn"):
        decide(WithdrawJudgement(judgement_id=held.event_id, reason="again"), state)


def test_a_refusal_names_the_conflicting_judgement_so_a_ui_can_offer_to_undo_it():
    """A dead end is a worse error than one that says what to withdraw first."""
    conflict = EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r")
    state = _fold(conflict)

    with pytest.raises(CommandRejectedError, match=str(conflict.event_id)):
        decide(HoldSame(judgements_id=PROJECT, keys=[IRAN, IRAQ], reason="r"), state)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: FAIL — `ImportError: cannot import name 'HoldSame'`

- [ ] **Step 3: Write minimal implementation**

Append to `research_team/domain/judgements.py` (add `from dataclasses import dataclass` and `CommandRejectedError` to the eventsource import):

```python
@dataclass(frozen=True)
class HoldSame:
    #: Which project's judgements. Carried on the command rather than read off
    #: the state because this may be the creation command, exactly as
    #: `StoreSourceDocument.corpus_id` is.
    judgements_id: UUID
    keys: list[EntityKey]
    reason: str


@dataclass(frozen=True)
class HoldDistinct:
    judgements_id: UUID
    left: EntityKey
    right: EntityKey
    reason: str


@dataclass(frozen=True)
class WithdrawJudgement:
    #: No `judgements_id`: a withdrawal can only follow a judgement, so the
    #: stream already exists and the state carries its id.
    judgement_id: UUID
    reason: str


JudgementCommand = HoldSame | HoldDistinct | WithdrawJudgement


def _prospective_group(state: JudgementsState, keys: list[EntityKey]) -> set[EntityKey]:
    """Every key that would end up in one group if `keys` were held same."""
    group: set[EntityKey] = set()
    for key in keys:
        group |= state.group_for(key)
    return group


def decide(command: JudgementCommand, state: JudgementsState) -> list[DomainEvent]:
    """Which judgements are legal, and what facts they produce.

    Contradictions are refused **here** rather than resolved later by
    `JudgedCandidates`. A finder that had to reconcile "same" against "not the
    same" would be choosing on a human's behalf, silently, at scoring time --
    and whichever way it chose would be invisible.
    """
    match command:
        case HoldSame(judgements_id=judgements_id, keys=keys, reason=reason):
            if not reason.strip():
                raise CommandRejectedError("a judgement requires a reason")
            unique = set(keys)
            if len(unique) < 2:
                raise CommandRejectedError(
                    "holding names the same needs at least two distinct keys"
                )
            group = _prospective_group(state, keys)
            # Checked over the prospective group, not the command's own keys:
            # holding A=B is a contradiction when B already shares a group with
            # C and A is held distinct from C, and that only appears after the
            # union.
            for judgement_id, record in state.judgements.items():
                if record.kind != "distinct" or record.withdrawn_reason is not None:
                    continue
                if set(record.keys) <= group:
                    raise CommandRejectedError(
                        f"those names are held distinct by judgement {judgement_id}; "
                        f"withdraw it first"
                    )
            return [
                EntitiesHeldSame(
                    aggregate_id=judgements_id, keys=list(keys), reason=reason
                )
            ]

        case HoldDistinct(
            judgements_id=judgements_id, left=left, right=right, reason=reason
        ):
            if not reason.strip():
                raise CommandRejectedError("a judgement requires a reason")
            if left == right:
                raise CommandRejectedError("a name cannot be held distinct from itself")
            if right in state.group_for(left):
                raise CommandRejectedError(
                    "those names are held same; withdraw that judgement first"
                )
            return [
                EntitiesHeldDistinct(
                    aggregate_id=judgements_id, left=left, right=right, reason=reason
                )
            ]

        case WithdrawJudgement(judgement_id=judgement_id, reason=reason):
            if not reason.strip():
                raise CommandRejectedError("a withdrawal requires a reason")
            record = state.judgements.get(judgement_id)
            if record is None:
                raise CommandRejectedError(f"unknown judgement {judgement_id}")
            if record.withdrawn_reason is not None:
                raise CommandRejectedError(
                    f"judgement {judgement_id} was already withdrawn: "
                    f"{record.withdrawn_reason}"
                )
            return [
                JudgementWithdrawn(
                    aggregate_id=state.judgements_id,
                    judgement_id=judgement_id,
                    reason=reason,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Run the ruff gates and commit**

```bash
uv run ruff check . && uv run ruff format .
git add research_team/domain/judgements.py tests/domain/test_judgements.py
git commit -m "Entity judgements: refuse contradictions at command time

A contradiction resolved by the finder instead would be the finder choosing
on a human's behalf, silently, at scoring time.

The transitive case is the one worth reading: holding A=B is legal on its
face and a contradiction when B already shares a group with C and A is held
distinct from C. Checked over the prospective group rather than the command's
own keys, because the conflict only exists after the union.

Refusals name the conflicting judgement's id so a caller can offer to
withdraw it rather than presenting a dead end."
```

---

### Task 4: The aggregate, its repository, and exports

**Files:**
- Modify: `research_team/domain/judgements.py`
- Modify: `research_team/domain/__init__.py`
- Modify: `research_team/infrastructure/persistence/event_store.py`
- Test: `tests/domain/test_judgements.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: `EntityJudgements(DeciderAggregate[JudgementsState, JudgementCommand])` with `aggregate_type = "EntityJudgements"`; `build_judgements_repository(store, publisher=None, snapshot_store=None) -> AggregateRepository[EntityJudgements]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/test_judgements.py`:

```python
from research_team.domain import EntityJudgements


def test_the_aggregate_executes_a_command_and_folds_its_event():
    judgements = EntityJudgements()
    judgements.execute(HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    assert judgements.state.group_for(JFK) == frozenset({JFK, JOHN})


def test_the_aggregate_type_keeps_the_stream_apart_from_the_corpus():
    """Project, corpus and judgements share one UUID and are three streams.

    `AggregateRepository` puts `aggregate_type` into the `StreamId`, so this
    string is the whole separation.
    """
    assert EntityJudgements.aggregate_type == "EntityJudgements"
```

And in `tests/infrastructure/test_schema_evolution.py`, follow the file's existing pattern to add one case per new event — write an old-shaped payload straight into the events table and read it back. Read the file first and copy the shape of the nearest existing case; do not invent a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_judgements.py -v`
Expected: FAIL — `ImportError: cannot import name 'EntityJudgements'`

- [ ] **Step 3: Write minimal implementation**

Append to `research_team/domain/judgements.py` (add `DeciderAggregate` to the eventsource import):

```python
class EntityJudgements(DeciderAggregate[JudgementsState, JudgementCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Corpus`'s shape exactly: the class attributes bind directly to the
    module-level functions rather than wrapping them in new method bodies, so
    there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "EntityJudgements"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
```

In `research_team/domain/__init__.py`, add an import block alphabetically among the others and extend `__all__` if the file defines one:

```python
from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityJudgements,
    EntityKey,
    HoldDistinct,
    HoldSame,
    JudgementCommand,
    JudgementRecord,
    JudgementsState,
    JudgementWithdrawn,
    WithdrawJudgement,
)
```

In `research_team/infrastructure/persistence/event_store.py`, add beside `build_corpus_repository` and import `EntityJudgements`:

```python
def build_judgements_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[EntityJudgements]:
    """A project's entity judgements, over the same log as its corpus.

    Shares the project's UUID and is kept apart by `aggregate_type`, exactly as
    the corpus is, so nothing has to invent or store a third id.

    Snapshots are on at the house threshold. Affordable because the state holds
    only human-authored judgements -- a set that grows with decisions a person
    made, not with documents ingested.
    """
    return AggregateRepository(
        store,
        EntityJudgements,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
    )
```

Copy the remaining constructor arguments from `build_corpus_repository` verbatim — read it first; it passes a snapshot threshold this snippet elides.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_judgements.py tests/infrastructure/test_schema_evolution.py -v`
Expected: PASS

- [ ] **Step 5: Run the ruff gates and commit**

```bash
uv run ruff check . && uv run ruff format .
git add research_team/domain/judgements.py research_team/domain/__init__.py \
        research_team/infrastructure/persistence/event_store.py \
        tests/domain/test_judgements.py tests/infrastructure/test_schema_evolution.py
git commit -m "Entity judgements: the aggregate and its repository

A third stream over the project's UUID, kept apart by aggregate_type the way
the corpus already is. Schema-evolution cases added for all three events,
because that file is the only thing standing between this and the discovery
much later that an old project no longer loads."
```

---

### Task 5: `JudgedCandidates`

**Files:**
- Create: `research_team/infrastructure/knowledge/judged_candidates.py`
- Test: `tests/infrastructure/test_judged_candidates.py`

**Interfaces:**
- Consumes: `JudgementsState`, `EntityKey` from the domain.
- Produces: `JudgedCandidates(inner: CandidateSource, *, graph_store, tenant_id: UUID, judgements: JudgementsState)` with `async def candidates(self, subject, *, minimum_score: float = 0.0) -> list[ScoredCandidate]`.

- [ ] **Step 1: Write the failing test**

```python
"""What a human's judgements do to consolidation's candidate list.

Asserted against fakes rather than a real `CandidateFinder`: the point of this
class is what it adds and removes, and a real finder would make every
assertion depend on scoring behaviour these tests are not about.
"""

from uuid import uuid4

import pytest
from redstring.consolidation.candidates import ScoredCandidate
from redstring.domain.similarity import SimilarityFeatures

from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    evolve,
    initial_state,
)
from research_team.infrastructure.knowledge.judged_candidates import JudgedCandidates

TENANT = uuid4()


class _Entity:
    """Enough of redstring's `Entity` for these tests: an id, a name, a type."""

    def __init__(self, name: str, entity_type: str = "person") -> None:
        self.id = uuid4()
        self.name = name
        self.entity_type = entity_type


class _FakeInner:
    def __init__(self, *candidates: ScoredCandidate) -> None:
        self._candidates = list(candidates)
        self.asked_with: float | None = None

    async def candidates(self, subject, *, minimum_score: float = 0.0):
        self.asked_with = minimum_score
        return list(self._candidates)


class _FakeGraph:
    """Answers `find_entities(name=...)` the way redstring's stores do."""

    def __init__(self, *entities: _Entity) -> None:
        self._entities = list(entities)

    async def find_entities(self, tenant_id, *, name=None, **_):
        from redstring.domain.similarity import normalize_name

        if name is None:
            return list(self._entities)
        return [e for e in self._entities if normalize_name(e.name) == normalize_name(name)]


def _scored(entity: _Entity, score: float) -> ScoredCandidate:
    return ScoredCandidate(
        entity=entity, features=SimilarityFeatures(name=score), score=score
    )


def _state(*events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


@pytest.mark.asyncio
async def test_a_held_same_counterpart_is_injected_even_when_it_scores_nothing():
    """The `JFK` case, and the reason injection exists rather than reweighting.

    `JFK`/`John F. Kennedy` scores 0.609 against a real embedding model and
    shares no blocking prefix, so `CandidateFinder` never surfaces it at all --
    no threshold change reaches a candidate that is never built. The inner
    finder here returns nothing, which is exactly that situation.

    Would pass with the feature removed only if the inner finder returned the
    counterpart itself; it deliberately returns an empty list so it cannot.
    """
    subject = _Entity("JFK")
    counterpart = _Entity("John F. Kennedy")
    finder = JudgedCandidates(
        _FakeInner(),
        graph_store=_FakeGraph(counterpart),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[EntityKey.of("JFK", "person"), EntityKey.of("John F. Kennedy", "person")],
                reason="same man",
            )
        ),
    )

    found = await finder.candidates(subject, minimum_score=0.75)

    assert [c.entity.id for c in found] == [counterpart.id]
    assert found[0].score == 1.0, "above HIGH_SIMILARITY, so it merges without a model call"


@pytest.mark.asyncio
async def test_a_held_distinct_candidate_is_dropped_before_it_is_scored():
    """Dropped rather than vetoed at the adjudicator, which is the whole reason
    the seam is the finder.

    An adjudicator-level veto is skipped entirely by a pair scoring at or above
    `HIGH_SIMILARITY` -- unreachable cross-document today, reachable if B58
    lands, where `Retriever`/`Retrievers` scores 0.968. The 1.0 here is that
    case.
    """
    subject = _Entity("Iran", "place")
    other = _Entity("Iraq", "place")
    finder = JudgedCandidates(
        _FakeInner(_scored(other, 1.0)),
        graph_store=_FakeGraph(other),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldDistinct(
                aggregate_id=TENANT,
                left=EntityKey.of("Iran", "place"),
                right=EntityKey.of("Iraq", "place"),
                reason="different countries",
            )
        ),
    )

    assert await finder.candidates(subject, minimum_score=0.75) == []


@pytest.mark.asyncio
async def test_an_empty_judgement_set_changes_nothing():
    """The property that makes this safe to wire in before any UI exists."""
    subject = _Entity("Grant")
    other = _Entity("Dr. Grant")
    inner = _FakeInner(_scored(other, 0.8))
    finder = JudgedCandidates(
        inner, graph_store=_FakeGraph(other), tenant_id=TENANT, judgements=initial_state()
    )

    found = await finder.candidates(subject, minimum_score=0.75)

    assert [(c.entity.id, c.score) for c in found] == [(other.id, 0.8)]
    assert inner.asked_with == 0.75, "the threshold is passed through untouched"


@pytest.mark.asyncio
async def test_the_subject_is_never_its_own_candidate():
    """A group contains the subject's own key, so the lookup finds the subject."""
    subject = _Entity("JFK")
    finder = JudgedCandidates(
        _FakeInner(),
        graph_store=_FakeGraph(subject),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[EntityKey.of("JFK", "person"), EntityKey.of("John F. Kennedy", "person")],
                reason="r",
            )
        ),
    )

    assert await finder.candidates(subject) == []


@pytest.mark.asyncio
async def test_an_injected_candidate_is_not_duplicated_when_the_finder_also_found_it():
    subject = _Entity("JFK")
    counterpart = _Entity("John F. Kennedy")
    finder = JudgedCandidates(
        _FakeInner(_scored(counterpart, 0.8)),
        graph_store=_FakeGraph(counterpart),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[EntityKey.of("JFK", "person"), EntityKey.of("John F. Kennedy", "person")],
                reason="r",
            )
        ),
    )

    found = await finder.candidates(subject)

    assert len(found) == 1
    assert found[0].score == 1.0, "the judgement wins over the computed score"


@pytest.mark.asyncio
async def test_candidates_come_back_in_descending_score_with_ties_broken_by_id():
    """`CandidateSource`'s ordering contract, and it is not cosmetic: a cutoff
    falling inside a tie must be decided the same way on every run, or
    consolidation stops being reproducible. Injected candidates all score 1.0
    and so are all one tie.
    """
    subject = _Entity("JFK")
    first, second = _Entity("John F. Kennedy"), _Entity("Kennedy")
    finder = JudgedCandidates(
        _FakeInner(_scored(_Entity("Someone"), 0.9)),
        graph_store=_FakeGraph(first, second),
        tenant_id=TENANT,
        judgements=_state(
            EntitiesHeldSame(
                aggregate_id=TENANT,
                keys=[
                    EntityKey.of("JFK", "person"),
                    EntityKey.of("John F. Kennedy", "person"),
                    EntityKey.of("Kennedy", "person"),
                ],
                reason="r",
            )
        ),
    )

    found = await finder.candidates(subject)

    assert [c.score for c in found] == sorted((c.score for c in found), reverse=True)
    injected = [str(c.entity.id) for c in found if c.score == 1.0]
    assert injected == sorted(injected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_judged_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""Consolidation's candidate list, with a human's judgements applied.

redstring exposes `CandidateSource` as a Protocol and `Consolidator.resolve`
takes `finder=`, which is the whole seam this needs. One layer covers both
directions, at the place where "is this a candidate" is already decided.

**Why injection rather than reweighting.** `JFK`/`John F. Kennedy` scores 0.609
against a real embedding model (measured 2026-08-14; BACKLOG B58 carries the
table) and the two names share no blocking prefix, so `CandidateFinder` never
builds that candidate at all. No threshold or weight change reaches a pair that
is never scored. Injecting it sidesteps scoring, which is the only mechanism
that works for the cases this feature exists for.

**Why dropping rather than vetoing at the adjudicator.** A veto placed on
`MergeAdjudicator` is skipped entirely by any pair scoring at or above
`HIGH_SIMILARITY` (0.92), because that band merges without asking. That is
unreachable cross-document today -- a present `graph = 0.0` caps such a pair at
0.8 -- but becomes reachable if B58 lands, where `Retriever`/`Retrievers`
scores 0.968. Dropping at the candidate stage is correct under both, so the
seam does not have to move later.
"""

from typing import Any
from uuid import UUID

from redstring.consolidation.candidates import ScoredCandidate
from redstring.domain.similarity import SimilarityFeatures

from research_team.domain.judgements import EntityKey, JudgementsState

#: The score an injected candidate carries.
#:
#: Above `HIGH_SIMILARITY` (0.92), so a held-same pair merges without a model
#: call -- a human has already made the judgement the adjudicator would be
#: asked to make, and paying for it again would be asking a model to
#: second-guess the person who owns the graph.
JUDGED_SAME_SCORE = 1.0


class JudgedCandidates:
    """A `CandidateSource` that applies this project's judgements to another.

    With an empty judgement set this is a pure passthrough, which is what makes
    it safe to wire in before anything can create a judgement.
    """

    def __init__(
        self,
        inner: Any,
        *,
        graph_store: Any,
        tenant_id: UUID,
        judgements: JudgementsState,
    ) -> None:
        self._inner = inner
        self._graph = graph_store
        self._tenant_id = tenant_id
        self._judgements = judgements

    async def candidates(
        self, subject: Any, *, minimum_score: float = 0.0
    ) -> list[ScoredCandidate]:
        subject_key = EntityKey.of(subject.name, subject.entity_type)
        group = self._judgements.group_for(subject_key)

        found = await self._inner.candidates(subject, minimum_score=minimum_score)
        kept = [
            candidate
            for candidate in found
            if not self._judgements.are_held_distinct(
                subject_key, EntityKey.of(candidate.entity.name, candidate.entity.entity_type)
            )
        ]

        injected = await self._injected(subject, group)
        # Injected wins over computed: the same entity found by both keeps the
        # judgement's score, not the finder's.
        by_id = {candidate.entity.id: candidate for candidate in kept}
        by_id.update({candidate.entity.id: candidate for candidate in injected})

        # `CandidateSource` requires descending score with ties broken by a
        # further total order -- `CandidateFinder` uses ascending entity id as
        # a string. Injected candidates all share one score and so are all one
        # tie; without the second key a cutoff inside it would fall differently
        # between runs and consolidation would stop being reproducible.
        return sorted(by_id.values(), key=lambda c: (-c.score, str(c.entity.id)))

    async def _injected(self, subject: Any, group: frozenset[EntityKey]) -> list[ScoredCandidate]:
        """Entities matching any other key in the subject's held-same group."""
        subject_key = EntityKey.of(subject.name, subject.entity_type)
        injected: list[ScoredCandidate] = []
        for key in group:
            if key == subject_key:
                continue
            entities = await self._graph.find_entities(
                self._tenant_id, name=key.normalized_name
            )
            for entity in entities:
                if entity.id == subject.id:
                    continue
                if entity.entity_type != key.entity_type:
                    continue
                injected.append(
                    ScoredCandidate(
                        entity=entity,
                        # Every feature absent, deliberately. The score did not
                        # come from these and saying otherwise would put a
                        # number nobody computed into the explanation a
                        # threshold decision is read back from.
                        features=SimilarityFeatures(),
                        score=JUDGED_SAME_SCORE,
                    )
                )
        return injected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/infrastructure/test_judged_candidates.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the ruff gates and commit**

```bash
uv run ruff check . && uv run ruff format .
git add research_team/infrastructure/knowledge/judged_candidates.py \
        tests/infrastructure/test_judged_candidates.py
git commit -m "Entity judgements: apply them where candidates are chosen

Injection rather than reweighting, because JFK/John F. Kennedy scores 0.609
and shares no blocking prefix -- it is never a candidate, so no threshold
change reaches it.

Dropping rather than an adjudicator veto, because a veto is skipped by
anything scoring 0.92 or above. That is unreachable cross-document today and
reachable if B58 lands, so the candidate stage is the seam that survives
both."
```

---

### Task 6: Wire it into `RedstringKnowledge`

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: `JudgedCandidates`, `EntityJudgements`.
- Produces: `RedstringKnowledge(..., judgements: AggregateRepository[EntityJudgements] | None = None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/infrastructure/test_redstring_adapter.py`, following the file's existing fixture style:

```python
@pytest.mark.asyncio
async def test_a_held_same_judgement_merges_two_documents_entities(
    tmp_path, build_adapter, judgements_repository
):
    """End to end: a human's judgement, then an ingest that obeys it.

    Proved red before it was trusted green: with `judgements=None` passed to
    `build_adapter` and everything else identical, `search` finds two nodes.
    """
    ...


@pytest.mark.asyncio
async def test_without_a_judgements_repository_nothing_changes(tmp_path, build_adapter):
    """The passthrough property, asserted through the adapter rather than the
    finder, because this is the guarantee every existing call site relies on."""
    ...
```

Write both bodies against the fixtures already in `tests/infrastructure/conftest.py`. Extend `build_adapter` with a `judgements=None` parameter, defaulting to None so every existing caller is untouched — read its docstring first; it explains why its defaults differ from the application's.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -k judgement -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

In `redstring_adapter.py`: add the constructor parameter, store it, and build the finder in `_consolidate`.

```python
        # Loaded once per call, not per entity. An ingest resolves every
        # extracted entity in this loop, and a human cannot make a judgement
        # part-way through it -- reloading per entity would be one event-store
        # read each to re-learn something that cannot have changed.
        finder = None
        if self._judgements is not None:
            judgements = await self._judgements.load_or_create(self._project_id)
            finder = JudgedCandidates(
                CandidateFinder(self._store, vector_store=self._vectors),
                graph_store=self._store,
                tenant_id=self._project_id,
                judgements=judgements.state,
            )
```

and pass `finder=finder` to `resolve`. `Consolidator.resolve` treats `finder=None` as "use the default", so the None case needs no branch at the call site.

Construct `CandidateFinder` with the same arguments the `Consolidator` is given in `__init__` — today that is the store and `vector_store`, with `weights` and `use_graph_signal` left at redstring's defaults. **Do not pass a `weights=` here**: commit 6c2ae4a withdrew a reweight for lack of evidence, and a second one hidden in the finder would be worse.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Wire the composition root**

Add `build_judgements_repository` to wherever `build_corpus_repository` is called in `research_team/composition.py`, and pass the result to `RedstringKnowledge`. Read the surrounding code first and follow it exactly.

- [ ] **Step 6: Run all four gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

Expected: all pass. `pytest` takes about 3.5 minutes; do not run a second pytest alongside it.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Entity judgements: consolidation consults them

Optional on the adapter, so every existing construction site keeps today's
behaviour: resolve() reads finder=None as 'use the default', and an empty
judgement set makes JudgedCandidates a passthrough anyway.

State is loaded once per _consolidate call rather than per entity -- a human
cannot make a judgement part-way through an ingest's loop, so a reload per
entity would be one event-store read each to re-learn something unchanged.
The repository rather than a snapshot is passed in because reconsolidate is a
separate entry point that must see judgements made since the last ingest."
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: `EntityKey` → 1; events → 1; groups/union-find and withdrawal-recompute → 2; commands and all five refusals → 3; aggregate and repository → 4; `JudgedCandidates`, injection, dropping, ordering contract → 5; wiring, load-once, optional repository → 6. Spec testing items 1-8 are covered by Tasks 2, 3, 5 and 6; schema evolution is Task 4.

**Known gaps, deliberate.** Task 6's test bodies are described rather than written out, because they depend on fixture details in `conftest.py` and `test_redstring_adapter.py` that the implementer must read; the docstrings and the red-proof are specified. Task 4's schema-evolution cases likewise defer to the existing file's pattern rather than inventing one.

**Type consistency.** `EntityKey.of` is the constructor everywhere. `group_for`/`are_held_distinct` are the only state queries used by Task 5. `judgements_id` appears on `HoldSame`/`HoldDistinct` and not on `WithdrawJudgement`, consistently in Tasks 3 and 4. `JUDGED_SAME_SCORE` is used only in Task 5.
