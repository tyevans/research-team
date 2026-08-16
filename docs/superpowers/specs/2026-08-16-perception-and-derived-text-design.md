# Perception and derived text

Media in the corpus is inert. A stored video can be listed, streamed and
proved against its digest, and nothing in the system can say what is in it —
`DocumentExtractor.unextracted` filters media out by name, with a comment
saying this slice is where that changes.

This is sub-project 2 of four. It makes a stored medium *legible*: a
transcript, a frame timeline, an image description, stored back into the same
corpus as a **derived text source** that carries a locator map from its own
character offsets to moments and regions in its parent. Extraction, chunking
and citation then work on it unchanged, because it is text and they already
know how to read text.

What it deliberately does not do is render any of that. A finding that cites
4:12 still displays as prose; the player seeked to 4:12 is sub-project 4, and
this slice's job is to make the 4:12 *recoverable* rather than to draw it.

## What `readeverything` already answers

The library does more than transcribe, and the design below is shaped by what
it hands over rather than by what this repository would have built alone.
Everything in this section was **measured on 2026-08-15 against
`readeverything==0.1.0` from PyPI**, not read off its documentation.

`build_perception(root, *, vision=None, transcriber=None, ...)` returns a
`Perception` over a filesystem root. `Perception.represent(uri, budget)`
returns a `Rendered`:

```python
@dataclass(frozen=True, slots=True)
class Rendered:
    text: str
    locator_map: LocatorMap
    barriers: tuple[int, ...]
    degradations: tuple[Degradation, ...]
```

`LocatorMap.resolve_span(CharSpan) -> tuple[Locator, ...]` where a `Locator` is
`TimeSpan | PageRef | BBox | CharSpan | ByteRange`. **That is the citation
anchor, already built.** This repository does not have to invent a timecode
index; it has to persist one and resolve against it.

Three measurements decide three questions that would otherwise have been
guesses.

**The blob store's own tree can be the perception root.** Detection is
content-authoritative — `PuremagicDetector` sniffs the leading bytes and the
filename is not consulted for a decision it can make itself. A file at
`ab/abdeadbeef0123456789` with no extension was identified as `video/mp4`, and
one at `cd/cdfeedface9876543210` as `image/png`. So the uri for a stored medium
is `f"{sha256[:2]}/{sha256}"` and **nothing is copied**. The alternative —
materialize each blob to a temp file with a plausible extension — would have
cost a full second copy of a file up to the 2 GB upload ceiling, on every
perception, for nothing.

**Missing capabilities degrade loudly rather than silently.** With no vision
model configured, `represent` over that video returned text and a
`Degradation(what='vision unavailable: frames were not described', detail=...)`
rather than raising or quietly emitting less. With a real transcriber wired to
the whisper.cpp server and still no vision, the ASR degradation disappeared and
the vision one remained — partial degradation is reported precisely. This is
the property `CLAUDE.md` spends most of its length defending, arriving for free
from a dependency, and the design's job is not to throw it away.

**Transcript and frame timelines interleave into one text.** The same probe
produced:

```
[0:00:00.0] (frame decoded, 8200 bytes; not described, as no vision model is configured)
[0:00:00.1] (speech) .
```

with segments `CharSpan(0, 89) -> TimeSpan(0.0, 0.1)` and
`CharSpan(89, 112) -> TimeSpan(0.1, 2.0)`. One text, one map, both kinds of
evidence in timeline order.

The whisper.cpp server at `192.168.1.14:8083` answers `POST /inference` and
reports no model name of its own. That settles a configuration question:
`RemoteWhisperTranscriber` requires an explicit `model_id`, there is nothing to
discover it from, and it is load-bearing rather than cosmetic — it is the ASR
revision inside `CapabilitySet.fingerprint()`, which is what invalidates
derived caches when the model changes.

## The problem with storing what comes back

A `Rendered` is text, and this corpus already knows how to keep text. The
temptation is to store it as an ordinary document and be finished. That is
wrong in three specific ways, and each one shapes a field below.

**It is not the author's words.** A quote from a transcript is a quote from a
model's reading of an audio track. Provenance that cannot tell those apart is
the unfalsifiable-provenance failure `domain/corpus.py` exists to prevent, one
level up. A derived source must be permanently distinguishable from a fetched
one.

**It must never be re-fetched.** An ordinary document carries a `uri` and the
system may go back to it. A derived source's "source" is a blob and a model;
re-fetching it means re-perceiving it, which is a different operation with a
different cost.

