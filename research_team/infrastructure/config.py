"""Everything the process reads from its configuration, in one place.

Kept at the edge on purpose: no layer below this one asks the environment
anything, so tests configure the application by passing arguments rather than
by setting variables.

**These are readers over a resolved value now, not over `os.getenv`.** Each
function below asks `domain/settings.py` for its declaration and gets back the
environment variable's name, the built-in default, the type and the validation
in one object -- which is what makes a settings UI possible without a second,
hand-written description of the same forty knobs, and what
`test_every_environment_variable_config_reads_is_declared_or_excused` checks by
introspection over this module's own source.

What has *not* changed is which value wins here: this module resolves the
environment, then the built-in default, and nothing else. It has no scope to
resolve for -- a process has no project and no user -- so it reads the bottom
two layers of the chain and no more. `application/settings.SettingsResolver` is
the same walk with project, user and tenant on top of it, and the two agree
because the environment layer and the defaults are read from the one registry.

Three behaviours the move standardised, all of them previously spelled three
different ways in this file: an empty variable now reads as unset everywhere
(it already did in most readers), a boolean accepts exactly one set of words,
and an enum is lowercased and validated against its declared choices.
"""

import os
from pathlib import Path

from research_team.domain.settings import BY_KEY, SettingType


def _value(key: str) -> object | None:
    """The environment's answer for `key`, or the built-in default.

    Empty reads as unset rather than as an empty string. That is what
    `AGENT_TRACING=` has always meant, and what `AGENT_SEARXNG_URL="   "` has
    always meant, and it is now what every variable means -- an empty value in
    a `.env` file is a person clearing a setting, not asking for the empty
    string.
    """
    spec = BY_KEY[key]
    raw = os.getenv(spec.env_var)
    if raw is None or not raw.strip():
        return spec.default
    return spec.parse(raw)


def _text(key: str) -> str:
    """A setting that always has a value. `str()` rather than a cast because
    the declaration is what guarantees the default is not None, and a reader
    that quietly returned `"None"` would be worse than a type error."""
    value = _value(key)
    if value is None:
        raise ValueError(f"{BY_KEY[key].env_var} has no value and no default")
    return str(value)


def _optional(key: str) -> str | None:
    """A setting whose absence is a meaningful state -- no search tool, no
    vision, no transcriber."""
    value = _value(key)
    return None if value is None else str(value)


def _int(key: str) -> int:
    return int(_value(key))  # type: ignore[arg-type]


def _float(key: str) -> float:
    return float(_value(key))  # type: ignore[arg-type]


def _flag(key: str) -> bool:
    return bool(_value(key))


def _builtin(key: str) -> object:
    """The declared default, ignoring the environment entirely.

    The module constants below are *defaults*, not resolved values, and the
    distinction bites at import time: reading them through `_value` would make
    `DEFAULT_MODEL` become whatever `AGENT_MODEL` happened to say in the
    process that imported this module. `redstring_adapter` takes
    `DEFAULT_CONSOLIDATION_BATCH` as a fallback and `test_embedding_config`
    asserts `embedding_model() != model_name()` against `DEFAULT_EMBEDDING_MODEL`
    -- both would have been quietly wrong, and neither would have failed on a
    machine with a clean environment.
    """
    value = BY_KEY[key].default
    if value is None:
        raise ValueError(f"{BY_KEY[key].env_var} has no built-in default")
    return value


def _builtin_text(key: str) -> str:
    return str(_builtin(key))


def _builtin_int(key: str) -> int:
    return int(_builtin(key))  # type: ignore[arg-type]


def _builtin_float(key: str) -> float:
    return float(_builtin(key))  # type: ignore[arg-type]


def _choices(key: str) -> tuple[str, ...]:
    """A declared enum's options, for the module constants below.

    Derived rather than duplicated: `CONTEXT_MODES` and `VECTOR_STORES` are
    parametrised over by tests and named in error messages, and a second copy
    of either would be free to drift from the one the validation uses.
    """
    spec = BY_KEY[key]
    assert spec.type is SettingType.ENUM
    return spec.choices


