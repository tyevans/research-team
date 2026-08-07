"""What a learner has done with the components in a course, kept rather than lost.

`POST /attempts` marked an answer and returned a verdict, and nothing recorded
that it happened. A reload lost every answer, a checklist's `persist: true` was
accepted and ignored, and the pedagogically interesting object -- the *sequence*
of attempts on one item -- existed nowhere. This aggregate is that record.

**The stream is the session's.** There is no user system (B18), so there is no
principal to key progress by; a session is the only identity in the system that
means "one person working through this material". It shares its UUID with its
session, the way a corpus shares its project's, and is a distinct stream by
`StreamId(aggregate_id, "LearnerProgress")`. When authentication arrives this
becomes the thing that has to change, which is why it is stated here rather
than left implicit in a call site.

**Identity is `(path, component_id)`, and revisions are recorded, not resolved.**
That pair survives an edit to a question that keeps its id, which is the common
case and the one worth surviving. Nothing survives an author rewriting the item
under the same id -- so rather than pretend otherwise, every attempt carries the
`digest` of the component body it was answered against. A reader can then tell
that an item changed under a learner, which is the input the "should this reset
their progress" decision needs and which nothing could reconstruct afterwards.
Deciding it here would be guessing: whether a reworded distractor invalidates an
attempt is a pedagogical call, not a domain rule.

**No creation event.** Progress has no attributes of its own, so
`LearnerProgressCreated` would be an empty payload whose only effect is to make
the first attempt fail if a caller forgot it. The first `ItemAnswered` (or
`ChecklistProgressRecorded`) creates it. The house `status: "new" | "created"`
vocabulary is kept because it is what a reader of `project.py` and `corpus.py`
expects.

**The state holds no response text.** `ItemRecord` carries counts, scores and
flags; what the learner actually typed lives only in the `ItemAnswered` payload.
Snapshots fold the state, and a growing list of every answer ever given would go
into each one. The sequence of attempts is a projection over the stream, which
is the same trade `corpus.py` makes for document text and for the same reason.

**The event names are xAPI verbs**, so an LRS bridge is a projection rather than
a redesign: `answered` and `completed`. `attempted` is deliberately *not* here.
No surface produces it -- nothing tells the server that a learner started an
item and did not submit -- so emitting one would be inventing a fact to fill a
vocabulary.
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field


@register_event
class ItemAnswered(DomainEvent):
    """A learner submitted an answer to a graded item, and how it was marked.

    Also this aggregate's creation event.

    The verdict is stored, not just the response. Re-deriving it later would
    need the file as it stood, the grader as it stood, and the answer key as it
    stood -- so a stored verdict is the only thing that keeps "what was this
    learner told" answerable after any of the three has changed.

    `at` is the event index the file was graded against, or None for HEAD. It is
    what makes a verdict checkable: without it, an item revised after the fact
    leaves no way to find the version the learner actually read.
    """

    aggregate_type: str = "LearnerProgress"
    path: str
    component_id: str
    component_type: str
    digest: str
    """sha256 of the component body this was answered against."""
    response: Any = None
    correct: bool = False
    score: float = 0.0
    at: int | None = None


@register_event
class ItemCompleted(DomainEvent):
    """The first time an item was answered correctly.

    Derived from `ItemAnswered` rather than reported by the caller, and emitted
    only once: "when did this land" is a different question from "how many times
    was it tried", and a completion re-emitted on every later correct answer
    would answer the first question with the last date.
    """

    aggregate_type: str = "LearnerProgress"
    path: str
    component_id: str
    attempts: int
    """How many answers it took, this one included."""


@register_event
class ChecklistProgressRecorded(DomainEvent):
    """Which boxes are ticked on a checklist that asked to be remembered.

    Not an attempt: a checklist has no answer key, so there is no verdict and
    nothing to be right about. It is state a learner accumulates, and the whole
    of `persist: true` is that it survives a reload.

    Absolute rather than a delta -- the full set of checked indices, every time.
    A toggle event would be smaller and would make the fold's correctness depend
    on never dropping one; this way any single event reconstructs the box.
    """

    aggregate_type: str = "LearnerProgress"
    path: str
    component_id: str
    checked: list[int] = Field(default_factory=list)


@dataclass(frozen=True)
class RecordAttempt:
    """Mark one attempt as having happened. The verdict is already decided."""

    #: Which learner's progress. This is the creation command, so on a fresh
    #: stream there is no state to read it back off -- every later command
    #: takes its id from the fold of this one's event.
    progress_id: UUID
    path: str
    component_id: str
    component_type: str
    digest: str
    response: Any = None
    correct: bool = False
    score: float = 0.0
    at: int | None = None


@dataclass(frozen=True)
class RecordChecklistState:
    """Remember which boxes are ticked. Also a creation command."""

    progress_id: UUID
    path: str
    component_id: str
    checked: list[int] = field(default_factory=list)


LearnerProgressCommand = RecordAttempt | RecordChecklistState


class ItemRecord(BaseModel):
    """What the fold keeps about one item. Deliberately not its responses."""

    path: str
    component_id: str
    component_type: str = ""
    attempts: int = 0
    correct: bool = False
    """Whether it has *ever* been answered correctly."""
    best_score: float = 0.0
    last_score: float = 0.0
    last_digest: str = ""
    """The body the most recent attempt was made against.

    Kept so a reader can see that the item changed under the learner without
    replaying the stream. This aggregate does not act on it -- see the module
    docstring on why resolving a rewrite is not a domain rule.
    """
    checked: list[int] = Field(default_factory=list)
    """Ticked boxes, for a checklist with `persist: true`. Empty otherwise."""


def key(path: str, component_id: str) -> str:
    """How an item is addressed in `items`.

    A single string because pydantic serialises mapping keys, and a tuple key
    would come back from a snapshot as something that is no longer a tuple.
    `\\n` separates because it cannot occur in either half: a path with a
    newline in it is not a path, and an id with one would not have survived the
    parser.
    """
    return f"{path}\n{component_id}"


class LearnerProgressState(BaseModel):
    """Everything derivable from one learner's progress stream."""

    progress_id: UUID | None = None
    """None before anything has been recorded. Set by the fold of the first event."""

    status: Literal["new", "created"] = "new"
    items: dict[str, ItemRecord] = Field(default_factory=dict)

    def item(self, path: str, component_id: str) -> ItemRecord | None:
        return self.items.get(key(path, component_id))


