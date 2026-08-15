# Media in the corpus

A corpus can hold a video, an audio file or an image as a first-class source:
stored, listed, dropped, streamed back, and provable against a digest. Nothing
in this slice looks *at* the media. It is inert evidence, and that is the
point — the layer that perceives it (`readeverything`) is worthless without a
layer that keeps it, and keeping it is where the interesting decisions are.

This is sub-project 1 of four. The others — perception and derived text,
acquisition, citation display — are named at the end so this document's
boundaries are legible, and are out of scope here.

## The problem the current corpus poses

`domain/corpus.py` states the guarantee this project's provenance rests on:

> The log keeps the bytes, so a quote can be verified against them years later.

It means that literally. `CorpusDocumentStored.text` is the document, carried
in the event payload; `CorpusState` deliberately holds no text so snapshots
stay small, and retrieval is a read model's job. `decide` computes the sha256
itself, and says why: a supplied digest "makes `by_digest` a claim instead of a
fact, and a wrong one stays invisible until two unrelated documents collide in
it."

None of that survives contact with a 400MB video. Snapshots are taken every 50
events; an event payload holding media bytes would fold whole films into the
event store and into every replay. The guarantee has to change shape, and the
only honest question is what replaces it.

## What replaces it

**The log holds the claim; a content-addressed store holds the bytes; the
digest is what joins them.** A `CorpusMediaStored` event carries `sha256`,
mimetype, byte count and the same provenance metadata a document carries. The
bytes live under their own digest in a blob store. A citation into media is
checkable exactly as far as the blob is present, and when it is absent that is
*detectable* rather than silent — which is the property the original guarantee
was actually buying.

Two alternatives were considered and rejected.

*Bytes inline below a size threshold, blob store above it.* It preserves the
current guarantee for images and splits provenance into two stories. Two
stories that must agree and are not the same story will eventually disagree,
and the threshold is a knob nobody can set correctly — the first 30MB PNG makes
it wrong in one direction and the first 200KB video clip makes it wrong in the
other.

*Media never enters the corpus; only derived text does* — the transcript, the
OCR, the description. The corpus stays untouched and this whole slice
disappears. It also destroys the thing the perception layer is for: you can no
longer go back and check the frame at 4:12, only the sentence a model wrote
about it. That is the unfalsifiable-provenance failure `corpus.py` was written
to prevent, reintroduced one level up.

## Where the digest stops being a fact

This is the real cost and it should not be buried.

For text, `decide` computes the digest from bytes it holds, so `by_digest` is a
fact about the event. For media the bytes never pass through the domain — they
are streamed to disk by the application layer, because holding a video in
memory to hand it to a pure function is not a thing to do. So the command
carries a digest computed elsewhere, and the domain takes it on trust.

The mitigation is that *nothing else can supply one*. `BlobStorePort.put`
computes the digest while streaming and returns it; the store-media use case
passes through what `put` returned and has no parameter by which a caller could
offer a different value. A wrong digest therefore requires a bug in the blob
store rather than a mistake at a call site, which is the difference between a
hazard and a trap.

`domain/corpus.py`'s module docstring must say this, in the paragraph that
currently explains why the digest is computed rather than accepted. A
guarantee that quietly weakened is worse than one that never existed.

## Design

### Domain

`CorpusState.documents` becomes a map to a union rather than to
`DocumentRecord`:

```python
SourceRecord = TextRecord | MediaRecord
```

`TextRecord` is today's `DocumentRecord`, renamed, plus `kind: Literal["text"]`.
`MediaRecord` carries `kind: Literal["media"]`, `media_type` (the mimetype),
`byte_count`, and the same `source_id`/`sha256`/`uri`/`title`/`published_at`/
`note`/`fetched_at`/`dropped_reason` as its sibling. The shared fields are a
frozen base model; the two subtypes add the one field each that the other
cannot answer for (`char_count` against `byte_count`).

**One `source_id` namespace, not two.** A drop, a citation and a read all
address a source by id, and a second namespace would make each of those
ambiguous at exactly the point where being wrong is unrecoverable. The cost is
that `documents` is now heterogeneous and every reader discriminates; the
discriminator is a literal field, so the type checker finds the readers rather
than the tests finding them at runtime.

**Storing media under a `source_id` that currently holds text is refused, and
vice versa.** Supersession by `source_id` exists because "a re-fetch of the same
URI is a revision of one document"; a URI that returned prose yesterday and a
video today is not a revision, it is a different source wearing a used name.
`CommandRejectedError` naming both kinds, because the next thing anyone asks is
which one is there now.

