"""The fork forest, as a pure function over summaries."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from research_team.application import SessionSummary, build_fork_tree

START = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def summary(index: int, *, forked_from=None, forked_at=None) -> SessionSummary:
    return SessionSummary(
        session_id=uuid4(),
        started_at=START + timedelta(minutes=index),
        turns=index,
        files=0,
        first_message=f"session {index}",
        forked_from=forked_from,
        forked_at=forked_at,
    )


def test_unforked_sessions_are_all_roots():
    sessions = [summary(1), summary(2)]
    tree = build_fork_tree(sessions)
    assert [node.session for node in tree] == sessions
    assert all(node.children == () for node in tree)


def test_a_fork_nests_under_its_parent():
    parent = summary(1)
    child = summary(2, forked_from=parent.session_id, forked_at=3)

    tree = build_fork_tree([parent, child])

    assert [node.session for node in tree] == [parent]
    assert [node.session for node in tree[0].children] == [child]
    assert tree[0].children[0].session.forked_at == 3


def test_forks_of_forks_nest_arbitrarily_deep():
    root = summary(1)
    child = summary(2, forked_from=root.session_id, forked_at=1)
    grandchild = summary(3, forked_from=child.session_id, forked_at=2)

    tree = build_fork_tree([root, child, grandchild])

    assert tree[0].children[0].children[0].session == grandchild


def test_siblings_are_ordered_by_when_they_started():
    parent = summary(1)
    later = summary(3, forked_from=parent.session_id, forked_at=2)
    earlier = summary(2, forked_from=parent.session_id, forked_at=1)

    tree = build_fork_tree([parent, later, earlier])

    assert [node.session for node in tree[0].children] == [earlier, later]


def test_an_orphan_stays_visible_as_a_root():
    """A session whose parent is gone must not vanish from the forest."""
    orphan = summary(1, forked_from=uuid4(), forked_at=5)

    tree = build_fork_tree([orphan])

    assert [node.session for node in tree] == [orphan]


def test_an_empty_store_is_an_empty_forest():
    assert build_fork_tree([]) == []
