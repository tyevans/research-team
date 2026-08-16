# Perception and Derived Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stored medium becomes legible — `readeverything` renders it to text plus a locator map, which is stored back into the corpus as a derived text source that chunks, extracts and cites like any other document.

**Architecture:** A new `CorpusDerivedTextStored` event carries the rendered text, a JSON locator map and the capability fingerprint that produced it. Derived text is a `TextRecord` with `derived_from` set, not a third union arm, so every existing text reader works on it unchanged. Perception is a port over `readeverything.Perception` built against the blob root, which is usable directly as a filesystem root because content sniffing identifies extensionless digest-named files.

**Tech Stack:** Python 3.13, pydantic, eventsource-py, `readeverything==0.1.x`, FastAPI, SQLite read models, React/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-08-16-perception-and-derived-text-design.md`

## Global Constraints

- **The dependency line is exactly** `"readeverything[remote-transcription,images,documents,vision]>=0.1.0,<0.2",`. Capped below the next minor: pre-1.0, a minor is where breaking renames land.
- **No test may make a network request.** No test may reference `192.168.1.14` or any other host. Use `readeverything.testing`'s `FakeTranscriber` / `FakeVision`, or `httpx.MockTransport` through `RemoteWhisperTranscriber`'s `transport=` seam.
- **Every projection test asserts a row or a field value, never a 2xx or "it did not raise."** An event no projection handles counts as APPLIED, so a missing handler yields an empty read model and a green suite. This is the repository's most-repeated failure.
- **Every column added to `corpus_documents` is nullable.** `apply_schema` reconciles an added nullable column onto a populated table and refuses a required one with no default.
- **At least one test per code path starts from a fixture that did not itself make the call the code under test is responsible for making.** Writing the event directly, then reading it back, is the shape.
- **The derived `source_id` is exactly `f"{parent_source_id}#perceived"`.**
- Comments explain **why**, name costs and trade-offs, and say when something was measured rather than reasoned. A comment restating the code is worse than none.
- Run `uv run ruff check .` and `uv run ruff format --check .` (repo-wide, both) plus the tests for the files you touched. Do **not** run the full pytest suite — CI runs it.
- `ffmpeg` and `ffprobe` are OS binaries, present on this machine (6.1.1) and on CI's Ubuntu runners. They are not Python dependencies and must not be added to `pyproject.toml`.

---

## File Structure

**Create:**
- `research_team/application/perception.py` — `PerceptionPort`, `Perceived`, `LocatorSpan`, `PerceptionCapabilities`, `MediaPerceiver`, `PerceptionReport`
- `research_team/application/locators.py` — pure resolver from a stored map + char span to locators
- `research_team/infrastructure/perception/__init__.py`
- `research_team/infrastructure/perception/readeverything_adapter.py` — `ReadEverythingPerception`
- `tests/application/test_perception.py`
- `tests/application/test_locators.py`
- `tests/infrastructure/test_readeverything_adapter.py`
- `tests/interfaces/web/test_perceive_route.py`

**Modify:**
- `pyproject.toml` — the dependency line
- `research_team/infrastructure/config.py` — four functions
- `research_team/domain/corpus.py` — event, command, `TextRecord` fields, `decide`, `evolve`
- `research_team/infrastructure/persistence/read_models.py` — four columns, projection handler, `to_record`
- `research_team/application/corpus_read.py` — carry the new fields onto the listing
- `research_team/application/document_extraction.py` — `unextracted` docstring only
- `research_team/composition.py` — build and wire the port and the perceiver
- `research_team/interfaces/web/app.py` — the perceive route
- `research_team/interfaces/web/extraction.py` — two stage values
- `frontend/src/...` — the Transcribe control and derived-source display
- `tests/infrastructure/test_schema_evolution.py` — a case for the new event
- `tests/domain/test_corpus.py` — refusals

---

## Task 1: Dependency and configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `research_team/infrastructure/config.py`
- Test: `tests/infrastructure/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.transcriber_url() -> str | None`, `config.transcriber_model() -> str`, `config.vision_model() -> str | None`, `config.perception_max_chars() -> int`, `config.perception_root() -> Path`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, inside `[project].dependencies`, add — with this comment, because the cap needs the same justification the other pre-1.0 pins carry:

```toml
    # Perception over stored media: renders a video, audio file or image to
    # text plus a locator map from character offsets to time spans and
    # regions. Capped below the next minor for the reason eventsource-py and
    # redstring are -- pre-1.0, and a minor is where the breaking renames
    # land. The extras: `remote-transcription` is httpx (already present),
    # `vision` is langchain-openai (already present), and `images` and
    # `documents` add pillow and pypdfium2, which are new weight bought for
    # image and PDF handling. ffmpeg/ffprobe are OS binaries and are
    # deliberately not represented here.
    "readeverything[remote-transcription,images,documents,vision]>=0.1.0,<0.2",
```

Then run `uv sync` and commit `uv.lock` in the same commit.

- [ ] **Step 2: Write the failing config tests**

Add to `tests/infrastructure/test_config.py` (match the file's existing style for env manipulation — it uses `monkeypatch`):

```python
def test_transcription_is_off_until_a_url_is_set(monkeypatch):
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)
    assert config.transcriber_url() is None


