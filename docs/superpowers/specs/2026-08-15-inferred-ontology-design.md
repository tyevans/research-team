# Inferred ontology: classes the text states and extraction throws away

Extraction produces `EASY`, `NORMAL`, `HARD`, `EXPERT`, `MASTER`, `APPEND` as
six unrelated `category` entities. The document they came from says, in one
sentence: *"There are six difficulties available in the game: EASY, NORMAL,
HARD, EXPERT, MASTER, and APPEND."* The class name, the membership, the
ordering and the count are all in that sentence, and none of the four survives
into the graph.

This is the design for recovering them: a persisted, re-runnable pass that
reads source text, emits classes and memberships marked inferred, and shares
only the *display* contract with the temporal edges already on the canvas.

## What was measured before designing this

All of it against `~/.research-team/sessions.db` on 2026-08-15, opened
read-only, by folding `DocumentExtracted` payloads out of the `events` table.
The graph itself is not a table — it is in-memory, folded from the log — so
these numbers come from the log, not from a store.

**The source document says it outright, in three different shapes.**
`source_id='sekaipedia-songs'`, 4,890 characters, project
`3881dec0-6d7c-4418-aaa0-f45d2a97032a`:

- *An enumerating sentence.* "There are six difficulties available in the game:
  EASY, NORMAL, HARD, EXPERT, MASTER, and APPEND." Class name, six members, an
  ordering that is not alphabetical, and a count that acts as a checksum.
- *A table whose header column names the class.* `| Rank | Reward |`, rows
  `D rank` through `S rank`. Plus, in the prose above it, the direction:
  "a rank from S to D will be assigned based on score earned."
- *A prose-structured two-level taxonomy.* Under "Versions of Songs": three
  version types obtainable directly (VIRTUAL SINGER / SEKAI / Collaboration)
  and three that "must be purchased separately after the base song is
  obtained" (Alternate Vocal / April Fools' / Connect Live). The split is a
  class with two subclasses, and the subclass criterion is stated.

**The extracted graph has eleven `category` entities from that document and no
class among them.** `EASY NORMAL HARD EXPERT MASTER APPEND` and `D/C/B/A/S
rank`. Note this differs from the brief's framing in two ways worth recording,
because both change what the design has to do:

- The brief listed four difficulties and three ranks. All six and all five are
  present. Nothing was dropped by extraction; only the structure was.
- The brief said none of them are connected. **The six difficulties are
  connected** — each has an asserted `part_of -> Rhythm game` edge — and the
  five ranks have no edges at all. That does not weaken the case, it sharpens
  it: `part_of Rhythm game` says the difficulties belong to a game feature. It
  does not say they are six members of one enumerated, ordered scale. The
  edges extraction *did* draw are the wrong shape for the claim the sentence
  makes, which is a stronger argument than "there are no edges" — a grouping
  pass has to add structure a plain edge cannot express, not merely add edges.

**`category` is not one problem.** Three projects hold it:

| project | entities | of type `category` |
|---|---|---|
| Project SEKAI (`3881dec0…`) | 55 | 11 |
| Ancient Rome (`cf4d9a61…`) | 2,525 | 116 |
| budgeting (`bbb418fd…`) | 174 | 45 |

The Ancient Rome 116 were read, not sampled. They are overwhelmingly *social
groups and occupations* — `plebeians`, `freedmen`, `fullones`, `salt merchants
(salinatores)`, `goldsmiths (aurifices)`, `Church Fathers`. A handful are
enumerable (`Official cults` / `Non-official but lawful cults` is a genuine
two-member partition the text states). Most are the model reaching for
`category` because the surface form was a plural noun phrase.

**This is the single most important finding in the document and it corrects the
brief's premise for layer 3.** Ontology discovery will not fix `category` in
Ancient Rome, because `category` there is not a flattened set of classes — it
is a bucket for plurals, and there is no class hiding in `fullones` to
discover. Layer 3 is therefore justified as *giving discovered classes somewhere
to land so re-extraction stops flattening them again*, and not as a repair of
`category`. The `category` bucket is a separate defect with a separate fix
(narrower types, or a prompt that says what to do with a plural noun phrase),
and conflating the two would buy per-project schema machinery on a promise it
cannot keep. §7 gates the build on a measurement for exactly this reason.

