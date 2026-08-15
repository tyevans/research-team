# Media in the Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A corpus can store, list, drop and stream back a video, audio file or image as a first-class source, with the bytes in a content-addressed blob store and the digest in the event log.

**Architecture:** The event carries the claim (`sha256`, mimetype, byte count, provenance); a filesystem blob store keyed by digest carries the bytes; a new `corpus_media` read-model table answers queries. `CorpusState.documents` becomes a map to a `TextRecord | MediaRecord` union under one `source_id` namespace, so a drop or a citation stays unambiguous.

**Tech Stack:** Python 3.13, `eventsource-py` (DeciderAggregate, DeclarativeProjection), pydantic v2, aiosqlite, FastAPI, pytest; React + TypeScript + zod on the frontend.

**Spec:** `docs/superpowers/specs/2026-08-15-media-in-the-corpus-design.md` — read it before Task 1. The plan argues from it and does not repeat its reasoning.

## Global Constraints

- **Four gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the *whole repository*, not the files you touched.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, say when something was measured rather than reasoned. A comment restating the code is worse than none.
- **Commit messages carry the reasoning that does not fit in a comment** — what was considered and rejected, what the change costs, what is deliberately left undone.
- **Prove a test red before trusting it green.** If a test would pass with the change reverted, say so in its docstring rather than leaving it as reassurance.
- **No backwards compatibility.** Pre-release, no users. Break events, data and contracts rather than migrating. A deliberate break is written down in the field's docstring; a silent one is a bug.
- **An event no projection handles counts as APPLIED, not rejected.** So a missing projection yields a silently EMPTY read model, and any test asserting "the request succeeded" passes with the projection deleted. Every projection test here asserts on a **row**.
- Python: `uv run` for everything. Line length and import order are ruff's; run `uv run ruff format .` before committing.

---

### Task 1: The blob store

Content-addressed byte storage. No domain changes, no events — this task stands alone and is testable alone.

**Files:**
- Create: `research_team/application/blobs.py`
- Create: `research_team/infrastructure/persistence/blob_store.py`
- Modify: `research_team/infrastructure/config.py` (add `blob_root()` beside the database path, ~line 71)
- Test: `tests/infrastructure/test_blob_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `research_team.application.blobs.BlobStat` — frozen dataclass, fields `sha256: str`, `byte_count: int`
  - `research_team.application.blobs.BlobStorePort` — Protocol with `async put(self, stream: AsyncIterator[bytes]) -> BlobStat`, `def open(self, sha256: str) -> AsyncIterator[bytes]`, `async stat(self, sha256: str) -> BlobStat | None`
  - `research_team.infrastructure.persistence.blob_store.FilesystemBlobStore(root: Path)`
  - `research_team.infrastructure.config.blob_root() -> Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_blob_store.py`:

```python
"""The blob store: bytes under their own digest.

Every test here writes through `put` rather than placing files by hand,
because `put` computing the digest is the property the whole provenance story
rests on -- a test that wrote a file itself and asserted on its name would be
asserting about `hashlib`, not about this class.
"""

import hashlib
from pathlib import Path

import pytest

from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


async def chunks(*parts: bytes):
    for part in parts:
        yield part


@pytest.fixture
def store(tmp_path: Path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path)


async def test_put_returns_the_digest_it_computed(store: FilesystemBlobStore) -> None:
    """The digest is a fact about the bytes, not a claim from the caller.

    `put` takes no digest argument at all, which is what makes a wrong one
    require a bug in this class rather than a mistake at a call site.
    """
    stat = await store.put(chunks(b"hello ", b"world"))
    assert stat.sha256 == hashlib.sha256(b"hello world").hexdigest()
    assert stat.byte_count == 11


async def test_bytes_come_back_whole(store: FilesystemBlobStore) -> None:
    stat = await store.put(chunks(b"one", b"two", b"three"))
    read = b"".join([part async for part in store.open(stat.sha256)])
    assert read == b"onetwothree"


async def test_storing_the_same_bytes_twice_keeps_one_blob(
    store: FilesystemBlobStore, tmp_path: Path
) -> None:
    """Deduplication is free and is the reason content addressing was chosen.

    Fails if `put` writes unconditionally: the second call would leave a second
    file, and the same video ingested into two projects would cost twice.
    """
    first = await store.put(chunks(b"same"))
    second = await store.put(chunks(b"same"))
    assert first == second
    assert len(list(tmp_path.rglob("*"))) == len(list(tmp_path.rglob("*/*")))
    blobs = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(blobs) == 1


async def test_stat_is_none_for_bytes_that_were_never_stored(
    store: FilesystemBlobStore,
) -> None:
    """The seam every missing-blob report goes through.

    `None` rather than an exception, because "are the bytes still there" is a
    question callers ask on the ordinary path.
    """
    assert await store.stat("0" * 64) is None


