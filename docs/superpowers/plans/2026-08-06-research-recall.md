# Research Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `fetch` and `web_search` re-retrieving what this project already has, by wiring them to the corpus and to a bounded in-process memo.

**Architecture:** `remember` starts recording `uri`/`title`/`published_at` into fields that already exist end-to-end but are never filled. A new `recall.py` provides a bounded, expiring, normalizing memo shared by both network tools. `fetch` consults corpus → memo → network, with `refresh=True` as an explicit override; `web_search` consults the memo only. A corpus-aware `fetch` reaches its project by being attached alongside the corpus tools, which requires `KnowledgeAttachment` to let attached tools shadow base tools of the same name.

**Tech Stack:** Python 3.12+, `httpx` (stubbed via `httpx.MockTransport` in tests), `langchain_core.tools`, `pytest` + `pytest-asyncio`, `ruff`.

## Global Constraints

- **No test may touch the network.** Both builders already take `client=` for this; use it.
- **Two requests share a memo entry only if the instance would have returned the same results for both.** Case, whitespace and Unicode form clear that bar. Term reordering, stopword stripping, stemming and embeddings do not, and must not be implemented.
- **Every cache hit must announce itself and carry its age.** Stored text returned as though freshly read is the failure this whole change exists to avoid producing a new form of.
- **Do not run the full test suite.** Run only the test files named in each task. CI runs the suite at PR time.
- **Both ruff gates must pass:** `uv run ruff check .` and `uv run ruff format .`.
- **Commit messages** end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **House style:** module and function docstrings carry the *reasoning* behind a decision, not a restatement of the code. Match the surrounding files.

---

## File Structure

| File | Responsibility |
|---|---|
| `research_team/infrastructure/agent/recall.py` | **New.** Normalization, and a bounded expiring memo. No knowledge of HTTP or of the corpus. |
| `research_team/infrastructure/agent/knowledge_tools.py` | `remember` grows three provenance parameters. |
| `research_team/infrastructure/agent/search.py` | `web_search` consults the memo. |
| `research_team/infrastructure/agent/fetch.py` | `fetch` consults corpus → memo → network; gains `refresh`. |
| `research_team/infrastructure/agent/corpus_tools.py` | `_bounded` becomes public `bounded` so `fetch` reuses the offset contract rather than reimplementing it. |
| `research_team/application/knowledge_attachment.py` | Attached tools shadow base tools of the same name. |
| `research_team/composition.py` | Builds one shared `Recall`; builds a corpus-aware `fetch` inside `open_graph`. |

---

### Task 1: `remember` records where its text came from

`SourceRef` already declares `uri`, `title` and `published_at`, and
`redstring_adapter.py:170,254` already passes them into `StoreSourceDocument`.
Only the tool signature drops them.

**Files:**
- Modify: `research_team/infrastructure/agent/knowledge_tools.py:81-89` (the `remember` tool) and `:119-134` (`KNOWLEDGE_PROMPT`)
- Test: `tests/infrastructure/test_knowledge_tools.py`

**Interfaces:**
- Consumes: `SourceRef(source_id, text, note, uri, title, published_at)` from `research_team.application.knowledge` — already exists, do not modify it.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`StubKnowledge.ingest` currently discards its argument. Give it a record so the test can inspect what was passed. In `tests/infrastructure/test_knowledge_tools.py`, add `self.ingested = []` to `StubKnowledge.__init__` and `self.ingested.append(source)` as the first line of `ingest` (after the error check). Then add:

```python
@pytest.mark.asyncio
async def test_remember_carries_the_provenance_fetch_returned():
    """`fetch` leads every page with `url:`, `title:` and `date:`. Those are
    the only record of where the text came from, and a corpus that drops them
    cannot recognise a page it already holds -- which is the whole reason
    `DocumentRecord.uri` exists.
    """
    report = IngestReport(
        source_id="s1",
        entity_count=1,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge)

    await tools["remember"].ainvoke(
        {
            "text": "body",
            "source_id": "s1",
            "uri": "https://ex.example/a",
            "title": "A page",
            "published_at": "2026-01-02",
        }
    )

    (source,) = knowledge.ingested
    assert source.uri == "https://ex.example/a"
    assert source.title == "A page"
    assert source.published_at == "2026-01-02"


@pytest.mark.asyncio
async def test_remember_without_provenance_stores_none_not_empty_string():
    """Absent provenance and blank provenance must not be the same value. A
    corpus row holding `""` for its uri looks like a page fetched from
    nowhere; `None` says plainly that none was given.
    """
    report = IngestReport(
        source_id="s1",
        entity_count=1,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
    )
    knowledge = StubKnowledge(report=report)
    tools = tools_by_name(knowledge)

    await tools["remember"].ainvoke({"text": "body", "source_id": "s1"})

    (source,) = knowledge.ingested
    assert source.uri is None
    assert source.title is None
    assert source.published_at is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py -v -k provenance`
Expected: FAIL — `remember` rejects the unexpected `uri` keyword.

- [ ] **Step 3: Write the implementation**

Replace the `remember` tool in `research_team/infrastructure/agent/knowledge_tools.py`:

```python
    @tool(REMEMBER_TOOL)
    async def remember(
        text: str,
        source_id: str,
        note: str = "",
        uri: str = "",
        title: str = "",
        published_at: str = "",
    ) -> str:
        """Commit text to the graph, extracting entities and relationships from it."""
        try:
            report = await knowledge.ingest(
                SourceRef(
                    source_id=source_id,
                    text=text,
                    note=note or None,
                    # Empty becomes None rather than travelling as "". A blank
                    # uri in the corpus is indistinguishable from a page
                    # fetched from nowhere, and the tool boundary is where a
                    # model's "I have nothing for this" arrives as "".
                    uri=uri or None,
                    title=title or None,
                    published_at=published_at or None,
                )
            )
        except KnowledgeError as error:
            return f"Could not record this: {error}"
        return format_ingest(report)
```

- [ ] **Step 4: Update `KNOWLEDGE_PROMPT`**

In the same file, replace the second paragraph of `KNOWLEDGE_PROMPT` (the one beginning "Committing is not free") by inserting this paragraph *before* it:

```python
    "When what you are committing came from a page you fetched, pass the "
    "`url:`, `title:` and `date:` lines `fetch` printed as `uri`, `title` and "
    "`published_at`. Those three are how this project recognises a page it "
    "has already read -- a document stored without its `uri` will be fetched "
    "again by some later session that had no way to tell.\n\n"
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tools.py
uv run ruff check research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tools.py
git add research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tools.py
git commit -m "feat: let remember record where its text came from

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The recall store

**Files:**
- Create: `research_team/infrastructure/agent/recall.py`
- Test: `tests/infrastructure/test_recall.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all used by Tasks 3 and 5:
  - `normalize_query(request: str) -> str`
  - `normalize_url(url: str) -> str`
  - `Recalled` — frozen dataclass with `text: str`, `asked: str`, `age_seconds: float`
  - `Recall(*, capacity: int = 128, ttl_seconds: float = 3600.0, clock: Callable[[], float] = time.monotonic)` with `get(request: str, *, key: str | None = None) -> Recalled | None` and `put(request: str, text: str, *, key: str | None = None) -> None`
  - `describe_age(seconds: float) -> str`

The `key=` parameter lets `fetch` supply a URL-normalized key while still
recording the URL as asked; `web_search` omits it and gets query
normalization.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_recall.py`:

```python
"""The recall store: what the network tools remember having already served.

The tests that matter most here are the two normalization boundaries. Merging
requests that would have produced different answers is not a cache miss with
extra steps -- it is a wrong answer wearing the label of a right one.
"""

import pytest

from research_team.infrastructure.agent.recall import (
    Recall,
    describe_age,
    normalize_query,
    normalize_url,
)


class _Clock:
    """A hand-wound monotonic clock, so TTL is tested without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# ---- normalization: what may be merged ----


@pytest.mark.parametrize(
    "a,b",
    [
        ("Backward Design", "backward design"),
        ("backward  design", "backward design"),
        (" backward design ", "backward design"),
        ("backward\tdesign", "backward design"),
    ],
)
def test_queries_a_search_instance_cannot_tell_apart_are_merged(a, b):
    assert normalize_query(a) == normalize_query(b)


# ---- normalization: what may not ----


@pytest.mark.parametrize(
    "a,b",
    [
        ("backward design assessment", "assessment design backward"),
        ("the design of assessment", "design assessment"),
        ("designing assessments", "design assessment"),
    ],
)
def test_queries_an_instance_ranks_differently_are_kept_apart(a, b):
    """Reordering, stopwords and stemming all change what comes back. A memo
    that merges them answers a question the agent did not ask while labelling
    the results as answering the one it did -- which is worse than the
    repeated request it saves, especially against an instance the operator
    runs themselves.
    """
    assert normalize_query(a) != normalize_query(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("HTTPS://Ex.Example/A", "https://ex.example/A"),
        ("https://ex.example:443/a", "https://ex.example/a"),
        ("http://ex.example:80/a", "http://ex.example/a"),
        ("https://ex.example/a#section", "https://ex.example/a"),
        ("https://ex.example", "https://ex.example/"),
    ],
)
def test_urls_that_address_the_same_resource_are_merged(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_url_paths_keep_their_case():
    """Hosts are case-insensitive and paths are not. Folding the path would
    merge two different pages on any server that serves both.
    """
    assert normalize_url("https://ex.example/A") != normalize_url("https://ex.example/a")


def test_a_query_string_distinguishes_urls():
    assert normalize_url("https://ex.example/s?q=1") != normalize_url("https://ex.example/s?q=2")


# ---- the store ----


def test_what_was_put_comes_back():
    recall = Recall(clock=_Clock())
    recall.put("https://ex.example/a", "body")
    hit = recall.get("https://ex.example/a")
    assert hit is not None
    assert hit.text == "body"


def test_nothing_stored_is_a_miss():
    assert Recall(clock=_Clock()).get("https://ex.example/a") is None


def test_a_hit_reports_the_request_that_produced_it():
    """The safety net under normalization. If the agent asked X and the entry
    was made for Y, the response must be able to say so -- a merge the agent
    can see is a wasted turn, and a merge it cannot see is a wrong answer.
    """
    recall = Recall(clock=_Clock())
    recall.put("Backward Design", "results")
    hit = recall.get("backward  design")
    assert hit is not None
    assert hit.asked == "Backward Design"


def test_a_hit_reports_its_age():
    clock = _Clock()
    recall = Recall(clock=clock)
    recall.put("q", "results")
    clock.now = 90.0
    hit = recall.get("q")
    assert hit is not None
    assert hit.age_seconds == pytest.approx(90.0)


def test_an_entry_past_its_ttl_is_a_miss():
    """The process may be a web server that has been up for days. Without
    expiry, `web_search` -- which has no refresh override -- would serve a
    days-old result set as current for as long as the process lived.
    """
    clock = _Clock()
    recall = Recall(ttl_seconds=60.0, clock=clock)
    recall.put("q", "results")
    clock.now = 61.0
    assert recall.get("q") is None


def test_the_store_evicts_its_least_recently_used_entry():
    """Entries are page bodies of up to 20k chars in a process that may run
    for days. Unbounded, this is a leak sized by how much research is done.
    """
    recall = Recall(capacity=2, clock=_Clock())
    recall.put("a", "1")
    recall.put("b", "2")
    recall.get("a")  # 'a' is now the more recently used of the two
    recall.put("c", "3")
    assert recall.get("b") is None
    assert recall.get("a") is not None
    assert recall.get("c") is not None


def test_putting_the_same_request_twice_replaces_it():
    clock = _Clock()
    recall = Recall(clock=clock)
    recall.put("q", "old")
    clock.now = 10.0
    recall.put("q", "new")
    hit = recall.get("q")
    assert hit is not None
    assert hit.text == "new"
    assert hit.age_seconds == pytest.approx(0.0)


def test_an_explicit_key_separates_matching_from_reporting():
    """`fetch` normalizes URLs and `web_search` normalizes queries, but both
    want the request recorded as the caller wrote it.
    """
    recall = Recall(clock=_Clock())
    recall.put("HTTPS://Ex.Example/A", "body", key=normalize_url("HTTPS://Ex.Example/A"))
    hit = recall.get("https://ex.example/A", key=normalize_url("https://ex.example/A"))
    assert hit is not None
    assert hit.asked == "HTTPS://Ex.Example/A"


# ---- age, in words ----


@pytest.mark.parametrize(
    "seconds,expected",
    [(0.4, "just now"), (45.0, "45 seconds ago"), (120.0, "2 minutes ago"), (7200.0, "2 hours ago")],
)
def test_age_reads_as_prose(seconds, expected):
    assert describe_age(seconds) == expected
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/test_recall.py -v`
Expected: FAIL — `ModuleNotFoundError: research_team.infrastructure.agent.recall`

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/agent/recall.py`:

```python
"""What the network tools remember having already served.