**The existing inferred-edge contract is already end-to-end and needs nothing
new for layer 1.** `GraphRelationship.inferred` / `.derivation`
(`research_team/application/graph_read.py:112-128`), computed in
`_inferred_edges` (`graph_reader.py:65`), rendered dashed in
`--link-inferred` (`GraphCanvas.tsx:274-275`), keyed on
`source|target|relationshipType|inferred` (`graph.ts:141-146`) so an asserted
and an inferred edge between the same pair cannot collide.

## 1. The crux: why this cannot live on the read path

The temporal edges are the obvious precedent and the wrong one to copy
wholesale. Being precise about *why* is what determines everything below.

`infer_relations` is admissible in `ProjectGraphReader.whole` because of four
properties, not one:

1. **Pure.** No I/O, no round trip; it runs over entities `whole` already
   fetched (`graph_reader.py:70-72` says so).
2. **Cheap.** Interval arithmetic. Bounded by `MAX_INFERRED_EDGES` and, above
   that, by `DEFAULT_MAX_PAIRS`.
3. **Deterministic.** The same extents always produce the same relations.
4. **Self-invalidating.** Because it is recomputed from current extents on
   every read, it *cannot* go stale. redstring's ADR 0005 gives staleness as
   the first reason `InferredRelation` carries no id: re-extraction improves an
   extent and there is no invalidation event. Recomputing every time is how
   that reason is answered rather than mitigated.

Grouping `D rank … S rank` into an ordered scale named "Rank" has **none of the
four**. It is a model judgement over document text: it needs a network call
measured in seconds, it costs money per call, two runs can disagree, and its
inputs are document text rather than the entity list already in hand. Putting
it behind `GraphReadPort.whole` would put a paid, multi-second, nondeterministic
call on the path a browser hits every time somebody opens a project — and
`whole` is the read a browser *opens with* (`graph_read.py:219`). That is not a
close call.

So the pass is persisted. What that costs is exactly what ADR 0005 warns about
and property 4 gave away for free: **a stored class can go stale.** Re-extract
the document under a better prompt, the entity ids change, and a stored
membership points at an entity that is gone. §4 pays for that explicitly, with
the same `stale`-flag shape `EntityDefinitionRow` already uses
(`read_models.py:1099`) rather than pretending the problem does not exist.

**ADR 0005's "no id" constraint does not bind here, and it is worth saying why
so nobody re-litigates it.** That ADR is about redstring's `InferredRelation`,
which deliberately carries no id so it cannot be handed to
`GraphStore.upsert_relationship` even by accident. This pass produces no
`InferredRelation` and writes nothing into the redstring graph. It writes into
*this application's own* read model, and the redstring graph stays exactly what
documents asserted. That separation is the whole design, and §2 rejects the
alternative.

**What is shared is the display contract and nothing else.** By the time a
class edge reaches the canvas it is a `GraphRelationship` with `inferred=True`
and a `derivation` — indistinguishable in kind from a temporal one, drawn by
the same dashed stroke, keyed by the same key. The production paths have
nothing in common; the presentation is identical. That is the correct seam:
a reader should learn "this line was derived, here is the working" once, and
not have to learn it twice for two flavours of derivation.

## 2. Rejected: writing classes into the redstring graph as ordinary entities

The tempting shortcut — mint a `Rank` entity and five `is_a` relationships,
`upsert` them, done. Everything downstream works with no new tables, no new
projection, no new DTO field.

Rejected for three reasons, in increasing order of severity:

- **It erases the distinction at the source of truth.** A stored relationship
  is, by this repository's own contract, "something a document said"
  (`graph_read.py:113-119`). A derived class edge stored identically is
  indistinguishable from an asserted one forever after, and every consumer —
  the canvas, `neighborhood`, the definition prompt which already marks
  `[inferred]` edges (`entity_definitions.py:138-180`) — silently starts
  treating a judgement as a citation.
