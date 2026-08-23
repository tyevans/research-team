"""A graph, laid out and written into files somebody can keep.

Three renderings of one arrangement. The HTML is the deliverable -- a single
file that opens from a mail attachment with no server, no network and no
build step -- and the other two exist because the first thing anyone does
with a graph they were sent is try to load it into something else.

**Positions are computed once and shared by all three.** Gephi lays a graph
out itself and does not need them, but a GraphML that already carries `x`/`y`
opens showing the same picture the HTML did, and two files of the same graph
that draw differently invite the question of which is the real one.

`GraphEntity`/`GraphRelationship` are `graph_read`'s types rather than
redstring's, so this module is reachable from anything that can already read
a graph and stays out of the extraction vocabulary entirely.
"""

import json
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from research_team.application.graph_layout import compute_layout
from research_team.application.graph_read import GraphEntity, GraphRelationship

#: How many nodes an export lays out by default. Well below
#: `MAX_GRAPH_NODES`, and the reason is time rather than legibility:
#: `compute_layout` is quadratic per pass, and measured on 2026-08-22 the
#: whole-graph layout takes 2.1 s at 500 nodes, 8.4 s at 1,000, 19 s at 2,500
#: and 40 s at 5,000. An export is a deliberate one-off action, so a few
#: seconds is affordable in a way it would not be on a browse path -- but a
#: forty-second request that a proxy may time out before it finishes is a
#: feature that fails for the largest projects and works for every one
#: somebody tested it on. Raise it per request with `limit` if you want the
#: whole of a big graph and are prepared to wait.
MAX_EXPORT_NODES = 2_000


@dataclass(frozen=True)
class ExportNode:
    """One node with somewhere to be. `x`/`y` are in `graph_layout`'s units."""

    entity_id: str
    name: str
    entity_type: str
    inferred: bool
    temporal: str | None
    x: float
    y: float


@dataclass(frozen=True)
class ExportGraph:
    """A laid-out graph and what it is a graph of.

    `title` and `scope` ride along because the file leaves the system: a
    `graph.html` in somebody's downloads folder with no idea which project or
    which area it came from is one they will delete rather than ask about.

    `truncated` is carried for the reason `Graph.truncated` is -- a reader
    handed 2,000 of 3,400 nodes and no flag is looking at something that
    reads as complete and is not.
    """

    title: str
    scope: str
    nodes: tuple[ExportNode, ...]
    edges: tuple[GraphRelationship, ...]
    truncated: bool


def build_export(
    entities: tuple[GraphEntity, ...] | list[GraphEntity],
    relationships: tuple[GraphRelationship, ...] | list[GraphRelationship],
    *,
    title: str,
    scope: str,
    limit: int = MAX_EXPORT_NODES,
    truncated: bool = False,
) -> ExportGraph:
    """Lay the graph out and pair each entity with its position.

    Edges whose ends did not both survive the `limit` are dropped rather than
    kept pointing at nothing. `GraphReadPort.neighborhood` already promises
    this of its own results and the reason is the same here: an edge to a node
    the file does not contain is a line the viewer cannot draw and Gephi will
    reject the import over.
    """
    kept = list(entities)[:limit]
    truncated = truncated or len(kept) < len(entities)
    index = {entity.entity_id: position for position, entity in enumerate(kept)}

    edges = tuple(
        edge for edge in relationships if edge.source_id in index and edge.target_id in index
    )
    layout = compute_layout(
        len(kept), [(index[e.source_id], index[e.target_id]) for e in edges]
    )

    nodes = tuple(
        ExportNode(
            entity_id=entity.entity_id,
            name=entity.name,
            entity_type=entity.entity_type,
            inferred=entity.inferred,
            temporal=entity.temporal,
            # Rounded to a tenth of a layout unit. The full float32 is noise
            # at the scale anyone views this -- the drawing spans a thousand
            # units -- and it roughly halves the size of the JSON blob the
            # HTML file has to carry inline.
            x=round(float(layout.positions[position][0]), 1),
            y=round(float(layout.positions[position][1]), 1),
        )
        for position, entity in enumerate(kept)
    )
    return ExportGraph(title=title, scope=scope, nodes=nodes, edges=edges, truncated=truncated)


