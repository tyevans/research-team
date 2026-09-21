"""The Session decider: the rules, as three pure functions.

`initial_state` says what a session is before anything has happened, `decide`
says which requests are legal and what facts they produce, and `evolve` says
what each fact does to the state. None of them touch a store, a version, an
aggregate, or anything async, so the rules can be read and tested as rules.

`Session` at the bottom is the shell that connects them to the library's
machinery -- replay, snapshots, optimistic concurrency, the repository. It
holds no logic of its own, which is the point: everything that decides
anything is above it, and everything below it is bookkeeping.
"""

from typing import Any, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent
from pydantic import BaseModel, Field

from research_team.session.domain.commands import (
    ChangeAutonomy,
    CompactConversation,
    CompleteTurn,
    DeleteFile,
    EditFile,
    FailTurn,
    RecordAssistantMessage,
    RecordForkSource,
    RecordToolDecision,
    RecordToolResult,
    SendUserMessage,
    SessionCommand,
    SessionPurpose,
    StartSession,
    WriteFile,
)
from research_team.session.domain.events import (
    AssistantMessageAdded,
    AutonomyChanged,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    ToolCallDecided,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)


class SessionState(BaseModel):
    """Everything derivable from the event stream."""

    session_id: UUID | None = None
    """None before the session exists. Set by the fold of `SessionStarted`.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "started"] = "new"
    """Whether the session exists yet.

    The imperative aggregate answered this with `version > 0`, which is a fact
    about the event store rather than about a session. A decider has to phrase
    it in the domain, because `decide` runs against a real state before any
    event exists and has nothing else to match on.
    """

    system_prompt: str = ""
    model_name: str = ""
    project_id: UUID | None = None
    """The project whose filesystem and knowledge graph this session shares.

    Still `| None`, unlike `SessionStarted.project_id`, and for the same reason
    `session_id` is: `initial_state()` takes no arguments, so every field needs
    a value that is true before any event exists. `None` here means `status ==
    "new"` and nothing else -- once `SessionStarted` has folded, a project is
    always present, because the event cannot carry anything else.
    """
    purpose: SessionPurpose = SessionPurpose.CHAT
    """What kind of work this session is for. See `SessionPurpose`.

    Defaulted here and required on the event, which looks inconsistent and is
    not: `initial_state()` takes no arguments (eventsource 0.12), so every
    field on the state needs a value that is true before any event exists --
    the same reason `session_id` and `project_id` are `| None` above despite
    being required on `SessionStarted`. The default is unreachable in practice:
    the fold replaces the state wholesale on `SessionStarted`, so no started
    session ever carries it.
    """
    files: dict[str, dict[str, Any]] = Field(default_factory=dict)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    turn_index: int = 0
    failed_turns: int = 0
    forked_from: UUID | None = None
    forked_at: int | None = None
    compacted_through: int = 0
    """How many leading messages a summary now stands in for. 0 means none."""
    compaction_summary: str = ""
    """The summary itself. The messages it replaces are still in `messages`."""

    @property
    def is_empty(self) -> bool:
        """True when the session has had no turns and has no messages."""
        return self.turn_index == 0 and len(self.messages) == 0

    @property
    def file_paths(self) -> list[str]:
        """All paths currently in the session filesystem, sorted."""
        return sorted(self.files.keys())

    @property
    def total_messages(self) -> int:
        """Count of all recorded messages."""
        return len(self.messages)

    @property
    def effective_messages(self) -> list[dict[str, Any]]:
        """The messages visible to the model after compaction."""
        return self.messages[self.compacted_through :]

    @property
    def last_user_message(self) -> str | None:
        """The text content of the latest user message, or None."""
        for msg in reversed(self.messages):
            if msg.get("type") == "human":
                content = msg.get("data", {}).get("content")
                if isinstance(content, str):
                    return content
                return str(content) if content is not None else None
        return None

    @property
    def last_assistant_message(self) -> str | None:
        """The text content of the latest assistant message, or None."""
        for msg in reversed(self.messages):
            if msg.get("type") == "ai":
                content = msg.get("data", {}).get("content")
                if isinstance(content, str):
                    return content
                return str(content) if content is not None else None
        return None

    @property
    def outstanding_tool_calls(self) -> set[str]:
        """Tool call ids requested by the last AI message but not yet answered."""
        return outstanding_tool_call_ids(self.messages)

    def has_file(self, path: str) -> bool:
        """Whether `path` currently exists in the session filesystem."""
        return path in self.files

    def file_content(self, path: str) -> str | None:
        """Content of `path` if it exists, otherwise None."""
        entry = self.files.get(path)
        if entry is None:
            return None
        content = entry.get("content")
        return str(content) if content is not None else None

    def message_counts_by_type(self) -> dict[str, int]:
        """Count messages grouped by their 'type' ('human', 'ai', 'tool', etc.)."""
        counts: dict[str, int] = {}
        for msg in self.messages:
            msg_type = msg.get("type", "unknown")
            counts[msg_type] = counts.get(msg_type, 0) + 1
        return counts


def initial_state() -> SessionState:
    """A session before anything has happened to it."""
    return SessionState()


def outstanding_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Tool call ids requested by the last AI message but not yet answered."""
    requested: set[str] = set()
    for message in reversed(messages):
        if message.get("type") == "ai":
            requested = {call["id"] for call in message.get("data", {}).get("tool_calls", [])}
            break
    answered = {
        message.get("data", {}).get("tool_call_id")
        for message in messages
        if message.get("type") == "tool"
    }
    return requested - answered