**Its offsets mean something.** Character 4,312 of a transcript is a moment in
a video. Nothing in `CorpusDocumentStored` has anywhere to put that, and
throwing the locator map away at the moment of storage would mean regenerating
it — another model call — every time anyone wanted to cite it.

## Design

### Domain

A new event, mirroring the existing pair rather than extending them:

```python
@register_event
class CorpusDerivedTextStored(DomainEvent):
    aggregate_type: str = "Corpus"
    source_id: str
    derived_from: str
    text: str
    sha256: str
    locator_map: str      # JSON
    perceived_with: str   # CapabilitySet.fingerprint()
    degradations: str     # JSON
    title: str | None = None
```

New event type, so an older build replays a log containing it without
incident — nothing subscribes and an event no projection handles counts as
applied. `tests/infrastructure/test_schema_evolution.py` gains a case saying
so, as `CorpusMediaStored` did.

`StoreDerivedText` is its command, carrying `corpus_id` for the reason
`StoreSourceMedia` does.

**`derived_from` is validated by the aggregate.** `decide` rejects a
`StoreDerivedText` whose `derived_from` names no source, or names one that is
not media. That is a real invariant and the aggregate is the only place that
can see it: the state holds every source, and a derived text pointing at
nothing is a dangling reference of exactly the kind sub-project 1 refused to
allow for blobs.

**`sha256` is computed here, not supplied.** Same reasoning as
`CorpusDocumentStored`: it is text, the aggregate has the bytes, and a supplied
digest would make `by_digest` a claim. Media supplies its digest only because
the aggregate never sees the bytes.

**A derived source is a `TextRecord`, not a third union arm.** `SourceRecord`
stays `TextRecord | MediaRecord`, and `TextRecord` gains
`derived_from: str | None`, `perceived_with: str | None` and
`degradations: tuple[str, ...]`. The alternative — `kind: "derived"` — was
rejected because every reader that discriminates would need a third arm, and a
derived source *is* text for every purpose those readers have: it chunks, it
quotes, it extracts. The discriminator exists to answer "can I read this as
prose", and the answer here is yes.

The cost is that `derived_from` is a nullable field the type checker cannot
force anyone to consider. That is paid down in the one place it matters:
`decide` refuses a store that would change a source's derivedness. A plain
document cannot be overwritten by a derived one, or the reverse. Supersession
by `source_id` means "a re-fetch of the same URI is a revision"; a transcript
landing on a document's id is not a revision, for the same reason a video
landing on a document's id is not.

**The derived `source_id` is `f"{parent}#perceived"`.** Deterministic, so
re-perceiving supersedes rather than accumulating, and the relationship is
legible in a log without a join. `#` because no fetched `source_id` in this
corpus contains one — it is a URI fragment delimiter, and a fragment is
precisely what this is.

### Perception port

```python
# application/perception.py

@dataclass(frozen=True)
class Perceived:
    text: str
    locators: tuple[LocatorSpan, ...]
    fingerprint: str
    degradations: tuple[str, ...]

@dataclass(frozen=True)
class LocatorSpan:
    char_start: int
    char_end: int
    locator: dict[str, object]   # readeverything's locator, as JSON

@dataclass(frozen=True)
class PerceptionCapabilities:
    """What this install can actually do. `missing` is what a 503 says."""

    vision: bool
    asr: bool
    ffmpeg: bool

    def any_model(self) -> bool:
        return self.vision or self.asr

    def missing(self) -> tuple[str, ...]: ...

class PerceptionPort(Protocol):
    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived: ...
    def capabilities(self) -> PerceptionCapabilities: ...
```

`capabilities()` rather than a bare boolean because the 503 has to name what is
absent — "no vision model configured" and "ffmpeg not found" send an operator
to two different places, and a route that can only say "not configured" sends
them to neither.

`sha256` rather than a path or a stream, because the adapter derives the uri
from the digest and the blob root is the perception root. The port takes no
mimetype: detection is the library's job and it does it from content, so
passing this repository's stored `media_type` would be handing a sniffed guess
to something with a better sniffer.

`capabilities()` is the 503 seam. An install with neither a transcriber nor a
vision model can still `represent` a video — it returns a metadata stub and two
degradations — and **storing that stub would be the worst outcome available**:
a sentence no human wrote, in the corpus, extracted into the graph as evidence.
So the route asks first and refuses, and this is a configuration question
answerable before any work is done.

