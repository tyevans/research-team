# Socratic Dialogue — Plan 1 of 3: the durable dialogue

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `SocraticDialogue` aggregate, its projection, and a service that resumes a dialogue from its own read model rather than starting over when the live cache drops it — driven by a stubbed executor, so this plan ships working, testable software with no model call in it.

**Architecture:** A third event-sourced aggregate beside `AskConversation` and `Session`, with the two-table projection pattern `AskConversationStore` established. The one genuinely new machine is `SocraticDialogueService`: where `ConversationRegistry.get` mints a fresh conversation on a miss, `DialogueRegistry.get` returns `None` and the service rehydrates goal, stopping condition and history from stored turns — so an evicted dialogue resumes on the **same** stream.

**Tech Stack:** Python 3 / `eventsource-py` (aggregates, `DeclarativeProjection`, `SubscriptionManager`) / aiosqlite / pydantic / FastAPI. No frontend in this plan.

**Spec:** `docs/superpowers/specs/2026-08-17-socratic-dialogue-design.md`

---

## Why this is three plans, not one

The spec covers four subsystems that do not share a review cadence: a domain
and its persistence, a prompted agent, an HTTP streaming surface, and a
frontend facet. Planning all of it in one document means writing the last five
tasks against signatures that do not exist yet, which is where a plan's types
drift from the code it produces.

The split, and what each plan ships on its own:

| Plan | Scope | Working software it produces |
| --- | --- | --- |
| **1 — this one** | Aggregate, events, schema evolution, the two-table projection and its runner, `SocraticDialogueService` with **resumption from the read model**, composition wiring, and the read-only history routes. The executor is a **port with a stub**. | A durable, resumable dialogue: start one, record turns, evict it, resume it on the same stream, and read it back over HTTP. |
| **2 — the agent and the live surface** | `DeepAgentSocraticExecutor`, the socratic prompt **composed from pieces** (never concatenated onto `ASK_PROMPT`), the `mcq`/`cloze`-only component reference, the second executor in `composition.py` and its `create_app` parameter, the POST route and its SSE stream, and attempts recorded against the dialogue id (spec §3). | A dialogue you can hold end to end with `curl`. |
| **3 — the reader's surface** | The `FACETS` entry, the `regionOf` arm, the `App.tsx` intercept, the streaming repository and transcript fold, and goal / stopping condition rendered visibly (spec §5). | The dialogue as a place on a project. |

Plan 1 is first because the resumption machinery is the spec's own answer to
"which of these is not optional" (§2), and because Plans 2 and 3 both consume
its signatures. **Do not start Plan 2 before Plan 1's Task 4 is green** — that
task is what proves the projection is constructed, and Plan 2 adds a second
executor to the same composition function.

## Global Constraints

Every task's requirements implicitly include this section.

- **Four gates, and passing three is not passing.** `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`.
  The two ruff commands run over the **whole repository**, not the files you touched.
  This plan touches no `frontend/src` file, so `npm run verify` and the rebuilt
  `research_team/interfaces/web/static` assets are not required by any task here —
  **but if you touch one, the fifth gate applies**: `cd frontend && npm run build` and
  commit the rebuilt assets, because CI compares them and `verify` never does.
- **An event no projection handles counts as APPLIED, not rejected.** A missing
  subscription is a silently EMPTY read model answering 200 — nothing raises, nothing
  logs. **Every projection assertion in this plan must be that a ROW EXISTS with the
  value the event carried.** "The request succeeded", "`start()` returned", "replay
  completed" all pass against exactly the bug this feature is most likely to ship with.
  `EntityDefinitionRunner` was never constructed in `composition.py` and served empty
  cache misses past a full green suite.
- **Events already written are not rewritten.** Every new event must be readable
  against payloads an older build stored, and every change gets a case in
  `tests/infrastructure/test_schema_evolution.py`.
- **Every aggregate type must appear in `FEED_AGGREGATE_TYPES` or
  `UNROUTED_AGGREGATE_TYPES`.** `tests/infrastructure/test_feed_coverage.py` fails
  on a type in neither, deliberately — absence from both is indistinguishable from
  nobody having thought about it.
- **A read-model change verified only against a fresh database is unverified.** Use
  `uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db`,
  which rewrites the store id in each checkpoint's position token. **Do not delete
  `projection_checkpoints`** to get a copy up: a projection with no checkpoint replays
  the whole log, which is `/rebuild` by another name and hides the half of the bug that
  matters.
- **The application layer may not import a framework.** `tests/test_architecture.py`
  holds it to `eventsource` alone. Anything LangChain-shaped lives behind a Protocol —
  which is why this plan's executor is a port and Plan 2 implements it.
- **Do not run two `vitest` processes at once** (not exercised here, but the rule holds).

---

## The test that matters, written before anything else

Spec §9: *"a dialogue evicted from the registry and resumed must carry its goal,
its stopping condition and its prior turns, and must record onto the **same**
stream. Write it first; it is the requirement whose absence looks exactly like
working software for an hour."*

Here it is in full. **Task 1 Step 1 creates this file and watches it fail**, and
every task after it re-runs the file and records how much further it gets. It is
red for the whole of Tasks 1 and 2 and turns green in Task 3; a task that leaves
it red *for the same reason as the previous task* has not moved.

`tests/application/test_socratic_resumption.py`:

```python
"""The one requirement whose absence looks exactly like working software.

`ConversationRegistry` is 64 entries and an hour idle, and a `Conversation`
mints a fresh `conversation_id` per registry entry -- so an evicted ask resumes
with no history on a new stream. For an ask that is an accepted cost. For a
goal-directed dialogue it is a correctness bug: a reader who comes back after
lunch to a dialogue that has forgotten its goal has not resumed anything, they
have started over while believing otherwise.

Every assertion here is on what the executor was *handed* and on which stream
the events landed on. "The call returned" is compatible with a service that
silently began a second dialogue, which is precisely the failure.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.socratic import (
    DialogueRegistry,
    SocraticDialogueService,
    SocraticFraming,
    SocraticPrompt,
)
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueStarted,
    SocraticTurnRecorded,
)

PROJECT_ID = uuid4()


class RecordingExecutor:
    """Asks fixed questions and remembers exactly what it was asked with.

    The list it is constructed with is a list of the *next questions* it will
    ask, because under this surface's naming the executor's output is a prompt
    -- the system asks, the reader answers. See the ruling in the plan.

    The history it received is the assertion: a service that resumed by
    starting over would call this with an empty history and a fresh goal, and
    every other observable -- the question it then asks, the returned id, the
    status code a route would give -- would be identical.
    """

    def __init__(self, questions: list[str]) -> None:
        self._questions = list(questions)
        self.calls: list[dict] = []

    async def frame(self, *, project_id, topic):
        self.calls.append({"kind": "frame", "topic": topic})
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition=f"the reader explains {topic} in their own words",
            opening_prompt=f"What do you already believe about {topic}?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        self.calls.append(
            {
                "kind": "respond",
                "history": [(m.role, m.text) for m in history],
                "goal": goal,
                "stopping_condition": stopping_condition,
                "reply": reply,
            }
        )
        return SocraticPrompt(prompt=self._questions.pop(0))


class StubReadModel:
    """The read model the service rehydrates from, without a projection.

    Hand-held rows rather than a started `SocraticDialogueRunner`: this file is
    about the service's resumption logic, and standing up a real projection
    here would make it fail for reasons that belong in
    `tests/infrastructure/test_socratic_read_model.py`. The *composed* pairing
    is proved in `tests/integration/test_a_dialogue_survives_a_restart.py`,
    which is the file that would catch a runner nobody constructed.

    `SimpleNamespace` and not a dict, deliberately: `DialogueReadModel` is a
    structural Protocol satisfied by `SocraticDialogueRow`, so `_resume` reads
    `row.goal` and `turn.reply` as *attributes*. A dict fixture would fail on
    `AttributeError` and read as a bug in the service rather than in the test.
    """

    def __init__(self) -> None:
        self.dialogues: dict[UUID, SimpleNamespace] = {}
        self.turns: dict[UUID, list[SimpleNamespace]] = {}

    def add(self, dialogue_id: UUID, **fields) -> None:
        self.dialogues[dialogue_id] = SimpleNamespace(**fields)

    def answered(self, dialogue_id: UUID, *pairs: tuple[str, str]) -> None:
        """`(reply, prompt)` per turn -- the reader's answer and the response
        it drew, which is the order `SocraticTurnRecorded` stores them in."""
        self.turns[dialogue_id] = [
            SimpleNamespace(position=index, reply=reply, prompt=prompt)
            for index, (reply, prompt) in enumerate(pairs)
        ]

    async def get(self, dialogue_id: UUID):
        return self.dialogues.get(dialogue_id)

    async def turns_for(self, dialogue_id: UUID):
        return list(self.turns.get(dialogue_id, []))


@pytest.fixture
def transcripts() -> AggregateRepository[SocraticDialogue]:
    return AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)


def build(executor, transcripts, read_model, registry=None):
    return SocraticDialogueService(
        executor=executor,
        dialogues=registry or DialogueRegistry(now=lambda: 0.0),
        read_model=read_model,
        now=lambda: 0.0,
        transcripts=transcripts,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    )


async def drain(iterator):
    return [note async for note in iterator]


async def events_on(transcripts, dialogue_id: UUID):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(transcripts.event_store.read_stream(stream))
    ]


async def all_dialogue_ids(transcripts) -> set[UUID]:
    """Every dialogue id anything was written under.

    `read_category`, matching `test_ask_persistence.py`'s `all_events`. The
    point of several assertions below is that there is exactly ONE id, which
    reading a single known stream could never establish -- the id under
    suspicion in the failure case is the one no test knows.
    """
    return {
        envelope.event.aggregate_id
        for envelope in await collect(
            transcripts.event_store.read_category(SocraticDialogue.aggregate_type)
        )
    }


async def test_an_evicted_dialogue_resumes_on_the_same_stream(transcripts):
    """The whole feature, in one test.

    Red three distinct ways, and only the first is obvious:

    1. A `DialogueRegistry.get` that mints a fresh entry on a miss, the way
       `ConversationRegistry.get` does -- a second dialogue id appears and
       `all_dialogue_ids` comes back with two.
    2. A rehydrate that restores history but not the framing -- `goal` and
       `stopping_condition` arrive as empty strings and the executor is asked
       to continue toward nothing.
    3. A rehydrate that restores the framing but not the turns -- the executor
       is handed an empty history and asks its opening question again, which
       reads to a reader as the dialogue having forgotten the conversation
       while still knowing the topic.
    4. A rehydrate that restores the turns but drops the *opening* question --
       the history then starts with the reader answering something nobody
       asked. The opening question lives on the start event rather than on any
       turn (see `SocraticTurnRecorded`), so it is the one utterance a
       turns-only rehydrate silently loses.

    Each of those looks like working software until an hour has passed.
    """
    executor = RecordingExecutor(["Why do you think that?", "And what follows from it?"])
    read_model = StubReadModel()
    registry = DialogueRegistry(now=lambda: 0.0)
    service = build(executor, transcripts, read_model, registry)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the Nicene settlement")
    await drain(
        service.respond(
            project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="It settled Arianism."
        )
    )

    # Stand in for the projection having caught up, which in a composed build
    # is what makes the stored turns readable. Hand-fed here so this file tests
    # the service and not the subscription.
    read_model.add(
        dialogue_id,
        project_id=PROJECT_ID,
        goal="understand the Nicene settlement",
        stopping_condition="the reader explains the Nicene settlement in their own words",
        status="started",
        # The opening question, which lives on the start event because it
        # precedes every turn -- and is therefore the one utterance a
        # turns-only rehydrate would lose.
        opening_prompt="What do you already believe about the Nicene settlement?",
    )
    read_model.answered(dialogue_id, ("It settled Arianism.", "Why do you think that?"))

    # An hour passes, or 65 other dialogues happen. Same thing.
    registry.drop(dialogue_id)

    await drain(
        service.respond(
            project_id=PROJECT_ID,
            dialogue_id=dialogue_id,
            reply="Because the creed names the Son as of one substance.",
        )
    )

    resumed = executor.calls[-1]
    assert resumed["kind"] == "respond"
    # The goal and the stopping condition survived the eviction.
    assert resumed["goal"] == "understand the Nicene settlement"
    assert (
        resumed["stopping_condition"]
        == "the reader explains the Nicene settlement in their own words"
    )
    # And so did the exchange, in order -- the dialogue speaking first, because
    # that is the direction this surface runs in. The opening question comes
    # from the start event and every pair after it from a turn, which is what
    # makes the history alternate correctly with nothing stored twice.
    assert resumed["history"] == [
        ("assistant", "What do you already believe about the Nicene settlement?"),
        ("user", "It settled Arianism."),
        ("assistant", "Why do you think that?"),
    ]

    # The same stream, and only that stream. This is the assertion a service
    # that started over would fail while every other observable agreed.
    assert await all_dialogue_ids(transcripts) == {dialogue_id}
    recorded = await events_on(transcripts, dialogue_id)
    assert [type(event) for event in recorded] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticTurnRecorded,
    ]
    # The exchange: what the reader answered, and what the dialogue said back.
    # Two fields, not three -- the question this answered is the *previous*
    # turn's `prompt`, already in the log once.
    assert recorded[2].reply == "Because the creed names the Son as of one substance."
    assert recorded[2].prompt == "And what follows from it?"


async def test_a_dialogue_still_in_the_registry_is_not_re_read(transcripts):
    """The registry is still a cache, and must still be one.

    Rehydrating on every turn would be correct and would cost a read-model
    round trip per exchange -- and worse, would make the cache untested, since
    every test would pass with it removed. Red against a service that reads
    through unconditionally.
    """
    executor = RecordingExecutor(["Why?", "And?"])
    read_model = StubReadModel()
    service = build(executor, transcripts, read_model)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="Arianism")
    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="first")
    )
    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="second")
    )

    # The read model was never consulted: the stub holds nothing, so a service
    # that read through it would have found no dialogue at all.
    assert read_model.dialogues == {}
    assert executor.calls[-1]["history"] == [
        ("assistant", "What do you already believe about Arianism?"),
        ("user", "first"),
        ("assistant", "Why?"),
    ]


async def test_a_dialogue_that_was_never_stored_is_refused_rather_than_invented(
    transcripts,
):
    """A miss in both the registry and the read model.

    Refused, and not started fresh. A guessed or stale id that quietly became a
    new dialogue would hand the reader a blank conversation under a URL they
    thought they knew -- and would write to a stream nobody asked for. Red
    against a service that falls back to `begin`.
    """
    executor = RecordingExecutor([])
    service = build(executor, transcripts, StubReadModel())

    with pytest.raises(UnknownDialogue):
        await drain(
            service.respond(project_id=PROJECT_ID, dialogue_id=uuid4(), reply="hello?")
        )

    assert await all_dialogue_ids(transcripts) == set()


async def test_a_dialogue_is_not_resumable_from_another_project(transcripts):
    """The aggregate carries `project_id` and that is the boundary (spec §7).

    `RecordSocraticTurn` carries no project id, so `decide` has nothing to
    compare -- this check is the only line of defence, exactly as
    `ConversationRegistry.get`'s project check is for an ask. Refused rather
    than treated as absence, unlike the ask: an ask's chat id is a browser
    string and a mismatch is ordinary, where a dialogue id is a server-minted
    UUID and a mismatch is either a bug or a probe.
    """
    executor = RecordingExecutor(["Why?"])
    read_model = StubReadModel()
    service = build(executor, transcripts, read_model)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="Arianism")
    read_model.add(
        dialogue_id,
        project_id=PROJECT_ID,
        goal="g",
        stopping_condition="s",
        status="started",
        opening_prompt="p",
    )
    read_model.answered(dialogue_id)

    with pytest.raises(UnknownDialogue):
        await drain(
            service.respond(project_id=uuid4(), dialogue_id=dialogue_id, reply="hello?")
        )
```

`UnknownDialogue` is imported alongside the other names from
`research_team.application.socratic` — add it to that import list when you write
Task 3; it is listed separately here only so the reason for it is next to the
test that needs it.

---

## Rulings this plan makes, and why

Read these before Task 1. Two of them resolve genuine ambiguity in the spec.

