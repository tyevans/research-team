"""Wiring and the operations that drive a session."""

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

from deepagents import create_deep_agent
from eventsource import DomainEvent, StreamId, collect
from eventsource.adapters.memory import InMemoryEventStore
from eventsource.adapters.memory.snapshots import InMemorySnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict
from langchain_openai import ChatOpenAI

from research_team.backend import EventSourcedBackend
from research_team.events import AssistantMessageAdded, ToolResultRecorded
from research_team.messages import classify, new_messages, to_langchain
from research_team.session import CodingSession

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell and no network."
)

SNAPSHOT_THRESHOLD = 50


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
    store: InMemoryEventStore
    repo: AggregateRepository[CodingSession]
    session_id: UUID
    model: BaseChatModel
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


def _build_repo(store: InMemoryEventStore) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        snapshot_store=InMemorySnapshotStore(),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="sync",
    )


async def build_runtime(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> AgentRuntime:
    store = InMemoryEventStore()
    repo = _build_repo(store)
    resolved_model = model if model is not None else build_model()
    model_name = getattr(resolved_model, "model_name", type(resolved_model).__name__)

    session_id = uuid4()
    aggregate = repo.create_new(session_id)
    aggregate.start(system_prompt, model_name)
    await repo.save(aggregate)

    return AgentRuntime(
        store=store,
        repo=repo,
        session_id=session_id,
        model=resolved_model,
        system_prompt=system_prompt,
    )


async def _invoke_agent(
    runtime: AgentRuntime, aggregate: CodingSession, messages: list[BaseMessage]
) -> list[BaseMessage]:
    """Seam kept separate so tests can force a mid-turn failure."""
    agent = create_deep_agent(
        model=runtime.model,
        backend=EventSourcedBackend(aggregate),
        system_prompt=runtime.system_prompt,
        checkpointer=None,
    )
    result = await agent.ainvoke({"messages": messages})
    return result["messages"]


async def run_turn(runtime: AgentRuntime, user_input: str) -> str:
    """One user turn. All events append atomically at the end, or not at all."""
    aggregate = await runtime.repo.load(runtime.session_id)
    aggregate.send_user_message(message_to_dict(_human(user_input)))

    sent = to_langchain(aggregate.state)
    after = await _invoke_agent(runtime, aggregate, sent)

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
