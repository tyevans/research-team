"""Choosing what backs the graph, and what backs the vectors.

In-memory by default and rebuilt from the log at project open, so the default
install needs no server -- and the rebuild path a Neo4j deployment would need
is the same one used at every startup, exercised continuously rather than
written under duress during a migration.

The vector store is the same shape and now the same default -- `memory`, since
#90, because the third scoring feature is what lets a cross-document duplicate
merge on evidence instead of an overridden threshold. It was `none` when this
module was written and this paragraph said so for one release longer than it
was true. See `config.vector_store` for what it costs.

The two differ in one way that matters to a caller: **`memory` is not the
graph's `memory`.** A graph store lost with the process is rebuilt from the log
at project open, so it costs a fold. A vector store lost with the process is
*gone*: this project never appends `EntitiesEmbedded`, so there is nothing for
a replay to fold, and consolidation silently drops to two features for every
entity extracted before the restart. `pgvector` is currently the only setting
under which an embedding outlives the process.
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


async def build_vector_store(kind: str, *, dimension: int) -> VectorStore | None:
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

    **`async`, and that is `PgVectorStore.connect`'s doing rather than a
    preference.** It is a coroutine -- unlike `Neo4jGraphStore.connect`, which
    is an ordinary method building a lazy driver -- and it `await`s
    `asyncpg.create_pool`, which opens `min_size` connections before it
    returns. So the two adapters differ in both respects a caller cares about:
    this one has to be awaited, and it reaches the server here rather than at
    first use. An unreachable database is therefore refused *at this call*,
    which is the better of the two behaviours and worth having said, because
    the previous comment here claimed the opposite of both halves and the
    function was `def`: it returned the un-awaited coroutine, and
    `AGENT_VECTOR_STORE=pgvector` handed a coroutine object to everything
    downstream that expected a store.

    The table does **not** need to exist first. `PgVectorStore.ensure_schema`
    issues `CREATE EXTENSION IF NOT EXISTS vector` along with the DDL, so a
    database whose role may create extensions needs no init script -- but
    something has to call it, and that is `ProjectGraphs`. redstring still
    fixes the width at DDL time, so changing the embedding model means a new
    table rather than an altered one; `ensure_schema` raises
    `DimensionMismatchError` rather than letting the mismatch reach a write.
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
        return await PgVectorStore.connect(config.pgvector_dsn(), dimension=dimension)
    raise ValueError(
        f"unknown AGENT_VECTOR_STORE {kind!r}; expected 'none', 'memory' or 'pgvector'"
    )
