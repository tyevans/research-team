"""What can be asked of a session.

Commands are values, not method calls: `decide` matches on the pair
*(command, state)*, so a request has to be something you can hold, pass to a
pure function, and assert about without an aggregate in scope.

They are never stored. A command that `decide` refuses leaves no trace -- the
log records what happened, and a rejected request did not happen. That is the
difference between these and the events in `events.py`, which are frozen facts
about the past and are written down forever.
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MAX_ERROR_MESSAGE = 500
"""How much of a failure's message the log keeps. Enough to recognise it."""


class SessionPurpose(StrEnum):
    """What kind of work a session exists to do.

    The one thing that decides whether a workflow attaches to its turns. A
    `StrEnum` rather than a `Literal` because it is named at six production
    call sites and read in `composition.py`; a bare string would let a typo
    reach the fold and read as an unknown purpose, which -- see
    `WORKFLOW_DRIVEN` in `composition.py` -- fails safe into "no workflow" and
    would therefore be silent.

    Deliberately not a boolean. `drives_workflow: bool` was the cheaper shape
    and was rejected: three of these five are unattended in different ways
    (a round works a topic queue, a seeding turn opens topics, a dispatch turn
    writes one topic up), and collapsing them loses the ability to answer
    "which sessions were research rounds" -- the first question anyone
    debugging this feature asks.

    Defined here rather than in `session.py`, where the brief for this change
    first placed it: `session.py` imports the command classes from this module
    to match on in `decide`, so a `session.py -> commands.py` import already
    exists, and `commands.py` needing the enum from `session.py` in turn is a
    real cycle, not a style choice -- `import research_team.domain.commands`
    raised `ImportError: cannot import name 'ChangeAutonomy' from partially
    initialized module` the moment both sides tried it. This module has no
    dependency on `session.py`, so it is the one that can hold a type both
    sides need. `session.py` re-exports it so `from research_team.domain.session
    import SessionPurpose` still works exactly as specified.
    """

    CHAT = "chat"
    """A person, at a keyboard, in the web console or the REPL."""

    WORKFLOW_STAGE = "workflow_stage"
    """`StageRunner`, driving one stage of the selected preset."""

    RESEARCH_ROUND = "research_round"
    """One round of `ResearchRunDriver`, working the topic queue."""

    TOPIC_SEEDING = "topic_seeding"
    """`TopicSeeder`, opening a project's initial topics in one turn."""

    TOPIC_DISPATCH = "topic_dispatch"
    """`TopicDispatcher`, writing up what is known about one topic."""

    COURSE_AUTHORING = "course_authoring"
    """`CourseAuthor`, writing one learning area's unit and lessons.

    A purpose of its own rather than `WORKFLOW_STAGE`, which it superficially
    resembles: a stage run is driven by the selected preset and its position
    in it decides what it writes, whereas this is driven by a projection over
    the graph and writes to a path derived from an area slug. Folding them
    together would make "which sessions were workflow stages" -- the question
    the docstring above says is the first one anyone asks -- unanswerable.
    """


class Command(BaseModel):
    """Base for every session command: frozen, and closed to stray fields.

    Frozen because a command is a request someone made, and rewriting it after
    the fact would make `decide`'s inputs untrustworthy in exactly the way the
    event log refuses to be.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class StartSession(Command):
    #: Which session to start. The one command whose target cannot be read back
    #: off the state, there being no state yet; every later command takes its id
    #: from the fold of `SessionStarted`.
    session_id: UUID
    system_prompt: str
    model_name: str
    project_id: UUID
    #: Which project the session belongs to. Required, so that "a session
    #: outside a project" cannot be expressed as a request in the first place
    #: -- `decide` never has to reject it, and no caller has to remember to
    #: pass it. `SessionService.start_in_project` is the only thing that
    #: issues this command.
    purpose: SessionPurpose
    #: What kind of work this session is for. Required and undefaulted, for the
    #: same reason `project_id` above is: a session whose purpose nobody stated
    #: cannot be expressed as a request in the first place, so `decide` never
    #: has to reject one and no caller can forget. Defaulting it to `CHAT` was
    #: considered and rejected -- it makes the safe value the silent one, so a
    #: caller who forgot would attach a workflow to an unattended run, which is
    #: precisely the defect this field exists to remove.


class SendUserMessage(Command):
    message: dict[str, Any]


class RecordAssistantMessage(Command):
    message: dict[str, Any]


class RecordToolResult(Command):
    message: dict[str, Any]
    is_error: bool = False


class CompleteTurn(Command):
    pass


class FailTurn(Command):
    """A turn was attempted and did not complete.

    Carries plain values rather than the exception itself, so `decide` stays a
    function over data. `from_error` is where an exception becomes those
    values -- the truncation and the cancelled/failed distinction live there,
    at the edge, rather than inside the rule.
    """

    error_type: str
    error_message: str
    cancelled: bool = False

    @classmethod
    def from_error(cls, error: BaseException, *, cancelled: bool = False) -> "FailTurn":
        """Describe an exception as a command.

        Whether an attempt counts as cancelled is the caller's judgement --
        what counts depends on how the turn was being run, which is not
        something the session knows.
        """
        return cls(
            error_type="Cancelled" if cancelled else type(error).__name__,
            error_message=str(error)[:MAX_ERROR_MESSAGE] or "cancelled",
            cancelled=cancelled,
        )


class CompactConversation(Command):
    """Replace older messages, for the model's benefit, with a summary."""

    summary: str
    through_index: int
    strategy: str
    tokens_before: int = 0
    tokens_after: int = 0


class RecordForkSource(Command):
    source_session_id: UUID
    at_event: int


class WriteFile(Command):
    path: str
    file_data: dict[str, Any]


class EditFile(Command):
    path: str
    file_data: dict[str, Any]
    old_string: str
    new_string: str
    replace_all: bool = False


class DeleteFile(Command):
    path: str


class RecordToolDecision(Command):
    """A tool call was allowed, refused, or amended, and by whom."""

    tool_name: str
    args: dict[str, Any]
    decision: str
    decided_by: str
    edited_args: dict[str, Any] | None = None
    review_id: UUID | None = None
    """The stage review this decision answered. None when it answered none."""


class RecordStageReview(Command):
    """The check library ran at a gate; here is what it was asked and found."""

    review_id: UUID
    project_id: UUID
    stage: str
    preset: str
    preset_version: str
    evaluated: list[dict[str, Any]]
    unimplemented: list[dict[str, Any]]
    posed_by: str


class ChangeAutonomy(Command):
    """A tool's autonomy level changed mid-session."""

    tool_name: str
    level: str


SessionCommand = (
    StartSession
    | SendUserMessage
    | RecordAssistantMessage
    | RecordToolResult
    | CompleteTurn
    | FailTurn
    | CompactConversation
    | RecordForkSource
    | WriteFile
    | EditFile
    | DeleteFile
    | RecordToolDecision
    | RecordStageReview
    | ChangeAutonomy
)
"""Every request a session accepts.

The union is the written-down surface: one place that says what a session can
be asked, which `decide` is expected to answer for in full. Nothing checks
that statically today -- this project runs ruff, not a type checker -- so the
guarantee at runtime is `decide`'s closing `raise`, which turns a command
nobody handled into a rejection rather than a silent no-op. Adding a type
checker later would move that from runtime to build time without changing
anything here.
"""