def initial_state() -> LearnerProgressState:
    return LearnerProgressState()


def decide(command: LearnerProgressCommand, state: LearnerProgressState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `corpus.decide` and `project.decide`
    do. Both commands are legal against an empty stream, because either one can
    be the first thing a learner does.
    """
    progress_id = state.progress_id
    match command:
        case RecordAttempt():
            if not command.path or not command.component_id:
                raise CommandRejectedError("an attempt needs a path and a component id")
            answered = ItemAnswered(
                # From the command, not the state: this may be the creation
                # command, in which case `state.progress_id` is still None.
                aggregate_id=command.progress_id,
                path=command.path,
                component_id=command.component_id,
                component_type=command.component_type,
                digest=command.digest,
                response=command.response,
                correct=command.correct,
                score=command.score,
                at=command.at,
            )
            record = state.item(command.path, command.component_id)
            if not command.correct or (record is not None and record.correct):
                return [answered]
            # First correct answer. Emitted after the attempt it is derived
            # from, so a fold that stops between the two sees an ordinary
            # correct attempt rather than a completion of nothing.
            return [
                answered,
                ItemCompleted(
                    aggregate_id=command.progress_id,
                    path=command.path,
                    component_id=command.component_id,
                    attempts=(record.attempts if record else 0) + 1,
                ),
            ]

        case RecordChecklistState():
            if not command.path or not command.component_id:
                raise CommandRejectedError("checklist state needs a path and a component id")
            if any(index < 0 for index in command.checked):
                raise CommandRejectedError("a checked box cannot have a negative index")
            return [
                ChecklistProgressRecorded(
                    aggregate_id=command.progress_id or progress_id,
                    path=command.path,
                    component_id=command.component_id,
                    # Sorted and de-duplicated here so the stored fact is
                    # canonical: two clients reporting the same boxes in a
                    # different order must not read as two different states.
                    checked=sorted(set(command.checked)),
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: LearnerProgressState, event: DomainEvent) -> LearnerProgressState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case ItemAnswered():
            slot = key(event.path, event.component_id)
            record = state.items.get(slot) or ItemRecord(
                path=event.path,
                component_id=event.component_id,
                component_type=event.component_type,
            )
            updated = record.model_copy(
                update={
                    "component_type": event.component_type or record.component_type,
                    "attempts": record.attempts + 1,
                    # Sticky: having once been right is not undone by later
                    # being wrong. The count is what says it took three goes.
                    "correct": record.correct or event.correct,
                    "best_score": max(record.best_score, event.score),
                    "last_score": event.score,
                    "last_digest": event.digest,
                }
            )
            return state.model_copy(
                update={
                    "progress_id": state.progress_id or event.aggregate_id,
                    "status": "created",
                    "items": {**state.items, slot: updated},
                }
            )

        case ChecklistProgressRecorded():
            slot = key(event.path, event.component_id)
            record = state.items.get(slot) or ItemRecord(
                path=event.path,
                component_id=event.component_id,
                component_type="checklist",
            )
            return state.model_copy(
                update={
                    "progress_id": state.progress_id or event.aggregate_id,
                    "status": "created",
                    "items": {
                        **state.items,
                        slot: record.model_copy(update={"checked": list(event.checked)}),
                    },
                }
            )

        case ItemCompleted():
            # Nothing to fold. `correct` is already set by the `ItemAnswered`
            # this was derived from, and duplicating it here would give the
            # state two sources for one fact. The event earns its place in the
            # *log* -- it is when the item landed and how many tries it took --
            # not in the fold.
            return state

        case _:
            return state


class LearnerProgress(DeciderAggregate[LearnerProgressState, LearnerProgressCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Corpus`'s shape exactly: the class attributes bind directly to the
    module-level functions rather than wrapping them in new method bodies, so
    there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "LearnerProgress"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