Two tools leave this process, and until now neither had any way to know it was
about to ask for something it already had. The corpus answers that question
durably for pages the project chose to keep; this answers it for the rest, for
as long as the process lives.

In-process and deliberately not persistent. A durable record of every page
ever fetched -- as opposed to every page deliberately kept -- would make
fetching permanent, which `remember`'s own prompt is careful to say it is not,
and would need a retention policy, a read model, and an answer to why it is
not the corpus. The failure that actually recurs is narrower than that: the
same page twice in one long-running process, after the first read was
compacted out of context. That is what this covers.

**The normalization rule, which is the whole design:** two requests share an
entry only if the instance would have returned the same results for both.
Case, whitespace and Unicode form clear that bar. Term order, stopwords and
stemming do not -- an engine ranks `"assessment design backward"` differently
from `"backward design assessment"`, so merging them returns results for a
question that was not asked while labelling them as answering the one that
was. That is a wrong answer wearing a right one's label, traded for a saved
request against a search instance the operator runs themselves. There is no
version of that trade worth making, which is why nothing here stems, sorts or
embeds.

`Recalled.asked` is the safety net under all of it. Every hit can report the
request that actually produced it, so a merge the agent did not intend is
visible in the response and costs a turn rather than an answer.
"""

import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

CAPACITY = 128
"""How many responses are held. Entries are page bodies of up to `MAX_CHARS`,
in a process that may be a web server running for days; unbounded, this is a
leak whose size is set by how much research the agent does."""

TTL_SECONDS = 3600.0
"""How long an entry stays usable.