New event, new command, mirroring the existing pair exactly:

```python
@register_event
class CorpusMediaStored(DomainEvent):
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
```

`StoreSourceMedia` is its command, carrying `corpus_id` for the same reason
`StoreSourceDocument` does: storing is what brings a corpus into existence, so
on a fresh corpus there is no state to read the id off.

`DropSourceDocument` is **not** duplicated. It addresses a `source_id` and
reads only `dropped_reason`, both of which the union shares; a second drop
command would be a second way to say one thing. Its docstring should stop
saying "document" in the sense of prose. `CorpusDocumentDropped` keeps its
name — the event is already written into real logs, and renaming a stored
event buys nothing this project needs.

`by_digest` is shared across kinds unchanged. Identical bytes under two
`source_id`s stay detectable and un-refused, for the reason already recorded:
"the same document legitimately arrives at two URIs, and the domain has no
basis for choosing which one the caller meant."

### The blob store

A port in `application/blobs.py`, an implementation in
`infrastructure/persistence/blob_store.py`.

```python
class BlobStorePort(Protocol):
    async def put(self, stream: AsyncIterator[bytes]) -> BlobStat: ...
    async def open(self, sha256: str) -> AsyncIterator[bytes]: ...
    async def stat(self, sha256: str) -> BlobStat | None: ...
```

`BlobStat` is `sha256` and `byte_count`. `put` returns rather than accepts the
digest, per the section above. `stat` returning `None` is how a caller asks
"are the bytes still there", and is the seam every missing-blob report goes
through.

The filesystem implementation writes to `~/.research-team/blobs/ab/abcdef…`,
two hex characters of fan-out because a flat directory of a hundred thousand
files is slow to list on every filesystem that matters. Writes go to a
temporary file in the same directory and are `os.replace`d into place once the
digest is known — a torn write must never be readable under a name that claims
its content, and `os.replace` within one filesystem is the atomicity we need.

**Write-once.** If the target already exists, `put` discards its temporary file
and returns the stat of what is there. Content addressing makes that safe and
makes deduplication free: the same video ingested into two projects is one
blob.

The root is an explicit constructor argument, not a module-level default read
from the environment. `config.py` computes it beside the database path and
hands it to composition, so a test can point one at a temporary directory
without touching the process.

**Orphans are accepted; dangling references are not.** A blob written whose
command is then rejected leaves an unreferenced file — harmless, because
content addressing means a later store of the same bytes adopts it rather than
duplicating it. No garbage collection in this slice; if it is ever wanted it is
a sweep over `corpus_media.sha256`, which is why the read model below carries
the digest. The failure that *does* matter is the reverse: a record whose blob
is gone. That must be loud, and is, because `read_media` distinguishes three
answers rather than two.

### Read model

A new table, `corpus_media`, rather than columns on `corpus_documents`.
`corpus_documents.text` is NOT NULL and every media row would have to lie
about it; a nullable text column would then let a text row lie too. `CLAUDE.md`
also records that `apply_schema` refuses a required column with no default
outright, so widening is the more expensive of the two paths as well as the
less honest one.

Columns: `project_id`, `source_id`, `sha256`, `media_type`, `byte_count`,
`uri`, `title`, `published_at`, `note`, `fetched_at`, `dropped_reason`. No
`extracted_at` — nothing extracts media in this slice, and a column whose only
value is NULL is a promise the next slice may not want to keep.

`CorpusRunner` gains handlers for `CorpusMediaStored` and, on
`CorpusDocumentDropped`, updates whichever table holds the id.

**`CorpusRunner` must be constructed with the media projection registered, and
no test that merely asserts a 200 will notice if it is not.** `CLAUDE.md`
records why: an event no projection handles counts as APPLIED, so a missing
projection produces an empty read model rather than a refusal. Every test here
asserts on a row.

### Application

`CorpusReadPort` gains:

- `list_sources(*, include_dropped=False) -> list[SourceListing]` — both
  kinds, discriminated. `SourceListing` replaces `DocumentListing`: same
  shape, but `record` is a `SourceRecord` and `extracted` is always `False`
  for media in this slice — a field the row cannot answer for yet, kept on the
  listing rather than split out, because the Documents page renders one table
  and a listing type per kind would make it assemble two.
  `list_documents` is **removed**, not kept beside it:
  two list methods is how a caller silently sees half a corpus. Its callers —
  the agent's `list_sources` tool, the console route, the topic queue — are
  updated to discriminate. This is a breaking change to a Protocol, which is
  fine (pre-release, no back-compat) and must be exhaustive rather than
  additive precisely because "sees half the corpus" is a silent failure.
