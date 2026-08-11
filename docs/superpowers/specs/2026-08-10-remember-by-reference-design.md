# Remembering a page by reference

## The gap

`remember` takes its document by value. The tool's signature is
`remember(text, source_id, note, uri, title, published_at)`
(`knowledge_tools.py:91-97`), so committing a page the agent has just read
means re-emitting the page — and copying back the three citation lines `fetch`
printed above it.

**Every one of those arguments is something `fetch` already held and threw
away.** The prompt asks for them in prose, twice: `KNOWLEDGE_PROMPT` asks the
model to "pass substantial content you have actually read rather than your own
summary of it" (`knowledge_tools.py:152-155`), and `FETCH_CORPUS_PROMPT` asks
it to pass the `url:`, `title:` and `date:` lines across
(`fetch.py:278-285`). A prompt that has to ask for a behaviour is describing a
missing affordance, not a disobedient model. Three consequences follow, and
each is visible in the code as it stands.

**The context budget silently became the storage budget.** `MAX_CHARS = 20_000`
is documented as what reaches the model — "short of the point where one page
crowds out the conversation it was fetched to inform" (`fetch.py:41-44`). The
corpus accepts `MAX_DOCUMENT_CHARS = 200_000` (`redstring_adapter.py:61`).
Because the document can only arrive through the model's own output, the
corpus can never hold more of a fetched page than one turn could afford to
look at, and the `[truncated -- the page continues beyond what was read]`
marker (`fetch.py:52`) is stored as though it were part of the document.

**Provenance travels by transcription.** `uri` is what lets a later session
recognise a page it already holds — `stored_page` matches on it
(`fetch.py:144-152`) and `test_a_document_stored_without_a_uri_never_matches`
pins the consequence of losing it. A field that must survive a copy through a
language model will not always survive it.

**`fetched_at` has never been populated on this path.** The field exists on
`SourceDocumentStored` (`domain/corpus.py:53-70`), and `remember` has no
argument that could fill it, so it is always `None`. **The event schema is
already shaped around a piece of provenance that only `fetch` holds and that a
by-value tool has no way to carry.**

The reasoning for closing this is not new. `2026-08-06-research-recall-design.md:113-121`
states it: a corpus hit "returns with `source_id@start-end` and is therefore
citable, which a live fetch never is — a page read off the wire has no
identifier anything downstream can point at, which is the whole reason
`remember` exists." That spec then declined to enforce it, listing "No
enforcement that a remembered page carries its URL" among its non-goals
(`:220-222`). This closes the hole that entry left open and labelled.

## What this builds

A second ingest path, `remember_page(url, source_id, note)`, that resolves the
document and all of its provenance from the memo `fetch` already keeps.
`remember` is unchanged and stays. **The model's contribution becomes judgment
— whether to commit, and why — never transcription.**

## 1. The handle is a URL, not a new identifier

`remember_page` takes the URL. It resolves by `url_key(url)`
(`recall.py:118-120`), which is how `fetch` already finds a memoised page
(`fetch.py:205`).

**Rejected — a synthetic handle id returned by `fetch`.** A fresh id per fetch
(`doc:7f3a…`) reads as tidier and is not. Page identity is already defined, on
the read side, by `normalize_url`: it is what `stored_page` matches on
(`fetch.py:144-152`) and what the memo keys on. A second identity scheme could
disagree with the first, and the disagreement would surface as a page stored
twice under different ids with no way to tell they were the same — the exact
failure `by_digest` exists to catch after the fact (`corpus.py:140-145`).

**Chosen — the URL, normalised the one existing way.** A handle and a corpus
hit then agree about what "the same page" means by construction rather than by
maintenance. `normalize_url` is already total against malformed input
(`recall.py:96-97`), which it must be, because it already runs against
model-written corpus `uri` values on every fetch.

## 2. A second memo retains the page as a record, not as a string

