"""In-memory conversations for the ask page, and the bounds on keeping them.

Nothing here is persisted. The registry exists so a follow-up question can see
the question before it within one browser tab, and the bounds exist so a
long-lived server cannot accumulate conversations without limit.
"""

from uuid import uuid4

from research_team.dialogue.application.ask import AskMessage, ConversationRegistry


def registry(clock, **kwargs) -> ConversationRegistry:
    return ConversationRegistry(now=clock, **kwargs)


def test_an_unknown_chat_id_yields_an_empty_conversation():
    """A first question should not need the browser to announce itself first."""
    conversations = registry(lambda: 0.0)

    conversation = conversations.get("chat-1", uuid4())

    assert conversation.messages == ()


def test_a_stored_conversation_comes_back_with_its_messages():
    """This is the whole point of holding them: a follow-up sees what came before."""
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conversation = conversations.get("chat-1", project).appended(
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
        at=0.0,
    )
    conversations.put(conversation)

    assert conversations.get("chat-1", project).messages == (
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
    )


def test_a_conversation_idle_past_the_ttl_is_forgotten():
    """Held forever, an ephemeral store is just a leak with a nicer name."""
    project = uuid4()
    clock = iter([0.0, 3_601.0])
    conversations = registry(lambda: next(clock), idle_seconds=3_600.0)
    conversations.put(
        conversations.get("chat-1", project).appended(
            AskMessage(role="user", text="hello"), at=0.0
        )
    )

    assert conversations.get("chat-1", project).messages == ()


def test_the_least_recently_used_conversation_is_evicted_at_the_limit():
    """A bound that only trims the newest would evict the chat someone is using."""
    project = uuid4()
    ticks = iter(range(100))
    conversations = registry(lambda: float(next(ticks)), limit=2)
    for chat_id in ("a", "b"):
        conversations.put(
            conversations.get(chat_id, project).appended(
                AskMessage(role="user", text=chat_id), at=0.0
            )
        )
    conversations.get("a", project)  # touch: 'b' is now the least recent

    conversations.put(
        conversations.get("c", project).appended(AskMessage(role="user", text="c"), at=0.0)
    )

    assert len(conversations) == 2
    assert conversations.get("a", project).messages != ()
    assert conversations.get("b", project).messages == ()


def test_a_chat_id_belonging_to_another_project_is_not_served():
    """Chat ids come from the browser; one must not read another project's answers."""
    conversations = registry(lambda: 0.0)
    conversations.put(
        conversations.get("chat-1", uuid4()).appended(
            AskMessage(role="user", text="secret"), at=0.0
        )
    )

    assert conversations.get("chat-1", uuid4()).messages == ()


def test_dropping_a_conversation_forgets_it():
    """The 'new chat' control has to mean something on the server too."""
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conversations.put(
        conversations.get("chat-1", project).appended(
            AskMessage(role="user", text="hello"), at=0.0
        )
    )

    conversations.drop("chat-1")

    assert conversations.get("chat-1", project).messages == ()


def test_conversation_registry_is_truthy_even_when_empty():
    conversations = registry(lambda: 0.0)
    assert len(conversations) == 0
    assert bool(conversations) is True


def test_conversation_registry_contains_and_in():
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conv = conversations.get("chat-1", project)
    conversations.put(conv)

    assert "chat-1" in conversations
    assert "chat-2" not in conversations
    assert conversations.contains("chat-1", project) is True
    assert conversations.contains("chat-1", uuid4()) is False


def test_conversation_registry_clear():
    project = uuid4()
    conversations = registry(lambda: 0.0)
    conversations.put(conversations.get("chat-1", project))
    conversations.put(conversations.get("chat-2", project))

    assert len(conversations) == 2
    conversations.clear()
    assert len(conversations) == 0


def test_conversation_registry_evict_idle_and_active_chat_ids():
    project = uuid4()
    current_time = [100.0]
    conversations = registry(lambda: current_time[0], idle_seconds=50.0)

    c1 = conversations.get("chat-1", project)
    conversations.put(c1)
    current_time[0] = 120.0
    c2 = conversations.get("chat-2", project)
    conversations.put(c2)

    current_time[0] = 160.0
    # c1 is idle (>50s), c2 is active (40s)
    assert conversations.active_chat_ids(project) == ["chat-2"]

    evicted = conversations.evict_idle()
    assert evicted == 1
    assert "chat-1" not in conversations
    assert "chat-2" in conversations


def test_conversation_registry_get_by_conversation_id():
    project = uuid4()
    conversations = registry(lambda: 0.0)
    c1 = conversations.get("chat-1", project)
    conversations.put(c1)

    found = conversations.get_by_conversation_id(c1.conversation_id, project)
    assert found is not None
    assert found.chat_id == "chat-1"

    # Mismatched project returns None
    assert conversations.get_by_conversation_id(c1.conversation_id, uuid4()) is None
    # Unknown id returns None
    assert conversations.get_by_conversation_id(uuid4(), project) is None
