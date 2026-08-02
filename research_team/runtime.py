"""Wiring and the operations that drive a session."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from deepagents import create_deep_agent
from eventsource import DomainEvent, StreamId, collect
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, message_to_dict
from langchain_openai import ChatOpenAI

from research_team.backend import EventSourcedBackend
from research_team.events import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)
from research_team.messages import classify, new_messages, to_langchain
from research_team.session import CodingSession

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell and no network."
)

SNAPSHOT_THRESHOLD = 50


def default_db_path() -> str:
    """Where sessions live. Sessions persist across runs and are resumable."""
    configured = os.getenv("AGENT_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "sessions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def build_model() -> BaseChatModel:
    """The local OpenAI-compatible endpoint, fully env-overridable."""
    return ChatOpenAI(
        model=os.getenv("AGENT_MODEL", "qwen3.6-27b-mtp"),
        base_url=os.getenv("AGENT_BASE_URL", "http://192.168.1.14:8080/v1/"),
        api_key=os.getenv("AGENT_API_KEY", "not-needed"),
        temperature=0,
    )


@dataclass
class AgentRuntime:
    store: SQLiteEventStore
    repo: AggregateRepository[CodingSession]
    session_id: UUID
    model: BaseChatModel
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    async def close(self) -> None:
        await self.store.close()


@dataclass(frozen=True)
class SessionSummary:
    """One row of `/sessions`, derived by folding a session's events."""

    session_id: UUID
    started_at: datetime
    turns: int
    files: int
    first_message: str


def _build_repo(store: SQLiteEventStore, db_path: str) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        # Same database file as the event store: the schema that creates the
        # `snapshots` table is applied by the store's connection, so a separate
        # path (or a second ":memory:") would leave the table missing.
        snapshot_store=SQLiteSnapshotStore(db_path),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="sync",
    )


async def build_runtime(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    session_id: UUID | None = None,
) -> AgentRuntime:
    """Open a session. Passing `session_id` resumes an existing one.

    Resuming appends no SessionStarted event and keeps the stored system
    prompt, so the resumed stream stays a faithful continuation rather than a
    session with two beginnings.
    """
    resolved_path = db_path if db_path is not None else default_db_path()
    store = SQLiteEventStore(resolved_path)
    repo = _build_repo(store, resolved_path)
    resolved_model = model if model is not None else build_model()

    if session_id is not None:
        aggregate = await repo.load(session_id)
        return AgentRuntime(
            store=store,
            repo=repo,
            session_id=session_id,
            model=resolved_model,
            system_prompt=aggregate.state.system_prompt or system_prompt,
        )

    model_name = getattr(resolved_model, "model_name", type(resolved_model).__name__)
    new_id = uuid4()
    aggregate = repo.create_new(new_id)
    aggregate.start(system_prompt, model_name)
    await repo.save(aggregate)

    return AgentRuntime(
        store=store,
        repo=repo,
        session_id=new_id,
        model=resolved_model,
        system_prompt=system_prompt,
    )


async def start_session(runtime: AgentRuntime) -> UUID:
    """Begin a fresh session on the same database and switch the runtime to it."""
    model_name = getattr(runtime.model, "model_name", type(runtime.model).__name__)
    new_id = uuid4()
    aggregate = runtime.repo.create_new(new_id)
    aggregate.start(runtime.system_prompt, model_name)
    await runtime.repo.save(aggregate)
    runtime.session_id = new_id
    return new_id


async def list_sessions(runtime: AgentRuntime) -> list[SessionSummary]:
    """Every session in the database, newest first.

    A projection built by folding the category stream -- the same events the
    aggregate folds, grouped by session instead of replayed into one.
    """
    envelopes = await collect(
        runtime.store.read_category(CodingSession.aggregate_type)
    )

    grouped: dict[UUID, list[DomainEvent]] = {}
    for envelope in envelopes:
        grouped.setdefault(envelope.event.aggregate_id, []).append(envelope.event)

    summaries = [
        SessionSummary(
            session_id=session_id,
            started_at=events[0].occurred_at,
            turns=max(
                (e.turn_index for e in events if isinstance(e, TurnCompleted)),
                default=0,
            ),
            files=len(
                {e.path for e in events if isinstance(e, FileWritten | FileEdited)}
                - {e.path for e in events if isinstance(e, FileDeleted)}
            ),
            first_message=_first_user_text(events),
        )
        for session_id, events in grouped.items()
    ]
    return sorted(summaries, key=lambda s: s.started_at, reverse=True)