- **`DocumentExtracted`'s validators refuse it anyway.** The event requires
  entities to be attributed to its `source_id`
  (`redstring/events/document.py:103`). A class node is derived from the
  document but is not an extraction of it, and forcing it through that event
  means lying in the field the validator checks.
- **Re-running becomes a merge problem.** The pass will be re-run often (§3).
  Re-running an `upsert`-based version needs delete-or-merge machinery for
  superseded classes, against a store whose merge semantics deliberately keep
  absorbed rows alive for `undo_merge` (`graph_reader.py:114-138`). A
  read-model row is replaced by writing over it.

## 3. Where the pass runs: separate, not inside `DocumentExtractor.extract`

**Recommendation: a separate pass over already-extracted documents,
re-runnable per document and per project without re-extracting.**

The three arguments for folding it into `extract` are real: one traversal of
the text, one place to wire, no chance of a document that is extracted but not
grouped. They lose to four arguments against, one of which is measured.

- **Re-extraction is not free, and this prompt will change repeatedly.** A
  first ontology prompt will be wrong several times — every judgement prompt in
  this repository has been. If discovery lives in `extract`, iterating on it
  means re-extracting. Measured consequence:
  `EntityDefinitionProjection.handle(DocumentExtracted)`
  (`read_models.py:1261`) marks **every entity in the event** stale. So
  re-extracting one document to retune an ontology prompt discards every
  cached definition for every entity in it — paid model work thrown away by a
  pass that has nothing to do with definitions. Re-extraction also remints
  entity ids, which is what merges and human judgements
  (`domain/judgements.py`) are keyed against.
- **Discovery needs extraction's output, not just the text.** A membership must
  resolve to an entity that exists, so the members named in the sentence have
  to be matched against extracted entity names. Inside `extract` that matching
  would happen against entities not yet committed; as a second pass it happens
  against the graph as it stands.
- **The two have different failure and retry profiles.** Extraction failing is
  "this document is not in the graph". Discovery failing is "this document is
  in the graph without its classes" — degraded, not broken. Sharing one queue
  entry means one failure mode reports the other's severity.
- **The shapes already exist separately.** `POST …/sources/{id}/extract` is the
  queued-202 shape for a model call (`app.py:937`); `POST …/sources/reindex` is
  the per-project synchronous sweep (`app.py:909`). Discovery is a model call,
  so it takes the first shape, per document and per project.

**What splitting costs, stated rather than waved at.** A document can be
extracted and never grouped, and nothing forces the second pass. That is a real
regression against the folded design and it is paid for in §4 with an
`ungrouped(project_id)` listing mirroring `DocumentExtractor.unextracted`
(`document_extraction.py:107`), so "which documents have no ontology pass" is a
question with an answer rather than a thing somebody notices later.

## 4. What gets built

### Layer 1 and 2 are one write, not two

A class and its memberships are produced by one model call and are meaningless
apart — a membership with no class has nothing to belong to, and a class with
no members is a name. They are two tables because they are two cardinalities,
not two features.

### The domain event

A new event in `research_team/domain/events.py` (extraction's events come from
redstring; this pass is ours, so its event is ours), appended against the
corpus-document aggregate, alongside `CorpusDocumentStored`:

```
OntologyDiscovered
    source_id: str
    model_version: str
    classes: list[DiscoveredClass]
```

where `DiscoveredClass` carries `name`, `kind`, `declared_count | None`,
`parent_name | None`, `evidence` (source_id + start + end), and `members: list[
DiscoveredMember]` of `name` + `ordinal | None`.

Two obligations from `CLAUDE.md` come with it and are not optional:

- `tests/infrastructure/test_schema_evolution.py` grows a case writing this
  payload shape straight into the events table and reading it back. Adding a
  new event type is the safe direction (an older build with no projection for
  it replays cleanly), so the case is cheap — but the field it will actually
  protect is `kind`, whose vocabulary §5 expects to grow.
