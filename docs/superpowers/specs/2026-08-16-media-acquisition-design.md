# Media acquisition

The corpus can hold a video and say what is in it. It cannot go and get one.

This is sub-project 3 of four. Sub-project 1 gave media a place to live, 2 made
it legible, 4 will render it where prose is rendered. This one is how media
arrives in the first place — and until now the only answer has been a person
holding a file and uploading it, because `upload_media` is the single entry
point and no agent tool writes media at all.

## What shipped already, and what it revealed

The original scope for this sub-project was one line: "`fetch` meeting a
non-HTML URL, `web_search` returning media results." The second half shipped on
2026-08-15 (`9941239`) and is worth reading before the rest of this document,
because measuring it is what reshaped the first half.

`format_results` had been flattening every result to title/url/snippet. For an
image or a video that discards the thing itself — `url` is the *page* the asset
was found on. An image search returned a list of gallery pages with every
`img_src` dropped, silently, while `categories=images` was already accepted and
already reached the instance. It looked like an instance with poor image
coverage. It was a reader looking at the wrong key, which is the same shape as
the `temporal_expression` finding in `CLAUDE.md`.

Three payloads were captured from a real instance that day — 262 image results,
91 video, 29 general — and they are the evidence base for several decisions
below. The load-bearing ones:

- `template` is set on all 353 media results and is what SearXNG itself
  dispatches on. Key-presence sniffing is not equivalent: 20 of 262 image
  results carry `iframe_src` as an empty string and `length` as null.
- Every field can be present-and-null. `publishedDate` was null in 262 of 262
  image results, `img_format` in 35, `thumbnail` in 22 of 91 videos,
  `iframe_src` in 1.
- `thumbnail_src` is **absent on 46 of 262 image results**, and `thumbnail` is
  frequently an empty string. Any thumbnail story needs a fallback.
- The instance returns **raw third-party thumbnail URLs**
  (`https://tse1.mm.bing.net/…`), so `image_proxy` is off. See below.

These proportions describe one instance's engine mix on one afternoon, not
SearXNG in general. What generalises is the shape — `template` always set, any
field nullable — not the ratios.

## Why a chain, and not only a tool

The obvious build is a gated `fetch_media` tool: the model finds an asset,
asks, a person approves, bytes land. That is half of this design and it is not
enough on its own, for a reason that is about attention rather than capability.
A model researching a topic is answering a question in prose. It reaches for an
image when an image is the obvious next move, which is rarely — so media would
arrive occasionally and unpredictably, in proportion to how visual the model
happened to feel, not to how visual the subject is.

The chain asks the question the model would not think to ask, deterministically,
at a moment chosen by a person: *what about this topic is better seen or heard
than read?* It is a fixed sequence of small calls, not an agent loop, and that
is the point — each stage has one job, one prompt, and a test.

Both exist. They share the download primitive, so there is one implementation of
"bytes from a URL into the corpus" and two callers.

## Trigger

**On demand, per topic.** Nothing runs automatically. A person asks for media
for a named topic; the chain runs against that topic's question, scope and
findings.

This was chosen over hanging it off `TopicRoundRunner` after every round, which
is where it naturally fits and where it will probably end up. On demand first
because it removes three problems at once and defers none of the value: no
repeat-proposal deduplication (a topic researched five times would be asked five
times), no cost surprise on an unattended run, and no interaction with
`FetchGrant` — the mechanism that exists because an `ask`-floored tool has
nobody to answer it in an autonomous round. When the chain is trusted, moving
the trigger is a change to one call site.

## The chain

`application/media_curation.py`. Three stages, two ports.

```
MediaCurationTextPort:  model_name, generate(prompt) -> str
MediaSearchPort:        search(query, categories) -> tuple[SearchResult, ...]
```

`MediaCurationTextPort` mirrors `OntologyTextPort` exactly — prompt in, text
out, plus the model's name for recording. Deliberately **not**
`with_structured_output`, which appears nowhere in this repository:
`OntologyTextPort`'s docstring gives the reason, which is that anything wider
puts LangChain's vocabulary into a layer `tests/test_architecture.py` keeps
clean, and makes the test fake a mocked chat model rather than six lines.
Parsing happens here, in the application layer, tolerating junk the way
`_members_from` does.

`MediaSearchPort` is why `parse_results` is extracted from `format_results` in
this work. The chain needs `img_src` and `thumbnail_src` as data; the existing
function renders them into a line for a model to read. Consuming that string
would mean re-parsing prose we just built. The extraction was argued for and
deferred when the widening shipped, on the grounds that nothing needed it yet —
this is what needed it.

**Stage 1 — needs.** One call. Given the topic's question, scope and findings:
what would be seen or heard, in what medium, and why it helps. Yields
`MediaNeed`s, recorded before anything is searched.

