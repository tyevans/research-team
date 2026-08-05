"""The default install has no knowledge graph at all.

Sibling of `test_no_network.py`, and for the same reason: a claim about what a
default install does is only true while something checks it.
"""

from uuid import uuid4

import pytest


def _tool_names(application) -> set[str]:
    return {tool.name for tool in application.turns_tools()}


async def test_a_session_with_no_project_gets_no_knowledge_tools(build_application):
    """With no project configured, the agent gets no knowledge tools at all."""
    application = await build_application()

    names = _tool_names(application)
    assert "remember" not in names
    assert "graph_search" not in names
    assert "unmerge" not in names
    assert application.knowledge is None


async def test_a_project_registers_the_knowledge_tools(build_application):
    application = await build_application(project_id=uuid4())

    names = _tool_names(application)
    assert {"remember", "graph_search", "unmerge"} <= names
    assert application.knowledge is not None


def test_composition_imports_redstring_events() -> None:
    """`composition.py` names `redstring.events` as its own top-level import.

    A runtime check ("is the registry populated after importing composition")
    cannot catch the explicit import being deleted: composition also imports
    `research_team.infrastructure.knowledge.redstring_adapter`, which reaches
    `redstring.events` transitively (via `redstring` and
    `redstring.events.streams`), and importing a submodule always imports its
    parent package too -- so `redstring.events` lands in `sys.modules`
    regardless of the explicit line. Verified by hand: deleting the explicit
    `import redstring.events` from `composition.py` and running this test as
    a runtime/`sys.modules` check left it passing.

    So this asserts the source, not the outcome: composition's own AST must
    contain the import statement. That is what makes the guarantee
    deliberate -- named by composition itself -- rather than an accident of
    which other module happens to get imported alongside it, and it is the
    one form of this test that a deleted import line actually fails.

    This does not prove the import is load-bearing today (nothing currently
    reads a `DocumentExtracted` on the no-project path in these tests) --
    only that composition performs the import itself, so the guarantee holds
    even if `redstring_adapter`'s import were ever made conditional.
    """
    import ast
    from pathlib import Path

    import research_team.composition as composition_module

    tree = ast.parse(Path(composition_module.__file__).read_text())
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "redstring.events" in imported_modules


async def test_an_unreachable_graph_store_fails_at_start(tmp_path, monkeypatch):
    """An unreachable Neo4j fails `start()` specifically, not construction.

    Split into two phases on purpose: `build_application` must return
    normally (the store is opened lazily; a driver is built but nothing has
    talked to the server yet), and only the subsequent `await app.start()` --
    which calls `ensure_schema()`, the first real network call -- may raise.
    Wrapping the whole build-and-start sequence in one `pytest.raises` would
    also pass for a `ValueError` out of `build_graph_store` or a `TypeError`
    from a mis-wired constructor, which is not the property this test is for.
    """
    from neo4j.exceptions import ServiceUnavailable

    from research_team.composition import build_application

    monkeypatch.setenv("AGENT_GRAPH_STORE", "neo4j")
    monkeypatch.setenv("AGENT_NEO4J_URI", "bolt://127.0.0.1:9")  # discard port
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", "irrelevant")

    application = build_application(db_path=str(tmp_path / "sessions.db"), project_id=uuid4())
    try:
        with pytest.raises(ServiceUnavailable):
            await application.start()
    finally:
        await application.close()