- **The event carries names, not entity ids.** Ids are resolved by the
  projection at write time and re-resolved at read time. Storing ids in the
  event would make the log record a fact about a graph state that
  re-extraction can invalidate, which is the durable-log-of-derived-facts
  mistake ADR 0005 is about.

### The read models

Two tables, `ontology_classes` and `ontology_memberships`, following
`EntityDefinitionRow`'s shape (`read_models.py:1099-1134`) including the
`uuid5(NAMESPACE, f"{project_id}:…")` row id.

`ontology_classes`: `project_id`, `source_id`, `name`, `kind`,
`declared_count: int | None`, `member_count: int`, `parent_class_id: str |
None`, `evidence_start`, `evidence_end`, `evidence_text`, `model`,
`generated_at`, `stale: bool`.

`ontology_memberships`: `project_id`, `class_id`, `member_name`,
`entity_id: str | None`, `ordinal: int | None`.

Three fields are the ones that earn layer 2 its separate rendering and each has
to justify itself:

**`kind`** — `ordered_scale`, `unordered_set`, `taxonomy`. This is the thing a
plain edge cannot express and the reason a class node is not just a hub. Five
`instance_of` edges into a `Rank` node say the same thing whether ranks are a
scale or a bag; only `kind` says S is above A. Rendering follows in §6.

**`declared_count`** — the checksum. "There are **six** difficulties" is a claim
the pass can be checked against: six declared, six found, verified. Five found
means the pass dropped one, and *a discovered class that silently lost a member
is worse than no class at all*, because it looks complete. When
`declared_count` is present and disagrees with `member_count` the class is
stored anyway and shown as incomplete — not discarded, because the four members
it did find are still true, and not shown silently, because the reader has to
know. When the text states no count, `declared_count` is `None` and no check is
possible; that is the ordinary case, not an error.

**`entity_id: str | None`** — nullable on purpose, and this is the staleness
answer §1 promised. A member the pass named but that resolves to no entity
today keeps its row with a null id: it is dropped from the drawing (nothing to
draw it against) and retained in the class, so `member_count` still checks out
against `declared_count` and a re-run is not needed merely because a name
drifted. Deleting the row instead would make an unrelated re-extraction look
like a discovery failure.

**A fourth field exists for §6 alone and would not otherwise be stored:
`rejected_members`**, a list of `name` + `reason` on the class row. Verification
(below) drops members the model named that do not occur in the document. Dropping
them silently is what makes a class unjudgeable: the reader sees "5 of 6 stated"
and cannot tell whether the model invented a sixth member or the document really
is short one. Recording the rejection turns an unexplained gap into a legible
one. It costs a JSON column on a table with one row per class per document, which
is the cheapest thing in this design.

Resolution is by `normalized_name` against the project's entities. It will
sometimes fail — "S rank" in the table versus "S-rank" in prose is exactly the
kind of drift the corpus produces. That is a known, bounded imprecision and it
fails visibly (a member with no node) rather than wrongly (a member wired to
the wrong node).

### The projection, the runner, and the four wiring points

An `OntologyProjection(DeclarativeProjection)` with `@handles(OntologyDiscovered)`
replacing that source's classes wholesale, and `@handles(DocumentExtracted)`
marking that source's classes `stale` — the same *mark, never regenerate*
discipline `EntityDefinitionProjection` documents at `read_models.py:1230-1233`,
and for the identical reason: a bulk re-extraction must not fire a model call
per document.