Recording the need before the search is the one structural decision in the
chain, and it is not free — it is an event and a projection for something that
may never produce a proposal. It buys three things. A need survives a search
that returns nothing, so "we looked for a gradient diagram and found none" is a
fact rather than a silence. It can be re-searched later with different terms
without re-running stage 1. And it is the grouping the review pane needs: a
person approving media should see the reason it was wanted above the thing
itself, which requires the reason to be a durable object rather than a sentence
the model wrote once into a variable.

**Stage 2 — terms.** One call per need, returning queries and the SearXNG
category to run them in. Per need rather than per topic so a query cannot drift
across needs and a bad query costs one need rather than all of them.

**Stage 3 — judge.** Searches run with no model involved. Results pool per need;
one call judges them, returning keep-or-drop and a one-line reason per
candidate. That reason is what the pane shows. It is "serves a purpose" made
inspectable, and it is the only defence against a chain that proposes whatever
the search happened to return.

**Bounds**, as named constants with the reasoning beside them the way
`MAX_SEARCHES_PER_TURN` has it: 4 needs per topic, 2 queries per need, 3
surviving candidates per need. Worst case per invocation is 8 searches and 24
candidates. These are guesses. They are constants so that being wrong is
visible and cheap, rather than unbounded and expensive.

**Parsing rejects rather than raises.** An item missing a required field is
dropped and counted. A stage returning nothing usable yields no needs or no
candidates, which is a legitimate outcome — a topic can genuinely want no
imagery, and a chain that cannot say so would invent something.

## The proposal aggregate

**A new aggregate, `MediaProposals`, keyed per project.** Not rows on `Corpus`.

`CorpusState`'s guards are all preconditions about stored sources: kind flips,
derivedness, transcript repointing, digest supersession. A proposal has no bytes
and satisfies none of them, so folding it in would mean qualifying every
existing guard with "unless this one is a proposal" — eight places to get right
and one place to get wrong. `Corpus` stays the aggregate that holds what
exists.

**Events.**

- `MediaNeedsIdentified` — stage 1's output, with `model_version`.
- `MediaProposed` — one per surviving candidate: the need it answers, the page
  URL, the asset URL, the thumbnail URL, the judge's reason, and the query that
  found it. The query is carried because a proposal nobody can trace back to a
  search is unauditable.
- `MediaProposalAccepted` / `MediaProposalRejected` — the latter with optional
  free text. Optional rather than required: a required reason is a click on
  every rejection, and most rejections are obvious. When someone does type one
  it is the only signal we will ever have for tuning stage 3's prompt.
- `MediaProposalStored` — carries the resulting `source_id`.
- `MediaProposalFailed` — carries why.

**Lifecycle:** `proposed → accepted → stored | failed`, or `proposed →
rejected`. `decide` refuses accepting twice, accepting something already
rejected, and any command naming an unknown proposal.

## The accept path

`POST /api/projects/{id}/media-proposals/{proposal_id}/accept` appends
`MediaProposalAccepted` and answers **202**. Acceptance is a decision, not a
download; the download is what follows.

A worker then: fetches the asset under the existing `MAX_UPLOAD_BYTES` ceiling,
refuses any content-type outside `image/*`, `video/*` and `audio/*`, calls
`CorpusEditor.store_media` with the *page* URL as `uri` so provenance survives,
and lets perception run eagerly on the stored bytes. `MediaProposalStored` lands
when perception finishes. Only then is the source visible to agents through
`list_sources` — a half-perceived video is a source that answers questions
wrongly rather than not at all.

The content-type refusal matters more than it looks. A judged candidate whose
URL turns out to serve an HTML interstitial is a **failure**, not a source; the
alternative is a corpus row whose bytes are a login page and whose transcript is
empty. `MediaProposalFailed` records it and the proposal stays visible rather
than disappearing.

"Pre-warm" in the original framing means exactly this eager perception, and the
word is easy to over-read. Nothing is fetched *speculatively in order to be
ready*: no asset is downloaded, and no perception is paid for, before a person
accepts. Two things do cross the network before then, and neither is the asset —
the searches in stage 2, and the thumbnails the browser loads when the pane
renders. The second is why the `image_proxy` setting below is a prerequisite
rather than a nicety.

## The read model, and the trap

`MediaProposalRow` — project, proposal, topic, need, reason, asset and thumbnail
URLs, state, and the resulting `source_id` or failure message. Registered in
`composition.py` and given `apply_schema` at build time like every other row.

**The trap, named here because this repository has already paid for it once.**
An event no projection handles counts as APPLIED, not rejected —
`eventsource.replay`'s own docstring says so, and `strict=True` has no opinion
about an event nothing subscribed to. If `MediaProposalProjection` is never
constructed, every request answers 200 with an empty pane, nothing raises and
nothing logs. That is precisely how `EntityDefinitionRunner` shipped missing
from `composition.py` with a full green suite behind it.

So the tests assert **a row exists carrying the reason the chain wrote**. Never
that the request succeeded, never that the pane rendered without throwing. An
assertion about the surrounding machinery passes with the projection deleted and
is worthless as a test of it.

The read-model rule applies too: this adds a new table rather than a column, so
`apply_schema`'s widening path is not exercised — but the change must still be
opened against a copy of a real database before it is believed. `local_copy` is
the supported way to make one.

