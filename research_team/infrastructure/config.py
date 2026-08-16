"""Everything the process reads from its environment, in one place.

Kept at the edge on purpose: no layer below this one asks the environment
anything, so tests configure the application by passing arguments rather than
by setting variables.
"""

import os
from pathlib import Path

DEFAULT_MODEL = "qwen3.6-27b-mtp"
DEFAULT_BASE_URL = "http://localhost:8080/v1/"
DEFAULT_API_KEY = "not-needed"

CONTEXT_MODES = ("full", "elide", "compact", "delegate")
DEFAULT_CONTEXT_MODE = "full"

DEFAULT_CONTEXT_TRIGGER_TOKENS = 120_000
DEFAULT_CONTEXT_KEEP_MESSAGES = 20
DEFAULT_CONTEXT_KEEP_RESULTS = 6
DEFAULT_CONTEXT_CLEAR_OVER_CHARS = 2_000

DEFAULT_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
DEFAULT_SERVICE_NAME = "research-team"

DEFAULT_SEARXNG_RESULTS = 5

DEFAULT_GRAPH_STORE = "memory"
#: `research_corpus`, not `auto`. See `knowledge_domain` for the trade, and
#: the schema's own YAML for the measurement that motivated it.
DEFAULT_KNOWLEDGE_DOMAIN = "research_corpus"

#: Chosen together, and neither means much alone -- see `extraction_chunk_size`
#: for why the pair is the unit. 8 matches the slot count of the local server
#: `DEFAULT_BASE_URL` points at; 2000 is below redstring's own 3000 default,
#: which is affordable only because the calls now overlap.
DEFAULT_EXTRACTION_CONCURRENCY = 8
DEFAULT_EXTRACTION_CHUNK_SIZE = 2_000

VECTOR_STORES = ("none", "memory", "pgvector")
#: On, since the third scoring feature is what lets consolidation merge a
#: cross-document duplicate on evidence rather than on an overridden threshold.
#: See `vector_store` for what it costs and how it degrades.
DEFAULT_VECTOR_STORE = "memory"

#: Named alongside `postgres` even though `build_chunk_store` refuses that
#: branch -- see its docstring -- so an operator who sets it sees a real,
#: unwired setting rather than a typo.
CHUNK_STORES = ("none", "memory", "postgres")
#: On by default, because `memory` here is the graph's `memory`: chunks are
#: rebuilt from `DocumentChunked` at project open, so the cost of the default
#: is a fold proportional to corpus size, paid once per open, not lost data.
DEFAULT_CHUNK_STORE = "memory"

#: A widely-served local embedding model, and the width it returns. Defaults
#: exist for these two *because* the store now defaults to on: a default-on
#: feature whose required variables have no defaults does not start. Both are
#: overridden together or not at all -- see `embedding_dimension`.
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_DIMENSION = 768

DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USER = "neo4j"

#: The `Budget` handed to `readeverything.represent`, deliberately equal to
#: `MAX_DOCUMENT_CHARS` in `application/knowledge.py` -- derived text lands in
#: `corpus_documents` and is extracted like any other document, so a second
#: ceiling would be a second answer to one question. Defined here rather than
#: imported from there: `application/` sits above `infrastructure/config.py`
#: in the direction this module's own docstring names as the edge nothing
#: below asks the environment anything, and importing upward would invert it.
#: The two constants must be changed together -- drift makes a transcript
#: truncate at a different length than a document, which is visible rather
#: than silent, but still a bug.
DEFAULT_PERCEPTION_MAX_CHARS = 200_000


