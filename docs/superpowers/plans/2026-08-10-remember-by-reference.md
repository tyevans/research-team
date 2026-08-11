# Remember By Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `remember_page(url, source_id, note)`, which commits a fetched page to the corpus and graph by resolving its text and provenance from what `fetch` retained, instead of requiring the model to retype the document.

**Architecture:** `fetch` gains a second process-wide store, `PageMemo`, holding a typed `RetainedPage` (untruncated text, `uri`, `title`, `published_at`, `fetched_at`). The existing `Recall` is untouched and keeps serving the truncated string the model sees. `remember_page` resolves against `PageMemo` by the existing `url_key`, builds a fully populated `SourceRef`, and delegates to the same `KnowledgePort.ingest` that `remember` uses. No new event, no new projection, no schema change.

**Tech Stack:** Python 3.13, `uv`, pytest, langchain `@tool`, eventsource-py. No new dependencies.

## Global Constraints

- **No test may touch the network.** Every fetch test stubs `httpx.AsyncClient`. Follow the existing pattern in `tests/infrastructure/test_fetch.py`.
- **Do not run the full test suite.** Run only the test files named in each task. CI runs the suite at PR time.
- **Both ruff gates run over the whole repository**, not the files you touched: `uv run ruff check .` and `uv run ruff format --check .`. An unsorted import in a test fails CI.
- **No event shape changes.** `fetched_at` already exists on `StoreSourceDocument` (`domain/corpus.py:101`), `SourceDocumentStored` (`:70`) and `CorpusDocumentRow` (`read_models.py:597`). If you find yourself editing `domain/corpus.py`'s event, stop — the plan is wrong, not the event.
- **`Recall` is not modified.** It is shared with `web_search`; widening it puts always-absent fields on every search entry. All existing `Recall` tests must pass untouched.
- **Nothing project-scoped may enter `PageMemo`.** It is process-wide and shared across projects, exactly as `Recall` is (`composition.py:491-495`). Only bytes from public URLs.
- **`remember` is unchanged.** Its signature, behaviour and all six of its tests in `tests/infrastructure/test_knowledge_tools.py` stay as they are.
- **House style:** module and function docstrings carry the *reasoning* behind a decision, not a restatement of the code. Comments explain why, state costs plainly, and name what a test would fail on.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `research_team/infrastructure/agent/recall.py` | Add `RetainedPage` and `PageMemo` beside the existing `Recall`. Shares `url_key`, `CAPACITY`, `TTL_SECONDS`. |
| `research_team/infrastructure/agent/fetch.py` | Split truncation from retention; write the full extraction to `PageMemo` alongside the `Recall` write. Prompt text. |
| `research_team/application/knowledge.py` | `SourceRef.fetched_at`; `REMEMBER_PAGE_TOOL` constant. |
| `research_team/infrastructure/knowledge/redstring_adapter.py` | Pass `fetched_at` through to `StoreSourceDocument`. |
| `research_team/infrastructure/agent/knowledge_tools.py` | The `remember_page` tool; prompt text. |
| `research_team/application/autonomy.py` | `remember_page` joins `GATED_TOOLS`. |
| `research_team/composition.py` | Build one `PageMemo`, hand it to both `fetch` builds and to `build_knowledge_tools`. |
| `tests/infrastructure/test_page_memo.py` | **New.** `PageMemo` and `RetainedPage`. |
| `tests/infrastructure/test_fetch.py` | Retention behaviour. |
| `tests/infrastructure/test_knowledge_tools.py` | `remember_page`. |
| `tests/infrastructure/test_redstring_adapter.py` | `fetched_at` reaches the command. |

---

### Task 1: `PageMemo` holds a page as a record

**Files:**
- Modify: `research_team/infrastructure/agent/recall.py` (append after `Recall`, which ends at :203)
- Test: `tests/infrastructure/test_page_memo.py` (new)

**Interfaces:**
- Consumes: `url_key`, `CAPACITY`, `TTL_SECONDS` from `recall.py`.
- Produces: `RetainedPage(text: str, uri: str, title: str | None, published_at: str | None, fetched_at: str)`; `PageMemo(*, capacity: int = CAPACITY, ttl_seconds: float = TTL_SECONDS, clock: Callable[[], float] = time.monotonic, stamp: Callable[[], str] = _utc_now)` with `get(url: str) -> RetainedPage | None` and `put(url: str, *, text: str, uri: str, title: str | None = None, published_at: str | None = None) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_page_memo.py`:

