# Mounting the corpus into the agent's file tools

## The defect

`grep` cannot see a single gathered source, and nothing says so.

The agent's file tools (`ls`, `glob`, `grep`, `read_file`) are deepagents'
built-ins over `EventSourcedBackend`, whose only read seam is
`dict(self._aggregate.state.files)` — the agent's own scratch files, folded out
of one session's event stream. Gathered sources live in an entirely different
store: the corpus read model plus a blob store, reached through
`ProjectCorpusReader`. Nothing projects one into the other.

So a `grep` for a phrase that appears in thirty kept documents returns no
matches, and an empty result is indistinguishable from a search that ran
against the right corpus and found nothing.

It bites hardest on the ask page, where `ASK_PROMPT` tells the model it can
"read the project's sources … and its files" and `READ_ONLY_FILE_TOOLS`
advertises `grep` directly beside `list_sources`. The model reaches for the
search-shaped tool and is told, in effect, that the project never gathered
anything.

The corpus has no search of its own either — `corpus_tools.py` exposes exactly
`list_sources` and `read_source`. Today the only way to search gathered text is
to read documents one at a time, or to go through the graph, which
`corpus_tools.py`'s own docstring rules out: an extraction is what a claim
needs checking *against*, not the thing to quote.

## The approach: mount, don't reimplement

`StateBackend` implements every file tool in terms of `_read_files()`. Read
from the installed 0.2.x source rather than assumed:

```python
def grep(self, pattern, path=None, glob=None, *, max_count=None) -> GrepResult:
    files = self._read_files()
    return grep_matches_from_files(files, pattern, path if path is not None else "/", glob, max_count=max_count)
```

`ls`, `glob` and `read` open identically. So merging corpus documents into that
one dictionary lights up all four tools at once, with deepagents' own pattern
matching, path filtering, result truncation and error strings — which is the
same reasoning `backend.py`'s docstring already gives for overriding only the
two seams.

Mount point is `/sources/<source_id>`.

One path segment per id is safe as of 06ad597, which refuses a `source_id`
containing `/` on the command path. Before that commit a url-keyed id would
have mounted as a directory tree and `ls /sources/` would have answered with
`https:/` — the fix that made per-source routes addressable is the same fix
that makes them mountable.

No file extension. `glob("/sources/*")` works without one, and an extension
would put a suffix between the path the model reads out of a grep hit and the
`source_id` it has to pass to `read_source`.

## What is mounted

Text sources only, not dropped.

- **Media is excluded.** A `MediaRecord` has no text. Mounting a filename with
  no content would put an empty file in front of every `grep`, which reads as
  "searched it, nothing there" for a source that was never searchable.
- **Dropped documents are excluded** — `include_dropped=False`, the port's
  default. A dropped document is one the project decided against; surfacing it
  to a search would reverse that decision silently.

No size cap. A cap that silently drops the tail of the corpus produces exactly
the failure this whole change exists to remove — a `grep` that misses and says
nothing. The cost is real and is stated below rather than mitigated.

## Search here, read through the corpus tool

**`read_file` refuses a mounted path** and names the call that works:

```
'/sources/s1' is a mounted corpus document; read it with read_source(source_id="s1")
```

The reason is citations, and it is the only part of this design that is not
mechanical. The corpus contract is `source_id@start-end`, character offsets
computed by `corpus_spans.quote` and reported back from the result rather than
from the request — `corpus_tools.py` is explicit that an offset which drifts
from the text under it is worse than no offset, because a citation built on it
looks verifiable and is not. `CITED_BY_TOOL` credits `read_source` alone for
that reason.

A mounted `read_file` would return a line-numbered window and earn no citation.
On the ask page that is an answer quoting gathered material with nothing
attached — the exact failure `corpus_tools.py` was written against. So the
mount is for *discovery*: `grep` says which source and roughly where,
`read_source` returns the span that can be quoted.

Grep hit snippets still put source text in front of the model without a
citation. That is accepted: a snippet is how the agent decides what to open,
and the alternative is a search that will not say what it found.

## Writes

Refused under `/sources/`, in `_send_files_update`.

Without this, `write_file("/sources/s1", ...)` appends a real `WriteFile` event
and puts a divergent copy of a source in session state, where it shadows the
mount for every later read. That is corpus corruption by way of the scratch
filesystem, and it is durable — the event log is not rewritten.

`edit_file` and `delete` reach the same seam and are refused by the same guard.
`ReadOnlyProjectBackend` already refuses every write, so the ask page needs
nothing further.

## The async seam