def test_a_transcriber_url_without_a_model_refuses_to_start(monkeypatch):
    """The server reports no model name -- measured against whisper.cpp on
    2026-08-15 -- so there is nothing to infer one from, and the name is the
    ASR revision inside the capability fingerprint. Defaulting it would let
    two models' output share one cache key."""
    monkeypatch.setenv("AGENT_TRANSCRIBER_URL", "http://localhost:8083")
    monkeypatch.delenv("AGENT_TRANSCRIBER_MODEL", raising=False)
    with pytest.raises(ValueError, match="AGENT_TRANSCRIBER_MODEL"):
        config.transcriber_model()


def test_perception_max_chars_matches_the_document_cap(monkeypatch):
    monkeypatch.delenv("AGENT_PERCEPTION_MAX_CHARS", raising=False)
    assert config.perception_max_chars() == MAX_DOCUMENT_CHARS
```

- [ ] **Step 3: Run them and watch them fail**

Run: `uv run pytest tests/infrastructure/test_config.py -v`
Expected: FAIL, `AttributeError: module ... has no attribute 'transcriber_url'`

- [ ] **Step 4: Implement**

Add to `research_team/infrastructure/config.py`.

**Define `DEFAULT_PERCEPTION_MAX_CHARS = 200_000` locally, beside the other defaults. Do not import `MAX_DOCUMENT_CHARS`.** It lives in `research_team/application/knowledge.py:40`, and `infrastructure/config.py` importing from `application/` inverts the dependency direction this repository maintains — the module's own docstring calls it the edge that no layer below asks anything of, and it imports only `os` and `pathlib` today. The cost is two constants that must track each other; pay it down with a comment in the new one naming the other and saying they must move together. Drift between them makes a transcript truncate at a different length than a document, which is visible rather than silent.

The test above should then assert against `200_000` directly, or against `config.DEFAULT_PERCEPTION_MAX_CHARS`, rather than importing the application constant into a config test.

```python
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
    return int(configured) if configured else MAX_DOCUMENT_CHARS


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
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/infrastructure/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Point the test fixture at a temp directory**

`tests/conftest.py` has an `isolate_database` fixture that already redirects `AGENT_DB` and `AGENT_BLOB_ROOT` to `tmp_path`. Add `AGENT_PERCEPTION_ROOT` alongside them, for the identical reason recorded in `blob_root`'s docstring: without it the suite writes cache files into the developer's real `~/.research-team/perception` and nothing fails.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add pyproject.toml uv.lock research_team/infrastructure/config.py tests/
git commit -m "Configure perception, and refuse a transcriber with no model name"
```

---

## Task 2: The domain event, command and refusals

**Files:**
- Modify: `research_team/domain/corpus.py`
- Test: `tests/domain/test_corpus.py`

**Interfaces:**
- Consumes: `SourceRecordBase`, `TextRecord`, `_kind_of`, `decide`, `evolve` as they stand.
- Produces: `CorpusDerivedTextStored`, `StoreDerivedText`, `TextRecord.derived_from/perceived_with/degradations`, and `CorpusCommand` widened to include `StoreDerivedText`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/domain/test_corpus.py`, matching its existing helper style for building state:

```python
def test_derived_text_must_name_a_source_that_exists():
    state = _state_with_media("vid")
    with pytest.raises(CommandRejectedError, match="unknown source 'nope'"):
        decide(
            StoreDerivedText(
                corpus_id=CORPUS_ID,
                source_id="nope#perceived",
                derived_from="nope",
                text="said something",
                locator_map="[]",
                perceived_with="abc123",
                degradations="[]",
            ),
            state,
        )


def test_derived_text_must_name_media_not_text():
    """A transcript of a text document is a category error, and the aggregate
    is the only place that can see it -- the state holds every source's kind."""
    state = _state_with_text("paper")
    with pytest.raises(CommandRejectedError, match="holds text"):
        decide(_store_derived(source_id="paper#perceived", derived_from="paper"), state)


def test_a_plain_document_cannot_be_overwritten_by_a_derived_one():
    """Supersession by source_id means "a re-fetch is a revision". A transcript
    landing on a document's id is not a revision, for the same reason a video
    landing on one is not."""
    state = _state_with_text("notes")  # a plain document at that exact id
    state = _with_media(state, "vid")
    with pytest.raises(CommandRejectedError, match="not derived"):
        decide(_store_derived(source_id="notes", derived_from="vid"), state)


def test_a_derived_document_cannot_be_overwritten_by_a_plain_one():
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")
    with pytest.raises(CommandRejectedError, match="derived"):
        decide(
            StoreSourceDocument(corpus_id=CORPUS_ID, source_id="vid#perceived", text="hand written"),
            state,
        )


def test_re_perceiving_supersedes_rather_than_accumulating():
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid", text="first")
    events = decide(
        _store_derived(source_id="vid#perceived", derived_from="vid", text="second"), state
    )
    state = evolve(state, events[0])
    record = state.documents["vid#perceived"]
    assert record.char_count == len("second")
    assert record.derived_from == "vid"
    assert len(state.documents) == 2  # the media and its one transcript


def test_the_digest_of_derived_text_is_computed_not_supplied():
    """It is text and the aggregate has the bytes, so `by_digest` stays a fact.
    Media supplies its digest only because the domain never sees a video."""
    state = _state_with_media("vid")
    events = decide(_store_derived(source_id="vid#perceived", derived_from="vid", text="hello"), state)
    assert events[0].sha256 == hashlib.sha256(b"hello").hexdigest()
```

