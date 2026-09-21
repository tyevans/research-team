"""The declared settings for the research team domain.

Decomposes settings.py by separating setting definitions and specs into
settings_registry.py.
"""

from __future__ import annotations

import research_team.settings.domain as _settings
from research_team.settings.domain.spec import (
    Scope,
    SettingSpec,
    SettingType,
    _spec,
)

__all__ = ["SETTINGS", "_DEPLOYMENT"]

#: Deployment-wide, and deliberately not per-project or per-user. Anything
#: scoped this way is read before a request exists, or names a shared backing
#: service, so a per-project answer is either meaningless or a way for one
#: project to move everyone's data.
_DEPLOYMENT = (Scope.TENANT,)


SETTINGS: tuple[SettingSpec, ...] = (
    # --- models and endpoints ---------------------------------------------
    _spec(
        "AGENT_MODEL",
        SettingType.STRING,
        "qwen3.6-27b-mtp",
        "Chat model",
        "The model the research agent talks to.",
        "Models",
    ),
    _spec(
        "AGENT_BASE_URL",
        SettingType.STRING,
        "http://localhost:8080/v1/",
        "Base URL",
        "An OpenAI-compatible endpoint. See the provider catalogue for shapes.",
        "Models",
    ),
    _spec(
        "AGENT_API_KEY",
        SettingType.STRING,
        "not-needed",
        "API key",
        "Credential for the chat endpoint. Stored encrypted; never read back.",
        "Models",
        secret=True,
    ),
    _spec(
        "AGENT_CURATION_MODEL",
        SettingType.STRING,
        None,
        "Curation model",
        "Runs the media-curation chain. Falls back to the chat model when unset.",
        "Models",
    ),
    _spec(
        "AGENT_EXTRACTION_MODEL",
        SettingType.STRING,
        None,
        "Extraction model",
        "Runs knowledge extraction. Falls back to the chat model when unset.",
        "Models",
    ),
    _spec(
        "AGENT_VISION_MODEL",
        SettingType.STRING,
        None,
        "Vision model",
        "Describes frames and images. Unset means no vision at all.",
        "Models",
    ),
    # **The pair below is deployment-scoped because a vector store is shared,
    # not because embeddings are uninteresting per project.** A `VectorStore`'s
    # width is fixed at construction -- at DDL time for pgvector -- and every
    # project in the process writes into the same one. Two projects resolving
    # different widths does not give each its own store; it raises
    # `DimensionMismatchError` on the first write, which is a *poison event*
    # (`redstring_adapter.py`, `rebuild.py`): the ingest stops and replaying the
    # log stops with it. And the two move together -- `config.embedding_model`'s
    # docstring says set both or neither -- so scoping them apart would let a
    # project change the model and inherit the tenant's width.
    #
    # They were declared at the default (every scope) until 2026-08-29, which
    # rendered editable controls for both on a project page while every reader
    # in the tree is `config.embedding_model()` / `config.embedding_dimension()`
    # -- process-wide, scope-blind. A user could set a value, see it stored, see
    # it resolve, and watch nothing use it.
    _spec(
        "AGENT_EMBEDDING_MODEL",
        SettingType.STRING,
        "nomic-embed-text",
        "Embedding model",
        "Turns text into vectors. Not the chat model -- see its reader's docstring.",
        "Embeddings",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_EMBEDDING_DIMENSION",
        SettingType.INTEGER,
        768,
        "Embedding dimension",
        "This model's vector width. A property of the model, not a taste.",
        "Embeddings",
        minimum=1,
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_EMBEDDING_BASE_URL",
        SettingType.STRING,
        None,
        "Embedding base URL",
        "Where embedding requests go. Falls back to the chat endpoint.",
        "Embeddings",
    ),
    _spec(
        "AGENT_EMBEDDING_API_KEY",
        SettingType.STRING,
        None,
        "Embedding API key",
        "Credential for the embedding endpoint. Falls back to the chat key.",
        "Embeddings",
        secret=True,
    ),
    _spec(
        "AGENT_TRANSCRIBER_URL",
        SettingType.STRING,
        None,
        "Transcriber URL",
        "A whisper.cpp server. Unset means audio is perceived without speech.",
        "Perception",
    ),
    _spec(
        "AGENT_TRANSCRIBER_MODEL",
        SettingType.STRING,
        None,
        "Transcriber model",
        "The ASR revision. Part of the capability fingerprint, so it has no default.",
        "Perception",
        required_when="a transcriber URL is set",
    ),
    # --- context management ------------------------------------------------
    _spec(
        "AGENT_CONTEXT",
        SettingType.ENUM,
        "full",
        "Context mode",
        "How a conversation that outgrows the window is managed.",
        "Context",
        choices=("full", "elide", "compact", "delegate"),
    ),
    _spec(
        "AGENT_CONTEXT_TRIGGER",
        SettingType.INTEGER,
        120_000,
        "Compaction trigger",
        "Approximate tokens of conversation `compact` tolerates before summarising.",
        "Context",
        minimum=1,
    ),
    _spec(
        "AGENT_CONTEXT_KEEP_MESSAGES",
        SettingType.INTEGER,
        20,
        "Messages kept",
        "How many recent messages `compact` leaves out of the summary.",
        "Context",
        minimum=0,
    ),
    _spec(
        "AGENT_CONTEXT_KEEP_RESULTS",
        SettingType.INTEGER,
        6,
        "Tool results kept",
        "How many recent tool results `elide` leaves whole.",
        "Context",
        minimum=0,
    ),
    _spec(
        "AGENT_CONTEXT_CLEAR_OVER",
        SettingType.INTEGER,
        2_000,
        "Clear results over",
        "How long an older tool result may be before `elide` replaces it outright.",
        "Context",
        minimum=1,
    ),
    _spec(
        "AGENT_AUTHORING_ROUNDS",
        SettingType.INTEGER,
        6,
        "Authoring research budget",
        "Model calls a course-authoring turn may make before its graph, corpus "
        "and web tools are withdrawn. 0 turns the bound off.",
        "Context",
        # `minimum=0` and no maximum, and both halves are claims with a caller
        # behind them. 0 is the documented off switch, so it must be accepted;
        # 1 would refuse the one value the README tells a person to write. And
        # there is no ceiling because none is knowable -- the default of 6 came
        # from three live runs against one corpus and one model, and a bound
        # written here would refuse a larger corpus on no evidence at all.
        minimum=0,
    ),
    # --- knowledge and extraction ------------------------------------------
    _spec(
        "AGENT_KNOWLEDGE_DOMAIN",
        SettingType.STRING,
        "research_corpus",
        "Knowledge schema",
        "This project's schema id, a redstring one, or `auto` to classify per document.",
        "Extraction",
    ),
    _spec(
        "AGENT_EXTRACTION_CONCURRENCY",
        SettingType.INTEGER,
        8,
        "Extraction concurrency",
        "Extraction calls in flight per document. Lower it against a quota'd endpoint.",
        "Extraction",
        minimum=1,
    ),
    _spec(
        "AGENT_EXTRACTION_CHUNK_SIZE",
        SettingType.INTEGER,
        2_000,
        "Extraction chunk size",
        "Characters per chunk. Smaller extracts more and costs consolidation calls.",
        "Extraction",
        minimum=200,
    ),
    _spec(
        "AGENT_EXTRACTION_THINKING",
        SettingType.BOOLEAN,
        False,
        "Extraction thinking",
        "Let the extraction model reason first. Off: measured worse precision, 5x slower.",
        "Extraction",
    ),
    _spec(
        "AGENT_CONSOLIDATION_BATCH",
        SettingType.INTEGER,
        25,
        "Consolidation batch",
        "Entities decided together in one consolidation pass.",
        "Extraction",
        minimum=1,
    ),
    _spec(
        "AGENT_CATALOG_SWEEP_CONCURRENCY",
        SettingType.INTEGER,
        1,
        "Catalog sweep concurrency",
        "Candidates a blurb or art sweep works on at once. 1 bought all that was measurable.",
        "Extraction",
        minimum=1,
    ),
    # --- stores --------------------------------------------------------------
    _spec(
        "AGENT_GRAPH_STORE",
        SettingType.ENUM,
        "memory",
        "Graph store",
        "What backs the knowledge graph.",
        "Stores",
        choices=("memory", "neo4j"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_VECTOR_STORE",
        SettingType.ENUM,
        "memory",
        "Vector store",
        "What backs entity embeddings. `none` drops consolidation's third feature.",
        "Stores",
        choices=("none", "memory", "pgvector"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_CHUNK_STORE",
        SettingType.ENUM,
        "memory",
        "Chunk store",
        "What backs the document-chunk corpus.",
        "Stores",
        choices=("none", "memory", "postgres"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_PGVECTOR_DSN",
        SettingType.STRING,
        None,
        "pgvector DSN",
        "Where the vectors live. No default: a silent localhost connection writes "
        "to somebody's development database.",
        "Stores",
        scopes=_DEPLOYMENT,
        secret=True,
        required_when="the vector store is pgvector",
    ),
    _spec(
        "AGENT_NEO4J_URI",
        SettingType.STRING,
        "bolt://localhost:7687",
        "Neo4j URI",
        "The bolt endpoint.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_NEO4J_USER",
        SettingType.STRING,
        "neo4j",
        "Neo4j user",
        "The account to connect as.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_NEO4J_PASSWORD",
        SettingType.STRING,
        None,
        "Neo4j password",
        "No default. A store that comes up on `neo4j/neo4j` connects to somebody's server.",
        "Stores",
        scopes=_DEPLOYMENT,
        secret=True,
        required_when="the graph store is neo4j",
    ),
    _spec(
        "AGENT_NEO4J_DATABASE",
        SettingType.STRING,
        None,
        "Neo4j database",
        "Which database within the server. Unset means the server's own default.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    # --- authorization --------------------------------------------------------
    _spec(
        "AGENT_AUTH",
        SettingType.ENUM,
        "off",
        "Authorization",
        "Whether permissions are enforced. `off` wires a permissive checker -- "
        "a real one, so every route runs the same resolution path -- and is what "
        "a single-user local install runs.",
        "Authorization",
        choices=("off", "on"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_ADMIN_SUBJECTS",
        SettingType.STRING,
        "",
        "Instance admins",
        "Comma-separated Zitadel subjects holding `instance.admin`: the rebuild "
        "and worker routes, which act across every tenant. Deployment scope only "
        "-- a tenant that could name its own instance admins could rebuild "
        "everyone else's corpus.",
        "Authorization",
        scopes=_DEPLOYMENT,
    ),
    # --- search ---------------------------------------------------------------
    _spec(
        "AGENT_SEARXNG_URL",
        SettingType.STRING,
        None,
        "SearXNG URL",
        "Unset means the agent gets no network tool at all.",
        "Search",
    ),
    _spec(
        "AGENT_SEARXNG_RESULTS",
        SettingType.INTEGER,
        5,
        "SearXNG results",
        "How many results reach the model. Capped because context is the cost.",
        "Search",
        minimum=1,
    ),
    # --- perception and media -------------------------------------------------
    _spec(
        "AGENT_PERCEPTION_MAX_CHARS",
        SettingType.INTEGER,
        500_000,
        "Perception budget",
        "Characters of derived text. Equal to the document cap, deliberately.",
        "Perception",
        minimum=1,
    ),
    _spec(
        "AGENT_MEDIA_RECONCILE_INTERVAL",
        SettingType.NUMBER,
        300.0,
        "Media reconcile interval",
        "Seconds between sweeps for proposals stuck at `accepted`.",
        "Media",
        scopes=_DEPLOYMENT,
        # Not `1`. A whole-second floor was invented while writing this
        # declaration and it refused a value the suite has always used:
        # `test_accept_reconciliation_sweep` drives the interval down to
        # hundredths so a sweep it is waiting on happens inside a test rather
        # than five minutes later, and the whole file went red on CI. The
        # floor that is real is "not zero and not negative", because a
        # non-positive interval is a sweep loop with no sleep in it.
        minimum=0.001,
    ),
    _spec(
        "AGENT_BLOB_SWEEP_GRACE",
        SettingType.NUMBER,
        86_400.0,
        "Blob sweep grace",
        "How long an unreferenced blob must sit before the sweep may delete it.",
        "Media",
        scopes=_DEPLOYMENT,
        # Zero is meaningful here and a floor of `1` would forbid it: it means
        # "delete anything unreferenced now", which is what a test asserting
        # the sweep deletes at all has to say. The reader's own docstring
        # argues at length for the 86,400 default; that argument is about the
        # default, not about what the type permits.
        minimum=0,
    ),
    # --- observability ---------------------------------------------------------
    _spec(
        "AGENT_TRACING",
        SettingType.BOOLEAN,
        False,
        "Tracing",
        "Export OTLP traces. Off unless something is collecting them.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_OTLP_ENDPOINT",
        SettingType.STRING,
        "http://localhost:4318/v1/traces",
        "OTLP endpoint",
        "Where traces are sent.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_SERVICE_NAME",
        SettingType.STRING,
        "research-team",
        "Service name",
        "What this process calls itself in a trace.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_INTERACTION_LOG",
        SettingType.BOOLEAN,
        True,
        "Interaction log",
        "Record what the user did in the console. The one default-on switch here.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
)


if not getattr(_settings, "SETTINGS", None) and SETTINGS:
    _settings.SETTINGS = SETTINGS
    if hasattr(_settings, "BY_KEY"):
        _settings.BY_KEY.update({spec.key: spec for spec in SETTINGS})
    if hasattr(_settings, "BY_ENV"):
        _settings.BY_ENV.update({spec.env_var: spec for spec in SETTINGS})
