# Research recall: reusing what has already been retrieved

## The gap

`fetch` and `web_search` have no reuse mechanism of any kind. Not a cache, not a
digest check, not a memo. Every call goes to the network, including a call for a
page this project fetched an hour ago and still holds the full text of.

The only thing standing between the agent and a repeated request is prompt text,
in two places:

- `fetch.py` — "Do not fetch a page you have already read this session."
- `knowledge_tools.py` — "check there before searching the web for something the
  project may already have learned."

Both are advisory, and both are scoped to *this session*. That scoping is
backwards. Within a session the model can usually see its own earlier fetch in
context; the case where it cannot is precisely when the earlier fetch has been
elided or compacted away, and the case where reuse would pay most is the second
session in a project, working over sources the first one already retrieved and
stored. The guidance lapses exactly where the persistent corpus would have
carried it.

The corpus is the reuse mechanism this system already has, and it is not wired
to anything that retrieves. `remember` stores a document, `list_sources` and
`read_source` read it back at stable offsets with no network involved. What is
missing is any way to get from a URL to the document already holding it.

**`DocumentRecord.uri` exists and is never filled.** It is declared on
`SourceRef`, carried through `redstring_adapter.py` into `StoreSourceDocument`,
persisted on `SourceDocumentStored`, folded into `DocumentRecord`, projected
into the read model, and rendered by `format_listing` and `format_document`. The
entire path is built. The `remember` tool's signature is `(text, source_id,
note)`, so nothing ever supplies a value, and the one field that would let
anything recognise a page it already has is dead weight in every layer it passes
through.

## What this builds

Four changes, in dependency order. The first is a precondition for the third.

### 1. `remember` records where its text came from

`remember` grows three optional parameters — `uri`, `title`, `published_at` —
and passes them into the `SourceRef` fields that already exist for them.

There is no domain or application change here. The port, the command, the event,
the fold, the read model and the two rendering functions all already handle these
values; only the tool boundary drops them. This is wiring.

`fetch` already returns `url:`, `title:` and `date:` as the first lines of every
successful read, so the prompt can name exactly what to carry across.

This alone does something worth having: `list_sources` starts showing the URL of
every stored page, so the corpus becomes legible as a record of what has been
retrieved. It is not sufficient on its own — it still depends on the model
looking — which is why it is the first of four and not the whole change.

### 2. A recall store

New module: `research_team/infrastructure/agent/recall.py`. In-process, no
persistence, shared by `fetch` and `web_search`. It maps a normalized key to the
text previously served for it, along with what the caller originally asked and
when it was served.

It lives in `infrastructure/agent/` beside its two consumers because it has no
domain meaning. Nothing outside those two tools has a use for it, and nothing
about it needs to survive a restart.

Two properties it must have that a plain dict does not:

**Bounded.** LRU with a fixed capacity. Entries are page bodies of up to 20,000
characters, and the process serving them may be a web server that runs for days.
An unbounded dict here is a leak whose size is set by how much research the
agent does.

**Expiring.** A TTL backstop on every entry. `fetch` gets an explicit override
(see below) but `web_search` does not, so without expiry a stale result set
would be pinned for the lifetime of the process. The TTL is what keeps "this
process has been up for three days" from meaning "these results are three days
old and presented as current."

Neither of these is about correctness of a single call. Both are about the store
being safe to leave running.

### 3. Query normalization, and the line it stops at

Keys are normalized before lookup: Unicode NFKC, casefold, whitespace collapse,
trim.

It stops there. No term reordering, no stopword stripping, no stemming, no
embeddings.

The rule that draws the line: **two requests share an entry only if the instance
would have returned the same results for both.** Case and whitespace clear that
bar — a search instance is insensitive to them, so merging cannot change the
answer. Term order does not clear it: engines rank differently on reordered
terms, so merging `"assessment design backward"` into `"backward design
assessment"` returns results for a question the agent did not ask, while
labelling them as results for the question it did.

That failure is worse than the cost it avoids. A repeated search hits one
SearXNG instance the operator runs themselves — there is no third party to
offend and no block to risk. Trading a correct answer for a saved request
against your own server is a bad trade in both directions.

**A memo hit echoes the request it actually ran.** This is the safety net under
the whole normalization question. If the agent asks X and the response says
"results for Y, searched earlier in this process," the mismatch is visible and
recoverable. Silent merging is what makes over-normalization dangerous; a
labelled merge is at worst a wasted turn.

### 4. `fetch` and `web_search` consult recall

**`fetch` looks in three places, in order: the corpus, then the memo, then the
network.**

The corpus comes first because a corpus hit is the *better* answer and not
merely the cheaper one. It returns with `source_id@start-end` and is therefore
citable, which a live fetch never is — a page read off the wire has no
identifier anything downstream can point at, which is the whole reason
`remember` exists.

**Every hit says it is a hit, and how old it is.** Returning stored text dressed
as a fresh read is the same class of dishonesty as an inference wearing a
citation: the model would reason about a snapshot from three days ago as though
it were current, and nothing in the transcript would show why. A corpus hit
already has a shape for this in `source_id@start-end`; a memo hit says it was
read earlier in this process, and when.