An `OntologyRunner` beside the other five in `composition.py`, then the three
registration points the existing runners establish — the comment at
`composition.py:702-707` states the rule ("a projection wired somewhere else is
a projection somebody forgets to start"): construct in `build_application`, add
an `Application` field, add lines to `start()` / `caught_up` / `stop`.

Its `rebuild()` follows `EntityDefinitionRunner.rebuild`
(`read_models.py:1395`) — reset the checkpoint, replay, **do not truncate** —
because like a definition's text, a class's `model`/`generated_at` and its
resolved ids are not derivable from the log alone.

### The service

`research_team/application/ontology_discovery.py`, in the shape
`entity_definitions.py` established:

- Narrow application-layer ports (`OntologyTextPort` with `model_name` +
  `async generate(prompt) -> str`, mirroring `DefinitionTextPort` at
  `entity_definitions.py:87`) so `tests/test_architecture.py` keeps
  `BaseChatModel` out of the application layer.
- Module-level `build_prompt(document_text) -> str`, not a method, so tests can
  read it without standing up the service.
- Tolerant JSON parsing with a hard refusal, not a retry — `_parse` returning
  empty on any failure (`entity_definitions.py:183`), and nothing stored on a
  bad reply (`:351`). No retries anywhere in this codebase's model calls; this
  adds none.
- The extraction model, shared, not a second client (`composition.py:1537`).

**Verification, which entity definitions could not do and this can.** `_verified`
in `entity_definitions.py:215` drops citations that do not lie inside a supplied
passage. The same check applies here and is stronger, because there is more to
check against the text than a span: **every member name must occur verbatim in
the document, and the evidence span must contain the class's own justification.**
A member the model invented is dropped before storage. This is the pass's main
defence against a model that pattern-matches a plausible-looking taxonomy onto
a document that does not state one — a failure mode that is otherwise invisible,
since an invented class looks exactly like a discovered one.

### Reading the whole document, not chunks

Discovery reads `CorpusReadPort.read_document(source_id).text` — the same call
`DocumentExtractor.extract` already makes (`document_extraction.py:89`) — and
not the chunk store.

This is not a convenience. **Chunking destroys the strongest signal.** The rank
table's class name lives entirely in its header row, `| Rank | Reward |`, one
line long. A chunk boundary between that header and `| S rank |` leaves the
members in a chunk with no name for what they are members of, and the pass
would be blind to precisely the case it exists for. `corpus_spans.py` prefers
paragraph then sentence boundaries and has no notion of a table, so nothing
prevents it. The enumerating sentence is more robust — it is one sentence — but
the two-level "Versions of Songs" taxonomy spans several paragraphs and has the
same exposure.

The cost is a document-length ceiling. At 4,890 characters the SEKAI document
is comfortable; a 200KB document is not. **Documents above a threshold are
refused by this pass rather than windowed**, with the refusal recorded and
listed by `ungrouped`. A windowed pass with overlap is a real design and it is
deliberately not built here: window boundaries reintroduce the split-table
problem with extra bookkeeping, and no measurement yet says how many documents
in a real corpus exceed the threshold. Take that measurement before building
it.

### The route

`POST /api/projects/{project_id}/sources/{source_id}/ontology` → 202 through
the existing `extract_queue`, matching the extraction route's shape
(`app.py:937`) because it is the same kind of thing: a queued model call a
human waits on.

`GET /api/projects/{project_id}/ontology` returns the classes for a project —
needed by the ontology view in §6 and by anyone checking whether the pass ran.

`POST /api/projects/{project_id}/sources/ontology` sweeps the project's
ungrouped documents, matching `extract_all_sources` (`app.py:865`).

Note for whoever builds it: **all three existing rebuild endpoints are
process-wide** (`/api/summaries/rebuild`, `/api/corpus/rebuild`) and
`EntityDefinitionRunner.rebuild()` is exposed by no route at all. This pass
should not be the one to invent a per-project rebuild convention as a side
effect; if `ontology.rebuild()` needs an endpoint, it takes the process-wide
shape the other two have, and a per-project rebuild is a separate decision.

## 5. How the classes reach the canvas

`ProjectGraphReader` gains a collaborator — the ontology read store — and
`whole`/`neighborhood` join its rows in after `kept` is computed, in the same
place `_inferred_edges` is called (`graph_reader.py:235`, `:290`).

This is a store round trip where `_inferred_edges` was pure, and that is the
honest cost of §1's decision. It is one indexed query per graph read against a
table with a `project_id` index, on a path that already pays
`resolve_entity_ids` plus `get_relationships_for` and, per `find_entities`'s own
docstring, fetches the tenant's entire entity set. It is not free and it is not
the expensive thing on this path.

Each class becomes:

- **A node.** `GraphEntity(entity_id=<synthetic uuid5>, name=<class name>,
  entity_type="class", inferred=True)`.
- **One edge per resolved member**, `relationship_type="instance_of"`,
  `inferred=True`, `derivation=` the quoted evidence sentence.

Three specifics, each of which is a bug if got wrong:

**`instance_of`, not `member_of` or `is_a`.** Both of those exist in
`research_corpus.yaml:118-141` as asserted types, and `member_of` is
person/organization → organization there, which these are not. Reusing an
asserted type is not a correctness bug — the frontend keys on
`…|relationshipType|inferred` (`graph.ts:146`) so the two cannot collide — but a
reader filtering the graph by `is_a` would get a silent mix of what documents
asserted and what this pass judged. `instance_of` appears nowhere in the schema
today; verified against `research_corpus.yaml`.

**`GraphEntity` needs an `inferred: bool = False` field, and this is a frontend
change.** A class node has a synthetic id that no redstring entity has, so
clicking it fires `/graph/entities/{id}/neighborhood` and
`…/definition` against a store that has no such entity — `neighborhood` returns
`None` → 404, and `DefinitionService.define` has nothing to define. The panel
must not issue those fetches for an inferred node. Defaulted, so every existing
construction site and test is unaffected, exactly as `inferred`/`derivation`
were on `GraphRelationship`. **This crosses into the frontend lane and needs
coordinating** — flagged to the team lead rather than assumed.

**The class node must be cap-aware.** `MAX_GRAPH_NODES` is 5,000 and counts
entities; class nodes are not entities and would slip past it, as would their
edges past `MAX_INFERRED_EDGES` if joined in after `_inferred_edges` has already
truncated. Count them against the same caps and fold the verdict into
`inferred_truncated` (`graph_read.py:176-183`). A drawing missing lines looks
exactly like a drawing with none to miss — the note at
`graph_reader.py:66-75` about why the cap's verdict is returned rather than
recomputed from a length applies unchanged.

## 6. The ontology view, and judging whether it is right

**This is a requirement, not a nicety.** Everything this pass produces is a
model judgement, and a model judgement nobody can check is worse than no
judgement — it adds confident-looking structure to a graph whose whole value is
that it came from documents. The test the design has to pass: *a reader who
suspects a class is wrong must be able to settle it without reading the code and
without re-running anything.*

Three things make that possible, and each is a build obligation rather than a
hope.

**Every class opens the sentence it came from.** `evidence_start`/`evidence_end`
are offsets into a document `GET /api/projects/{project_id}/sources/{source_id}`
already serves (`app.py:1038`), and the frontend already has a document reader.
Clicking a class's evidence must open that document scrolled to the span and
highlight it — not merely show the quoted text inline. Quoted text proves the
model wrote a sentence; opening the document proves the sentence is *in the
document*, which is the different and stronger claim. This reuses
`corpus_spans.Span` (`corpus_spans.py:40`) rather than inventing a citation
shape, for the reason its own docstring gives: a citation that survives
re-chunking is one a reader can still follow a month later.

**Every class shows its own arithmetic.** `declared_count` vs `member_count` is
a claim the reader can check against the sentence in front of them — "6 of 6
stated", or a visible "5 of 6 stated" — and `rejected_members` says what
happened to the difference, with the reason each was dropped. A class that found
five of six with no explanation is exactly the case that erodes trust in the
whole feature; a class that says "APPEND — named by the model, not found in the
document" is one the reader can adjudicate in a second.

**Nothing derived is drawn like something asserted.** Class nodes and
`instance_of` edges carry `inferred=True` and reach the canvas through the same
dashed, `--link-inferred` treatment temporal edges already use, and the ontology
view marks classes derived in that same visual language. A class presented like
an asserted fact is precisely the confusion `derivation` exists to prevent
(`graph_read.py:121-128`).

What is deliberately *not* built here is an accept/reject control. Judging that
a class is wrong and recording that judgement are different features; the second
belongs to the judgements mechanism (`domain/judgements.py`), and putting a human
verdict into a derived table is the confusion §9 already rules out. This pass
owes the reader enough to decide — not a place to write the decision down.

Layer 2's payoff is a rendering the graph canvas cannot give, and the reason is
that a force-directed layout has no way to draw *order*. Five `instance_of`
edges into a `Rank` hub are five identical spokes whether or not `kind` is
`ordered_scale`; the ordinal exists in the data and is invisible on the canvas.

So `kind` selects the drawing:

- `ordered_scale` — members in a row, in ordinal order, with the direction the
  text stated ("a rank from S to D").
- `unordered_set` — members in a plain group, deliberately unordered so nobody
  reads a sequence into an alphabetical list.
- `taxonomy` — nested, with the subclass criterion the text gave ("must be
  purchased separately after the base song is obtained") shown on the nesting.

Every class shows its evidence sentence and, when `declared_count` is present,
its checksum — "6 of 6 stated" or a visible "5 of 6 stated". Every class is
marked derived, in the same visual language the dashed inferred edges already
establish; a class presented like an asserted fact is the exact confusion
`derivation` exists to prevent (`graph_read.py:121-128`).

Frontend detail beyond this is deliberately not specified here — that lane is
owned concurrently and this document should not dictate its component shapes.

## 7. Layer 3: schema refinement, and the measurement that should gate it

The precedent is in the YAML's own header (`research_corpus.yaml:1-24`) and it
is exactly this failure solved once before. A `date` entity type existed; the
model obliged and produced 17 date-named entities related to nothing much. The
fix was **two-part and explicitly neither half sufficient**: remove the entity
type *and* tell the prompt where the value belongs instead — "redstring's own
guide is explicit that a schema shapes prompts but does not enforce output", so
removing the type only stops the model being invited, and removing it without
saying where dates go instead would simply lose them.

Applied here, the same two halves:

1. **Structural.** Discovered classes become entity types in a schema, so
   `EASY` extracts as a `difficulty` rather than a `category`.
2. **Prose.** The prompt says where a member of an enumerated set belongs —
   otherwise removing or narrowing `category` loses the members rather than
   classifying them.

**Since no backwards compatibility is required, this is a hard cutover: change
the schema, drop the graph, re-extract.** No migration, no shim, no
dual-vocabulary period. That is the right call for a pre-release project and it
is what makes layer 3 tractable at all.

**The obstacle is that schema selection is global and this ontology is
per-project.** `config.knowledge_domain()` reads `AGENT_KNOWLEDGE_DOMAIN` once
per process (`config.py:207`), resolved at `composition.py:1270`; nothing on the
`Project` aggregate carries a schema id, and there is no per-project override.
Discovered classes are per-project by construction — SEKAI's difficulties have
no business in Ancient Rome's vocabulary — so layer 3 needs a per-project schema
id on `Project`, a generator writing a YAML per project, and `resolve_domain`
reached per project rather than per process. `domain_schemas.py:49` globs
`*.yaml` stems, so a generated file becomes usable with no code change; the
selection path is the work.

**That is the largest single cost in this document, and it should be gated on a
measurement rather than assumed.** The measurement: run layers 1–2 over all
three projects and count classes found per project. If SEKAI yields several and
the other two yield near zero — which the `category` reading in the opening
section predicts, since neither Ancient Rome's occupations nor budgeting's
expense categories are enumerated-with-a-count sets — then per-project schema
machinery is being built for one document, and the honest answer is to defer it
and revisit when a second project produces classes. The measurement costs one
pass over 3 already-extracted corpora and settles it.

Layer 3 is therefore **specified, and recommended to be built third and only
after that count**. Layers 1 and 2 are useful without it: they add structure to
the graph as it stands today and require no re-extraction of anything.

## 8. Tests

The failure shapes these have to distinguish, per `CLAUDE.md`:

- **Assert rows, not status codes.** An event no projection handles counts as
  APPLIED, not rejected — `strict=True` has no opinion about an unsubscribed
  event. A build with `OntologyRunner` never constructed in `composition.py`
  serves every ontology request as an empty 200 and every "the endpoint works"
  test passes. So every test asserts a class row exists with the name, kind and
  ordinal the text stated. This is the entity-definitions failure repeating; it
  is written here because it already happened once.
- **A fixture that has not run the pass.** The entity-definitions 503 was
  invisible to all six of its tests because each one's arrange phase called
  `graphs.open` — the very call the code under test had stopped making. At least
  one test here must issue a graph read for a project whose fixture never
  invoked discovery, or a reader that forgets to open the ontology store is
  undetectable.
- **A class whose `declared_count` disagrees with its members**, asserting the
  class is stored *and* marked incomplete. Both halves: dropping it loses four
  true memberships, and storing it silently is the failure §4 says is worse
  than no class.
- **A model reply naming a member that is not in the document**, asserting the
  member is absent from `ontology_memberships` *and present in*
  `rejected_members` with its reason. Only the first half is a correctness
  test; the second half is what §6 depends on, and an implementation that
  silently drops the member passes the first half alone.
- **An ordered scale whose ordinals are not alphabetical.** `D C B A S` is the
  case. Ordinals matching alphabetical order would also pass under an
  implementation that never read the ordering and sorted the members.
- **A member name that resolves to no entity**, asserting the membership row
  survives with a null `entity_id` and no edge reaches the graph. This is the
  staleness contract and nothing else would catch it.
- **A `DocumentExtracted` for a grouped source**, asserting its classes go
  `stale` and that **no model call is made**. Mark-never-regenerate is the whole
  protection against a bulk re-extraction firing hundreds of paid calls, and an
  exemption that is never checked stops holding silently.
- **A class node counted against the caps**, asserting `inferred_truncated`
  where classes push past `MAX_INFERRED_EDGES`.

Before trusting any of it: delete the ontology join from `whole` and watch the
suite go red. A test that stays green under a deliberate break is evidence
about the fixture.

**Verify the read models against a database that predates them.** New tables are
the safe direction — `CREATE TABLE IF NOT EXISTS` on a database that lacks them
creates them — so the `apply_schema` column-reconciliation hazard does not bite
on the first build. It bites on the *second*, when a field is added to
`OntologyClassRow`. Use
`uv run python -m research_team.infrastructure.persistence.local_copy`, not a
hand copy: a copied database will not open, because every checkpoint's position
token carries the store id derived from the database path.

## 9. Deliberately not built

- **Windowed discovery for long documents.** §4. Refuse above a threshold and
  measure how many real documents exceed it before designing windows.
- **Cross-document classes.** A class is discovered from one document and cited
  to one span. Two documents each stating "six difficulties" produce two
  classes. Merging them is the same identity problem redstring's `Consolidator`
  exists for and should reuse it rather than grow a private version — but not
  until a corpus actually produces the duplicate.
- **A shared ontology across projects.** Per-project by construction (§7).
- **Repairing `category`.** The opening section explains why this is a separate
  defect. Ancient Rome's 116 `category` entities are mostly plural noun phrases
  and no ontology pass discovers a class inside `fullones`.
- **Class-to-class edges beyond `parent_class_id`.** A single nesting pointer
  covers the two-level taxonomy actually observed. Anything richer is a
  vocabulary invented ahead of evidence.
- **Editing a discovered class by hand.** Everything here is derived and
  re-derivable. A human correction would be an asserted fact living in a derived
  table, which is the confusion this whole design is arranged to avoid; it wants
  the judgements mechanism (`domain/judgements.py`), not this one.

## 10. For the user to confirm

1. **The `category` correction (opening section).** Layer 3 does not fix
   `category`; it gives discovered classes a home. Accepting this changes what
   layer 3 is for.
2. **Gating layer 3 on the class-count measurement (§7).** Build 1 and 2, count
   classes across the three projects, then decide on per-project schemas.
3. **`GraphEntity.inferred` is a frontend-visible change (§5)** and needs
   sequencing against the concurrent frontend work.