Partial capability is different and does store. A transcript with no frame
descriptions is real evidence with a real gap, the gap is named in
`degradations`, and refusing it would mean an install without a vision model
could never transcribe anything.

The adapter is `infrastructure/perception/readeverything_adapter.py`. It owns
one `Perception`, built once at composition against `config.blob_root()`, with
a `FilesystemArtifactStore` under `~/.research-team/perception/` so a
re-perception of unchanged bytes with unchanged capabilities costs nothing —
the library keys its artifact cache on content hash, handler version,
affordance, params and capability fingerprint together.

### Read model

`corpus_documents` gains four nullable columns: `derived_from`,
`locator_map` (JSON), `perceived_with`, `degradations` (JSON). Nullable
because `apply_schema` reconciles an added nullable column onto an existing
database and refuses a required one with no default — `CLAUDE.md` records both
halves, and the second is why widening is chosen here where sub-project 1 chose
a new table. A media row cannot answer these; a text row can, with NULL.

**The locator map is one JSON column, not a row per segment.** It is read whole
or not at all — `LocatorMap.build` needs every segment to resolve one offset —
and no query will ever filter on a locator's internals. The trade is that the
locator union is `readeverything`'s to evolve, and a flattened schema would
make every new locator kind a migration here. A two-hour video is a few
thousand segments, tens of kilobytes; that is document-scale, which is the
scale this table is already built for.

`CorpusProjection` gains a `CorpusDerivedTextStored` handler. Per `CLAUDE.md`,
every test for it asserts a row, never a 2xx.

### Application

`MediaPerceiver` in `application/perception.py`, mirroring `DocumentExtractor`
deliberately — same shape, same constructor style, same `UnknownDocument`:

- `perceive(project_id, source_id) -> PerceptionReport` — reads the media
  record, refuses a text one, calls the port with the digest, issues
  `StoreDerivedText`.
- `unperceived(project_id) -> tuple[str, ...]` — live media sources with no
  derived text, in listing order.

`CorpusReadPort` gains `derived_of(source_id) -> str | None` and its inverse is
free: a derived record carries `derived_from`.

A resolver, `application/locators.py`:

```python
def resolve(locator_map: str, start: int, end: int) -> tuple[dict, ...]
```

Given a derived source's stored map and a character span — the span
`corpus_spans.quote` already produces for a citation — return the locators it
covers. This is the whole of what sub-project 4 will consume, and it is a pure
function over a JSON string, so it needs no port and no fixture.

`DocumentExtractor.unextracted` changes behaviour without changing code: a
derived source is `kind == "text"` and unextracted, so it queues. Its docstring
must stop saying nothing extracts media — the truth becomes that media is
extracted *through* its derived text, and the media row itself still never is.

### Web

- `POST /api/projects/{id}/sources/{source_id}/perceive` — 202 and progress
  through the existing `ExtractionActivity` channel with two added stages,
  `perceiving` and `perceived`. A second progress pane for one workflow would
  be a second thing to watch; the queue in `extraction_queue.py` already
  serialises model work and this joins it rather than competing for the server.
- **503 when `capabilities().any_model()` is false**, naming what is missing —
  vision, ASR, ffmpeg. Not 501: the route exists and the install has not been
  given what it needs, which is an operator's problem and should read like one.
- 409 when the source is text rather than media.
- The listing response carries `derived_from` and `degradations`, so the page
  can say what was missed.

### Frontend

The Documents page gains a Transcribe control on a media row with no derived
text, and, on one that has it, a link to the derived source — which is an
ordinary text row and already renders. Degradations show as a plain line of
text beneath the derived source's title: "no vision model configured; frames
were not described."

No player, no cue list, no seeking. Those need the reference syntax
sub-project 4 is for, and building half of it here would mean building it
twice.

### Configuration

Four variables in `infrastructure/config.py`, all unset-means-off:

- `AGENT_TRANSCRIBER_URL` — whisper.cpp base url. Unset, no ASR.
- `AGENT_TRANSCRIBER_MODEL` — **required when the url is set**, raising when it
  is not. There is nothing to discover it from (the server reports no name,
  measured above) and it is the ASR revision in the capability fingerprint, so
  a wrong or absent one silently mixes two models' output in one cache.
- `AGENT_VISION_MODEL` — unset, no frame description or image reading. Reuses
  `AGENT_BASE_URL`/`AGENT_API_KEY`, since `build_openai_vision_model` speaks to
  an OpenAI-compatible endpoint and the local server is one.
