"""Laying a graph out, and writing it into the three files that leave here.

What can only break in this module: the arrangement being reproducible, the
extent being the one the exported viewer's thresholds assume, and each
serialisation being loadable by the thing it is for. The viewer's own
behaviour is not here -- it is JavaScript in a file, and the only honest test
of it is opening it in a browser (see the task report).
"""

import json
from xml.etree import ElementTree as ET

from research_team.application.graph_export import (
    build_export,
    to_graphml,
    to_json,
    to_payload,
)
from research_team.application.graph_layout import _EXTENT, compute_layout
from research_team.application.graph_read import GraphEntity, GraphRelationship
from research_team.interfaces.web.graph_html import render_html


def _entities(count: int) -> list[GraphEntity]:
    return [
        GraphEntity(
            entity_id=f"e{i}",
            name=f"Entity {i}",
            entity_type="concept" if i % 2 else "event",
            inferred=i % 5 == 0,
            temporal="AD 380" if i % 3 == 0 else None,
        )
        for i in range(count)
    ]


def _chain(count: int) -> list[GraphRelationship]:
    return [
        GraphRelationship(
            source_id=f"e{i}",
            target_id=f"e{i + 1}",
            relationship_type="relates_to",
            inferred=i % 4 == 0,
            derivation="1923 contains November 1923" if i % 4 == 0 else None,
        )
        for i in range(count - 1)
    ]


def test_the_same_graph_lays_out_the_same_way_twice() -> None:
    """The seed is a constant, and this is what says so.

    Two people comparing the file they were each sent have to be comparing
    the same drawing. Would fail on an unseeded `default_rng()`, which is the
    obvious way to write this and is wrong.
    """
    edges = [(0, 1), (1, 2), (2, 3), (0, 3)]
    first = compute_layout(8, edges)
    second = compute_layout(8, edges)

    assert first.positions.tolist() == second.positions.tolist()


def test_a_settled_layout_fills_the_extent_it_claims_to() -> None:
    """`_EXTENT` is normalised to, not merely aimed at.

    Failed before the normalising step existed: the loop's own units put a
    220-node graph across roughly 19,000, twenty times the constant. Nothing
    downstream raised -- the exported viewer simply drew no labels, because
    its threshold is a zoom level and fitting a 19,000-unit drawing to a
    window is a zoom of 0.035.
    """
    positions = compute_layout(60, [(i, i + 1) for i in range(59)]).positions
    span = max(
        float(positions[:, 0].max() - positions[:, 0].min()),
        float(positions[:, 1].max() - positions[:, 1].min()),
    )

    assert span == 0 or abs(span - _EXTENT) < 1.0


def test_a_graph_with_no_edges_still_gets_positions() -> None:
    """The gravity term is what stops this being a division by zero.

    A project whose entities are all unconnected is an ordinary early state,
    not an error, and it must export rather than 500.
    """
    layout = compute_layout(12, [])

    assert len(layout) == 12
    assert not (layout.positions != layout.positions).any(), "NaN in the positions"


def test_an_edge_whose_end_was_truncated_away_is_dropped() -> None:
    """Not kept pointing at nothing.

    Gephi refuses an import naming a node the file does not declare, and the
    exported viewer would draw a line to the origin. Would pass with the
    filter removed if the fixture happened to keep both ends, which is why
    the limit here cuts the chain in the middle.
    """
    graph = build_export(_entities(10), _chain(10), title="t", scope="project", limit=4)

    assert len(graph.nodes) == 4
    assert {edge.target_id for edge in graph.edges} <= {"e0", "e1", "e2", "e3"}
    assert graph.truncated is True


def test_the_json_carries_a_position_for_every_node() -> None:
    """The point of computing the layout server-side.

    A JSON export with no coordinates would be a node list, which is what
    `/api/projects/{id}/graph` already returns.
    """
    graph = build_export(_entities(6), _chain(6), title="t", scope="project")
    body = json.loads(to_json(graph))

    assert len(body["nodes"]) == 6
    assert all("x" in node and "y" in node for node in body["nodes"])
    assert body["edges"][0]["relationship_type"] == "relates_to"


def test_the_graphml_declares_a_key_for_every_data_it_writes() -> None:
    """An undeclared `<data key>` is dropped silently by every importer.

    So a file missing a `<key>` element opens in Gephi as a graph of
    unlabelled dots rather than failing -- which is the failure this asserts
    against, because nothing else would report it.
    """
    document = ET.fromstring(
        to_graphml(build_export(_entities(5), _chain(5), title="t", scope="project"))
    )
    namespace = "{http://graphml.graphdrawing.org/xmlns}"

    declared = {key.get("id") for key in document.findall(f"{namespace}key")}
    used = {data.get("key") for data in document.iter(f"{namespace}data")}

    assert used, "no data elements at all"
    assert used <= declared


def test_the_graphml_names_every_node_and_its_edges() -> None:
    graph = build_export(_entities(5), _chain(5), title="t", scope="project")
    document = ET.fromstring(to_graphml(graph))
    namespace = "{http://graphml.graphdrawing.org/xmlns}"

    ids = {node.get("id") for node in document.iter(f"{namespace}node")}
    assert ids == {f"e{i}" for i in range(5)}
    assert len(list(document.iter(f"{namespace}edge"))) == 4


def test_an_entity_named_after_a_closing_script_tag_does_not_end_the_script() -> None:
    """`json.dumps` does not escape `<`, and this file inlines its data.

    An entity called `</script><h1>x</h1>` would otherwise close the tag
    early: the rest of the graph renders as visible page text and the markup
    after it renders as markup. Model output contains angle brackets often
    enough that this is a case rather than a hypothetical.
    """
    hostile = [
        GraphEntity(
            entity_id="e0",
            name="</script><h1>pwned</h1>",
            entity_type="concept",
        )
    ]
    html = render_html(build_export(hostile, [], title="t", scope="project"))

    assert "</script><h1>pwned</h1>" not in html
    assert "\\u003c/script>" in html
    # And the escape is still valid JSON, so the viewer can read it back.
    start = html.index('type="application/json">') + len('type="application/json">')
    payload = json.loads(html[start : html.index("</script>", start)])
    assert payload["nodes"][0]["name"] == "</script><h1>pwned</h1>"


def test_the_exported_html_asks_the_network_for_nothing() -> None:
    """The whole promise of the file: it opens from a mail attachment.

    A single `<script src>` or `@import` added later would break that with no
    other symptom on a machine that happens to be online, which is every
    machine anybody would test it on.
    """
    html = render_html(build_export(_entities(4), _chain(4), title="t", scope="project"))

    assert "http://" not in html
    assert "https://" not in html
    assert "<script src" not in html
    assert "@import" not in html


def test_the_payload_the_viewer_reads_is_the_payload_the_json_file_holds() -> None:
    """One function behind both, so the drawing and the data file cannot
    describe different graphs."""
    graph = build_export(_entities(6), _chain(6), title="t", scope="project")

    assert json.loads(to_json(graph)) == to_payload(graph)