def _first_user_text(events: list[DomainEvent]) -> str:
    for event in events:
        if isinstance(event, UserMessageSent):
            return str(event.message.get("data", {}).get("content", ""))
    return ""


def describe_activity(message: BaseMessage) -> str | None:
    """A one-line progress note for a message, or None if it is not worth showing."""
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return "· " + ", ".join(
            f"{call['name']}({_first_arg(call.get('args', {}))})" for call in tool_calls
        )
    if isinstance(message, ToolMessage):
        first_line = str(message.content).strip().splitlines()
        return f"  ↳ {first_line[0][:70]}" if first_line else None
    return None


def _first_arg(args: dict[str, object]) -> str:
    for key in ("file_path", "path", "pattern", "command"):
        if key in args:
            return str(args[key])
    return ""


async def _invoke_agent(
    runtime: AgentRuntime,
    aggregate: CodingSession,
    messages: list[BaseMessage],
    on_activity: Callable[[str], None] | None = None,
) -> list[BaseMessage]:
    """Run one agent pass, reporting tool activity as it happens.

    Streams with `stream_mode="values"`, where each chunk is the full state.
    That yields live progress and the final message list from a single pass --
    a local model can take a minute per turn, and silence for that long is
    indistinguishable from a hang.

    Kept as a separate seam so tests can force a mid-turn failure.
    """
    agent = create_deep_agent(
        model=runtime.model,
        backend=EventSourcedBackend(aggregate),
        system_prompt=runtime.system_prompt,
        checkpointer=None,
    )

    final: list[BaseMessage] = list(messages)
    reported = len(messages)
    async for state in agent.astream({"messages": messages}, stream_mode="values"):
        final = state["messages"]
        if on_activity is not None:
            for message in final[reported:]:
                note = describe_activity(message)
                if note:
                    on_activity(note)
        reported = len(final)
    return final


async def run_turn(
    runtime: AgentRuntime,
    user_input: str,
    on_activity: Callable[[str], None] | None = None,
) -> str:
    """One user turn. All events append atomically at the end, or not at all."""
    aggregate = await runtime.repo.load(runtime.session_id)
    aggregate.send_user_message(message_to_dict(_human(user_input)))

    sent = to_langchain(aggregate.state)
    after = await _invoke_agent(runtime, aggregate, sent, on_activity)

    for message in new_messages(len(sent), after):
        event_class = classify(message)
        if event_class is ToolResultRecorded:
            aggregate.record_tool_result(message_to_dict(message))
        elif event_class is AssistantMessageAdded:
            aggregate.record_assistant_message(message_to_dict(message))
        else:
            # A HumanMessage in the suffix means turn accounting has drifted:
            # the user's message would be recorded twice. Fail loudly rather
            # than quietly writing a corrupt event to an append-only log.
            raise RuntimeError(
                f"unexpected {type(message).__name__} in agent output suffix; "
                "turn accounting is wrong"
            )

    aggregate.complete_turn()
    await runtime.repo.save(aggregate)

    return _last_text(after)


def _human(text: str) -> BaseMessage:
    from langchain_core.messages import HumanMessage

    return HumanMessage(text)


def _last_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            if message.content:
                return message.content
    return ""


def _stream(session_id: UUID) -> StreamId:
    return StreamId(session_id, CodingSession.aggregate_type)


async def history(runtime: AgentRuntime) -> list[DomainEvent]:
    envelopes = await collect(runtime.store.read_stream(_stream(runtime.session_id)))
    return [envelope.event for envelope in envelopes]


async def fork(runtime: AgentRuntime, at: int) -> UUID:
    """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
    events = await history(runtime)
    if not 1 <= at <= len(events):
        raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

    new_id = uuid4()
    forked = runtime.repo.create_new(new_id)
    for event in events[:at]:
        forked.create_event(
            type(event),
            **event.model_dump(
                exclude={
                    "event_id",
                    "event_type",
                    "occurred_at",
                    "aggregate_id",
                    "aggregate_type",
                    "aggregate_version",
                }
            ),
        )
    await runtime.repo.save(forked)
    return new_id


async def rewind(runtime: AgentRuntime, at: int) -> None:
    """Fork at `at` and continue from the fork. The original stream remains."""
    runtime.session_id = await fork(runtime, at)
