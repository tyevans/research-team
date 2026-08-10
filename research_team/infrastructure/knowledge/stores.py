"""Choosing what backs the graph, and what backs the vectors.

In-memory by default and rebuilt from the log at project open, so the default
install needs no server -- and the rebuild path a Neo4j deployment would need
is the same one used at every startup, exercised continuously rather than
written under duress during a migration.

The vector store is the same shape with one deliberate difference: its default
is `none` rather than `memory`, because holding it costs a model call per
entity on every ingest rather than nothing. See `config.vector_store`.
"""

from redstring import GraphStore, InMemoryGraphStore, InMemoryVectorStore, VectorStore
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


def build_vector_store(kind: str, *, dimension: int) -> VectorStore | None:
    """The vector store named by `kind`, or None when `kind` is `none`.

    **`None` rather than an empty store**, and the difference is not cosmetic.
    `CandidateFinder` handed an empty `InMemoryVectorStore` reads the subject's
    vector, finds nothing, and drops the embedding feature -- the same score it
    would compute with no store, reached after a lookup per subject and while
    holding a connection. `None` is the value that says the feature is off, and
    it is what the caller checks to decide whether to build an embedding
    provider at all.

    `dimension` is passed rather than read from config so this stays a function
    of its arguments: the caller has already read it once to build the provider,
    and reading it twice is how the two come to disagree.

    `PgVectorStore.connect` builds a pool without talking to the server, the
    same way `Neo4jGraphStore.connect` does -- so an unreachable database
    surfaces at the first write rather than here. The table must already exist
    with a `vector(dimension)` column; redstring fixes the width at DDL time
    and changing the embedding model means a new table, not an altered one.
    """
    if kind == "none":
        return None
    if kind == "memory":
        return InMemoryVectorStore(dimension=dimension)
    if kind == "pgvector":
        from redstring.vector.adapters.pgvector import PgVectorStore

        # Imported here rather than at module scope: it needs `redstring[pgvector]`
        # and its `asyncpg`, and a default install that never asks for pgvector
        # must not fail to import this module over a dependency it does not use.
        # `Neo4jGraphStore` is imported at the top because `redstring[neo4j]` is
        # pinned unconditionally; pgvector is not.
        return PgVectorStore.connect(config.pgvector_dsn(), dimension=dimension)
    raise ValueError(
        f"unknown AGENT_VECTOR_STORE {kind!r}; expected 'none', 'memory' or 'pgvector'"
    )
