# Extraction candidate: the agent web-research tools

Scope: `research_team/infrastructure/agent/search.py`, `fetch.py`, `recall.py`.

**Verdict: lean further in.** Not extractable as-is, and the extractable
subset is a package nobody would install. The parts that are genuinely good
here are the parts that are about *this* application's honesty rules, and they
get better by being pushed further into the app, not pulled out of it.

---

## 1. What the code is

| File | Lines | Tests | Test file lines |
|---|---|---|---|
| `search.py` | 246 | 25 | 395 |
| `fetch.py` | 497 | 57 | 980 |
| `recall.py` | 309 | 16 + 8 (`test_page_memo.py`) | 222 + 112 |
| **total** | **1052** | **106** | **1709** |

Test-to-source ratio is 1.6:1 and the fetch suite is exhaustive (57 tests over
one tool). Coverage is not the constraint on extraction here.

### Generic vs. coupled, line by line

**`recall.py` (309 lines) — almost entirely generic.**

- `normalize_query`, `normalize_url`, `query_key`, `url_key`, `describe_age`,
  `Recall`, `Recalled` — zero imports from this project. Pure stdlib
  (`time`, `unicodedata`, `OrderedDict`, `urlsplit`).
- `PageMemo` / `RetainedPage` are generic in mechanism but shaped by a
  consumer: `RetainedPage`'s fields (`uri`, `title`, `published_at`,
  `fetched_at` as a *string*) exist because `SourceDocumentStored.fetched_at`
  is `str | None` (`recall.py:206-214` says so explicitly). Generic code that
  is the wrong shape for a stranger.
- The genuinely valuable thing in this file is not code, it is the
  **normalization rule and the argument for it** (module docstring, lines
  16-29): fold only where the upstream is already insensitive; never stem,
  sort or embed, because a merged query returns an answer to a question nobody
  asked while labelling it as the one that was. Plus `Recalled.asked` as the
  visibility net under it. That is ~60 lines of implementation and a page of
  reasoning. A library cannot ship the reasoning as a dependency.

**`search.py` (246 lines) — generic except for two app hooks.**

- Coupled: `from research_team.application import SEARCH_TOOL` (a string
  constant, `autonomy.py:27`) and `_exhausted_notice`, which names
  `record_gap` — a tool that only exists in this app.
- `SearchAttempts` (48 lines) is the interesting piece and is also the one
  with a documented concurrency bug: it is process-wide despite every
  docstring saying "this turn" (`search.py:60-74`). Shipping a class whose own
  docstring says "the contract this class states is not true under
  concurrency" is not a library move.
- `format_results` + the two error sentinels are ~50 lines of generic SearXNG
  handling. This is the only part with a real analogue in the ecosystem, and
  it is 50 lines.

**`fetch.py` (497 lines) — the coupling is real, but shallower than the import
list suggests.**

Three app imports, and they are not equally hard:

1. `CorpusReadPort` / `CorpusReadError` (`application/corpus_read.py`) —
   **already a `Protocol`**, two methods, no storage vocabulary. This is
   already an injected port; nothing needs doing. The only leak is that
   `stored_page` returns text formatted by `corpus_tools.format_document`
   against `corpus_spans.quote` offsets — that is genuinely app-specific
   (the offset contract is a citation-verifiability invariant of *this*
   project) and is the wrong thing to genericize.
2. `FETCH_TOOL` from `autonomy.py` — a string constant. Trivial.
3. `FetchGrant` (`application/grants.py`, 352 lines) — **this is the hard
   one, and it is also the most valuable code in the candidate.** The
   `reserve(call_id, url)` / `spend()` / `release()` protocol exists because a
   plain `covers()` check let ten requests through on a budget of one when the
   model put ten `fetch` calls in one message, and keying reservations by
   `InjectedToolCallId` exists because langgraph re-executes the whole gate
   pass on `Command(resume=...)`. Both bugs are documented in
   `fetch.py:261-299` with the reproduction. Turning this into a port is
   mechanically easy (it is already one object with three methods) but
   *semantically* it is welded to `approval.py`'s gate: the host check
   deliberately appears in two places answering two different questions, and
   `fetch.py:246-250` says in as many words **"Do not refactor them
   together."** A library boundary drawn through a seam whose own comment
   forbids collapsing it is a boundary that will be violated by the first
   person who does not read the comment.