**`prompt` is the system's utterance and `reply` is the reader's** — the
ordinary sense of both words. The spec names `SocraticTurnRecorded`'s fields
without saying which speaker owns which, and the deciding argument is the shape
of the surface: a socratic dialogue **leads by questioning**, so the system asks
and the reader answers. Naming the reader's text `prompt` would make the field
mean the opposite of what every reader of the code assumes, on a surface whose
entire premise is that the questioning direction is reversed from an ask.

**This deliberately does *not* map 1:1 onto `AskTurnRecorded`'s
`question`/`answer`, and that is the point rather than a cost.** An ask is
reader-asks / agent-answers; a dialogue is agent-asks / reader-answers. The
inversion is the feature, and a field layout that hid it is how someone later
writes a socratic turn that behaves like an ask turn. The executor port still
reuses cleanly — the reader's `reply` is its input and the next `prompt` is its
output.

An earlier draft of this plan ruled the opposite, on the grounds that
`citations` sit beside the agent's utterance. That argument does not decide
anything: both fields are on the same event, so wherever citations live is
equally consistent with either naming. It proves the citations belong on
`SocraticTurnRecorded`, which was never in question.

**A turn is one exchange: what the reader answered, and what the dialogue said
back.** Not a question paired with its own answer — that pairing is what an ask
does, and adopting it here would leave the dialogue's newest question belonging
to no turn, which then has to be stored a second time somewhere.

An intermediate draft of this plan did exactly that: it defined a turn as
`(question, the answer to it)` and added `next_prompt` to carry the question
that followed. That put **every system utterance in the log twice** — this
turn's `next_prompt` and the next turn's `prompt` — and two copies that can
drift is a bug that surfaces only on a rebuild. It was a mistake, and it did not
follow from the naming ruling: the ruling says who owns each *field*, not which
utterances a turn *pairs*.

Pairing the reader's answer with the dialogue's response instead stores every
utterance exactly once, and it is the shape of one executor call — `reply` in,
`prompt` out:

```
SocraticDialogueStarted(goal, stopping_condition, opening_prompt=Q1)
SocraticTurnRecorded(reply=A1, prompt=Q2)
SocraticTurnRecorded(reply=A2, prompt=Q3)
SocraticDialogueConcluded(reason="met")
```

**This makes the opening question an orphan, and that is deliberate.** Q1 has no
turn to live on, so it lives on the start event as `opening_prompt` — which is
where it already belonged, because the framing and the first question are one
decision the model makes from the topic.

**The outstanding question is therefore derived, never stored twice**: it is the
last turn's `prompt`, or `opening_prompt` when there are no turns. The
projection precomputes it into `SocraticDialogueRow.pending_prompt` because that
is what a read model is for, and the aggregate does not carry it at all — there
is no decision that needs it.

**`observations` is stored on the dialogue row as JSON, not as a third table.**
Spec §5 asks for the two-table pattern *and* names `observations` as state.
Both hold if observations ride the dialogue row the way `AskTurnRow.citations`
and `SessionSummaryRow.file_paths` ride theirs. The cost is that nothing can
query by observation, and nothing wants to.

**`DialogueRegistry.get` returns `None` on a miss.** This one line is the whole
difference from `ConversationRegistry`, whose `get` returns a fresh
`Conversation` — which is why an evicted ask silently starts over. Returning
`None` makes the caller decide, and there is nowhere for the decision to be
made silently.

**State carries the observation texts, not a count.** `AskConversationState`
holds `turns: int` and the repository builder's docstring says to revisit
snapshots "if `AskConversationState` ever grows the turns themselves rather
than a count of them". This state grows with the dialogue, so the fold is O(n)
per load. Accepted for the first release — a dialogue is a person typing, and
an observation is a sentence — and written down in the repository builder so
the next person meets the note rather than the surprise.

---

## File structure

| File | Responsibility |
| --- | --- |
| `research_team/domain/socratic_dialogue.py` | Events, commands, state, `decide`, `evolve`, the aggregate |
| `tests/domain/test_socratic_dialogue.py` | The decision rules, over pure functions |
| `tests/infrastructure/test_schema_evolution.py` | New events readable against older payloads |
| `research_team/infrastructure/persistence/event_store.py` | `build_socratic_dialogue_repository`, `UNROUTED_AGGREGATE_TYPES` entry |
| `research_team/infrastructure/persistence/read_models.py` | `SocraticDialogueRow`, `SocraticTurnRow`, `SocraticDialogueStore`, `SocraticDialogueProjection`, `SocraticDialogueRunner` |
| `tests/infrastructure/test_socratic_read_model.py` | Row-exists assertions, ordering, rebuild |
| `research_team/application/socratic.py` | `DialogueMessage`, `DialogueRegistry`, the executor port, `SocraticDialogueService` |
| `tests/application/test_socratic_resumption.py` | The test that matters (above) |
| `tests/application/test_socratic_service.py` | The rest of the service's behaviour |
| `research_team/composition.py` | The runner, the service, the `Application` fields |
| `tests/integration/test_a_dialogue_survives_a_restart.py` | The composed pairing, over two applications |
| `research_team/interfaces/web/app.py` | `GET /dialogues`, `GET /dialogues/{id}` |
| `tests/integration/test_socratic_routes.py` | The routes, on a project nothing has opened |

---

### Task 1: The aggregate

**Files:**
- Create: `research_team/domain/socratic_dialogue.py`
- Create: `tests/domain/test_socratic_dialogue.py`
- Create: `tests/application/test_socratic_resumption.py` (the file above, left red)
- Modify: `research_team/infrastructure/persistence/event_store.py` — `UNROUTED_AGGREGATE_TYPES` (~line 72) and a new `build_socratic_dialogue_repository` beside `build_ask_conversation_repository` (~line 159)
- Modify: `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: `eventsource`'s `CommandRejectedError`, `DeciderAggregate`, `DomainEvent`,
  `register_event`; pydantic `BaseModel`, `Field`.
- Produces, for every later task and for Plans 2 and 3:

```python
CitationKind = Literal["source"]
Citation = tuple[CitationKind, str]
EvidenceKind = Literal["attempt", "assessment"]
ConclusionReason = Literal["met", "abandoned"]

class SocraticDialogueStarted(DomainEvent):
    aggregate_type: str = "SocraticDialogue"
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    opened_at: datetime

class SocraticTurnRecorded(DomainEvent):
    aggregate_type: str = "SocraticDialogue"
    reply: str      # what the reader answered to the outstanding question
    prompt: str     # what the dialogue said back — usually the next question
    citations: list[Citation] = Field(default_factory=list)

class SocraticProgressObserved(DomainEvent):
    aggregate_type: str = "SocraticDialogue"
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""

class SocraticDialogueConcluded(DomainEvent):
    aggregate_type: str = "SocraticDialogue"
    reason: ConclusionReason

@dataclass(frozen=True)
class StartSocraticDialogue:
    dialogue_id: UUID
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str
    opened_at: datetime

@dataclass(frozen=True)
class RecordSocraticTurn:
    dialogue_id: UUID
    reply: str
    prompt: str
    citations: tuple[Citation, ...] = ()

@dataclass(frozen=True)
class ObserveSocraticProgress:
    dialogue_id: UUID
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""

@dataclass(frozen=True)
class ConcludeSocraticDialogue:
    dialogue_id: UUID
    reason: ConclusionReason

class SocraticDialogueState(BaseModel):
    dialogue_id: UUID | None = None
    project_id: UUID | None = None
    topic: str = ""
    goal: str = ""
    stopping_condition: str = ""
    status: Literal["new", "started", "concluded"] = "new"
    turns: int = 0
    observations: list[str] = Field(default_factory=list)
    @property
    def is_started(self) -> bool: ...
    @property
    def is_concluded(self) -> bool: ...

def initial_state() -> SocraticDialogueState: ...
def decide(command, state) -> list[DomainEvent]: ...
def evolve(state, event) -> SocraticDialogueState: ...
class SocraticDialogue(DeciderAggregate[...]):
    aggregate_type = "SocraticDialogue"

# in event_store.py
def build_socratic_dialogue_repository(
    store: SQLiteEventStore, publisher: InMemoryEventBus | None = None
) -> AggregateRepository[SocraticDialogue]: ...
```

- [ ] **Step 1: Create the resumption test file, and watch it fail**

Create `tests/application/test_socratic_resumption.py` with exactly the content in
"The test that matters" above, plus `UnknownDialogue` added to the import from
`research_team.application.socratic`.

Run: `uv run pytest tests/application/test_socratic_resumption.py -x`

Expected: FAIL at collection —
`ModuleNotFoundError: No module named 'research_team.application.socratic'`.

**Write down that error.** Task 2's last step and Task 3's first step both check
that it has changed; a task that leaves this file failing on the identical line
has not moved the feature.

- [ ] **Step 2: Write the failing aggregate tests**

Create `tests/domain/test_socratic_dialogue.py`:

```python
"""What a socratic dialogue will and will not accept, over pure functions.

Modelled on `tests/domain/test_ask_conversation.py`, which these deliberately
mirror: same `_with` fold helper, same one-assertion-per-rule shape. The
differences are the state this aggregate has that an ask cannot express -- a
goal, a stopping condition, and a terminal status -- which is the whole reason
it is a second aggregate rather than a re-prompted first one.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.socratic_dialogue import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticDialogueState,
    SocraticProgressObserved,
    SocraticTurnRecorded,
    StartSocraticDialogue,
    decide,
    evolve,
    initial_state,
)

PROJECT_ID = uuid4()
DIALOGUE_ID = uuid4()
OPENED_AT = datetime(2026, 8, 17, tzinfo=UTC)

STARTED = SocraticDialogueStarted(
    aggregate_id=DIALOGUE_ID,
    project_id=PROJECT_ID,
    topic="the Nicene settlement",
    goal="understand what the creed actually settled",
    stopping_condition="the reader distinguishes the settlement from its politics",
    opening_prompt="What do you already believe about it?",
    opened_at=OPENED_AT,
)


def _with(*events: DomainEvent) -> SocraticDialogueState:
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_starting_carries_the_goal_and_the_stopping_condition():
    """The two fields that make this a different aggregate from an ask.

    `AskConversationState` is four fields with nowhere to put either, which is
    the spec's §1 argument for not re-prompting it. Red against an event that
    carries the topic and lets the model hold the goal in its context -- a
    stopping condition decided inside an LLM's context is one nothing can test.
    """
    events = decide(
        StartSocraticDialogue(
            dialogue_id=DIALOGUE_ID,
            project_id=PROJECT_ID,
            topic="the Nicene settlement",
            goal="understand what the creed actually settled",
            stopping_condition="the reader distinguishes the settlement from its politics",
            opening_prompt="What do you already believe about it?",
            opened_at=OPENED_AT,
        ),
        initial_state(),
    )

    assert [type(e) for e in events] == [SocraticDialogueStarted]
    assert events[0].aggregate_id == DIALOGUE_ID
    assert events[0].project_id == PROJECT_ID
    assert events[0].goal == "understand what the creed actually settled"
    assert (
        events[0].stopping_condition
        == "the reader distinguishes the settlement from its politics"
    )


def test_starting_folds_to_a_state_that_knows_what_it_is_for():
    state = _with(STARTED)

    assert state.dialogue_id == DIALOGUE_ID
    assert state.project_id == PROJECT_ID
    assert state.topic == "the Nicene settlement"
    assert state.goal == "understand what the creed actually settled"
    assert state.is_started
    assert not state.is_concluded
    assert state.turns == 0
    assert state.observations == []


def test_starting_twice_is_refused():
    with pytest.raises(CommandRejectedError, match="already started"):
        decide(
            StartSocraticDialogue(
                dialogue_id=DIALOGUE_ID,
                project_id=PROJECT_ID,
                topic="t",
                goal="g",
                stopping_condition="s",
                opening_prompt="p",
                opened_at=OPENED_AT,
            ),
            _with(STARTED),
        )


def test_a_turn_before_the_dialogue_started_is_refused():
    """Nothing may be first but the start, which is what lets the projection
    treat a turn against an unknown dialogue as a log it never saw the head of
    rather than as a case to handle."""
    with pytest.raises(CommandRejectedError, match="not started"):
        decide(
            RecordSocraticTurn(dialogue_id=DIALOGUE_ID, reply="hi", prompt="why?"),
            initial_state(),
        )


def test_a_turn_pairs_the_reader_s_answer_with_the_dialogue_s_response():
    """The field-naming ruling and the pairing, which are two claims.

    `prompt` is what the *dialogue* said and `reply` is what the reader
    answered -- the ordinary sense of both words, and the inverse of
    `AskTurnRecorded`, because this surface runs in the opposite direction.

    And a turn pairs the reader's answer with the response it drew, not a
    question with its own answer. That is one executor call -- `reply` in,
    `prompt` out -- and it stores every utterance exactly once. The pairing
    that seems more natural leaves the newest question belonging to no turn,
    which then has to be stored a second time.

    Red against an implementation that reads the fields the other way round.
    That failure produces a transcript which still reads as a conversation --
    just one where the reader asks all the questions -- so nothing but this
    assertion would notice.
    """
    events = decide(
        RecordSocraticTurn(
            dialogue_id=DIALOGUE_ID,
            reply="It settled Arianism.",
            prompt="Settled by whom, though?",
            citations=(("source", "s1"),),
        ),
        _with(STARTED),
    )

    assert [type(e) for e in events] == [SocraticTurnRecorded]
    assert events[0].aggregate_id == DIALOGUE_ID
    assert events[0].reply == "It settled Arianism."
    assert events[0].prompt == "Settled by whom, though?"
    assert events[0].citations == [("source", "s1")]


def test_turns_count_up_as_they_fold():
    """A count and not the texts. Which question is outstanding is a read
    concern -- the last turn's `prompt` -- and no decision in this module needs
    it, so the state does not carry it and cannot disagree with the log."""
    state = _with(
        STARTED,
        SocraticTurnRecorded(aggregate_id=DIALOGUE_ID, reply="b", prompt="c?"),
        SocraticTurnRecorded(aggregate_id=DIALOGUE_ID, reply="d", prompt="e?"),
    )

    assert state.turns == 2


def test_an_observation_is_kept_and_not_merely_counted():
    """The state has to express "this dialogue is trying to reach X and has not
    yet", and a counter cannot. Red against `observations: int`, which folds
    cheaply and answers nothing the stopping condition needs."""
    state = _with(
        STARTED,
        SocraticProgressObserved(
            aggregate_id=DIALOGUE_ID,
            observation="distinguished the creed from the council",
            evidence="attempt",
            detail="mcq nicene-1 correct",
        ),
    )

    assert state.observations == ["distinguished the creed from the council"]


def test_concluding_records_why():
    events = decide(ConcludeSocraticDialogue(dialogue_id=DIALOGUE_ID, reason="met"), _with(STARTED))

    assert [type(e) for e in events] == [SocraticDialogueConcluded]
    assert events[0].reason == "met"


def test_a_concluded_dialogue_takes_no_more_turns():
    """The terminal status is the point of having one. A dialogue that reached
    its stopping condition and then accepted three more exchanges has a
    stopping condition in name only. Red against a `decide` that matches on
    `status="new"` alone and lets everything else through -- which is exactly
    what `AskConversation.decide` does, correctly, for a surface with no end.
    """
    concluded = _with(
        STARTED, SocraticDialogueConcluded(aggregate_id=DIALOGUE_ID, reason="met")
    )

    assert concluded.is_concluded
    for command in (
        RecordSocraticTurn(dialogue_id=DIALOGUE_ID, reply="yes", prompt="one more?"),
        ObserveSocraticProgress(dialogue_id=DIALOGUE_ID, observation="late"),
        ConcludeSocraticDialogue(dialogue_id=DIALOGUE_ID, reason="abandoned"),
    ):
        with pytest.raises(CommandRejectedError, match="concluded"):
            decide(command, concluded)


def test_evolve_ignores_an_event_it_has_no_rule_for():
    """Total, like every other fold here: an event from another aggregate that
    somehow reached this stream leaves the state alone rather than raising
    inside a replay."""
    from research_team.domain.ask_conversation import AskTurnRecorded

    state = _with(STARTED)

    assert evolve(state, AskTurnRecorded(aggregate_id=DIALOGUE_ID, question="q", answer="a")) == state
```

- [ ] **Step 3: Run the aggregate tests to verify they fail**

Run: `uv run pytest tests/domain/test_socratic_dialogue.py -x`

Expected: FAIL at collection —
`ModuleNotFoundError: No module named 'research_team.domain.socratic_dialogue'`.

- [ ] **Step 4: Write the aggregate**

Create `research_team/domain/socratic_dialogue.py`:

```python
"""A guided conversation with a goal it can be measured against.

