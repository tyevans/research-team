"""No search tool unless one was configured.

The README promises a default install reaches nothing outside the process.
That promise now rests on a conditional registration rather than on an absent
dependency, which is a weaker thing to rest on -- so it is asserted here.
"""

from research_team.application import SEARCH_TOOL


def _tool_names(application) -> set[str]:
    return {tool.name for tool in application.service._executor._tools}


async def test_a_default_application_has_no_search_tool(build_application, monkeypatch):
    """With no SearXNG configured, the agent is offered no network tool."""
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)

    application = await build_application()

    assert SEARCH_TOOL not in _tool_names(application)


async def test_a_configured_application_offers_search(build_application, monkeypatch):
    """With one configured, the tool appears -- and is gated, not free."""
    monkeypatch.setenv("AGENT_SEARXNG_URL", "http://localhost:8888")

    application = await build_application()

    assert SEARCH_TOOL in _tool_names(application)
    assert SEARCH_TOOL in application.policy.levels()
