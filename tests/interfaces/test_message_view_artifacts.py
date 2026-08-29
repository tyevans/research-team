"""`message_view` stops dropping a tool message's `name` and `artifact`.

Both already sit in the stored payload -- `message_to_dict` keeps every field
of a `ToolMessage` -- and both were being dropped on the way to the browser.
"""

from research_team.interfaces.web.presenters import message_view


def test_a_tool_message_carries_its_name_and_artifact() -> None:
    view = message_view(
        {
            "type": "tool",
            "data": {
                "content": "19 match(es) …",
                "name": "search_sources",
                "artifact": {"shape": "hit_list", "version": 1, "sources": []},
            },
        }
    )
    assert view["name"] == "search_sources"
    assert view["artifact"]["shape"] == "hit_list"


def test_a_message_written_before_artifacts_existed_carries_none() -> None:
    """The permanent path, not an error case: every historical message takes
    it, and the console must render text rather than an empty card."""
    view = message_view({"type": "tool", "data": {"content": "19 match(es) …"}})
    assert view["artifact"] is None
    assert view["name"] is None
    assert view["content"] == "19 match(es) …"


def test_a_message_with_a_name_but_no_artifact_carries_a_none_artifact() -> None:
    """An unconverted tool: `name` was always there, `artifact` never was.
    The two fields are independent -- one present does not imply the other."""
    view = message_view(
        {"type": "tool", "data": {"content": "some text", "name": "an_unconverted_tool"}}
    )
    assert view["name"] == "an_unconverted_tool"
    assert view["artifact"] is None