```python
"""What `fetch` retains for `remember_page`, as against what it shows the model."""

from research_team.infrastructure.agent.recall import PageMemo, RetainedPage


def test_a_retained_page_comes_back_whole() -> None:
    """The retained text is the document, not the excerpt the model was shown.

    This is the point of the store: `Recall` holds the truncated string, and a
    corpus that could only ever receive that string was capped at the context
    budget rather than at its own limit.
    """
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put("https://example.com/a", text="whole document", uri="https://example.com/a")

    retained = memo.get("https://example.com/a")

    assert retained is not None
    assert retained.text == "whole document"


def test_provenance_is_stored_not_reparsed() -> None:
    """title and published_at arrive as fields, so nothing has to read them back
    out of a citation header a page's own prose could imitate."""
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put(
        "https://example.com/a",
        text="body",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
    )

    retained = memo.get("https://example.com/a")

    assert retained == RetainedPage(
        text="body",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
        fetched_at="2026-08-10T12:00:00+00:00",
    )


def test_fetched_at_is_stamped_at_write_time() -> None:
    """A wall-clock stamp, because the expiry clock is `time.monotonic` and has
    no zero to convert an age against. Without this the field cannot be filled
    honestly at ingest, and a guessed timestamp is worse than the None it
    replaces."""
    stamps = iter(["2026-08-10T12:00:00+00:00", "2026-08-10T13:00:00+00:00"])
    memo = PageMemo(stamp=lambda: next(stamps))

    memo.put("https://example.com/a", text="a", uri="https://example.com/a")
    memo.put("https://example.com/b", text="b", uri="https://example.com/b")

    first = memo.get("https://example.com/a")
    second = memo.get("https://example.com/b")
    assert first is not None and second is not None
    assert first.fetched_at == "2026-08-10T12:00:00+00:00"
    assert second.fetched_at == "2026-08-10T13:00:00+00:00"


def test_a_url_that_was_never_retained_is_a_miss() -> None:
    memo = PageMemo()

    assert memo.get("https://example.com/missing") is None


def test_equivalent_urls_are_one_entry() -> None:
    """Keyed by `url_key`, so a handle and a corpus hit agree about what the
    same page is. Fails if this grows its own normalization."""
    memo = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    memo.put("https://Example.com:443/a#frag", text="body", uri="https://example.com/a")

    assert memo.get("https://example.com/a") is not None


def test_an_expired_page_is_a_miss() -> None:
    """An hour-old handle does not resolve, and that is ordinary operation --
    `remember_page` is expected to say so rather than store nothing quietly."""
    now = 0.0
    memo = PageMemo(ttl_seconds=10.0, clock=lambda: now, stamp=lambda: "t")
    memo.put("https://example.com/a", text="body", uri="https://example.com/a")

    now = 11.0

    assert memo.get("https://example.com/a") is None


def test_the_coldest_entry_is_evicted_when_full() -> None:
    memo = PageMemo(capacity=2, stamp=lambda: "t")
    memo.put("https://example.com/1", text="1", uri="https://example.com/1")
    memo.put("https://example.com/2", text="2", uri="https://example.com/2")
    memo.get("https://example.com/1")
    memo.put("https://example.com/3", text="3", uri="https://example.com/3")

    assert memo.get("https://example.com/2") is None
    assert memo.get("https://example.com/1") is not None
    assert memo.get("https://example.com/3") is not None


def test_a_second_put_replaces_the_first() -> None:
    """A refreshed read supersedes what was retained, so `remember_page` after
    `refresh=True` commits the new bytes rather than the old."""
    memo = PageMemo(stamp=lambda: "t")
    memo.put("https://example.com/a", text="old", uri="https://example.com/a")
    memo.put("https://example.com/a", text="new", uri="https://example.com/a")

    retained = memo.get("https://example.com/a")

    assert retained is not None
    assert retained.text == "new"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_page_memo.py -v`
Expected: FAIL — `ImportError: cannot import name 'PageMemo'`.

- [ ] **Step 3: Implement `RetainedPage` and `PageMemo`**