Write `_store_derived`, `_state_with_media`, `_with_media` and `_evolve_derived` as local helpers in the test module, in the style the file already uses.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/domain/test_corpus.py -v -k derived`
Expected: FAIL with `ImportError` / `NameError` on `StoreDerivedText`.

- [ ] **Step 3: Add the event**

In `research_team/domain/corpus.py`, after `CorpusMediaStored`:

```python
@register_event
class CorpusDerivedTextStored(DomainEvent):
    """What a perception model made of a stored medium.

    A separate event from `CorpusDocumentStored` because a derived source has
    to stay permanently distinguishable from a fetched one: a quote from a
    transcript is a quote from a model's reading of an audio track, and
    provenance that cannot tell those apart is the unfalsifiable-provenance
    failure this module exists to prevent, one level up.

    `locator_map` is JSON rather than a structured field because the locator
    union (`TimeSpan | PageRef | BBox | CharSpan | ByteRange`) belongs to
    `readeverything` and will evolve there. A structured field here would make
    every locator kind it adds a schema change in this repository, in exchange
    for queries nobody makes -- the map is read whole or not at all, since
    resolving one offset needs every segment.

    `perceived_with` is `CapabilitySet.fingerprint()`: which models, at which
    revisions, produced this. Two transcripts of one video from two models are
    two different claims, and this is the field that says so.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    derived_from: str
    text: str
    sha256: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None
```

- [ ] **Step 4: Add the command and widen the union**

```python
@dataclass(frozen=True)
class StoreDerivedText:
    """Store what perception made of a medium.

    Carries `corpus_id` for `StoreSourceMedia`'s reason -- though unlike that
    one this can never be the creation command, since it requires a media
    source to already exist. Carried anyway so the three store commands have
    one shape; a command that omitted it would invite the question of why.
    """

    corpus_id: UUID
    source_id: str
    derived_from: str
    text: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None


CorpusCommand = StoreSourceDocument | StoreSourceMedia | StoreDerivedText | DropSourceDocument
```

- [ ] **Step 5: Add the fields to `TextRecord`**

```python
class TextRecord(SourceRecordBase):
    kind: Literal["text"] = "text"
    char_count: int
    derived_from: str | None = None
    """The media source this was perceived from, or None for a fetched document.

    Not a third arm of `SourceRecord`. A derived source *is* text for every
    purpose a reader has -- it chunks, it quotes, it extracts -- and the
    discriminator's job is to answer "can I read this as prose". The cost is
    that this is a nullable field the type checker cannot force anyone to
    consider, and it is paid down in exactly one place: `decide` refuses any
    store that would change a source's derivedness, so nothing can quietly
    become or stop being a transcript.
    """
    perceived_with: str | None = None
    """The capability fingerprint that produced it. None for a fetched document."""
    degradations: tuple[str, ...] = ()
    """What the perception could not do -- "no vision model configured; frames
    were not described". Empty for a fetched document and for a complete
    perception; a reader cannot tell those two apart from here, and does not
    need to, because `derived_from` already does."""
```

- [ ] **Step 6: Add the `decide` cases**

Insert **before** the existing `StoreSourceDocument`/`StoreSourceMedia` guard clauses so a derivedness clash is reported as such rather than as a kind clash:

```python
        case StoreSourceDocument(source_id=source_id), _ if _is_derived(state, source_id):
            raise CommandRejectedError(
                f"source {source_id!r} is derived from "
                f"{_derived_from(state, source_id)!r}; storing a fetched document "
                "under it would overwrite a transcript with prose nobody perceived"
            )

        case StoreDerivedText(source_id=source_id), _ if (
            _kind_of(state, source_id) is not None and not _is_derived(state, source_id)
        ):
            raise CommandRejectedError(
                f"source {source_id!r} is not derived; storing perceived text "
                "under it would replace a source with a reading of another one"
            )
```

and the main case, after `StoreSourceMedia()`:

```python
        case StoreDerivedText(derived_from=parent), _:
            parent_record = state.documents.get(parent)
            if parent_record is None:
                raise CommandRejectedError(f"unknown source {parent!r}")
            if parent_record.kind != "media":
                raise CommandRejectedError(
                    f"source {parent!r} holds text; there is nothing in it to perceive"
                )
            return [
                CorpusDerivedTextStored(
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    derived_from=command.derived_from,
                    text=command.text,
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    locator_map=command.locator_map,
                    perceived_with=command.perceived_with,
                    degradations=command.degradations,
                    title=command.title,
                )
            ]
```

Add the two helpers beside `_kind_of`:

```python
def _is_derived(state: CorpusState, source_id: str) -> bool:
    record = state.documents.get(source_id)
    return record is not None and getattr(record, "derived_from", None) is not None


def _derived_from(state: CorpusState, source_id: str) -> str | None:
    record = state.documents.get(source_id)
    return getattr(record, "derived_from", None)
```

- [ ] **Step 7: Add the `evolve` case**

Model it on `CorpusDocumentStored`'s, including the identical `by_digest` supersession handling, and build a `TextRecord` with `derived_from`, `perceived_with`, and `degradations=tuple(json.loads(event.degradations))`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/domain/test_corpus.py -v`
Expected: PASS, including every pre-existing test.

- [ ] **Step 9: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/domain/corpus.py tests/domain/test_corpus.py
git commit -m "Let the corpus hold what a model made of a medium"
```

---

## Task 3: The read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_read_models.py`

**Interfaces:**
- Consumes: `CorpusDerivedTextStored` from Task 2; `TextRecord`'s new fields.
- Produces: `CorpusDocumentRow.derived_from/locator_map/perceived_with/degradations`, all `str | None`; a `CorpusProjection` handler; `to_record` carrying them through.

- [ ] **Step 1: Write the failing test — assert the row, not the call**

```python
async def test_a_derived_source_lands_in_the_documents_table_with_its_map(corpus_store):
    """Asserts the row and the map, because an assertion that the projection
    "ran" passes with the handler deleted -- an event no projection handles
    counts as applied."""
    await _project(
        CorpusDerivedTextStored(
            aggregate_id=CORPUS_ID,
            source_id="vid#perceived",
            derived_from="vid",
            text="[0:00:01.0] (speech) hello",
            sha256="deadbeef",
            locator_map='[{"char_start": 0, "char_end": 26, '
            '"locator": {"kind": "time", "start_s": 1.0, "end_s": 2.0}}]',
            perceived_with="fingerprint123",
            degradations='["no vision model configured"]',
        )
    )
    row = await corpus_store.get(CorpusDocumentRow.row_id(PROJECT_ID, "vid#perceived"))
    assert row is not None
    assert row.derived_from == "vid"
    assert row.perceived_with == "fingerprint123"
    assert json.loads(row.locator_map)[0]["locator"]["start_s"] == 1.0
    assert row.text == "[0:00:01.0] (speech) hello"


async def test_a_fetched_document_leaves_the_derived_columns_null(corpus_store):
    """The columns are nullable and a plain document is what makes them so."""
    await _project(CorpusDocumentStored(...))
    row = await corpus_store.get(CorpusDocumentRow.row_id(PROJECT_ID, "paper"))
    assert row.derived_from is None
    assert row.locator_map is None


def test_to_record_carries_derivedness_back_out():
    row = CorpusDocumentRow(..., derived_from="vid", perceived_with="fp", degradations='["a gap"]')
    record = to_record(row)
    assert record.kind == "text"
    assert record.derived_from == "vid"
    assert record.degradations == ("a gap",)
```

- [ ] **Step 2: Run and watch fail**

Run: `uv run pytest tests/infrastructure/test_read_models.py -v -k derived`
Expected: FAIL — no such field.

- [ ] **Step 3: Add the columns**

On `CorpusDocumentRow`, all four `str | None = None`. Nullable is mandatory: `apply_schema` reconciles an added nullable column onto a populated table and refuses a required one with no default. Put a comment on `locator_map` saying it is JSON, that it is read whole because resolving one offset needs every segment, and that the union it encodes belongs to `readeverything`.

- [ ] **Step 4: Add the projection handler**

A `CorpusDerivedTextStored` handler on `CorpusProjection` writing a `CorpusDocumentRow` with `char_count=len(event.text)` and the four new columns. It writes to `corpus_documents`, not a new table, because a derived source is a text source and every text reader must find it there.

- [ ] **Step 5: Carry the fields through `to_record`**

`degradations` is stored as JSON and the record wants `tuple[str, ...]`; decode with `tuple(json.loads(row.degradations)) if row.degradations else ()`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/infrastructure/test_read_models.py -v`
Expected: PASS

- [ ] **Step 7: Verify against a database that predates the change**

This is the standing rule and this slice is the harder of `apply_schema`'s two paths — nullable columns onto a **populated** table, which sub-project 1 did not exercise.

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/perception-probe.db
```

Then start the app against the printed `AGENT_DB=` line and confirm the Documents page answers 200 with its existing rows intact. Record in the task report what you ran and what you saw; "it works on my fresh database" is the sound of the bug this rule exists for.

- [ ] **Step 8: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/infrastructure/persistence/read_models.py tests/
git commit -m "Project derived text into the documents table it belongs in"
```

---

## Task 4: The perception port and its `readeverything` adapter

**Files:**
- Create: `research_team/application/perception.py` (the port half only; `MediaPerceiver` is Task 5)
- Create: `research_team/infrastructure/perception/__init__.py`
- Create: `research_team/infrastructure/perception/readeverything_adapter.py`
- Test: `tests/infrastructure/test_readeverything_adapter.py`

**Interfaces:**
- Consumes: `config.transcriber_url/transcriber_model/vision_model/perception_max_chars/perception_root`, `config.blob_root`.
- Produces: `PerceptionPort`, `Perceived`, `LocatorSpan`, `PerceptionCapabilities`, `ReadEverythingPerception(blob_root, perception, capabilities)`.

- [ ] **Step 1: Write the port**

```python
"""Making a stored medium legible.