`fetch` has `refresh=True` as an explicit override and `web_search` has
nothing, so without expiry a long-lived process would pin a stale result set
and present it as current for as long as it ran. An hour is short enough that
a page which changed is re-read within a working session, and long enough to
cover the case this exists for."""

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_query(request: str) -> str:
    """A search query, folded only where an instance is already insensitive.

    NFKC first so that visually identical text composed differently -- a
    precomposed accent against a combining one -- does not produce two
    entries. Then casefold, which is the full-Unicode form of lowercasing and
    the right one for a comparison key. Then whitespace collapse.

    Nothing else. See this module's docstring for why the list stops here.
    """
    folded = unicodedata.normalize("NFKC", request).casefold()
    return " ".join(folded.split())


def normalize_url(url: str) -> str:
    """A URL, folded only where two spellings address the same resource.

    Scheme and host are case-insensitive by RFC 3986 and are folded. A default
    port is equivalent to no port and is dropped. A fragment never reaches the
    server at all, so two URLs differing only in one are one request. An empty
    path is `/`.

    The path, query and everything else are left exactly alone. Paths are
    case-sensitive on any server that says they are, and folding one would
    merge two genuinely different pages -- which is the same failure as
    merging two search queries, arriving through a different door.
    """
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(parts.scheme.lower()) != str(port):
        host = f"{host}:{port}"
    return urlunsplit(
        (parts.scheme.lower(), host, parts.path or "/", parts.query, "")
    )


def describe_age(seconds: float) -> str:
    """How long ago, in words, for a sentence the model reads.

    Coarse on purpose: the decision this informs is "is this still good
    enough", and a figure to the second invites precision the entry does not
    have -- it was fetched once, at a moment nothing here recorded to that
    resolution.
    """
    if seconds < 1:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    return f"{int(seconds // 3600)} hours ago"


@dataclass(frozen=True)
class Recalled:
    """One remembered response, and enough context to present it honestly."""

    text: str

    asked: str
    """The request as the caller originally wrote it, not as it was keyed.

    Reported back so a response can say which request these results are for.
    Without it a normalization that merged too much would be invisible, and an
    invisible merge is the only kind that does damage.
    """

    age_seconds: float


class Recall:
    """A bounded, expiring, least-recently-used memo.

    Not thread-safe and not trying to be: one process, one event loop, and
    every caller is inside an `async def` that never awaits mid-update. A lock
    here would be ceremony around an operation that cannot interleave.
    """

    def __init__(
        self,
        *,
        capacity: int = CAPACITY,
        ttl_seconds: float = TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, tuple[str, str, float]] = OrderedDict()

    def get(self, request: str, *, key: str | None = None) -> Recalled | None:
        """What was served for `request` before, or None.

        An expired entry is dropped on the way out rather than left to the
        eviction path. It is already known to be useless, and keeping it would
        let dead weight hold a slot against a live entry.
        """
        resolved = key if key is not None else normalize_query(request)
        entry = self._entries.get(resolved)
        if entry is None:
            return None
        asked, text, stored_at = entry
        age = self._clock() - stored_at
        if age > self._ttl:
            del self._entries[resolved]
            return None
        self._entries.move_to_end(resolved)
        return Recalled(text=text, asked=asked, age_seconds=age)

    def put(self, request: str, text: str, *, key: str | None = None) -> None:
        """Remember what `request` returned, evicting the coldest if full."""
        resolved = key if key is not None else normalize_query(request)
        self._entries[resolved] = (request, text, self._clock())
        self._entries.move_to_end(resolved)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/test_recall.py -v`
Expected: PASS, all of them.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format research_team/infrastructure/agent/recall.py tests/infrastructure/test_recall.py
uv run ruff check research_team/infrastructure/agent/recall.py tests/infrastructure/test_recall.py
git add research_team/infrastructure/agent/recall.py tests/infrastructure/test_recall.py
git commit -m "feat: a bounded expiring memo for what the network tools already served

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `web_search` consults the memo

**Files:**
- Modify: `research_team/infrastructure/agent/search.py`
- Test: `tests/infrastructure/test_search.py`

**Interfaces:**
- Consumes: `Recall`, `Recalled`, `describe_age` from Task 2.
- Produces: `build_search_tool(base_url, *, limit=5, client=None, recall: Recall | None = None)` — Task 6 passes `recall=`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_search.py`:

```python
# ---------------- recall ----------------


def _counting_handler(counter: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://ex.example/a", "content": "c"}]},
        )

    return handler


@pytest.mark.asyncio
async def test_the_same_query_twice_reaches_the_instance_once():
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    await tool.ainvoke({"query": "backward design"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_recalled_result_set_says_it_is_one():
    """Returning an earlier result set dressed as a fresh search would have
    the model reason about a snapshot as though it were current, with nothing
    in the transcript to show why.
    """
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    again = await tool.ainvoke({"query": "backward design"})
    assert "searched" in again.lower()
    assert "https://ex.example/a" in again


@pytest.mark.asyncio
async def test_a_recalled_result_set_names_the_query_that_produced_it():
    """The safety net under normalization: a merge the agent can see costs a
    turn, and a merge it cannot see costs a correct answer.
    """
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "Backward Design"})
    again = await tool.ainvoke({"query": "backward  design"})
    assert "Backward Design" in again


@pytest.mark.asyncio
async def test_a_different_query_is_a_different_search():
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    await tool.ainvoke({"query": "design backward"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_failed_search_is_not_remembered():
    """Caching "could not reach the instance" would turn one outage into an
    hour of them, and the retry that would have worked never happens.
    """
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(
            200, json={"results": [{"title": "T", "url": "u", "content": "c"}]}
        )

    tool = build_search_tool("http://searx.local", client=_client(handler), recall=Recall())
    await tool.ainvoke({"query": "q"})
    second = await tool.ainvoke({"query": "q"})
    assert len(calls) == 2
    assert "T" in second


@pytest.mark.asyncio
async def test_without_a_recall_every_search_reaches_the_instance():
    calls: list[int] = []
    tool = build_search_tool("http://searx.local", client=_client(_counting_handler(calls)))
    await tool.ainvoke({"query": "q"})
    await tool.ainvoke({"query": "q"})
    assert len(calls) == 2
```

Add `from research_team.infrastructure.agent.recall import Recall` to the imports at the top of the file.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/test_search.py -v -k recall or same_query`
Expected: FAIL — `build_search_tool` rejects the `recall` keyword.

- [ ] **Step 3: Write the implementation**

In `research_team/infrastructure/agent/search.py`, add the import:

```python
from research_team.infrastructure.agent.recall import Recall, describe_age
```

Add this module-level helper above `build_search_tool`:

```python
def format_recalled(recalled, query: str) -> str:
    """An earlier result set, labelled with when and for what.

    Names the query that produced the entry rather than the one just asked,
    because normalization means they need not be identical. A model that can
    see the difference can ask again; one that cannot would take results for a
    neighbouring question as answering its own.
    """
    asked = "" if recalled.asked == query else f" for {recalled.asked!r}"
    return (
        f"[recalled -- searched{asked} {describe_age(recalled.age_seconds)} in this "
        f"process, not a fresh search]\n\n{recalled.text}"
    )
```

Change the signature and body of `build_search_tool`:

```python
def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
) -> BaseTool:
```

and inside `web_search`, before `owned = client is None`:

```python
        if recall is not None:
            remembered = recall.get(query)
            if remembered is not None:
                return format_recalled(remembered, query)
```

and store the result immediately before `return format_results(payload, limit)`, replacing that line with:

```python
            results = format_results(payload, limit)
            if recall is not None:
                # Only a result set is remembered. A transport failure cached
                # for an hour turns one outage into an hour of them, and the
                # retry that would have succeeded never happens.
                recall.put(query, results)
            return results
```

- [ ] **Step 4: Update `SEARCH_PROMPT`**

Replace the first paragraph of `SEARCH_PROMPT` with:

```python
    "\n\nYou can search the web with the `web_search` tool. What it returns is "
    "a snapshot at the moment you searched, recorded permanently in this "
    "session's log -- not a live view you can refresh by asking again. Asking "
    "the same question twice returns the first answer, marked as recalled and "
    "naming the query it came from; if that query is not the one you meant, "
    "ask a different one rather than the same one again. If a search is "
    "refused, that refusal is your answer for this turn.\n\n"
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/test_search.py -v`
Expected: PASS, all of them.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format research_team/infrastructure/agent/search.py tests/infrastructure/test_search.py
uv run ruff check research_team/infrastructure/agent/search.py tests/infrastructure/test_search.py
git add research_team/infrastructure/agent/search.py tests/infrastructure/test_search.py
git commit -m "feat: web_search returns an earlier result set rather than asking twice

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Attached tools shadow base tools of the same name

Without this, a project-scoped `fetch` cannot be attached — it would collide
by name with the base one and the executor would hold two tools called
`fetch`.

**Files:**
- Modify: `research_team/application/knowledge_attachment.py:79` (the `set_tools` call in `attach`)
- Test: `tests/application/test_knowledge_attachment.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the shadowing behaviour Task 6 relies on. No signature change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/application/test_knowledge_attachment.py`:

```python
# ---------------- shadowing ----------------


class _NamedTool:
    def __init__(self, name: str, marker: str) -> None:
        self.name = name
        self.marker = marker


def _shadowing_attachment(executor, base_tools, attached):
    async def open_graph(project_id):
        return object(), attached

    async def close_graph(knowledge):
        return None

    return KnowledgeAttachment(
        executor, base_tools, open_graph=open_graph, close_graph=close_graph
    )


@pytest.mark.asyncio
async def test_an_attached_tool_replaces_a_base_tool_of_the_same_name():
    """`fetch` is built once at composition with no project; a corpus-aware
    one can only arrive with the project. Both are called `fetch`, and an
    executor holding two tools of one name is a coin toss over which the model
    reaches.
    """
    base = (_NamedTool("fetch", "plain"), _NamedTool("other", "base"))
    executor = _FakeExecutor(base)
    attachment = _shadowing_attachment(
        executor, base, (_NamedTool("fetch", "corpus-aware"),)
    )

    await attachment.attach(uuid4())

    by_name = {tool.name: tool for tool in executor.tools}
    assert by_name["fetch"].marker == "corpus-aware"
    assert by_name["other"].marker == "base"
    assert [tool.name for tool in executor.tools].count("fetch") == 1


@pytest.mark.asyncio
async def test_detaching_restores_the_shadowed_base_tool():
    """The reason shadowing was chosen over a mutable holder: leaving a
    project must restore the project-less tool, and the attachment is the one
    thing that already knows exactly when that happens.
    """
    base = (_NamedTool("fetch", "plain"),)
    executor = _FakeExecutor(base)
    attachment = _shadowing_attachment(
        executor, base, (_NamedTool("fetch", "corpus-aware"),)
    )

    await attachment.attach(uuid4())
    await attachment.detach()

    by_name = {tool.name: tool for tool in executor.tools}
    assert by_name["fetch"].marker == "plain"
    assert len(executor.tools) == 1


@pytest.mark.asyncio
async def test_a_tool_without_a_name_is_kept_rather_than_dropped():
    """Shadowing is keyed on `.name`. Anything without one cannot collide, and
    silently dropping it would be a worse bug than the collision.
    """

    class _Anonymous:
        pass

    anonymous = _Anonymous()
    base = (anonymous,)
    executor = _FakeExecutor(base)
    attachment = _shadowing_attachment(executor, base, (_NamedTool("fetch", "new"),))

    await attachment.attach(uuid4())

    assert anonymous in executor.tools
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/application/test_knowledge_attachment.py -v -k shadow or same_name or restores`
Expected: FAIL — two tools named `fetch` reach the executor.

- [ ] **Step 3: Write the implementation**

In `research_team/application/knowledge_attachment.py`, add a module-level helper above the `TurnExecutorTools` protocol:

```python
def _compose(base: Sequence[Any], attached: Sequence[Any]) -> list[Any]:
    """`base` and `attached`, with an attached tool replacing a base one of
    the same name.

    `fetch` is the reason this exists. It is built once at composition with no
    project, and a corpus-aware version of it can only be built once a project
    is known -- which is here. Both are called `fetch`, so without shadowing
    the executor would hold two tools of one name and which one the model
    reached would be an accident of ordering.

    The alternative was handing the base tool a mutable slot for the current
    project's corpus. That fails on `detach`: nothing would clear the slot, so
    a session that left a project would keep reading its sources. Shadowing
    makes that impossible rather than merely discouraged, because restoring
    the base set is something `detach` already does.

    Anything without a `.name` cannot collide and is kept.
    """
    shadowed = {name for tool in attached if (name := getattr(tool, "name", None))}
    kept = [tool for tool in base if getattr(tool, "name", None) not in shadowed]
    return [*kept, *attached]
```

Then in `attach`, replace:

```python
        self._executor.set_tools([*self._base_tools, *tools])
```

with:

```python
        self._executor.set_tools(_compose(self._base_tools, tools))
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/application/test_knowledge_attachment.py -v`
Expected: PASS, all of them — including the pre-existing ones, which assert the knowledge tools arrive and are removed on detach.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format research_team/application/knowledge_attachment.py tests/application/test_knowledge_attachment.py
uv run ruff check research_team/application/knowledge_attachment.py tests/application/test_knowledge_attachment.py
git add research_team/application/knowledge_attachment.py tests/application/test_knowledge_attachment.py
git commit -m "feat: an attached tool shadows a base tool of the same name

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `fetch` consults corpus, then memo, then network

**Files:**
- Modify: `research_team/infrastructure/agent/corpus_tools.py:101` (`_bounded` → `bounded`) and `:161` (its call site)
- Modify: `research_team/infrastructure/agent/fetch.py`
- Test: `tests/infrastructure/test_fetch.py`

**Interfaces:**
- Consumes: `Recall`, `normalize_url`, `describe_age` from Task 2; `CorpusReadPort`, `StoredDocument` from `research_team.application.corpus_read`; `format_document`, `bounded` from `corpus_tools`.
- Produces: `build_fetch_tool(*, max_chars=MAX_CHARS, max_bytes=MAX_BYTES, client=None, recall: Recall | None = None, corpus: CorpusReadPort | None = None)` — Task 6 passes both.

- [ ] **Step 1: Make `_bounded` public**

In `research_team/infrastructure/agent/corpus_tools.py`, rename `_bounded` to `bounded` (definition at line 101 and its single call at line 161). Add to its docstring:

```
    Public because `fetch` returns corpus hits through `format_document` too,
    and two implementations of the offset contract would eventually disagree
    -- which is the exact failure this module's docstring says is worse than
    having no offsets at all.
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/infrastructure/test_fetch.py`:

```python
# ---------------- recall ----------------


class _StubCorpus:
    """A `CorpusReadPort` over a fixed set of documents."""

    def __init__(self, documents=(), error=None):
        self._documents = list(documents)
        self._error = error
        self.reads: list[str] = []

    async def list_documents(self):
        if self._error:
            raise self._error
        return [document.record for document in self._documents]

    async def read_document(self, source_id):
        if self._error:
            raise self._error
        self.reads.append(source_id)
        for document in self._documents:
            if document.record.source_id == source_id:
                return document
        return None


def _stored(source_id: str, uri: str, text: str = "stored prose") -> StoredDocument:
    return StoredDocument(
        record=DocumentRecord(
            source_id=source_id,
            sha256="0" * 64,
            char_count=len(text),
            uri=uri,
            title="Stored",
        ),
        text=text,
    )


def _counting(counter: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(200, html=ARTICLE)

    return handler


@pytest.mark.asyncio
async def test_a_page_already_in_the_corpus_is_not_fetched_again():
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus, recall=Recall())

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert calls == []
    assert "stored prose" in text


@pytest.mark.asyncio
async def test_a_corpus_hit_comes_back_citable():
    """The reason the corpus is consulted before the memo: a stored hit
    carries `source_id@start-end`, and a page read off the wire carries no
    identifier anything downstream can point at.
    """
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_html_response), corpus=corpus)

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert "s1@0-" in text


@pytest.mark.asyncio
async def test_a_corpus_hit_matches_an_equivalent_url():
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await fetch.ainvoke({"url": "HTTPS://Ex.Example:443/sev#top"})

    assert calls == []


@pytest.mark.asyncio
async def test_the_same_page_twice_is_fetched_once():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_recalled_page_says_it_is_recalled_and_how_old():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    again = await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert "recalled" in again.lower()
    assert "ago" in again or "just now" in again


@pytest.mark.asyncio
async def test_refresh_reaches_the_network_past_both():
    """A tool that cannot be asked for a fresh read does not stop the request
    -- it makes the agent reach for a cache-busting query parameter, which
    arrives at the same server in a form nothing can recognise or count.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus, recall=Recall())

    await fetch.ainvoke({"url": "https://ex.example/sev"})
    await fetch.ainvoke({"url": "https://ex.example/sev", "refresh": True})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_dropped_or_absent_page_still_reaches_the_network():
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/other")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_document_stored_without_a_uri_never_matches():
    """Most of the corpus looks like this today. It must be a miss, not a
    match on the empty string.
    """
    calls: list[int] = []
    document = _stored("s1", "https://ex.example/sev")
    document = StoredDocument(
        record=document.record.model_copy(update={"uri": None}), text=document.text
    )
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=_StubCorpus([document]))

    await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_an_unreadable_corpus_falls_through_to_the_network():
    """A storage failure must not cost the fetch. The corpus is an
    optimisation here, and an optimisation that can break the operation is
    not one.
    """
    calls: list[int] = []
    fetch = build_fetch_tool(
        client=_client(_counting(calls)),
        corpus=_StubCorpus(error=CorpusReadError("neo4j down")),
    )

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 1
    assert "revenue critical path" in text