A second conversational aggregate beside `AskConversation`, and the spec's §1
gives the one-line reason it is not the same one re-prompted:
`AskConversationState` is four fields -- id, project, status, turn count --
with nowhere to put a goal or a stopping condition, and nothing in it can
express "this dialogue is trying to reach X and has not yet". A stopping
condition **is** state.

**`prompt` is the system's utterance and `reply` is the reader's**, in the
ordinary sense of both words. A socratic dialogue leads by questioning, so the
system asks and the reader answers -- which is the *inverse* of
`AskTurnRecorded`'s question/answer, deliberately. That inversion is the
feature, and a field layout that hid it is how someone later writes a socratic
turn that behaves like an ask turn.

**A turn is therefore a completed pair, and the newest question belongs to no
turn.** A turn pairs the reader's answer with the response it drew --
`Started(opening_prompt=Q1)`, `Turn(A1, Q2)`, `Turn(A2, Q3)` -- which is one
executor call per event and stores every utterance exactly once. The pairing
that seems more natural, a question with its own answer, leaves the newest
question belonging to no turn and forces it to be stored a second time; an
intermediate draft did that and put every system utterance in the log twice.

So the opening question is an orphan and lives on the start event, and the
question currently outstanding is *derived* -- the last turn's `prompt`, or
`opening_prompt` when there are none.

**The status is terminal and the ask's is not.** `AskConversation` has `new`
and `started` and correctly never ends, because an ask has no notion of being
finished. A dialogue that reached its stopping condition and then accepted
three more exchanges has a stopping condition in name only, so `concluded`
refuses everything.

**The id is minted by the server**, as `AskConversation`'s is and for the
identical reason: an aggregate id, a row key and a URL segment cannot be a
string a browser chose. `SocraticDialogueService.begin` does the minting; this
module only types it as a `UUID`.
"""

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

CitationKind = Literal["source"]

Citation = tuple[CitationKind, str]
"""What a reply rested on. Narrowed to `"source"` for `AskConversation`'s
stated reason: `read_source` is the only admitted tool that opens one
identified thing, and a branch nothing can emit cannot be tested."""

EvidenceKind = Literal["attempt", "assessment"]
"""Where an observation came from.

Two members and the difference is what a reader could argue with: `"attempt"`
means a component the reader answered and the server graded, which is a fact;
`"assessment"` means the model judged the reader's prose, which is an opinion.
A stopping condition met entirely by assessments is a dialogue that graded its
own homework, and keeping the kinds apart is what makes that visible later.
"""

ConclusionReason = Literal["met", "abandoned"]


# ---------------- events ----------------


@register_event
class SocraticDialogueStarted(DomainEvent):
    """A dialogue began, against one project, aimed at one thing.

    Must be the first event on the stream -- `decide` refuses every other
    command against a dialogue that has not started.

    `opening_prompt` defaults to empty for the schema-evolution strategy's
    case 1: it was added after the first draft of this event and an older
    payload without it reads as "the opening question was not recorded", which
    is honest -- the dialogue is still resumable from its goal and its turns.
    """

    aggregate_type: str = "SocraticDialogue"
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    opened_at: datetime


@register_event
class SocraticTurnRecorded(DomainEvent):
    """One exchange: what the reader answered, and what the dialogue said back.

    Appended once per successful turn. A failed turn records nothing, matching
    `AskTurnRecorded`: this is a fact about an exchange that happened, not an
    attempt that was made.

    **The pairing is reader-then-system, and it is not the same as the field
    naming.** `prompt` is the system's utterance and `reply` is the reader's
    (see the module docstring), but a *turn* pairs the reader's answer with the
    response it drew -- not a question with its own answer. That is the shape of
    one executor call, `reply` in and `prompt` out, and it stores every
    utterance in the conversation exactly once:

        Started(opening_prompt=Q1) / Turn(A1, Q2) / Turn(A2, Q3) / Concluded

    The alternative -- pairing each question with its answer -- leaves the
    newest question belonging to no turn, which then has to be stored a second
    time. An intermediate draft did that, with a `next_prompt` field, and put
    every system utterance in the log twice; two copies that can drift is a bug
    that surfaces only on a rebuild.

    So the opening question is an orphan and lives on
    `SocraticDialogueStarted.opening_prompt`, and the question currently
    outstanding is *derived* -- the last turn's `prompt`, or `opening_prompt`
    when there are none. `SocraticDialogueRow.pending_prompt` precomputes it;
    nothing stores it twice.

    `prompt` is a question on every turn but the last, where it is whatever the
    dialogue said as it concluded. The field is "what the dialogue said", and
    `SocraticDialogueConcluded` is what says the dialogue ended -- so nothing
    here has to encode "this one is not a question".
    """

    aggregate_type: str = "SocraticDialogue"
    reply: str
    prompt: str
    citations: list[Citation] = Field(default_factory=list)


@register_event
class SocraticProgressObserved(DomainEvent):
    """Something the reader demonstrated, and what showed it.

    Separate from `SocraticTurnRecorded` rather than a field on it, because
    progress and exchanges are not one-to-one in either direction: a turn can
    demonstrate nothing, and a graded `mcq` attempt can arrive without any
    exchange around it at all.
    """

    aggregate_type: str = "SocraticDialogue"
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""
    """What the evidence was, in whatever form it took -- a component id and
    its verdict for an attempt, the model's words for an assessment. Free text
    because the two shapes have nothing in common and a union of two typed
    payloads would be read by nothing."""


@register_event
class SocraticDialogueConcluded(DomainEvent):
    """The dialogue ended, and why."""

    aggregate_type: str = "SocraticDialogue"
    reason: ConclusionReason


# ---------------- commands ----------------


@dataclass(frozen=True)
class StartSocraticDialogue:
    dialogue_id: UUID
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str
    opened_at: datetime


@dataclass(frozen=True)
class RecordSocraticTurn:
    dialogue_id: UUID
    reply: str
    prompt: str
    citations: tuple[Citation, ...] = dc_field(default_factory=tuple)


@dataclass(frozen=True)
class ObserveSocraticProgress:
    dialogue_id: UUID
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""


@dataclass(frozen=True)
class ConcludeSocraticDialogue:
    dialogue_id: UUID
    reason: ConclusionReason


SocraticCommand = (
    StartSocraticDialogue
    | RecordSocraticTurn
    | ObserveSocraticProgress
    | ConcludeSocraticDialogue
)


# ---------------- state ----------------


class SocraticDialogueState(BaseModel):
    """Everything derivable from a dialogue's stream.

    **`observations` holds the texts, not a count**, unlike
    `AskConversationState.turns`. The state has to be able to express what the
    reader has demonstrated so far, and a counter cannot. The cost is a fold
    that grows with the dialogue rather than staying constant, which is
    recorded on `build_socratic_dialogue_repository` where the snapshot
    decision lives.
    """

    dialogue_id: UUID | None = None
    project_id: UUID | None = None
    topic: str = ""
    goal: str = ""
    stopping_condition: str = ""
    status: Literal["new", "started", "concluded"] = "new"
    turns: int = 0
    observations: list[str] = Field(default_factory=list)

    @property
    def is_started(self) -> bool:
        return self.status == "started"

    @property
    def is_concluded(self) -> bool:
        return self.status == "concluded"


def initial_state() -> SocraticDialogueState:
    return SocraticDialogueState()


# ---------------- decide ----------------


def decide(command: SocraticCommand, state: SocraticDialogueState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce."""
    match command, state:
        case StartSocraticDialogue(), SocraticDialogueState(status="new"):
            return [
                SocraticDialogueStarted(
                    aggregate_id=command.dialogue_id,
                    project_id=command.project_id,
                    topic=command.topic,
                    goal=command.goal,
                    stopping_condition=command.stopping_condition,
                    opening_prompt=command.opening_prompt,
                    opened_at=command.opened_at,
                )
            ]
        case StartSocraticDialogue(), _:
            raise CommandRejectedError("dialogue already started")

        # Concluded is checked before "not started" for every other command,
        # because a concluded dialogue is also not `new` and the two refusals
        # say different things to whoever reads the error.
        case _, SocraticDialogueState(status="concluded"):
            raise CommandRejectedError("dialogue already concluded")

        case _, SocraticDialogueState(status="new"):
            raise CommandRejectedError("dialogue not started")

        case RecordSocraticTurn(reply=reply, prompt=prompt, citations=citations), _:
            return [
                SocraticTurnRecorded(
                    aggregate_id=state.dialogue_id,
                    reply=reply,
                    prompt=prompt,
                    citations=list(citations),
                )
            ]

        case ObserveSocraticProgress(
            observation=observation, evidence=evidence, detail=detail
        ), _:
            return [
                SocraticProgressObserved(
                    aggregate_id=state.dialogue_id,
                    observation=observation,
                    evidence=evidence,
                    detail=detail,
                )
            ]

        case ConcludeSocraticDialogue(reason=reason), _:
            return [SocraticDialogueConcluded(aggregate_id=state.dialogue_id, reason=reason)]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


# ---------------- evolve ----------------


def evolve(state: SocraticDialogueState, event: DomainEvent) -> SocraticDialogueState:
    """What each fact does to the state. Total, like every other fold here."""
    match event:
        case SocraticDialogueStarted(
            project_id=project_id, topic=topic, goal=goal, stopping_condition=condition
        ):
            return SocraticDialogueState(
                dialogue_id=event.aggregate_id,
                project_id=project_id,
                topic=topic,
                goal=goal,
                stopping_condition=condition,
                status="started",
            )

        # A counter, not the text. Which question is outstanding is a *read*
        # concern -- the last turn's `prompt`, or `opening_prompt` -- and no
        # decision in this module needs it, so the aggregate does not carry it.
        case SocraticTurnRecorded():
            return state.model_copy(update={"turns": state.turns + 1})

        case SocraticProgressObserved(observation=observation):
            return state.model_copy(
                update={"observations": [*state.observations, observation]}
            )

        case SocraticDialogueConcluded():
            return state.model_copy(update={"status": "concluded"})

    return state


