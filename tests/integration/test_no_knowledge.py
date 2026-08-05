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


async def test_reading_a_store_holding_knowledge_events_needs_no_extra_import(tmp_path):
    """redstring registers its event types at import; composition must force it."""
    import subprocess
    import sys

    # A cold process that imports only research_team must still be able to
    # deserialize redstring's events, or the registry is incomplete.
    code = (
        "from research_team.composition import build_application; "
        "from eventsource import default_registry; "
        "assert 'DocumentExtracted' in default_registry, sorted(default_registry)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


async def test_an_unreachable_graph_store_fails_at_start(build_applications, monkeypatch):
    """An unreachable Neo4j fails `start()`, not some later turn."""
    monkeypatch.setenv("AGENT_GRAPH_STORE", "neo4j")
    monkeypatch.setenv("AGENT_NEO4J_URI", "bolt://127.0.0.1:9")  # discard port
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", "irrelevant")

    # The exact type is the driver's to choose (DNS failure, connection
    # refused, timeout) -- what matters here is that *something* raises
    # during `start()` rather than later, mid-turn.
    with pytest.raises(Exception):  # noqa: B017
        await build_applications(project_id=uuid4())
