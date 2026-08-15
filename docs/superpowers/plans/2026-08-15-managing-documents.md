# Managing documents implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person upload, edit, drop and restore documents from the
project view's Documents tab, which today can only read and extract them.

**Architecture:** A new application service, `CorpusEditor`, is the corpus's
write side, mirroring how `CorpusReadPort` is its read side and how
`DocumentExtractor` is assembled. Four routes in `interfaces/web/app.py` call
it. The frontend gains four repository methods and three components, with the
per-document actions living in the reader drawer rather than on the
virtualized row.

**Tech Stack:** Python 3.12 / FastAPI / eventsource / pytest; React 19 /
TypeScript / zod / TanStack Query v5 / Tailwind v4 / Vitest.

**Spec:** `docs/superpowers/specs/2026-08-15-managing-documents-design.md`

## Global Constraints

- **Four gates, all of them, and passing three is not passing:**
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`,
  `cd frontend && npm run verify`. The two ruff commands run over the whole
  repository, including tests.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously
  with a coverage temp-file error that names nothing about the real cause.
- **Do not use `store_source` for an edit.**
  `RedstringKnowledge._store_document` returns early when the sha256 of the
  text matches what that `source_id` already holds, so a metadata-only edit
  through it is a silent no-op. Edits execute `StoreSourceDocument` on the
  `Corpus` repository directly and then call `KnowledgePort.index` themselves.
- **Anything writing `StoreSourceDocument` directly must call `index` after
  it.** Indexing normally hangs off `_store_document`; a command issued
  directly bypasses it, and the chunk corpus would keep quoting text the
  document no longer contains.
- **New literal route segments go above `/sources/{source_id}`** in
  `app.py`. FastAPI matches in declaration order; a literal registered after
  the parameterized route is unreachable and answers a 404 that looks like a
  missing route.
- **Comments explain why, not what.** State costs and trade-offs, name what a
  test would fail on, and say when something was measured rather than
  reasoned. Commit messages carry what was considered and rejected. If a test
  would pass with the change reverted, say so in its docstring.
- The corpus is pre-release; **no backwards compatibility is owed** to stored
  data, events or HTTP contracts.
- Existing names used throughout, verbatim: `SourceRef(source_id, text, note,
  uri, title, published_at, fetched_at)`; `StoreSourceDocument(corpus_id,
  source_id, text, uri, title, published_at, note, fetched_at)`;
  `DropSourceDocument(source_id, reason)`; `CorpusReadPort.list_documents(
  include_dropped=False)` / `.read_document(source_id)`; `StoredDocument(
  record, text)`; `DocumentListing(record, extracted)`; `DocumentRecord(
  source_id, sha256, char_count, uri, title, published_at, note,
  dropped_reason)`.

## File structure

**Backend**

| File | Responsibility |
|---|---|
| `research_team/application/corpus_editing.py` (create) | `CorpusEditor`: store, revise, drop, restore. The only place the two-write-paths cost is paid. |
| `research_team/interfaces/web/app.py` (modify) | Four routes, thin, calling the editor. |
| `research_team/composition.py` (modify) | Build the editor, pass it to `create_app`. |
| `research_team/domain/corpus.py` (unmodified) | Already has both commands. Only its tests grow. |

**Frontend**

| File | Responsibility |
|---|---|
| `frontend/src/infrastructure/http/http-client.ts` (modify) | Add `patch`. |
| `frontend/src/application/ports/repositories.ts` (modify) | Four methods on `DocumentRepository`, plus `DocumentDraft` / `DocumentEdit`. |
| `frontend/src/infrastructure/http/document-repository.ts` (modify) | Their HTTP implementation. |
| `frontend/src/application/research/use-document-writes.ts` (create) | The four mutations. Sits beside `use-extraction-queue.ts`, the file it is modelled on. |
| `frontend/src/presentation/research/DocumentUpload.tsx` (create) | The add dialog. |
| `frontend/src/presentation/research/DocumentEditForm.tsx` (create) | The edit form. |
| `frontend/src/presentation/research/DocumentDropDialog.tsx` (create) | Drop, with its required reason. |
| `frontend/src/presentation/research/DocumentManagePane.tsx` (create) | The drawer body: action bar over the reader, or the edit form. |
| `frontend/src/presentation/research/DocumentList.tsx` (modify) | Renders the manage pane and the upload dialog. |
| `frontend/src/presentation/research/DocumentBrowser.tsx` (modify) | One "Add document" button. |
| `frontend/src/presentation/research/use-documents.ts` (modify) | Expose `onAdd` and the upload dialog's open state. |

---

### Task 1: `CorpusEditor.store` and `.drop`

The two methods that need no read-back. `store` is the upload path and goes
through `KnowledgePort.store_source`; `drop` issues the command that has been
sitting uncalled since the aggregate landed.

**Files:**
- Create: `research_team/application/corpus_editing.py`
- Test: `tests/application/test_corpus_editing.py`

**Interfaces:**
- Consumes: `KnowledgePort` (`store_source`, `index`), `CorpusReadPort`
  (`list_documents`, `read_document`), `AggregateRepository[Corpus]`,
  `OpenKnowledge` and `CorpusReaders` from
  `research_team/application/document_extraction.py`.
- Produces:
  - `class DocumentExists(Exception)`
  - `class NotDropped(Exception)`
  - `CorpusEditor(open_knowledge: OpenKnowledge, readers: CorpusReaders, corpus: AggregateRepository[Corpus])`
  - `async store(project_id: UUID, source_id: str, text: str, *, uri: str | None = None, title: str | None = None, note: str | None = None, published_at: str | None = None) -> None`
  - `async drop(project_id: UUID, source_id: str, reason: str) -> None`
  - Task 2 adds `revise` and `restore` to the same class.
  - `UnknownDocument` is imported from `document_extraction.py`, not
    redefined.

- [ ] **Step 1: Read the two collaborators before writing anything**

Read `research_team/application/document_extraction.py` in full (about 120
lines). It is the template: same two callables, same construction story, same
`UnknownDocument`. Read `research_team/domain/corpus.py`'s `decide` to see
which refusals are already the aggregate's and must not be duplicated here
(blank reason, unknown source, double drop).

- [ ] **Step 2: Write the failing tests**

Create `tests/application/test_corpus_editing.py`. The fixtures follow
`tests/application/test_document_extraction.py` — read it for the fake
`KnowledgePort` shape and copy it rather than inventing a second one.

```python
"""The corpus's write side, driven the way the routes will drive it."""

import pytest
from eventsource.errors import CommandRejectedError

from research_team.application.corpus_editing import (
    CorpusEditor,
    DocumentExists,
)
from research_team.application.document_extraction import UnknownDocument