def to_payload(graph: ExportGraph) -> dict:
    """The graph as plain data, which is both the JSON file and what the
    HTML viewer is handed inline.

    One function rather than two so the file somebody loads into a script and
    the drawing they were sent cannot describe different graphs. Keys are
    `snake_case`, matching every other JSON this server emits.
    """
    return {
        "title": graph.title,
        "scope": graph.scope,
        "truncated": graph.truncated,
        "nodes": [
            {
                "id": node.entity_id,
                "name": node.name,
                "entity_type": node.entity_type,
                "inferred": node.inferred,
                "temporal": node.temporal,
                "x": node.x,
                "y": node.y,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": edge.source_id,
                "target": edge.target_id,
                "relationship_type": edge.relationship_type,
                "inferred": edge.inferred,
                "derivation": edge.derivation,
            }
            for edge in graph.edges
        ],
    }


def to_json(graph: ExportGraph) -> str:
    return json.dumps(to_payload(graph), indent=2, ensure_ascii=False)


#: GraphML's own namespace plus yEd's `viz` extension, which is what Gephi
#: reads node positions out of. Declared together because a document that
#: names `viz:position` without binding the prefix is not well-formed XML and
#: Gephi's importer fails on it with a parse error rather than a warning.
_GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
_VIZ_NS = "http://www.gexf.net/1.1draft/viz"


def to_graphml(graph: ExportGraph) -> str:
    """The graph as GraphML, with positions, for Gephi and friends.

    Hand-built with `ElementTree` rather than through a graph library: the
    document is four element shapes and `networkx` would be a dependency
    added to call one writer. `ElementTree` is in the standard library and
    escapes attribute values, which is the part worth not writing by hand --
    entity names in this corpus are whole clauses and contain quotes.

    Attribute *keys* are declared up front because GraphML requires it: a
    `<data key="name">` with no matching `<key>` element is silently dropped
    by every importer rather than rejected, so a file that looked fine would
    open in Gephi as a graph of unlabelled dots.
    """
    ET.register_namespace("", _GRAPHML_NS)
    ET.register_namespace("viz", _VIZ_NS)
    root = ET.Element(f"{{{_GRAPHML_NS}}}graphml")

    for key_id, target, name, kind in (
        ("name", "node", "name", "string"),
        ("entity_type", "node", "entity_type", "string"),
        ("temporal", "node", "temporal", "string"),
        ("node_inferred", "node", "inferred", "boolean"),
        ("x", "node", "x", "double"),
        ("y", "node", "y", "double"),
        ("relationship_type", "edge", "relationship_type", "string"),
        ("edge_inferred", "edge", "inferred", "boolean"),
        ("derivation", "edge", "derivation", "string"),
    ):
        ET.SubElement(
            root,
            f"{{{_GRAPHML_NS}}}key",
            {"id": key_id, "for": target, "attr.name": name, "attr.type": kind},
        )

    # `edgedefault` is required by the schema and the honest value is
    # "directed": every relationship here reads source-to-target ("Rome
    # contains the Forum"), and declaring it undirected would turn each into
    # a claim it does not make.
    body = ET.SubElement(
        root, f"{{{_GRAPHML_NS}}}graph", {"id": graph.scope, "edgedefault": "directed"}
    )

    for node in graph.nodes:
        element = ET.SubElement(body, f"{{{_GRAPHML_NS}}}node", {"id": node.entity_id})
        _data(element, "name", node.name)
        _data(element, "entity_type", node.entity_type)
        _data(element, "node_inferred", "true" if node.inferred else "false")
        _data(element, "x", str(node.x))
        _data(element, "y", str(node.y))
        if node.temporal is not None:
            _data(element, "temporal", node.temporal)
        # The `viz` position as well as the plain `x`/`y` data keys. Gephi
        # reads this one; a script reading the file with `ElementTree` will
        # find the other more obvious. Writing both costs two attributes.
        ET.SubElement(
            element,
            f"{{{_VIZ_NS}}}position",
            {"x": str(node.x), "y": str(node.y), "z": "0.0"},
        )

    for position, edge in enumerate(graph.edges):
        element = ET.SubElement(
            body,
            f"{{{_GRAPHML_NS}}}edge",
            # An explicit id per edge rather than letting them go unnamed:
            # this graph can hold two differently-typed relationships between
            # the same pair, and an importer deduplicating on endpoints would
            # silently drop the second.
            {"id": f"e{position}", "source": edge.source_id, "target": edge.target_id},
        )
        _data(element, "relationship_type", edge.relationship_type)
        _data(element, "edge_inferred", "true" if edge.inferred else "false")
        if edge.derivation is not None:
            _data(element, "derivation", edge.derivation)

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _data(parent: ET.Element, key: str, value: str) -> None:
    element = ET.SubElement(parent, f"{{{_GRAPHML_NS}}}data", {"key": key})
    element.text = value
