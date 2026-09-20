"""Graph, ontology, and timeline presenters for the web interface."""

from typing import Any

from research_team.application.entity_definitions import Definition, ServedCitation
from research_team.application.graph_read import (
    EntityPage,
    Graph,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.application.timeline_read import Timeline, TimelineBand
from research_team.application.usages import Usage


def entity_view(entity: GraphEntity) -> dict[str, Any]:
    """One node, in the shape a graph browser draws: id, label, kind.

    `temporal` is passed through as the port already rendered it -- `None`
    for an entity with no extent, a string for one that has it -- rather
    than reshaped here, so there is one place, not two, that decides what a
    temporal edge is allowed to compare.

    `inferred` travels with every node, not only synthesised ones, for
    `relationship_view`'s reason: a client should never have to read an
    absent key as `false`. It matters more here than there, because it is not
    only a display flag -- a synthesised class node's id belongs to no stored
    entity, so a client that fetches `/neighborhood` or `/definition` on click
    must not fetch for one. See `GraphEntity.inferred`.
    """
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "inferred": entity.inferred,
        "temporal": entity.temporal,
    }


def relationship_view(relationship: GraphRelationship) -> dict[str, Any]:
    """One edge: the two ends a browser connects, and the label on the line.

    `inferred` and `derivation` travel with every edge, not only inferred
    ones, so a client never has to treat their absence as "false" -- see
    `GraphRelationship.derivation`'s docstring for why an inferred edge with
    no visible derivation would be indistinguishable from a stored one.
    """
    return {
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "relationship_type": relationship.relationship_type,
        "inferred": relationship.inferred,
        "derivation": relationship.derivation,
    }


def entity_page_view(page: EntityPage) -> dict[str, Any]:
    """One page of `/api/projects/{id}/graph/entities`.

    `next_after` is passed straight through -- `None` already means "no
    further page" on both `EntityPage` and the cursor contract the browser
    consumes it under, so there is no translation to do here.
    """
    return {
        "entities": [entity_view(entity) for entity in page.entities],
        "next_after": page.next_after,
    }


def graph_view(graph: Graph) -> dict[str, Any]:
    """A whole project graph, in the shape a browser draws it in one go.

    Flat `entities`/`relationships` with no root, unlike `neighborhood_view`:
    a whole graph has no entity the reader asked about, and inventing one to
    match the other response's shape would be inventing a fact. `truncated`
    is passed through rather than being left implicit in the entity count --
    a client cannot tell a complete graph of 500 from the first 500 of 900 by
    counting. `inferred_truncated` is the same guarantee for the inferred
    edges specifically: they are capped separately from the node limit (see
    `MAX_INFERRED_EDGES`), so a graph can be complete on `truncated` and still
    have dropped inferred edges.
    """
    return {
        "entities": [entity_view(entity) for entity in graph.entities],
        "relationships": [
            relationship_view(relationship) for relationship in graph.relationships
        ],
        "truncated": graph.truncated,
        "inferred_truncated": graph.inferred_truncated,
    }


def neighborhood_view(neighborhood: Neighborhood) -> dict[str, Any]:
    """A root plus what a graph browser can draw around it in one response.

    `root` is rendered through `entity_view` rather than repeated inline,
    the same reason `topic_detail_view` builds on `topic_view`: the root and
    an entry in `entities` describe a node the same way, and duplicating that
    shape here is a second place for it to drift.
    """
    return {
        "root": entity_view(neighborhood.root),
        "entities": [entity_view(entity) for entity in neighborhood.entities],
        "relationships": [
            relationship_view(relationship) for relationship in neighborhood.relationships
        ],
    }


def usages_view(usages: list[Usage]) -> dict[str, Any]:
    """`GET .../usages`, best matches first -- already the order `UsageReader`
    returns, so there is nothing to re-sort here.
    """
    return {
        "usages": [
            {
                "source_id": usage.source_id,
                "start": usage.start,
                "end": usage.end,
                "text": usage.text,
                "score": usage.score,
            }
            for usage in usages
        ]
    }


def definition_view(
    definition: Definition | None, served: list[ServedCitation] | None = None
) -> dict[str, Any]:
    """`GET .../definition`.

    `definition is None` renders as `text: None` with no citations, rather
    than the route raising a 404 -- see `read_graph_definition`'s docstring
    for why an undefinable entity is not a missing one. `model` and
    `generated_at` are `None` too in that case: there is no generation to
    report on, and a placeholder value here would read as though one had run.

    `served` is `definition.citations` run through `entity_definitions.
    serve_citations`, in the same order -- passed in rather than resolved
    here because this function is a pure presenter and resolving a citation's
    moment needs a corpus read (see `read_graph_definition`). `None` (the
    default) means the caller had no corpus read model to resolve against,
    which renders every citation's `at_seconds` as `None` -- indistinguishable
    from a source with no locator map, which is the correct behaviour for a
    build that cannot check: it is not this presenter's place to claim a
    moment it cannot verify.
    """
    if definition is None:
        return {
            "text": None,
            "citations": [],
            "model": None,
            "generated_at": None,
            "stale": False,
        }
    citations = (
        served
        if served is not None
        else [
            ServedCitation(source_id=c.source_id, start=c.start, end=c.end, at_seconds=None)
            for c in definition.citations
        ]
    )
    return {
        "text": definition.text,
        "citations": [
            {
                "source_id": citation.source_id,
                "start": citation.start,
                "end": citation.end,
                "at_seconds": citation.at_seconds,
            }
            for citation in citations
        ],
        "model": definition.model,
        "generated_at": definition.generated_at,
        "stale": definition.stale,
    }


def band_view(band: TimelineBand) -> dict[str, Any]:
    """One bar: what to draw, where to put it, and what the document said.

    `extent` and the `start`/`end` pair both travel, which looks redundant and
    is not -- see `TimelineBand.extent`. A browser given only the interval
    would label a bar "1815-01-01T00:00:00 - 1816-01-01T00:00:00" for a
    document that said "1815".

    `precision` and `uncertainty` travel on every band rather than only on
    uncertain ones, the same choice `relationship_view` makes with `inferred`:
    a client never has to read an absent field as a default it guessed at.
    """
    return {
        "entity_id": band.entity_id,
        "name": band.name,
        "entity_type": band.entity_type,
        "extent": band.extent,
        "start": band.start,
        "end": band.end,
        "precision": band.precision,
        "uncertainty": band.uncertainty,
    }


def timeline_view(timeline: Timeline) -> dict[str, Any]:
    """A project's dated entities in time order, and what is not in the drawing.

    `undated_count` is not decoration. Most entities in a real graph are not
    events, so a timeline is a view of a minority of the corpus by nature, and
    one showing forty bars with no denominator reads as "this project contains
    forty things". Same guarantee `truncated` gives on `graph_view`: data
    missing from a drawing is invisible precisely because it is missing.
    """
    return {
        "bands": [band_view(band) for band in timeline.bands],
        "undated_count": timeline.undated_count,
        "truncated": timeline.truncated,
    }
