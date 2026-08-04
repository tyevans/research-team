"""The CodingSession decider: the rules, as three pure functions.

`initial_state` says what a session is before anything has happened, `decide`
says which requests are legal and what facts they produce, and `evolve` says
what each fact does to the state. None of them touch a store, a version, an
aggregate, or anything async, so the rules can be read and tested as rules.

`CodingSession` at the bottom is the shell that connects them to the library's
machinery -- replay, snapshots, optimistic concurrency, the repository. It
holds no logic of its own, which is the point: everything that decides
anything is above it, and everything below it is bookkeeping.
"""

from typing import Any, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent
from pydantic import BaseModel, Field

from research_team.domain.commands import (
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
    StartSession,
    WriteFile,
)
from research_team.domain.events import (
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

    session_id: UUID
    status: Literal["new", "started"] = "new"
    """Whether the session exists yet.

    The imperative aggregate answered this with `version > 0`, which is a fact
    about the event store rather than about a session. A decider has to phrase
    it in the domain, because `decide` runs against a real state before any
    event exists and has nothing else to match on.
    """

    system_prompt: str = ""
    model_name: str = ""
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


def initial_state(aggregate_id: UUID) -> SessionState:
    """A session before anything has happened to it."""
    return SessionState(session_id=aggregate_id)


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
        case StartSession(system_prompt=prompt, model_name=model), SessionState(
            status="new"
        ):
            return [
                SessionStarted(
                    aggregate_id=session_id, system_prompt=prompt, model_name=model
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
                raise CommandRejectedError(
                    f"no outstanding tool call with id {call_id!r}"
                )
            return [
                ToolResultRecorded(
                    aggregate_id=session_id, message=message, is_error=is_error
                )
            ]

        # ---- turns ----
        case CompleteTurn(), _:
            return [
                TurnCompleted(aggregate_id=session_id, turn_index=state.turn_index + 1)
            ]

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
        case RecordForkSource(source_session_id=source, at_event=at), _:
            return [
                SessionForkedFrom(
                    aggregate_id=session_id, source_session_id=source, at_event=at
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
        # Both of these are audit records: they say what was decided about a
        # tool call, or how a tool's autonomy level changed. Neither is a fact
        # `SessionState` tracks, so `evolve` deliberately leaves them alone.
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
            return [
                AutonomyChanged(
                    aggregate_id=session_id, tool_name=tool_name, level=level
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: SessionState, event: DomainEvent) -> SessionState:
    """What each fact does to the state.

    Total on purpose: an event with no branch leaves the state alone rather
    than raising, so a stream carrying an event this build does not know about
    still replays instead of failing halfway through.
    """
    match event:
        case SessionStarted(system_prompt=prompt, model_name=model):
            # Replaces state wholesale: this is the creation event, and it is
            # the only one that establishes rather than amends.
            return SessionState(
                session_id=state.session_id,
                status="started",
                system_prompt=prompt,
                model_name=model,
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

        case SessionForkedFrom(source_session_id=source, at_event=at):
            return state.model_copy(update={"forked_from": source, "forked_at": at})

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


class CodingSession(DeciderAggregate[SessionState, SessionCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Everything the library needs from an aggregate (replay, snapshots, version
    checks, repository integration) is inherited; everything this project
    decides lives in the functions above.

    Note what is gone relative to the imperative version: there is no
    `requires_creation_event`, because `DeciderAggregate` initialises state
    eagerly and "not created yet" is `status="new"` instead -- a fact about
    the session rather than about its event count.
    """

    aggregate_type = "CodingSession"
    schema_version = 4  # SessionState gained `status` for the decider port

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