@pytest.mark.asyncio
async def test_a_failed_fetch_is_not_remembered():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, html=ARTICLE)

    fetch = build_fetch_tool(client=_client(handler), recall=Recall())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    second = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 2
    assert "revenue critical path" in second


@pytest.mark.asyncio
async def test_a_project_less_fetch_still_works():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)))
    text = await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert len(calls) == 1
    assert "revenue critical path" in text
```

Add to the imports at the top of the file:

```python
from research_team.application.corpus_read import CorpusReadError, StoredDocument
from research_team.domain import DocumentRecord
from research_team.infrastructure.agent.recall import Recall
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `uv run pytest tests/infrastructure/test_fetch.py -v -k corpus or recall or refresh`
Expected: FAIL — `build_fetch_tool` rejects the `corpus` keyword.

- [ ] **Step 4: Write the implementation**

In `research_team/infrastructure/agent/fetch.py`, add imports:

```python
from research_team.application.corpus_read import CorpusReadError, CorpusReadPort
from research_team.infrastructure.agent.corpus_tools import bounded, format_document
from research_team.infrastructure.agent.recall import Recall, describe_age, normalize_url
```

Add this helper above `build_fetch_tool`:

```python
async def stored_page(corpus: CorpusReadPort, url: str, max_chars: int) -> str | None:
    """This page as the corpus already holds it, or None.

    Matched on `normalize_url` rather than on the stored string, so a URL that
    differs only in scheme case, a default port or a fragment is recognised as
    the same page. Scanning `list_documents` is O(corpus) per call; a corpus
    holds hundreds of records at most and the scan is a local read-model
    query, so an index would be machinery bought against a cost nobody has
    measured.

    A storage failure returns None rather than propagating. The corpus is an
    optimisation on this path, and an optimisation that can break the
    operation it accelerates is not one -- a Neo4j outage should cost a
    redundant fetch, not the page.
    """
    target = normalize_url(url)
    try:
        records = await corpus.list_documents()
    except CorpusReadError:
        return None
    match = next(
        (record for record in records if record.uri and normalize_url(record.uri) == target),
        None,
    )
    if match is None:
        return None
    try:
        document = await corpus.read_document(match.source_id)
    except CorpusReadError:
        return None
    if document is None:
        # Listed and then unreadable: a drop landed between the two calls.
        return None
    span = bounded(document.text, None, None, max_chars)
    return (
        "[recalled -- this page is already in this project's corpus, so it was "
        "not fetched again. Quote it from here; the offsets below are real.]\n\n"
        + format_document(document, span)
    )
```

