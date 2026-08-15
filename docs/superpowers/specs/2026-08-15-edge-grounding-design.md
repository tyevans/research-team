# Edge grounding: can an edge be cited, and what to do about the wasted call

Design investigation for "Important 1" of `final-review.md`. No code changed.

## Recommendation, in one line

**Option 1: refuse before the model call when there are no passages** — and
say in the code *why* that is not a limitation being cemented but the only
honest reading of what an edge is in this system today.

The reasoning is not "edges are less important than passages". It is that a
citation in this design is `(source_id, start, end)`, an edge does not carry
`start`/`end`, **and the absence is deliberate upstream rather than an
oversight this repo can fix**. Option 2 is not a bigger version of the same
change; it is a change to redstring's extraction schema.

## The crux: does an edge carry provenance a reader can open?

Traced end to end, from the upstream type down to the pixel.

**redstring's `Relationship`** — `.venv/.../redstring/domain/relationship.py:13-34`.
Fields: `id`, `tenant_id`, `source_entity_id`, `target_entity_id`,
`relationship_type`, `source_id: SourceId | None`, `properties`, `confidence`.
So there *is* a document id, and there is no span. The docstring says why, and
it is worth quoting because it is the whole answer:

> There is deliberately no `source_text` beside it. `Entity` has one because
> the extraction schema asks the model for it; `ExtractedRelationship` has no
> span field, so a `source_text` here could only be reconstructed or
> paraphrased -- and a paraphrase in a field named for a quotation reads as
> evidence while being generation. See BACKLOG B76 for what asking for it
> would cost.

That is the same argument this feature's own module docstring makes about
ungrounded definitions, made one layer down about edges. An edge-as-citation
would be exactly the thing both docstrings refuse: something that renders as
checkable and is not.

**This repo's `GraphRelationship`** — `research_team/application/graph_read.py:110-133`.
Carries `source_id`/`target_id` (which are *entity* ids, not document ids),
`relationship_type`, `inferred`, `derivation`. It does not carry the
document `source_id` at all: `_to_graph_relationship`
(`research_team/infrastructure/knowledge/graph_reader.py:57-62`) builds it
from three fields and drops the rest. So even the document-level provenance
that does exist upstream is not present at the point `entity_definitions.py`
would need it.

**Inferred edges have no document, ever.** `_inferred_edges`
(`graph_reader.py:65-99`) constructs them from `infer_relations`, pure
arithmetic over two temporal extents. There is no source to cite because no
document said it. The prompt already marks these `[inferred]`
(`entity_definitions.py:158-163`) precisely so the model does not report a
computation as a reported fact. An entity whose only edges are inferred is
the *most* likely edge-only entity in a young graph (a bare date node), and
it is the case where an edge citation is most clearly a fiction.

**What the panel would have to render.** `GraphDetail.tsx:194-204` renders a
citation as a link to the `doc` facet, `href={projectHref(projectId, {facet:
'doc', id: citation.sourceId})}`, labelled `shortId(citation.sourceId)`. An
edge citation has nothing to put in that href beyond, at best, a whole
document with no offset — a link that opens a document and leaves the reader
to find the claim themselves, which is the "range that does not exist"
problem `_verified`'s docstring
(`entity_definitions.py:211-219`) already rejects, one step less obvious.

**Verdict.** The category-error argument is the correct one. Edges *support* a
definition — they are legitimately in the prompt, and the spec is right that
the definition is grounded in passages **and** edges — but "grounded in" and
"citable" are not the same relation, and this system's refusal rule is built
on citability, not on support. An edge can constrain what the model may say;
it cannot be the thing a reader clicks.

## What changes (Option 1)

1. **`research_team/application/entity_definitions.py:326`** — the guard
   becomes `if not passages: return None`. The `neighborhood.relationships`
   half goes, because an entity with edges and no passages is already
   guaranteed to be refused four lines later at :332; the only thing the
   current guard buys it is one model call.

   The comment must say the *new* thing, not restate the code: that this is
   not "edges do not count as grounding" but "no citation this system can
   verify can come from an edge, so the refusal at :332 is knowable here",
   with the pointer to `Relationship`'s missing span as the reason.

2. **`entity_definitions.py:10-13`** (module docstring bullet) — "An entity
   with no passages *and* no edges" becomes "no passages". Keep the
   reasoning; extend it with the edge case, since a reader who knows edges
   are in the prompt will otherwise think this is a bug.