`_read_files()` is synchronous and is called inside synchronous tool bodies.
`ProjectCorpusReader.list_sources` and `read_document` are coroutines. The
mount is therefore a **snapshot taken per turn, in async context, and handed to
the backend as a plain dict** — which is the shape both call sites already use:

- `ask_agent.py:167` awaits `self._project_files(project_id)` and passes the
  result to `ReadOnlyProjectBackend`.
- `deep_agent.py:_invoke` is async and constructs `EventSourcedBackend(session)`
  per turn, next to `await self._resolved_tools(session)`.

**Consequence, deliberate:** a document `remember`ed during a turn is not
greppable until the next one. Making it live would mean either an async read
seam deepagents does not have, or a thread-blocking call inside a sync tool.
The staleness window is one turn and the tool that stored the document already
returned its `source_id`, so the agent can `read_source` it immediately without
searching for it.

## Costs

1. **The whole corpus is resident per turn and rescanned per call.**
   `grep_matches_from_files` walks every mounted document on every `grep`.
   Measured on 2026-08-16 against a copy of the real database: 69 text sources
   across three projects, mounting to 1.5M, 331K and 181K characters. The
   largest project is 1.5MB held per turn and walked per call. Affordable now;
   the number to watch.
2. **One turn of staleness**, as above.
3. **Two ways to reach a source** — `ls`/`glob`/`grep` through the mount,
   `read_source` through the tool — with a refusal in between explaining why.
   A model that has not read the refusal will waste one call.
4. **Snapshot cost per turn**: `list_sources` plus one `read_document` per text
   source, before the model is called at all. Paid on every turn, including
   turns that never touch a file tool.

## Rejected

**Mount `read_file` too, and map the path back to a citation.** Cheaper for the
model — one tool instead of two — and it was the first shape considered. It
means synthesising a `source_id@start-end` from a line-window read, and the
line window is deepagents' own slicing, so the character offsets would be
computed here rather than by `corpus_spans.quote`. Two citation builders that
must agree forever is how offsets drift, and drifted offsets are the one
failure `corpus_tools.py` says is worse than having no offsets at all.

**A `search_sources` corpus tool instead of a mount.** One tool, one contract,
citations for free from `corpus_spans.quote`. Rejected because it leaves `grep`
in the tool list still answering "no matches" over the wrong store — the
misleading affordance is the defect, and adding a correct tool beside it does
not remove it. Worth revisiting if the mount's scan cost becomes real, at which
point a tool backed by an indexed search is the answer and the mount comes out.

**A denylist that hides `grep` from the ask agent.** Removes the wrong answer
without supplying the right one, and the ask page is where searching gathered
material is most obviously the whole job.

## Tests

Each names the defect it fails on.

1. `test_grep_finds_a_term_only_a_corpus_document_holds` — fails if the mount is
   absent. The term must appear in no session file, or the test passes against
   an unmounted backend.
2. `test_ls_shows_a_mounted_source_beside_the_session_files` — fails if the
   mount is keyed off a prefix `ls` does not walk.
3. `test_read_file_on_a_mounted_path_names_read_source` — fails if `read`
   serves mounted text, which is the citation hole.
4. `test_writing_to_a_mounted_path_appends_no_event` — asserts on the event
   log, not on the raised error: a guard that raises *after* executing the
   command passes an exception-shaped assertion.
5. `test_a_media_source_is_not_mounted` — fails if the snapshot mounts every
   `SourceListing` rather than the text ones.
6. `test_a_dropped_document_is_not_mounted`.
7. `test_the_ask_agent_can_grep_the_corpus` — the ask path builds its own
   backend, so 1 passing proves nothing about it.
8. `test_a_session_file_under_sources_does_not_shadow_the_corpus` — an older
   build could have written one before the guard existed, and the mount must
   win.

Test 4 is the one to prove red first: it passes trivially against a build with
no mount at all, since a write to `/sources/x` is then an ordinary scratch file
that appends an ordinary event — so it has to be written against the mount and
watched to fail. It was: with the read side landed and the write guard not yet
written, it failed `DID NOT RAISE MountedSourceIsReadOnly` with the event
already appended.

## Measured, not reasoned

Against a copy of the real database on 2026-08-16, through
`ProjectCorpusReader` over the real `CorpusRunner`:

```
project 20566d34 (Ancient Rome): 21 listed, 21 mounted, 1,525,116 chars
  grep 'Constantine':            43 hits over the mount
  grep 'Constantine' unmounted:   0 hits
```

Zero against forty-three is the defect and the fix in one line. All 69 text
sources across the three projects mounted; the refusal renders with the real
derived ids (`read_source(source_id="en-wikipedia-org-wiki-agriculture-in-ancient-rome-74a06c27")`).