Append to `research_team/infrastructure/agent/recall.py`. Add `from datetime import UTC, datetime` to the imports at the top of the file (alphabetically before `from collections import OrderedDict`... follow ruff's isort ordering; run the formatter if unsure).

```python
def _utc_now() -> str:
    """The wall-clock moment a page was read, as text.

    Text rather than a `datetime` because that is what it becomes:
    `SourceDocumentStored.fetched_at` is a `str | None`, matching
    `published_at`, which is text because sources report dates in whatever
    shape they please. Converting here and back would buy nothing.
    """
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class RetainedPage:
    """One page as `fetch` read it, kept for `remember_page`.

    Distinct from `Recalled` in the two ways that matter. `text` is the whole
    extraction rather than the excerpt the model was shown, so the corpus is
    capped by its own limit rather than by the context budget. And the
    provenance is fields, not a citation header to be parsed back out -- a page
    whose own prose opens with something header-shaped would otherwise be
    stored under whatever that text claimed.
    """

    text: str
    uri: str
    title: str | None
    published_at: str | None
    fetched_at: str


class PageMemo:
    """What `fetch` retained, by URL, for as long as the process lives.

    Separate from `Recall` rather than an extension of it. `Recall` is shared
    with `web_search`, whose entries are flattened result blocks with no `uri`,
    no title and no fetch time; widening it would put four permanently-absent
    fields on every search entry. The cost of the split is this class's
    eviction logic, which is `Recall`'s again -- paid to keep one store with
    one value type serving two tools.

    Process-wide and shared across projects, under `Recall`'s invariant and for
    its reason: this holds only responses from public URLs, which are the same
    bytes whoever asked. **Nothing project-scoped may ever go in it** -- a
    project-derived value here would turn a shared cache into a cross-project
    read.

    Not persistent. A durable record of every page ever fetched would make
    fetching permanent, which `remember`'s own prompt says it is not. Retaining
    more text in an ephemeral store is not that; retaining it across restarts
    would be.
    """

    def __init__(
        self,
        *,
        capacity: int = CAPACITY,
        ttl_seconds: float = TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        stamp: Callable[[], str] = _utc_now,
    ) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._stamp = stamp
        self._entries: OrderedDict[str, tuple[RetainedPage, float]] = OrderedDict()

    def get(self, url: str) -> RetainedPage | None:
        """The page retained for `url`, or None if it was never read here,
        has expired, or was evicted. All three are ordinary."""
        key = url_key(url)
        entry = self._entries.get(key)
        if entry is None:
            return None
        page, stored_at = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return page

    def put(
        self,
        url: str,
        *,
        text: str,
        uri: str,
        title: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Retain `url`'s full text and provenance, evicting the coldest if full."""
        key = url_key(url)
        self._entries[key] = (
            RetainedPage(
                text=text,
                uri=uri,
                title=title,
                published_at=published_at,
                fetched_at=self._stamp(),
            ),
            self._clock(),
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_page_memo.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Confirm `Recall` is untouched**

Run: `uv run pytest tests/infrastructure/test_recall.py -v`
Expected: PASS, unchanged.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/infrastructure/agent/recall.py tests/infrastructure/test_page_memo.py
uv run ruff check .
uv run ruff format --check .
git add research_team/infrastructure/agent/recall.py tests/infrastructure/test_page_memo.py
git commit -m "$(cat <<'EOF'
Retain a fetched page as a record, beside what the model was shown

`Recall` holds the string `fetch` returned: truncated at MAX_CHARS and headed
by a citation block. That is the right thing to hand back to a model and the
wrong thing to commit to a corpus, which accepts ten times as much and wants
the provenance as fields rather than as a header to be parsed back out.

Considered and rejected: widening `Recall` to carry uri, title, published_at
and fetched_at. It is shared with `web_search`, whose entries have none of
those, so every search entry would carry four permanently-absent fields.

Cost: this duplicates `Recall`'s eviction logic. Paid to keep one store with
one value type serving two tools.

`fetched_at` is stamped at write time because the expiry clock is
`time.monotonic` and has no zero to convert an age against.

Nothing uses this yet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `fetch` retains the whole extraction and still shows 20,000 characters

**Files:**
- Modify: `research_team/infrastructure/agent/fetch.py` — `format_page` (:71-95), `build_fetch_tool` (:170-253)
- Test: `tests/infrastructure/test_fetch.py`

**Interfaces:**
- Consumes: `PageMemo`, `RetainedPage` from Task 1.
- Produces: `build_fetch_tool(..., pages: PageMemo | None = None)`; `extract_page(html: str, url: str) -> tuple[str, str | None, str | None] | None` returning `(full_markdown, title, date)` or `None` when there is no readable prose; `truncate_page(citation: str, text: str, limit: int) -> str`.

**Note on `format_page`:** it stays, with its signature and behaviour intact — `test_fetch.py:58-110` pins it and other call sites read it. It is reimplemented in terms of the two new functions so the truncated string and the retained text cannot drift apart.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_fetch.py`. Match the file's existing stub-client pattern.

```python
def test_the_whole_page_is_retained_though_only_part_is_shown() -> None:
    """The model's budget stops being the corpus's ceiling.

    MAX_CHARS is documented as what one page may cost the conversation. Because
    a document could only reach the corpus through the model's own output, it
    was also the most the corpus could ever hold of a fetched page -- against a
    corpus that accepts 200_000.
    """
    body = "<html><body><p>" + ("word " * 4000) + "</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(
        max_chars=100, client=_client(body), pages=pages
    )

    shown = asyncio.run(tool.ainvoke({"url": "https://example.com/long"}))

    retained = pages.get("https://example.com/long")
    assert retained is not None
    assert len(retained.text) > len(shown)
    assert "[truncated" not in retained.text


def test_the_retained_text_carries_no_citation_header() -> None:
    """The header is for the model to read. The corpus stores it as fields, and
    a document whose first line is `url: ...` would quote back as though the
    page said it."""
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_client(body), pages=pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert not retained.text.startswith("url:")


def test_retained_provenance_matches_the_header_the_model_saw() -> None:
    """One extraction feeds both, so the fields and the header cannot disagree."""
    body = (
        "<html><head><title>A Paper</title>"
        '<meta property="article:published_time" content="2026-01-02"/>'
        "</head><body><p>Real prose here, at length.</p></body></html>"
    )
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_client(body), pages=pages)

    shown = asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert retained.uri == "https://example.com/a"
    assert retained.title == "A Paper"
    assert retained.title is not None and retained.title in shown


def test_an_unreadable_page_is_not_retained() -> None:
    """For UNREADABLE's existing reason: retaining it would pin "this renders in
    the browser" for an hour after a deploy fixed it."""
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_client("<html><body></body></html>"), pages=pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/shell"}))

    assert pages.get("https://example.com/shell") is None


def test_a_failed_fetch_is_not_retained() -> None:
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_failing_client(), pages=pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/gone"}))

    assert pages.get("https://example.com/gone") is None


def test_a_corpus_hit_is_not_retained() -> None:
    """Nothing project-scoped may enter a process-wide store. A corpus hit is
    one project's stored text; retaining it would serve it to another project's
    `remember_page`."""
    pages = PageMemo(stamp=lambda: "t")
    corpus = _corpus_holding("s1", text="stored body", uri="https://example.com/a")
    tool = build_fetch_tool(client=_client("<html/>"), corpus=corpus, pages=pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))

    assert pages.get("https://example.com/a") is None


def test_a_recall_hit_does_not_disturb_what_was_retained() -> None:
    """The memo answers the second fetch without a request, so nothing is
    re-retained and the first retention stands."""
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    recall = Recall()
    tool = build_fetch_tool(client=_client(body), recall=recall, pages=pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))
    asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert "Real prose" in retained.text


def test_refresh_replaces_what_was_retained() -> None:
    tool_pages = PageMemo(stamp=lambda: "t")
    client = _client_returning(
        "<html><body><p>First body, long enough.</p></body></html>",
        "<html><body><p>Second body, long enough.</p></body></html>",
    )
    tool = build_fetch_tool(client=client, recall=Recall(), pages=tool_pages)

    asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))
    asyncio.run(tool.ainvoke({"url": "https://example.com/a", "refresh": True}))

    retained = tool_pages.get("https://example.com/a")
    assert retained is not None
    assert "Second body" in retained.text
```

Add to the file's imports: `from research_team.infrastructure.agent.recall import PageMemo, Recall` (merge with the existing `recall` import line if one is present).

**Helpers:** `_client`, `_failing_client`, `_corpus_holding` and `_client_returning` are the stub builders this file already uses. Reuse the existing ones by their real names — read the top of `tests/infrastructure/test_fetch.py` and adapt these calls to whatever they are actually called. If a two-response stub client does not exist, add one modelled on the existing single-response stub.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_fetch.py -v -k "retain or whole_page or disturb"`
Expected: FAIL — `build_fetch_tool() got an unexpected keyword argument 'pages'`.

- [ ] **Step 3: Split extraction from truncation**

Replace `format_page` (`fetch.py:71-95`) with three functions. `_citation` (`:98-118`) is refactored to take already-extracted metadata rather than re-reading it, so one extraction feeds both outputs.

```python
def extract_page(html: str, url: str) -> tuple[str, str | None, str | None] | None:
    """One page's main content and metadata, or None when there is no prose.

    Split out of `format_page` so the text kept for `remember_page` and the
    text shown to the model come from a single extraction. Two extractions
    would eventually disagree, and the disagreement would surface as a corpus
    document that does not match the citation the model was reading from.

    Metadata is best-effort for `_citation`'s original reason: it reaches into
    a foreign document, and a page with no title is worth reading anyway.
    """
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )
    if not text or not text.strip():
        return None
    title = date = None
    try:
        metadata = extract_metadata(html)
    except Exception:  # noqa: BLE001 - foreign parser; absent metadata is not a failure
        metadata = None
    if metadata is not None:
        title = (getattr(metadata, "title", None) or "").strip() or None
        date = (getattr(metadata, "date", None) or "").strip() or None
    return text.strip(), title, date


