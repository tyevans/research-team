# Media in courses: where the chain breaks

Read-only investigation, 2026-08-22. Every claim below is marked **measured**
(a value traced or a probe run) or **read** (inferred from code that was read
but not executed).

## Summary in one line

Nothing is broken in the media machinery. There are **three independent
breaks**, and the one that explains "no images at all" is the last: the
authoring prompts never mention images, the lesson renderer has no media
widget, and the sanitiser deletes `![](url)` outright — so even a model that
tried could not put a picture on a page.

---

## 1. Scraping: media is destroyed at extraction

`research_team/infrastructure/agent/fetch.py:104-109` is the whole decision:

```python
text = trafilatura.extract(
    html,
    output_format="markdown",
    include_links=True,
    include_tables=True,
)
```

`include_images` is not passed. Trafilatura defaults it to `False`.

**Measured** — `extract_page` run against a page carrying `<figure><img
src=… alt=… srcset=…><figcaption>`, `<video>`, `<audio>` and `<picture>`:

```
('# Rome\n\nSome prose about the Roman empire…\n\nMore prose follows here…', 'Rome', None)
```

Not the `src`. Not the `alt`. Not the `figcaption`. Not the poster frame. The
elements are gone before any text is stored, so no downstream stage can
recover them — not the corpus, not extraction, not the graph.

One survivor, **read**: `include_links=True` means an image reached through an
anchor (`<a href="x.jpg">plate 4</a>`) keeps its URL as a markdown link. That
is incidental, not a channel.

## 2. What a source can hold

`research_team/domain/corpus.py:293` and `:330` — `SourceRecord` is a
discriminated union of exactly two shapes:

- `TextRecord` — prose, optionally `derived_from` a medium, with
  `perceived_with` and `degradations`.
- `MediaRecord` — `media_type`, `byte_count`, and a `sha256` that addresses
  blob-store bytes. It deliberately carries **no URL and no path**
  (`corpus.py:333`: "The digest *is* the address").

So a source is one text blob **or** one media blob, never text with attached
figures. `POST /api/projects/{id}/sources` writes the first;
`POST /api/projects/{id}/sources/media` (multipart, `app.py:1320`) writes the
second. There is no field on either for embedded media. **Read.**

## 3. The media path that does exist — and it is fully wired

This is not a port with no adapter. Every link is constructed in
`composition.py` (`media_perceiver` at :2239, `media_accept_worker` at :2522,
reconcile interval at :2583). **Read**, but from the composition root itself,
which is the place the co-mention defect was invisible from.

The chain:

1. **Curation** (`application/media_curation.py`) — three fixed model calls
   per topic: what wants to be seen or heard → search terms → judge the
   results. Caps: 4 needs, 2 queries each, 5 candidates each.
2. **Search** (`infrastructure/agent/search.py:220-248`) — SearXNG results are
   typed `image` / `video` / `other`, carrying `img_src`, `iframe_src`,
   `resolution`, `length`, `thumbnail_url`.
3. **Human review** — `GET /api/projects/{id}/media-proposals`, then
   `accept` / `reject` / `ignore` (`app.py:2318-2422`).
4. **Download** (`application/media_acquisition.py::download_media`) —
   content-type check, streamed byte ceiling, three named refusals
   (`UnsupportedMedia`, `MediaMoved`, `MediaTooLarge`). Shared with the
   `fetch_media` agent tool so the two cannot drift.
5. **Store** — blob store (`application/blobs.py`), content-addressed.
6. **Perceive** (`application/perception.py:359`) — produces
   `StoreDerivedText`: a *new text source*, `derived_from` the medium,
   carrying a `locator_map` of char-span → `{"kind":"time","start_s":…}`.

**The product of perception is text, and it is real corpus text.** It chunks,
it quotes, it extracts, it reaches the graph — `TextRecord.derived_from`'s
docstring says so explicitly. This is the one part of the media story that
works end to end.

Capabilities degrade rather than fail: with no `AGENT_VISION_MODEL` a video
still perceives and carries `vision unavailable: frames were not described`
(`perception.py`, measured upstream 2026-08-16).