3. **`entity_definitions.py:253-262` and `:284-287`** (`define`'s docstring) —
   "an entity with no passages and no edges" and "an entity with nothing to
   ground a definition in is refused before any request reaches the model"
   both narrow to passages. The second sentence is the one that matters: it
   is currently a true statement about a false premise, and it is the kind of
   docstring that let this survive three reviews.

4. **`research_team/composition.py:1474-1480`** — this one is **already
   correct** and should be left, not "fixed". It says a missing chunk store
   "costs definitions for edge-only entities, which `DefinitionService` could
   otherwise ground without passages -- accepted ... because a definition
   assembled from edges alone cites nothing and would be refused by
   `_verified` anyway." That is the finding, written down before the fix. The
   only edit worth making is deleting "could otherwise ground without
   passages", which is the half that is now wrong, and pointing at the guard.

5. **Nothing in the frontend changes.** `GraphDetail.tsx:160-166` already
   renders `text === null` as "No grounded definition is available for this
   entity." That is what an edge-only entity sees today, after a model call;
   it is what it will see tomorrow, without one.

## What a reader sees

Identical output, sooner and cheaper. The only observable difference is
latency and cost on entities that were always going to be refused.

## What it costs

- **It cements passages-only citability.** Stated plainly rather than hidden:
  an entity that a human could genuinely define from its edges alone will not
  be defined. In a young corpus with a rich extracted graph this is a real
  loss, and the graph panel is where it is most visible.
- **It makes the spec's "and in the edges" sentence read as broader than the
  code.** The spec is not wrong — edges *are* in the prompt and do shape the
  text — but someone reading only that sentence will expect edge-only
  definitions. Worth one line in the spec, or in the module docstring, saying
  edges ground but do not cite.
- **The recovery path is not closed.** If redstring ever gains a span on
  `ExtractedRelationship`, `GraphRelationship` gains a source id and offsets,
  and `_verified` gains a second clause. Nothing in this change makes that
  harder; it is a strictly smaller diff than the one being deferred.

## What could go wrong

- **A regression in the other direction:** someone later "restores" the edge
  half of the guard as an obvious symmetry fix, and the wasted call comes
  back. Mitigated only by the comment and by test (a) below, which fails on
  exactly that.
- **The stale-fallback interaction.** `define` falls back to the stale cached
  row when `_generate` returns `None` (`:293-309`). Moving the refusal earlier
  does not change which entities return `None` — the set is identical — so the
  fallback behaviour is unchanged. Worth asserting rather than assuming; test
  (c).
- **`usages` failing (rather than returning empty)** would now be the only
  thing standing between an edge-only entity and a refusal. It already was, at
  `:321`; no change.

## Tests that pin it

All in `tests/application/test_entity_definitions.py`, beside the existing
`test_an_entity_with_no_passages_and_no_edges_is_not_sent_to_the_model`
(`:237`).

- (a) `test_an_entity_with_edges_but_no_passages_is_not_sent_to_the_model` —
  the load-bearing one. Fake `DefinitionTextPort` records call count; assert
  zero and `define(...) is None`. **This fails today**: the current code calls
  the model once and then returns `None`, so the `None` assertion alone would
  pass green against the bug. The call-count assertion is the test; write the
  docstring to say so.
- (b) Rename/retarget the existing `:237` test — with the guard narrowed, "no
  passages and no edges" is no longer the boundary. Keep it (it is a real
  case) but add (a); the pair is what documents the boundary's new position.
- (c) `test_an_edge_only_entity_falls_back_to_its_stale_definition` — a cached
  stale row plus edges and no passages returns the stale text with
  `stale=True`, and still calls the model zero times. Guards the interaction
  in "what could go wrong" above.
- (d) Prompt test `:222` is unaffected and should stay: the edges are still in
  the prompt for every entity that has passages. If it were deleted, nothing
  would fail if the edge section were dropped from `build_prompt` entirely,
  and edges genuinely do ground the text.

## Rejected

**Option 2 — edges as first-class citations.** Rejected because the data does
not exist: `Relationship` has no span, `ExtractedRelationship` has no span
field to populate one from, and the omission is argued for upstream in
`relationship.py:22-32`, not accidental. Implementing it means either asking
the extraction model for spans (a redstring change, redstring's B76) or
synthesising a range, and a synthesised range is the paraphrase-as-evidence
failure the same docstring names. Inferred edges could never satisfy it at
all.

**Option 3 — "at least one verifiable citation OR a non-empty edge set", with
the UI distinguishing the two.** Rejected because it stores a definition whose
claims cannot be checked and labels it, which is precisely the alternative
`entity_definitions.py:16-22` already considered and rejected: "a label is
read once and the paragraph is read every time". Re-litigating it here without
new evidence would be reversing a written decision on weaker grounds than it
was made on. It also introduces the cached-ungrounded-text invalidation
problem that same passage names.

**Do nothing.** Rejected: one model call per panel open per edge-only entity,
refetched on remount, for a result that is knowably `None` before the call.

**A wider fix — carry the document `source_id` onto `GraphRelationship` so
edge-only entities cite whole documents.** Rejected, but the closest call. It
is buildable today (the field exists upstream at `relationship.py:33`), and it
would give the reader a document to open. It fails on offsets: every other
citation in the system points at a span, `GraphDetail.tsx:194-204` and
`corpus_spans.quote` are both built for spans, and a citation list mixing
"this sentence" with "somewhere in this document" degrades the ones that are
precise. Worth a backlog entry rather than this change.