def decide(command: SessionCommand, state: SessionState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table: each `case` is one legal move, or one
    explicitly illegal one. The "session does not exist yet" rejection is a
    single case near the top rather than a guard repeated per command -- every
    command except `StartSession` needs a started session, and saying that
    once is both shorter and harder to forget.
    """
    session_id = state.session_id
    match command, state:
        # ---- creation ----
        case StartSession(
            session_id=new_id,
            system_prompt=prompt,
            model_name=model,
            project_id=project_id,
            purpose=purpose,
        ), SessionState(status="new"):
            return [
                SessionStarted(
                    # From the command, not the state: this is the creation
                    # command, so on a fresh session `state.session_id` is None.
                    aggregate_id=new_id,
                    system_prompt=prompt,
                    model_name=model,
                    project_id=project_id,
                    purpose=purpose,
                )
            ]
        case StartSession(), _:
            raise CommandRejectedError("session already started")

        case _, SessionState(status="new"):
            raise CommandRejectedError("session not started")

        # ---- conversation ----
        case SendUserMessage(message=message), _:
            return [UserMessageSent(aggregate_id=session_id, message=message)]

        case RecordAssistantMessage(message=message), _:
            return [AssistantMessageAdded(aggregate_id=session_id, message=message)]

        case RecordToolResult(message=message, is_error=is_error), _:
            call_id = message.get("data", {}).get("tool_call_id")
            if call_id not in outstanding_tool_call_ids(state.messages):
                raise CommandRejectedError(f"no outstanding tool call with id {call_id!r}")
            return [
                ToolResultRecorded(aggregate_id=session_id, message=message, is_error=is_error)
            ]

        # ---- turns ----
        case CompleteTurn(), _:
            return [TurnCompleted(aggregate_id=session_id, turn_index=state.turn_index + 1)]

        case FailTurn(
            error_type=error_type, error_message=error_message, cancelled=cancelled
        ), _:
            # turn_index is not advanced: the turn did not happen.
            return [
                TurnFailed(
                    aggregate_id=session_id,
                    turn_index=state.turn_index + 1,
                    error_type=error_type,
                    error_message=error_message,
                    cancelled=cancelled,
                )
            ]

        # ---- context ----
        case CompactConversation(through_index=through), _ if not (
            state.compacted_through < through <= len(state.messages)
        ):
            # Going backwards would uncover messages an earlier summary
            # covered, leaving the model both a summary and its own inputs.
            raise CommandRejectedError(
                f"cannot compact through {through}: "
                f"{len(state.messages)} messages, "
                f"already compacted through {state.compacted_through}"
            )
        case CompactConversation(
            summary=summary,
            through_index=through,
            strategy=strategy,
            tokens_before=before,
            tokens_after=after,
        ), _:
            return [
                ConversationCompacted(
                    aggregate_id=session_id,
                    summary=summary,
                    through_index=through,
                    strategy=strategy,
                    tokens_before=before,
                    tokens_after=after,
                )
            ]

        # ---- lineage ----
        case RecordForkSource(source_session_id=source, at_event=at, purpose=purpose), _:
            return [
                SessionForkedFrom(
                    aggregate_id=session_id,
                    source_session_id=source,
                    at_event=at,
                    purpose=purpose,
                )
            ]

        # ---- files ----
        case WriteFile(path=path, file_data=file_data), _:
            return [FileWritten(aggregate_id=session_id, path=path, file_data=file_data)]

        case EditFile(path=path), _ if path not in state.files:
            raise CommandRejectedError(f"file {path!r} does not exist")
        case EditFile(
            path=path,
            file_data=file_data,
            old_string=old,
            new_string=new,
            replace_all=replace_all,
        ), _:
            return [
                FileEdited(
                    aggregate_id=session_id,
                    path=path,
                    file_data=file_data,
                    old_string=old,
                    new_string=new,
                    replace_all=replace_all,
                )
            ]

        case DeleteFile(path=path), _ if path not in state.files:
            raise CommandRejectedError(f"file {path!r} does not exist")
        case DeleteFile(path=path), _:
            return [FileDeleted(aggregate_id=session_id, path=path)]

        # ---- supervision ----
        # Both are audit records: what was decided about a tool call, and how a
        # tool's autonomy level changed. Neither is a fact `SessionState`
        # tracks, so `evolve` deliberately leaves them alone.
        case RecordToolDecision(
            tool_name=tool_name,
            args=args,
            decision=decision,
            decided_by=decided_by,
            edited_args=edited_args,
        ), _:
            return [
                ToolCallDecided(
                    aggregate_id=session_id,
                    tool_name=tool_name,
                    args=args,
                    decision=decision,
                    decided_by=decided_by,
                    edited_args=edited_args,
                )
            ]

        case ChangeAutonomy(tool_name=tool_name, level=level), _:
            return [AutonomyChanged(aggregate_id=session_id, tool_name=tool_name, level=level)]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: SessionState, event: DomainEvent) -> SessionState:
    """What each fact does to the state.

    Total on purpose: an event with no branch leaves the state alone rather
    than raising, so a stream carrying an event this build does not know about
    still replays instead of failing halfway through.
    """
    match event:
        case SessionStarted(
            system_prompt=prompt,
            model_name=model,
            project_id=project_id,
            purpose=purpose,
        ):
            # Replaces state wholesale: this is the creation event, and it is
            # the only one that establishes rather than amends.
            return SessionState(
                # The event is where the id enters the state: `decide` reads it
                # back off `state` for every command but the first.
                session_id=event.aggregate_id,
                status="started",
                system_prompt=prompt,
                model_name=model,
                project_id=project_id,
                purpose=purpose,
            )

        case (
            UserMessageSent(message=message)
            | AssistantMessageAdded(message=message)
            | ToolResultRecorded(message=message)
        ):
            return state.model_copy(update={"messages": [*state.messages, message]})

        case TurnCompleted(turn_index=turn_index):
            return state.model_copy(update={"turn_index": turn_index})

        case TurnFailed():
            # turn_index deliberately unchanged: the turn did not happen.
            return state.model_copy(update={"failed_turns": state.failed_turns + 1})

        case ConversationCompacted(summary=summary, through_index=through):
            # `messages` is untouched: the log keeps everything, and only the
            # view handed to the model is shortened.
            return state.model_copy(
                update={"compacted_through": through, "compaction_summary": summary}
            )

        case SessionForkedFrom(source_session_id=source, at_event=at, purpose=purpose):
            updates: dict[str, Any] = {"forked_from": source, "forked_at": at}
            if purpose is not None:
                updates["purpose"] = purpose
            return state.model_copy(update=updates)

        case (
            FileWritten(path=path, file_data=file_data)
            | FileEdited(path=path, file_data=file_data)
        ):
            return state.model_copy(update={"files": {**state.files, path: file_data}})

        case FileDeleted(path=path):
            remaining = {k: v for k, v in state.files.items() if k != path}
            return state.model_copy(update={"files": remaining})

        case _:
            return state


class Session(DeciderAggregate[SessionState, SessionCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Everything the library needs from an aggregate (replay, snapshots, version
    checks, repository integration) is inherited; everything this project
    decides lives in the functions above.

    Note what is gone relative to the imperative version: there is no
    `requires_creation_event`, because `DeciderAggregate` initialises state
    eagerly and "not created yet" is `status="new"` instead -- a fact about
    the session rather than about its event count.
    """

    aggregate_type = "Session"
    schema_version = 4  # SessionState gained `status` for the decider port

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