def _citation(url: str, title: str | None, date: str | None) -> str:
    """A `url` line, plus title and date when the page offered them.

    The URL leads the output because the citation is the reason for fetching.
    Text that arrives without its address cannot be cited by anything
    downstream, and a model that has lost a source will confabulate one rather
    than say so.
    """
    lines = [f"url: {url}"]
    if title:
        lines.append(f"title: {title}")
    if date:
        lines.append(f"date: {date}")
    return "\n".join(lines)


def format_page(html: str, url: str, limit: int = MAX_CHARS) -> str:
    """Extract one page's main content as markdown, headed by its citation.

    Total by construction: a server can send anything at all under a
    `text/html` content type, and an app shell that extracts to nothing is an
    ordinary thing for the web to be rather than an exception for the agent to
    reason about. Both arrive here as `None` from `extract_page` and leave as
    the same sentence.
    """
    extracted = extract_page(html, url)
    if extracted is None:
        return UNREADABLE
    text, title, date = extracted
    if len(text) > limit:
        text = text[:limit].rstrip() + _TRUNCATED
    return "\n\n".join(part for part in (_citation(url, title, date), text) if part)
```

- [ ] **Step 4: Retain inside the tool**

In `build_fetch_tool`, add `pages: PageMemo | None = None` to the signature (`fetch.py:170-177`) and document it in the docstring alongside `client`.

Replace the success block (`fetch.py:226-238`) with:

```python
            body = response.content[:max_bytes]
            truncated = len(response.content) > max_bytes
            html = body.decode(response.encoding or "utf-8", errors="replace")
            extracted = extract_page(html, url)
            if extracted is None:
                return UNREADABLE
            full, title, date = extracted
            if pages is not None:
                # The whole extraction, not the excerpt below it. `max_chars`
                # is what one page may cost the conversation; it was never
                # meant to be what the corpus can hold, and was only ever that
                # because a document could not reach the corpus except through
                # the model's own output.
                pages.put(url, text=full, uri=url, title=title, published_at=date)
            shown = full
            if len(shown) > max_chars:
                shown = shown[:max_chars].rstrip() + _TRUNCATED
            text = "\n\n".join(
                part for part in (_citation(url, title, date), shown) if part
            )
            if truncated and not text.endswith(_TRUNCATED):
                text += _TRUNCATED
            if recall is not None:
                # Only a page that was actually read. Remembering a failure
                # would turn one outage into an hour of them.
                recall.put(url, text, key=url_key(url))
            return text
