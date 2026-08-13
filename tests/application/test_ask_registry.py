"""In-memory conversations for the ask page, and the bounds on keeping them.

Nothing here is persisted. The registry exists so a follow-up question can see
the question before it within one browser tab, and the bounds exist so a
long-lived server cannot accumulate conversations without limit.
"""

from uuid import uuid4

from research_team.application.ask import AskMessage, ConversationRegistry


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