**`fetch(url, refresh=False)`** is the override. Some pages are legitimately
worth re-reading — a changelog, a status page, a document revised between stages
of a long run — and a tool that cannot be asked for a fresh read does not stop
the request, it just makes the agent reach for a cache-busting query parameter,
which arrives at the same server in a form nothing can recognise or count. As a
named parameter it is visible in the event log, so its use can be reviewed. The
prompt says when it is legitimate: the page is expected to have changed, not
"to be sure."

`web_search` consults the memo only. It is project-agnostic and stays in the
base tool set.

## The structural change: how `fetch` reaches the corpus

`fetch` is built once at composition (`composition.py:316`) with no project. The
corpus is per-project and arrives later, through `KnowledgeAttachment`, which
swaps tools onto the executor as `set_tools([*base_tools, *attached])`.

So a corpus-aware `fetch` cannot simply be attached: it would collide by name
with the base one.

**Rejected — a resolver callable.** `build_fetch_tool(corpus=lambda: ...)`
reading a single-slot holder that `open_graph` writes. It is local and needs no
change to shared machinery, and it is wrong: `detach` has no way to clear the
holder, so after a session leaves a project the holder still points at that
project's corpus reader, and the next project-less session's `fetch` reads
another project's sources. That is a cross-project read, which rules it out on
correctness rather than taste.

**Chosen — attached tools shadow base tools of the same name.**
`KnowledgeAttachment.attach` composes its tool list so that an attached tool
replaces a base tool with the same name; `detach` restores the base set exactly,
as it already does.

This touches shared machinery, but it is one rule stated in one place, and it
removes the failure mode the resolver had: there is no holder to clear, so
there is nothing to forget to clear, and `detach` restores the base set exactly
without having to know that a corpus-aware `fetch` was ever composed. The
attachment already knows precisely when a project is live and when it is not —
that is its entire job — so a project-scoped `fetch` existing exactly across
that window is the property it is already built to provide.

What this does not fix is when that window closes. `detach` is correct;
`SessionService.ensure_project_attached` simply does not call it for a session
that belongs to no project — it returns `False` and leaves whatever was
attached in place. So in a front end serving several sessions from one
executor, a project-less session takes its turn still holding the previously
attached project's tools, and its `fetch` reads that project's corpus.
`list_sources` and `read_source` already leak by exactly this path; shadowing
puts `fetch` on the same footing as the tools beside it rather than opening a
new hole. Closing it means teaching `ensure_project_attached` that "no project"
is a state to enter and not merely a case to decline, which changes behaviour
for every attached tool and belongs to its own change.

The base `fetch` keeps working unchanged for sessions with no project: it
consults the memo and the network, and skips the corpus because there isn't one.

## Prompts

`fetch.py`'s "Do not fetch a page you have already read this session" comes out.
The tool enforces it now, and the sentence was describing a rule nothing applied
with a scope that was wrong in both directions.

The `fetch` prompt gains: what a hit looks like, that hits carry an age, when
`refresh=True` is warranted, and that a fetched page worth keeping should go to
`remember` *with its URL*.

The `remember` prompt gains the instruction to carry `url`, `title` and
`published_at` across from what `fetch` returned.

The `web_search` prompt gains: a repeated query in the same process returns the
earlier results, labelled with the query that produced them.

## What this does not do

**No fetch log.** A durable record of every page ever fetched — as opposed to
every page deliberately kept — would give complete coverage across restarts. It
is not built here because it quietly makes fetching permanent, which the current
design deliberately avoids: `remember`'s own prompt says committing "is not free
and not private." A second durable store would need its own retention policy,
its own read model, and its own answer to why it is not the corpus. The memo
covers the failure mode that actually recurs (the same page twice in one
long-running process, after compaction) without any of that.

**No cross-restart memo.** A fetch from a fresh process a day later is a
defensible request, not hammering.

**No semantic search matching.** Section 3 gives the argument.

**No enforcement that a remembered page carries its URL.** The model may still
call `remember` without a `uri`. A check that flags corpus documents lacking one
would fit the check library, and is out of scope here.

## Testing

Unit, no network — consistent with the rest of the suite, which stubs
`httpx.AsyncClient` through the `client=` parameter both builders already take.

- Normalization merges case and whitespace differences; does **not** merge
  reordered terms. This is the boundary from section 3 and is the test that
  matters most.
- LRU evicts at capacity; TTL expires an entry and lets the next call through.
- `fetch` order: corpus hit before memo, memo hit before network, network only
  when neither has it.
- `fetch(refresh=True)` bypasses both and hits the network.
- A hit is labelled as one and carries its age; a corpus hit carries
  `source_id@start-end`.
- A memo hit echoes the request that produced it.
- `KnowledgeAttachment` shadows a base tool by name, and `detach` restores the
  base tool exactly.
- A project-less `fetch` consults the memo and the network and does not fail
  looking for a corpus.
- `remember` passes `uri`, `title` and `published_at` through to the port.