Change the signature of `build_fetch_tool` to:

```python
def build_fetch_tool(
    *,
    max_chars: int = MAX_CHARS,
    max_bytes: int = MAX_BYTES,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
    corpus: CorpusReadPort | None = None,
) -> BaseTool:
```

Change the tool signature and add the two lookups. The tool becomes:

```python
    @tool(FETCH_TOOL)
    async def fetch(url: str, refresh: bool = False) -> str:
        """Read one web page and return its main content as markdown text."""
        scheme = urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            return (
                f"Only http and https URLs can be fetched; {scheme or 'that'} is not "
                "one. Use the file tools to read the workspace."
            )
        if not refresh:
            # Corpus before memo: both avoid the request, and only one comes
            # back with offsets a claim can cite.
            if corpus is not None:
                found = await stored_page(corpus, url, max_chars)
                if found is not None:
                    return found
            if recall is not None:
                remembered = recall.get(url, key=normalize_url(url))
                if remembered is not None:
                    return (
                        f"[recalled -- read {describe_age(remembered.age_seconds)} in "
                        f"this process, not a fresh read. Pass refresh=True if the "
                        f"page is expected to have changed since.]\n\n{remembered.text}"
                    )
        owned = client is None
        http = client or httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, headers=_HEADERS
        )
        try:
            response = await http.get(url, headers=_HEADERS)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            media_type = content_type.split(";")[0].strip().lower()
            if media_type and "html" not in media_type and "xml" not in media_type:
                return (
                    f"That URL returned {media_type}, which this tool cannot read -- "
                    "it reads HTML pages. No text this time."
                )
            body = response.content[:max_bytes]
            truncated = len(response.content) > max_bytes
            html = body.decode(response.encoding or "utf-8", errors="replace")
            text = format_page(html, url, limit=max_chars)
            if truncated and text is not UNREADABLE and not text.endswith(_TRUNCATED):
                text += _TRUNCATED
            if recall is not None and text is not UNREADABLE:
                # Only a page that was actually read. Remembering a failure
                # would turn one outage into an hour of them, and remembering
                # UNREADABLE would pin "this renders in the browser" for an
                # hour after a deploy fixed it.
                recall.put(url, text, key=normalize_url(url))
            return text
        except httpx.HTTPStatusError as error:
            return (
                f"Could not read that page: the server returned {error.response.status_code}."
            )
        except httpx.HTTPError as error:
            return f"Could not reach that page: {error}"
        except UnicodeError as error:
            return f"Could not decode that page: {error}"
        finally:
            if owned:
                await http.aclose()
```

