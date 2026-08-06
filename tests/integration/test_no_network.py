"""What the agent can reach outside the process, and what stands in front of it.

The README makes two different promises about egress, because the two network
tools are withheld two different ways, and both promises rest on registration
and policy rather than on an absent dependency -- which is a weaker thing to
rest on. So both are asserted here.

`web_search` is withheld by configuration: no instance, no tool. `fetch` is
always registered and withheld by its `ask` floor instead, because there is no
instance to leave unconfigured. If that floor ever silently became `auto`, a
default install would reach the open web unattended and nothing else in the
suite would notice.
"""

from research_team.application import SEARCH_TOOL
from research_team.application.autonomy import FETCH_TOOL


def _tool_names(application) -> set[str]:
    return {tool.name for tool in application.service._executor._tools}


async def test_a_default_application_has_no_search_tool(build_application, monkeypatch):
    """With no SearXNG configured, the agent cannot search."""
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)

    application = await build_application()

    assert SEARCH_TOOL not in _tool_names(application)


async def test_fetch_is_always_registered(build_application, monkeypatch):
    """Unlike search, it is present even with nothing configured -- there is
    no instance to withhold, so registration is not the lever."""
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)

    application = await build_application()

    assert FETCH_TOOL in _tool_names(application)


async def test_fetch_cannot_reach_the_network_unattended(build_application, monkeypatch):
    """The floor is the whole reason the tool can ship registered. This is the
    assertion that makes the README's wording true.
    """
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)

    application = await build_application()

    assert application.policy.level_for(FETCH_TOOL) == "ask"


async def test_a_configured_application_offers_search(build_application, monkeypatch):
    """With one configured, the tool appears -- and is gated, not free."""
    monkeypatch.setenv("AGENT_SEARXNG_URL", "http://localhost:8888")

    application = await build_application()

    assert SEARCH_TOOL in _tool_names(application)
    assert SEARCH_TOOL in application.policy.levels()