# Every constant below is read out of the registry rather than written
# twice. They are kept as module names because other modules import them
# (`redstring_adapter` takes `DEFAULT_CONSOLIDATION_BATCH`, `composition`
# takes the reconcile interval) and because the tests that pin the documented
# numbers read them from here -- but the *value* now has exactly one home, so
# a default changed in `domain/settings.py` cannot leave a stale twin behind.
DEFAULT_MODEL = _builtin_text("model")
DEFAULT_BASE_URL = _builtin_text("base_url")
DEFAULT_API_KEY = _builtin_text("api_key")

CONTEXT_MODES = _choices("context")
DEFAULT_CONTEXT_MODE = _builtin_text("context")

DEFAULT_CONTEXT_TRIGGER_TOKENS = _builtin_int("context_trigger")
DEFAULT_CONTEXT_KEEP_MESSAGES = _builtin_int("context_keep_messages")
DEFAULT_CONTEXT_KEEP_RESULTS = _builtin_int("context_keep_results")
DEFAULT_CONTEXT_CLEAR_OVER_CHARS = _builtin_int("context_clear_over")

#: Model calls a parent authoring turn may make before its reading tools are
#: withdrawn. `infrastructure/agent/research_budget.py` imports this name
#: rather than repeating the number, and its module docstring carries the three
#: live runs that fixed it at 6. Read through `_builtin_int` like every
#: constant here, so the value has one home in `domain/settings.py`.
DEFAULT_AUTHORING_ROUNDS = _builtin_int("authoring_rounds")

DEFAULT_OTLP_ENDPOINT = _builtin_text("otlp_endpoint")
DEFAULT_SERVICE_NAME = _builtin_text("service_name")

DEFAULT_SEARXNG_RESULTS = _builtin_int("searxng_results")

DEFAULT_GRAPH_STORE = _builtin_text("graph_store")
#: `research_corpus`, not `auto`. See `knowledge_domain` for the trade, and
#: the schema's own YAML for the measurement that motivated it.
DEFAULT_KNOWLEDGE_DOMAIN = _builtin_text("knowledge_domain")

#: Chosen together, and neither means much alone -- see `extraction_chunk_size`
#: for why the pair is the unit. 8 matches the slot count of the local server
#: `DEFAULT_BASE_URL` points at; 2000 is below redstring's own 3000 default,
#: which is affordable only because the calls now overlap.
DEFAULT_EXTRACTION_CONCURRENCY = _builtin_int("extraction_concurrency")
DEFAULT_EXTRACTION_CHUNK_SIZE = _builtin_int("extraction_chunk_size")

#: How many extracted entities are decided together in one consolidation pass.
#: 25 rather than "all of them" -- see `consolidation_batch_size` for the two
#: costs that grow with it and why neither has been measured to a limit yet.
DEFAULT_CONSOLIDATION_BATCH = _builtin_int("consolidation_batch")

#: How many catalog candidates a blurb or art sweep has in flight at once.
#: 1, not because concurrency is unimplemented but because it was measured
#: to buy 1.1% on this endpoint. See `catalog_sweep_concurrency` for the curve.
DEFAULT_CATALOG_SWEEP_CONCURRENCY = _builtin_int("catalog_sweep_concurrency")

#: The one value of `AGENT_VECTOR_STORE` that means "do not embed". Named
#: because those comparison sites are the whole definition of "are embeddings
#: on", and a second value meaning off would otherwise have to be found by
#: grepping for a string literal.
#:
#: Written out rather than taken as `VECTOR_STORES[0]`: an index is a claim
#: about the declaration's *order*, which nothing in `domain/settings.py`
#: promises and no reader of that file would think to preserve. The assertion
#: below is the derivation instead -- it costs nothing at import and turns a
#: rename of the choice into an immediate, named failure rather than a silent
#: `vector_kind != "none"` that is true forever and embeds when asked not to.
NO_VECTOR_STORE = "none"