- [ ] **Step 5: Update `FETCH_PROMPT`**

Replace the final paragraph of `FETCH_PROMPT` (the one beginning "Fetch when a search snippet") with:

```python
    "Fetch when a search snippet is not enough to make a claim you would be "
    "willing to cite, and not to confirm something the snippet already said "
    "plainly.\n\n"
    "You do not have to track what you have already read. A page this project "
    "has stored comes back from the corpus, with the offsets that make it "
    "quotable; a page read earlier in this process comes back as it was, "
    "marked as recalled and dated. Both say so plainly. If a page is expected "
    "to have changed since -- a changelog, a status page, a document revised "
    "during this run -- pass `refresh=True` and it will be read again. Do not "
    "pass it merely to be sure.\n\n"
    "When a fetched page is worth keeping, pass it to `remember` along with "
    "the `url:`, `title:` and `date:` lines printed above it. That is what "
    "lets a later session recognise the page instead of fetching it again."
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest tests/infrastructure/test_fetch.py tests/infrastructure/test_corpus_tools.py -v`
Expected: PASS, all of them. `test_corpus_tools.py` is included because Step 1 renamed a function it may reference.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format research_team/infrastructure/agent/fetch.py research_team/infrastructure/agent/corpus_tools.py tests/infrastructure/test_fetch.py
uv run ruff check research_team/infrastructure/agent/fetch.py research_team/infrastructure/agent/corpus_tools.py tests/infrastructure/test_fetch.py
git add research_team/infrastructure/agent/fetch.py research_team/infrastructure/agent/corpus_tools.py tests/infrastructure/test_fetch.py
git commit -m "feat: fetch reads the corpus and the memo before the network

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire it together in composition

