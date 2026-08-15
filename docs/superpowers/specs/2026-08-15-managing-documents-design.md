# Managing documents

The Documents tab lists what the corpus holds, lets you read a document in a
drawer, and lets you extract one into the graph. Everything it shows arrived
by way of an agent: `remember`, `remember_page`, or the automatic keep that
runs on `fetch` during an unattended run. A person looking at the tab can
observe the corpus and cannot change it — there is no way to add a document,
correct a wrong title, or remove something that should not be there.

This adds those three. Upload text, edit a document, drop one (with a reason,
because the corpus keeps dropped records rather than deleting them), and put
a dropped one back.

## What was verified before designing this

Four things were read rather than assumed. Each one moved a decision.

**The drop command is already built and has no caller.**
`DropSourceDocument(source_id, reason)` is in `domain/corpus.py`, is decided
and folded, refuses a blank reason, refuses an unknown source, refuses a
double drop, and is exercised by `tests/domain/test_corpus.py` and
`tests/infrastructure/test_corpus_read_model.py`. Nothing in production
issues it. `DocumentRecord.dropped_reason` is already on the wire, already in
`DocumentSummary` on the frontend, and `DocumentBrowser` already styles a
dropped row. So "delete" is wiring, not building — the domain decided this
shape a while ago and nobody connected it.

**`store_source` silently skips a metadata-only edit, and this is the finding
the design turns on.** `RedstringKnowledge._store_document` opens with a
digest check:

```python
digest = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
if corpus.state.by_digest.get(digest) == source.source_id:
    return
```

That is right for its callers — a second `remember` of an unchanged page
should not write a revision that revises nothing — and it is wrong for an
edit. Correcting a title while leaving the text alone is exactly the case the
check discards, and it discards it *quietly*: `store_source` returns None,
the route would answer 200, and the title would be unchanged. There is no
error to surface and no test that would go red, because from the adapter's
point of view nothing happened and nothing was supposed to.

`decide()` has no such check — `StoreSourceDocument` always produces
`CorpusDocumentStored`. So the edit path issues the command against the
`Corpus` repository directly and calls `index` itself, and the upload path
(new bytes, where the check cannot fire) keeps using `store_source` and gets
the length cap, the blank-id refusal and indexing for free. **Two paths into
one aggregate is the cost of this design and it is deliberate**; see Decision
2 for why the alternative is worse.

**A re-store un-drops a document, for free.** `evolve` on
`CorpusDocumentStored` constructs a fresh `DocumentRecord` and never copies
`dropped_reason` forward, so storing over a dropped id clears the exclusion.
That is what makes restore a small slice rather than a new command: it is an
edit that changes nothing, and the fold already does the rest. It was found
by reading `evolve`, not by inference from the command list, and a test
asserts it so a future `evolve` that preserves the field fails loudly rather
than removing a feature nobody remembers is implicit.

**Nothing in this repository uploads a file.** Zero hits for `UploadFile`,
`multipart`, `FormData` or `type="file"` across `research_team/` and
`frontend/src/`. `python-multipart` is not a dependency and `HttpClient`
sets `Content-Type: application/json` on every request it makes. So the
cheapest honest upload is not a file upload at all; see Decision 1.

## Three decisions, and what was rejected

### Decision 1: upload is text, decoded in the browser

The corpus stores `text: str`. It has never held bytes, `CorpusDocumentStored`
has no field for them, and there is no decoder for any binary document format
anywhere in the codebase — `filetype` is a transitive dependency nothing
imports. So a multipart endpoint would accept a PDF, fail to read it, and
have to reject it at the boundary having already spent a new dependency
(`python-multipart`), a new method on `HttpClient`, and a second content type
in a layer that has exactly one.

Instead the browser reads the file with `FileReader.readAsText`, and the
request is the JSON the corpus already speaks. The file picker accepts
`.txt`, `.md`, `.markdown` and `text/*`, and a paste box sits beside it for
text that is not in a file at all — which `SourceRef.uri` already anticipates
("Unset for text the caller typed or pasted").

What this costs, stated plainly: **a PDF cannot be uploaded**, and the person
holding one has to convert it first. That is the same limitation the system
already has by way of `fetch` and `remember`, so this adds no new
incapability; it declines to remove an old one. Binary decoding is a
separate piece of work with its own dependency argument, and doing it here
would double the size of this one. Filed as backlog rather than built.

Rejected: multipart with a text-only guard. It buys nothing over the
`FileReader` path except a larger request pipeline and a new server
dependency, and it puts the "this is not text" refusal on the far side of a
network round-trip, where the person learns about their PDF after uploading
it rather than before.