```

Note what this deliberately keeps: the byte-cap marker still lands only on the *shown* string. A page cut at `max_bytes` is retained as far as it was decoded, which is the honest thing to store — the marker is a message to a reader, not part of the document.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_fetch.py -v`
Expected: PASS. Every pre-existing test in the file must still pass — the corpus and recall paths are untouched.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/infrastructure/agent/fetch.py tests/infrastructure/test_fetch.py
uv run ruff check .
uv run ruff format --check .
git add research_team/infrastructure/agent/fetch.py tests/infrastructure/test_fetch.py
git commit -m "$(cat <<'EOF'
Keep the whole page, show the model twenty thousand characters of it

MAX_CHARS is documented as a context budget -- what one page may cost the
conversation it was fetched to inform. In practice it was also the corpus's
ceiling, because a document could not reach the corpus except by the model
retyping it, and the model can only retype what it was shown. The corpus
accepts 200_000.

`extract_page` splits extraction from truncation so both outputs come from one
extraction. Two would eventually disagree, and the disagreement would surface
as a corpus document that does not match the citation the model quoted from.

Not retained: unreadable pages, failed fetches, and corpus hits. The first two
for the reason recall already gives; the third because a corpus hit is one
project's stored text and this store is process-wide.

The byte-cap marker still lands only on the shown string. A page cut at
max_bytes is retained as far as it decoded -- the marker is a message to a
reader, not part of the document.

Nothing reads the retained page yet.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `fetched_at` reaches the stored document

**Files:**
- Modify: `research_team/application/knowledge.py` — `SourceRef` (:28-50)
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py` — the `StoreSourceDocument` construction inside `_store_document` (~:529-537)
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Produces: `SourceRef.fetched_at: str | None = None`.

**No event changes.** `StoreSourceDocument.fetched_at` (`domain/corpus.py:101`) and `SourceDocumentStored.fetched_at` (`:70`) already exist and `decide` already passes it (`:176`). This task connects a wire that was left unconnected.

- [ ] **Step 1: Write the failing test**

Append to `tests/infrastructure/test_redstring_adapter.py`, beside the existing `test_citation_fields_reach_the_source_document` (:492):

```python
async def test_fetched_at_reaches_the_stored_document() -> None:
    """The field has existed on the command and the event since the corpus
    layer landed, and has always been None on this path -- `remember` has no
    argument that could fill it. Fails if the adapter drops it again."""
    adapter, store = _adapter()

    await adapter.ingest(
        SourceRef(
            source_id="s1",
            text="body",
            uri="https://example.com/a",
            fetched_at="2026-08-10T12:00:00+00:00",
        )
    )

    stored = _stored_events(store)[0]
    assert stored.fetched_at == "2026-08-10T12:00:00+00:00"


async def test_a_source_without_a_fetch_time_leaves_it_unset() -> None:
    """`remember` cannot know when text it was handed was read, and a guessed
    timestamp would be worse than the absence it replaced."""
    adapter, store = _adapter()

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    stored = _stored_events(store)[0]
    assert stored.fetched_at is None
```

**Helpers:** `_adapter` and `_stored_events` stand for whatever this file already uses to build an adapter and read back its appended events — read `test_citation_fields_reach_the_source_document` (:492-514) and copy its arrangement exactly rather than inventing one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v -k fetched_at`
Expected: FAIL — `SourceRef.__init__() got an unexpected keyword argument 'fetched_at'`.

- [ ] **Step 3: Add the field**

In `research_team/application/knowledge.py`, append to `SourceRef` after `published_at`:

```python
    fetched_at: str | None = None
    """When this text was read, for content that came off the network.

    Set only by the by-reference path, which is the only caller that knows:
    `remember` is handed text with no way to tell when it was read, and a
    guessed timestamp is worse than the absence it would replace. Text for the
    same reason as `published_at` -- the field it lands in is text.
    """
```

- [ ] **Step 4: Pass it through the adapter**

In `_store_document`, add one line to the `StoreSourceDocument(...)` construction, after `note=source.note,`:

```python
                    fetched_at=source.fetched_at,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: PASS, including every pre-existing test.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/application/knowledge.py research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
uv run ruff check .
uv run ruff format --check .
git add research_team/application/knowledge.py research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
git commit -m "$(cat <<'EOF'
Connect fetched_at, which the command and the event have always had

`StoreSourceDocument.fetched_at` and `SourceDocumentStored.fetched_at` have
existed since the corpus layer landed and have been None on every ingest, because
`remember` has no argument that could fill them. The event schema was already
shaped around provenance a by-value tool cannot carry.

No event changes: this connects a wire, it does not lay one. `remember` still
leaves the field unset, which is correct -- it is handed text with no way to
know when it was read, and a guessed timestamp is worse than an absent one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `remember_page` commits what `fetch` retained

**Files:**
- Modify: `research_team/application/knowledge.py` — tool-name constants (:18-21)
- Modify: `research_team/application/autonomy.py` — `GATED_TOOLS` (:31-40)
- Modify: `research_team/infrastructure/agent/knowledge_tools.py` — `build_knowledge_tools` (:76-145)
- Test: `tests/infrastructure/test_knowledge_tools.py`

**Interfaces:**
- Consumes: `PageMemo`, `RetainedPage` (Task 1); `SourceRef.fetched_at` (Task 3).
- Produces: `REMEMBER_PAGE_TOOL = "remember_page"`; `build_knowledge_tools(knowledge, *, limit=10, report=None, pages: PageMemo | None = None)` now returning four tools when `pages` is given and three when it is not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_knowledge_tools.py`:

```python
def test_remember_page_commits_what_fetch_retained() -> None:
    """The document is not passed. That is the point: a tool that required the
    model to re-emit twenty thousand characters got a summary instead, which
    ingests cleanly and quietly degrades the graph."""
    pages = PageMemo(stamp=lambda: "2026-08-10T12:00:00+00:00")
    pages.put(
        "https://example.com/a",
        text="the whole document",
        uri="https://example.com/a",
        title="A Paper",
        published_at="2026-01-02",
    )
    port = _RecordingKnowledge()
    tools = _by_name(build_knowledge_tools(port, pages=pages))

    asyncio.run(
        tools["remember_page"].ainvoke(
            {"url": "https://example.com/a", "source_id": "s1"}
        )
    )

    assert port.last is not None
    assert port.last.text == "the whole document"
    assert port.last.uri == "https://example.com/a"
    assert port.last.title == "A Paper"
    assert port.last.published_at == "2026-01-02"
    assert port.last.fetched_at == "2026-08-10T12:00:00+00:00"
    assert port.last.source_id == "s1"


def test_remember_page_carries_the_note_the_agent_wrote() -> None:
    """The note is the model's actual contribution and the one argument it is
    right to ask for."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    port = _RecordingKnowledge()
    tools = _by_name(build_knowledge_tools(port, pages=pages))

    asyncio.run(
        tools["remember_page"].ainvoke(
            {"url": "https://example.com/a", "source_id": "s1", "note": "why it matters"}
        )
    )

    assert port.last is not None
    assert port.last.note == "why it matters"


def test_an_unretained_page_names_the_url_and_stores_nothing() -> None:
    """Degrades in band rather than silently. A `remember_page` that quietly
    stored nothing would be indistinguishable from one that worked, and the
    corpus would be missing a document nobody was told about."""
    port = _RecordingKnowledge()
    tools = _by_name(build_knowledge_tools(port, pages=PageMemo()))

    result = asyncio.run(
        tools["remember_page"].ainvoke(
            {"url": "https://example.com/gone", "source_id": "s1"}
        )
    )

    assert port.last is None
    assert "https://example.com/gone" in result
    assert "fetch" in result


def test_remember_page_reports_what_it_recorded() -> None:
    """The same report `remember` returns, from the same formatter -- two
    renderings of one ingest would eventually disagree."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    port = _RecordingKnowledge()
    tools = _by_name(build_knowledge_tools(port, pages=pages))

    result = asyncio.run(
        tools["remember_page"].ainvoke(
            {"url": "https://example.com/a", "source_id": "s1"}
        )
    )

    assert "Recorded s1" in result


def test_a_failure_is_returned_as_text_not_raised() -> None:
    """As `remember` does: a tool that raises turns an outage into a broken
    turn."""
    pages = PageMemo(stamp=lambda: "t")
    pages.put("https://example.com/a", text="body", uri="https://example.com/a")
    port = _FailingKnowledge()
    tools = _by_name(build_knowledge_tools(port, pages=pages))

    result = asyncio.run(
        tools["remember_page"].ainvoke(
            {"url": "https://example.com/a", "source_id": "s1"}
        )
    )

    assert "Could not record this" in result


def test_remember_page_is_absent_without_a_page_memo() -> None:
    """A tool that could never resolve anything is worse than an absent one:
    the model would spend turns on it and be told to fetch a page it had just
    fetched."""
    tools = _by_name(build_knowledge_tools(_RecordingKnowledge()))

    assert "remember_page" not in tools
    assert "remember" in tools


def test_remember_page_is_gated() -> None:
    """A commit is a commit however the bytes arrived. An ungated by-reference
    path would be a way around the gate on the by-value one."""
    from research_team.application.autonomy import GATED_TOOLS, REMEMBER_PAGE_TOOL

    assert REMEMBER_PAGE_TOOL in GATED_TOOLS
```

Add to the file's imports: `from research_team.infrastructure.agent.recall import PageMemo`.

**Helpers:** `_RecordingKnowledge`, `_FailingKnowledge` and `_by_name` stand for whatever this file already uses — read the existing `test_remember_carries_the_provenance_fetch_returned` (:151) and `test_a_failure_is_returned_as_text_not_raised` (:94) and reuse their fixtures under their real names. If the recording double does not expose the last `SourceRef`, extend it rather than writing a second double.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py -v -k remember_page`
Expected: FAIL — `KeyError: 'remember_page'`.

- [ ] **Step 3: Add the tool-name constant**

In `research_team/application/knowledge.py`, after `REMEMBER_TOOL` (:19):

```python
REMEMBER_PAGE_TOOL = "remember_page"
```

- [ ] **Step 4: Gate it**

In `research_team/application/autonomy.py`, add `REMEMBER_PAGE_TOOL` to the import from `knowledge` and to `GATED_TOOLS` beside `REMEMBER_TOOL`, with a comment:

```python
    # Gated beside `remember` for the same reason and not a weaker one: a
    # commit changes what every later session in the project sees, however the
    # bytes reached it. An ungated by-reference path would be a way around the
    # gate on the by-value one.
    REMEMBER_PAGE_TOOL,