VECTOR_STORES = _choices("vector_store")
assert NO_VECTOR_STORE in VECTOR_STORES, (
    f"{NO_VECTOR_STORE!r} is no longer a declared AGENT_VECTOR_STORE choice; "
    "whatever replaced it is what turns embeddings off, and every comparison "
    "against NO_VECTOR_STORE now means the opposite of what it says"
)
#: On, since the third scoring feature is what lets consolidation merge a
#: cross-document duplicate on evidence rather than on an overridden threshold.
#: See `vector_store` for what it costs and how it degrades.
DEFAULT_VECTOR_STORE = _builtin_text("vector_store")

#: Named alongside `postgres` even though `build_chunk_store` refuses that
#: branch -- see its docstring -- so an operator who sets it sees a real,
#: unwired setting rather than a typo.
CHUNK_STORES = _choices("chunk_store")
#: On by default, because `memory` here is the graph's `memory`: chunks are
#: rebuilt from `DocumentChunked` at project open, so the cost of the default
#: is a fold proportional to corpus size, paid once per open, not lost data.
DEFAULT_CHUNK_STORE = _builtin_text("chunk_store")

#: A widely-served local embedding model, and the width it returns. Defaults
#: exist for these two *because* the store now defaults to on: a default-on
#: feature whose required variables have no defaults does not start. Both are
#: overridden together or not at all -- see `embedding_dimension`.
DEFAULT_EMBEDDING_MODEL = _builtin_text("embedding_model")
DEFAULT_EMBEDDING_DIMENSION = _builtin_int("embedding_dimension")

DEFAULT_NEO4J_URI = _builtin_text("neo4j_uri")
DEFAULT_NEO4J_USER = _builtin_text("neo4j_user")

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
DEFAULT_PERCEPTION_MAX_CHARS = _builtin_int("perception_max_chars")

#: Seconds between periodic reconciliation sweeps -- see
#: `media_reconcile_interval_seconds` below for why this number.
DEFAULT_MEDIA_RECONCILE_INTERVAL_SECONDS = _builtin_float("media_reconcile_interval")

#: How old an unreferenced blob must be before the sweep may delete it -- see
#: `blob_sweep_grace_seconds` below for why a whole day.
DEFAULT_BLOB_SWEEP_GRACE_SECONDS = _builtin_float("blob_sweep_grace")