@pytest.mark.asyncio
async def test_store_puts_the_text_in_the_corpus(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")

    listing = await reader.list_documents()
    assert [row.record.source_id for row in listing] == ["s1"]
    assert listing[0].record.title == "Hello"


@pytest.mark.asyncio
async def test_store_refuses_an_id_the_corpus_already_holds(editor, project_id):
    """Upload is creation. Superseding somebody's document silently is not
    what the word means, and the aggregate would allow it -- `decide` treats
    a repeat `source_id` as a revision -- so the refusal has to be here."""
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(DocumentExists):
        await editor.store(project_id, "s1", "different")


@pytest.mark.asyncio
async def test_drop_excludes_the_document_and_keeps_the_record(
    editor, reader, project_id
):
    await editor.store(project_id, "s1", "hello")

    await editor.drop(project_id, "s1", "off topic")

    listing = await reader.list_documents(include_dropped=True)
    assert listing[0].record.dropped_reason == "off topic"
    assert await reader.list_documents() == []


@pytest.mark.asyncio
async def test_drop_refuses_a_blank_reason(editor, project_id):
    """The refusal is the aggregate's, not this service's. Asserted here so
    that a future editor that validates ahead of the command -- and drifts
    from it -- fails rather than merely duplicating it."""
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(CommandRejectedError):
        await editor.drop(project_id, "s1", "   ")


@pytest.mark.asyncio
async def test_drop_refuses_a_source_the_corpus_does_not_hold(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(CommandRejectedError):
        await editor.drop(project_id, "missing", "off topic")


@pytest.mark.asyncio
async def test_drop_on_an_empty_corpus_is_unknown_not_rejected(editor, project_id):
    """A corpus with no documents has no stream, and `decide` answers "corpus
    is empty" for every command but a store. The route needs a 404 there, not
    a 409, so the editor turns that one case into `UnknownDocument`."""
    with pytest.raises(UnknownDocument):
        await editor.drop(project_id, "s1", "off topic")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/application/test_corpus_editing.py -v`
Expected: FAIL, collection error — `No module named
'research_team.application.corpus_editing'`.

- [ ] **Step 4: Write `corpus_editing.py`**

The module docstring carries the reasoning; it is the point of the file.

```python
"""Changing the corpus, in this application's own terms.

`corpus_read.py` is the corpus's read side; this is its write side, and the
same argument shapes both -- a narrow port above, no storage vocabulary, the
project supplied by the instance rather than by the caller.

A service rather than four route bodies for `DocumentExtractor`'s reason: the
web layer has no business assembling a project's `KnowledgePort` (only
`open_graph`'s closure builds one) alongside its corpus repository. It is also
where the awkward part of this feature is paid, in one place with a comment on
it rather than spread across the routes:

**Two paths reach one aggregate, deliberately.** `store` goes through
`KnowledgePort.store_source`, which gives it the length cap, the blank-id
refusal and indexing for free. `revise` and `restore` execute
`StoreSourceDocument` on the repository directly. They have to:
`RedstringKnowledge._store_document` skips a store whose text hashes to what
that `source_id` already holds, which is right for its callers -- a second
`remember` of an unchanged page should not append a revision that revised
nothing -- and silently wrong for an edit. Correcting a title without touching
the text is exactly the case that check discards, and it discards it with no
error: `store_source` returns None and the caller would answer 200 over a
document that did not change. `decide` has no such check.

The cost of taking the direct path is that indexing does not come with it --
`index` hangs off `_store_document`, which is bypassed -- so both methods call
it themselves. An edit that skipped it would leave the chunk corpus quoting
text the document no longer contains, which is the one failure
`corpus_spans.py` exists to make impossible.

The alternative was a `force: bool` on `store_source`. It is fewer lines, and
it turns the adapter's most carefully-reasoned guard into a request parameter
every future caller opts out of at will.
"""

from uuid import UUID

from eventsource.aggregate import AggregateRepository

from research_team.application.corpus_read import CorpusReadPort
from research_team.application.document_extraction import (
    CorpusReaders,
    OpenKnowledge,
    UnknownDocument,
)
from research_team.application.knowledge import SourceRef
from research_team.domain.corpus import Corpus, DropSourceDocument


class DocumentExists(Exception):
    """The corpus already holds this `source_id`.

    Its own type because the route answers 409 for it and 404 for
    `UnknownDocument`, and "the id is taken" and "the id is unknown" are the
    two halves of the same question asked by different callers.
    """


class NotDropped(Exception):
    """A restore was asked for a document that is not excluded.

    Refused rather than treated as a no-op: a restore that silently does
    nothing is indistinguishable, from the far side of the network, from one
    that worked.
    """


class CorpusEditor:
    """Upload, revise, drop and restore one project's documents."""

    def __init__(
        self,
        open_knowledge: OpenKnowledge,
        readers: CorpusReaders,
        corpus: AggregateRepository[Corpus],
    ) -> None:
        self._open_knowledge = open_knowledge
        self._readers = readers
        self._corpus = corpus

    async def store(
        self,
        project_id: UUID,
        source_id: str,
        text: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Add a document nobody has stored under this id.

        The existence check is this service's and not the aggregate's, because
        the aggregate is right to allow a repeat `source_id` -- that is what a
        revision is. Only *upload* means creation, and only upload can say so.
        """
        reader = self._readers(project_id)
        if await self._record(reader, source_id) is not None:
            raise DocumentExists(f"the corpus already holds {source_id!r}")
        knowledge = await self._open_knowledge(project_id)
        await knowledge.store_source(
            SourceRef(
                source_id=source_id,
                text=text,
                uri=uri,
                title=title,
                note=note,
                published_at=published_at,
            )
        )

    async def drop(self, project_id: UUID, source_id: str, reason: str) -> None:
        """Exclude a document, keeping its record and its text.

        The blank reason, the unknown source and the double drop are all the
        aggregate's refusals and are left to it, so there is one implementation
        of each rule. The one case translated here is an empty corpus, which
        `decide` reports as "corpus is empty" -- true, and not what a caller
        asking about one document needs to hear.
        """
        reader = self._readers(project_id)
        if await self._record(reader, source_id) is None:
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(DropSourceDocument(source_id=source_id, reason=reason))
        await self._corpus.save(corpus)

    @staticmethod
    async def _record(reader: CorpusReadPort, source_id: str):
        """This document's record, dropped ones included, or None.

        Listed rather than read: `read_document` fetches the text, and every
        caller here wants to know only whether the id exists.
        """
        for listing in await reader.list_documents(include_dropped=True):
            if listing.record.source_id == source_id:
                return listing.record
        return None
```

**Check `AggregateRepository`'s real method names before running.** Read how
`DocumentExtractor` or `session_service.py` loads and saves an aggregate and
match it exactly — if the repository saves inside `execute`, or the loader is
`load` rather than `load_or_create`, use what the codebase uses and delete the
call that does not exist. `redstring_adapter.py:645` shows the corpus being
loaded with `load_or_create(self._project_id)`; find its matching save.

- [ ] **Step 5: Add the fixtures the tests need**

In the same test file, above the tests. Model them on
`tests/application/test_document_extraction.py`; if that file already has a
fake knowledge port that fits, import it rather than writing a second.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/application/test_corpus_editing.py -v`
Expected: 6 passed.

- [ ] **Step 7: Run the Python gates**

Run: `uv run ruff check . && uv run ruff format . && uv run pytest tests/application tests/domain -q`
Expected: all pass. `ruff format` (not `--check`) so it fixes rather than
reports; the gate is `--check` and CI runs it repo-wide.

- [ ] **Step 8: Commit**

```bash
git add research_team/application/corpus_editing.py tests/application/test_corpus_editing.py
git commit -m "Give the corpus a write side: store and drop

DropSourceDocument has been decided, folded and tested since the corpus
aggregate landed and has never had a production caller. This is that caller,
and the upload path beside it.

The existence check on store is this service's rather than the aggregate's:
decide is right to treat a repeat source_id as a revision, and only upload
means creation. The empty-corpus case is translated to UnknownDocument because
'corpus is empty' is true and is not what a caller asking about one document
needs to hear."
```

---

### Task 2: `CorpusEditor.revise` and `.restore`

The two methods that take the direct command path, and the ones the whole
design turns on.

**Files:**
- Modify: `research_team/application/corpus_editing.py`
- Modify: `tests/application/test_corpus_editing.py`
- Modify: `tests/domain/test_corpus.py`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces:
  - `async revise(project_id: UUID, source_id: str, *, text: str | None = None, uri: str | None = None, title: str | None = None, note: str | None = None, published_at: str | None = None) -> None`
  - `async restore(project_id: UUID, source_id: str) -> None`

- [ ] **Step 1: Write the failing domain test**

Restore depends on a property of `evolve` that nothing currently pins. Add to
`tests/domain/test_corpus.py`:

```python
def test_storing_over_a_dropped_document_clears_its_exclusion():
    """A re-store un-drops, and restore is built entirely on this.

    `evolve` builds a fresh `DocumentRecord` on `CorpusDocumentStored` and
    never copies `dropped_reason` forward. That is implicit in the code and
    load-bearing for `CorpusEditor.restore`, so it is pinned here: an `evolve`
    that starts preserving the field would otherwise remove a feature with no
    test going red.
    """
    corpus = Corpus()
    corpus.execute(
        StoreSourceDocument(corpus_id=CORPUS_ID, source_id="s1", text="hello")
    )
    corpus.execute(DropSourceDocument(source_id="s1", reason="off topic"))

    corpus.execute(
        StoreSourceDocument(corpus_id=CORPUS_ID, source_id="s1", text="hello")
    )

    assert corpus.state.documents["s1"].dropped_reason is None
```

Match the file's existing style for building a `Corpus` and its `CORPUS_ID`
constant — read the top of `tests/domain/test_corpus.py` and use what is
there rather than the names above if they differ.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/domain/test_corpus.py -k dropped -v`
Expected: PASS immediately. This one is a characterization test, not a
red-then-green one — it pins behaviour that already exists. Say so in the
docstring, which the code above does.

- [ ] **Step 3: Write the failing service tests**

Add to `tests/application/test_corpus_editing.py`:

```python
@pytest.mark.asyncio
async def test_a_metadata_only_revise_changes_the_title(editor, reader, project_id):
    """The test the design exists for.

    Against an implementation that routed edits through
    `KnowledgePort.store_source`, this fails: `_store_document` returns early
    when the text hashes to what the id already holds, so the title never
    moves and nothing raises. Reverting `revise` to `store_source` is the way
    to see it go red.
    """
    await editor.store(project_id, "s1", "hello", title="Typo")

    await editor.revise(project_id, "s1", title="Fixed")

    listing = await reader.list_documents()
    assert listing[0].record.title == "Fixed"
    assert (await reader.read_document("s1")).text == "hello"


@pytest.mark.asyncio
async def test_a_revise_reindexes(editor, knowledge, project_id):
    """Indexing rides on `_store_document`, which the direct command path
    bypasses. Nothing else here would notice: the corpus is correct either
    way, and the damage is the chunk store quoting text the document no longer
    contains -- invisible until a citation is checked."""
    await editor.store(project_id, "s1", "hello")
    knowledge.indexed.clear()

    await editor.revise(project_id, "s1", text="goodbye")

    assert [source.source_id for source in knowledge.indexed] == ["s1"]


@pytest.mark.asyncio
async def test_a_revise_keeps_the_text_when_none_is_given(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")

    await editor.revise(project_id, "s1", note="checked")

    stored = await reader.read_document("s1")
    assert stored.text == "hello"
    assert stored.record.note == "checked"


@pytest.mark.asyncio
async def test_revise_refuses_an_unknown_source(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(UnknownDocument):
        await editor.revise(project_id, "missing", title="x")


@pytest.mark.asyncio
async def test_restore_puts_a_dropped_document_back(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")
    await editor.drop(project_id, "s1", "off topic")

    await editor.restore(project_id, "s1")

    listing = await reader.list_documents()
    assert [row.record.source_id for row in listing] == ["s1"]
    assert listing[0].record.title == "Hello"
    assert listing[0].record.dropped_reason is None


@pytest.mark.asyncio
async def test_restore_refuses_a_document_that_is_not_dropped(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(NotDropped):
        await editor.restore(project_id, "s1")
```

The `knowledge` fixture must record what `index` was called with; extend the
fake from Task 1 with an `indexed: list[SourceRef]` if it does not already
have one.

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/application/test_corpus_editing.py -v`
Expected: 6 failures, `AttributeError: 'CorpusEditor' object has no attribute
'revise'` and `... 'restore'`.

- [ ] **Step 5: Implement both methods**

```python
    async def revise(
        self,
        project_id: UUID,
        source_id: str,
        *,
        text: str | None = None,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Change a stored document's metadata, its text, or both.

        Not through `store_source`. See the module docstring: that path drops
        a store whose text is unchanged, which is most edits.

        `text=None` means "keep what is stored" and is read back from the
        corpus rather than required from the caller. A browser correcting a
        title should not have to round-trip a hundred kilobytes of prose to
        do it, and a caller that had to send the text back is a caller that
        can send back a stale copy of it.
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id)
        if stored is None:
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        await self._store(
            project_id,
            SourceRef(
                source_id=source_id,
                text=stored.text if text is None else text,
                uri=stored.record.uri if uri is None else uri,
                title=stored.record.title if title is None else title,
                note=stored.record.note if note is None else note,
                published_at=(
                    stored.record.published_at if published_at is None else published_at
                ),
            ),
        )

    async def restore(self, project_id: UUID, source_id: str) -> None:
        """Put a dropped document back, unchanged.

        A re-store of the same bytes, which the fold turns into a restore for
        free: `evolve` builds a fresh record on `CorpusDocumentStored` and does
        not carry `dropped_reason` across. Pinned by
        `test_storing_over_a_dropped_document_clears_its_exclusion`, because
        that property is implicit in `evolve` and this is its only caller.
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id)
        if stored is None:
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        if stored.record.dropped_reason is None:
            raise NotDropped(f"{source_id!r} is not dropped")
        await self._store(
            project_id,
            SourceRef(
                source_id=source_id,
                text=stored.text,
                uri=stored.record.uri,
                title=stored.record.title,
                note=stored.record.note,
                published_at=stored.record.published_at,
            ),
        )

    async def _store(self, project_id: UUID, source: SourceRef) -> None:
        """The direct path: command, then index.

        Both halves are required and neither is optional for a caller. The
        index call is the one that has no local evidence -- the corpus is
        correct without it and the chunk store is not -- so it lives here
        rather than at the two call sites, where one of them would eventually
        be written without it.
        """
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreSourceDocument(
                corpus_id=project_id,
                source_id=source.source_id,
                text=source.text,
                uri=source.uri,
                title=source.title,
                published_at=source.published_at,
                note=source.note,
            )
        )
        await self._corpus.save(corpus)
        knowledge = await self._open_knowledge(project_id)
        await knowledge.index(source)
```

Add `StoreSourceDocument` to the module's import from
`research_team.domain.corpus`. Use the same load/save calls Task 1 settled on.

**A note on `read_document` returning `None` for a dropped document.** Check
whether `CorpusReadPort.read_document` filters dropped rows out — if it does,
`restore` can never read the text it needs, and the fix is to read the record
through `list_documents(include_dropped=True)` and the text through whatever
path ignores the flag. Verify by reading
`research_team/infrastructure/persistence/corpus_reader.py` before
implementing; do not assume either way.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/application/test_corpus_editing.py tests/domain/test_corpus.py -v`
Expected: all pass.

- [ ] **Step 7: Prove the key test red**

Temporarily change `revise` to call `knowledge.store_source(...)` instead of
`self._store(...)`. Run
`uv run pytest tests/application/test_corpus_editing.py -k metadata_only -v`.
Expected: FAIL — the title stays `Typo`. **If it passes, the fake knowledge
port does not reproduce `_store_document`'s digest check and the test is
worthless; give the fake that check before continuing.** Then revert.

- [ ] **Step 8: Run the gates and commit**

```bash
uv run ruff check . && uv run ruff format . && uv run pytest -q
git add research_team/application/corpus_editing.py tests/application/test_corpus_editing.py tests/domain/test_corpus.py
git commit -m "Edit and restore a document, off the direct command path

store_source cannot carry an edit. _store_document returns early when the
text hashes to what the id already holds -- correct for its callers, and
exactly the case a metadata-only edit is. It fails silently: no error, and
nothing to assert on from outside. test_a_metadata_only_revise_changes_the_
title is the test that goes red against it, and was proved red before being
trusted green.

The direct path costs the indexing that hangs off _store_document, so _store
does it. An edit that skipped it would leave the chunk corpus quoting text
the document no longer contains.

Restore is a re-store of unchanged bytes: evolve builds a fresh record and
does not carry dropped_reason across. That was implicit and is now pinned in
the domain tests, since restore is its only caller."
```

---

### Task 3: The four routes

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Modify: `research_team/composition.py`
- Test: `tests/interfaces/test_document_routes.py` (create)

**Interfaces:**
- Consumes: `CorpusEditor`, `DocumentExists`, `NotDropped`, `UnknownDocument`.
- Produces: `create_app(..., editor: CorpusEditor | None = None)` and the four
  routes below. Task 4 consumes their wire shapes.

Request and response shapes, exactly:

| Route | Body | Answer |
|---|---|---|
| `POST /api/projects/{project_id}/sources` | `{source_id, text, uri?, title?, note?, published_at?}` | 201, `source_view` of the new row |
| `PATCH /api/projects/{project_id}/sources/{source_id}` | `{text?, uri?, title?, note?, published_at?}` | 200, `source_view` |
| `POST /api/projects/{project_id}/sources/{source_id}/drop` | `{reason}` | 200, `source_view` |
| `POST /api/projects/{project_id}/sources/{source_id}/restore` | `{}` | 200, `source_view` |

Status mapping: `DocumentExists` → 409, `UnknownDocument` → 404, `NotDropped`
→ 409, `CommandRejectedError` → 409, `KnowledgeError` → 400, editor absent or
`corpus is None` → 503.

- [ ] **Step 1: Read the surrounding code**

Read `app.py` around the existing `/sources` routes (roughly lines 700–930):
`_reader`, `_require_project`, and the comment stating the declaration-order
constraint. Read `presenters.py`'s `source_view` and `_record_view`. Note how
another write route maps exceptions to status codes and copy that shape.

- [ ] **Step 2: Write the failing route tests**

Create `tests/interfaces/test_document_routes.py`, modelled on
`tests/interfaces/test_extraction_routes.py` — read it first for the
`app_and_client` fixture and the `_project_with_sources` helper.

```python
"""The four write routes over a project's corpus."""


def test_upload_stores_a_document(app_and_client):
    app, client = app_and_client
    project = _new_project(client)

    response = client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Hello"},
    )

    assert response.status_code == 201
    assert response.json()["source_id"] == "s1"
    listed = client.get(f"/api/projects/{project}/sources").json()
    assert [row["source_id"] for row in listed] == ["s1"]


def test_upload_refuses_an_id_the_corpus_holds(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "other"}
    )

    assert response.status_code == 409


def test_a_patch_changes_the_title_and_leaves_the_text(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources",
        json={"source_id": "s1", "text": "hello", "title": "Typo"},
    )

    response = client.patch(
        f"/api/projects/{project}/sources/s1", json={"title": "Fixed"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Fixed"
    assert client.get(f"/api/projects/{project}/sources/s1").json()["text"] == "hello"


def test_a_patch_on_an_unknown_source_is_404(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = client.patch(
        f"/api/projects/{project}/sources/missing", json={"title": "x"}
    )

    assert response.status_code == 404


def test_drop_excludes_the_document_and_restore_puts_it_back(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    dropped = client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "off topic"}
    )
    assert dropped.status_code == 200
    assert client.get(f"/api/projects/{project}/sources").json() == []

    restored = client.post(f"/api/projects/{project}/sources/s1/restore", json={})
    assert restored.status_code == 200
    assert restored.json()["dropped_reason"] is None
    assert len(client.get(f"/api/projects/{project}/sources").json()) == 1


def test_drop_refuses_a_blank_reason(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = client.post(
        f"/api/projects/{project}/sources/s1/drop", json={"reason": "  "}
    )

    assert response.status_code == 409


def test_restore_refuses_a_document_that_is_not_dropped(app_and_client):
    app, client = app_and_client
    project = _new_project(client)
    client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    response = client.post(f"/api/projects/{project}/sources/s1/restore", json={})

    assert response.status_code == 409


def test_the_routes_answer_503_with_no_corpus_configured(app_without_corpus):
    """`_reader` already answers this for the read routes; the write routes
    have to make the same check rather than failing further in."""
    client, project = app_without_corpus

    response = client.post(
        f"/api/projects/{project}/sources", json={"source_id": "s1", "text": "hello"}
    )

    assert response.status_code == 503
```

**And the fixture-blindness test `CLAUDE.md` requires**, because every test
above seeds through `POST /sources` — the very call whose path opens the
graph:

```python
def test_upload_works_on_a_project_no_earlier_call_has_touched(app_and_client):
    """A second project, seeded by nothing.

    `CLAUDE.md` records the failure this guards: a request path that stopped
    opening the project answered 503 on the first call for a
    newly-touched project and succeeded on every one after, because some
    earlier test in the same process had already opened it. Every other test
    in this file arranges through the route under test and cannot see that.
    """
    app, client = app_and_client
    _new_project(client)  # the project every other assertion would run against
    untouched = _new_project(client)

    response = client.post(
        f"/api/projects/{untouched}/sources",
        json={"source_id": "s1", "text": "hello"},
    )

    assert response.status_code == 201
```

Write `_new_project(client)` as a helper that POSTs `/api/projects` and
returns the id — copy the body shape from `test_web.py`'s existing project
creation rather than guessing at required fields. Write `app_without_corpus`
by building the app with `corpus=None`; if `test_web.py` already has such a
fixture, reuse it.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/interfaces/test_document_routes.py -v`
Expected: FAIL — 405 or 404 on every request; no such routes.

- [ ] **Step 4: Add the routes**

`create_app` gains `editor: CorpusEditor | None = None` at the end of its
parameter list, beside `definitions`. Then, **inside the literal-segment
block, above `/sources/{source_id}`**:

```python
    def _editor() -> CorpusEditor:
        """The corpus's write side, or the same 503 `_reader` answers.

        A project without a corpus read model is a valid thing to serve, so
        this is a refusal rather than a construction failure -- see `_reader`,
        which draws the same line for reading.
        """
        if editor is None:
            raise HTTPException(status_code=503, detail="no corpus is configured")
        return editor

    class NewSource(BaseModel):
        source_id: str
        text: str
        uri: str | None = None
        title: str | None = None
        note: str | None = None
        published_at: str | None = None

    class SourceEdit(BaseModel):
        """Every field optional, and `None` means "leave it alone".

        There is deliberately no way to clear a field back to null through
        this: distinguishing "unset" from "set to null" needs a sentinel, and
        the console has no control that asks for it. A caller that wants an
        empty title sends "".
        """

        text: str | None = None
        uri: str | None = None
        title: str | None = None
        note: str | None = None
        published_at: str | None = None

    class DropReason(BaseModel):
        reason: str

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    async def upload_source(project_id: UUID, body: NewSource):
        """Store a document a person is holding, rather than one an agent found.

        Every other way into this corpus is an agent path -- `remember`,
        `remember_page`, the automatic keep on `fetch` -- and this is the
        first that is not.
        """
        await _require_project(project_id)
        try:
            await _editor().store(
                project_id,
                body.source_id,
                body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except DocumentExists as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KnowledgeError as error:
            # The blank-id refusal and the length cap, both `store_source`'s.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _source_row(project_id, body.source_id)

    @app.post("/api/projects/{project_id}/sources/{source_id}/drop")
    async def drop_source(project_id: UUID, source_id: str, body: DropReason):
        await _require_project(project_id)
        try:
            await _editor().drop(project_id, source_id, body.reason)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CommandRejectedError as error:
            # The blank reason and the double drop, both the aggregate's.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @app.post("/api/projects/{project_id}/sources/{source_id}/restore")
    async def restore_source(project_id: UUID, source_id: str):
        await _require_project(project_id)
        try:
            await _editor().restore(project_id, source_id)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotDropped as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @app.patch("/api/projects/{project_id}/sources/{source_id}")
    async def revise_source(project_id: UUID, source_id: str, body: SourceEdit):
        await _require_project(project_id)
        try:
            await _editor().revise(
                project_id,
                source_id,
                text=body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    async def _source_row(project_id: UUID, source_id: str) -> dict[str, Any]:
        """The written document, read back through the listing.

        Read back rather than composed from the request, so the answer is what
        the corpus holds rather than what the caller sent -- `sha256` and
        `char_count` are computed in the fold and a client that trusted its own
        echo would render a digest nothing verified.
        """
        for listing in await _reader(project_id).list_documents(include_dropped=True):
            if listing.record.source_id == source_id:
                return source_view(listing)
        raise HTTPException(status_code=404, detail=f"no document {source_id!r}")
```

Only `/drop` and `/restore` have literal tails and strictly need to be above
`/sources/{source_id}`; keeping the whole block together is simpler than
remembering which. Add the imports: `CorpusEditor`, `DocumentExists`,
`NotDropped` from `research_team.application.corpus_editing`,
`UnknownDocument` from `...document_extraction` (it may already be imported
for the extraction routes), `CommandRejectedError` from `eventsource.errors`,
and `KnowledgeError` — check which of these `app.py` already has.

- [ ] **Step 5: Wire it in `composition.py`**

Find where `DocumentExtractor` is constructed and build the editor beside it,
from the same `open_graph` closure and corpus reader factory, plus the corpus
repository already built around line 1246. Pass `editor=...` to `create_app`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/interfaces/test_document_routes.py -v`
Expected: 9 passed.

- [ ] **Step 7: Run the whole backend suite**

Run: `uv run ruff check . && uv run ruff format . && uv run pytest -q`
Expected: all pass. `tests/test_architecture.py` in particular — the new
application module imports `eventsource`, which that layer is allowed, and
nothing outward.

- [ ] **Step 8: Commit**

```bash
git add research_team/interfaces/web/app.py research_team/composition.py tests/interfaces/test_document_routes.py
git commit -m "Serve upload, edit, drop and restore over the corpus

Dropping is a POST to /drop rather than a DELETE: the console's HttpClient
sends no body on a DELETE, and a mandatory free-text reason would have gone in
the query string, where it gets logged. It pairs with /restore, which has to
be a POST anyway.

Both literal tails are declared above /sources/{source_id}, which app.py
already documents as a FastAPI declaration-order constraint -- getting it
wrong answers a 404 that reads like a missing route.

Every route reads the written row back through the listing rather than echoing
the request: sha256 and char_count are computed in the fold, and an echo would
render a digest nothing verified.

test_upload_works_on_a_project_no_earlier_call_has_touched is there because
every other test in the file arranges through the route it tests, which
CLAUDE.md records as the shape that cannot see a dropped graph-open."
```

---

### Task 4: The frontend port and its HTTP implementation

**Files:**
- Modify: `frontend/src/infrastructure/http/http-client.ts`
- Modify: `frontend/src/application/ports/repositories.ts`
- Modify: `frontend/src/infrastructure/http/document-repository.ts`
- Test: `frontend/src/infrastructure/http/document-repository.test.ts` (create,
  unless one exists — check first)

**Interfaces:**
- Consumes: Task 3's four routes; `dto.documentDto`,
  `mappers.toDocumentSummary`, `seg`, `HttpClient`.
- Produces, on `DocumentRepository`:
  - `create(projectId: ProjectId, draft: DocumentDraft): Promise<DocumentSummary>`
  - `revise(projectId: ProjectId, sourceId: SourceId, edit: DocumentEdit): Promise<DocumentSummary>`
  - `drop(projectId: ProjectId, sourceId: SourceId, reason: string): Promise<DocumentSummary>`
  - `restore(projectId: ProjectId, sourceId: SourceId): Promise<DocumentSummary>`
  - `interface DocumentDraft { sourceId: string; text: string; uri?: string; title?: string; note?: string; publishedAt?: string }`
  - `interface DocumentEdit { text?: string; uri?: string; title?: string; note?: string; publishedAt?: string }`
- Also produces `HttpClient.patch<S>(path: string, body: unknown, schema: S): Promise<z.output<S>>`.

- [ ] **Step 1: Add `patch` to `HttpClient`**

Directly under `post`, written the same way:

```ts
  patch<S extends z.ZodTypeAny>(path: string, body: unknown, schema: S): Promise<z.output<S>> {
    return this.request('PATCH', path, body ?? {}, schema)
  }
```

- [ ] **Step 2: Write the failing repository tests**

```ts
import { describe, expect, it, vi } from 'vitest'

import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { HttpDocumentRepository } from './document-repository.ts'
import type { HttpClient } from './http-client.ts'

const row = {
  source_id: 's1',
  char_count: 5,
  sha256: 'abc',
  uri: null,
  title: 'Hello',
  published_at: null,
  note: null,
  dropped_reason: null,
  extracted: false,
}

const project = ProjectId('11111111-1111-4111-8111-111111111111')

describe('HttpDocumentRepository writes', () => {
  it('posts a draft to the collection', async () => {
    const post = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    const created = await repository.create(project, { sourceId: 's1', text: 'hello' })

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources`,
      { source_id: 's1', text: 'hello' },
      expect.anything(),
    )
    expect(created.title).toBe('Hello')
  })

  it('omits fields an edit did not set, so the server keeps them', async () => {
    // The client half of the design: a metadata-only edit sends no `text`,
    // and the server reads the stored text back rather than the browser
    // round-tripping the whole document to change a title.
    const patch = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ patch } as unknown as HttpClient)

    await repository.revise(project, SourceId('s1'), { title: 'Fixed' })

    expect(patch).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1`,
      { title: 'Fixed' },
      expect.anything(),
    )
  })

  it('sends the reason on a drop', async () => {
    const post = vi.fn().mockResolvedValue({ ...row, dropped_reason: 'off topic' })
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    const dropped = await repository.drop(project, SourceId('s1'), 'off topic')

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1/drop`,
      { reason: 'off topic' },
      expect.anything(),
    )
    expect(dropped.droppedReason).toBe('off topic')
  })

  it('posts an empty body to restore', async () => {
    const post = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    await repository.restore(project, SourceId('s1'))

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1/restore`,
      {},
      expect.anything(),
    )
  })
})
```

If `ProjectId`/`SourceId` are branded constructors with a different call
shape, use whatever `DocumentList.test.tsx` uses to build them.

- [ ] **Step 3: Run to verify they fail**

Run: `cd frontend && npx vitest run src/infrastructure/http/document-repository.test.ts`
Expected: FAIL — `repository.create is not a function`.

- [ ] **Step 4: Add the port methods**

On `DocumentRepository` in `repositories.ts`, after `cancelExtraction`:

```ts
  /** Store a document a person is holding.
   *
   * Refused by the server when the corpus already holds the id, rather than
   * superseding it: uploading is creating, and quietly replacing somebody
   * else's document is not what the word means. */
  create(projectId: ProjectId, draft: DocumentDraft): Promise<DocumentSummary>
  /** Change a stored document. Every field is optional and an omitted one is
   *  left alone -- in particular `text`, so correcting a title does not
   *  round-trip the prose, and cannot send back a stale copy of it. */
  revise(projectId: ProjectId, sourceId: SourceId, edit: DocumentEdit): Promise<DocumentSummary>
  /** Exclude a document, keeping the record and the reason. The corpus keeps
   *  dropped documents on purpose, so this is reversible -- see `restore`. */
  drop(projectId: ProjectId, sourceId: SourceId, reason: string): Promise<DocumentSummary>
  /** Put a dropped document back. Refused for one that is not dropped, so a
   *  press that did nothing cannot look like one that worked. */
  restore(projectId: ProjectId, sourceId: SourceId): Promise<DocumentSummary>
```

And the two interfaces beside `DocumentRange`:

```ts
export interface DocumentDraft {
  /** The citation key. The corpus keys on it and it cannot be changed
   *  afterwards without orphaning every citation that points at it. */
  sourceId: string
  text: string
  uri?: string
  title?: string
  note?: string
  publishedAt?: string
}

/** An omitted field is left as stored. There is no way to clear one back to
 *  null: telling "unset" from "set to null" needs a sentinel and no control
 *  in the console asks for it. An empty title is sent as "". */
export interface DocumentEdit {
  text?: string
  uri?: string
  title?: string
  note?: string
  publishedAt?: string
}
```

- [ ] **Step 5: Implement them on `HttpDocumentRepository`**

```ts
  async create(projectId: ProjectId, draft: DocumentDraft) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources`,
      // Built key by key rather than by mapping the whole draft, so an
      // undefined field is absent from the JSON instead of present as null --
      // which the server reads as "leave it alone" on the edit route, and the
      // two shapes are deliberately the same one.
      prune({
        source_id: draft.sourceId,
        text: draft.text,
        uri: draft.uri,
        title: draft.title,
        note: draft.note,
        published_at: draft.publishedAt,
      }),
      dto.documentDto,
    )
    return toDocumentSummary(body)
  }

  async revise(projectId: ProjectId, sourceId: SourceId, edit: DocumentEdit) {
    const body = await this.http.patch(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}`,
      prune({
        text: edit.text,
        uri: edit.uri,
        title: edit.title,
        note: edit.note,
        published_at: edit.publishedAt,
      }),
      dto.documentDto,
    )
    return toDocumentSummary(body)
  }

  async drop(projectId: ProjectId, sourceId: SourceId, reason: string) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/drop`,
      { reason },
      dto.documentDto,
    )
    return toDocumentSummary(body)
  }

  async restore(projectId: ProjectId, sourceId: SourceId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/restore`,
      {},
      dto.documentDto,
    )
    return toDocumentSummary(body)
  }
```

With, at the bottom of the file:

```ts
/** Drop the keys whose value is undefined.
 *
 * `JSON.stringify` already omits them, so this changes no request. It is here
 * for the tests, which assert on the object handed to the client rather than
 * on the serialized body, and would otherwise have to spell out every absent
 * field as `undefined` in every expectation.
 */
const prune = (body: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined))
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npx vitest run src/infrastructure/http/document-repository.test.ts`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/infrastructure/http frontend/src/application/ports/repositories.ts
git commit -m "Give the document port its four writes

An edit omits the fields it did not change, text included: correcting a title
should not round-trip the prose, and a client that had to send the text back
is one that can send back a stale copy of it. The server reads the stored text
when none arrives.

DocumentEdit deliberately cannot clear a field to null -- telling 'unset' from
'set to null' needs a sentinel, and no control in the console asks for one."
```

---

### Task 5: The four mutations

**Files:**
- Create: `frontend/src/application/research/use-document-writes.ts`
- Test: `frontend/src/application/research/use-document-writes.test.tsx`

**Interfaces:**
- Consumes: Task 4's port methods; `queryKeys.documents`, `queryKeys.document`,
  `useContainer`, `notify`, `errorMessage`.
- Produces: `useCreateDocument(projectId)`, `useReviseDocument(projectId)`,
  `useDropDocument(projectId)`, `useRestoreDocument(projectId)` — each a
  TanStack `useMutation` result. `useCreateDocument().mutate(draft)`,
  `useReviseDocument().mutate({sourceId, edit})`,
  `useDropDocument().mutate({sourceId, reason})`,
  `useRestoreDocument().mutate(sourceId)`.

- [ ] **Step 1: Read the model**

Read `frontend/src/application/research/use-extraction-queue.ts` — the three
mutations at its foot are the shape to copy, including where invalidation
goes and where it does not.

- [ ] **Step 2: Write the failing test**

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { useReviseDocument } from './use-document-writes.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

describe('useReviseDocument', () => {
  it('invalidates both the listing and the open document', async () => {
    // Two keys, not one. The listing carries the title and the reader carries
    // the text, and an edit can move either -- a reader left on the old key
    // would show the previous text under the new title.
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const documents = { revise: vi.fn().mockResolvedValue({}) }
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ContainerProvider value={{ documents } as never}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </ContainerProvider>
    )

    const { result } = renderHook(() => useReviseDocument(project), { wrapper })
    result.current.mutate({ sourceId: SourceId('s1'), edit: { title: 'Fixed' } })

    await waitFor(() => {
      expect(documents.revise).toHaveBeenCalledWith(project, 's1', { title: 'Fixed' })
    })
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: expect.arrayContaining(['documents']),
      })
    })
  })
})
```

Copy the wrapper shape from an existing hook test —
`DocumentList.test.tsx` shows how `ContainerProvider` is imported and what a
fake container needs. If `queryKeys.documents(project)` is not an array
starting with `'documents'`, assert on `queryKeys.documents(project)` itself
instead of `arrayContaining`.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/application/research/use-document-writes.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Write the hooks**

```ts
/** Writing to the corpus, one mutation per operation.
 *
 * Beside `use-extraction-queue.ts` and shaped like it: `useMutation`,
 * invalidate on success, and no optimistic write. The reason is the same one
 * that file gives -- the server computes `sha256` and `char_count` in the
 * fold, so the row it answers with is not the row a client could have
 * predicted, and writing a guess into the cache would show a digest that is
 * about to change.
 *
 * All four invalidate `queryKeys.documents(projectId)`. `revise` and
 * `restore` also invalidate `queryKeys.document(projectId, sourceId)`,
 * because they can change the *text*, which is what the reader holds -- and a
 * reader left on a stale key shows the old prose under the new title.
 * `drop` cannot: it changes only the record.
 */
export const useReviseDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, edit }: { sourceId: SourceId; edit: DocumentEdit }) =>
      documents.revise(projectId, sourceId, edit),
    onSuccess: async (_row, { sourceId }) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
      await queryClient.invalidateQueries({
        queryKey: queryKeys.document(projectId, sourceId),
      })
    },
  })
}
```

Write the other three the same way: `useCreateDocument` takes a
`DocumentDraft` and invalidates the listing only; `useDropDocument` takes
`{sourceId, reason}` and invalidates the listing only; `useRestoreDocument`
takes a `SourceId` and invalidates both, since a restore re-stores the text.

Toasts stay out of these hooks and go at the call sites, matching
`use-documents.ts`, whose `onExtract` puts `notify` in the component layer
because the wording depends on what the answer said.

- [ ] **Step 5: Run the tests, then the whole frontend suite once**

Run: `cd frontend && npx vitest run src/application/research/use-document-writes.test.tsx`
Expected: PASS. Do not start a second vitest process while this runs.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/application/research/use-document-writes.ts frontend/src/application/research/use-document-writes.test.tsx
git commit -m "Add the four corpus write mutations

No optimistic writes, for use-extraction-queue's reason: sha256 and char_count
are computed in the fold, so the answered row is not one a client could have
predicted.

revise and restore invalidate the open document as well as the listing,
because both can change the text and the reader holds it under its own key. A
drop changes only the record and does not."
```

---

### Task 6: The upload dialog

**Files:**
- Create: `frontend/src/presentation/research/DocumentUpload.tsx`
- Create: `frontend/src/presentation/research/DocumentUpload.test.tsx`

**Interfaces:**
- Consumes: `useCreateDocument`; `Drawer` from `../common/Drawer.tsx`;
  `Button` from `../common/primitives.tsx`; `notify`, `errorMessage`.
- Produces: `DocumentUpload({ projectId, onClose }: { projectId: ProjectId; onClose: () => void })`.

- [ ] **Step 1: Write the failing test**

```tsx
it('fills the text and the title from a picked file', async () => {
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.upload(
    screen.getByLabelText('Text file'),
    new File(['the contents'], 'a-paper.md', { type: 'text/markdown' }),
  )

  await waitFor(() => {
    expect(screen.getByLabelText('Text')).toHaveValue('the contents')
  })
  expect(screen.getByLabelText('Title')).toHaveValue('a-paper')
})

it('sends what is on screen', async () => {
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.type(screen.getByLabelText('Title'), 'Hello')
  await user.type(screen.getByLabelText('Text'), 'hello')
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  await waitFor(() => {
    expect(documents.create).toHaveBeenCalledWith(project, {
      sourceId: 'hello',
      text: 'hello',
      title: 'Hello',
    })
  })
})

it('refuses an empty id before it calls the server', async () => {
  // The id is the citation key and the corpus keys on it, so a blank one is
  // refused here rather than spending a round-trip to be told.
  const user = userEvent.setup()
  render(<DocumentUpload projectId={project} onClose={vi.fn()} />, { wrapper })

  await user.type(screen.getByLabelText('Text'), 'hello')
  await user.clear(screen.getByLabelText('Identifier'))
  await user.click(screen.getByRole('button', { name: 'Add document' }))

  expect(documents.create).not.toHaveBeenCalled()
})
```

Build `wrapper` and the `documents` fake by copying `DocumentList.test.tsx`'s
`fakeDocuments()` and provider stack — there is no MSW here; the port is what
gets faked.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/research/DocumentUpload.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

A `Drawer` (heading "Add document") containing a form with, in order: a file
input labelled "Text file" accepting `.txt,.md,.markdown,text/*`; Title; an
Identifier field defaulting to a slug of the title and editable; URI; Note; a
textarea labelled "Text". Submit calls
`create.mutate(draft, {onSuccess: () => { notify('Document added'); onClose() },
onError: (error) => notify(errorMessage(error), 'bad')})`.

The file is read with `await file.text()` — the promise form of
`FileReader.readAsText`, and one line instead of an event handler. Picking a
file fills the text area and defaults the title from the filename with its
extension stripped, both only if the field is still untouched, so a person who
typed a title first does not lose it.

The slug: lowercase, non-alphanumerics to `-`, collapse and trim `-`. Put it
in a small exported `slugify` in the same file with a test, or inline it with
a comment — do not reach for a dependency.

Carry a comment on the accepted types explaining that the corpus stores text
and this build decodes nothing binary, so a PDF has to be converted first —
see the spec's Decision 1. Follow the existing dressing conventions in
`DocumentBrowser.tsx` for inputs (`className="input w-full"`), and **pair
`border-0` with any directional border width** per `CLAUDE.md`.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/presentation/research/DocumentUpload.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/presentation/research/DocumentUpload.tsx frontend/src/presentation/research/DocumentUpload.test.tsx
git commit -m "Add a document from a file or from pasted text

Read with file.text() in the browser rather than posted as multipart. The
corpus stores text, nothing in this tree decodes a binary document format, and
a multipart endpoint would have spent a dependency and a second content type
to accept a PDF it would then refuse -- after the upload rather than before.
The cost is stated in the form's own copy: a PDF has to be converted first.

The identifier is shown and editable rather than generated silently. It is the
citation key and the corpus keys on it, so it is not a detail to hide behind a
slug nobody saw."
```

---

### Task 7: The manage pane, the edit form and the drop dialog

**Files:**
- Create: `frontend/src/presentation/research/DocumentEditForm.tsx`
- Create: `frontend/src/presentation/research/DocumentDropDialog.tsx`
- Create: `frontend/src/presentation/research/DocumentManagePane.tsx`
- Create: `frontend/src/presentation/research/DocumentManagePane.test.tsx`
- Create: `frontend/src/presentation/research/DocumentEditForm.test.tsx`
- Modify: `frontend/src/presentation/research/DocumentList.tsx`

**Interfaces:**
- Consumes: `useReviseDocument`, `useDropDocument`, `useRestoreDocument`;
  `DocumentReader`; `Drawer`; `DocumentSummary`.
- Produces:
  - `DocumentManagePane({ projectId, sourceId, document }: { projectId: ProjectId; sourceId: SourceId; document: DocumentSummary | null })`
  - `DocumentEditForm({ projectId, document, onDone }: { projectId: ProjectId; document: DocumentSummary; onDone: () => void })`
  - `DocumentDropDialog({ projectId, sourceId, onClose }: { projectId: ProjectId; sourceId: SourceId; onClose: () => void })`

- [ ] **Step 1: Write the failing tests**

```tsx
// DocumentManagePane.test.tsx
it('offers Drop for a live document and Restore for a dropped one', async () => {
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })
  expect(screen.getByRole('button', { name: 'Drop' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()

  cleanup()
  render(<DocumentManagePane {...props({ droppedReason: 'off topic' })} />, { wrapper })
  expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Drop' })).not.toBeInTheDocument()
})

it('will not drop without a reason', async () => {
  // The aggregate refuses a blank reason and would answer 409. Refused here
  // too, so the person is told by the field rather than by a toast.
  const user = userEvent.setup()
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })

  await user.click(screen.getByRole('button', { name: 'Drop' }))
  await user.click(screen.getByRole('button', { name: 'Drop document' }))

  expect(documents.drop).not.toHaveBeenCalled()
})

it('drops with the reason typed', async () => {
  const user = userEvent.setup()
  render(<DocumentManagePane {...props({ droppedReason: null })} />, { wrapper })

  await user.click(screen.getByRole('button', { name: 'Drop' }))
  await user.type(screen.getByLabelText('Reason'), 'off topic')
  await user.click(screen.getByRole('button', { name: 'Drop document' }))

  await waitFor(() => {
    expect(documents.drop).toHaveBeenCalledWith(project, 's1', 'off topic')
  })
})
```

```tsx
// DocumentEditForm.test.tsx
it('sends only what changed, and no text', async () => {
  // The client half of the design: the server reads the stored text back when
  // none arrives, so correcting a title does not round-trip the prose and
  // cannot send back a stale copy of it.
  const user = userEvent.setup()
  render(<DocumentEditForm projectId={project} document={doc()} onDone={vi.fn()} />, {
    wrapper,
  })

  await user.clear(screen.getByLabelText('Title'))
  await user.type(screen.getByLabelText('Title'), 'Fixed')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => {
    expect(documents.revise).toHaveBeenCalledWith(project, 's1', { title: 'Fixed' })
  })
})

it('shows the identifier and does not let it be edited', async () => {
  // Changing it would create a different document and orphan every citation
  // pointing at the old id.
  render(<DocumentEditForm projectId={project} document={doc()} onDone={vi.fn()} />, {
    wrapper,
  })

  expect(screen.getByText('s1')).toBeInTheDocument()
  expect(screen.queryByLabelText('Identifier')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/presentation/research/DocumentManagePane.test.tsx src/presentation/research/DocumentEditForm.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write the three components**

`DocumentEditForm` — the upload dialog's fields minus the file picker and
minus an editable identifier, initialized from `document`, with the id
rendered as text. On save it builds a `DocumentEdit` containing **only the
fields whose value differs from the document's**, which is what makes the
"no text" assertion above true rather than incidental. Then
`revise.mutate({sourceId, edit}, {onSuccess: () => { notify('Document
updated'); onDone() }, onError: ...})`.

`DocumentDropDialog` — a `Drawer` built the way `Confirm.tsx` is (read it
first). Heading "Drop this document". Body copy, verbatim, because it is the
honest statement of what this does and Decision 3 exists for it:

> "The document stops being listed and stops being offered for extraction. Its
> record and its reason are kept, so this can be undone."
>
> "It is not erased. Anything already extracted from it stays in the graph, and
> a definition written earlier may still quote it."

Then a required "Reason" input, a Cancel and a destructive "Drop document"
whose handler returns early on a blank reason.

`DocumentManagePane` — an action bar above `<DocumentReader/>`. Buttons: Edit
and Drop when `document?.droppedReason` is null, Restore when it is not.
Editing swaps the body for `DocumentEditForm`. Dropping opens
`DocumentDropDialog`. Restore calls `restore.mutate(sourceId, {...})`
directly, with no dialog — it is not destructive and it is the undo for one
that was.

`DocumentList` renders `<DocumentManagePane projectId sourceId={reading}
document={rowFor(reading)} />` inside the reader drawer instead of
`<DocumentReader/>`, passing the summary it already has from `query.data`.
`DocumentReader` itself is not modified.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/presentation/research/`
Expected: all pass, including the existing `DocumentList.test.tsx` and
`DocumentBrowser.test.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/presentation/research
git commit -m "Edit, drop and restore a document from the reader drawer

Not from the browser row. The rows are virtualized against a 52px estimate in
a 340px rail and already carry two controls whose ring geometry a browser test
pins; three more would change the height or squeeze the title, and that row is
the measured part of the pane. The drawer has 640px, and every action here is
a decision made having read the thing.

The drop dialog says what a drop does not do -- the document is excluded and
kept, and anything already extracted from it stays in the graph. That gap is
real, purging it needs provenance the graph does not record, and the copy is
where a person meets it rather than a backlog entry.

Built on Drawer rather than widening Confirm, which takes lines: string[] and
has no slot for a field; adding one for a single caller would put an optional
input on every confirm in the console."
```

---

### Task 8: The Add button, and the gates

**Files:**
- Modify: `frontend/src/presentation/research/DocumentBrowser.tsx`
- Modify: `frontend/src/presentation/research/use-documents.ts`
- Modify: `frontend/src/presentation/research/DocumentList.tsx`
- Modify: `frontend/src/presentation/research/DocumentBrowser.test.tsx`
- Modify: `BACKLOG.md`

**Interfaces:**
- Consumes: `DocumentUpload` from Task 6.
- Produces: `onAdd: () => void` on `DocumentBrowser`'s props and on the
  `browser` object `useDocuments` returns.

- [ ] **Step 1: Write the failing test**

Add to `DocumentBrowser.test.tsx`:

```tsx
it('offers a way to add a document', async () => {
  const onAdd = vi.fn()
  const user = userEvent.setup()
  render(<DocumentBrowser {...props({ onAdd })} />)

  await user.click(screen.getByRole('button', { name: 'Add' }))

  expect(onAdd).toHaveBeenCalled()
})
```

Use the file's existing props builder rather than inventing one.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/research/DocumentBrowser.test.tsx`
Expected: FAIL — no such button.

- [ ] **Step 3: Add the button and thread `onAdd`**

In `DocumentBrowser`'s action row, beside "Extract all", a
`<Button small tone="quiet" onClick={onAdd}>Add</Button>` wrapped in a
`Tooltip` explaining "Store a document you have, rather than one an agent
found" — matching how the neighbouring buttons carry theirs.

It goes **before** the `total === 0` guard that the extract controls sit
after, or is otherwise placed so that a corpus holding nothing still offers
it: an empty corpus is exactly when a person most needs to add the first
document, and the existing guard would hide the control precisely then. Check
where that guard actually starts and place the button accordingly, with a
comment saying why it is outside it.

`useDocuments` gains `const [adding, setAdding] = useState(false)`, returns
`adding`, `onAddClose: () => setAdding(false)`, and `onAdd: () => setAdding(true)`
inside `browser`. `DocumentList` renders `{adding ? <DocumentUpload
projectId={projectId} onClose={onAddClose} /> : null}`.

- [ ] **Step 4: Run the full frontend verify**

Run: `cd frontend && npm run verify`
Expected: all of format:check, lint, typecheck, test:coverage, build, size
pass. If the bundle-size budget fails, raise the budget rather than shaving
the feature — that is the recorded preference — and say so in the commit.

- [ ] **Step 5: Run the browser suite**

Run: `cd frontend && npm run test:browser`
Expected: pass. This touches `DocumentBrowser`'s header, and
`DocumentBrowser.browser.test.tsx` measures ring geometry in that component.
**Do not start this while any other vitest process is running.** If something
fails, re-run it alone before investigating, then re-run the whole suite —
two identical results is the bar.

- [ ] **Step 6: File what was deliberately not built**

Add to `BACKLOG.md`, in the same voice as its neighbours: binary document
upload (no decoder in the tree; a person with a PDF converts it first), and
purging a dropped document's graph contributions (needs provenance the graph
does not record — which edges came from which document). Both are named in
the spec's "Deliberately not built" and each should say where its reasoning
lives.

- [ ] **Step 7: Run all four gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

All four. Three is not passing.

- [ ] **Step 8: Commit and open the PR**

```bash
git add -A
git commit -m "Offer Add from the document browser, and file what was left

The button sits outside the total === 0 guard the extract controls sit
inside: an empty corpus is exactly when somebody needs to add the first
document, and the guard would hide the control precisely then.

Backlog gets the two things this deliberately did not build, each with the
reason rather than the name: binary upload, and purging a dropped document's
graph contributions."
git push -u origin worktree-sidebar-shell
gh pr create --fill
```

## Self-review

**Spec coverage.** Decision 1 (browser-side text upload) → Task 6. Decision 2
(the write service and the two paths) → Tasks 1, 2. Decision 3 (soft drop,
copy about what is not erased) → Task 7. Backend routes → Task 3. Frontend
port → Task 4, mutations → Task 5, components → Tasks 6–7, the Add button →
Task 8. Every test the spec names has a task: the metadata-only revise (Task
2), the `index` call (Task 2), the un-drop domain test (Task 2), the
fixture-blindness route test (Task 3), the three frontend suites (Tasks 6–7),
the Add button (Task 8). The spec's "Deliberately not built" reaches
`BACKLOG.md` in Task 8.

One spec item is deliberately not a task: the read-model addition to
`tests/infrastructure/test_corpus_read_model.py`. The spec says this feature
adds no column and changes no projection shape, and the route tests in Task 3
already assert a revised title reaches the listing, which is the same claim
through the same table. If Task 2 or 3 finds itself touching
`CorpusDocumentRow`, that is the signal the spec was wrong — stop, add the
column reconciliation check, and run against a copy of a real database via
`uv run python -m research_team.infrastructure.persistence.local_copy`.

**Names.** `CorpusEditor`, `DocumentExists`, `NotDropped`, `UnknownDocument`,
`DocumentDraft`, `DocumentEdit`, `create`/`revise`/`drop`/`restore` are used
identically in every task that mentions them. The service methods are
`store`/`revise`/`drop`/`restore` and the port methods are
`create`/`revise`/`drop`/`restore` — `store` and `create` are the same
operation on opposite sides of the wire, named for what each side calls it,
and no task uses the other side's word.

**Verification the plan cannot do for you.** Three places say "read this
first and use what is there": `AggregateRepository`'s load/save names (Task
1), whether `read_document` filters dropped rows (Task 2), and the branded-id
constructors (Tasks 4–5). Each is a fact this plan asserts from a partial
read; check rather than trusting the code blocks above.