```

- [ ] **Step 5: Build the tool**

In `knowledge_tools.py`, add `pages: PageMemo | None = None` to `build_knowledge_tools`'s signature and document it. Add the tool inside the builder, after `remember`:

```python
    @tool(REMEMBER_PAGE_TOOL)
    async def remember_page(url: str, source_id: str, note: str = "") -> str:
        """Commit a page you have already fetched, by its URL, without re-typing it."""
        assert pages is not None  # guarded by the registration below
        retained = pages.get(url)
        if retained is None:
            # In band, naming the URL, rather than storing nothing quietly.
            # A silent no-op is indistinguishable from success, and the corpus
            # would be missing a document nobody was told about.
            return (
                f"Nothing retained for {url} -- it was not read in this process, or was "
                f"read more than an hour ago. `fetch` it, then call this again."
            )
        try:
            ingested = await knowledge.ingest(
                SourceRef(
                    source_id=source_id,
                    text=retained.text,
                    note=note or None,
                    uri=retained.uri,
                    title=retained.title,
                    published_at=retained.published_at,
                    fetched_at=retained.fetched_at,
                ),
                report=report,
            )
        except KnowledgeError as error:
            return f"Could not record this: {error}"
        return format_ingest(ingested)
```

Change the return at `:145` so the tool is registered only when it can work:

```python
    if pages is None:
        # A tool that could never resolve anything is worse than an absent one:
        # the model would spend turns on it and be told to fetch a page it had
        # just fetched.
        return (remember, graph_search, unmerge)
    return (remember, remember_page, graph_search, unmerge)
```

Import `PageMemo` from `research_team.infrastructure.agent.recall` and `REMEMBER_PAGE_TOOL` from `research_team.application.knowledge`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py tests/application/test_autonomy.py -v`
Expected: PASS, including all six pre-existing `remember` tests unchanged.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format research_team/application/knowledge.py research_team/application/autonomy.py research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tools.py
uv run ruff check .
uv run ruff format --check .
git add research_team/application/knowledge.py research_team/application/autonomy.py research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tools.py
git commit -m "$(cat <<'EOF'
Commit a fetched page by its URL, without re-typing it

`remember` asks the model to re-emit up to twenty thousand characters and to
copy back the three citation lines `fetch` printed above them. Its own prompt
has to ask for this in prose -- "pass substantial content you have actually
read rather than your own summary of it" -- which is a missing affordance
described as a compliance problem. A summary ingests cleanly, reports plausible
counts, and quietly degrades the graph.

`remember_page(url, source_id, note)` resolves text and all four provenance
fields from what `fetch` retained. The note stays, because it is the model's
actual contribution; nothing else asked of it here is transcription.

`remember` is unchanged. Search snippets, supplied text and the agent's own
synthesis have no URL to resolve, and a design that removed the by-value path
would trade three real capabilities for symmetry.

An unresolved URL degrades in band, naming it -- #91's decision adopted
unchanged, and for its reason: a silent fallback is indistinguishable from
success. Registered only when a PageMemo exists, since a tool that could never
resolve anything would cost turns to discover.

Gated beside `remember`: a commit is a commit however the bytes arrived.

Not yet wired into composition.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire it, and say so in the prompts

**Files:**
- Modify: `research_team/composition.py` — :496-505, :905-938
- Modify: `research_team/infrastructure/agent/knowledge_tools.py` — `KNOWLEDGE_PROMPT` (:148-168)
- Modify: `research_team/infrastructure/agent/fetch.py` — `FETCH_CORPUS_PROMPT` (:278-285)
- Test: `tests/integration/test_no_knowledge.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_no_knowledge.py`:

```python
async def test_a_project_registers_remember_page() -> None:
    """The by-reference path exists wherever `remember` does. Fails if the
    PageMemo is built but never handed to the knowledge tools -- which would
    leave `remember_page` silently absent and every prompt naming it wrong."""
    app = await _application_with_project()

    names = {tool.name for tool in _tools_of(app)}

    assert "remember_page" in names
    assert "remember" in names
```

**Helpers:** `_application_with_project` and `_tools_of` stand for whatever this file already uses — read `test_a_project_registers_knowledge_tools` (:27) and copy its arrangement.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_no_knowledge.py -v -k remember_page`
Expected: FAIL — `remember_page` not in the tool names.

- [ ] **Step 3: Build one `PageMemo` and share it**

In `composition.py`, beside `recall = Recall()` (:496):

```python
    # One store, shared by both `fetch` builds exactly as `recall` is: it holds
    # only bytes from public URLs, which are the same whoever asked. Nothing
    # project-scoped may ever go in it.
    pages = PageMemo()