class SocraticDialogue(DeciderAggregate[SocraticDialogueState, SocraticCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = "SocraticDialogue"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
```

- [ ] **Step 5: Run the aggregate tests to verify they pass**

Run: `uv run pytest tests/domain/test_socratic_dialogue.py -v`

Expected: PASS, 10 tests.

- [ ] **Step 6: Add the repository builder and the feed decision**

In `research_team/infrastructure/persistence/event_store.py`, import
`SocraticDialogue`, add it to `UNROUTED_AGGREGATE_TYPES` beside
`AskConversation.aggregate_type`, and append this paragraph to that constant's
docstring:

```python
"""
`SocraticDialogue` is off for `AskConversation`'s reason and one more: the
only client that would repaint on a dialogue frame is the browser already
holding the SSE stream that produced it, so a feed frame would be a second
signal for a repaint that has already happened.
"""
```

Then add, beside `build_ask_conversation_repository`:

```python
def build_socratic_dialogue_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[SocraticDialogue]:
    """Guided dialogues, over the same log as everything else.

    Published like its neighbours even though `SocraticDialogue` is in
    `UNROUTED_AGGREGATE_TYPES`, for `build_ask_conversation_repository`'s
    reason: publishing is what `read_since`'s local append flag watches, and
    the scoping decision is made there rather than by half-wiring the bus here.

    **No snapshots, and this one is closer to the line than the ask's.**
    `SocraticDialogueState.observations` holds the observation texts rather
    than a count, so unlike `AskConversationState` this fold grows with the
    dialogue -- which is precisely the condition
    `build_ask_conversation_repository` names as the trigger to revisit. It is
    still the right call for the first release: a dialogue is a person typing,
    an observation is a sentence, and a stream long enough for the threshold to
    matter is a conversation nobody has had yet. Revisit when a dialogue can
    run unattended, which is the change that would make the length unbounded.
    """
    return AggregateRepository(store, SocraticDialogue, event_publisher=publisher)
```

- [ ] **Step 7: Add the schema-evolution cases**

Append to `tests/infrastructure/test_schema_evolution.py`, reusing that file's own
raw-insert helper. Its real signature, confirmed against the file:

```python
async def _write_old_event(
    db_path: str,
    session_id,
    version: int,
    event_type: str,
    payload: dict,
    aggregate_type: str = "Session",
) -> None: ...
```

so the calls below are positional-with-keywords in that order —
`await _write_old_event(db_path, dialogue_id, 1, "SocraticDialogueStarted", {...},
aggregate_type="SocraticDialogue")`. It deliberately bypasses the library, because
constructing the event through today's model would add today's fields, which is the
thing under test.

```python
async def test_a_dialogue_written_before_the_opening_prompt_existed_still_loads(
    db_path, store
):
    """Case 1 of the strategy in `domain/events.py`: a field added with a
    default that means what its absence meant.

    `opening_prompt` was added to `SocraticDialogueStarted` after the first
    draft. An older payload has no key, the default fills in, and the value
    reads as "the opening question was not recorded" -- which is honest,
    because the dialogue is still resumable from its goal and its turns.

    Red against a build that makes `opening_prompt` required: every dialogue
    written before it existed stops loading, and the failure surfaces as a
    reader's dialogue simply refusing to resume.
    """
    dialogue_id = uuid4()
    await _write_old_event(
        db_path,
        dialogue_id,
        1,
        "SocraticDialogueStarted",
        {
            "project_id": str(uuid4()),
            "topic": "the Nicene settlement",
            "goal": "understand what the creed settled",
            "stopping_condition": "the reader can state it in their own words",
            "opened_at": datetime.now(UTC).isoformat(),
        },
        aggregate_type="SocraticDialogue",
    )

    repository = build_socratic_dialogue_repository(store)
    dialogue = await repository.load(dialogue_id)

    assert dialogue.state.goal == "understand what the creed settled"
    assert dialogue.state.stopping_condition == (
        "the reader can state it in their own words"
    )
    assert dialogue.state.is_started



async def test_an_observation_written_before_evidence_kinds_existed_reads_as_assessment(
    db_path, store
):
    """The same case for `SocraticProgressObserved.evidence`.

    The default is `"assessment"` and not `"attempt"`, deliberately: an
    unlabelled observation is the model's judgement until something says
    otherwise, and defaulting to `"attempt"` would silently promote every old
    opinion to a graded fact -- which is the exact distinction `EvidenceKind`
    exists to keep.
    """
    dialogue_id = uuid4()
    await _write_old_event(
        db_path,
        dialogue_id,
        1,
        "SocraticDialogueStarted",
        {
            "project_id": str(uuid4()),
            "topic": "t",
            "goal": "g",
            "stopping_condition": "s",
            "opened_at": datetime.now(UTC).isoformat(),
        },
        aggregate_type="SocraticDialogue",
    )
    await _write_old_event(
        db_path,
        dialogue_id,
        2,
        "SocraticProgressObserved",
        {"observation": "named the two parties"},
        aggregate_type="SocraticDialogue",
    )

    repository = build_socratic_dialogue_repository(store)
    dialogue = await repository.load(dialogue_id)

    assert dialogue.state.observations == ["named the two parties"]
```

One note for whoever writes these: `_write_old_event`'s second parameter is named
`session_id` because the file predates every non-session aggregate. Pass the dialogue
id positionally and do not rename the parameter — it is shared with every existing
case and renaming it is a diff across a file this task is not otherwise touching.

- [ ] **Step 8: Run the schema and feed guards**

Run: `uv run pytest tests/infrastructure/test_schema_evolution.py tests/infrastructure/test_feed_coverage.py -v`

Expected: PASS. `test_every_aggregate_type_is_decided` is the one that would have
failed before Step 6 — confirm it did by temporarily removing the
`UNROUTED_AGGREGATE_TYPES` line and re-running; the message names
`SocraticDialogue`. Restore it.

- [ ] **Step 9: Wiring**

Nothing constructs any of this yet, and that is correct for this task — but check the
one hop that is already live:

Run: `uv run pytest tests/test_architecture.py -v`

Expected: PASS. `research_team/domain/socratic_dialogue.py` imports `eventsource` and
pydantic and nothing else; a stray import of anything framework-shaped fails here.

Re-run the resumption test and confirm the error has **not** changed yet:

Run: `uv run pytest tests/application/test_socratic_resumption.py -x`

Expected: still `ModuleNotFoundError: No module named 'research_team.application.socratic'`.
That is the honest state after this task — the aggregate exists and nothing drives it.

- [ ] **Step 10: Gates**

Run, one at a time:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 11: Commit**

```bash
git add research_team/domain/socratic_dialogue.py \
  research_team/infrastructure/persistence/event_store.py \
  tests/domain/test_socratic_dialogue.py \
  tests/application/test_socratic_resumption.py \
  tests/infrastructure/test_schema_evolution.py
git commit -m "A dialogue aggregate, because a stopping condition is state

A second conversational aggregate rather than a re-prompted AskConversation.
The deciding line is that AskConversationState is four fields with nowhere to
put a goal or a stopping condition, and nothing in it can express that a
dialogue is trying to reach something and has not yet.

Two namings worth arguing, both settled here:

prompt is the READER's utterance and reply is the DIALOGUE's, which is the
opposite of the intuitive reading. citations forces it: they sit on the same
event and come from tools the agent ran, so the agent's utterance is the one
they belong beside. The pair then maps one-to-one onto AskTurnRecorded's
question/answer, which is what lets the executor port keep the ask's shape.

observations holds texts, not a count. A counter folds cheaply and answers
nothing a stopping condition needs. The cost is a fold that grows with the
dialogue where the ask's stays constant -- which is exactly the condition
build_ask_conversation_repository names as the trigger to revisit snapshots, so
the note is written where the next person will meet it.

The status is terminal and the ask's deliberately is not. A dialogue that
reached its stopping condition and then took three more exchanges has a
stopping condition in name only.

Off the feed, in UNROUTED_AGGREGATE_TYPES, because the only client that would
repaint on a dialogue frame is the browser already holding the stream that
produced it.

The resumption test is in this commit and is red. It is the requirement the
spec says to write first, and it fails on the module the service will live in.

Nothing constructs any of this yet."
```

---

### Task 2: The read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` — add after the
  `AskConversationRunner` block (~line 3330): `SOCRATIC_NAMESPACE`,
  `SocraticDialogueRow`, `SocraticTurnRow`, `SocraticDialogueStore`,
  `SocraticDialogueProjection`, `SocraticDialogueRunner`
- Create: `tests/infrastructure/test_socratic_read_model.py`

**Interfaces:**
- Consumes: Task 1's four events and its repository builder; `ReadModel`,
  `SQLiteReadModelRepository`, `ReadModelRepository`, `Query`, `Filter`,
  `apply_schema`, `model_schema`, `DeclarativeProjection`, `handles`,
  `LOCAL_RETRY_POLICY`, `SubscriptionManager`, `SubscriptionConfig`,
  `SQLCheckpointRepository`, `SQLDLQRepository`, `DLQEntry` — all already imported
  in `read_models.py`.
- Produces, for Tasks 3–5 and Plans 2–3:

```python
SOCRATIC_NAMESPACE = UUID("...")   # a fresh uuid4, pasted as a literal

class SocraticDialogueRow(ReadModel):
    __table_name__ = "socratic_dialogues"
    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    pending_prompt: str = ""
    opened_at: datetime
    status: str = "started"
    concluded_reason: str = ""
    turn_count: int = 0
    observations: list[dict] = Field(default_factory=list)   # JSON column

class SocraticTurnRow(ReadModel):
    __table_name__ = "socratic_turns"
    dialogue_id: UUID
    project_id: UUID
    position: int
    reply: str         # what the reader answered
    prompt: str        # what the dialogue said back
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime
    @staticmethod
    def row_id(dialogue_id: UUID, position: int) -> UUID: ...

class SocraticDialogueStore:
    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "SocraticDialogueStore": ...
    async def start(self, dialogue_id, project_id, *, topic, goal,
                    stopping_condition, opening_prompt, opened_at) -> None: ...
    async def record(self, dialogue_id, *, reply, prompt,
                     citations, recorded_at) -> None: ...
    async def observe(self, dialogue_id, *, observation, evidence, detail) -> None: ...
    async def conclude(self, dialogue_id, *, reason: str) -> None: ...
    async def get(self, dialogue_id) -> SocraticDialogueRow | None: ...
    async def for_project(self, project_id) -> list[SocraticDialogueRow]: ...
    async def turns_for(self, dialogue_id) -> list[SocraticTurnRow]: ...
    async def truncate(self) -> None: ...
    async def close(self) -> None: ...

class SocraticDialogueRunner:
    def __init__(self, store, db_path, bus, tracer=None): ...
    projection_name: str
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def caught_up(self, timeout: float = 10.0) -> None: ...
    async def rebuild(self) -> None: ...
    async def failures(self, limit: int = 100) -> list[DLQEntry]: ...
    async def get(self, dialogue_id) -> SocraticDialogueRow | None: ...
    async def for_project(self, project_id) -> list[SocraticDialogueRow]: ...
    async def turns_for(self, dialogue_id) -> list[SocraticTurnRow]: ...
```

`SocraticDialogueRunner.get` and `.turns_for` are the two methods Task 3's service
reads through, and their shapes are what the `DialogueReadModel` Protocol will name.

- [ ] **Step 1: Write the failing read-model tests**

Create `tests/infrastructure/test_socratic_read_model.py`:

```python
"""The dialogue tables: what they store, and the order they refuse to lose.

Every assertion here is on a *row* and on the value the event carried, never on
"the append returned" or "replay completed". An event no projection handles
counts as APPLIED rather than rejected -- `strict` raises only when a handler
itself raises -- so a build with `SocraticDialogueProjection` never registered
replays perfectly cleanly and serves an empty table. Any assertion weaker than
"this row holds this value" passes against exactly the bug this feature is most
likely to ship with.

Modelled on `test_ask_read_model.py`, including driving through the aggregate
rather than appending raw: `SocraticDialogue` has a `decide` that refuses a
turn before a start and everything after a conclusion, and a test that bypassed
it could store a sequence the domain would have rejected.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.domain.socratic_dialogue import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    StartSocraticDialogue,
)
from research_team.infrastructure.persistence.event_store import (
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.read_models import SocraticDialogueRunner


@pytest.fixture
def transcripts(store, publisher):
    return build_socratic_dialogue_repository(store, publisher)


@pytest.fixture
async def runner(db_path, store, publisher):
    started = SocraticDialogueRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


async def _dialogue(
    transcripts,
    project_id,
    dialogue_id,
    *,
    turns=(),
    observations=(),
    conclude=None,
    goal="understand what the creed settled",
    stopping_condition="the reader states it in their own words",
):
    aggregate = transcripts.create_new(dialogue_id)
    aggregate.execute(
        StartSocraticDialogue(
            dialogue_id=dialogue_id,
            project_id=project_id,
            topic="the Nicene settlement",
            goal=goal,
            stopping_condition=stopping_condition,
            opening_prompt="What do you already believe about it?",
            opened_at=datetime.now(UTC),
        )
    )
    # `(what the reader answered, what the dialogue said back)` -- one
    # exchange, reader first. The question each `reply` answers is the previous
    # entry's `prompt`, or `opening_prompt` for the first.
    for reply, prompt, citations in turns:
        aggregate.execute(
            RecordSocraticTurn(
                dialogue_id=dialogue_id,
                reply=reply,
                prompt=prompt,
                citations=citations,
            )
        )
    for observation, evidence, detail in observations:
        aggregate.execute(
            ObserveSocraticProgress(
                dialogue_id=dialogue_id,
                observation=observation,
                evidence=evidence,
                detail=detail,
            )
        )
    if conclude is not None:
        aggregate.execute(
            ConcludeSocraticDialogue(dialogue_id=dialogue_id, reason=conclude)
        )
    await transcripts.save(aggregate)


async def test_a_started_dialogue_stores_its_goal_and_stopping_condition(
    runner, transcripts, project_id
):
    """The two columns the whole feature rests on, asserted as stored values.

    This is the resumption path's source of truth: `SocraticDialogueService`
    reads these back when the live cache has dropped the dialogue, so a
    projection that stored the topic and dropped the goal would resume a
    dialogue aimed at nothing -- and every request would still answer 200.

    Red against a build with `SocraticDialogueProjection` unregistered, which
    is the failure this file exists for: `get` returns None and this fails on
    the attribute rather than on a status code that was never wrong.
    """
    dialogue_id = uuid4()
    await _dialogue(transcripts, project_id, dialogue_id)
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row is not None, "no row: the projection is not following the log"
    assert row.project_id == project_id
    assert row.topic == "the Nicene settlement"
    assert row.goal == "understand what the creed settled"
    assert row.stopping_condition == "the reader states it in their own words"
    assert row.opening_prompt == "What do you already believe about it?"
    assert row.status == "started"
    assert row.turn_count == 0


async def test_three_turns_come_back_in_the_order_they_were_asked(
    runner, transcripts, project_id
):
    """Order is the assertion, not the count. A read leaning on rowid ordering
    would pass until a `rebuild` reordered the inserts, which is why
    `SocraticTurnRow.position` is a stored column and `turns_for` sorts on it.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[
            ("It settled Arianism.", "Settled by whom?", (("source", "a"),)),
            ("The council of 325.", "And against whom?", ()),
            ("Against Arius.", "What did he actually claim?", (("source", "b"),)),
        ],
    )
    await runner.caught_up()

    turns = await runner.turns_for(dialogue_id)

    assert [turn.position for turn in turns] == [0, 1, 2]
    assert [turn.reply for turn in turns] == [
        "It settled Arianism.",
        "The council of 325.",
        "Against Arius.",
    ]
    assert [turn.prompt for turn in turns] == [
        "Settled by whom?",
        "And against whom?",
        "What did he actually claim?",
    ]
    assert turns[0].citations == [{"kind": "source", "id": "a"}]
    assert turns[1].citations == []

    row = await runner.get(dialogue_id)
    assert row.turn_count == 3
    # Precomputed from the newest turn rather than stored a second time. Red
    # against a projection that writes it only on start, where a resumed
    # dialogue would show the reader the opening question forever.
    assert row.pending_prompt == "What did he actually claim?"
    # And the utterance no turn holds: what the dialogue opened with.
    assert row.opening_prompt == "What do you already believe about it?"


async def test_the_speakers_are_not_swapped_on_the_way_into_the_table(
    runner, transcripts, project_id
):
    """The `prompt`/`reply` ruling, pinned a second time at the storage layer.

    Asserted with two texts that could not be mistaken for each other, because
    a projection that swapped them would produce a transcript that still reads
    as a conversation -- just one where the reader asks all the questions, and
    nothing but an assertion like this one would notice.

    Red against `prompt=event.reply`.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[("THE READER ANSWERED THIS", "THE DIALOGUE SAID THIS", ())],
    )
    await runner.caught_up()

    turn = (await runner.turns_for(dialogue_id))[0]

    assert turn.reply == "THE READER ANSWERED THIS"
    assert turn.prompt == "THE DIALOGUE SAID THIS"


async def test_an_observation_is_stored_with_the_kind_of_evidence_behind_it(
    runner, transcripts, project_id
):
    """A stopping condition met entirely by the model's own assessments is a
    dialogue that graded its own homework, and the only thing that makes that
    visible later is storing which kind each observation was. Red against a
    projection that stores the text and drops `evidence`.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        observations=[
            ("distinguished creed from council", "attempt", "mcq nicene-1 correct"),
            ("used homoousios correctly", "assessment", ""),
        ],
    )
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row.observations == [
        {
            "observation": "distinguished creed from council",
            "evidence": "attempt",
            "detail": "mcq nicene-1 correct",
        },
        {"observation": "used homoousios correctly", "evidence": "assessment", "detail": ""},
    ]


async def test_a_concluded_dialogue_says_so_and_says_why(runner, transcripts, project_id):
    dialogue_id = uuid4()
    await _dialogue(transcripts, project_id, dialogue_id, conclude="met")
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row.status == "concluded"
    assert row.concluded_reason == "met"


async def test_only_this_project_s_dialogues_are_listed(runner, transcripts, project_id):
    """Red against a `for_project` with no filter, which would list every
    reader's dialogue on every project's page."""
    mine, theirs = uuid4(), uuid4()
    await _dialogue(transcripts, project_id, mine)
    await _dialogue(transcripts, uuid4(), theirs)
    await runner.caught_up()

    listed = await runner.for_project(project_id)

    assert [row.id for row in listed] == [mine]


async def test_a_rebuild_reproduces_the_positions_and_the_derived_question(
    runner, transcripts, project_id
):
    """`rebuild()` truncates and replays, and is allowed here for the reason it
    is allowed on the ask tables: every column comes from an event payload,
    including `position`, which the projection derives in log order and
    therefore reproduces. Red against a `position` taken from a row count read
    at insert time under a different physical order.

    **The second assertion is the one to keep.** `pending_prompt` is the only
    value in these tables that is *derived from another stored value* -- it is
    the newest turn's `prompt`, precomputed. Everything else is copied straight
    off an event, so nothing else here can disagree with the log. A projection
    that wrote it on start and forgot to overwrite it per turn, or that wrote
    it from the wrong field, produces a dialogue whose transcript reads
    perfectly and whose "what am I answering?" is a question from three
    exchanges ago -- and a rebuild is the moment that surfaces, which is the
    worst time to find it.

    This is the assertion the team lead asked for against an earlier draft that
    stored the outstanding question twice, in the form that survives now that
    it is stored once and derived. It is not awkward to write, which is the
    signal that the redundancy is at the right level: a read model precomputing
    something is fine, a log holding two copies of one utterance was not.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[("1", "a?", ()), ("2", "b?", ()), ("3", "c?", ())],
    )
    await runner.caught_up()
    before = [(turn.position, turn.prompt) for turn in await runner.turns_for(dialogue_id)]
    # The invariant, before the rebuild: the precomputed question is the newest
    # thing the dialogue actually said.
    assert (await runner.get(dialogue_id)).pending_prompt == before[-1][1] == "c?"

    await runner.rebuild()

    after = [(turn.position, turn.prompt) for turn in await runner.turns_for(dialogue_id)]
    assert after == before
    # And the derived value still agrees with the turns it was derived from.
    # A replay in a different physical order is exactly what would break this
    # while leaving every other column identical.
    assert (await runner.get(dialogue_id)).pending_prompt == after[-1][1]


async def test_a_turn_against_a_dialogue_the_projection_never_saw_is_dropped(
    runner, transcripts, project_id
):
    """The same policy `AskConversationStore.record` states: `decide` refuses a
    turn before a start, so the only way to arrive here is a log whose head
    this projection never saw, and a DLQ entry per turn would bury a real
    failure under a stream that cannot be repaired anyway.

    Driven by starting a dialogue, rebuilding from a checkpoint that skipped
    the head is not reachable from a test -- so this asserts the store's own
    guard directly, which is the honest reachable version.
    """
    from research_team.infrastructure.persistence.read_models import SocraticDialogueStore

    store = await SocraticDialogueStore.open(":memory:")
    try:
        await store.record(
            uuid4(),
            reply="nothing",
            prompt="orphan?",
            citations=[],
            recorded_at=datetime.now(UTC),
        )
        assert await store.turns_for(uuid4()) == []
    finally:
        await store.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/infrastructure/test_socratic_read_model.py -x`

Expected: FAIL —
`ImportError: cannot import name 'SocraticDialogueRunner' from ...read_models`.

- [ ] **Step 3: Write the rows and the store**

Add to `read_models.py`, after the `AskConversationRunner` class. Mirror
`AskConversationStore` exactly in shape — `open` applying both schemas then
creating the two indexes, `record` reading the parent row for its position, a
`truncate` that deletes from both tables:

```python
SOCRATIC_NAMESPACE = UUID("e1c7a9d2-4b0f-4a6e-9c31-2f58d7b6e410")
"""Namespace for derived socratic row ids. A fresh uuid5 namespace rather than
reusing `ASK_NAMESPACE`: the two id spaces would otherwise collide on a
dialogue and a conversation that happened to share an id and a position, which
is astronomically unlikely and free to prevent."""


class SocraticDialogueRow(ReadModel):
    """One dialogue. `id` is the dialogue id.

    The aggregate id itself with no `uuid5` over it, for `AskConversationRow`'s
    reason: the id is minted by the server and handed to the client, so
    deriving a second one would give every read route a key nothing returned.

    **`goal` and `stopping_condition` are the resumption path's source of
    truth.** When the live registry has dropped a dialogue, this row is what it
    is rebuilt from -- so a projection that stored the topic and dropped these
    two would resume a dialogue aimed at nothing, and every request would still
    answer 200.

    `observations` is a JSON list for `AskTurnRow.citations`' reason. A third
    table was the alternative and buys a query nothing issues; the spec asks
    for the two-table pattern and this is what keeps it.
    """

    __table_name__ = "socratic_dialogues"

    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    pending_prompt: str = ""
    """The question the reader is currently looking at.

    **Derived, not a second copy.** It is the last turn's `prompt`, or
    `opening_prompt` when there are no turns -- the projection writes it on
    start and overwrites it on each turn, so the log still holds each utterance
    once and this column is the precomputation a read model exists to do. A
    client asking "what am I answering?" would otherwise have to fetch every
    turn to find out.

    `rebuild()` reproduces it, because it is written in log order from event
    payloads like every other column here."""

    opened_at: datetime
    status: str = "started"
    concluded_reason: str = ""
    turn_count: int = 0
    observations: list[dict] = Field(default_factory=list)

    @field_validator("observations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class SocraticTurnRow(ReadModel):
    """One exchange: what the reader said, and what the dialogue said back.

    **`position` is stored, not inferred**, for `AskTurnRow`'s reason: a read
    leaning on insertion order is correct until `rebuild()` truncates and
    replays, which is supported here and free to insert in a different physical
    order.

    `prompt` is the dialogue's utterance and `reply` is the reader's -- the
    inverse of `AskTurnRow`, because this surface runs in the opposite
    direction. See `test_the_speakers_are_not_swapped_on_the_way_into_the_table`
    for what a swap would look like: a transcript that still reads as a
    conversation, just one where the reader asks all the questions.

    **A row is one exchange, reader first.** The question this row's `reply`
    answers is the *previous* row's `prompt` -- or `opening_prompt` on the
    dialogue, for row 0. So a client rendering only this table draws a
    transcript that starts with the reader; `openingPrompt` on the dialogue
    view is the missing first utterance, and the route's Interfaces block says
    so.
    """

    __table_name__ = "socratic_turns"

    dialogue_id: UUID
    project_id: UUID
    position: int
    prompt: str
    reply: str
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(dialogue_id: UUID, position: int) -> UUID:
        """Derived from the pair, so replaying one event twice rewrites a row
        rather than appending a second copy of the same turn."""
        return uuid5(SOCRATIC_NAMESPACE, f"{dialogue_id}:{position}")
```

Then `SocraticDialogueStore`, with `open` following `AskConversationStore.open`
verbatim in structure (both `apply_schema` calls, then these two indexes, then
`commit`):

```python
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_socratic_dialogues_project "
            f"ON {SocraticDialogueRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_socratic_turns_dialogue "
            f"ON {SocraticTurnRow.table_name()}(dialogue_id, position)",
        ):
            await connection.execute(statement)
```

and these methods:

```python
    async def start(
        self,
        dialogue_id: UUID,
        project_id: UUID,
        *,
        topic: str,
        goal: str,
        stopping_condition: str,
        opening_prompt: str,
        opened_at: datetime,
    ) -> None:
        await self._dialogues.save(
            SocraticDialogueRow(
                id=dialogue_id,
                project_id=project_id,
                topic=topic,
                goal=goal,
                stopping_condition=stopping_condition,
                opening_prompt=opening_prompt,
                # With no turns yet, the opening question is the outstanding
                # one. `record` overwrites this on every turn.
                pending_prompt=opening_prompt,
                opened_at=opened_at,
            )
        )

    async def record(
        self,
        dialogue_id: UUID,
        *,
        reply: str,
        prompt: str,
        citations: list[dict],
        recorded_at: datetime,
    ) -> None:
        """Store one exchange at the next position, and move the dialogue on.

        A turn against a dialogue with no row is dropped rather than raised on,
        for `AskConversationStore.record`'s reason: `decide` refuses a turn
        before a start, so the only way to arrive here is a log whose head this
        projection never saw, and a DLQ entry per turn would bury a real
        failure under a stream that cannot be repaired anyway.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        position = dialogue.turn_count
        await self._turns.save(
            SocraticTurnRow(
                id=SocraticTurnRow.row_id(dialogue_id, position),
                dialogue_id=dialogue_id,
                project_id=dialogue.project_id,
                position=position,
                reply=reply,
                prompt=prompt,
                citations=citations,
                recorded_at=recorded_at,
            )
        )
        dialogue.turn_count = position + 1
        # Precomputed, not a second copy: this turn's `prompt` is the newest
        # thing the dialogue said, so it is what the reader is now answering.
        # Derivable from the turns table; kept here so a client does not have
        # to fetch every turn to learn it.
        dialogue.pending_prompt = prompt
        await self._dialogues.save(dialogue)

    async def observe(
        self, dialogue_id: UUID, *, observation: str, evidence: str, detail: str
    ) -> None:
        """Append one observation to the dialogue's list.

        Read-modify-write on a JSON column, which is only safe because this
        projection is the single writer of these tables and processes one event
        at a time -- the same assumption `record`'s position counter already
        makes.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.observations = [
            *dialogue.observations,
            {"observation": observation, "evidence": evidence, "detail": detail},
        ]
        await self._dialogues.save(dialogue)

    async def conclude(self, dialogue_id: UUID, *, reason: str) -> None:
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.status = "concluded"
        dialogue.concluded_reason = reason
        await self._dialogues.save(dialogue)

    async def get(self, dialogue_id: UUID) -> SocraticDialogueRow | None:
        return await self._dialogues.get(dialogue_id)

    async def for_project(self, project_id: UUID) -> list[SocraticDialogueRow]:
        """A project's dialogues, most recently opened first."""
        return await self._dialogues.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="opened_at",
                order_direction="desc",
            )
        )

    async def turns_for(self, dialogue_id: UUID) -> list[SocraticTurnRow]:
        """One dialogue's exchanges, in the order they happened -- by the
        stored `position`, never by arrival. See `SocraticTurnRow`."""
        return await self._turns.find(
            Query(
                filters=[Filter(field="dialogue_id", operator="eq", value=str(dialogue_id))],
                order_by="position",
                order_direction="asc",
            )
        )
```

- [ ] **Step 4: Write the projection and the runner**

```python
class SocraticDialogueProjection(DeclarativeProjection):
    """Writes dialogues into the two tables above.

    Nothing else writes them: every column comes from an event payload, which
    is what lets `rebuild()` truncate.
    """

    def __init__(self, dialogues, checkpoint_repo=None, dlq_repo=None, tracer=None) -> None:
        self._dialogues = dialogues
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(SocraticDialogueStarted)
    async def _on_started(self, event: SocraticDialogueStarted) -> None:
        await self._dialogues.start(
            event.aggregate_id,
            event.project_id,
            topic=event.topic,
            goal=event.goal,
            stopping_condition=event.stopping_condition,
            opening_prompt=event.opening_prompt,
            opened_at=event.opened_at,
        )

    @handles(SocraticTurnRecorded)
    async def _on_turn(self, event: SocraticTurnRecorded) -> None:
        """`event.occurred_at` rather than a clock read, for the reason
        `AskConversationProjection._on_turn` gives: a rebuild has to reproduce
        the timestamps it produced the first time, not today's."""
        await self._dialogues.record(
            event.aggregate_id,
            reply=event.reply,
            prompt=event.prompt,
            citations=[{"kind": kind, "id": cited} for kind, cited in event.citations],
            recorded_at=event.occurred_at,
        )

    @handles(SocraticProgressObserved)
    async def _on_observed(self, event: SocraticProgressObserved) -> None:
        await self._dialogues.observe(
            event.aggregate_id,
            observation=event.observation,
            evidence=event.evidence,
            detail=event.detail,
        )

    @handles(SocraticDialogueConcluded)
    async def _on_concluded(self, event: SocraticDialogueConcluded) -> None:
        await self._dialogues.conclude(event.aggregate_id, reason=event.reason)
```

Then `SocraticDialogueRunner`, copied from `AskConversationRunner` in structure —
same `start`, `stop`, `failures`, `_started`, `rebuild`, `caught_up`, and the same
`RuntimeError(f"the socratic projection failed to start: {failures}")` shape. Its
docstring:

```python
    """Keeps the dialogue tables following the log.

    A ninth runner, for `AskConversationRunner`'s reason: a
    `rebuild()`/`failures()`-shaped surface for these tables alone, and a
    `rebuild()` that cannot truncate tables it does not own.

    **This is also the read side of resumption.** `get` and `turns_for` are
    what `SocraticDialogueService` reads through when the live registry has
    dropped a dialogue, so a build that never constructs this does not merely
    serve an empty history list -- it makes every resumed dialogue start over
    while telling the reader it continued.
    """
```

- [ ] **Step 5: Run the read-model tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_socratic_read_model.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 6: Prove the row-exists assertions red**

Comment out the `@handles(SocraticDialogueStarted)` decorator on `_on_started` and
re-run. Expected: `test_a_started_dialogue_stores_its_goal_and_stopping_condition`
fails on `assert row is not None`, **not** on anything raising — that is the point.
Restore the decorator.

This is the repository's convention and it is the one measurement this task exists
to take: an event no projection handles counts as APPLIED, so nothing anywhere
raises and every weaker assertion stays green.

- [ ] **Step 7: Verify against a database that predates the change**

```
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/socratic-probe.db
```

Then, with the `AGENT_DB=` line that prints, start a `SocraticDialogueRunner`
against `/tmp/socratic-probe.db` and call `for_project(uuid4())`.

Expected: the two tables are created, `for_project` answers `[]`, and nothing
raises `PositionForeignError`.

**State the honest limit in your notes:** these are new tables, so this does not
exercise `apply_schema`'s column-widening path at all. What it does prove is that
`SocraticDialogueStore.open` succeeds against a database that already holds
`projection_checkpoints` and every other table — which is the failure mode a fresh
`tmp_path` database cannot show. Widening either row later is the change that needs
the full reconcile check.

**Do not delete `projection_checkpoints` to get the copy up.** `local_copy` rebinds
the store id in each token; clearing them makes every projection replay the whole
log, which is `/rebuild` by another name and hides the half of the bug that matters.

- [ ] **Step 8: Wiring**

Nothing constructs the runner yet — Task 4 does. Confirm the resumption test's
failure is unchanged:

Run: `uv run pytest tests/application/test_socratic_resumption.py -x`

Expected: still `ModuleNotFoundError: No module named 'research_team.application.socratic'`.
Two tasks in, the test that matters has not moved, and that is correct: it is a
service test and the service starts in Task 3.

- [ ] **Step 9: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 10: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py \
  tests/infrastructure/test_socratic_read_model.py
git commit -m "Project dialogues into two tables, goal and condition included

The two-table pattern the ask read model established, with the columns the
resumption path actually reads: goal and stopping_condition are this feature's
source of truth once the live registry has dropped a dialogue, so a projection
that stored the topic and lost those two would resume a dialogue aimed at
nothing while every request still answered 200.

Every assertion in the test file is on a row and on the value the event
carried. Proved by commenting out the @handles decorator on the start handler:
nothing raises, replay completes cleanly, and the test fails on row is None --
which is what an event no projection handles does, and why any assertion about
a status code would have stayed green.

observations rides the dialogue row as JSON rather than getting a third table.
It buys a query nothing issues; the spec asks for the two-table pattern and
this is what keeps it. evidence is stored beside each observation because a
stopping condition met entirely by the model's own assessments is a dialogue
that graded its own homework, and storing the kind is the only thing that makes
that visible later.

position is a stored column, not insertion order, so rebuild() reproduces it --
asserted by rebuilding and comparing.

Verified against a copy of a real database via local_copy, which rebinds the
store id in each checkpoint token. The honest limit: these are new tables, so
apply_schema's widening path is not exercised. What it proves is that open()
succeeds against a database that already has projection_checkpoints, which a
fresh tmp_path database cannot show.

Nothing constructs the runner yet."
```

---

### Task 3: The service, and resumption

This is the task the plan exists for.

**Files:**
- Create: `research_team/application/socratic.py`
- Create: `tests/application/test_socratic_service.py`
- Modify: `tests/application/test_socratic_resumption.py` (only if a name in it
  turns out to be wrong — the file is the specification, not a draft)

**Interfaces:**
- Consumes: Task 1's aggregate and commands; `AggregateRepository`;
  `ActivityNote`, `ActivityReporter` from `research_team.application.ports`.
- Produces, for Tasks 4–5 and Plans 2–3:

```python
Role = Literal["user", "assistant"]

@dataclass(frozen=True)
class DialogueMessage:
    role: Role
    text: str

@dataclass(frozen=True)
class SocraticFraming:
    goal: str
    stopping_condition: str
    opening_prompt: str

@dataclass(frozen=True)
class SocraticObservation:
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""

# The executor's output: the dialogue's NEXT question, not a reply to
# anything. Named for what it holds -- an earlier draft called this
# `SocraticReply` with a `text` field, which put a question in a field named
# for the reader's answer and is precisely the confusion the naming ruling
# exists to prevent.
@dataclass(frozen=True)
class SocraticPrompt:
    prompt: str
    citations: tuple[Citation, ...] = ()
    observation: SocraticObservation | None = None
    concluded: bool = False
    """The stopping condition was met by the exchange that produced this.
    `prompt` is empty when so -- there is no further question."""
    position: int = 0

@dataclass(frozen=True)
class SocraticDialogueOpened:
    dialogue_id: UUID
    goal: str
    stopping_condition: str
    pending_prompt: str
    """The question the reader is looking at right now: the opening one on a
    fresh dialogue, the outstanding one on a resumed dialogue. Named for what
    it is rather than `opening_prompt`, because after an eviction it is not
    the opening question and a page that labelled it so would be lying."""

SocraticNote = SocraticDialogueOpened | ActivityNote | SocraticPrompt

class UnknownDialogue(LookupError): ...
class DialogueInFlight(RuntimeError): ...

@dataclass(frozen=True)
class LiveDialogue:
    dialogue_id: UUID
    project_id: UUID
    goal: str
    stopping_condition: str
    messages: tuple[DialogueMessage, ...] = ()
    """The conversation so far, alternating assistant/user and *starting* with
    the assistant -- the opening question is `messages[0]`. The outstanding
    question is simply `messages[-1]`, so nothing here caches it."""
    used_at: float = 0.0
    def appended(self, *messages: DialogueMessage, at: float) -> "LiveDialogue": ...

class DialogueRegistry:
    def __init__(self, *, now, limit: int = 64, idle_seconds: float = 3_600.0) -> None: ...
    def __len__(self) -> int: ...
    def get(self, dialogue_id: UUID, project_id: UUID) -> LiveDialogue | None: ...
    def put(self, dialogue: LiveDialogue) -> None: ...
    def drop(self, dialogue_id: UUID) -> None: ...

class SocraticExecutor(Protocol):
    async def frame(self, *, project_id: UUID, topic: str) -> SocraticFraming: ...
    async def respond(self, *, project_id: UUID, history: Sequence[DialogueMessage],
                      goal: str, stopping_condition: str, reply: str,
                      on_activity: ActivityReporter) -> SocraticPrompt: ...

class DialogueReadModel(Protocol):
    async def get(self, dialogue_id: UUID) -> Any | None: ...
    async def turns_for(self, dialogue_id: UUID) -> list[Any]: ...

class SocraticDialogueService:
    def __init__(self, *, executor: SocraticExecutor, dialogues: DialogueRegistry,
                 read_model: DialogueReadModel, now: Callable[[], float],
                 transcripts: AggregateRepository[SocraticDialogue],
                 clock: Callable[[], datetime]) -> None: ...
    async def begin(self, *, project_id: UUID, topic: str) -> UUID: ...
    def respond(self, *, project_id: UUID, dialogue_id: UUID,
                reply: str) -> AsyncIterator[SocraticNote]: ...
    def forget(self, dialogue_id: UUID) -> None: ...
```

`DialogueReadModel` is a Protocol over `Any`-typed rows deliberately: the
application layer cannot name `SocraticDialogueRow` without importing
infrastructure, and the service reads only `.project_id`, `.goal`,
`.stopping_condition`, `.status`, `.prompt`, `.reply`. Structural typing is what
lets `SocraticDialogueRunner` satisfy it with no adapter — and the composed
pairing is what Task 4 proves.

- [ ] **Step 1: Run the resumption test and confirm where it stands**

Run: `uv run pytest tests/application/test_socratic_resumption.py -x`

Expected: `ModuleNotFoundError: No module named 'research_team.application.socratic'`,
unchanged since Task 1. This step exists so the next one has a baseline.

- [ ] **Step 2: Write the rest of the service's tests**

Create `tests/application/test_socratic_service.py`:

```python
"""What the service does around the executor, other than resume.

Resumption is in `test_socratic_resumption.py`, alone, because it is the
requirement the spec says to write first and a file named for it is harder to
delete by accident than four assertions among twenty.

Every assertion about persistence reads the stream. "The call returned" is
compatible with nothing having been written -- an event no projection handles
counts as applied, so there is no layer below this that would have complained.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.socratic import (
    DialogueInFlight,
    DialogueRegistry,
    LiveDialogue,
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticFraming,
    SocraticObservation,
    SocraticPrompt,
)
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticProgressObserved,
    SocraticTurnRecorded,
)

PROJECT_ID = uuid4()


class StubExecutor:
    def __init__(self, questions=None, fail=None):
        self._questions = list(questions or [SocraticPrompt(prompt="why?")])
        self.fail = fail

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal="understand it",
            stopping_condition="the reader states it plainly",
            opening_prompt="what do you think?",
        )

    async def respond(self, *, project_id, history, goal, stopping_condition, reply, on_activity):
        if self.fail is not None:
            raise self.fail
        return self._questions.pop(0)


class EmptyReadModel:
    async def get(self, dialogue_id):
        return None

    async def turns_for(self, dialogue_id):
        return []


@pytest.fixture
def transcripts():
    return AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)


def build(executor, transcripts, read_model=None):
    return SocraticDialogueService(
        executor=executor,
        dialogues=DialogueRegistry(now=lambda: 0.0),
        read_model=read_model or EmptyReadModel(),
        now=lambda: 0.0,
        transcripts=transcripts,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    )


async def drain(iterator):
    return [note async for note in iterator]


async def events_on(transcripts, dialogue_id):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(transcripts.event_store.read_stream(stream))
    ]


async def test_beginning_a_dialogue_writes_the_framing_the_model_chose(transcripts):
    """The goal and the stopping condition are set once, at the start, by the
    model -- and are then the reader's to see (spec §5). This asserts they
    reach the stream, which is the only place the resumption path can find
    them again. Red against a service that holds the framing in the registry
    and never records it.
    """
    service = build(StubExecutor(), transcripts)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    recorded = await events_on(transcripts, dialogue_id)
    assert [type(e) for e in recorded] == [SocraticDialogueStarted]
    assert recorded[0].project_id == PROJECT_ID
    assert recorded[0].topic == "the creed"
    assert recorded[0].goal == "understand it"
    assert recorded[0].stopping_condition == "the reader states it plainly"
    assert recorded[0].opening_prompt == "what do you think?"


async def test_the_first_note_names_the_dialogue_and_what_it_is_for(transcripts):
    """`SocraticDialogueOpened` carries the framing as well as the id, so the
    page can show the reader what this dialogue is aiming at before they have
    typed anything. A reader who disagrees with the goal should be able to see
    that they disagree before spending twenty minutes on it (spec §5).
    """
    service = build(StubExecutor(), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    notes = await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="hello")
    )

    assert isinstance(notes[0], SocraticDialogueOpened)
    assert notes[0].dialogue_id == dialogue_id
    assert notes[0].goal == "understand it"
    assert notes[0].stopping_condition == "the reader states it plainly"
    # The question the reader is answering, which on a fresh dialogue is the
    # opening one. On a resumed dialogue it is whatever was outstanding, which
    # is why the field is not called `opening_prompt`.
    assert notes[0].pending_prompt == "what do you think?"


async def test_a_failed_turn_records_nothing(transcripts):
    """`SocraticTurnRecorded` is a fact about an exchange that happened, not an
    attempt that was made -- the same rule `AskTurnRecorded` follows. Red
    against a service that appends before awaiting the executor.
    """
    service = build(StubExecutor(fail=RuntimeError("the model is down")), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    with pytest.raises(RuntimeError, match="model is down"):
        await drain(
            service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="hello")
        )

    assert [type(e) for e in await events_on(transcripts, dialogue_id)] == [
        SocraticDialogueStarted
    ]


async def test_an_observation_the_executor_reported_is_recorded_beside_the_turn(
    transcripts,
):
    """Two events from one exchange, in that order: the turn happened, and then
    something was demonstrated in it. Red against a service that folds the
    observation into the turn event, which would make progress unreadable
    without re-parsing every reply.
    """
    service = build(
        StubExecutor(
            [
                SocraticPrompt(
                    prompt="what makes you say that?",
                    observation=SocraticObservation(
                        observation="named both parties",
                        evidence="assessment",
                    ),
                )
            ]
        ),
        transcripts,
    )
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="Arius and Athanasius")
    )

    assert [type(e) for e in await events_on(transcripts, dialogue_id)] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticProgressObserved,
    ]


async def test_a_reply_that_concludes_the_dialogue_ends_it_as_met(transcripts):
    """The stopping condition, actually stopping something. Red against a
    service that carries `concluded` to the browser and never writes it: the
    dialogue would look finished and would accept a further turn on reload.
    """
    service = build(
        StubExecutor([SocraticPrompt(prompt="", concluded=True)]),
        transcripts,
    )
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="one substance")
    )

    recorded = await events_on(transcripts, dialogue_id)
    assert [type(e) for e in recorded] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticDialogueConcluded,
    ]
    assert recorded[2].reason == "met"


async def test_two_replies_at_once_on_one_dialogue_are_refused(transcripts):
    """One reply at a time per dialogue, for `AskInFlight`'s reason: two
    streams interleaving into one transcript is worse for the reader than a
    refusal they can act on -- and here it would also interleave two writes to
    one stream.
    """
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowExecutor(StubExecutor):
        async def respond(self, **kwargs):
            started.set()
            await release.wait()
            return SocraticPrompt(prompt="why?")

    service = build(SlowExecutor(), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    first = asyncio.create_task(
        drain(service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="a"))
    )
    await started.wait()
    with pytest.raises(DialogueInFlight):
        await drain(
            service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="b")
        )
    release.set()
    await first


def test_the_registry_returns_nothing_on_a_miss_rather_than_a_fresh_dialogue():
    """The one line that differs from `ConversationRegistry`, tested on its own.

    `ConversationRegistry.get` returns a brand-new `Conversation` on a miss,
    which is why an evicted ask silently starts over on a new stream. Returning
    `None` here is what forces the caller to decide, and there is nowhere for
    that decision to be made silently.

    Red against a copy-paste of `ConversationRegistry.get`, which is exactly
    how this would be written by someone reusing the neighbour.
    """
    registry = DialogueRegistry(now=lambda: 0.0)
    dialogue_id = uuid4()

    assert registry.get(dialogue_id, PROJECT_ID) is None

    registry.put(
        LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=PROJECT_ID,
            goal="g",
            stopping_condition="s",
        )
    )
    assert registry.get(dialogue_id, PROJECT_ID) is not None
    # Another project's id is a miss, not a hit on someone else's dialogue.
    assert registry.get(dialogue_id, uuid4()) is None

    registry.drop(dialogue_id)
    assert registry.get(dialogue_id, PROJECT_ID) is None


def test_an_idle_dialogue_is_evicted_and_a_busy_one_is_not():
    """The bound that makes resumption necessary in the first place. A clock
    the test drives, so this does not sleep."""
    clock = {"t": 0.0}
    registry = DialogueRegistry(now=lambda: clock["t"], idle_seconds=10.0)
    dialogue_id = uuid4()
    registry.put(
        LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=PROJECT_ID,
            goal="g",
            stopping_condition="s",
            used_at=0.0,
        )
    )

    clock["t"] = 9.0
    assert registry.get(dialogue_id, PROJECT_ID) is not None
    clock["t"] = 11.0
    assert registry.get(dialogue_id, PROJECT_ID) is None
```

- [ ] **Step 3: Run both service test files to verify they fail**

Run: `uv run pytest tests/application/test_socratic_service.py tests/application/test_socratic_resumption.py -x`

Expected: FAIL at collection on the missing module, for both files.

- [ ] **Step 4: Write the service**

Create `research_team/application/socratic.py`. Structure it as
`application/ask.py` is structured — messages, the live entry, the registry, the
port, the service — and write these docstrings, which carry the reasoning this
task exists for:

```python
"""A guided dialogue over a project's gathered material.

A parallel path to `AskService`, not a caller of it: the two share a shape and
almost nothing else, and the thing that is genuinely different is the one this
module is mostly about.

**An evicted ask resumes with no history, on a fresh stream.** That is
`ConversationRegistry`'s documented behaviour and an accepted cost for an ask --
a dropped chat is a lost convenience. For a goal-directed dialogue it is a
correctness problem: a reader who comes back after lunch to a dialogue that has
forgotten its goal, its progress and its stopping condition has not resumed
anything, they have started over while believing otherwise.

So this module's registry is a cache *in front of a read model*, not the record
itself. `DialogueRegistry.get` returns `None` on a miss where
`ConversationRegistry.get` returns a fresh conversation, and the service
rehydrates from stored turns rather than minting a new stream. That one return
type is the whole difference, and `tests/application/test_socratic_resumption.py`
is what fails if it is ever copy-pasted back.

Nothing in this module may import a framework. `tests/test_architecture.py`
holds the application layer to `eventsource` alone, so everything LangChain-
shaped lives behind `SocraticExecutor` and is implemented in
`infrastructure/agent/`.

`DialogueMessage` duplicates `AskMessage` rather than importing it, and the
duplication is deliberate: a dialogue's history will want observations
interleaved into it before an ask's does, and a shared type is where that
divergence becomes a change to both surfaces. Three lines is the price.
"""
```

```python
class DialogueRegistry:
    """Live dialogues, bounded two ways -- and only a cache.

    The defaults match `ConversationRegistry`'s (64 entries, an hour idle) and
    are guesses at a single-user console rather than measurements.

    **`get` returns `None` on a miss.** That is the one line that differs from
    the neighbour this is otherwise modelled on, and it is the whole of §2 of
    the design. `ConversationRegistry.get` hands back a fresh `Conversation`
    with a fresh stream id, so an evicted ask starts over silently; here the
    caller is made to decide, and the only honest decisions are "rehydrate" and
    "refuse".
    """
```

```python
class SocraticExecutor(Protocol):
    """Frames a dialogue, and takes one turn in it.

    Two methods rather than one because they happen at different times and want
    different things: `frame` runs once, from a topic, and produces the goal and
    stopping condition that everything after it is measured against; `respond`
    runs per exchange and is handed that framing rather than deriving it.

    Keeping the framing out of `respond` is what makes the stopping condition
    testable. The agent is built fresh per turn with no checkpointer -- a
    `MemorySaver` was tried on the ask path and raised, because `astream`
    passes no `thread_id` -- so a stopping condition held in the model's context
    would not survive a turn boundary, let alone an eviction. It lives in the
    aggregate, which is the right place for it anyway: a stopping condition
    decided inside an LLM's context is one nothing can test.

    `on_activity` must not be called after `respond` returns, for the reason
    `AskExecutor` states at length -- the drain loop relies on every report
    happening-before the executor task's completion.
    """
```

The service's `respond` follows `AskService.ask`'s body closely — the in-flight
guard, the `SocraticDialogueOpened` note first, the `asyncio.Queue` drain, the
`finally` that cancels an abandoned executor task, and the record-before-yield
ordering with its comment. The new part is the front:

```python
    async def _resume(self, project_id: UUID, dialogue_id: UUID) -> LiveDialogue:
        """The live dialogue, from the cache or from the read model.

        The read-through the ask path deliberately declined. Three refusals are
        folded in here and each is a different bug if it is missed:

        * no row at all -- a guessed, stale or deleted id. Refused rather than
          started fresh: a dialogue that quietly became a new one would hand
          the reader a blank conversation under a URL they thought they knew.
        * a row belonging to another project. `RecordSocraticTurn` carries no
          project id, so `decide` has nothing to compare and this is the only
          line of defence -- exactly as `ConversationRegistry.get`'s project
          check is for an ask.
        * a concluded dialogue. `decide` would refuse the turn anyway, but only
          after the model had been called and paid for.

        The turns are folded back into `messages` in stored `position` order,
        which is why `SocraticTurnRow.position` is a column rather than
        insertion order: a rehydrated history in the wrong order is a
        conversation the model is asked to continue from a jumbled transcript,
        and it will do so without complaint.

        **The opening question comes first and comes from the start event.** A
        turn is `(reply, prompt)` -- the reader's answer and the response it
        drew -- so folding the turns alone produces a history that begins with
        the reader answering something nobody asked. `opening_prompt` is the
        missing first utterance, and it is on the dialogue row rather than any
        turn because it precedes them all.

        The result alternates assistant/user/assistant/... and ends on the
        dialogue's newest utterance, which is exactly the question the reader
        is now answering. Nothing is read twice and nothing is inferred.
        """
        cached = self._dialogues.get(dialogue_id, project_id)
        if cached is not None:
            return cached
        row = await self._read_model.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise UnknownDialogue(f"no dialogue {dialogue_id} in project {project_id}")
        if getattr(row, "status", "started") == "concluded":
            raise UnknownDialogue(f"dialogue {dialogue_id} has already concluded")
        messages: list[DialogueMessage] = []
        if row.opening_prompt:
            messages.append(DialogueMessage(role="assistant", text=row.opening_prompt))
        for turn in await self._read_model.turns_for(dialogue_id):
            messages.append(DialogueMessage(role="user", text=turn.reply))
            messages.append(DialogueMessage(role="assistant", text=turn.prompt))
        return LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=project_id,
            goal=row.goal,
            stopping_condition=row.stopping_condition,
            messages=tuple(messages),
            used_at=self._now(),
        )
```

and the record, which unlike the ask's never has to decide whether to start the
stream — `begin` already did:

```python
    async def _record(
        self, dialogue: LiveDialogue, *, reply: str, asked: SocraticPrompt
    ) -> None:
        """Append this exchange, and anything it demonstrated.

        The exchange is `(reply, asked.prompt)`: what the reader typed, and
        what the dialogue said back. The question the reader was answering is
        already in the log -- as the previous turn's `prompt`, or as
        `opening_prompt` -- so it is not written again here. See
        `SocraticTurnRecorded` for why that pairing rather than the other one.

        Always a `load`, never a `create_new`: `begin` is the only thing that
        starts a stream, so by the time anything reaches here the stream
        exists. That is simpler than `AskService._record`, which has to infer
        the same fact from an empty message list -- and it is simpler for the
        reason this whole module exists, that a dialogue's identity outlives
        its cache entry.
        """
        aggregate = await self._transcripts.load(dialogue.dialogue_id)
        aggregate.execute(
            RecordSocraticTurn(
                dialogue_id=dialogue.dialogue_id,
                reply=reply,
                prompt=asked.prompt,
                citations=asked.citations,
            )
        )
        if asked.observation is not None:
            aggregate.execute(
                ObserveSocraticProgress(
                    dialogue_id=dialogue.dialogue_id,
                    observation=asked.observation.observation,
                    evidence=asked.observation.evidence,
                    detail=asked.observation.detail,
                )
            )
        if asked.concluded:
            aggregate.execute(
                ConcludeSocraticDialogue(dialogue_id=dialogue.dialogue_id, reason="met")
            )
        await self._transcripts.save(aggregate)
```

- [ ] **Step 5: Run the resumption test — the moment this plan is for**

Run: `uv run pytest tests/application/test_socratic_resumption.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 6: Run the rest**

Run: `uv run pytest tests/application/test_socratic_service.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 7: Prove the resumption test red the way it would really break**

Change `DialogueRegistry.get` to return a fresh `LiveDialogue` on a miss — the
`ConversationRegistry.get` body, which is what a copy-paste produces:

```python
        if held is None or held.project_id != project_id or now - held.used_at > self._idle_seconds:
            self._held.pop(dialogue_id, None)
            return LiveDialogue(dialogue_id=dialogue_id, project_id=project_id, used_at=now)
```

Re-run `test_an_evicted_dialogue_resumes_on_the_same_stream`. Expected: it fails on
the goal being empty, and — the assertion that matters —
`all_dialogue_ids` still returns one id, because the *service* would then append to
the same aggregate with a blank framing. Note which assertion caught it; if only the
goal assertion fires and the history assertion does not, say so in your commit
message rather than claiming the test covers more than it does.

Restore the `None` return.

- [ ] **Step 8: Wiring**

Nothing constructs the service yet — Task 4 does. Confirm the layering:

Run: `uv run pytest tests/test_architecture.py -v`

Expected: PASS. `research_team/application/socratic.py` must import `eventsource`
and the domain and nothing framework-shaped; the `SocraticExecutor` Protocol is the
whole point of that constraint.

- [ ] **Step 9: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 10: Commit**

```bash
git add research_team/application/socratic.py \
  tests/application/test_socratic_service.py \
  tests/application/test_socratic_resumption.py
git commit -m "Resume a dialogue from its read model, not from the cache

The one piece of new machinery in this spec, and the one whose absence looks
exactly like working software for an hour.

DialogueRegistry.get returns None on a miss. ConversationRegistry.get returns a
fresh Conversation with a fresh stream id, which is why an evicted ask silently
starts over -- an accepted cost there, a correctness bug here, because a reader
who comes back to a dialogue that has forgotten its goal has started over while
believing otherwise. Returning None is what forces the caller to decide, and
there is nowhere for that decision to be made silently.

Proved red by restoring the ConversationRegistry.get body: the resumption test
fails on an empty goal, and the executor is asked to continue a dialogue aimed
at nothing while the reply, the id and any status code all look correct.

Three refusals fold into _resume and each is a different bug: an unknown id is
refused rather than started fresh, because a dialogue that quietly became a new
one hands the reader a blank conversation under a URL they thought they knew; a
row from another project is refused because RecordSocraticTurn carries no
project id and decide has nothing to compare; a concluded dialogue is refused
before the model is called rather than after, which decide would do anyway but
only once it had been paid for.

DialogueMessage duplicates AskMessage rather than importing it. A dialogue's
history will want observations interleaved before an ask's does, and a shared
type is where that divergence becomes a change to both surfaces.

The executor is a port. Plan 2 implements it; a stub drives every test here."
```

---

### Task 4: Composition, and the test that catches a projection nobody built

**Files:**
- Modify: `research_team/composition.py` — the runner beside `asks` (~line 1115),
  the service beside `ask_service` (~line 1923), two `Application` fields (~line 451),
  and the two arguments in the `Application(...)` construction (~line 2322)
- Create: `tests/integration/test_a_dialogue_survives_a_restart.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `Application.dialogues: SocraticDialogueRunner` and
  `Application.socratic: SocraticDialogueService`, plus `application.start()`
  starting the runner. Plan 2 adds the executor here and the `create_app`
  parameters; **this task wires the stub-free service with a placeholder executor
  and says so.**

The executor question, decided here so Task 4 can be finished: `SocraticDialogueService`
takes `executor` as a required argument, and this plan has no real one. Construct it
in `composition.py` with `DeepAgentAskExecutor`'s socratic sibling **absent** by
passing an executor that raises:

```python
class _UnbuiltSocraticExecutor:
    """A placeholder until Plan 2 builds the real one.

    Raises rather than returning a canned reply, and raises at *call* time
    rather than at composition: composing must succeed so the runner, the
    service and the history routes are all reachable and testable now, and a
    caller that actually tries to hold a dialogue must be told plainly rather
    than handed a stub answer that looks like a model's.

    Delete this class in Plan 2. `grep _UnbuiltSocraticExecutor` is how you
    find every line that has to change.
    """

    async def frame(self, *, project_id, topic):
        raise NotImplementedError("the socratic executor is not built yet")

    async def respond(self, **_kwargs):
        raise NotImplementedError("the socratic executor is not built yet")
```

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_a_dialogue_survives_a_restart.py`:

```python
"""The whole feature, over applications the composition root actually built.

Everything else about dialogues is green in a build where `composition.py`
never constructs a `SocraticDialogueRunner`: the service appends its events,
nothing is subscribed to them, and `eventsource` counts an event no projection
handles as APPLIED rather than rejected. Nothing raises, nothing logs, and
every history request answers an empty list -- and, worse than for an ask,
every resumed dialogue starts over while telling the reader it continued.

That is the failure this codebase has shipped six times, which is why every
assertion below is on a turn's *text* and a dialogue's *goal*, never on
`start()` returning or a request succeeding.

Two applications over one database file, the second standing in for the
restart, exactly as `test_ask_survives_a_restart.py` does -- a second
`build_application` over the same `tmp_path` reaches the same state, with the
first application's projection stopped and the tables re-derived or resumed by
a process that did not append the events.

**The executor is a stub, stated rather than implied.** `application.socratic`
is the composed service with the composed repository and the composed read
model behind it; only the thing that would call a model is replaced. What this
proves is that a turn appended through the composed service reaches the
composed read model and the composed resumption path -- not anything about an
agent.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.interfaces.web import create_app


class StubExecutor:
    """Frames once and answers whatever it was handed, in order.

    Remembers the history and framing of its last call, which is what the
    resumption assertion reads.
    """

    def __init__(self, questions: list[str]) -> None:
        self._questions = list(questions)
        self.last: dict | None = None

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition=f"the reader explains {topic} unaided",
            opening_prompt=f"What do you make of {topic}?",
        )

    async def respond(self, *, project_id, history, goal, stopping_condition, reply, on_activity):
        self.last = {
            "history": [(m.role, m.text) for m in history],
            "goal": goal,
            "stopping_condition": stopping_condition,
        }
        return SocraticPrompt(prompt=self._questions.pop(0))


@pytest.fixture
def db_file(tmp_path) -> str:
    return str(tmp_path / "dialogue-restart.db")


async def _application(db_file, questions):
    """A started application whose socratic executor is a stub.

    Replaced on the composed service rather than injected through
    `build_application`, which takes no such parameter -- reaching for the
    private attribute is the smaller lie than building a
    `SocraticDialogueService` by hand here, because a hand-built one would be
    exactly the thing this file is meant to prove is composed.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_file
    )
    await application.start()
    stub = StubExecutor(questions)
    application.socratic._executor = stub
    return application, stub


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def test_a_dialogue_reaches_the_composed_read_model(db_file):
    """The assertion is on the stored text of the turn, and on the goal.

    Red against a build with no `SocraticDialogueRunner` constructed: the
    events are appended, nothing follows them, `turns_for` comes back empty,
    and this fails on the list length rather than on anything raising.
    """
    application, _stub = await _application(db_file, ["Why do you say that?"])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the Nicene settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
        ):
            pass
        await application.dialogues.caught_up()

        row = await application.dialogues.get(dialogue_id)
        assert row is not None, "no row: no runner is following the log"
        assert row.goal == "understand the Nicene settlement"
        assert row.turn_count == 1
        # The dialogue's newest question, which belongs to no turn.
        assert row.pending_prompt == "Why do you say that?"

        turns = await application.dialogues.turns_for(dialogue_id)
        assert [(t.prompt, t.reply) for t in turns] == [
            # The opening question the framing chose, and the reader's answer
            # to it -- the dialogue speaking first, as this surface does.
            ("What do you make of the Nicene settlement?", "It settled Arianism.")
        ]
    finally:
        await application.close()


async def test_a_dialogue_resumes_across_a_restart_on_the_same_stream(db_file):
    """The spec's §2, over the composed pairing rather than a stub read model.

    The second application has never seen this dialogue in memory -- its
    registry is empty by construction -- so the only way the framing and the
    history can reach the executor is through the read model the first
    application's events built. Red against a composition that wires the
    service without the runner, or wires the runner and hands the service
    something else.
    """
    first, _ = await _application(db_file, ["Why do you say that?"])
    try:
        project_id = await _project(first)
        dialogue_id = await first.socratic.begin(
            project_id=project_id, topic="the Nicene settlement"
        )
        async for _note in first.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
        ):
            pass
        await first.dialogues.caught_up()
    finally:
        await first.close()

    second, stub = await _application(db_file, ["And what follows from that?"])
    try:
        async for _note in second.socratic.respond(
            project_id=project_id,
            dialogue_id=dialogue_id,
            reply="Because the creed names the Son as of one substance.",
        ):
            pass
        await second.dialogues.caught_up()

        assert stub.last is not None
        assert stub.last["goal"] == "understand the Nicene settlement"
        assert stub.last["stopping_condition"] == (
            "the reader explains the Nicene settlement unaided"
        )
        # The dialogue speaks first, and the outstanding question is last --
        # rebuilt out of the stored `opening_prompt` and the stored turns, by a
        # process that appended none of them.
        assert stub.last["history"] == [
            ("assistant", "What do you make of the Nicene settlement?"),
            ("user", "It settled Arianism."),
            ("assistant", "Why do you say that?"),
        ]

        # One dialogue, two turns, one stream.
        row = await second.dialogues.get(dialogue_id)
        assert row.turn_count == 2
        assert row.pending_prompt == "And what follows from that?"
        assert [t.position for t in await second.dialogues.turns_for(dialogue_id)] == [0, 1]
        assert len(await second.dialogues.for_project(project_id)) == 1
    finally:
        await second.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_a_dialogue_survives_a_restart.py -x`

Expected: FAIL — `AttributeError: 'Application' object has no attribute 'socratic'`.

- [ ] **Step 3: Wire the runner**

In `composition.py`, beside the `asks = AskConversationRunner(...)` block:

```python
    # The ninth, built here with the other eight and for the same reason, with
    # a worse failure mode than any of them: a dialogue appends whether or not
    # anything is following, so a build missing this line answers 200 with an
    # empty history for every dialogue anyone ever held -- AND makes every
    # resumed dialogue start over with a blank goal while telling the reader it
    # continued. `test_a_dialogue_survives_a_restart.py` is what fails.
    dialogues = SocraticDialogueRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
```

- [ ] **Step 4: Wire the service**

Beside `ask_service = AskService(...)`:

```python
    # Built here for `ask_service`'s reason. The executor is a placeholder --
    # see `_UnbuiltSocraticExecutor` -- because the prompted agent is a
    # separate slice; everything else about a dialogue is composed and
    # reachable now, which is what lets the read model and the resumption path
    # be tested against a build the composition root actually made.
    #
    # `read_model=dialogues` is the whole of resumption's wiring, and it is one
    # keyword. A build that passed something else here -- or nothing -- would
    # compose, serve, and start every resumed dialogue over.
    socratic_service = SocraticDialogueService(
        executor=_UnbuiltSocraticExecutor(),
        dialogues=DialogueRegistry(now=time.monotonic),
        read_model=dialogues,
        now=time.monotonic,
        transcripts=build_socratic_dialogue_repository(
            repository.store, repository.publisher
        ),
        clock=lambda: datetime.now(UTC),
    )
```

Add the imports, add the two fields to the `Application` dataclass with docstrings
in the register the neighbours use, pass `dialogues=dialogues` and
`socratic=socratic_service` in the `Application(...)` construction, and add
`dialogues` to whatever `start()`/`close()` already do for `asks` — **find that by
reading, not by guessing**: `grep -n "asks" research_team/composition.py` shows every
line the ask runner appears on, and the dialogue runner needs the same set.

- [ ] **Step 5: Run the integration test to verify it passes**

Run: `uv run pytest tests/integration/test_a_dialogue_survives_a_restart.py -v`

Expected: PASS, 2 tests.

- [ ] **Step 6: Prove it red the way it would really ship**

Comment out the `dialogues = SocraticDialogueRunner(...)` construction and pass
`read_model=None` — the shape of a build where somebody wired the service and
forgot the runner. Re-run.

Expected: `test_a_dialogue_reaches_the_composed_read_model` fails on
`assert row is not None`, and nothing anywhere raises during the append. **That is
the measurement this task exists to take.** Restore both lines.

- [ ] **Step 7: Wiring — trace it end to end**

| Link | Where | Confirm |
| --- | --- | --- |
| aggregate | `domain/socratic_dialogue.py` | four events registered |
| feed decision | `event_store.py` `UNROUTED_AGGREGATE_TYPES` | contains `SocraticDialogue` |
| repository | `build_socratic_dialogue_repository` | called in `composition.py` |
| runner constructed | `composition.py` | `SocraticDialogueRunner(...)` |
| runner **started** | `Application.start()` | started alongside `asks` |
| service constructed | `composition.py` | `SocraticDialogueService(...)` |
| **resumption wired** | `read_model=dialogues` | the runner, not `None`, not a second store |
| reachable | `Application.socratic`, `Application.dialogues` | both fields present |

Run: `uv run pytest tests/integration/ -k "dialogue or ask" -v`

Expected: PASS, and the existing ask integration tests must be untouched — this task
edits the same three regions of `composition.py` they depend on.

- [ ] **Step 8: Gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

- [ ] **Step 9: Commit**

```bash
git add research_team/composition.py \
  tests/integration/test_a_dialogue_survives_a_restart.py
git commit -m "Compose the dialogue runner and service, and prove they are composed

The ninth runner, with a worse failure mode than any of the eight before it. A
dialogue appends whether or not anything follows the log, so a build missing
this construction answers 200 with an empty history for every dialogue anyone
ever held -- and makes every resumed dialogue start over with a blank goal
while telling the reader it continued. Nothing raises: an event no projection
handles counts as APPLIED, not rejected.

Proved by removing the construction and passing read_model=None. The append
succeeds, replay is clean, the service returns, and the integration test fails
on row is None. Every weaker assertion -- a status code, a call returning --
stays green through that.

read_model=dialogues is the whole of resumption's wiring and it is one keyword
argument. That is the hop this file exists to hold.

The executor is a placeholder that raises at call time rather than at
composition, so the runner, the service and the history routes are all
reachable and testable now while the prompted agent is a separate slice.
grep _UnbuiltSocraticExecutor finds every line that changes when it lands."
```

---

### Task 5: The history routes

**Files:**
- Modify: `research_team/interfaces/web/app.py` — `create_app` gains
  `dialogues: SocraticDialogueRunner | None = None`; two routes beside the ask
  history routes (~line 3080)
- Modify: `research_team/interfaces/web/web.py` (or wherever `create_app` is called
  from — **find it with `grep -rn "create_app(" research_team/`** and pass the new
  argument at every call site the composition root owns)
- Create: `tests/integration/test_socratic_routes.py`

**Interfaces:**
- Consumes: `Application.dialogues` from Task 4.
- Produces:
  - `GET /api/projects/{project_id}/dialogues` → a list of dialogue views
  - `GET /api/projects/{project_id}/dialogues/{dialogue_id}` → one view plus `turns`
  - `_dialogue_view(row) -> dict` with keys `dialogueId`, `projectId`, `topic`,
    `goal`, `stoppingCondition`, `openingPrompt`, `pendingPrompt`, `openedAt`,
    `status`, `concludedReason`, `turnCount`, `observations`
  - each turn: `position`, `prompt`, `reply`, `citations`, `recordedAt`

Plan 3's DTOs are written against exactly these key names — camelCase on the way
out, matching `_conversation_view`.

**Two things Plan 3 must not get wrong about `prompt`, `reply` and
`pendingPrompt`.** `prompt` is the *dialogue's* question and `reply` is the
*reader's* answer, which is the inverse of the ask transcript's
question/answer — a view that reuses the ask's turn component unchanged renders
every dialogue with the speakers swapped, and it still looks like a
conversation. And `pendingPrompt` is the question the reader is being asked
right now: it belongs to no turn and must be rendered *after* the last one, or
the reader sees a transcript that ends on their own words with nothing asking
them anything.

- [ ] **Step 1: Write the failing route tests**

Create `tests/integration/test_socratic_routes.py`:

```python
"""The dialogue history routes, over a composed application.

Two claims, and they are different: that a dialogue written through the service
is readable over HTTP with its goal intact, and that these routes answer for a
project no fixture has opened. The second is CLAUDE.md's fixture trap -- a
fixture that seeds through the same call the code under test depends on cannot
see that dependency go missing.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.interfaces.web import create_app


class StubExecutor:
    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt="Where would you start?",
        )

    async def respond(self, *, project_id, history, goal, stopping_condition, reply, on_activity):
        return SocraticPrompt(prompt="What makes you say that?", citations=(("source", "s1"),))


