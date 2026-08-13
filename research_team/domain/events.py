"""Domain events for a coding session.

One stream carries both the conversation and the virtual filesystem, so
ordering between "the model said X" and "file Y changed" is total.

Changing an event's shape
-------------------------
Events already written are not rewritten, so every change here has to be
readable against payloads stored by an older build. Two cases, in order of
preference:

1. **Adding a field.** Give it a default that means what its absence meant.
   `TurnFailed.cancelled` and `ConversationCompacted.tokens_*` were both done
   this way -- an old payload has no key, the default fills in, and the value
   reads as "unrecorded" rather than as a real measurement.

2. **Renaming or restructuring one.** No default can express this, so add a
   pydantic `model_validator(mode="before")` to the event class and translate
   the old shape there. It runs on the stored dict before validation, which is
   the only point where both shapes are visible at once, and it needs nothing
   from the library -- events are rebuilt through their own model on the way
   out of the registry. Bump `event_version` at the same time so a reader can
   tell which shape a payload was written in.

Either way, add a case to `tests/infrastructure/test_schema_evolution.py`,
which writes old-shaped payloads straight into the events table and reads them
back. That file is the only thing standing between this strategy and the
discovery, much later, that some old session no longer loads.
"""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent, register_event


@register_event
class SessionStarted(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "CodingSession"
    system_prompt: str
    model_name: str
    project_id: UUID
    """The project whose filesystem and knowledge graph this session shares.

    Required, and deliberately not defaulted. It was `UUID | None` under case 1
    of the strategy above, which was right while sessions could exist outside a
    project; they cannot now, so a `None` here is not "written before projects
    existed" but a session with no filesystem, no knowledge graph and no course
    -- a state the rest of the system has no handling for.

    This is a **breaking change to stored payloads**: a session written without
    a project no longer loads, and there is no validator to translate one,
    because there is nothing to translate it *to*. Chosen over a shim while the
    project is pre-release and holds no real data. The cost is stated rather
    than hidden -- a build that has to read such a log again needs this field
    optional and every caller of `project_id` ready for None, which is the
    design that was just removed.
    """


@register_event
class UserMessageSent(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class AssistantMessageAdded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class ToolResultRecorded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]
    is_error: bool = False


@register_event
class TurnCompleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    turn_index: int


@register_event
class TurnFailed(DomainEvent):
    """A turn was attempted and did not complete.

    Appended on its own, after the failed turn's events have been discarded --
    so the log gains the attempt without gaining a half-applied turn. The
    turn_index is the one that was being attempted, and is not advanced.

    `cancelled` separates "someone stopped this" from "this broke". Both leave
    the same hole in the log, but they are different facts about what happened,
    and an audit trail that cannot tell them apart is a worse audit trail.
    Defaults to False, so events written before the distinction existed read
    as ordinary failures -- which is what they were.
    """

    aggregate_type: str = "CodingSession"
    turn_index: int
    error_type: str
    error_message: str
    cancelled: bool = False


@register_event
class ConversationCompacted(DomainEvent):
    """Older messages were replaced, for the model's benefit, by a summary.

    The messages themselves are not removed -- nothing is ever removed. This
    records a decision about what the *model* is shown from here on, so the
    fold can apply it while the log still holds every original message. Replay
    stays exact, and folding to a point before this event shows the
    conversation as it was.

    `through_index` is the 1-based index, within the session's message list, of
    the last message the summary stands in for.
    """

    aggregate_type: str = "CodingSession"
    summary: str
    through_index: int
    strategy: str
    """Which strategy produced this, so a log reader knows what made the call."""
    tokens_before: int = 0
    """Roughly what the conversation cost when this fired. 0 if unrecorded.

    Without it the log says compaction happened but not why *then*, which is
    the first question anyone asks of it -- and the answer is not recoverable
    afterwards, because the threshold it crossed is configuration that may
    since have changed.
    """
    tokens_after: int = 0
    """Roughly what it cost afterwards. 0 if unrecorded."""


@register_event
class SessionForkedFrom(DomainEvent):
    """Records that this stream was branched off another one.

    Emitted after the copied prefix rather than before it: `SessionStarted` is
    the creation event and must come first, and its reducer replaces state
    wholesale, so lineage recorded ahead of it would be overwritten.
    """

    aggregate_type: str = "CodingSession"
    source_session_id: UUID
    at_event: int


@register_event
class FileWritten(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]


@register_event
class FileEdited(DomainEvent):
    """Carries both the resulting file_data and the edit intent.

    file_data keeps the fold O(1); old_string/new_string keep the audit
    trail meaningful.
    """

    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]
    old_string: str
    new_string: str
    replace_all: bool = False