def default_db_path() -> str:
    """Where sessions live. Sessions persist across runs and are resumable."""
    configured = os.getenv("AGENT_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "sessions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def interaction_db_path() -> str:
    """Where the interaction log lives. Its own file, not `sessions.db`.

    Separate because `eventsource` derives a store id from the database string
    and every checkpoint position carries it, so a position from one store
    cannot be ordered against a position from another. That makes the split
    structural rather than tidy: no projection can span both stores, which is
    exactly the boundary this feature wants.

    Droppable by design. Unlike `sessions.db` there is no evolution contract
    over these payloads -- when the vocabulary changes, delete the file.
    """
    configured = os.getenv("AGENT_INTERACTION_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "interactions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def interaction_log_enabled() -> bool:
    """Whether the console reports what the user did. On unless switched off.

    The only default-on boolean in this module, and the inversion is
    deliberate. Every other switch here is off by default because unset
    meaning "the route is not there" is a stronger promise than a check inside
    a route that exists -- and that reasoning still holds for anything that
    spends model time or reaches the network on a caller's behalf. This route
    does neither: it writes rows to a local file on the user's own machine.

    Default-on because a log nobody collects is worth nothing, and the whole
    point of this feature is to have a corpus to look at before designing
    against it. Off by default would mean discovering in a month that
    collection was never on.

    What the default costs, stated plainly: `AskSubmitted` carries the
    research prompt, which is a transcript of what someone was thinking
    about. That is the most sensitive field in the system and this variable is
    the answer to it.
    """
    return _flag("interaction_log")


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
    return _text("model")


def base_url() -> str:
    return _text("base_url")


def api_key() -> str:
    return _text("api_key")


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
    return _text("context")


def context_trigger_tokens() -> int:
    """How much conversation `compact` tolerates before summarizing.

    Approximate tokens, not characters: the threshold has to mean something
    against a model's window, and every published trigger is quoted in tokens.
    """
    return _int("context_trigger")


def context_keep_messages() -> int:
    """How many recent messages `compact` leaves out of the summary.

    Separate from the tool-result count below because they are different
    quantities: six messages might be one exchange or six, while six tool
    results is six tool results. LangChain's summarizer keeps twenty by
    default, and a thin tail is where summarization does most of its damage --
    recent detail is what the agent is actively using.
    """
    return _int("context_keep_messages")


def context_keep_results() -> int:
    """How many recent tool results `elide` leaves whole.

    Counted in results rather than messages so the retained volume does not
    swing with the shape of the conversation; Anthropic's tool-result clearing
    counts the same way.
    """
    return _int("context_keep_results")


def context_clear_over_chars() -> int:
    """How long an older tool result may be before `elide` clears it.

    Not a truncation length -- a result over this size is replaced outright,
    because a partial result reads as a whole one.
    """
    return _int("context_clear_over")


def authoring_research_rounds() -> int:
    """How many model calls a parent authoring turn may make before its
    reading tools are withdrawn.

    Separate from the context-management knobs above, and the separation is
    the point: those bound what a *turn* re-sends, and the failure this bounds
    is inside one turn, where they never run. (Written as prose rather than as
    the variable-name glob it wants to be, because
    `test_every_environment_variable_config_reads_is_declared_or_excused`
    scans this module's source for literals and reads a glob as an undeclared
    setting -- which it did, and the failure message is clear enough that the
    test earns the small awkwardness.) See
    `infrastructure/agent/research_budget.py` for the three live runs that
    fixed the default at 6, and for the log-derived number that preceded it and
    was measured to do nothing.

    Zero turns the budget off, for the same reason `AGENT_CONTEXT=full` exists:
    a bound derived from one model's behaviour on one corpus should be
    removable by whoever meets a corpus it is wrong about, without editing
    code. That is why the declaration's `minimum` is 0 rather than 1 -- the
    off switch is a value the README tells a person to write.
    """
    return _int("authoring_rounds")


def tracing_enabled() -> bool:
    """Whether this process should export traces. Off unless asked.

    Opt-in rather than opt-out because tracing is only useful if something is
    collecting it, and a developer running this locally has nothing listening.
    """
    return _flag("tracing")


def otlp_endpoint() -> str:
    """Where traces are sent. The OTLP/HTTP default collector address."""
    return _text("otlp_endpoint")


def tracing_service_name() -> str:
    """What this process calls itself in a trace."""
    return _text("service_name")


def searxng_url() -> str | None:
    """The SearXNG instance to search, or None if this install has no search.

    Unset is the default and means the agent gets no network tool at all --
    which is what keeps the sandbox claim true for anyone who has not opted in.
    """
    configured = _optional("searxng_url")
    return configured.rstrip("/") if configured else None


def searxng_results() -> int:
    """How many results reach the model. Capped because context is the cost."""
    return _int("searxng_results")


def graph_store() -> str:
    """What backs the knowledge graph. `memory` needs no server."""
    return _text("graph_store")


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
    return _text("knowledge_domain")


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
    return _int("extraction_concurrency")


def consolidation_batch_size() -> int:
    """How many entities one `resolve_many` pass decides together. 25 by default.

    This is the knob on the cost `extraction_chunk_size`'s docstring names as
    the one to watch -- adjudicator calls per document. Consolidation used to
    resolve entity by entity, and `Adjudicator.adjudicate` batches only within
    one subject, where the ambiguous band is nearly always a single pair. So a
    document with twenty cross-document duplicates spent twenty round trips
    asking twenty one-pair questions. Batched, the whole batch's band goes in
    one `adjudicate_many` call.

    **Bigger is not simply better, and "all of them" was rejected.** Two costs
    grow with this number:

    - Phase 1 completes before any merge is emitted, so a bigger batch is a
      wider window in which a decision can go stale. redstring re-resolves and
      *skips* rather than retrying, which is correct and also means a bigger
      batch quietly consolidates less per pass.
    - One `adjudicate_many` call is rendered into one prompt. A poisoned batch
      -- one whose verdict count disagrees with what was asked -- yields
      `None` for **every** pair in it, so a wider batch is a wider blast
      radius for one bad answer.

    25 is a starting point chosen against the first cost, not measured to the
    second: it is comfortably more than the duplicates a single document
    usually carries, so the common case is one call, while staying far enough
    below a context limit that batch rendering is not the thing that breaks.
    **Not measured against a real corpus.** The number to watch if this is
    raised is not wall clock but merges-per-pass -- if it falls, phase 1's
    staleness window is what took them.
    """
    return _int("consolidation_batch")


def catalog_sweep_concurrency() -> int:
    """How many candidates a catalog sweep works on at once. **1 by default,
    because on this deployment concurrency was measured to buy nothing.**

    The sweeps (`interfaces/web/blurb_sweep.py`, `interfaces/web/art_sweep.py`)
    can run candidates in parallel, and the arithmetic said they should: a real
    project has 75 candidates, each needing a blurb and an outline, and the art
    sweep an SVG on top. The measurement disagreed.

    Taken 2026-08-24 against the live endpoint over real candidates from a copy
    of the real database, empty caches so every candidate is a real miss.
    Ceilings run **interleaved**, in the order below, over the same 24
    candidates, with an 8-token completion timed immediately before and after
    each run so the ambient load is a column rather than an assumption:

    ======= ======= ============ =========== ==========
    ceiling wall    probe before probe after window UTC
    ======= ======= ============ =========== ==========
    1       149.7s  0.29s        0.66s       20:14:50 (excluded, see below)
    2       169.5s  0.30s        0.67s       20:17:2x
    4       148.5s  0.30s        0.68s       20:20:1x
    8       148.0s  0.31s        0.69s       20:23:0x
    1       149.5s  0.29s        0.66s       20:25:5x
    ======= ======= ============ =========== ==========

    **The first row is excluded and the last row is the baseline.** Four
    orphaned probe processes from an unrelated task were killed at 20:14:57Z,
    about seven seconds into that first run, so it spans two conditions and is
    not one measurement. Every other row ran entirely after. The closing
    ceiling-1 run is the clean sequential baseline.

    Against that baseline, **ceiling 8 is 1.0% faster than ceiling 1**
    (148.0s vs 149.5s). That the excluded row came back within 0.13% of the
    clean one is worth noting only as evidence that the orphans were
    contributing no measurable load by then; it is not why the row is excluded.
    The 169.5s at ceiling 2 is the one row off the line, is unexplained, and
    should be read as noise rather than as a shape.

    The reading: wall clock here is bounded by total generation work, not by
    how many requests are outstanding. This server serialises. Asking it eight
    questions at once returns the eighth answer no sooner than asking eight
    times in a row.

    **Why the ceiling still exists at 1.** The mechanism is not the same thing
    as the number. An endpoint that batches -- a hosted one, or this one
    reconfigured -- turns this into a real speedup for the cost of an
    environment variable, and the alternative was deleting a tested code path
    and rediscovering the need for it later. What 1 buys in the meantime is
    the absence of concurrency's costs on a deployment that pays them for
    nothing: `ArtStore.decrement_uses` is a read-modify-write that two
    candidates can reach at once (locked in `art_sweep._drive`, and *not*
    locked in `ArtReroll`, which has the same hazard), and progress frames
    settle out of submission order.

    **Do not raise this without re-measuring**, and re-measure the way the
    table above was taken -- interleaved, with a latency probe bracketing each
    run, and with the probes checked rather than assumed. An earlier pass ran
    the ceilings back to back while those orphans were alive and produced
    ceiling 6 at 274.1s against a 148.5s baseline, which reads as "concurrency
    is 1.85x slower". It is not: ceiling **8** -- higher than 6 -- measures
    148.0s on a quiet box with a 0.31s probe in front of it, so the sweep's own
    concurrency does not queue the server harmfully at any ceiling tested. That
    274.1s was ambient load, and the tell was never in the wall clock. A queued
    call and a slow call are indistinguishable from the client, which is why
    the probe columns are part of this table rather than a note beside it.
    """
    return _int("catalog_sweep_concurrency")


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

    `consolidation_batch_size` is the other end of this trade and postdates
    the paragraph above: the calls it describes are now batched across
    subjects rather than spent one per duplicate, so "more candidate pairs"
    no longer means "proportionally more round trips". The direction to watch
    is unchanged; the slope is not.
    """
    return _int("extraction_chunk_size")


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
    return _flag("extraction_thinking")


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
    and nothing else, so this feature and the name feature are two readings of
    one thin input, and it moves near-misses in step with true duplicates.

    Not because an embedding is a comparison of spellings -- it is not, and an
    earlier version of this docstring's phrasing ("a blurrier second
    measurement of the string") seeded that confusion through three other
    documents; see `docs/design/learning-areas-and-paths.md` §1. `glass` and
    `cup` share no substring and embed close together. The point is narrower:
    a *name on its own* carries no type, no properties and no neighbourhood, so
    two readings of it agree more than two independent signals would. The
    curriculum's own channel embeds the entity's card instead, and is a
    separate store for exactly this reason -- see
    `infrastructure/knowledge/entity_embeddings.py` and `BACKLOG.md` B129.

    The measurement behind all this: under a real model the exact duplicate and
    `University of York` / `University of Cork` land about 0.011 apart. The
    gain is that 0.75 is defensible; the cost is more traffic in the
    adjudication band.

    **What it costs to run.** Two embedding calls per extracted entity, not
    one: this channel embeds the name for consolidation and the curriculum's
    channel embeds the entity's card, and they are separate stores because
    collapsing them would move consolidation's measured thresholds with no way
    to re-measure them here (`BACKLOG.md` B129). Both are batched, and paid
    again on re-ingest -- `build_graph`
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
    return _text("vector_store")


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
    return _text("chunk_store")


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
    return _optional("curation_model") or model_name()


def extraction_model() -> str:
    """Which model runs knowledge extraction.

    **Not `AGENT_MODEL`, and that is the change.** Extraction shared the chat
    model's name until now -- not by a default, but by having no variable of
    its own -- so an install that wanted extraction on something cheap had to
    repoint the research agent at it too. `ModelRole` named five roles while
    two of them resolved from one string, which made the enum a description of
    an intention rather than of the system.

    Falls back to `model_name()` when unset, exactly as `curation_model` does:
    both jobs run against the same endpoint on a default install, and a
    required variable for a role nobody has customised is a new way for a fresh
    clone not to start. What the fallback does *not* do any more is make the
    two move together when one is set.

    Only the model *name* was shared. Extraction has had its own client since
    `build_extraction_model` -- different `extra_body`, thinking off -- so this
    changes which name that client sends, and nothing about how it sends it.
    """
    return _optional("extraction_model") or model_name()


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
    return _text("embedding_model")


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
    return _int("embedding_dimension")


def embedding_base_url() -> str:
    """Where embedding requests go. Defaults to the endpoint everything else uses.

    Separable because it often has to be: llama.cpp serves one model per
    process, so an install running a chat model locally serves embeddings from
    a second port, and a hosted embedding provider is a different host
    entirely. Reusing `AGENT_BASE_URL` is the right default and would be a
    wrong requirement.
    """
    return _optional("embedding_base_url") or base_url()


def embedding_api_key() -> str:
    """The key for the embedding endpoint. Falls back to the shared one."""
    return _optional("embedding_api_key") or api_key()


def pgvector_dsn() -> str:
    """Where the vectors live. Raises when unset.

    No default, for `neo4j_auth`'s reason: a store that silently comes up
    against `postgres://localhost/postgres` either fails confusingly or
    connects to somebody's development database and writes to it.
    """
    configured = _optional("pgvector_dsn")
    if not configured:
        raise ValueError("AGENT_PGVECTOR_DSN must be set when AGENT_VECTOR_STORE=pgvector")
    return configured


def neo4j_uri() -> str:
    return _text("neo4j_uri")


def neo4j_auth() -> tuple[str, str]:
    """User and password. Raises when the password is unset.

    No default password. A graph store that silently comes up on `neo4j/neo4j`
    is one that either fails confusingly or, worse, connects to somebody's
    development server.
    """
    password = _optional("neo4j_password")
    if not password:
        raise ValueError("AGENT_NEO4J_PASSWORD must be set when AGENT_GRAPH_STORE=neo4j")
    return _text("neo4j_user"), password


def neo4j_database() -> str | None:
    """Which database within the server. None means the server's default."""
    return _optional("neo4j_database")


def transcriber_url() -> str | None:
    """The whisper.cpp server to transcribe against, or None for no ASR.

    Unset is the default and means audio and video are perceived without
    speech -- a frame timeline and nothing said. That is a real, reportable
    degradation rather than an error, which is why this is a `None` and not a
    raise.
    """
    configured = _optional("transcriber_url")
    return configured.rstrip("/") if configured else None


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
    configured = _optional("transcriber_model")
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
    return _optional("vision_model")


def perception_max_chars() -> int:
    """The `Budget` handed to `represent`. The document cap, deliberately.

    The derived text *is* a document -- it lands in `corpus_documents` and is
    extracted like one -- so a second ceiling would be a second answer to one
    question, and the smaller of two answers would be the one that silently
    truncated a transcript.
    """
    return _int("perception_max_chars")


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


def media_reconcile_interval_seconds() -> float:
    """How long between periodic sweeps for proposals stuck at `accepted`.

    Five minutes. The sweep costs one read of the accepted set per interval
    against a set that is normally empty, so the interval is chosen for how
    long a stranded proposal may sit looking like it is working, not for the
    cost of asking -- a review pane showing a card that is downloading and is
    not is tolerable for minutes and not for hours. Reasoned, not measured:
    nothing here has run long enough in anger to have a distribution of how
    often an accept's task is actually lost.

    A sweep that overruns its interval cannot pile up -- the loop in
    `Application` sleeps *between* sweeps rather than on a fixed schedule --
    so lowering this trades wasted reads for latency and nothing else.
    """
    return _float("media_reconcile_interval")


def blob_sweep_grace_seconds() -> float:
    """How long a blob must have sat untouched before the sweep may delete it.

    A whole day. The number is not a performance tuning knob -- it is the one
    thing standing between the sweep and destroyed user data, because
    `CorpusEditor.store_media` writes the bytes and saves the record in two
    separate writes with no transaction across them. A blob observed with no
    `corpus_media` row naming it may simply be a store that has not reached
    its save yet, and the two states are indistinguishable from the outside.
    Twenty-four hours is far longer than any plausible store, and the cost of
    being generous is disk while the cost of being wrong is bytes nobody can
    get back; a day of an orphaned film is cheaper than the film.

    Reasoned, not measured. Nothing here has run against a real corpus long
    enough to have a distribution of how long a store takes, and B85 says
    plainly that the amount of space actually wasted is unmeasured too -- so
    both halves of this trade are guesses, and the guess is deliberately made
    on the side of keeping bytes.

    **The residual risk this does not remove.** A grace period makes the
    window improbable, not impossible: a `store_media` that stalls for longer
    than this between `put` and the command's save still loses its blob. What
    would cause that -- a very large upload streamed slowly enough that `put`
    itself spans a day is not the case, since the mtime is set as the bytes
    land; the real cases are a process suspended (SIGSTOP, a laptop asleep
    mid-request) between the two writes, or a command whose save blocks for a
    day behind a lock or a wedged event store. Both are pathological, and
    neither is impossible. This is the reason the sweep is operator-run and
    reports before it deletes rather than running on a timer.
    """
    return _float("blob_sweep_grace")