The port takes a digest and no mimetype. Detection is `readeverything`'s job
and it does it from content -- measured on 2026-08-15, an extensionless file
named for its own sha256 was identified as `video/mp4` -- so handing it this
repository's stored `media_type` would be giving a sniffed guess to something
with a better sniffer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LocatorSpan:
    """A stretch of the rendered text, and where in the medium it came from."""

    char_start: int
    char_end: int
    locator: dict[str, object]
    """`readeverything`'s locator, as JSON-ready data. A dict rather than the
    library's union type so nothing above this line imports `readeverything`:
    the adapter is the only place that should know which library perceives."""


@dataclass(frozen=True)
class Perceived:
    text: str
    locators: tuple[LocatorSpan, ...]
    fingerprint: str
    degradations: tuple[str, ...]


@dataclass(frozen=True)
class PerceptionCapabilities:
    """What this install can actually do.

    A structure rather than a boolean because the 503 has to name what is
    absent: "no vision model configured" and "ffmpeg not found" send an
    operator to two different places, and a route that can only say "not
    configured" sends them to neither.
    """

    vision: bool
    asr: bool
    ffmpeg: bool

    def any_model(self) -> bool:
        """Whether anything here can perceive rather than merely describe.

        With neither model, `represent` still returns a metadata stub -- "Image
        x.png, 64x48 PNG, 469 bytes" -- and storing that would put a sentence
        no human wrote into the corpus to be extracted as evidence. So this is
        the question the route asks before doing any work.
        """
        return self.vision or self.asr

    def missing(self) -> tuple[str, ...]:
        absent = []
        if not self.vision:
            absent.append("no vision model (AGENT_VISION_MODEL)")
        if not self.asr:
            absent.append("no transcriber (AGENT_TRANSCRIBER_URL)")
        if not self.ffmpeg:
            absent.append("ffmpeg not found on PATH")
        return tuple(absent)


