"""Choosing what backs the graph.

In-memory by default and rebuilt from the log at project open, so the default
install needs no server -- and the rebuild path a Neo4j deployment would need
is the same one used at every startup, exercised continuously rather than
written under duress during a migration.
"""

from redstring import GraphStore, InMemoryGraphStore
from redstring.graph.adapters.neo4j import Neo4jGraphStore

from research_team.infrastructure import config


def build_graph_store(kind: str) -> GraphStore:
    """The graph store named by `kind`.

    Raises `ValueError` naming the unknown kind rather than falling back to
    memory: a deployment that asked for Neo4j and silently got a store that
    empties on restart is worse off than one that refused to start.

    `Neo4jGraphStore.connect` builds a driver but does not talk to the server;
    the first query does. Reachability is therefore established at project
    open, by `ensure_schema`, which is where a connection failure can still
    stop the process rather than surfacing mid-turn.
    """
    if kind == "memory":
        return InMemoryGraphStore()
    if kind == "neo4j":
        return Neo4jGraphStore.connect(
            config.neo4j_uri(),
            auth=config.neo4j_auth(),
            database=config.neo4j_database(),
        )
    raise ValueError(f"unknown AGENT_GRAPH_STORE {kind!r}; expected 'memory' or 'neo4j'")