- `AGENT_PERCEPTION_MAX_CHARS` — the `Budget`, defaulting to
  `MAX_DOCUMENT_CHARS` (200,000). The derived text is a document and documents
  are capped; a separate number would be a second answer to one question.

`ffmpeg` and `ffprobe` are **OS binaries, not Python dependencies**. Without
them `readeverything`'s capability probe drops the video and audio handlers
entirely and every video degrades to `BinaryHandler`, which is a silent-ish
failure mode this repository will not tolerate: `capabilities()` reports FFMPEG
alongside the models, and the 503 names it. Both are present on CI's Ubuntu
runners and on the development machine (ffmpeg 6.1.1, verified 2026-08-15).

### Dependency

```toml
"readeverything[remote-transcription,images,documents,vision]>=0.1.0,<0.2",
```

Capped below the next minor, for the reason `eventsource-py` and `redstring`
are: pre-1.0, and a minor is where breaking renames land. The extras add
`pillow` and `pypdfium2` as new weight; `remote-transcription` is `httpx`,
already present, and `vision` is `langchain-openai`, already present.

**The PyPI release is 0.1.0 and the working copy elsewhere is an unreleased
0.2.0.** This spec is written against 0.1.0 because that is what
`uv sync` can resolve, and every measurement above was taken against 0.1.0
installed from PyPI rather than against the source tree.

## Testing

The four gates. `npm run test:browser` only if a stylesheet is touched, which
this slice should not need.

`readeverything.testing` ships `FakeTranscriber` and `FakeVision` for exactly
this, and they are what the suite uses. Beyond the obvious:

1. **A projection test that asserts the derived row and its locator map**, not
   that perceive returned 202. The 202 passes with the handler deleted.
2. **A test whose fixture did not perceive**, per the `graphs.open` finding:
   write `CorpusDerivedTextStored` directly and read it back, so a path that
   forgets to do something the perceiver does is visible.
3. **A no-network guard.** No test may reach `192.168.1.14` or any other host.
   An adapter test uses `httpx.MockTransport` through
   `RemoteWhisperTranscriber`'s `transport` seam; a composition test asserts
   that with no environment set, `any_model()` is false and no transcriber is
   constructed.
4. **A refusal test for the empty perception**: with neither model configured,
   the route answers 503 and **no source is stored** — the assertion is the
   absent row, because the failure this prevents is a stub in the corpus.
5. **A derivedness-supersession test**: storing derived text over a plain
   document's id is refused, and the reverse, naming both kinds.
6. **An extraction test**: a derived source appears in `unextracted` and
   extracts, because that is the entire point of the slice and nothing else
   asserts it end to end.

Plus the standing rule: run the read-model change against a copy of a real
database via
`uv run python -m research_team.infrastructure.persistence.local_copy`. This
slice adds nullable columns to a *populated* table, which is the harder of
`apply_schema`'s two paths and the one sub-project 1 did not exercise.

## What this makes true, and what it does not

An autonomous run can now put a video in a corpus and end up with entities and
edges from what was said in it. That was the question sub-project 1 could not
answer.

It still cannot *watch* the video in any sense a person would recognise:
frames are sampled and described one at a time, and nothing reasons across
them. Nor can it acquire media — `fetch` meeting an MP4 is sub-project 3 — so
media arrives by upload only.

**One thing gets worse, and it is worth saying plainly.** `BACKLOG.md` B19
records that nothing in the event log can be erased, and names its one item
with a deadline: pseudonymize identifiers at intake, because it "becomes
impossible the moment the first real transcript is ingested." This slice is
what ingests the first real transcript. It does not solve B19 and is not
scoped to; it moves that deadline from hypothetical to imminent, and anyone
reading B19 after this ships should read it as overdue rather than pending.

## Out of scope

- **The affordance surface.** `readeverything` ships `build_tools`, giving an
  agent `inspect_path` / `invoke_affordance` / `ask_about_image` over a root —
  a genuinely different way to use media, where the agent asks questions of a
  file instead of reading a flattened rendering of it. It is a larger design
  than this one and would compete with `represent` rather than complete it.
- **Diarization.** The capability exists and no adapter here supplies it, so
  every cue's speaker is `None`. Worth having for interview material and it
  needs its own model.
- **Sub-projects 3 and 4**, unchanged in scope from the previous spec.