`Recall` is not extended to carry provenance. It is shared with `web_search`
(`composition.py:497-502`), whose entries are flattened result blocks with no
`uri`, `title` or fetch time to carry, and whose value type is a string by
contract. Widening it would put four always-absent fields on every search
entry.

**Rejected — parsing the citation header back out of the memoised string.**
The memo already holds the headed text, so `remember_page` could re-read the
`url:` / `title:` / `date:` lines `_citation` wrote (`fetch.py:98-118`). This
is transcription with the model removed rather than transcription removed: it
re-derives by parsing what was structured a moment earlier, and it breaks the
first time a page's own prose begins with something shaped like a header.

**Chosen — `PageMemo`, a second store in `recall.py`, holding a record.**
`RetainedPage` carries `text` (the untruncated extraction), `uri`, `title`,
`published_at` and `fetched_at`. `fetch` writes it alongside the `Recall`
entry, keyed identically by `url_key`. `Recall` continues to hold exactly what
the model saw, so every existing recall behaviour and test is untouched.

The cost is a second LRU with the same capacity and TTL discipline, which is
duplication of a small amount of eviction logic. It buys a typed value and
leaves `Recall` serving two tools with one contract, which is the trade this
takes.

`fetched_at` is stored as a wall-clock timestamp at write time. It cannot be
derived later from `Recalled.age_seconds`, because `Recall`'s clock is
`time.monotonic` (`recall.py:174`) and has no zero to convert against — which
is the reason this field lives on the record rather than being computed at
ingest.

`MAX_CHARS` stops being the storage ceiling and returns to being what its
docstring already claims it is: a context budget. The model still sees 20,000
characters.

The invariant this must not break is stated at `composition.py:491-495`: these
stores are process-wide, holding "only responses from public URLs, which are
the same bytes whoever asked. Nothing project-scoped may ever go in it."
**Full page text is still public bytes, so the invariant holds** — but it is
now load-bearing in a second place, and `PageMemo` says so in its docstring,
because a future change that put anything project-derived into it would turn a
shared cache into a cross-project read.

Cost, stated rather than reasoned about: `PageMemo` holds `CAPACITY = 128`
entries, whole pages rather than truncated ones, each bounded by
`MAX_BYTES = 2_000_000` (`fetch.py:37`). The worst case is far larger than the
working case. This is not measured here. If it proves real, `PageMemo`'s
capacity is the dial, and lowering it costs redundant fetches rather than
correctness.

## 3. An unresolved handle degrades in band, per call

`PageMemo` is process-scoped, with the same `TTL_SECONDS = 3600.0` and LRU
eviction `Recall` uses (`recall.py:39-44`). A URL fetched in an earlier
process, or an hour ago, or evicted under pressure, does not resolve. This is
expected operation, not an error condition.

`remember_page` returns a notice naming the URL and saying to `fetch` it
first. It does not fall back to storing nothing, and it does not raise.

This is `prompt_ref`'s decision (#91) adopted unchanged, and for its reason:
silent fallback was rejected there because "an empty prompt is
indistinguishable from the system before prompts existed." A `remember_page`
that quietly stored nothing would be indistinguishable from one that worked,
and the corpus would be missing a document nobody was told about. Refusing the
turn is the other rejected option — the model can recover by fetching, and a
tool that raises turns a recoverable miss into a broken turn
(`knowledge_tools.py:3-7`).

## 4. `fetched_at` is populated from the record

`remember_page` fills `fetched_at` from `RetainedPage`. `SourceRef` gains the
field; `remember` leaves it `None`, because a by-value caller genuinely does
not know when the text was read.

**This is the first thing on this path able to fill that field honestly**, and
the reason it is worth doing here rather than later: a `fetched_at` guessed by
the model would be worse than the `None` it replaces.

## 5. `remember` is unchanged

By-value ingest stays, with its signature intact. Not every document comes
from `fetch`: search snippets, text a person supplied, and the agent's own
synthesis all have no URL to resolve, and a design that removed the by-value
path would trade a real capability for symmetry.

