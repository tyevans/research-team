"""The CodingSession aggregate: the single source of truth for a session."""

from typing import Any
from uuid import UUID

from eventsource import DeclarativeAggregate, handles
from pydantic import BaseModel, Field

from research_team.domain.events import (
    AssistantMessageAdded,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)


class SessionState(BaseModel):
    """Everything derivable from the event stream."""

    session_id: UUID
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


def _outstanding_tool_call_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Tool call ids requested by the last AI message but not yet answered."""
    requested: set[str] = set()
    for message in reversed(messages):
        if message.get("type") == "ai":
            requested = {
                call["id"] for call in message.get("data", {}).get("tool_calls", [])
            }
            break
    answered = {
        message.get("data", {}).get("tool_call_id")
        for message in messages
        if message.get("type") == "tool"
    }
    return requested - answered


class CodingSession(DeclarativeAggregate[SessionState]):
    aggregate_type = "CodingSession"
    requires_creation_event = True
    schema_version = 3  # SessionState gained conversation compaction

    # ---------------- commands ----------------

    def start(self, system_prompt: str, model_name: str) -> None:
        if self.version > 0:
            raise ValueError("session already started")
        self.create_event(
            SessionStarted, system_prompt=system_prompt, model_name=model_name
        )

    def send_user_message(self, message: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(UserMessageSent, message=message)

    def record_assistant_message(self, message: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(AssistantMessageAdded, message=message)

    def record_tool_result(
        self, message: dict[str, Any], *, is_error: bool = False
    ) -> None:
        self._require_started()
        call_id = message.get("data", {}).get("tool_call_id")
        if call_id not in _outstanding_tool_call_ids(self.state.messages):
            raise ValueError(f"no outstanding tool call with id {call_id!r}")
        self.create_event(ToolResultRecorded, message=message, is_error=is_error)

    def complete_turn(self) -> None:
        self._require_started()
        self.create_event(TurnCompleted, turn_index=self.state.turn_index + 1)

    def fail_turn(self, error: BaseException, *, cancelled: bool = False) -> None:
        """Record an attempted turn that did not complete.

        Does not advance turn_index: the turn did not happen. This is appended
        to a freshly loaded aggregate, so it never carries the failed turn's
        own events with it.

        `cancelled` says the attempt was stopped on purpose. Deciding that is
        the caller's job -- what counts as a cancellation depends on how the
        turn was being run, which is not something the aggregate knows.
        """
        self._require_started()
        self.create_event(
            TurnFailed,
            turn_index=self.state.turn_index + 1,
            error_type="Cancelled" if cancelled else type(error).__name__,
            error_message=str(error)[:500] or "cancelled",
            cancelled=cancelled,
        )

    def compact_conversation(
        self,
        summary: str,
        through_index: int,
        strategy: str,
        *,
        tokens_before: int = 0,
        tokens_after: int = 0,
    ) -> None:
        """Record that a summary now stands in for the first `through_index`
        messages, as far as the model is concerned.

        Refuses to go backwards or past the end: a compaction that uncovered
        messages an earlier one had covered would leave the model seeing a
        summary *and* the messages it summarises.
        """
        self._require_started()
        if not self.state.compacted_through < through_index <= len(self.state.messages):
            raise ValueError(
                f"cannot compact through {through_index}: "
                f"{len(self.state.messages)} messages, "
                f"already compacted through {self.state.compacted_through}"
            )
        self.create_event(
            ConversationCompacted,
            summary=summary,
            through_index=through_index,
            strategy=strategy,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

    def record_fork_source(self, source_session_id: UUID, at_event: int) -> None:
        self._require_started()
        self.create_event(
            SessionForkedFrom,
            source_session_id=source_session_id,
            at_event=at_event,
        )

    def write_file(self, path: str, file_data: dict[str, Any]) -> None:
        self._require_started()
        self.create_event(FileWritten, path=path, file_data=file_data)

    def edit_file(
        self,
        path: str,
        file_data: dict[str, Any],
        old_string: str,
        new_string: str,
        replace_all: bool,
    ) -> None:
        self._require_started()
        self._require_file(path)
        self.create_event(
            FileEdited,
            path=path,
            file_data=file_data,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )

    def delete_file(self, path: str) -> None:
        self._require_started()
        self._require_file(path)
        self.create_event(FileDeleted, path=path)

    # ---------------- guards ----------------

    def _require_started(self) -> None:
        if self.version == 0:
            raise ValueError("session not started")

    def _require_file(self, path: str) -> None:
        if path not in self.state.files:
            raise ValueError(f"file {path!r} does not exist")

    # ---------------- reducers ----------------

    @handles(SessionStarted)
    def _on_started(self, event: SessionStarted) -> None:
        self._state = SessionState(
            session_id=self.aggregate_id,
            system_prompt=event.system_prompt,
            model_name=event.model_name,
        )

    @handles(UserMessageSent)
    def _on_user_message(self, event: UserMessageSent) -> None:
        self._append_message(event.message)

    @handles(AssistantMessageAdded)
    def _on_assistant_message(self, event: AssistantMessageAdded) -> None:
        self._append_message(event.message)

    @handles(ToolResultRecorded)
    def _on_tool_result(self, event: ToolResultRecorded) -> None:
        self._append_message(event.message)

    @handles(TurnCompleted)
    def _on_turn_completed(self, event: TurnCompleted) -> None:
        self._state = self._state.model_copy(update={"turn_index": event.turn_index})

    @handles(TurnFailed)
    def _on_turn_failed(self, event: TurnFailed) -> None:
        # turn_index deliberately unchanged: the turn did not happen.
        self._state = self._state.model_copy(
            update={"failed_turns": self._state.failed_turns + 1}
        )

    @handles(ConversationCompacted)
    def _on_compacted(self, event: ConversationCompacted) -> None:
        # `messages` is untouched: the log keeps everything, and only the view
        # handed to the model is shortened.
        self._state = self._state.model_copy(
            update={
                "compacted_through": event.through_index,
                "compaction_summary": event.summary,
            }
        )

    @handles(SessionForkedFrom)
    def _on_forked_from(self, event: SessionForkedFrom) -> None:
        self._state = self._state.model_copy(
            update={
                "forked_from": event.source_session_id,
                "forked_at": event.at_event,
            }
        )

    @handles(FileWritten)
    def _on_file_written(self, event: FileWritten) -> None:
        self._put_file(event.path, event.file_data)

    @handles(FileEdited)
    def _on_file_edited(self, event: FileEdited) -> None:
        self._put_file(event.path, event.file_data)

    @handles(FileDeleted)
    def _on_file_deleted(self, event: FileDeleted) -> None:
        files = {k: v for k, v in self._state.files.items() if k != event.path}
        self._state = self._state.model_copy(update={"files": files})

    # ---------------- reducer helpers ----------------

    def _append_message(self, message: dict[str, Any]) -> None:
        self._state = self._state.model_copy(
            update={"messages": [*self._state.messages, message]}
        )

    def _put_file(self, path: str, file_data: dict[str, Any]) -> None:
        self._state = self._state.model_copy(
            update={"files": {**self._state.files, path: file_data}}
        )