class PerceptionPort(Protocol):
    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived: ...

    def capabilities(self) -> PerceptionCapabilities: ...
```

- [ ] **Step 2: Write the failing adapter tests**

Use `readeverything.testing`'s fakes and a real temporary root; **no network**.

```python
async def test_it_reads_a_blob_by_digest_with_no_copy(tmp_path):
    """The blob store's own tree is the perception root. Measured 2026-08-15:
    content sniffing identifies an extensionless digest-named file, so the uri
    is `ab/abc...` and nothing is materialised anywhere."""
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = await build_test_adapter(tmp_path, vision=FakeVision("a red square"))
    perceived = await adapter.perceive(sha256=digest, max_chars=1000)
    assert "red square" in perceived.text
    assert perceived.locators[0].char_start == 0


async def test_a_missing_capability_becomes_a_named_degradation(tmp_path):
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = await build_test_adapter(tmp_path)  # no models at all
    perceived = await adapter.perceive(sha256=digest, max_chars=1000)
    assert perceived.degradations
    assert any("vision" in d for d in perceived.degradations)


async def test_capabilities_report_what_is_missing(tmp_path):
    adapter = await build_test_adapter(tmp_path)
    assert adapter.capabilities().any_model() is False
    assert any("AGENT_VISION_MODEL" in m for m in adapter.capabilities().missing())


async def test_the_fingerprint_changes_when_the_model_does(tmp_path):
    """It is what invalidates a derived transcript. If it did not move with the
    model, two models' readings would be indistinguishable in the corpus."""
    one = await build_test_adapter(tmp_path, vision=FakeVision("x", model_id="v1"))
    two = await build_test_adapter(tmp_path, vision=FakeVision("x", model_id="v2"))
    assert one.capabilities() != two.capabilities() or _fingerprint(one) != _fingerprint(two)
```

Check `FakeVision`'s actual constructor signature before writing these — it is `readeverything.testing.FakeVision` and this plan does not assume its parameter names.

- [ ] **Step 3: Run and watch fail**

Run: `uv run pytest tests/infrastructure/test_readeverything_adapter.py -v`
Expected: FAIL, module does not exist.

- [ ] **Step 4: Implement the adapter**

```python
class ReadEverythingPerception:
    """`readeverything` over the blob store's own directory tree.

    The root is `blob_root()` itself and the uri for a medium is
    `f"{sha256[:2]}/{sha256}"` -- the fan-out path the store already writes.
    Nothing is copied. The alternative considered and rejected was
    materialising each blob to a temp file with a plausible extension, which
    would have cost a full second copy of a file up to the 2GB upload ceiling
    on every perception, to give a sniffer a filename it does not consult.

    The consequence to know: this `Perception` can read any project's blobs,
    because the blob store is not partitioned by project. That is safe only
    because the digest handed to `perceive` came from the calling project's own
    read model -- there is no path from a uri back to a project, so nothing
    here can be asked to enumerate.
    """

    def __init__(self, *, perception: Perception, capabilities: PerceptionCapabilities,
                 fingerprint: str) -> None: ...

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        rendered = await self._perception.represent(
            f"{sha256[:2]}/{sha256}", Budget(max_chars=max_chars)
        )
        ...