```

Pass `pages=pages` to the base `build_fetch_tool` (:497), to the project `build_fetch_tool` (:923), and to `build_knowledge_tools` (:930-934). Import `PageMemo` alongside `Recall` at :100.

- [ ] **Step 4: Rewrite the two prompt passages**

In `knowledge_tools.py`, replace the first two paragraphs of `KNOWLEDGE_PROMPT` (the sentences beginning "`remember` commits text to it" and "When what you are committing came from a page you fetched") with:

```python
    "`remember_page` commits a page you have fetched: give it the page's URL "
    "and a stable `source_id`, and the text and its citation details are taken "
    "from what you already read -- you do not retype the page, and you do not "
    "copy its `url:`, `title:` or `date:` lines across. If the page was read "
    "too long ago to still be held, it will say so and you can `fetch` it "
    "again.\n\n"
    "`remember` is for everything else: text you were given, or a passage you "
    "are recording in your own words. Extraction runs over exactly what you "
    "pass, and the result is recorded permanently.\n\n"
```

In `fetch.py`, replace `FETCH_CORPUS_PROMPT`'s second sentence ("When a fetched page is worth keeping...") with:

```python
    "When a fetched page is worth keeping, call `remember_page` with its URL. "
    "That is what lets a later session recognise the page instead of fetching "
    "it again."
```

Leave the "Committing is not free and not private" paragraph exactly as it is. It is the sentence that makes the decision a decision, and it applies to both paths.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/integration/test_no_knowledge.py tests/infrastructure/test_knowledge_tools.py tests/infrastructure/test_fetch.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole Python suite once**

This task changes composition and prompts, which many tests read.

Run: `uv run pytest`
Expected: PASS. A prompt assertion elsewhere may fail on the changed wording — update it to match the new text; do not weaken it to a substring that would pass either way.

- [ ] **Step 7: All four gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

The frontend gate is run because it is one of the four and CI runs it regardless, not because this task touches the frontend. Do not run two vitest processes at once.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Wire remember_page, and stop asking the model to transcribe

Both prompt constants spent their opening paragraphs asking for transcription:
KNOWLEDGE_PROMPT for the document itself, FETCH_CORPUS_PROMPT for the three
citation lines. Those sentences are now spent naming which tool to use, and the
judgment the model is actually being asked for.

Kept exactly as it was: "Committing is not free and not private -- it changes
what every later session in this project sees." That sentence is what makes the
decision a decision, and it applies to both paths.

One PageMemo is shared by both `fetch` builds and the knowledge tools, as
`recall` already is, under the same invariant: only bytes from public URLs,
nothing project-scoped, ever.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage.** §1 (the handle is a URL) → Task 1 keying and `test_equivalent_urls_are_one_entry`, Task 4's resolution. §2 (a second memo holding a record) → Tasks 1 and 2, including the rejected header-parsing alternative, which Task 1's `test_provenance_is_stored_not_reparsed` pins. §3 (unresolved handles degrade in band) → Task 1's expiry test and Task 4's `test_an_unretained_page_names_the_url_and_stores_nothing`. §4 (`fetched_at`) → Task 3, plus Task 1's stamping test and Task 4's assertion that it arrives. §5 (`remember` unchanged) → asserted in Tasks 3, 4 and 5 by requiring the pre-existing tests to pass untouched. "Ordering" (delegates to the same `ingest`; joins `GATED_TOOLS`) → Task 4. Every "Testing" bullet in the spec maps to a named test above, including the two added during spec review about `Recall` keeping the truncated string and `web_search` being unaffected — those are Task 2's `test_a_recall_hit_does_not_disturb_what_was_retained` and the untouched `tests/infrastructure/test_recall.py` run in Task 1 Step 5.

**Placeholders.** None. Every code step carries the actual code. Four steps name test helpers by placeholder identifiers (`_client`, `_RecordingKnowledge`, `_adapter`, `_application_with_project`) and each says explicitly to read the cited existing test and reuse its real fixtures — this is deliberate, because inventing parallel doubles beside the file's own is how test suites acquire two ways to build the same thing.

**Type consistency.** `PageMemo.get` returns `RetainedPage | None` in Tasks 1, 2 and 4. `put` is keyword-only after `url` throughout. `RetainedPage.uri` is `str` (never `None` — `fetch` always knows the URL it asked for), while `title` and `published_at` are `str | None`, matching `SourceRef`. `fetched_at` is `str` on `RetainedPage` and `str | None` on `SourceRef`, which is correct: the memo always stamps, `remember` never does. `build_knowledge_tools` returns a 3-tuple or a 4-tuple depending on `pages`; Task 4's `test_remember_page_is_absent_without_a_page_memo` pins both arms.

**Ordering hazard worth flagging to executors.** Tasks 1-4 each leave the tree working but inert — nothing calls the new code until Task 5. That is intentional, so each task is independently reviewable, but it means **Task 5 is the first point at which the feature is exercised end to end**, and it is the only task that runs the full suite and all four gates. Do not treat Tasks 1-4 passing as evidence the feature works.

**One thing an executor will be tempted to do and should not.** Task 2 rewrites `format_page` in terms of `extract_page`. It would be simpler to delete `format_page` and inline it. Do not: `tests/infrastructure/test_fetch.py:58-110` tests it directly, and those tests are the only coverage of the citation-header shape that `_citation` produces.