async def test_a_partial_write_is_never_readable_under_a_finished_name(
    store: FilesystemBlobStore, tmp_path: Path
) -> None:
    """A torn write must not be readable under a name claiming its content.

    The stream raises halfway; afterwards nothing may exist under the digest of
    the bytes that *would* have been written, and no temporary file may be left
    behind. Fails if `put` writes directly to the final path instead of
    `os.replace`-ing a temporary one into place.
    """
    payload = b"first half second half"

    async def failing():
        yield payload[:11]
        raise RuntimeError("connection dropped")

    with pytest.raises(RuntimeError):
        await store.put(failing())

    assert await store.stat(hashlib.sha256(payload).hexdigest()) is None
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_open_raises_for_a_blob_that_is_gone(store: FilesystemBlobStore) -> None:
    """Callers are expected to `stat` first; `open` still refuses loudly.

    A silent empty stream here would render as a zero-byte video, which is the
    dangling reference presenting itself as a corrupt file.
    """
    with pytest.raises(FileNotFoundError):
        [part async for part in store.open("0" * 64)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_blob_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.infrastructure.persistence.blob_store'`

- [ ] **Step 3: Write the port**

Create `research_team/application/blobs.py`:

```python
"""Bytes too large for an event payload, addressed by their own digest.

The corpus keeps document text inside the event that stored it, and says why:
the log holding the bytes is what makes a quote checkable years later. Media
cannot go there -- snapshots every 50 events would fold whole films into the
store and into every replay -- so the log keeps the claim and this keeps the
bytes, joined by a digest.

**`put` returns the digest rather than accepting one, and that is the whole
mitigation for the guarantee this weakens.** For text, `Corpus.decide` computes
the digest from bytes it holds, so `by_digest` is a fact about the event. Media
bytes never pass through the domain -- holding a video in memory to hand it to
a pure function is not a thing to do -- so the command carries a digest computed
out here. Giving the caller no parameter by which to offer a different one makes
a wrong digest require a bug in the store rather than a mistake at a call site:
a hazard rather than a trap.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BlobStat:
    """What a stored blob is: its digest, and how many bytes it holds."""

    sha256: str
    byte_count: int


class BlobStorePort(Protocol):
    """Write-once, content-addressed byte storage."""

    async def put(self, stream: AsyncIterator[bytes]) -> BlobStat:
        """Store a stream, returning the digest computed while reading it.

        Idempotent by content: storing bytes already held returns the stat of
        what is there without writing again, so the same video ingested into
        two projects costs one blob.
        """
        ...

    def open(self, sha256: str) -> AsyncIterator[bytes]:
        """Stream a blob back. Raises `FileNotFoundError` if it is gone.

        Not `async def` -- an async generator function is already awaitable at
        iteration, and wrapping it in a coroutine would make every caller
        `await` twice for nothing.
        """
        ...

    async def stat(self, sha256: str) -> BlobStat | None:
        """What is stored under this digest, or `None`.

        `None` is how a caller asks whether a record's bytes still exist, which
        is an ordinary question rather than an error -- the read path answers it
        on every media request.
        """
        ...
```

- [ ] **Step 4: Write the filesystem implementation**

Create `research_team/infrastructure/persistence/blob_store.py`:

```python
"""`BlobStorePort` over an ordinary directory.

Two hex characters of fan-out (`blobs/ab/abcdef...`) because a flat directory
of a hundred thousand files is slow to list on every filesystem that matters,
and listing is what a future garbage sweep would do.

The root is a constructor argument and never an environment variable, so two
differently-rooted stores can run side by side in one test process.
"""

import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from research_team.application.blobs import BlobStat

CHUNK_SIZE = 1024 * 1024
"""How much is read per `open` iteration. A megabyte is large enough that a
gigabyte file is a thousand awaits rather than a million, and small enough
that a handful of concurrent streams cannot exhaust memory."""


class FilesystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256

    async def put(self, stream: AsyncIterator[bytes]) -> BlobStat:
        """Stream to a temporary file, then `os.replace` it into place.

        The rename is the atomicity: the digest is not known until the last
        byte, so a direct write would be readable under a name claiming content
        it does not yet hold. `os.replace` within one filesystem is atomic,
        which is why the temporary lives in the destination directory rather
        than in `/tmp`.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_count = 0
        # `os.getpid` so two processes sharing a root cannot collide on the
        # temporary name; `id(self)` so two stores in one process cannot either.
        temporary = self._root / f".incoming-{os.getpid()}-{id(self)}-{id(stream)}"
        try:
            async with aiofiles.open(temporary, "wb") as handle:
                async for part in stream:
                    digest.update(part)
                    byte_count += len(part)
                    await handle.write(part)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        sha256 = digest.hexdigest()
        destination = self._path(sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # Write-once: identical bytes are already here, and rewriting them
            # would briefly replace a file other readers may be streaming.
            temporary.unlink(missing_ok=True)
            return BlobStat(sha256=sha256, byte_count=destination.stat().st_size)
        os.replace(temporary, destination)
        return BlobStat(sha256=sha256, byte_count=byte_count)

    async def open(self, sha256: str) -> AsyncIterator[bytes]:
        path = self._path(sha256)
        # Raises FileNotFoundError, which is the loud answer this wants: a
        # silent empty stream would render as a zero-byte video, turning a
        # dangling reference into what looks like a corrupt file.
        async with aiofiles.open(path, "rb") as handle:
            while True:
                part = await handle.read(CHUNK_SIZE)
                if not part:
                    return
                yield part

    async def stat(self, sha256: str) -> BlobStat | None:
        path = self._path(sha256)
        if not path.is_file():
            return None
        return BlobStat(sha256=sha256, byte_count=path.stat().st_size)
```

Note the temporary file cleanup uses `BaseException`, not `Exception`: a
cancelled upload is `asyncio.CancelledError`, which is a `BaseException`, and
is exactly the case that would otherwise litter the root.

- [ ] **Step 5: Add `aiofiles` and the config root**

Add to `pyproject.toml` dependencies: `"aiofiles>=24.1"`, and to the dev extra
`"types-aiofiles>=24.1"`. Run `uv sync`.

In `research_team/infrastructure/config.py`, beside the database path helper
(~line 71):

```python
def blob_root() -> Path:
    """Where media bytes live: beside the database, not inside it.

    SQLite would hold them -- it has a BLOB type and a 1GB row ceiling -- and
    the reason not to is streaming. Serving a range request out of a BLOB means
    reading it into memory to slice it; a file supports `seek`. The cost is
    that a backup now has two things to copy, which is written on the
    `/rebuild` page rather than being left for someone to discover.
    """
    path = Path.home() / ".research-team" / "blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_blob_store.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 7: Run the Python gates**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add research_team/application/blobs.py research_team/infrastructure/persistence/blob_store.py research_team/infrastructure/config.py pyproject.toml uv.lock tests/infrastructure/test_blob_store.py
git commit -m "Store bytes under their digest, beside the log rather than in it"
```

The message body should record: why the digest is returned rather than
accepted, why the temporary file is `os.replace`d rather than written directly,
why `BaseException` and not `Exception` guards the cleanup, and why the bytes
are files rather than SQLite BLOBs (range requests need `seek`).

---

### Task 2: The domain — a media source

**Files:**
- Modify: `research_team/domain/corpus.py` (whole file)
- Modify: `research_team/domain/events.py` (export `CorpusMediaStored`)
- Modify: `research_team/domain/__init__.py` (export the new names)
- Test: `tests/domain/test_corpus.py`
- Test: `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: nothing from Task 1 — the domain never touches the blob store.
- Produces:
  - `CorpusMediaStored(DomainEvent)` — `aggregate_type="Corpus"`, `source_id: str`, `sha256: str`, `media_type: str`, `byte_count: int`, `uri/title/published_at/note/fetched_at: str | None = None`
  - `StoreSourceMedia` — frozen dataclass, `corpus_id: UUID`, `source_id: str`, `sha256: str`, `media_type: str`, `byte_count: int`, plus the same optional metadata
  - `SourceRecord = TextRecord | MediaRecord` (discriminated on `kind`)
  - `TextRecord` — today's `DocumentRecord` plus `kind: Literal["text"] = "text"`. **`DocumentRecord` is removed**; every importer moves to `TextRecord` or `SourceRecord`.
  - `MediaRecord` — `kind: Literal["media"] = "media"`, `media_type: str`, `byte_count: int`, shared metadata fields
  - `CorpusState.documents: dict[str, SourceRecord]`

- [ ] **Step 1: Write the failing domain tests**

Append to `tests/domain/test_corpus.py`:

```python
def test_storing_media_records_the_digest_it_was_given() -> None:
    """The one place the corpus takes a digest on trust rather than computing it.

    Asserted explicitly because it is a documented weakening of the guarantee
    in this module's docstring: the bytes never reach the domain, so `decide`
    cannot hash them. If a future change makes `decide` compute a digest for
    media, this test is the one that should fail and force the docstring to be
    reconciled with it.
    """
    corpus_id = uuid4()
    events = decide(
        StoreSourceMedia(
            corpus_id=corpus_id,
            source_id="v1",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=1234,
            uri="https://example.test/talk.mp4",
        ),
        initial_state(),
    )
    assert len(events) == 1
    stored = events[0]
    assert isinstance(stored, CorpusMediaStored)
    assert stored.sha256 == "a" * 64
    assert stored.byte_count == 1234
    assert stored.media_type == "video/mp4"


def test_media_creates_a_corpus_the_way_a_document_does() -> None:
    """Storing is what brings a corpus into existence, whichever kind is stored.

    Fails if `StoreSourceMedia` falls through to the `status="new"` rejection
    that guards every non-storing command.
    """
    corpus_id = uuid4()
    state = evolve(
        initial_state(),
        decide(_store_media(corpus_id, "v1"), initial_state())[0],
    )
    assert state.status == "created"
    assert state.corpus_id == corpus_id
    record = state.documents["v1"]
    assert record.kind == "media"
    assert record.byte_count == 1234


def test_media_may_not_take_over_a_source_id_holding_text() -> None:
    """A URI that returned prose yesterday and a video today is not a revision.

    Supersession by `source_id` exists for re-fetches of one document. Letting
    a kind change ride on it would make `read_document` start answering `None`
    for a source that still exists, which is the silent half of this failure.
    The refusal names both kinds because the next question is which one is
    there now.
    """
    corpus_id = uuid4()
    state = evolve(
        initial_state(),
        decide(
            StoreSourceDocument(corpus_id=corpus_id, source_id="s1", text="prose"),
            initial_state(),
        )[0],
    )
    with pytest.raises(CommandRejectedError, match="text"):
        decide(_store_media(corpus_id, "s1"), state)


def test_text_may_not_take_over_a_source_id_holding_media() -> None:
    """The same refusal in the other direction.

    Written separately rather than parametrised: the two paths are two
    branches, and a single test passing proves only one of them.
    """
    corpus_id = uuid4()
    state = evolve(initial_state(), decide(_store_media(corpus_id, "v1"), initial_state())[0])
    with pytest.raises(CommandRejectedError, match="media"):
        decide(StoreSourceDocument(corpus_id=corpus_id, source_id="v1", text="prose"), state)


def test_media_is_dropped_by_the_same_command_text_is() -> None:
    """One drop command for one `source_id` namespace.

    A second drop command for media would be a second way to say one thing, and
    the citation path addresses an id without knowing its kind.
    """
    corpus_id = uuid4()
    state = evolve(initial_state(), decide(_store_media(corpus_id, "v1"), initial_state())[0])
    dropped = decide(DropSourceDocument(source_id="v1", reason="wrong talk"), state)
    state = evolve(state, dropped[0])
    assert state.documents["v1"].dropped_reason == "wrong talk"
    assert state.by_digest == {}


def _store_media(corpus_id: UUID, source_id: str) -> StoreSourceMedia:
    return StoreSourceMedia(
        corpus_id=corpus_id,
        source_id=source_id,
        sha256="a" * 64,
        media_type="video/mp4",
        byte_count=1234,
    )
```

Add the imports these need to the file's existing import block:
`CorpusMediaStored`, `StoreSourceMedia` from `research_team.domain.corpus`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_corpus.py -v`
Expected: FAIL — `ImportError: cannot import name 'StoreSourceMedia'`

- [ ] **Step 3: Split the record type**

In `research_team/domain/corpus.py`, replace `DocumentRecord` with:

```python
class SourceRecordBase(BaseModel):
    """What every source has, whatever its bytes are.

    Split out rather than repeated so a field added to provenance is added
    once. The two subclasses differ by exactly the one measure the other
    cannot give: characters against bytes.
    """

    source_id: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    """When the source was retrieved, for by-reference content the corpus did
    not create -- provenance, not a corpus fact. Carried through so a revise
    or restore that re-stores this record's own fields cannot silently zero
    it; see `CorpusEditor._store` for why that caller has to read it back
    before writing."""
    dropped_reason: str | None = None
    """Set means excluded. The record stays, so the exclusion stays auditable."""


class TextRecord(SourceRecordBase):
    """A source the corpus holds as prose. Deliberately not its text.

    Was `DocumentRecord`, renamed when media arrived: `document` had quietly
    come to mean both "a source" and "a source made of words", and the union
    below needs those to be different words.
    """

    kind: Literal["text"] = "text"
    char_count: int


class MediaRecord(SourceRecordBase):
    """A source whose bytes live in the blob store under `sha256`.

    Carries no path or URL to those bytes. The digest *is* the address, and a
    second locator stored here would be a thing that could disagree with it --
    which is precisely the failure the digest exists to make impossible.
    """

    kind: Literal["media"] = "media"
    media_type: str
    """The mimetype, as the ingest path determined it. Not re-sniffed here:
    the domain has no bytes to sniff."""
    byte_count: int


SourceRecord = Annotated[TextRecord | MediaRecord, Field(discriminator="kind")]
"""One `source_id` namespace, two shapes.

Discriminated on a literal rather than left as a bare union so pydantic
round-trips it without guessing and so the type checker -- not a runtime
`AttributeError` in a template -- finds the readers that assumed `.text`.
"""
```

Add `Annotated` and `Literal` to the `typing` import.

- [ ] **Step 4: Add the event and the command**

```python
@register_event
class CorpusMediaStored(DomainEvent):
    """A media source was stored: the claim about it, never its bytes.

    `sha256` is where the bytes are and what proves they are the ones this
    event meant. Unlike `CorpusDocumentStored.sha256` it is *supplied* rather
    than computed -- see this module's docstring, and `application/blobs.py`
    for why that is a hazard rather than a trap.

    `published_at` is text for the same reason it is on the document event:
    sources report dates in whatever shape they please.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class StoreSourceMedia:
    #: Carried for the same reason `StoreSourceDocument` carries it: storing is
    #: what brings a corpus into existence, so there is no state to read it off.
    corpus_id: UUID
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


CorpusCommand = StoreSourceDocument | StoreSourceMedia | DropSourceDocument
```

- [ ] **Step 5: Extend `decide` and `evolve`**

In `decide`, add a kind-collision guard shared by both store branches, placed
**before** the existing `StoreSourceDocument` case:

```python
        case StoreSourceDocument(source_id=source_id) if _kind_of(state, source_id) == "media":
            raise CommandRejectedError(
                f"source {source_id!r} holds media; storing text under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceMedia(source_id=source_id) if _kind_of(state, source_id) == "text":
            raise CommandRejectedError(
                f"source {source_id!r} holds text; storing media under it would "
                "change what the id means rather than revise it"
            )
```

and a `StoreSourceMedia` case beside `StoreSourceDocument`'s, before the
`status="new"` rejection:

```python
        case StoreSourceMedia(), _:
            return [
                CorpusMediaStored(
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    sha256=command.sha256,
                    media_type=command.media_type,
                    byte_count=command.byte_count,
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]
```

with the helper:

```python
def _kind_of(state: CorpusState, source_id: str) -> str | None:
    """Which shape a source id already holds, or None if it is free.

    A dropped record still counts. Its id is taken -- restore reads it back --
    and letting a drop free the id for the other kind would make restore
    resurrect a record whose kind no longer matches its row.
    """
    record = state.documents.get(source_id)
    return None if record is None else record.kind
```

In `evolve`, add:

```python
        case CorpusMediaStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = MediaRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                media_type=event.media_type,
                byte_count=event.byte_count,
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )
```

Change `CorpusState.documents` to `dict[str, SourceRecord]`, and in
`CorpusDocumentStored`'s `evolve` branch construct a `TextRecord` with
`char_count=len(event.text)`.

- [ ] **Step 6: Update the module docstring**

The paragraph beginning "The digest is computed here rather than accepted from
the caller" is now half true. Extend `decide`'s docstring and the module
docstring so they say which half:

```
**For media the digest is supplied, and that is a deliberate weakening.** The
bytes never reach the domain -- holding a video in memory to hand it to a pure
function is not a thing to do -- so `CorpusMediaStored.sha256` is what the blob
store computed while streaming, and `by_digest` is a claim for those entries
rather than a fact. `application/blobs.py` carries the mitigation: `put`
returns the digest and there is no parameter by which a caller could offer a
different one, so a wrong digest requires a bug in the store rather than a
mistake at a call site.
```

- [ ] **Step 7: Run the domain tests**

Run: `uv run pytest tests/domain/test_corpus.py -v`
Expected: PASS.

- [ ] **Step 8: Fix every `DocumentRecord` importer**

Run: `uv run grep -rn "DocumentRecord" research_team tests` (or ripgrep). Each
site becomes `TextRecord` or `SourceRecord` depending on whether it can now
see media. Known sites: `research_team/application/corpus_read.py`,
`research_team/infrastructure/persistence/read_models.py` (`to_record`),
`research_team/infrastructure/agent/corpus_tools.py`. Tasks 3–4 rework those
anyway; here, make them compile and keep meaning text.

- [ ] **Step 9: Add the schema-evolution case**

In `tests/infrastructure/test_schema_evolution.py`:

```python
async def test_a_build_without_the_media_projection_still_replays(...) -> None:
    """A new event type is additive: an older build replays a log holding it.

    This is `eventsource.replay`'s documented behaviour -- an event every
    projection ignores counts as applied -- and it is what "events are not
    rewritten" depends on. Asserted here rather than assumed, because the same
    property is the reason a *missing* projection is silent, and a reader of
    this file should meet both halves in one place.
    """
```

Write a `CorpusMediaStored` payload straight into the events table and replay
with only `CorpusProjection`'s document handlers registered; assert the replay
completes and the document rows are unaffected.

- [ ] **Step 10: Run all four gates and commit**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`

```bash
git add research_team/domain tests/domain/test_corpus.py tests/infrastructure/test_schema_evolution.py
git commit -m "Let a corpus hold media, in the same source_id namespace as text"
```

Message body: why one namespace rather than two, why the kind collision is
refused in both directions, why `DropSourceDocument` was not duplicated, and
that `DocumentRecord` was renamed to `TextRecord` (a deliberate break, no
migration, pre-release).

---

### Task 3: The read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (`CorpusMediaRow`, `CorpusProjection`, `CorpusStore`, `CorpusRunner`)
- Test: `tests/infrastructure/test_read_models.py` (or the file holding the existing corpus read-model tests — locate with `grep -rln CorpusRunner tests`)

**Interfaces:**
- Consumes: `CorpusMediaStored`, `MediaRecord`, `TextRecord`, `SourceRecord` from Task 2.
- Produces:
  - `CorpusMediaRow(ReadModel)` — `__table_name__ = "corpus_media"`, fields `project_id: UUID`, `source_id: str`, `sha256: str`, `media_type: str`, `byte_count: int`, `uri/title/published_at/note/fetched_at/dropped_reason: str | None = None`, and `row_id(project_id, source_id)` staticmethod matching `CorpusDocumentRow`'s scheme
  - `CorpusStore.get_media(project_id, source_id, *, include_dropped=False) -> CorpusMediaRow | None`
  - `CorpusStore.list_all(project_id, *, include_dropped=False) -> list[CorpusDocumentRow | CorpusMediaRow]`
  - `CorpusRunner.get_media(...)` and `CorpusRunner.list_all(...)` delegating to the store
  - `to_record(row) -> SourceRecord` accepting either row type

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_stored_media_event_lands_as_a_row(corpus_store) -> None:
    """Assert the row, not the call.

    An assertion that the projection "handled" the event, or that a request
    returned 200, passes with the media handler deleted entirely: an event no
    projection handles counts as APPLIED. The row is the only thing that does
    not.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(
        CorpusMediaStored(
            aggregate_id=project_id,
            source_id="v1",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=999,
            title="A talk",
        )
    )
    row = await corpus_store.get_media(project_id, "v1")
    assert row is not None
    assert row.sha256 == "a" * 64
    assert row.byte_count == 999
    assert row.media_type == "video/mp4"
    assert row.title == "A talk"


async def test_dropping_media_marks_the_media_row(corpus_store) -> None:
    """One drop event, two tables. Fails if `_on_dropped` only ever looked in
    `corpus_documents` -- in which case a dropped video keeps listing as live
    and the console offers to drop it again forever."""
    project_id = uuid4()
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    await corpus_store.projection.handle(
        CorpusDocumentDropped(aggregate_id=project_id, source_id="v1", reason="wrong talk")
    )
    assert await corpus_store.get_media(project_id, "v1") is None
    dropped = await corpus_store.get_media(project_id, "v1", include_dropped=True)
    assert dropped is not None and dropped.dropped_reason == "wrong talk"


async def test_listing_returns_both_kinds_in_one_answer(corpus_store) -> None:
    """The Documents page renders one table.

    Fails if `list_all` queries only one table, which reads downstream as half
    a corpus -- and half a corpus looks exactly like a whole one.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(
        CorpusDocumentStored(
            aggregate_id=project_id, source_id="s1", text="prose", sha256="b" * 64
        )
    )
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    kinds = sorted(to_record(row).kind for row in await corpus_store.list_all(project_id))
    assert kinds == ["media", "text"]


async def test_a_replayed_media_event_rewrites_rather_than_duplicates(corpus_store) -> None:
    """Idempotent by overwrite, like both document handlers.

    Replay from a checkpoint that is behind must re-derive the same row rather
    than accumulate, because that is what makes `rebuild()` safe to reach for.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    rows = await corpus_store.list_all(project_id)
    assert len(rows) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/ -k media -v`
Expected: FAIL — `AttributeError: 'CorpusStore' object has no attribute 'get_media'`

- [ ] **Step 3: Add the row**

```python
class CorpusMediaRow(ReadModel):
    """One media source: everything but its bytes.

    A separate table rather than columns on `corpus_documents`, for two
    reasons. `corpus_documents.text` is NOT NULL and every media row would have
    to lie about it -- and making it nullable would then let a text row lie
    too, which is the failure mode where a document silently loses its content
    and still lists. Second, `apply_schema` refuses a required column with no
    default outright, so widening is also the more expensive path.

    No `extracted_at`. Nothing extracts media yet, and a column whose only
    value is NULL is a promise the perception slice may not want to keep.
    """

    __table_name__ = "corpus_media"

    project_id: UUID
    source_id: str
    sha256: str
    """Where the bytes are. A row whose blob is gone is a dangling reference,
    which the read path reports as 410 rather than 404 -- see
    `CorpusReadPort.read_media`."""
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """Mirrors `CorpusDocumentRow.row_id` exactly.

        Deliberately the same derivation over the same inputs: the two tables
        share one `source_id` namespace, so a row id that differed between them
        would let one id name two rows.
        """
        Source ids are chosen per project -- `"s1"`, a URL, a filename -- and
        will collide across them. Keying on the pair means one project's
        re-ingest cannot overwrite another's.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")
```

- [ ] **Step 4: Extend the projection, store and runner**

Add `@handles(CorpusMediaStored)` writing the row by load-and-mutate (matching
`_on_stored`, so the version counter climbs and `dropped_reason` is cleared
explicitly).

Change `_on_dropped` to update whichever table holds the id — document row
first, media row if the document row is absent. Comment why it is not both:
the kind-collision guard in Task 2 makes an id in both tables impossible, and a
handler that quietly updated both would hide a violation of that guard.

`CorpusStore.open` applies `apply_schema(connection, CorpusMediaRow)` and
creates `idx_corpus_media_project` on `project_id`, mirroring the documents
index and for the same reason.

`to_record` gains a media branch returning `MediaRecord`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/infrastructure/ -k media -v`
Expected: PASS.

- [ ] **Step 6: Verify against a database that predates the change**

This is the standing rule in `CLAUDE.md`, and it is not optional:

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
AGENT_DB=/tmp/probe.db uv run python -c "
import asyncio
from research_team.infrastructure.persistence.read_models import CorpusStore
async def main():
    store = await CorpusStore.open('/tmp/probe.db')
    print(await store.list_all(<a real project uuid from the copy>))
asyncio.run(main())
"
```

Expected: the new table is created on open, existing document rows list
unchanged, and no query fails. **Record the result in the commit message with
the date, as a measurement rather than an expectation.** If it fails, stop —
do not proceed to Task 4.

- [ ] **Step 7: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py tests/
git commit -m "Follow media events into a table of their own"
```

---

### Task 4: The read port

**Files:**
- Modify: `research_team/application/corpus_read.py`
- Modify: `research_team/infrastructure/persistence/corpus_reader.py`
- Modify: `research_team/infrastructure/agent/corpus_tools.py` (the `list_sources` tool)
- Modify: every other `list_documents` caller — find with `grep -rn "list_documents" research_team tests`
- Test: `tests/application/test_corpus_read.py` (create if absent)

**Interfaces:**
- Consumes: Task 1's `BlobStorePort`/`BlobStat`, Task 3's `CorpusRunner.list_all`/`get_media`, Task 2's `SourceRecord`.
- Produces:
  - `SourceListing` — frozen dataclass, `record: SourceRecord`, `extracted: bool`. **Replaces `DocumentListing`.**
  - `MediaHandle` — frozen dataclass, `record: MediaRecord`, `stat: BlobStat | None`, `open: Callable[[], AsyncIterator[bytes]]`
  - `CorpusReadPort.list_sources(*, include_dropped=False) -> list[SourceListing]` — **replaces `list_documents`, which is removed**
  - `CorpusReadPort.read_media(source_id, *, include_dropped=False) -> MediaHandle | None`
  - `read_document` unchanged in signature; returns `None` for a media source

- [ ] **Step 1: Write the failing tests**

```python
async def test_read_media_answers_none_for_a_source_that_does_not_exist(reader) -> None:
    assert await reader.read_media("nope") is None


async def test_read_media_answers_a_handle_with_no_stat_when_the_bytes_are_gone(
    reader, blob_store
) -> None:
    """Three outcomes, not two -- and this is the one that matters.

    A record whose blob is missing is not the same as a source that was never
    stored, and a caller that could not tell them apart would report a
    dangling reference as a 404: an operator would go looking for an ingest
    that never happened instead of for bytes that went away.
    """
    await _store_media(reader, "v1", b"payload")
    _delete_the_blob_underneath(blob_store, "v1")
    handle = await reader.read_media("v1")
    assert handle is not None
    assert handle.stat is None


async def test_read_document_answers_none_for_a_media_source(reader) -> None:
    """It promises text, and a media source has none.

    Not an exception: `read_document`'s contract already reserves the exception
    for storage failure, and a model guessing at a source id is the expected
    case rather than a bug.
    """
    await _store_media(reader, "v1", b"payload")
    assert await reader.read_document("v1") is None


async def test_list_sources_returns_both_kinds(reader) -> None:
    await _store_text(reader, "s1", "prose")
    await _store_media(reader, "v1", b"payload")
    assert sorted(listing.record.kind for listing in await reader.list_sources()) == [
        "media",
        "text",
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/application/test_corpus_read.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'read_media'`

- [ ] **Step 3: Implement the port and reader**

`ProjectCorpusReader` gains the blob store as a second constructor argument.
`read_media` reads the row, returns `None` if absent, then `stat`s the blob and
returns a handle either way.

Docstring for `read_media` must carry the three-outcome argument, in this
repository's register:

```python
    async def read_media(
        self, source_id: str, *, include_dropped: bool = False
    ) -> MediaHandle | None:
        """One media source, or `None` when this project has no such id.

        Three outcomes rather than two, and the middle one is why this is not
        just `read_document` with different bytes. `None` means nothing was
        ever stored under this id. A handle whose `stat` is `None` means the
        record is here and the bytes are not -- a dangling reference, which the
        web layer reports as 410 Gone. A caller that collapsed those two would
        send an operator looking for an ingest that never happened instead of
        for bytes that went away.

        The handle carries `open` as a factory rather than an open stream, so
        a caller that only wants the metadata -- the Documents list, deciding
        whether to offer playback -- does not pay for a file descriptor it
        will not read.
        """
```

- [ ] **Step 4: Replace `list_documents` everywhere**

`list_documents` is **removed**, not deprecated. Two list methods is how a
caller silently sees half a corpus. Update:
- `corpus_tools.py`'s `list_sources` tool — its rendering must say what a media
  source is (mimetype and size) rather than a character count it does not have
- the console route in `app.py`
- the topic queue's corpus facts, if it lists

Each call site discriminates on `record.kind`; the type checker finds them.

- [ ] **Step 5: Run the tests, then the whole Python suite**

Run: `uv run pytest tests/application/test_corpus_read.py -v` then `uv run pytest -q`
Expected: PASS. Expect breakage in `list_documents` callers — that is the point
of removing rather than keeping it.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/corpus_read.py research_team/infrastructure tests/
git commit -m "Read a corpus by source rather than by document"
```

Message body: why `list_documents` was removed rather than kept beside
`list_sources`, and why `read_media` has three outcomes.

---

### Task 5: Storing media

**Files:**
- Modify: `research_team/application/corpus_editing.py`
- Test: `tests/application/test_corpus_editing.py`

**Interfaces:**
- Consumes: `BlobStorePort` (Task 1), `StoreSourceMedia` (Task 2), `CorpusEditor`'s existing repository plumbing.
- Produces: `CorpusEditor.store_media(project_id, source_id, stream, media_type, *, uri=None, title=None, note=None, published_at=None, fetched_at=None) -> MediaRecord`

- [ ] **Step 1: Write the failing tests**

```python
async def test_store_media_writes_the_bytes_before_the_event(editor, blob_store) -> None:
    """Order is not arbitrary and this test is what holds it.

    Bytes first means a rejected command leaves an orphan blob -- unreferenced,
    harmless, and adopted by the next store of the same bytes because the store
    is content-addressed. Command first would mean a committed record whose
    bytes are not there yet, which is the dangling reference the read path had
    to grow a third outcome for. Cheap failure over expensive one.
    """
    await editor.store_media(project_id, "v1", chunks(b"payload"), "video/mp4")
    stat = await blob_store.stat(hashlib.sha256(b"payload").hexdigest())
    assert stat is not None and stat.byte_count == 7


async def test_a_rejected_store_leaves_the_blob_and_no_record(editor, blob_store) -> None:
    """The orphan is accepted, deliberately. Assert it rather than pretend.

    Documents the cost so nobody later "fixes" it by reordering the writes and
    reintroduces the dangling reference.
    """
    await editor.store(project_id, "s1", "prose")
    with pytest.raises(CommandRejectedError):
        await editor.store_media(project_id, "s1", chunks(b"payload"), "video/mp4")
    assert await blob_store.stat(hashlib.sha256(b"payload").hexdigest()) is not None


async def test_the_recorded_digest_is_the_one_the_store_computed(editor, blob_store) -> None:
    """`store_media` has no digest parameter, and this asserts the consequence.

    The mitigation for the domain taking a digest on trust is that no call site
    can supply one. If a parameter is ever added, this test still passes -- so
    it is paired with a signature assertion below, which does not.
    """
    record = await editor.store_media(project_id, "v1", chunks(b"payload"), "video/mp4")
    assert record.sha256 == hashlib.sha256(b"payload").hexdigest()


def test_store_media_takes_no_digest_from_its_caller() -> None:
    """The signature is the mitigation, so the signature is asserted.

    Reads as a strange test and is the honest one: `application/blobs.py`
    claims a wrong digest requires a bug in the store rather than a mistake at
    a call site, and that claim is only true while this parameter list has no
    `sha256` in it.
    """
    assert "sha256" not in inspect.signature(CorpusEditor.store_media).parameters
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/application/test_corpus_editing.py -k media -v`
Expected: FAIL — `AttributeError: 'CorpusEditor' object has no attribute 'store_media'`

- [ ] **Step 3: Implement**

```python
    async def store_media(
        self,
        project_id: UUID,
        source_id: str,
        stream: AsyncIterator[bytes],
        media_type: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
        fetched_at: str | None = None,
    ) -> MediaRecord:
        """Stream the bytes to the blob store, then record the claim.

        Bytes first, deliberately: a rejected command then leaves an
        unreferenced blob, which content addressing makes harmless -- the next
        store of the same bytes adopts it. The other order would commit a
        record whose bytes are not there, and a dangling reference is the one
        failure this design promised to make impossible rather than merely
        rare.

        Takes no `sha256`. That absence is the whole mitigation for the domain
        accepting a digest it did not compute; see `application/blobs.py`.
        """
        stat = await self._blobs.put(stream)
        ...  # existing repository/execute plumbing, issuing StoreSourceMedia
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/application/test_corpus_editing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add research_team/application/corpus_editing.py tests/application/test_corpus_editing.py
git commit -m "Store media bytes first, then the claim about them"
```

---

### Task 6: The web routes

**Files:**
- Modify: `research_team/interfaces/web/app.py` (beside `upload_source`, ~line 780)
- Modify: `research_team/composition.py` (build the blob store, pass it to the reader and editor)
- Modify: `research_team/interfaces/web/presenters.py` (`source_view` renders both kinds)
- Test: `tests/interfaces/test_document_routes.py`

**Interfaces:**
- Consumes: Tasks 1–5 entire.
- Produces:
  - `POST /api/projects/{project_id}/sources/media` (multipart, field name `file`; optional form fields `source_id`, `uri`, `title`, `note`, `published_at`) → 201, the source view
  - `GET /api/projects/{project_id}/sources/{source_id}/content` → 200 or 206, streaming
  - `source_view` gains `kind`, and `media_type`/`byte_count` for media rows

- [ ] **Step 1: Write the failing tests**

```python
async def test_uploading_media_stores_a_row_that_lists(client, project_id) -> None:
    """Asserts the listing, not the 201.

    A 201 is returned by a handler whose projection was never registered; the
    row is what is not.
    """
    response = await client.post(
        f"/api/projects/{project_id}/sources/media",
        files={"file": ("talk.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
        data={"source_id": "v1"},
    )
    assert response.status_code == 201
    listed = (await client.get(f"/api/projects/{project_id}/sources")).json()
    assert [row["source_id"] for row in listed if row["kind"] == "media"] == ["v1"]


async def test_content_streams_the_bytes_back_with_their_type(client, project_id) -> None:
    await _upload(client, project_id, "v1", b"payload", "video/mp4")
    response = await client.get(f"/api/projects/{project_id}/sources/v1/content")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"payload"


async def test_a_range_request_answers_206_with_only_that_range(client, project_id) -> None:
    """Ahead of the citation slice that needs it, and argued for in the spec:
    a `<video>` seeking to 4:12 issues a range request, and without one
    Chromium downloads the whole file before it will play."""
    await _upload(client, project_id, "v1", b"0123456789", "video/mp4")
    response = await client.get(
        f"/api/projects/{project_id}/sources/v1/content", headers={"Range": "bytes=2-5"}
    )
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"


async def test_a_record_whose_bytes_are_gone_answers_410(client, project_id, blob_store) -> None:
    """410 Gone, not 404. The source exists and its bytes do not, and an
    operator told 404 goes looking for an ingest that never happened."""
    await _upload(client, project_id, "v1", b"payload", "video/mp4")
    _delete_the_blob_underneath(blob_store, b"payload")
    response = await client.get(f"/api/projects/{project_id}/sources/v1/content")
    assert response.status_code == 410


async def test_content_for_a_text_source_answers_404(client, project_id) -> None:
    """The route serves bytes from the blob store; a text source has none
    there. 404 rather than 410 -- nothing is missing, this is the wrong route
    for that source."""
```

Plus the fixture-independence test `CLAUDE.md` demands:

```python
async def test_media_reads_from_a_project_the_fixture_never_touched(client) -> None:
    """A path exercised from a fixture that did not make the call under test.

    The entity-definitions incident: six tests missed a missing `graphs.open`
    because every fixture seeded through it, so from the fixture's point of
    view the project was always open. Here the equivalent is a project whose
    blob store the fixture never constructed. Insert the media event directly
    into the event store, then request `/content` -- and get 410, because the
    record is real and the bytes were never written.
    """
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/interfaces/test_document_routes.py -k media -v`
Expected: FAIL — 404 on the upload route.

- [ ] **Step 3: Implement the upload route**

Use `UploadFile`; stream `file.read(1MB)` chunks into `store_media` rather than
`await file.read()`, which would buffer a gigabyte. Determine `media_type` from
`file.content_type`, corrected by sniffing the leading bytes when it is absent
or `application/octet-stream` (browsers send that for plenty of things that are
not). Default `source_id` to the filename when the form omits it.

Enforce a ceiling: `MAX_UPLOAD_BYTES = 2 * 1024**3`, refused with 413 mid-stream
rather than after. Comment: streaming bounds memory, and only this bounds disk.

- [ ] **Step 4: Implement the content route**

`StreamingResponse` over `handle.open()`. Parse `Range: bytes=start-end`;
answer 206 with `Content-Range` and `Accept-Ranges: bytes`, 416 for a range
past the end. `handle.stat is None` → 410.

- [ ] **Step 5: Wire composition**

`build_application` constructs one `FilesystemBlobStore(config.blob_root())`
and hands it to both `ProjectCorpusReader` and `CorpusEditor`. One instance,
because two would each hold their own root and a test that repointed one would
silently leave the other on the real directory.

- [ ] **Step 6: Run the tests, then all four gates**

Run: `uv run pytest tests/interfaces/ -v` then `uv run ruff format . && uv run ruff check . && uv run pytest -q`

- [ ] **Step 7: Commit**

```bash
git add research_team/interfaces research_team/composition.py tests/interfaces/
git commit -m "Upload media, and stream it back in ranges"
```

Message body: why 410 rather than 404, why range support lands now rather than
with the citation slice, and why the upload streams rather than buffers.

---

### Task 7: The Documents page

**Files:**
- Modify: `frontend/src/domain/research/document.ts` (the summary type becomes a union)
- Modify: `frontend/src/infrastructure/http/dto.ts` and `mappers.ts`
- Modify: `frontend/src/infrastructure/http/document-repository.ts` (`uploadMedia`, content URL)
- Modify: `frontend/src/presentation/research/DocumentList.tsx`, `DocumentReader.tsx`, `DocumentUpload.tsx`
- Test: the sibling `*.test.tsx` files

**Interfaces:**
- Consumes: Task 6's `source_view` shape (`kind`, `media_type`, `byte_count`) and the two routes.
- Produces: `SourceSummary = TextSummary | MediaSummary` discriminated on `kind`; `documentLabel` accepts either.

- [ ] **Step 1: Write the failing tests**

In `DocumentList.test.tsx`:

```tsx
it('shows a media row by its type and size, not a character count', () => {
  // A media row rendered through the text path shows "0 characters", which
  // reads as an empty document rather than as a video -- the failure this
  // asserts against is a plausible-looking row, not a crash.
})

it('offers drop and restore on a media row exactly as on a text one', () => {
  // One `source_id` namespace means one set of actions. A media row missing
  // them would make a dropped video unrecoverable through the console.
})
```

In `DocumentReader.test.tsx`:

```tsx
it('renders a video source as a player against the content route', () => {})
it('renders an image source as an image', () => {})
it('does not attempt to read text for a media source', () => {
  // Fails if the reader still calls `read()` on selection: the text route
  // answers 404 for media, and the pane would show an error where a video
  // belongs.
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm run test -- DocumentList DocumentReader`
Expected: FAIL.

**Do not run this concurrently with any other vitest process.**

- [ ] **Step 3: Split the domain type**

```ts
/** One row of a project's document browser, whichever shape its bytes are.
 *
 *  Discriminated on `kind` rather than left as an optional-fields widening:
 *  a `charCount` that is `null` for media invites a component to render "0
 *  characters", which reads as an empty document rather than as a video. The
 *  union makes the compiler ask which one is being rendered. */
export type SourceSummary = TextSummary | MediaSummary
```

`TextSummary` is today's `DocumentSummary` plus `kind: 'text'`; `MediaSummary`
carries `kind: 'media'`, `mediaType: string`, `byteCount: number`, and the
shared provenance fields. `extracted` stays on both — `false` always for media
in this slice.

- [ ] **Step 4: Implement the list, reader and upload**

`DocumentList` renders a size (`formatBytes`) and the mimetype for media rows.
`DocumentReader` switches on `kind`: `<video controls>`, `<audio controls>` or
`<img>` against `/api/projects/{id}/sources/{sourceId}/content`, with digest and
byte count beside it. `DocumentUpload` accepts a file and posts multipart.

No thumbnails: a thumbnail needs a frame, a frame needs `ffmpeg`, and that is
the perception slice.

- [ ] **Step 5: Run the frontend gate**

Run: `cd frontend && npm run verify`
Expected: PASS, including prettier and the bundle-size budget — the two that
only fail in CI.

If the bundle budget fails, **raise the budget rather than shaving the
feature** (this project's standing preference), and say so in the commit.

- [ ] **Step 6: Run browser tests if any stylesheet or measured layout changed**

Run: `cd frontend && npm run test:browser`

Only if a stylesheet, a layout primitive, or anything whose correctness is a
computed style was touched. If a media pane got new CSS, it was.

- [ ] **Step 7: Run all four gates and commit**

```bash
git add frontend/src
git commit -m "Show media in the document browser"
```

---

## Final verification

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pytest`
- [ ] `cd frontend && npm run verify`
- [ ] The read-model probe against a copy of the real database (Task 3, Step 6) re-run against final `main`, with the date recorded
- [ ] `BACKLOG.md`: file blob garbage collection as deferred, with the sweep described (over `corpus_media.sha256`) and the reason it is not needed yet (orphans are unreferenced and adopted by the next identical store)
- [ ] `README.md`: note that `~/.research-team/blobs` is now part of a backup