def default_db_path() -> str:
    """Where sessions live. Sessions persist across runs and are resumable."""
    configured = os.getenv("AGENT_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "sessions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def blob_root() -> Path:
    """Where media bytes live: beside the database, not inside it.

    SQLite would hold them -- it has a BLOB type and a 1GB row ceiling -- and
    the reason not to is streaming. Serving a range request out of a BLOB means
    reading it into memory to slice it; a file supports `seek`. The cost is
    that a backup now has two things to copy, which is written on the
    `/rebuild` page rather than being left for someone to discover.

    `AGENT_BLOB_ROOT` overrides it for the reason `AGENT_DB` overrides the
    database path, and it became load-bearing the moment a route could write
    here: `tests/conftest.py`'s `isolate_database` points both at `tmp_path`,
    and without this half every media upload in the suite would deposit real
    bytes in the developer's own `~/.research-team/blobs` and never remove
    them. Nothing in the suite would fail -- that is what makes it worth an
    environment variable rather than a note.
    """
    configured = os.getenv("AGENT_BLOB_ROOT")
    path = Path(configured) if configured else Path.home() / ".research-team" / "blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_name() -> str:
    return os.getenv("AGENT_MODEL", DEFAULT_MODEL)


def base_url() -> str:
    return os.getenv("AGENT_BASE_URL", DEFAULT_BASE_URL)


def api_key() -> str:
    return os.getenv("AGENT_API_KEY", DEFAULT_API_KEY)


def web_host() -> str:
    return os.getenv("AGENT_WEB_HOST", "127.0.0.1")


def web_port() -> int:
    return int(os.getenv("AGENT_WEB_PORT", "8000"))


def context_mode() -> str:
    """How this instance manages a conversation that outgrows the window.

    One instance, one mode: the choice shapes what every session on it sends
    to the model, and mixing them within a process would make "why did this
    turn see that?" unanswerable.
    """
    configured = os.getenv("AGENT_CONTEXT", DEFAULT_CONTEXT_MODE).strip().lower()
    if configured not in CONTEXT_MODES:
        raise ValueError(
            f"AGENT_CONTEXT={configured!r} is not one of {', '.join(CONTEXT_MODES)}"
        )
    return configured


def context_trigger_tokens() -> int:
    """How much conversation `compact` tolerates before summarizing.

    Approximate tokens, not characters: the threshold has to mean something
    against a model's window, and every published trigger is quoted in tokens.
    """
    return int(os.getenv("AGENT_CONTEXT_TRIGGER", DEFAULT_CONTEXT_TRIGGER_TOKENS))


def context_keep_messages() -> int:
    """How many recent messages `compact` leaves out of the summary.

    Separate from the tool-result count below because they are different
    quantities: six messages might be one exchange or six, while six tool
    results is six tool results. LangChain's summarizer keeps twenty by
    default, and a thin tail is where summarization does most of its damage --
    recent detail is what the agent is actively using.
    """
    return int(os.getenv("AGENT_CONTEXT_KEEP_MESSAGES", DEFAULT_CONTEXT_KEEP_MESSAGES))


def context_keep_results() -> int:
    """How many recent tool results `elide` leaves whole.

    Counted in results rather than messages so the retained volume does not
    swing with the shape of the conversation; Anthropic's tool-result clearing
    counts the same way.
    """
    return int(os.getenv("AGENT_CONTEXT_KEEP_RESULTS", DEFAULT_CONTEXT_KEEP_RESULTS))


def context_clear_over_chars() -> int:
    """How long an older tool result may be before `elide` clears it.

    Not a truncation length -- a result over this size is replaced outright,
    because a partial result reads as a whole one.
    """
    return int(os.getenv("AGENT_CONTEXT_CLEAR_OVER", DEFAULT_CONTEXT_CLEAR_OVER_CHARS))


def tracing_enabled() -> bool:
    """Whether this process should export traces. Off unless asked.

    Opt-in rather than opt-out because tracing is only useful if something is
    collecting it, and a developer running this locally has nothing listening.
    """
    return os.getenv("AGENT_TRACING", "").strip().lower() in {"1", "true", "yes", "on"}


def otlp_endpoint() -> str:
    """Where traces are sent. The OTLP/HTTP default collector address."""
    return os.getenv("AGENT_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)


def tracing_service_name() -> str:
    """What this process calls itself in a trace."""
    return os.getenv("AGENT_SERVICE_NAME", DEFAULT_SERVICE_NAME)


def searxng_url() -> str | None:
    """The SearXNG instance to search, or None if this install has no search.

    Unset is the default and means the agent gets no network tool at all --
    which is what keeps the sandbox claim true for anyone who has not opted in.
    """
    configured = os.getenv("AGENT_SEARXNG_URL", "").strip()
    return configured.rstrip("/") or None


def searxng_results() -> int:
    """How many results reach the model. Capped because context is the cost."""
    return int(os.getenv("AGENT_SEARXNG_RESULTS", str(DEFAULT_SEARXNG_RESULTS)))


def research_run_over_http() -> bool:
    """Whether the web UI may start an autonomous run. Off unless asked.

    The one switch in front of the loop, and it is configuration rather than a
    gate for the reason `AGENT_SEARXNG_URL` is: "unset means the route is not
    there" is a stronger promise than any check inside a route that exists.

    Off by default because of what the run is and where the port is. There is
    no authentication on any route (BACKLOG B18), and this is the only one that
    would spend an hour of model time on behalf of whoever called it -- every
    other route reads the log or runs one turn somebody is waiting on. The REPL
    has no equivalent switch and needs none: somebody is at the terminal, which
    is the property this variable is standing in for.
    """
    return os.getenv("AGENT_RESEARCH_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def graph_store() -> str:
    """What backs the knowledge graph. `memory` needs no server."""
    return os.getenv("AGENT_GRAPH_STORE", DEFAULT_GRAPH_STORE)


def knowledge_domain() -> str:
    """This project's own schema id, a redstring one, or `auto` to classify.

    Defaults to `research_corpus`, which this project ships -- see
    `infrastructure/knowledge/schemas/research_corpus.yaml` for why it exists
    at all. The short version: no redstring schema asks the model to fill
    `temporal_expression`, so with any of them the timeline draws nothing.

    **The default gives up per-document classification**, which `auto` did and
    which cost one model call per document. That is the deliberate trade: this
    project's corpus is one subject at a time, so a schema chosen once fits it
    better than a classifier whose low-confidence fallback was
    `encyclopedia_wiki` -- the schema whose `date` entity type is half of the
    bug. Set `AGENT_KNOWLEDGE_DOMAIN=auto` to get the old behaviour back.
    """
    return os.getenv("AGENT_KNOWLEDGE_DOMAIN", DEFAULT_KNOWLEDGE_DOMAIN)


def extraction_concurrency() -> int:
    """How many extraction calls may be in flight per document. 8 by default.

    redstring builds one `CallLimiter` per `build_graph` from this, shared
    across classification, extraction, gleaning and embedding, so the ceiling
    is per *document* and not per process. **Two documents ingested at once
    are two ceilings**, and `_store_document` says two `remember` calls in one
    assistant message do run concurrently -- so the real bound against the
    server is this times the number of overlapping ingests. `build_graph`
    constructs its own limiter and accepts no injected one, so a single
    process-wide ceiling is not reachable without dropping to
    `ExtractionPipeline` and reimplementing what `build_graph` does around it.
    Not judged worth it; the number to raise if the server starts queueing is
    this one, downward.

    8 because `DEFAULT_BASE_URL` is a local server with 8 slots -- the same
    server redstring's own measurement was taken against, this being the same
    author's library on the same hardware. Against a hosted endpoint with a
    request-per-minute quota this is the wrong shape of limit entirely and
    wants lowering.

    Raising it past a document's chunk count does nothing: what runs at once
    is `min(concurrency, chunks in the batch)`, and the chunk count is not
    `len(text) / chunk_size` -- overlap makes it larger.
    """
    return int(os.getenv("AGENT_EXTRACTION_CONCURRENCY", str(DEFAULT_EXTRACTION_CONCURRENCY)))


def extraction_chunk_size() -> int:
    """Characters per extraction chunk. 2000 by default, against redstring's 3000.

    This is the half of the concurrency change that actually buys something,
    and it only became affordable because of the other half. Upstream measured
    332.7s to 166.4s on a 33k-character document, and reports the gain is
    mostly *not* the overlapping calls -- it is that overlapping calls make
    smaller chunks cheap, and smaller chunks extract more (329 entities and
    384 relationships against 209 and 276). Serially, halving the chunk size
    roughly doubles the wall clock; concurrently it is close to free.

    Those numbers transfer further than a third party's would: redstring is
    this project's own library, measured on this hardware against comparable
    content. What does not transfer is the *pipeline they were taken through*.
    `build_graph` is where that measurement stops, and this adapter runs a
    consolidation pass after it that redstring's benchmark never paid for --
    with `adjudicate` defaulting to True and embeddings on, every
    cross-document duplicate costs one adjudicator call (see the note above
    `_CountingProvider` in `redstring_adapter.py`, which pins that at 0.8
    against `HIGH_SIMILARITY` 0.92).

    That is the direction to watch, because smaller chunks push on it: an
    entity named once per chunk across more chunks is more mentions, more
    candidate pairs, and more adjudicator calls. Extraction gets faster and
    finds more while consolidation gets more expensive, and only the first
    half of that is in the 332.7s-to-166.4s figure. Upstream warns separately
    that below some size extraction stops finding more and starts
    manufacturing duplicate identities outright; 2000 is above where that was
    seen. **What has not been measured is the whole-ingest cost through this
    adapter** -- `docs/how-to/tune-ingestion-throughput.md` in redstring is
    the method, and the number to watch here is adjudicator calls per
    document, not wall clock alone.

    Overlap is left at redstring's 200 deliberately: it is what keeps an
    entity spanning a chunk boundary from being lost, and it does not scale
    with chunk size on its own.
    """
    return int(os.getenv("AGENT_EXTRACTION_CHUNK_SIZE", str(DEFAULT_EXTRACTION_CHUNK_SIZE)))


def extraction_thinking() -> bool:
    """Whether the extraction model may reason before it answers. Off by default.

    Off is redstring's own measured default (see `NO_THINKING` in
    `redstring.llm.adapters.langchain`): on one graded corpus, thinking on
    against thinking off was 155.1s against 27.3s of wall clock, 9 entity
    false positives against 3 and 11 relationship false positives against 6,
    with recall unchanged. Extraction asks what the text *states*, and a model
    given room to deliberate spends it inferring -- every inference grades as
    a false positive.

    The cost of the default is that it is sent as `chat_template_kwargs`,
    which only a server rendering the model's own chat template understands.
    A backend without one -- OpenAI's hosted API is the case to expect -- will
    reject the field with a 400 on the very first extraction call. Set
    `AGENT_EXTRACTION_THINKING=1` there. This defaults to off anyway because
    `base_url` points at a local OpenAI-compatible server, and the failure is
    a loud 400 rather than a silent degradation.

    Only extraction is affected. Whether the conversational agent should
    reason is a separate question that nobody has measured.
    """
    return os.getenv("AGENT_EXTRACTION_THINKING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def vector_store() -> str:
    """What backs entity embeddings. `none` switches the feature off.

    Mirrors `AGENT_GRAPH_STORE`'s shape -- same naming, same named-and-refused
    error -- and now its default too.

    **On, because the third scoring feature is the difference between merging a
    cross-document duplicate and dropping it.** Measured on the `#84` fixture
    through a real `CandidateFinder`: two features score an identically-named
    pair 0.7143, below redstring's `LOW_SIMILARITY` of 0.75, so it is dropped
    before the adjudicator is offered it. Three features score it 0.8000 and it
    clears 0.75 on its own evidence -- which is what let `low=EXACT_NAME_SCORE`
    be deleted rather than merely narrowed.

    **What it does not buy is discrimination.** redstring embeds `entity.name`
    and nothing else, so the embedding feature is a blurrier second measurement
    of the string the name feature already measured, and it moves near-misses
    in step with true duplicates. Under a real model the exact duplicate and
    `University of York` / `University of Cork` land about 0.011 apart. The
    gain is that 0.75 is defensible; the cost is more traffic in the
    adjudication band.

    **What it costs to run.** One embedding call per extracted entity, batched
    into one request per document, paid again on re-ingest -- `build_graph`
    builds a fresh aggregate per call and re-embeds rather than suppressing a
    repeat. And auto-merge stays out of reach: a perfect name and a perfect
    embedding cap at 0.8 against `graph = 0.0`, below `HIGH_SIMILARITY` 0.92,
    so **every cross-document duplicate still costs one adjudicator call**.

    **What happens when the endpoint is not there.** `AGENT_BASE_URL` defaults
    to a local server which may serve only a chat model, so a default-on
    feature has to survive a 400. It does: the adapter probes the provider once
    and falls back to two-feature scoring with a loud log if the probe fails --
    see `RedstringKnowledge._embedding_pair`. Set `AGENT_VECTOR_STORE=none` to
    skip the probe entirely.

    Raises `ValueError` naming the unknown kind rather than falling back, for
    `build_graph_store`'s reason: a deployment that asked for pgvector and
    silently got none consolidates worse than it asked to and says nothing.
    """
    configured = os.getenv("AGENT_VECTOR_STORE", DEFAULT_VECTOR_STORE).strip().lower()
    if configured not in VECTOR_STORES:
        raise ValueError(
            f"AGENT_VECTOR_STORE={configured!r} is not one of {', '.join(VECTOR_STORES)}"
        )
    return configured


def chunk_store() -> str:
    """What backs the document-chunk corpus. `none` switches the feature off.

    Defaults on: `memory` is the graph's `memory`, not the vector store's --
    chunks come from `DocumentChunked`, so the store is rebuilt by folding the
    log at project open rather than lost with the process. What the default
    costs is that fold, proportional to corpus size, paid once per open.

    Raises `ValueError` naming the unknown kind rather than falling back, for
    `build_graph_store`'s reason. `postgres` is listed as valid here even
    though `build_chunk_store` refuses it -- see that function's docstring --
    so an operator who sets it is told it is a real, unwired setting rather
    than a typo.
    """
    configured = os.getenv("AGENT_CHUNK_STORE", DEFAULT_CHUNK_STORE).strip().lower()
    if configured not in CHUNK_STORES:
        raise ValueError(
            f"AGENT_CHUNK_STORE={configured!r} is not one of {', '.join(CHUNK_STORES)}"
        )
    return configured


def curation_model() -> str:
    """Which model runs the media-curation chain.

    **Not necessarily `AGENT_MODEL`, for `embedding_model`'s reason:** curation
    is a distinct role -- deciding what a topic needs seen or heard, phrasing
    a search term, judging a pool of results -- and pointing it at a name
    tuned for a different job is a decision, not a neutral default. Unlike
    `embedding_model`, this one *does* default to the chat model
    (`model_name()`) rather than raising or picking a guessed name of its
    own: curation's replies are read the way the agent's own JSON-shaped
    replies already are (see `MediaCurationTextPort`), so the chat model is a
    reasonable thing to point it at until there is a reason to want
    something else. The default is a convenience, not a claim that the two
    roles are the same thing -- an install that wants curation cheaper, or
    faster, or on a different endpoint entirely sets `AGENT_CURATION_MODEL`
    and the two stop moving together.
    """
    return os.getenv("AGENT_CURATION_MODEL", "").strip() or model_name()


def embeddings_enabled() -> bool:
    """Whether anything should embed. A convenience over `vector_store`, not a knob."""
    return vector_store() != "none"


def embedding_model() -> str:
    """Which model turns text into vectors.

    **Not `AGENT_MODEL`.** The chat model and the embedding model are different
    models, and pointing this at the chat one sends embedding requests to a
    name that answers chat. Most OpenAI-compatible servers answer that with a
    400; the dangerous ones answer with something vector-shaped and
    numerically meaningless, which would consolidate on noise and never once
    look broken. So this has its own variable even though it usually shares an
    endpoint with the chat model.

    It has a default only because `AGENT_VECTOR_STORE` now defaults to on, and
    a default-on feature whose required variables have no defaults does not
    start. `nomic-embed-text` is the guess -- widely served locally, and wrong
    for plenty of installs, which is why the probe in
    `RedstringKnowledge._embedding_pair` exists rather than a promise that this
    name resolves.
    """
    return os.getenv("AGENT_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL


def embedding_dimension() -> int:
    """How wide this model's vectors are. A property of the model, not a taste.

    A `VectorStore`'s width is fixed at construction -- at DDL time for
    pgvector -- and redstring refuses to wire a provider to a store whose
    number disagrees, before any text is embedded rather than after the call
    has been paid for.

    Defaulted alongside `AGENT_EMBEDDING_MODEL` and for the same reason, which
    makes the pair of them load-bearing together: **set both or neither.** 768
    is `nomic-embed-text`'s width, so overriding the model and leaving this
    alone produces a provider that declares one width and a server that returns
    another. The probe catches that too, and says which two numbers disagreed.

    Changing this against an existing store means a **new store**, not a
    widened one -- two models' vectors are not comparable even at equal
    dimension, so a store holding both ranks on nonsense.
    """
    configured = os.getenv("AGENT_EMBEDDING_DIMENSION", "").strip()
    return int(configured) if configured else DEFAULT_EMBEDDING_DIMENSION


def embedding_base_url() -> str:
    """Where embedding requests go. Defaults to the endpoint everything else uses.

    Separable because it often has to be: llama.cpp serves one model per
    process, so an install running a chat model locally serves embeddings from
    a second port, and a hosted embedding provider is a different host
    entirely. Reusing `AGENT_BASE_URL` is the right default and would be a
    wrong requirement.
    """
    configured = os.getenv("AGENT_EMBEDDING_BASE_URL", "").strip()
    return configured or base_url()


def embedding_api_key() -> str:
    """The key for the embedding endpoint. Falls back to the shared one."""
    return os.getenv("AGENT_EMBEDDING_API_KEY", "").strip() or api_key()


def pgvector_dsn() -> str:
    """Where the vectors live. Raises when unset.

    No default, for `neo4j_auth`'s reason: a store that silently comes up
    against `postgres://localhost/postgres` either fails confusingly or
    connects to somebody's development database and writes to it.
    """
    configured = os.getenv("AGENT_PGVECTOR_DSN", "").strip()
    if not configured:
        raise ValueError("AGENT_PGVECTOR_DSN must be set when AGENT_VECTOR_STORE=pgvector")
    return configured


def neo4j_uri() -> str:
    return os.getenv("AGENT_NEO4J_URI", DEFAULT_NEO4J_URI)


def neo4j_auth() -> tuple[str, str]:
    """User and password. Raises when the password is unset.

    No default password. A graph store that silently comes up on `neo4j/neo4j`
    is one that either fails confusingly or, worse, connects to somebody's
    development server.
    """
    password = os.getenv("AGENT_NEO4J_PASSWORD")
    if not password:
        raise ValueError("AGENT_NEO4J_PASSWORD must be set when AGENT_GRAPH_STORE=neo4j")
    return os.getenv("AGENT_NEO4J_USER", DEFAULT_NEO4J_USER), password


def neo4j_database() -> str | None:
    """Which database within the server. None means the server's default."""
    return os.getenv("AGENT_NEO4J_DATABASE") or None


def transcriber_url() -> str | None:
    """The whisper.cpp server to transcribe against, or None for no ASR.

    Unset is the default and means audio and video are perceived without
    speech -- a frame timeline and nothing said. That is a real, reportable
    degradation rather than an error, which is why this is a `None` and not a
    raise.
    """
    return os.getenv("AGENT_TRANSCRIBER_URL", "").strip().rstrip("/") or None


def transcriber_model() -> str:
    """What to call the ASR model. Required once a URL is set.

    No default, and the reason is not taste. The server reports no model name
    of its own (measured against whisper.cpp at `POST /inference` on
    2026-08-15), and this string is the ASR revision inside
    `CapabilitySet.fingerprint()` -- which is what invalidates every derived
    artifact when the model changes. A default would let a swapped model reuse
    the previous one's cache entries silently, and "silently" is the whole
    problem.
    """
    configured = os.getenv("AGENT_TRANSCRIBER_MODEL", "").strip()
    if not configured:
        raise ValueError("AGENT_TRANSCRIBER_MODEL must be set when AGENT_TRANSCRIBER_URL is")
    return configured


def vision_model() -> str | None:
    """The model that describes frames and images, or None for no vision.

    Speaks to `AGENT_BASE_URL` with `AGENT_API_KEY`, since
    `build_openai_vision_model` wants an OpenAI-compatible endpoint and the
    local server is one. Separate from `AGENT_MODEL` for
    `AGENT_EMBEDDING_MODEL`'s reason: a chat model and a vision model are
    different models, and pointing this at one that cannot see images fails
    per-request rather than at startup.
    """
    return os.getenv("AGENT_VISION_MODEL", "").strip() or None


def perception_max_chars() -> int:
    """The `Budget` handed to `represent`. The document cap, deliberately.

    The derived text *is* a document -- it lands in `corpus_documents` and is
    extracted like one -- so a second ceiling would be a second answer to one
    question, and the smaller of two answers would be the one that silently
    truncated a transcript.
    """
    configured = os.getenv("AGENT_PERCEPTION_MAX_CHARS", "").strip()
    return int(configured) if configured else DEFAULT_PERCEPTION_MAX_CHARS


def perception_root() -> Path:
    """Where `readeverything`'s artifact cache lives. Beside the blobs.

    Its own directory rather than inside `blob_root()`: the blob root is
    content-addressed and every name in it is a digest of its own contents, so
    a cache file sitting there would be the one entry for which that is untrue.
    """
    configured = os.getenv("AGENT_PERCEPTION_ROOT")
    path = Path(configured) if configured else Path.home() / ".research-team" / "perception"
    path.mkdir(parents=True, exist_ok=True)
    return path