So: mechanically, extraction is maybe a day. `CorpusReadPort` is already a
port; `FetchGrant` becomes a 3-method Protocol; the two tool-name constants
become parameters. The problem is not difficulty.

---

## 2. The competitive landscape

### SearXNG tools

- **`langchain_community.utilities.SearxSearchWrapper`** + the
  `SearxSearchResults` tool. Has `searx_host`, `engines`, `categories`, `k`,
  `query_suffix`, sync + async (`arun`/`aresults`).
  ([reference](https://reference.langchain.com/python/langchain-community/utilities/searx_search/SearxSearchWrapper),
  [docs](https://docs.langchain.com/oss/javascript/integrations/tools/searxng))
  What it lacks, relative to ours: no memoization, no result-set cap framed as
  a context-budget concern, no in-band handling of the *specific* SearXNG
  failure that everyone hits (JSON API disabled by default — our
  `_JSON_DISABLED` message is the single most operationally useful string in
  the module), no distinction between "no results" and "instance unreachable".
  It also exposes far more of SearXNG's surface than we do (engine/category
  selection), which is a real feature we don't have.
  **But:** `langchain-community` is
  [officially sunset and no longer maintained](https://github.com/langchain-ai/langchain-community)
  ([sunset issue #674](https://github.com/langchain-ai/langchain-community/issues/674)).
  This cuts both ways — it is a decaying competitor, but it also means the
  centralized-integration-package model is the thing LangChain just gave up
  on. A new framework-agnostic tool-collection package is walking into a
  category its largest incumbent abandoned for reasons that would apply to us
  too.

### Trafilatura-based fetch

- **`trafilatura` itself** — the extraction is one call
  (`trafilatura.extract(html, output_format="markdown")`). Mature, widely
  adopted (HuggingFace, IBM, Microsoft Research, AI2 cited on the
  [project docs](https://trafilatura.readthedocs.io/)), consistently top of
  extraction benchmarks. Our `extract_page` is 28 lines *around* it.
- **`llama-index-readers-web`** ships `TrafilaturaWebReader`
  ([llamahub](https://llamahub.ai/l/readers/llama-index-readers-web),
  [PyPI](https://pypi.org/project/llama-index-readers-web/)) — returns
  `Document`s, no caching, no metadata citation header, no budget/approval
  concept, no content-type or byte-cap guard.

### The crowded middle: MCP servers

This is where our exact combination already exists, repeatedly, as a product:

- **Search & Fetch** — SearXNG search + trafilatura markdown extraction for
  local LLMs ([mcpmarket](https://mcpmarket.com/server/search-fetch-1))
- **web-search-mcp** — SearXNG instance + configurable trafilatura endpoint
  ([LobeHub](https://lobehub.com/mcp/oremus-labs-web-search-mcp))
- **searxng-mcp**, **searxng-mcp-scraper**
  ([Glama](https://glama.ai/mcp/servers/TadMSTR/searxng-mcp),
  [Glama](https://glama.ai/mcp/servers/ptrken01/searxng-mcp-scraper))
- **master-fetch** — trafilatura extraction, Cloudflare bypass, smart routing
  ([GitHub](https://github.com/dondai44423/master-fetch))
- **`web-research-agent`** on PyPI — whole-agent, Playwright fallback
  ([PyPI](https://pypi.org/project/web-research-agent/))

None of these do memoization with a defensible normalization rule, and none do
budget reservation. Most are thin, single-author, and recent. But they are
*free and already installed*, which is the bar.

### Hosted alternatives

Tavily, Exa, Firecrawl. These are the actual competition for the job, and
they win on everything our code does not: rendered-page handling, anti-bot,
server-side caching, and an SLA. They lose on the one axis this project
chose deliberately — **nothing escapes to a third party**, which is the whole
reason a self-hosted SearXNG is the search backend at all. That is a real
differentiator for this app and a very small addressable market for a library.

### Caching of agent web tools

Nothing framework-level. LangChain caches LLM calls, not tool calls.
General-purpose HTTP caches (`hishel`, `requests-cache`) cache at the
transport layer, which is the wrong layer: they cannot express "a search query
and a fetched URL live in one store and must not collide", they do not report
provenance back to the model (`Recalled.asked`), and they cache bytes rather
than the *extraction*, so a memo hit still re-runs trafilatura. Our
`recall.py` is genuinely not covered by anything I found. It is also 60 useful
lines.

---

## 3. Why not extract

The bar the lead set is "someone else would install this instead of the
alternatives." Applying it honestly:

- The **SearXNG tool** competes with a langchain-community wrapper that is
  more configurable and four MCP servers that are free. Our edge is ~5 error
  strings and a result cap. Nobody installs a package for that.
- The **fetch tool** competes with `trafilatura.extract` in one line plus the
  MCP servers. Our edge is the citation header, the byte cap, the content-type
  guard, and the redirect refusal — all good, all ~40 lines, all easily
  re-derived.
- The **recall layer** is the one genuinely novel piece and it is the *least*
  extractable as a product, because its value is a policy argument, not an
  API. A 60-line LRU with a docstring explaining why it does not stem is not a
  dependency; it is a blog post and a copy-paste.
- The **grant/reservation protocol** is the most valuable code here by a wide
  margin — it fixes two bugs (batch over-spend, langgraph resume
  double-claim) that anyone building budgeted agent tools will hit. But it is
  half in `approval.py`, its correctness depends on langgraph's re-execution
  semantics, and its own comments forbid the refactor that extraction would
  require. Extracting it would mean extracting the gate too, at which point
  the "library" is this application's autonomy model.

Extraction also imposes a cost the current design specifically avoids: three
of these modules currently get to *state their assumptions and rely on them*
(single event loop, no thread safety, one process, `Recalled.asked` is checked
by a model that reads prose). A library has to defend those against callers
who do not share them — `Recall` grows a lock, `SearchAttempts` grows per-turn
scoping it does not have (its docstring already admits the contract is false
under concurrency), and `PageMemo`'s `RetainedPage` grows a generic shape
instead of the one that matches `SourceDocumentStored`.

## 4. Why "lean further in" rather than "balanced as-is"

There is a real open defect, already written down and currently unowned by the
design: **`SearchAttempts` is process-wide while claiming to be per-turn**
(`search.py:60-74`, deferred in `BACKLOG.md`). The docstring's own accounting
is that the blast radius is small — but the blocker it names is "the larger
change of making the tool (and its dependency on a single SearXNG client)
rebuildable per turn." That is precisely the change extraction would have
forced, and it is worth making *in-repo* for its own sake: a per-turn tool
build is also what would let `SearchAttempts` be a turn-scoped object, and it
removes the one place in this candidate where a shipped contract is knowingly
false.

Two smaller in-repo investments follow from the landscape scan rather than the
code:

- `search.py` exposes none of SearXNG's `engines` / `categories` / `time_range`
  parameters, which langchain-community does. For a research agent choosing
  between a general query and a scholarly one, that is a capability gap, not a
  simplification.
- `fetch.py`'s `UNREADABLE` path is a dead end for any JS-rendered page. Every
  competitor in the scan either has a Playwright fallback or documents its
  absence as the main limitation. Worth a BACKLOG entry deciding explicitly
  whether this project accepts that ceiling (it may well — "an app shell will
  come back empty however many times you ask" is already in `FETCH_PROMPT` as
  a deliberate answer).

## 5. If the verdict is ever revisited

The only piece with a plausible independent life is the **budget-reservation
protocol** (`FetchGrant.reserve`/`spend`/`release` keyed by tool-call id,
correct under langgraph resume) — not the web tools. If a second application
in this stack ever needs budgeted, human-gated tool calls, extract *that*, as
a langgraph-aware companion library, and leave search and fetch here. Do not
package the web tools.