```

Convert each `LocatorSegment` to a `LocatorSpan` with a `dict` locator tagged by kind — `{"kind": "time", "start_s": ..., "end_s": ...}`, `{"kind": "page", "page": ...}`, `{"kind": "bbox", ...}`, `{"kind": "char", ...}`, `{"kind": "byte", ...}`. Tag explicitly rather than relying on which keys are present, so the resolver in Task 5 can dispatch without guessing and an unknown kind is visibly unknown.

**Capabilities are declared from configuration, not probed, and `Perception` is built lazily.** This is the shape, and the reasoning belongs in the code:

- `capabilities()` is synchronous and derives from `AGENT_VISION_MODEL`, `AGENT_TRANSCRIBER_URL` and `shutil.which("ffmpeg")`. It must be synchronous because the route checks it before enqueuing anything, and `build_perception` is `async def`.
- The `CapabilitySet` handed to `build_perception` is constructed explicitly — `CapabilitySet.of({Capability.VISION: vision_model_id, Capability.ASR: transcriber_model_id, Capability.FFMPEG: "present"})`, omitting whichever is absent — so `fingerprint()` is computable without awaiting a probe.
- `build_perception` is awaited on **first `perceive`**, memoized behind an `asyncio.Lock`, not at construction.

The alternative — making `build_application` async — was rejected: it would change every caller in the repository, REPL, web and tests, for one port. The cost of this choice is that a binary present but broken reads as available, so the failure arrives as a degradation from a later `represent` rather than as a 503 up front. That is a worse error message rather than a wrong answer.

**`build_perception` validates an explicitly supplied `capabilities` against `vision.model_id` and raises `DomainError` when they disagree** — so the VISION revision must be exactly the model id passed to `build_openai_vision_model`. Write a test for that agreement; getting it wrong fails at startup, which is the good case, but only if something proves the two are wired from one value.

Write a module-level `build_perception_adapter()` factory that reads config, constructs `RemoteWhisperTranscriber` only when a URL is set, `build_openai_vision_model` only when a vision model is set, and passes `artifacts=FilesystemArtifactStore(root=config.perception_root())`. It is synchronous.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/infrastructure/test_readeverything_adapter.py -v`
Expected: PASS

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/perception.py research_team/infrastructure/perception/ tests/
git commit -m "Perceive a blob where it already lies, rather than copying it"
```

---

## Task 5: `MediaPerceiver` and the locator resolver

**Files:**
- Modify: `research_team/application/perception.py` (add the use case)
- Create: `research_team/application/locators.py`
- Test: `tests/application/test_perception.py`, `tests/application/test_locators.py`

**Interfaces:**
- Consumes: `PerceptionPort`, `CorpusReadPort`, the corpus repository, `StoreDerivedText`.
- Produces: `MediaPerceiver.perceive(project_id, source_id) -> PerceptionReport`, `MediaPerceiver.unperceived(project_id) -> tuple[str, ...]`, `derived_source_id(parent) -> str`, `locators.resolve(locator_map, start, end) -> tuple[dict, ...]`.

- [ ] **Step 1: The resolver, which is a pure function and needs no fixture**

```python
def resolve(locator_map: str, start: int, end: int) -> tuple[dict[str, object], ...]:
    """Which moments or regions a character span covers.

    The span is the one `corpus_spans.quote` already produces for a citation,
    so a media citation costs no new event and no stored offset: the quote is
    resolved against the derived text exactly as it is for any document, and
    this turns the result into a place in the medium.

    Overlap is inclusive at both ends -- a span touching one character of a
    segment gets that segment -- because a quote clipped mid-sentence still
    came from the moment it was clipped in, and returning nothing there would
    read as "this quote is from nowhere".
    """
```

Tests: an empty map returns empty; a span inside one segment returns one locator; a span crossing two returns both in order; a span past the end returns empty rather than raising, matching `quote`'s clamping habit.

- [ ] **Step 2: Write the failing perceiver tests**

```python
async def test_perceiving_stores_a_derived_source_under_the_parent(perceiver, corpus):
    await perceiver.perceive(PROJECT_ID, "vid")
    listing = await corpus.list_sources()
    derived = [x for x in listing if x.record.source_id == "vid#perceived"]
    assert derived, "no derived source was stored"
    assert derived[0].record.derived_from == "vid"


async def test_perceiving_a_text_source_is_refused(perceiver):
    with pytest.raises(NotPerceivable):
        await perceiver.perceive(PROJECT_ID, "paper")


