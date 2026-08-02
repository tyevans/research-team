import inspect

import pytest
from deepagents.backends.state import StateBackend

from research_team.backend import EventSourcedBackend
from research_team.events import FileDeleted, FileEdited, FileWritten


@pytest.fixture
def backend(session) -> EventSourcedBackend:
    return EventSourcedBackend(session)


def event_types(session) -> list[type]:
    return [type(e) for e in session.uncommitted_events]


def test_seams_still_exist_on_upstream_state_backend():
    """Guard: we subclass over private seams. An upstream change must fail loudly."""
    assert hasattr(StateBackend, "_read_files")
    assert hasattr(StateBackend, "_send_files_update")
    read_sig = inspect.signature(StateBackend._read_files)
    send_sig = inspect.signature(StateBackend._send_files_update)
    assert list(read_sig.parameters) == ["self"]
    assert list(send_sig.parameters) == ["self", "update"]


def test_write_emits_file_written(backend, session):
    result = backend.write("/a.py", "print(1)\n")
    assert result.error is None
    assert event_types(session)[-1] is FileWritten
    assert session.state.files["/a.py"]["content"] == "print(1)\n"


def test_read_returns_written_content(backend):
    backend.write("/a.py", "print(1)\n")
    result = backend.read("/a.py")
    assert result.error is None
    assert result.file_data["content"] == "print(1)\n"


def test_edit_emits_file_edited_with_intent(backend, session):
    backend.write("/a.py", "print(1)\n")
    result = backend.edit("/a.py", "1", "2")
    assert result.error is None

    event = session.uncommitted_events[-1]
    assert isinstance(event, FileEdited)
    assert (event.old_string, event.new_string) == ("1", "2")
    assert event.file_data["content"] == "print(2)\n"


def test_edit_on_missing_file_errors_without_emitting(backend, session):
    before = len(session.uncommitted_events)
    result = backend.edit("/nope.py", "1", "2")
    assert result.error is not None
    assert len(session.uncommitted_events) == before


def test_edit_intent_is_cleared_after_edit(backend, session):
    backend.write("/a.py", "print(1)\n")
    backend.edit("/a.py", "1", "2")
    backend.write("/b.py", "x = 1\n")
    assert event_types(session)[-1] is FileWritten


def test_edit_intent_cleared_even_when_edit_raises(backend, session, monkeypatch):
    backend.write("/a.py", "print(1)\n")
    monkeypatch.setattr(
        StateBackend, "edit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError):
        backend.edit("/a.py", "1", "2")
    monkeypatch.undo()
    backend.write("/b.py", "x = 1\n")
    assert event_types(session)[-1] is FileWritten


def test_delete_emits_file_deleted(backend, session):
    backend.write("/a.py", "print(1)\n")
    result = backend.delete("/a.py")
    assert result.error is None
    assert event_types(session)[-1] is FileDeleted
    assert "/a.py" not in session.state.files


def test_inherited_ls_grep_glob_work(backend):
    backend.write("/a.py", "alpha\nbeta\n")
    backend.write("/b.txt", "gamma\n")

    assert {entry["path"] for entry in backend.ls("/").entries} == {"/a.py", "/b.txt"}
    assert [m["path"] for m in backend.glob("**/*.py").matches] == ["/a.py"]
    assert [m["line"] for m in backend.grep("beta").matches] == [2]


def test_ambiguous_edit_is_rejected_by_inherited_validation(backend, session):
    backend.write("/a.py", "x\nx\n")
    before = len(session.uncommitted_events)
    result = backend.edit("/a.py", "x", "y")
    assert result.error is not None
    assert len(session.uncommitted_events) == before


def test_replace_all_edits_every_occurrence(backend, session):
    backend.write("/a.py", "x\nx\n")
    result = backend.edit("/a.py", "x", "y", replace_all=True)
    assert result.error is None
    assert session.state.files["/a.py"]["content"] == "y\ny\n"


def test_file_ops_do_not_require_graph_context(backend):
    """Overriding both seams means _get_config is never reached."""
    assert backend.write("/a.py", "x\n").error is None