**Transcriber**: real. `readeverything_adapter.py:40` imports
`RemoteWhisperTranscriber`; `config.py:674` reads `AGENT_TRANSCRIBER_URL`,
`:688` requires `AGENT_TRANSCRIBER_MODEL` alongside it. It transcribes **a
stored blob by digest** (`perception.py:325`: `sha256=handle.record.sha256`) —
never a URL. Bytes must be on disk first. `ffmpeg` *and* `ffprobe` must both be
on PATH (`readeverything_adapter.py:115`).

**Playback works.** `GET /api/projects/{id}/sources/{sid}/content`
(`app.py:1409`) streams the bytes with `Accept-Ranges`, 206 partial content,
416 on a bad range, and 410 — distinct from 404 — when the record is present
and the blob is gone. `DocumentReader.tsx:245-295` renders `<video>`,
`<audio>` or `<img>` against it and seeks to `currentTime`. So the console can
already show a stored medium; it just cannot do it inside a lesson.

## 4. The gap: can page-discovered media reach perception?

**No.** Two reasons, and either alone is sufficient:

- The URL is destroyed at §1 before anything sees it. **Measured.**
- Every entrance to the media path takes a URL from somewhere else: a
  *search* result the curation chain judged, a *human* uploading a file, or
  the `fetch_media` tool at a URL the model chose. **Read.**

The `fetch_media` tool is the closest thing to an escape hatch, and it is
closed by §1: the model would have to know the asset's URL, and the only place
it could have learned it is a page whose `<img>` tags were stripped before the
text reached it. Its realistic sources of media URLs are image/video search
results — which is exactly the curation chain, differently invoked.

## 5. Course authoring: the direct cause

`research_team/application/course_authoring.py`, read in full.

**Measured** — `grep -cniE "image|figure|diagram|media|video|photo|picture|
illustrat|visual"` over that file returns **0**. Not one of the three UbD
prompts, nor the path-overview prompt, nor `COMPONENT_GUIDE`, mentions
anything visual.

`COMPONENT_GUIDE` (`:106-135`) enumerates what the model may write:
`mcq`, `cloze`, `flashcards`, `checklist`, `definition`, `evidence`, `graph`,
`timeline`, `explorer`, `compare`. Ten types. **None carries media.**
`application/components.py:627-1026` is the same ten in the registry.

Stage 3 (`:226`) instructs "at least one resolves against the project
(`definition`, `evidence`, `graph`, `timeline`, `explorer` or `compare`)". A
lesson is prose plus those ten blocks, and that is the entire vocabulary the
model has.

One thing the model *does* have, and is never pointed at: the
`[[src:<id>@<seconds>]]` reference grammar. `REFERENCE_SYNTAX_PROMPT`
(`application/corpus_read.py:36`) is imported into `CORPUS_PROMPT`
(`corpus_tools.py:210`), which an authoring turn carries because it runs with
corpus tools bound. And `list_sources` renders a media row plainly —
`corpus_tools.py:71-73`: `"<id> -- media, <mimetype>, …"`. So the model could
already write a timestamped citation to a stored video, which
`references.ts` expands to a `#/p/<project>/doc/<id>` link into the
DocumentReader that plays it. **Nothing tells it to.**

## 6. Rendering: the sanitiser would delete it anyway

`frontend/src/infrastructure/rendering/markdown.ts:85-116` — `marked` then
`DOMPurify` with an explicit allow-list. `img`, `video`, `audio`, `figure`,
`picture`, `source` are **not** in `ALLOWED_TAGS`. `src`, `alt`, `srcset`,
`controls`, `poster` are **not** in `ALLOWED_ATTR`.

**Measured**, running the same DOMPurify and `marked` versions from
`frontend/node_modules` with this file's exact configuration:

| source | rendered |
|---|---|
| `![The Forum](https://ex.com/f.jpg)` | `<p></p>\n` |
| `<img src="…" alt="The Forum">` | `""` |
| `<video src="/api/…/content" controls></video>` | `<p></p>\n` |
| `<figure><img src="a.jpg"><figcaption>Cap</figcaption></figure>` | `Cap` |

A bare markdown image renders an **empty paragraph** — not a broken image,
not the alt text. It is invisible in exactly the way that would stop anyone
noticing it had been attempted.

`LessonDocument.tsx:103-112` maps the ten component names to widgets. There is
no media widget and nothing that could carry one without a new entry.

## 7. Transcripts for remote video