@register_event
class FileDeleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str


@register_event
class ToolCallDecided(DomainEvent):
    """A gated tool call was allowed, refused, or amended -- and by whom.

    Recorded because a supervision decision is a fact about how the session was
    conducted, and one that is not recoverable afterwards: the policy that
    produced it is configuration, and configuration changes. `decided_by`
    separates a human's judgement from the policy's own refusal; both stop a
    call, and an audit trail that cannot tell them apart is a worse one.
    """

    aggregate_type: str = "CodingSession"
    tool_name: str
    args: dict[str, Any]
    decision: str
    """langchain's vocabulary: approve | edit | reject | respond."""
    decided_by: str
    """`human` or `policy`."""
    edited_args: dict[str, Any] | None = None
    """The amended arguments when `decision` is `edit`. None otherwise."""
    review_id: UUID | None = None
    """The stage review this decision answered, when it answered one.

    None for every gated call that is not an `advance_stage`, and for every
    `advance_stage` decided before this field existed -- which is what its
    absence always meant. `ToolCallDecided` names no stage otherwise, and
    `ProjectStageAdvanced`, which does, is on the `Project` stream and is not written
    at all when a gate is rejected. So this is the only join.
    """


@register_event
class StageChecksEvaluated(DomainEvent):
    """What the check library found at a gate, and what it was asked to check.

    Recorded because the findings themselves are a *file* -- one per stage
    number, overwritten by the next review of that stage -- so the only durable
    record of what the checks found describes the most recent run and nothing
    before it. A question like "does this check ever pass?" has no evidence to
    answer it from.

    **`evaluated` holds every bound check, not every finding**, and that is the
    field this event exists for. A fire rate needs a denominator, and the
    denominator is the runs where a check ran and found nothing. An event
    modelled on the findings file -- which lists only findings -- can count
    numerators forever and never produce a rate.

    No message and no `cites`: the counts are the fact, the prose is already in
    `/course/NN-check-findings.md`, and putting it here too would make every
    review permanent at the size of its worst output and fold it into every
    snapshot. `corpus.py` holds no document text for the same reason.

    `posed_by` distinguishes the two gate paths because it decides whether a
    duration means anything. On the runner path this event and the
    `ToolCallDecided` that answers it are appended separately, so their
    `occurred_at` values bracket a human's deliberation. On the tool path both
    land at `_save_turn`, milliseconds apart, and the difference measures
    serialization -- so a consumer must report no duration rather than a fast
    one. See BACKLOG.md B36 for why the tool path is like that.
    """

    aggregate_type: str = "CodingSession"
    review_id: UUID
    """Joins this review to the decision that answered it.

    A field of our own rather than the inherited `correlation_id`: that one
    belongs to whatever is tracing, and a join that borrowed it would break
    silently the first time a tracer is wired.
    """
    project_id: UUID
    stage: str
    preset: str
    preset_version: str
    evaluated: list[dict[str, Any]]
    """One entry per bound check that ran: `check`, `severity`, `findings`.

    `findings: 0` means it ran and passed. `severity` is the one `run_check`
    resolved -- a spec's `fixed_severity` where it has one, the binding's
    otherwise -- because that is the severity the finding would have carried.
    """
    unimplemented: list[dict[str, Any]]
    """One entry per binding naming no registered check: `check`, `severity`.

    Separate from `evaluated` because such a check neither ran nor passed, and
    folding it into either would make one of the two rates lie. The severity is
    the binding's own; there is no spec to resolve a fixed one from, which is
    what being unimplemented means.
    """
    posed_by: str
    """`runner` or `tool`."""


@register_event
class AutonomyChanged(DomainEvent):
    """How much the agent may do without asking was changed mid-session."""

    aggregate_type: str = "CodingSession"
    tool_name: str
    level: str
    """auto | ask | deny."""


SESSION_EVENTS: tuple[type[DomainEvent], ...] = (
    SessionStarted,
    ConversationCompacted,
    UserMessageSent,
    AssistantMessageAdded,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    SessionForkedFrom,
    FileWritten,
    FileEdited,
    FileDeleted,
    ToolCallDecided,
    StageChecksEvaluated,
    AutonomyChanged,
)