**Files:**
- Modify: `research_team/composition.py:316` (base `fetch`), `:321` (`web_search`), and the `open_graph` closure around `:560-592`
- Test: `tests/infrastructure/test_deep_agent.py` is the closest existing composition test; no new test file. Verification is by the checks below plus the tests already written.

**Interfaces:**
- Consumes: `Recall` (Task 2), `build_search_tool(recall=)` (Task 3), shadowing (Task 4), `build_fetch_tool(recall=, corpus=)` (Task 5).
- Produces: nothing.

- [ ] **Step 1: Build one shared `Recall`**

In `research_team/composition.py`, add the import:

```python
from research_team.infrastructure.agent.recall import Recall
```

Immediately above the `tools: tuple[BaseTool, ...] = (build_fetch_tool(),)` line at `:316`, add:

```python
    # One memo for both network tools and for every session this application
    # serves. Process-wide rather than per-session because `build_fetch_tool`
    # is called once here -- and correct at that scope for the same reason it
    # is safe: it holds only responses from public URLs, which are the same
    # bytes whoever asked. Nothing project-scoped may ever go in it.
    recall = Recall()
```

Change line 316 to:

```python
    tools: tuple[BaseTool, ...] = (build_fetch_tool(recall=recall),)
```

and the `build_search_tool` call at 321 to:

```python
        tools += (build_search_tool(searxng, limit=config.searxng_results(), recall=recall),)
```

- [ ] **Step 2: Attach a corpus-aware `fetch` per project**

In the `open_graph` closure, `reader = ProjectCorpusReader(corpus, target_project_id)` already exists. Change the returned tool tuple to lead with a project-scoped `fetch`:

```python
        return knowledge, (
            # Shadows the base `fetch` for as long as this project is attached
            # -- see `_compose` in `knowledge_attachment.py`. It is the same
            # tool with one more place to look: this project's own sources,
            # which is the only lookup that can return something citable.
            build_fetch_tool(recall=recall, corpus=reader),
        )
        + build_knowledge_tools(knowledge)
        + build_corpus_tools(reader)
        + build_topic_tools(topic_port, target_project_id)
```

Take care with the parenthesisation — the existing expression is a single
parenthesised sum. The safest edit is to introduce a local first:

```python
        project_fetch = build_fetch_tool(recall=recall, corpus=reader)
        return knowledge, (
            (project_fetch,)
            + build_knowledge_tools(knowledge)
            + build_corpus_tools(reader)
            + build_topic_tools(topic_port, target_project_id)
        )
```

- [ ] **Step 3: Verify composition still builds**

Run: `uv run python -c "from research_team.composition import build_application; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the affected tests**

Run: `uv run pytest tests/infrastructure/test_deep_agent.py tests/application/test_knowledge_attachment.py tests/infrastructure/test_fetch.py tests/infrastructure/test_search.py tests/infrastructure/test_recall.py tests/infrastructure/test_knowledge_tools.py tests/infrastructure/test_corpus_tools.py -v`
Expected: PASS. Do not run the full suite.

- [ ] **Step 5: Lint everything and commit**

```bash
uv run ruff format .
uv run ruff check .
git add -A
git commit -m "feat: wire recall through composition, corpus-aware fetch per project

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Spec §1 → Task 1. §2 → Task 2. §3 (normalization boundary) → Task 2, with the two parametrized boundary tests. §4 (fetch/search consult recall, hit labelling, `refresh`) → Tasks 3 and 5. "The structural change" → Task 4, with the rejected resolver-callable alternative recorded in `_compose`'s docstring. "Prompts" → prompt steps in Tasks 1, 3 and 5. "What this does not do" → nothing is built for any of it; the missing-URI check is explicitly absent. "Testing" → every bullet has a named test.

**Placeholders.** None. Every code step carries the actual code; no "similar to Task N"; no "add error handling."

**Type consistency.** `Recall.get`/`put` take `key=` in Task 2 and are called with `key=normalize_url(url)` in Task 5 and without it in Task 3. `Recalled` fields `text`/`asked`/`age_seconds` are used consistently in Tasks 3 and 5. `bounded` is renamed in Task 5 Step 1 before Task 5 Step 4 imports it. `build_fetch_tool` gains `recall` and `corpus` in Task 5 and is called with both only in Task 6, which runs after.

**One ordering hazard worth flagging to executors:** Task 5 imports `corpus_tools` from `fetch.py`. `corpus_tools.py` does not import `fetch.py`, so there is no cycle — but do not add one.