Rejected: fetching a URL server-side from the upload form. There is already a
tool that does this, the agent is the thing that should decide to use it, and
a form that fetches is a form that can be pointed at a file:// URL or an
internal host.

### Decision 2: writing goes through a new application service, not the web layer

`application/corpus_editing.py` holds `CorpusEditor`, which does the same job
for writing that `CorpusReadPort` does for reading: it is the corpus's write
side in this application's own terms, with no storage vocabulary above it.
Four methods — `store`, `revise`, `drop`, `restore`.

It follows `DocumentExtractor` exactly, and for the reason that module's
docstring gives: a route body has no business assembling a project's
`KnowledgePort` (only `open_graph`'s closure can build one) alongside its
corpus repository. `DocumentExtractor` takes `OpenKnowledge` and
`CorpusReaders` callables; this takes those two plus an
`AggregateRepository[Corpus]`. Naming `eventsource` in the application layer
is allowed by `test_architecture.py` and precedented by `session_service.py`.

This is where the two-paths-into-one-aggregate cost from above is paid, and
paid in one file with a comment explaining it, rather than spread across four
route bodies. `store` (new document) delegates to
`KnowledgePort.store_source`. `revise` and `restore` execute
`StoreSourceDocument` on the repository and then call `KnowledgePort.index`,
because indexing hangs off `_store_document` and a command issued directly
does not pass through it — **an edit that skipped `index` would leave the
chunk corpus quoting text the document no longer contains**, which is the
failure mode `corpus_spans` exists to make impossible.

The alternative considered and rejected was relaxing the digest check in
`_store_document` — adding a `force: bool` to `store_source`. It is fewer
lines and it makes the adapter's most carefully-reasoned guard configurable
by its callers, which turns a property ("the log carries no revision that
revised nothing") into a request parameter. The comment above that check
would have to be rewritten to say "unless someone passes force", and every
future caller gets to decide whether the invariant applies to them.

### Decision 3: a drop stays a drop, and the graph is not touched

Dropping is soft, mandatory-reason, and reversible, because the aggregate
already says so — `dropped_reason` is documented as "the record stays, so the
exclusion stays auditable". The UI matches: a confirm dialog with a required
reason field, mirroring `TopicManagePane`'s justification flow, and a
`Restore` action on a dropped row.

**A drop does not remove the document's chunks, and does not remove anything
it contributed to the graph.** Extraction has already written entities and
edges that no longer know which document proposed them, and the chunk store
is content-addressed with no delete path in use here. So a dropped document
stops being listed and stops being offered for extraction, and a definition
generated last week may still quote it. That is a real gap between what
"delete" looks like and what it does, and it is written into the confirm
dialog's copy rather than left for someone to discover: the dialog says the
document is excluded from the corpus, not that it is erased. Erasing
downstream derivations is its own piece of work — it needs an answer for
"which edges came from this document", which the graph does not currently
record — and is filed as backlog.

## What gets built

### Backend

`application/corpus_editing.py` — new. `CorpusEditor` with:

- `store(project_id, source_id, text, *, uri, title, note, published_at)` —
  refuses a `source_id` the corpus already holds (409; upload is creation, and
  silently superseding somebody's document is not what "upload" means), then
  `store_source`.
- `revise(project_id, source_id, *, text, uri, title, note, published_at)` —
  raises `UnknownDocument` for an id the corpus does not hold. `text` is
  optional; omitted means "keep what is stored", read back through
  `CorpusReadPort.read_document` so a metadata-only edit does not have to
  round-trip the whole document through the browser. Then
  `StoreSourceDocument` + `index`.
- `drop(project_id, source_id, reason)` — `DropSourceDocument`. Lets
  `CommandRejectedError` reach the route, which maps it to 409.
- `restore(project_id, source_id)` — reads the stored text and record, and
  re-stores it unchanged. `UnknownDocument` if absent; refuses a document
  that is not dropped (409), because a restore that silently does nothing is
  indistinguishable from one that worked.

`interfaces/web/app.py` — four routes, placed against the declaration-order
constraint the file already documents (FastAPI matches in declaration order,
so a literal segment registered after `/sources/{source_id}` is unreachable):

- `POST   /api/projects/{project_id}/sources` — create. 201.
- `PATCH  /api/projects/{project_id}/sources/{source_id}` — revise. 200.
- `DELETE /api/projects/{project_id}/sources/{source_id}` — drop; reason in
  the body. 200.
- `POST   /api/projects/{project_id}/sources/{source_id}/restore` — 200.

Of the four, only `/restore` has a literal tail and must therefore be
declared inside the existing literal block, above `/sources/{source_id}`. The
`POST` on the collection has no `{source_id}` to be shadowed by, and the
`PATCH`/`DELETE` are different methods on a path that already exists, so
their position is free. The ordering rule is cited here because getting it
wrong produces a 404 that looks like a missing route rather than a
mis-declared one.
`_require_project` first, then the editor, matching how every other write
route in the file is arranged. All four answer 503 when no corpus is
configured, through the same check `_reader` makes.

`composition.py` — build the editor beside `DocumentExtractor`, from the same
`open_graph` closure and the corpus repository already built at line ~1246,
and pass it to `create_app` as `editor`.

### Frontend

`DocumentRepository` (`application/ports/repositories.ts`) gains `create`,
`revise`, `drop`, `restore`. `HttpDocumentRepository` implements them.
`HttpClient` gains a `patch` method — it has `get`, `post` and `delete` and
this is the fourth, written the same way, with the same zod validation.

`use-documents.ts` gains the four mutations, each invalidating
`queryKeys.documents(project)`, each notifying through the existing toast
helper on success and `errorMessage(error)` on failure — the shape
`use-extraction-queue.ts` already uses.

`DocumentBrowser` gains an "Add document" button in its header and, per row,
Edit and Drop (or Restore, when the row is dropped) beside the existing
Extract. New components in `presentation/research/`:

- `DocumentUpload.tsx` — a dialog: title, optional URI, note, a file picker
  and a text area. Picking a file fills the text area and defaults the title
  from the filename, so what is about to be stored is visible before it is
  stored. `source_id` defaults to the URI when one is given and to a slug of
  the title otherwise, and is editable, because it is the citation key and
  the corpus keys on it.
- `DocumentEditPane.tsx` — the same fields over an existing document.
- Drop reuses `Confirm.tsx` with a required reason field.

## Testing

The gates are the four in `CLAUDE.md`, all of them, plus `npm run
test:browser` if a stylesheet or a measured layout changes — which this is not
expected to, since it adds controls to a browser that already has them.

Backend, in `tests/`:

- `application/test_corpus_editing.py` — the four methods against real
  aggregates. **Including a metadata-only revise, asserting the new title is
  in the read model**, which is the test that would have failed against the
  rejected `store_source` implementation, and which is the whole reason that
  path exists. And a revise asserting `index` was called, since the failure it
  guards against (stale chunks) is invisible to every other assertion.
- `domain/test_corpus.py` — one addition: storing over a dropped id clears
  `dropped_reason`. Restore depends on this and nothing currently pins it.
- `interfaces/test_document_routes.py` — new file, following
  `test_extraction_routes.py`. Status codes, the 503-with-no-corpus case, the
  duplicate-id 409, the blank-reason 409, and the 404 for an unknown source.
- `infrastructure/test_corpus_read_model.py` — one addition: a revise's new
  metadata reaches `corpus_documents`.

Per `CLAUDE.md`'s note on fixtures that seed through the call under test:
**at least one route test must act on a project whose corpus the fixture has
not opened**, since the editor's write path opens the graph and the seeding
helper `_project_with_sources` writes corpus events directly.

Per the read-model rule: this adds no column and changes no projection shape,
so `apply_schema` is not involved. That claim is worth checking rather than
trusting — if a slice finds itself adding a field to `CorpusDocumentRow`, it
must be run against a copy of a real database via
`infrastructure.persistence.local_copy`, and this spec is wrong.

Frontend, faking the `DocumentRepository` port (there is no MSW here):

- `DocumentUpload.test.tsx` — a file drop populates the text area; submit
  calls `create` with what is on screen; a blank `source_id` is refused before
  the request.
- `DocumentEditPane.test.tsx` — a metadata-only save sends no `text` field,
  which is the client half of Decision 2.
- `DocumentBrowser.test.tsx` — additions for the new row actions, including
  that a dropped row offers Restore and not Drop.

## Deliberately not built

- **Binary documents.** No PDF or docx decoding; backlog.
- **Hard delete.** The aggregate has no command for it and the audit trail is
  the point.
- **Purging a dropped document's graph contributions.** Needs provenance the
  graph does not record; backlog, and named in Decision 3.
- **Bulk upload.** One document at a time. The agent paths already handle
  volume; this is for the document a person has in their hand.
- **Versions or diffs.** The log holds every revision and nothing reads it
  back. A history view is a separate feature with its own read model.
