"""The CodingSession aggregate: the single source of truth for a session."""

from typing import Any
from uuid import UUID

from eventsource import DeclarativeAggregate, handles
from pydantic import BaseModel, Field

from research_team.events import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
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
    schema_version = 1

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