**Nothing exists.** **Measured** — a repo-wide grep for `youtube`, `yt-dlp`,
`youtube_transcript`, `caption track`, `.vtt`, `webvtt`, `subtitle` outside
`node_modules` returns three hits, all incidental: two SearXNG fixtures in
`tests/infrastructure/test_search.py`, and an `AskView` test matching on a page
subtitle. `pyproject.toml` declares no media-fetching or caption library.

`DocumentReader.tsx:247` states the position in the repository's own words:
"a caption track needs a transcript, and nothing in this build produces one".
That comment is now half-stale — the Whisper transcriber landed — but its
conclusion still holds for *remote* video, because the transcriber takes a
digest, not a URL.

The nearest reachable path today is: search finds a video → judge keeps it →
human accepts → `download_media` pulls the file → perception transcribes it.
That works only for a **direct media URL**. A YouTube watch page is
`text/html` and `download_media` refuses it as `UnsupportedMedia`. **Read.**

---

## Which single link is missing

There is no single link. Ranked by how much each one alone blocks:

1. **Authoring has no media vocabulary.** Ten component types, no prompt
   mention. Even a perfect corpus of images produces the same imageless
   lessons. This alone explains the reported symptom.
2. **Rendering has no media path.** Fix (1) and lessons still render empty
   paragraphs where a picture was meant to be.
3. **Scraping discards media.** Fix (1) and (2) and there is still almost
   nothing in the corpus to show, because the only media that ever enters is
   what a human accepted from a search-and-judge chain.

The order matters: fixing (3) first buys nothing visible, which is how this
would look like it was still broken after real work.

## Options, ranked by payoff against effort

**A. Let images render, and tell the author they exist.** Add `img` to
`ALLOWED_TAGS` and `src`/`alt` to `ALLOWED_ATTR` (with a scheme hook mirroring
the existing anchor hook — `data:` and `javascript:` must not survive, and an
off-origin `src` is a tracking pixel), then name figures in
`learning_plan_prompt`. Smallest change that puts a picture on a page.
Constrained by (3): with today's corpus there is little to point at, so the
honest first target is the `content` route for *accepted* media.

**B. A `media` component type.** One registry entry in `components.py`, one
widget in `LessonDocument.tsx`, one paragraph in `COMPONENT_GUIDE`. Resolves a
`source_id` to `/api/projects/{id}/sources/{sid}/content` — a route that
already streams with range support and already has a player in
`DocumentReader.tsx` to copy. Higher effort than A, and strictly better: it
reuses the sanitiser-free component channel, so no allow-list is loosened, and
it inherits 410 handling and time-seeking for free. **This is the recommended
first move.**

**C. Point the author at `[[src:@seconds]]` for media.** Nearly free — a
sentence in the Stage 3 prompt. Produces a timestamped link into a player
rather than an embed. Worth doing alongside A or B regardless.

**D. Keep images during scraping.** `include_images=True` on
`trafilatura.extract`, then decide what the resulting `![](…)` means: a remote
hotlink (cheap, fragile, leaks the reader's IP to the source host) or a
crawl-and-store into the blob store (a real ingest sub-project, and the only
version that makes an image a first-class source). Note that `alt` and
`figcaption` are worth capturing for *extraction* even if the bytes are never
stored — they are prose about the image, which is what perception spends a
vision model to produce.

**E. Remote video and transcripts.** The largest, and the only one needing a
new dependency. Two separable halves: (i) a caption-track reader, which gets a
transcript with no download and no ffmpeg and is by far the cheaper half; (ii)
an audio download feeding the existing Whisper path, which needs a
site-specific extractor and inherits its licensing and reliability problems.
Do (i) first; it may be enough, since perception's product is text either way.

## Honest notes

- Unlike the co-mention channel, **this machinery is not a port without an
  adapter.** Curation, download, blob store, perception, transcription and
  byte-serving are all constructed in `composition.py` and all have real
  implementations. The failure here is a missing *consumer*, not a missing
  producer.
- I did **not** measure how many media sources a real project actually holds.
  The curation chain is topic-triggered and human-gated, so the count is
  plausibly zero, which would make option B correct and still show nothing
  until media is accepted. That number should be checked against
  `~/.research-team/sessions.db` before B is scheduled.
- The `[[src:]]` grammar has three copies that must agree (this file's §5
  names two of them plus a design doc). Any option touching it should read
  `corpus_read.py:55-69` first.