## The pane

Proposals grouped by need, each need showing its sentence from stage 1. Each
card: thumbnail, title, the judge's reason, accept and reject.

An accepted card stays visible in a working state until `MediaProposalStored`
arrives. B94 records the inverse failure already in this codebase — a media row
showing no state at all between a 202 and a terminal frame, for the minutes an
hour of audio takes — and rebuilding it here would be a known defect
reintroduced deliberately.

A stored card links to `DocumentReader`, which already plays video and audio and
renders images against the content route. Nothing new is needed to *view* media;
what was missing was viewing something that is not stored yet.

**Thumbnails.** Measured: the instance returns raw third-party URLs, so
rendering them hotlinks the viewer's browser to Bing and leaks IP and referrer
to whoever indexed the image. This is a different axis from the agent's network
access — "nothing escapes" has always been about the process, and this is the
browser.

The fix is one setting on the instance: `image_proxy: true` in `settings.yml`,
after which SearXNG rewrites `thumbnail_src` to an instance-relative proxied URL
and the browser never talks to a third party. This is a **deployment
prerequisite**, documented in `docs/configuration.md`, not something this code
can enforce. The rejected alternative is a proxy endpoint of our own, which
means our server fetching model-supplied URLs on a browser's behalf — an SSRF
surface added for a feature that does not need one.

When a thumbnail is absent (46 of 262 image results) the card renders a **typed
placeholder**, not the full-size asset. Falling back to `img_src` is correct and
would put a grid of full-resolution images on the page.

## The agent tool

`fetch_media`, sharing the download primitive with the accept path.

Permissions are the existing mechanism, with nothing bespoke:

```python
GATED_TOOLS = (..., FETCH_MEDIA_TOOL, ...)
TOOL_FLOORS = {FETCH_TOOL: "ask", FETCH_MEDIA_TOOL: "ask", ADVANCE_STAGE_TOOL: "ask"}
```

Floored at `ask`, overridable to `auto` by an explicit `set()`, deniable, and
swept up by `relax_all` — it is a hazard, not a stage gate. `TOOL_FLOORS`'s
docstring already states the property this relies on: a floor raises a default
and never lowers it, and an explicit setting wins in both directions.

Two things deliberately kept out of the policy. The byte ceiling is a refusal
about size enforced where the bytes stream, not a permission — so setting
`fetch_media` to `auto` does not also remove the cap. And `relax_all` sweeping
this in is intended, but it is the first tool where "allow all" means megabytes
and a perception pass; that consequence is stated here so it is a decision
rather than an inheritance.

## Testing

- Chain: a fake `MediaCurationTextPort` returning canned text — six lines, per
  `OntologyTextPort`'s reasoning. A parser test per stage over deliberately
  malformed output, since that is the half that meets a real model.
- `decide`: each refusal, asserted as a refusal.
- Accept path: a stored proposal produces a corpus source with the page URL as
  its `uri`; a non-media content-type produces `MediaProposalFailed` and no
  source; an oversized asset produces the same.
- Projection: **a row exists with the reason the chain wrote**, per the trap
  above. At least one test must start from a fixture that has *not* opened the
  project itself — `CLAUDE.md` records six tests that all missed a dropped
  `graphs.open` because every fixture made the call under test.
- Frontend: jsdom for roles, keyboard and rendered text; nothing here is a
  computed style, so `test:browser` is not indicated.

## Slicing

This is larger than one sitting, and the order is chosen so each slice is
independently verifiable rather than so the pieces arrive in dependency order.

1. `parse_results` extracted from `format_results`, behaviour unchanged. Pure
   refactor with the existing tests as the check.
2. The aggregate, its events and `decide`'s refusals. No callers yet.
3. The chain against fake ports, producing proposals into the aggregate.
4. The projection and the routes — the slice where the APPLIED trap bites, so
   the row assertion lands here.
5. The accept path: worker, download, `store_media`, eager perception.
6. The pane.
7. `fetch_media` and its floor.

The tool is last on purpose. It shares the download primitive, so building it
before slice 5 would mean writing that primitive twice or writing it in the
wrong place.

## Out of scope

- **Rendering media where prose is rendered** is sub-project 4 — a finding
  citing 4:12 drawn as a player seeked there, model-emitted markdown embedding a
  source, and the Ask page. That needs a reference syntax serving all three, and
  it is a design question this document must not answer by accident. The
  machinery it will consume already exists: `locators.resolve` maps a character
  span to `TimeSpan`s and is currently called by nothing outside tests.
- **Automatic triggering** — see Trigger above.
- **Audio search.** `format_results` handles `images.html` and `videos.html`;
  other templates fall through to the unchanged three-line rendering, which is
  correct but means an audio-only result would drop its asset the way images
  did. No music payload was captured. Minor, and deferred deliberately.
- **Deduplication across topics.** Two topics wanting the same image get two
  proposals. On-demand triggering makes this rare enough to leave.