@pytest.fixture
async def app(tmp_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "routes.db")
    )
    await application.start()
    application.socratic._executor = StubExecutor()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        ask=application.ask,
        asks=application.asks,
        dialogues=application.dialogues,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, application
    await application.close()


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


async def test_a_dialogue_is_readable_with_its_goal_and_its_turns(app):
    """The assertion is on the goal and the turn text, not on the status code.

    Red against a build with no runner: this route would answer 200 with an
    empty list for `/dialogues` and 404 here, and only an assertion on the
    *content* distinguishes that from a project nobody has talked to.
    """
    http, application = app
    project_id = await _project(http)
    dialogue_id = await application.socratic.begin(
        project_id=project_id, topic="the Nicene settlement"
    )
    async for _note in application.socratic.respond(
        project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
    ):
        pass
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{project_id}/dialogues/{dialogue_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dialogueId"] == str(dialogue_id)
    assert body["goal"] == "understand the Nicene settlement"
    assert body["stoppingCondition"] == "the reader explains it unaided"
    assert body["status"] == "started"
    # The dialogue's opening question paired with the reader's answer to it --
    # the dialogue speaking first, which is the inverse of `read_ask`'s turns.
    assert body["turns"] == [
        {
            "position": 0,
            "prompt": "Where would you start?",
            "reply": "It settled Arianism.",
            "citations": [{"kind": "source", "id": "s1"}],
            "recordedAt": body["turns"][0]["recordedAt"],
        }
    ]
    # And the question now outstanding, which is in no turn above. Red against
    # a view that omits it: the page would render a transcript ending on the
    # reader's own words with nothing asking them anything.
    assert body["pendingPrompt"] == "What makes you say that?"


async def test_the_list_shows_this_project_s_dialogues_and_what_they_are_for(app):
    """A reader picking a dialogue back up needs to know which one it was, and
    the topic alone does not say what it was aiming at. Red against a list view
    that carries only ids and timestamps."""
    http, application = app
    project_id = await _project(http)
    await application.socratic.begin(project_id=project_id, topic="the Nicene settlement")
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{project_id}/dialogues")

    assert response.status_code == 200, response.text
    listed = response.json()
    assert [row["topic"] for row in listed] == ["the Nicene settlement"]
    assert listed[0]["goal"] == "understand the Nicene settlement"
    assert listed[0]["turnCount"] == 0


async def test_a_dialogue_from_another_project_is_a_404_not_a_read(app):
    """404 covers both "no such dialogue" and "that dialogue belongs to another
    project", deliberately the same answer as the ask routes give: the second
    is a guessed id, and telling a caller that an id they cannot read does
    exist is the distinction not worth drawing."""
    http, application = app
    mine = await _project(http)
    theirs = await _project(http)
    dialogue_id = await application.socratic.begin(project_id=mine, topic="t")
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{theirs}/dialogues/{dialogue_id}")

    assert response.status_code == 404, response.text


async def test_the_list_answers_for_a_project_nothing_has_opened(app):
    """CLAUDE.md's fixture trap. Every other test here creates a dialogue
    first, which opens whatever the dialogue path opens -- so a route that
    reached for a reader without opening the project would be invisible from
    all of them and answer 503 exactly once per project.

    An empty list is the right answer and the assertion is that it is 200 with
    an empty body, not merely `!= 503`: this route has one honest answer for a
    project nobody has talked to.
    """
    http, _application = app
    project_id = await _project(http)

    response = await http.get(f"/api/projects/{project_id}/dialogues")

    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_an_unconfigured_build_says_so_rather_than_answering_empty(tmp_path):
    """503 when the projection is unwired, not an empty 200 -- the same ruling
    `list_asks` makes, and it matters for the same reason: an empty list is the
    right answer for a project nobody has talked to, and a dialogue appends
    whether or not anything follows the log, so the two are indistinguishable
    unless the route says so.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "bare.db")
    )
    await application.start()
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            response = await http.get(f"/api/projects/{project_id}/dialogues")
            assert response.status_code == 503, response.text
    finally:
        await application.close()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/integration/test_socratic_routes.py -x`

Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'dialogues'`.

- [ ] **Step 3: Add the parameter and the routes**

Add `dialogues: SocraticDialogueRunner | None = None` to `create_app`'s signature,
beside `asks`. Then, after the ask history routes:

```python
    def _dialogue_view(row) -> dict[str, Any]:
        """One dialogue, without its turns -- what a history list needs.

        Carries `goal` and `stoppingCondition` in the *list* view and not only
        in the detail one, deliberately. A reader picking a dialogue back up
        needs to know what it was aiming at, and the topic alone does not say:
        two dialogues about the Nicene settlement can be trying to do entirely
        different things. It is two strings per row on a page that is a cheap
        index, which is the same trade `firstQuestion` makes on the ask list.
        """
        return {
            "dialogueId": str(row.id),
            "projectId": str(row.project_id),
            "topic": row.topic,
            "goal": row.goal,
            "stoppingCondition": row.stopping_condition,
            "openingPrompt": row.opening_prompt,
            # The question the reader is looking at now, which belongs to no
            # turn -- see `SocraticTurnRecorded`. A view that omitted it would
            # render a transcript ending on the reader's own words with
            # nothing asking them anything.
            "pendingPrompt": row.pending_prompt,
            "openedAt": row.opened_at.isoformat(),
            "status": row.status,
            "concludedReason": row.concluded_reason,
            "turnCount": row.turn_count,
            "observations": row.observations,
        }

    @app.get("/api/projects/{project_id}/dialogues")
    async def list_dialogues(project_id: UUID):
        """Every dialogue held with this project, most recent first.

        **503 when the projection is unwired, not an empty 200** -- the same
        ruling `list_asks` makes and for the same reason: a dialogue appends
        whether or not anything follows the log, so a build with no runner
        started is indistinguishable from a project nobody has talked to unless
        the route says so.
        """
        if dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        return [_dialogue_view(row) for row in await dialogues.for_project(project_id)]

    @app.get("/api/projects/{project_id}/dialogues/{dialogue_id}")
    async def read_dialogue(project_id: UUID, dialogue_id: UUID):
        """One dialogue, with its exchanges in the order they happened.

        404 covers both "no such dialogue" and "that dialogue belongs to
        another project", and they are deliberately the same answer, matching
        `read_ask`: the second is a guessed id, and telling a caller that an id
        they cannot read does exist is the distinction not worth drawing.

        `prompt` is the dialogue's question and `reply` is the reader's answer
        -- the inverse of `read_ask`'s question/answer, because this surface
        runs in the opposite direction. A client that reused the ask's turn
        renderer here would draw every dialogue with the speakers swapped, and
        it would still read as a conversation.
        """
        if dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        return {
            **_dialogue_view(row),
            "turns": [
                {
                    "position": turn.position,
                    "prompt": turn.prompt,
                    "reply": turn.reply,
                    "citations": turn.citations,
                    "recordedAt": turn.recorded_at.isoformat(),
                }
                for turn in await dialogues.turns_for(dialogue_id)
            ],
        }
```

- [ ] **Step 4: Pass it from the composition root**

Run: `grep -rn "create_app(" research_team/`

Add `dialogues=application.dialogues` at every call site the composition root owns
(not the test call sites, which pass what each test needs). **This is the hop that
makes the routes reachable in a real build**, and a route added to `app.py` but never
handed its dependency answers 503 forever while every route test passes.

- [ ] **Step 5: Run the route tests to verify they pass**

Run: `uv run pytest tests/integration/test_socratic_routes.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 6: Wiring**

Run: `grep -rn "dialogues=" research_team/`

Expected: the `create_app` call site(s) in the composition root, and nothing else
missing. Then run the whole integration suite for this feature and its neighbour:

Run: `uv run pytest tests/integration/ -v`

Expected: PASS. The ask routes share `create_app`'s signature and this task changed it.

- [ ] **Step 7: All four gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd frontend && npm run verify`

The frontend gate is here because this is the plan's last task and CI runs all four
regardless of what changed. **No `frontend/src` file is edited in this plan**, so
`research_team/interfaces/web/static` must show no drift:

Run: `git status --porcelain research_team/interfaces/web/static`

Expected: empty. If it is not, something rebuilt the assets and the diff belongs in
the commit — or, more likely, `npm run verify` was run from a dirty tree and the
change is not yours.

- [ ] **Step 8: Commit**

```bash
git add research_team/interfaces/web/app.py research_team/interfaces/web/web.py \
  tests/integration/test_socratic_routes.py
git commit -m "Read dialogues back over HTTP, goal included

Two routes matching the ask history pair, with one deliberate difference: goal
and stoppingCondition are in the LIST view and not only the detail one. A
reader picking a dialogue back up needs to know what it was aiming at, and the
topic does not say -- two dialogues about the same subject can be trying to do
entirely different things. Two strings per row on a page whose job is to be a
cheap index, which is the trade firstQuestion already makes on the ask list.

503 when the projection is unwired, never an empty 200. Same ruling as
list_asks and the same reason: a dialogue appends whether or not anything
follows the log, so a build with no runner is indistinguishable from a project
nobody has talked to unless the route says so.

One test starts from a project no fixture has opened, which every other test in
the file cannot do -- they all create a dialogue first, and a route that
reached for a reader without opening the project would answer 503 exactly once
per project and be invisible from all of them.

The composition root now passes dialogues= to create_app. A route added to
app.py and never handed its dependency answers 503 forever while every route
test passes, because route tests construct their own app."
```

---

## Self-review

**Spec coverage — Plan 1's share.**

| Spec | Where |
| --- | --- |
| §1 a `SocraticDialogue` aggregate alongside `AskConversation`; state is what is new | Task 1 |
| §2 resumption from the read model, not the registry; the registry stays a cache | Task 3 (the test that matters), Task 4 (composed) |
| §5 events, state, two-table read model with `position` **stored**; a turn records only on success; goal and stopping condition set once at the start | Tasks 1, 2, 3 |
| §5 goal and stopping condition **visible to the reader** | Task 3 (`SocraticDialogueOpened` carries them), Task 5 (both route views) — *rendering* is Plan 3 |
| §7 in-scope: aggregate, projection, resumption | this plan |
| §7 out-of-scope: multi-reader, cross-project resumption | Task 3's `_resume` refuses a project mismatch; nothing invents a principal below the dialogue |
| §9 schema evolution | Task 1 Step 7 |
| §9 the projection must be constructed; row-exists assertions | Task 2 Step 6, Task 4 Step 6 — both **prove it red** |
| §9 resumption written first | Stated verbatim before Task 1; created in Task 1 Step 1; green in Task 3 |
| §9 read models against a database that predates the change | Task 2 Step 7, with its limit stated |
| §4, §6, §8, §3, and §7's executor/route/frontend/grading | **Plans 2 and 3** — see "Why this is three plans" |

**What I could not plan cleanly, and what I did instead:**

1. **The spec does not say which speaker owns `prompt` and which owns `reply`.**
   Ruled: `prompt` is the **system's** question, `reply` is the **reader's** answer —
   the ordinary sense of both words, and deliberately the inverse of
   `AskTurnRecorded`, because the questioning direction is what makes this surface
   different from an ask. Pinned twice — in the aggregate test and again at the
   storage layer — because a swap produces a transcript that still reads as a
   conversation, just one where the reader asks all the questions.

   An earlier draft of this plan ruled the opposite on the grounds that `citations`
   belong beside the agent's utterance. **That argument does not decide anything**:
   both fields are on the same event, so either naming is equally consistent with
   where citations live. It only proves the citations belong on
   `SocraticTurnRecorded`, which was never in question.

   **A turn pairs the reader's answer with the response it drew** —
   `Started(opening_prompt=Q1)`, `Turn(A1, Q2)`, `Turn(A2, Q3)` — which is one
   executor call per event and stores every utterance exactly once. The opening
   question is therefore an orphan and lives on the start event, and the
   currently-outstanding question is derived (the last turn's `prompt`, or
   `opening_prompt`), precomputed into `SocraticDialogueRow.pending_prompt` because
   that is what a read model is for.

   **An intermediate draft got this wrong and the correction is worth recording.**
   It read the naming ruling as also fixing the *pairing*, defined a turn as
   `(question, the answer to it)`, and added `next_prompt` to carry the question that
   followed — which put every system utterance in the log twice, as this turn's
   `next_prompt` and the next turn's `prompt`. Two copies that can drift is a bug
   that surfaces only on a rebuild. The naming ruling says who owns each *field*; it
   says nothing about which utterances a turn pairs, and conflating the two cost a
   redundant field and a redundant state entry.

   The executor's output type is `SocraticPrompt` because of the naming ruling: an
   earlier draft called it `SocraticReply` with a `text` field, which put a question
   in a field named for the reader's answer.
2. **§5 asks for `observations` in state *and* for the two-table pattern.** Both hold
   only if observations ride the dialogue row as JSON. Stated as a ruling with its
   cost (nothing can query by observation).
3. **The service needs an executor and this plan has no real one.** Rather than defer
   composition to Plan 2 — which would leave the runner, the resumption path and the
   routes unreachable and therefore untestable in a real build — Task 4 composes
   everything with `_UnbuiltSocraticExecutor`, which raises at call time and not at
   construction. `grep _UnbuiltSocraticExecutor` is the handover.
4. **`local_copy` cannot fully exercise what CLAUDE.md's rule is about here**, because
   these are new tables and `apply_schema`'s widening path never runs. Task 2 Step 7
   says so in the step rather than claiming the check is stronger than it is; what it
   does prove is that `open()` succeeds against a database that already holds
   `projection_checkpoints`, which a `tmp_path` database cannot show.
**Three names corrected during self-review, all checked against the source rather
than reasoned** — they were wrong in the first draft and would each have cost an
executor a cycle:

- The raw-insert helper is `_write_old_event(db_path, session_id, version,
  event_type, payload, aggregate_type=...)` — positional, not the keyword-only
  `_write_raw_event` the draft invented.
- Reading every event of one aggregate type is `event_store.read_category(type)`,
  not `read_all()`; `test_ask_persistence.py`'s `all_events` is the precedent.
- `SocraticDialogueState` carries no `opening_prompt`, so the schema-evolution
  assertion had to move to `goal` and `stopping_condition`. The draft asserted on a
  field the state does not have, behind a walrus placeholder.

**Placeholder scan.** No "TBD", no "add error handling", no "write tests for the
above", no "similar to Task N". Two places deliberately say "read the real file":
the set of lines `asks` appears on in `composition.py` (Task 4 Step 4) and the
`create_app` call sites (Task 5 Step 4). Both are `grep`-shaped checks, not gaps.

**Type consistency.** `SocraticDialogue`, `SocraticDialogueStarted`,
`SocraticTurnRecorded`, `SocraticProgressObserved`, `SocraticDialogueConcluded`,
`StartSocraticDialogue`, `RecordSocraticTurn`, `ObserveSocraticProgress`,
`ConcludeSocraticDialogue`, `SocraticDialogueState` are spelled identically in Tasks
1–4. `DialogueRegistry`, `LiveDialogue`, `DialogueMessage`, `SocraticFraming`,
`SocraticPrompt`, `SocraticObservation`, `SocraticDialogueOpened`, `UnknownDialogue`,
`DialogueInFlight`, `SocraticDialogueService` are identical across the resumption
test, Task 3 and Tasks 4–5. `SocraticDialogueRunner.get` / `.for_project` /
`.turns_for` are the same three names in Task 2's store, Task 3's `DialogueReadModel`
Protocol, Task 4's composition and Task 5's routes. The row field names
(`goal`, `stopping_condition`, `opening_prompt`, `pending_prompt`, `status`,
`concluded_reason`, `turn_count`, `observations`, `prompt`, `reply`, `position`,
`recorded_at`) match between Task 2's models, Task 3's `_resume`, and Task 5's view
functions — and the camelCase route keys are listed once, in Task 5's Interfaces
block, which is what Plan 3's DTOs will be written against.

**Every utterance is stored exactly once, traced end to end.** The conversation
`Q1 A1 Q2 A2 Q3` lands as `SocraticDialogueStarted.opening_prompt` = Q1, then
`SocraticTurnRecorded(reply=A1, prompt=Q2)` and `(reply=A2, prompt=Q3)`. Nothing
appears twice, so nothing can drift on a rebuild. The derived views:

- `SocraticDialogueRow.opening_prompt` ← the start event (Task 2)
- `SocraticDialogueRow.pending_prompt` ← the newest turn's `prompt`, overwritten per
  turn, seeded from `opening_prompt` on start (Task 2)
- `_resume`'s history ← `opening_prompt`, then `(user reply, assistant prompt)` per
  turn, alternating and ending on the dialogue's newest utterance (Task 3)
- `SocraticDialogueOpened.pending_prompt` → `pendingPrompt` in both route views
  (Tasks 3 and 5)

Each hop has a test: the row and its `pending_prompt` in Task 2's ordering test, the
rehydrated history in the resumption test, the composed pairing in Task 4, and the
route body in Task 5. `SocraticDialogueState` deliberately carries **neither** the
outstanding question nor the turn texts — only a count — because no decision in
`decide` needs them, and state that nothing reads is state that can disagree with
the log.