async def test_an_install_with_no_models_stores_nothing(perceiver_without_models, corpus):
    """The assertion is the absent row. With no models, `represent` still
    returns a metadata stub, and storing it would put a sentence no human wrote
    into the corpus to be extracted as evidence."""
    with pytest.raises(PerceptionUnavailable):
        await perceiver_without_models.perceive(PROJECT_ID, "vid")
    assert not [x for x in await corpus.list_sources() if "#perceived" in x.record.source_id]


async def test_partial_degradation_still_stores_and_records_the_gap(perceiver_asr_only, corpus):
    """A transcript with no frame descriptions is real evidence with a named
    gap. Refusing it would mean an install without vision could never
    transcribe anything."""
    await perceiver_asr_only.perceive(PROJECT_ID, "vid")
    record = _find(await corpus.list_sources(), "vid#perceived").record
    assert record.degradations
    assert any("vision" in d for d in record.degradations)


async def test_unperceived_lists_media_with_no_transcript_and_stops_listing_it(perceiver):
    assert "vid" in await perceiver.unperceived(PROJECT_ID)
    await perceiver.perceive(PROJECT_ID, "vid")
    assert "vid" not in await perceiver.unperceived(PROJECT_ID)
```

**The fixture rule applies here.** Add one test whose corpus was seeded by writing `CorpusMediaStored` directly rather than by calling the perceiver or the editor, and perceive against it. A fixture that seeds through the same call the code depends on cannot see that dependency go missing — that is the `graphs.open` finding, and this is its shape here.

- [ ] **Step 3: Run and watch fail**

Run: `uv run pytest tests/application/test_perception.py -v`
Expected: FAIL

- [ ] **Step 4: Implement**

`MediaPerceiver` mirrors `DocumentExtractor`'s constructor style — keyword-only collaborators, a `corpus_readers` callable per project. `perceive`:

1. read the source; `UnknownDocument` if absent, `NotPerceivable` if it is text
2. `PerceptionUnavailable` if `capabilities().any_model()` is false, carrying `missing()` in the message
3. call the port with the record's `sha256` and `config.perception_max_chars()`
4. issue `StoreDerivedText` with `source_id=derived_source_id(parent)`, the JSON-serialised locators and degradations, `perceived_with=fingerprint`, and a title of `f"{parent title or parent source_id} (perceived)"`

Order matters and mirrors `store_media`'s reasoning: perceive first, store second. A rejected store leaves a wasted model call, which is money; the other order would leave a derived record claiming a perception that did not happen.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/application/test_perception.py tests/application/test_locators.py -v`
Expected: PASS

- [ ] **Step 6: Update the extraction docstring**

In `research_team/application/document_extraction.py`, `unextracted`'s docstring currently says media is excluded because "nothing extracts media yet, so every one of them reads `extracted=False` ... and would otherwise queue for an extraction this codebase has no way to perform." Replace that paragraph: media rows are still never extracted, but a medium now reaches the graph through its derived text, which is an ordinary text source and queues on its own. **No code changes** — the `kind == "text"` filter already does the right thing, which is the point worth writing down.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/ tests/application/
git commit -m "Perceive a medium into a text source the graph already knows how to read"
```

---

## Task 6: Composition

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/test_composition.py`

**Interfaces:**
- Consumes: everything from Tasks 4 and 5.
- Produces: `Application.perception: PerceptionPort`, `Application.perceiver: MediaPerceiver`.

- [ ] **Step 1: Write the failing test**

```python
def test_no_transcriber_is_constructed_without_configuration(monkeypatch):
    """The no-network guard, at the seam where a network client would be born."""
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)
    monkeypatch.delenv("AGENT_VISION_MODEL", raising=False)
    app = build_application(...)
    assert app.perception.capabilities().any_model() is False
```

- [ ] **Step 2: Wire it**

`build_application` gains `perception: PerceptionPort | None = None`, matching the optional-port precedent already there (`approvals`, `extractions`, `grants`, `activity`) and for the same reason: a test needs to supply a fake so nothing reaches a network. `None` calls `build_perception_adapter()`, which is **synchronous** — see Task 4, capabilities are declared from configuration and the library's `Perception` is built lazily on first use, precisely so `build_application` does not have to become async.

`MediaPerceiver` is constructed beside `document_extractor`, sharing `corpus_readers` and the corpus repository.

**Construct it where `CorpusRunner` is constructed and register the projection handler in the same change.** A build with the perceiver wired and the projection handler missing serves every perceive request as a 202 and stores nothing visible — `CLAUDE.md` records this exact failure from the entity-definitions work.

- [ ] **Step 3: Run, gates, commit**

```bash
uv run pytest tests/test_composition.py -v
uv run ruff check . && uv run ruff format --check .
git commit -am "Wire perception once, at composition, where the probe belongs"
```

---

## Task 7: The web route

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Modify: `research_team/interfaces/web/extraction.py`
- Test: `tests/interfaces/web/test_perceive_route.py`

**Interfaces:**
- Consumes: `Application.perceiver`, `Application.perception`.
- Produces: `POST /api/projects/{project_id}/sources/{source_id}/perceive`; listing fields `derived_from`, `degradations`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_perceiving_a_medium_answers_202_and_stores_the_row(client, corpus_store):
    response = await client.post(f"/api/projects/{PROJECT_ID}/sources/vid/perceive")
    assert response.status_code == 202
    await _settle()
    row = await corpus_store.get(CorpusDocumentRow.row_id(PROJECT_ID, "vid#perceived"))
    assert row is not None and row.derived_from == "vid"