- `read_media(source_id, *, include_dropped=False) -> MediaHandle | None`,
  where `MediaHandle` carries the record and a stream factory. Three outcomes,
  not two: `None` for no such source, a handle whose `stat` is `None` for a
  record whose bytes are missing, and a working handle otherwise. The middle
  one is the dangling-reference case and callers must not be able to confuse
  it with the first.

`read_document` is unchanged and now returns `None` for a media source. That
is right — it promises text, and a media source has none.

A `StoreMedia` use case in `application/corpus_editing.py`, beside the existing
editor: stream to the blob store, then issue `StoreSourceMedia` with the digest
`put` returned. Order matters and is not arbitrary — bytes first means a
rejected command leaves an orphan, while command first would mean a committed
record with no bytes, which is the dangling reference we just said must not
happen.

### Web

- `POST /api/projects/{project_id}/sources/media` — multipart upload,
  streamed to the blob store rather than buffered. `media_type` from the
  upload's content type, corrected by sniffing the leading bytes when they
  disagree; browsers send `application/octet-stream` for plenty of things that
  are not.
- `GET /api/projects/{project_id}/sources/{source_id}/content` — streams the
  bytes back with the stored mimetype. **Range requests are supported in this
  slice**, ahead of the citation work that needs them: a `<video>` element
  seeking to 4:12 issues a range request, and without one Chromium downloads
  the whole file before it will play. Cheap now, and the alternative is a
  Documents page that appears to work and stalls on the first large file.
- A record whose blob is missing answers **410 Gone**, not 404. The source
  exists and its bytes do not, and that is a different thing an operator needs
  to be told.
- The existing drop/restore/patch routes address a `source_id` and work
  unchanged.

An upload size ceiling, configurable, defaulting to 2 GB. Streaming bounds
memory; the ceiling bounds disk, which nothing else does.

### Frontend

The Documents page lists media rows alongside text ones: kind, mimetype,
human-readable size. Selecting one shows a `<video>`, `<audio>` or `<img>`
against the content route rather than a text pane, with the digest and byte
count beside it, and drop/restore exactly as text has.

No transcript view, no player controls beyond the browser's own, no thumbnails.
Thumbnails need a frame, a frame needs `ffmpeg`, and that is the perception
slice.

## Testing

The four gates, and `npm run test:browser` if a stylesheet or a measured layout
is touched.

Three tests this repository's history says will otherwise be missing:

1. **A projection test that asserts the row, not the response.** An assertion
   that the upload returned 201 passes with the media projection deleted
   entirely.
2. **A test whose fixture has not opened the blob store**, mirroring the
   `graphs.open` finding in `CLAUDE.md`: at least one path exercised from a
   fixture that did not itself make the call the code under test is
   responsible for making. Concretely, a read against a project whose media was
   inserted by writing the event directly rather than by going through
   `StoreMedia`.
3. **A dangling-reference test**: store media, delete the blob from the store
   underneath it, assert 410 and a `stat` of `None` — not an exception, and not
   a 404.

Plus the standing rule: run the read-model change against a copy of a real
database, via
`uv run python -m research_team.infrastructure.persistence.local_copy`. A new
table on an existing database is the case `apply_schema` handles most easily,
which is exactly why it should be confirmed rather than assumed.

Schema evolution: `CorpusMediaStored` is a *new* event type, so an older build
replays a log containing it without incident — nothing subscribes, and an event
no projection handles counts as applied. That is the intended behaviour and
`tests/infrastructure/test_schema_evolution.py` gains a case saying so.

## Out of scope, and where it goes

- **Perception and derived text** (sub-project 2) — `readeverything` over a
  root materialized from the corpus; transcripts, OCR and descriptions stored
  as derived text sources carrying their parent's `source_id` and a timecode
  index; extraction reaching the graph through them. This is where the
  citation story lands: a media citation is a span over the derived transcript
  plus a timecode anchor, so `corpus_spans.chunk`/`quote` keep working
  unchanged and no event has to record an offset.
- **Acquisition** (sub-project 3) — `fetch` meeting a non-HTML URL,
  `web_search` returning media results.
- **Citation display** (sub-project 4) — a finding citing 4:12 rendering as a
  player seeked there.

Nothing in this slice presumes their designs. The one place it reaches ahead is
range support on the content route, and that is argued for above on its own
terms.