**Rejected — making `fetch` return a handle and `remember` accept only
handles.** Conceptually cleaner, and it breaks all three of those cases. It
also rewrites both prompt constants and all six `remember` tests
(`tests/infrastructure/test_knowledge_tools.py`) to buy tidiness.

**Chosen — two paths, with the by-reference one preferred in the prompt.**
`KNOWLEDGE_PROMPT` and `FETCH_CORPUS_PROMPT` change from asking the model to
carry text and citation lines across, to naming `remember_page` as what to use
for a fetched page. The sentences those constants currently spend on
transcription instructions are spent instead on the judgment the model is
actually being asked for.

## Ordering

`remember_page` resolves, then delegates to the same `KnowledgePort.ingest`
with a fully populated `SourceRef`. It adds no new storage path, no new event,
and no new projection. Everything downstream of `SourceRef` — the digest, the
supersession rules, consolidation, the extraction event — is untouched.

`remember_page` joins `GATED_TOOLS` alongside `REMEMBER_TOOL`
(`autonomy.py:31-40`). A commit is a commit however the bytes arrived, and a
by-reference path that skipped the gate would be a way around it.

## What this does not do

**No fetch log.** The memo stays process-scoped, TTL'd and evicted. Nothing
becomes durable that is not durable today: the agent's decision to commit
remains the only thing that writes to the corpus. This is
`2026-08-06-research-recall-design.md:204-210`'s non-goal, inherited
deliberately — a durable record of every page ever fetched "quietly makes
fetching permanent, which the current design deliberately avoids." Retaining
more text in an ephemeral memo is not that; retaining it across restarts would
be.

**No enforcement that a remembered page carries its URL.** `remember` can
still be called without one. `remember_page` makes the correct thing easy
rather than compulsory, and the check that would flag corpus documents lacking
a `uri` remains where the recall spec left it (`:220-222`).

**No change to offsets, citations or chunking.** Ingest text stays
byte-identical to what gets chunked, because citations are `source_id` plus
two integers resolved against the stored text (`corpus_spans.py:9-16`), and
text that differed from what was chunked would shift every existing citation
silently.

**No `source_id` derivation.** Nothing validates `source_id` beyond
non-blankness (`redstring_adapter.py:282-283`); the model still invents them,
and two ids for one page remain possible. Deriving an id from the URL is
tempting and is a separate identity question that would double this spec.

**No representation of absence.** A search that finds nothing still leaves no
trace. That is the subject of its own spec, and it is the larger half of the
problem this one exposes.

**Nothing about the truncation ceiling for existing documents.** Pages already
stored at 20,000 characters stay that way. Re-fetching supersedes them
(`corpus.py:26-34`), which is the existing mechanism and needs no new one.

## Testing

- A page in `PageMemo` is remembered without its text being passed.
- The document reaching the port is the untruncated extraction, not the
  20,000-character string the model saw.
- `Recall` still holds the truncated string: a page retained at full length is
  still recalled by `fetch` at 20,000 characters.
- A `web_search` entry is unaffected — the two stores do not share a value
  type, and a URL fetched and the same URL searched still key apart
  (`recall.py:103-120`).
- The stored text carries no `[truncated]` marker.
- `uri`, `title` and `published_at` reach the `SourceRef` from the memo, not
  from arguments.
- `fetched_at` is populated by `remember_page` and left `None` by `remember`.
- A URL absent from the memo returns the notice, names the URL, and stores
  nothing.
- An expired entry behaves as an absent one.
- `remember`'s existing behaviour is unchanged: all six existing tests pass
  untouched.
- A page remembered by reference is afterwards found by `stored_page`, so the
  next `fetch` of that URL is a corpus hit.
- `remember_page` is gated.
- Nothing project-scoped enters the memo: a corpus hit is not written back to
  it.