async def test_an_unconfigured_install_answers_503_and_names_what_is_missing(client_no_models):
    response = await client_no_models.post(f"/api/projects/{PROJECT_ID}/sources/vid/perceive")
    assert response.status_code == 503
    assert "AGENT_VISION_MODEL" in response.json()["detail"]


async def test_perceiving_a_text_source_answers_409(client):
    response = await client.post(f"/api/projects/{PROJECT_ID}/sources/paper/perceive")
    assert response.status_code == 409


async def test_perceiving_an_unknown_source_answers_404(client):
    response = await client.post(f"/api/projects/{PROJECT_ID}/sources/nope/perceive")
    assert response.status_code == 404


async def test_the_listing_carries_degradations_so_the_page_can_say_what_was_missed(client):
    ...
```

- [ ] **Step 2: Run and watch fail**

- [ ] **Step 3: Implement**

Add `perceiving` and `perceived` to `ExtractionNote`'s stage literal in `extraction.py`. The route enqueues through the existing `extraction_queue` rather than running inline — transcription of an hour of audio takes minutes and would hold the connection — and reports through the same `ExtractionActivity` channel, because a second progress pane for one workflow would be a second thing to watch.

Map the exceptions: `UnknownDocument` → 404, `NotPerceivable` → 409, `PerceptionUnavailable` → 503 with `missing()` in the detail.

Add `derived_from` and `degradations` to the source-listing response model and its zod schema on the frontend side.

- [ ] **Step 4: Run, gates, commit**

---

## Task 8: The frontend

**Files:**
- Modify: the Documents page components (`frontend/src/…/DocumentManagePane.tsx` and the listing table; find the exact files — sub-project 1 added the media row rendering there)
- Test: the existing `*.test.tsx` beside them

**Interfaces:**
- Consumes: `derived_from` and `degradations` on the listing; the perceive route.

- [ ] **Step 1: Write the failing tests**

- a media row with no derived source shows a Transcribe control
- a media row that has one does not, and links to the derived source instead
- a derived source's row shows its degradations as text
- a 503 renders the message the server sent, not a generic failure — the whole point of naming `AGENT_VISION_MODEL` is that it reaches a person

- [ ] **Step 2: Implement, keeping it to a control and a line of text**

No player, no cue list, no seeking. Those need sub-project 4's reference syntax and building half of it here means building it twice.

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run verify
```

`npm run test:browser` only if a stylesheet or a measured layout was touched, which this should not need. If it was, run it — and not concurrently with any other vitest process.

- [ ] **Step 4: Commit** (including the rebuilt bundle, as this branch has throughout)

---

## Task 9: Schema evolution and the end-to-end proof

**Files:**
- Modify: `tests/infrastructure/test_schema_evolution.py`
- Create: an end-to-end test beside the existing extraction tests

**Interfaces:** consumes everything above.

- [ ] **Step 1: The schema-evolution case**

Write a `CorpusDerivedTextStored` payload straight into the events table and read it back, mirroring the `CorpusMediaStored` case. It is a new event type, so an older build replays a log containing it without incident — nothing subscribes, and an event no projection handles counts as applied. Assert that, rather than asserting the absence of an exception.

- [ ] **Step 2: The end-to-end test, which is the one that proves the slice**

```python
async def test_a_stored_video_reaches_the_graph_through_its_transcript(app):
    """The whole point of the slice, and nothing else asserts it end to end.

    Store media -> perceive -> the derived source appears in `unextracted` ->
    extract -> the graph holds an entity from what was said. With a fake
    transcriber, so no network."""
```

- [ ] **Step 3: Run both, gates, commit**

---

## Self-Review

**Spec coverage.** Domain → Task 2. Perception port → Task 4. Read model → Task 3. Application (`MediaPerceiver`, `unperceived`, resolver, extraction docstring) → Task 5. Web → Task 7. Frontend → Task 8. Configuration and dependency → Task 1. Composition → Task 6. Testing items 1–6 from the spec: item 1 → Task 3 Step 1; item 2 → Task 5 Step 2; item 3 → Tasks 4, 6; item 4 → Task 5; item 5 → Task 2; item 6 → Task 9. The real-database rule → Task 3 Step 7.

**Not covered by any task, deliberately:** the affordance surface, diarization, and B19, all named as out of scope in the spec. B19 becomes newly overdue when this ships and the spec says so; no task here addresses it.

**Type consistency.** `derived_from: str | None` on `TextRecord` and `str` on the event and command (a derived source always has a parent; a text record usually has none). `degradations` is `str` (JSON) on the event, command and row, and `tuple[str, ...]` on the record — Tasks 2, 3 and 5 all encode and decode at those exact boundaries. `locator_map` is `str` (JSON) everywhere above the adapter; `LocatorSpan.locator` is `dict[str, object]` and is the only structured form, tagged with an explicit `kind`.
