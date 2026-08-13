"""A filesystem the ask agent can read and cannot write.

The refusal is loud on purpose. A backend that silently dropped writes would
let a prompt believe it had saved something, and the failure would surface
later as absence rather than as an error.
"""

import pytest

from research_team.infrastructure.agent.read_only_backend import (
    ReadOnlyFilesystem,
    ReadOnlyProjectBackend,
)


def test_files_given_at_construction_are_readable():
    """The agent's whole reason to have a filesystem is reading what a project wrote."""
    backend = ReadOnlyProjectBackend({"notes.md": {"content": "hello"}})

    assert backend._read_files() == {"notes.md": {"content": "hello"}}


def test_a_write_raises_rather_than_being_dropped():
    """Silence here would read as success to the model and as data loss to a person."""
    backend = ReadOnlyProjectBackend({})

    with pytest.raises(ReadOnlyFilesystem):
        backend._send_files_update({"notes.md": {"content": "hello"}})


def test_the_snapshot_is_copied_so_a_caller_cannot_mutate_it_afterwards():
    """Handing out the caller's own dict would be a write path with extra steps."""
    files = {"notes.md": {"content": "hello"}}
    backend = ReadOnlyProjectBackend(files)
    files["other.md"] = {"content": "snuck in"}

    assert "other.md" not in backend._read_files()
