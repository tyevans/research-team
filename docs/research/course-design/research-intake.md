# Research Intake: From Unstructured Sources to a Usable Corpus

**Scope.** The other half of "turning unstructured research into real course materials." Every methodology report in this directory — UbD's `SourceCorpusIndex`, Tyler's `SourcedClaimIndex`, ADDIE's `NormalizedClaimSet` / `SourceInventory` — begins from "you have organized source material." This report covers how you get there, and does it against what this repository already has rather than in the abstract.

**Claim marking.** Claims about this repository were verified by reading the files cited. Claims about redstring 0.2.0 were verified by introspecting the installed package (`.venv/lib/python3.13/site-packages/redstring`, version 0.2.0). Everything else is marked **[unverified]** where it is inference rather than something I confirmed in session.

---

## 1. What Exists Today

### 1.1 The ingest path, end to end

Verified by reading the source. The whole path is roughly 700 lines across five files.

```
agent calls remember(text, source_id, note?)
  → knowledge_tools.py:81                    tool wrapper, returns text on failure
  → KnowledgePort.ingest(SourceRef)          application/knowledge.py:79
  → RedstringKnowledge.ingest                infrastructure/knowledge/redstring_adapter.py:104
      guard: source_id non-blank              :105
      guard: len(text) <= 200_000             :107  (MAX_DOCUMENT_CHARS, :48)
      SourceDocument(id, text, metadata)      :117
      async with tenant_scope(project_id)     :123
      build_graph(...)                        :124  chunk → extract → fold into GraphStore
      append report.event to Document stream  :142  DocumentExtracted
      _consolidate(report.event.entities)     :147  per-entity Consolidator.resolve
  → IngestReport                              :155
  → format_ingest → text back to the model   knowledge_tools.py:25
```

**What `remember` extracts.** Not text spans — a graph. `build_graph` runs redstring's `ExtractionPipeline` (default `SlidingWindowChunker`, per the spec at `docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md:216`), and produces a `DocumentExtracted` event carrying `entities: list[Entity]` and `relationships: list[Relationship]`, plus a `domain` and `domain_confidence` from the content classifier.

Verified `Entity` fields (redstring 0.2.0):

```
id, tenant_id, name, normalized_name, entity_type, original_entity_type,
description, source_id, source_text, external_ids, properties,
extraction_method, model, confidence, temporal, blocking_keys
```

Verified `Relationship` fields:

```
id, tenant_id, source_entity_id, target_entity_id,
relationship_type, properties, confidence
```

**What consolidation does.** `_consolidate` (`redstring_adapter.py:165`) loops the extraction's entities and calls `Consolidator.resolve(entity, adjudicator=...)` on each. `resolve` appends *and folds its own* `EntitiesMerged` event — the adapter deliberately does not append it (documented at `redstring_adapter.py:9-18`). An `Adjudicator` over the same LLM provider is passed because without one the middle similarity band is rejected rather than merged (`:83-87`). Failures are counted, not raised: an entity absorbed by an earlier merge in the same loop raises, and that is a normal outcome (`:181-185`).

**What `unmerge` does.** `undo_merge` (`:278`) reverses a consolidation by the `event_id` of its `EntitiesMerged`, which `format_ingest` prints for exactly this reason (`knowledge_tools.py:28-31`). Durable across restart only because the `Consolidator` gets both `event_store` and `snapshot_store` (`:78-82`); `remembers_merges_across_restarts` (`:234`) exists to be asserted in tests.

**What `graph_search` returns.** `Match(entity_id, name, entity_type, relationship_count)` — nothing more. Critically, the search is a **substring match on entity name, in Python, over a full page of the tenant's entities** (`:239-276`). The adapter's own comment says so and flags it as the first thing to revisit behind Neo4j (`:243-247`). It is an entry-point finder, not traversal; `neighbors` is explicitly deferred to a later spec (spec `:288-291`).

**What is project-scoped.** Everything. The project id *is* redstring's `tenant_id` (spec `:70`), supplied once at adapter construction rather than per call, "so nothing above can write into another project's graph" (`redstring_adapter.py:53-56`). Every redstring call runs inside `async with tenant_scope(project_id)`. `KnowledgeAttachment` (`application/knowledge_attachment.py:37`) opens a project's graph at runtime and swaps its tools into the executor, restoring base tools on detach. A session in no project gets no knowledge tools and opens no store (spec `:276-278`).

**Rebuild.** `rebuild_graph` (`infrastructure/knowledge/rebuild.py:37`) folds the log into the store at project open, with `GraphProjection(store, tenant_filter=project_id)`. It takes no provider and the docstring forbids growing one (`:41-44`) — replay purity is the constraint the whole design obeys (spec `:106-110`).

### 1.2 The gaps that still bite

The spec's upstream table (`:341-347`) lists five. Against redstring 0.2.0, here is which ones actually matter for *intake*:

| | Gap | Status | Does it bite intake? |
|---|---|---|---|
| **R1** | No `EmbeddingProvider` port | **Closed in 0.2.0** — `EmbeddingProvider`, `FakeEmbeddingProvider`, `build_graph(embedding_provider=, vector_store=)` all exported (I verified these are present in `dir(redstring)`) | **Not a gap any more — an unbuilt feature.** There is no `AGENT_VECTOR_STORE`, no embedding wiring, no recall path. This is the single biggest intake gap and it is now ours, not upstream's. |
| **R2** | No way to identify unconsolidated entities | Open | Mildly. Repair stays keyed by `source_id` (`redstring_adapter.py:198`). Bounded and working. |
| **R3** | `project()` cannot scope to stream/category/tenant | Open | Yes, at scale. Every project open reads the whole global log and filters in Python. Fine for now; a corpus of hundreds of documents makes it a startup cost. |
| **R4** | `ReplayReport.failed` is a count, and the exception is *discarded* | Open | Yes, and nastily. `rebuild.py:51` refuses a partial graph but literally cannot say which event failed (`rebuild.py:19-21`: "safe and undiagnosable at the same time"). For a large ingested corpus, one poison document bricks project open with an unactionable message. |
| **R5** | eventsource floor understated | **Closed in 0.2.0** | No. |

**Plus the two "asks" at spec `:353-363`, both of which bite intake hard:**

- **No progress callback on `build_graph`.** `remember` is one opaque `await` that chunks, extracts per chunk, and consolidates per entity — described in the spec as "the slowest thing in a turn and the least legible." For a one-off `remember` this is a UX annoyance. **For bulk corpus ingest it is disqualifying** — ingesting forty documents with no progress signal is not a feature anyone will use twice. Note the spec's own observation that closing this needs work on both sides: `build_knowledge_tools` takes no `ActivityReporter`.
- The `project` verb collision, which is cosmetic and already worked around (`rebuild.py:32`).

### 1.3 Three gaps the spec does not list, which I found by reading the code

These are the ones that matter most for course production, and none appear in the upstream table.

**Gap A — the raw text is never persisted. There is no corpus.**

`DocumentExtracted` carries `source_id`, `model_version`, `entities`, `relationships`. It does **not** carry the document text (verified against `DocumentExtracted.model_fields`). `SourceDocument.text` is passed into `build_graph` and dropped. Nothing in `redstring_adapter.py` writes the text anywhere.

So after `remember`, the system holds a graph *about* a document and no copy of the document. `Entity.source_text` retains some originating text per entity **[unverified how much — I did not run an extraction to see what the pipeline populates it with]**, but that is a per-entity fragment, not the source.

**This is the central finding of this report.** Every downstream artifact the other reports demand — quoted spans in Tyler's `SourcedClaimIndex`, provenance citations in ADDIE's storyboard gate, "the citation chain that makes SME review verification rather than proofreading" — requires the source text to still exist and be addressable. Today it does not exist.

**Gap B — no character offsets survive extraction.**

`Chunk` carries `text, chunk_index, start_char, end_char, overlap_with_previous, metadata` (verified). So redstring *computes* offsets during chunking. But `Entity` has `source_id` and `source_text` and no offsets, and `DocumentExtracted` carries entities, not chunks. **The offsets are computed and discarded.**

Consequence: you can say "this entity came from document X" and you may have a text fragment, but you cannot say "characters 4,120-4,380 of document X" — which is what span-level anchoring means and what makes a citation clickable and verifiable.

**Gap C — relationships carry no provenance at all.**

`Relationship` has no `source_id` and no `source_text` (verified above). An entity can point at where it came from; an edge cannot. Since instructional claims are overwhelmingly *relational* ("step B follows step A", "this control mitigates that risk", "this concept enables that skill"), the part of the graph carrying the most instructional content is the part with the least provenance.

**One cheap adjacent finding.** `SourceDocument` accepts `uri`, `title`, and `published_at` (verified). `redstring_adapter.py:117-121` sets only `id`, `text`, and `metadata`. Those three unset fields are exactly the citation fields — URL, title, date. Populating them is a small change to `SourceRef` and the adapter, and it is the cheapest provenance improvement available today.

---

## 2. What "Unstructured Research" Actually Is Here

Mapped against what the current tooling can consume. The honest summary: **`remember` accepts one thing — a string under 200,000 characters that the agent already has in context.** Everything below is a question of how material becomes that string.

| Source type | Can the current path consume it? | What's missing |
|---|---|---|
| **SME interview transcript** | Yes, if someone pastes it in. | No transcription. No speaker/turn structure — it goes in as flat text, so "the SME said X" and "the interviewer suggested X" are indistinguishable after extraction. |
| **Web sources** | Partially. `web_search` (`infrastructure/agent/search.py:74`) returns title/url/snippet only, capped at 5. | **No `fetch` tool.** The spec lists it as out of scope (`:44`) and as the next-most-wanted thing (`:369-370`), noting it "is what gives `remember` substantial content instead of search snippets." Today the agent can find a page and cannot read it. This is the largest concrete hole in web intake. |
| **Existing internal docs (markdown, txt)** | Yes, via the session filesystem, if the agent reads then remembers. | Nothing structural. Works. |
| **PDFs** | No. | No extraction. Needs a text layer, and for real documents an OCR fallback and layout handling (tables, multi-column, headers). |
| **Office docs (docx, pptx, xlsx)** | No. | No converters. Note the irony against the deliverables report: facilitator guides and decks — the highest-value existing source material in an L&D shop — are exactly the formats we cannot read. |
| **Code / repos** | Partially, as text files. | No AST awareness, no repo-scale traversal. **[unverified]** — for a technical curriculum, structure-aware ingest (symbols, call graphs, docstrings) would probably beat flat-text extraction substantially. |
| **Tickets / issue trackers** | No. | No connectors. Yet ticket categories and QA scorecards are precisely ADDIE's gap-analysis evidence. |
| **Recorded sessions (audio/video)** | No. | No transcription pipeline. |
| **Standards / regulatory documents** | Only as text, and poorly. | Clause numbering and hierarchical structure are load-bearing for compliance training, and flat extraction destroys them. |
| **Textbooks** | No, practically. | The 200k cap (`redstring_adapter.py:48`) means a book must be split by hand into parts, "each with its own `source_id`" (`:113-114`). That is a correct guard, but it means document identity fragments across parts and nothing reassembles it. |

**Two structural observations.**

First, the cap is real and the error message is good, but it pushes segmentation onto the caller with no support. **[unverified]** A `source_id` naming convention (`handbook.pdf#part-3`) plus a parent-document record would make split documents recomposable; today they are just separate documents that happen to share a prefix.

Second, and more important: **the current design assumes the agent has already read the material.** `KNOWLEDGE_PROMPT` says it outright — "pass substantial content you have actually read rather than your own summary of it" (`knowledge_tools.py:124-126`). That is a good instruction and a hard ceiling. Corpus construction at course scale means ingesting more material than fits in a context window, which means ingest must become a pipeline the agent *directs* rather than a tool it *calls with a payload*.

---

## 3. Corpus Construction

### 3.1 Can redstring's graph carry claim-level provenance with quoted spans?

**No, not today.** This is the direct answer to the team lead's question, and §1.3 is the evidence:

- Raw text is not persisted (Gap A) — there is nothing for a span to point *into*.
- Offsets are computed at chunking and discarded before the event (Gap B).
- Relationships, which carry most instructional content, have no provenance field at all (Gap C).

`Entity.source_text` is the closest thing, and it is a per-entity fragment with no offset and no guarantee of being a verbatim contiguous span **[unverified — it may be a model-generated summary rather than a quote; worth confirming with a real extraction before relying on it]**.

Current external practice is unambiguous about what is needed: span-based citations rather than document-level, with visible quote boundaries and claim-level attribution where each claim maps to one or more spans, plus freshness and provenance metadata (version, timestamp, source type) ([RankStudio](https://rankstudio.net/articles/en/ai-citation-frameworks), [Tensorlake](https://www.tensorlake.ai/blog/rag-citations)). Anthropic's citations API works by grounding against pre-chunked sources with chunk anchors and re-injecting literal quotes ([RankStudio](https://rankstudio.net/articles/en/ai-citation-frameworks)) — note that this presumes *the chunks are retained and addressable*, which is exactly what we do not do.

There is also a caution worth carrying into the design: **a citation is not the same as support.** Quotes can be accurate and still mislead through context leaks, chunking artifacts, and evaluation shortcuts ([When RAG Citations Still Lie](https://medium.com/@bhagyarana80/when-rag-citations-still-lie-7d289b5ba7cd)). A span anchor makes a claim *checkable*; it does not make it *checked*. That distinction is what the human gate in §4 is for.

### 3.2 Therefore: a corpus store alongside the graph

**Recommendation: build a separate corpus index, and keep the graph as a derived navigational layer over it.** Do not try to make redstring's graph carry spans.

The reasons are structural, not merely expedient:

1. **The graph is lossy by construction and that is its job.** Extraction is a compression from text to entities and edges. Provenance needs the pre-compression artifact. Asking one store to be both the compressed index and the uncompressed record is asking it to not do its job.
2. **The upstream changes required are not ours to make.** Persisting text, threading offsets onto entities, and adding provenance to relationships are three redstring changes. Two of them (offsets, relationship provenance) are schema changes to event payloads. Blocking course production on that is the wrong dependency.
3. **The event log already gives us the right substrate.** The project pattern is established: one SQLite file holds session streams and redstring's (spec `:100-104`). A `SourceDocumentStored` event on a research-team-owned stream, carrying the text and its metadata, fits the existing architecture exactly and adds no new storage system.
4. **It makes the ADDIE report's provenance requirement achievable.** "Every instructional claim traces to a `SourceInventory` entry" needs a durable, addressable record of the source. That is the corpus, not the graph.

**Proposed shape [unverified — design proposal, not a verified pattern]:**

```
SourceDocumentStored          (research-team stream, per project)
  source_id, uri, title, published_at, media_type, sha256,
  text, ingested_at, ingested_by_session, note

SourceChunked
  source_id, chunks: [(chunk_id, start_char, end_char, text_sha)]

ClaimExtracted
  claim_id, claim_text, claim_type,        # step|rule|exception|example|constraint|rationale
  anchors: [(source_id, chunk_id, start_char, end_char, quoted_span)],
  extracted_from_session, confidence
```

`ClaimExtracted` is what Tyler's `SourcedClaimIndex` and ADDIE's `NormalizedClaimSet` actually need, and it is a research-team concept — redstring has no claim type and shouldn't grow one.

The relationship to the graph then becomes clean and stateable: **`remember` keeps doing exactly what it does today**, and the corpus is a parallel record that the same ingest writes first. The graph answers "what is this project about, and what connects to what"; the corpus answers "where exactly did this sentence come from." Both are needed and they are different questions.

### 3.3 Deduplication

Three levels, cheapest first **[unverified — standard practice, not verified in session]**:

1. **Exact** — `sha256` over normalized text. Catches the same PDF uploaded twice, the same doc pasted twice. Nearly free. Should be a hard guard in `remember` today.
2. **Near-duplicate** — MinHash/SimHash shingling. Catches revised SOPs, the same policy in two intranet locations, transcript reprocessing.
3. **Semantic** — embeddings. R1 is closed upstream but nothing here is built. This is where "these two SMEs said the same thing differently" gets detected.

Note that redstring's *consolidation* already dedupes at the **entity** level and does it well — that machinery exists and is adjudicated. What is missing is dedup at the **document** and **claim** levels. These are different problems and entity consolidation does not cover either.

Worth flagging: redstring already has per-`model_version` idempotency at the document level. `redstring_adapter.py:131-140` handles `report.event is None`, meaning "the same content and model version as a previous run" — so re-ingesting an identical document is already a no-op. That is exact-dedup for the *extraction*, but not for the *corpus*, which does not exist yet.

### 3.4 Contradictory sources

The ADDIE report's rule stands and the code has no mechanism for it: **contradictions escalate to a named human; they never auto-resolve.**

What the current path does instead is worse than nothing in one specific way. Consolidation *merges* entities that look like the same thing. If SME A says the escalation threshold is 24 hours and SME B says 48, and both mention "escalation threshold," consolidation will likely merge those entities — silently unifying two contradictory claims into one node. The `unmerge` escape hatch exists (`knowledge_tools.py:100`), and `KNOWLEDGE_PROMPT` tells the agent it "has context the matcher does not" (`:130-133`), but that depends on the agent noticing.

**A `ContradictionLog` needs to be a first-class artifact**, with entries carrying both claims, both span anchors, both source authorities, and an adjudication status (`open` / `resolved-by-<person>` / `both-true-in-different-contexts`). The last value matters more than it looks: in procedural domains, apparent contradictions are frequently unstated conditionals — the expert-blind-spot pattern from the ADDIE report. A contradiction between SMEs is often the *most instructionally valuable* thing in the corpus, because it marks a decision point neither expert articulated.

### 3.5 Source authority

A `SourceInventory` entry needs an authority level, because dedup and contradiction resolution both depend on ranking. **[unverified — proposed ordering]**: signed-off policy/SOP > current system behavior observed directly > SME consensus > single SME > undocumented practice > inferred. Recency is a second axis and can invert the first (a stale SOP loses to current observed behavior). `SourceDocument.published_at` exists and is unset today (§1.3), so half of this is available for free.

---

## 4. Source Quality and Sufficiency: What the Human Actually Reviews

Both the UbD and Tyler reports make "is this the right corpus?" the first human gate. The failure mode to design against is a gate that shows a wall of documents and asks "looks good?" — that is not review, it is assent.

**The gate should present a `CorpusSufficiencyReport` structured as a set of specific, falsifiable claims about the corpus** — the human is checking judgments, not reading source material.

**Coverage — against what?** Not against the source material (circular), but against the *task inventory*. For each task in scope: is there source material covering it, from how many independent sources, at what authority? This produces the useful output:

```
Task 3.2 "Escalate a P1 incident"    ✓ 3 sources (SOP, SME-A, ticket sample)
Task 3.4 "Decide severity level"     ⚠ 1 source (SME-A only) — judgment-heavy, single-sourced
Task 4.1 "Notify affected customers" ✗ NO SOURCE — in scope, nothing covers it
```

The third row is the whole point. **The most valuable thing the intake gate can report is what is missing**, and that is only computable against a task inventory, which means corpus sufficiency cannot be assessed before scope exists. This is a hard ordering constraint on the pipeline: ADDIE's `InScopeTaskSet` (or Tyler's purposes, or UbD's Stage 1) must precede the sufficiency gate, even though it follows initial ingest. Intake is therefore two-pass by necessity: ingest enough to scope, scope, then assess sufficiency against the scope and ingest again.

**What the human reviews, concretely:**

1. **`SourceInventory`** — every source with type, author, date, authority, and coverage. Cheap to scan, and the place where "wait, that policy is from 2019" gets caught.
2. **Coverage matrix** — the table above. Reviewed for the ✗ and ⚠ rows.
3. **`ContradictionLog`** — every unresolved conflict, with both spans quoted. **This is the highest-value screen in the entire pipeline.** It is short, it is specific, it requires exactly the judgment a human has and the system doesn't, and every entry left unresolved becomes a wrong claim in a course.
4. **`ExpertGapFlags`** (from the ADDIE report) — steps where an expert stopped explaining. Also short, also specific, and directly actionable: each one is an interview question (§5).
5. **A sample of extracted claims with their spans** — say 20, sampled across sources and confidence bands, each shown against its quoted source text. This is the calibration check: does extraction actually reflect the sources? Twenty spot-checks tell a reviewer more about corpus quality than reading three documents.
6. **Authority conflicts** — where a low-authority source is the *only* source for an in-scope task.

**What the human should not be shown:** the full corpus, the raw entity list, or the graph. **[unverified but I'd argue strongly]** — a graph visualization is a demo, not a review artifact. Nobody has ever caught a wrong claim by looking at a node-link diagram.

**Sufficiency thresholds** should be advisory and stated, not enforced **[unverified — proposed]**: every in-scope task has ≥1 source; every high-criticality task has ≥2 independent sources; no in-scope task rests solely on inferred material; all contradictions on in-scope tasks are adjudicated. Report against these; let the human proceed anyway with the shortfall recorded. Blocking on thresholds produces gaming; recording shortfalls produces accountability.

---

## 5. The Knowledge Graph's Role

**The team lead asked me to argue this. My position: the graph is a derived, long-lived navigational index over a corpus that outlives any single course — and the corpus, not the graph, is the course pipeline's actual input.**

The argument:

**The graph cannot be the corpus index, because it does not index the corpus.** §1.3 Gap A is decisive: the corpus text isn't stored, so the graph indexes documents that no longer exist in the system. An index into nothing is not an index.

**The graph should not be a per-course artifact, because the tenant boundary is already the project.** This is settled in the code, not open for redesign: project id *is* `tenant_id` (spec `:70`), and it is supplied at adapter construction specifically so nothing above can cross projects (`redstring_adapter.py:53-56`). The team lead's note that a project may outlive any single course is correct and is exactly the right framing — a project is an *organization or domain* boundary ("Acme's compliance training", "the payments platform"), and courses are things you build within it. Second and third courses in a project should inherit the accumulated graph. That is the entire premise of the spec: "The agent researches, and then forgets... session 40 cannot use what session 3 learned" (spec `:5-8`).

**So: three layers, with distinct lifetimes.**

| Layer | Lifetime | Owner | What it answers |
|---|---|---|---|
| **Corpus** (`SourceDocumentStored`, chunks, claims) | Project — append-only, permanent | research-team | "Where exactly did this come from?" |
| **Graph** (entities, relationships, merges) | Project — derived, rebuildable | redstring | "What is this project about? What connects to what? Have we seen this before?" |
| **Course artifacts** (objectives, storyboards, builds) | Course — versioned, replaceable | research-team | "What are we teaching?" |

The graph's genuine value in this arrangement is not as a citation store. It is:

- **Cross-course recall** — the second course in a project starts with the first course's research already digested. This is the compounding asset and the reason the graph is worth having at all.
- **Entity consolidation** — the adjudicated dedup machinery is real, working, and hard to rebuild. It answers "is this new SME talking about the thing we already know as X?"
- **Coverage and gap detection** — a sparsely-connected region of the graph around an in-scope task is a corpus gap signal **[unverified — plausible and worth testing, but I have no evidence graph sparsity correlates with instructional gaps]**.
- **Navigation for the agent** — `graph_search` as an entry-point finder is exactly the right role for it, and it is already what the code does.

**The corollary the team lead should note:** if the graph is derived and the corpus is the source of truth, then losing the graph costs a rebuild, not data — which is already how `rebuild.py` is designed and documented (`:1-6`: "the store is derived, so losing it costs a fold rather than data"). Adding a corpus layer strengthens that property rather than complicating it, because today the *log* is the only copy of anything and the text isn't in it.

---

## 6. SME Interview Support

`ExpertGapFlags` from the ADDIE report is the mechanism, and it needs source material to work on — which is why it belongs here rather than in the analysis phase.

### 6.1 What is detectable

The expert blind spot is well documented: experts "have performed the task so often that some of the steps become so internalized that they fail to acknowledge doing so" ([Foundations of Instructional Design](https://id.rjhogue.name/foundations/chapter/task-analysis-skills-and-knowledge-analysis/), cited in the ADDIE report). The tractable insight is that this leaves *textual signatures* in a transcript:

**[unverified — this is my proposed detection taxonomy, not a validated method. It is the part of this report most worth prototyping before committing to.]**

| Signature | Example | Question it generates |
|---|---|---|
| **Unstated decision criterion** | "then you decide whether to escalate" | "What specifically tells you to escalate versus handle it yourself?" |
| **Abstraction jump** | Step 3 is "configure the routing" between two keystroke-level steps | "Walk me through configuring the routing the way you did steps 2 and 4." |
| **Undefined jargon** | A term used without introduction and never defined in-corpus | "What is a 'soft hold'? Who uses that term?" |
| **Unquantified qualifier** | "if it's taking too long", "when there's a lot of traffic" | "Too long compared to what? What number would make you act?" |
| **Unenumerated exception** | "usually", "normally", "in most cases" | "What are the cases where that isn't true?" |
| **Orphan reference** | A named tool/form/system never explained | "What is the CRT form and when do you fill it in?" |
| **Missing failure branch** | A procedure with no error path | "What happens when that step fails?" |
| **Contradiction** | Two sources disagree | "SME A said 24 hours, the SOP says 48. Which is right, and when?" |

These are lexical and structural patterns, not deep semantics. **That is what makes this the strongest automation candidate in the whole pipeline** — it is a text-analysis job with a well-defined output, and it targets a failure humans miss *by construction* (an ID doesn't know what the expert didn't say; the gap is invisible from inside the conversation).

Current practice is already heading here: AI tools are being used to extract key concepts, identify knowledge gaps, flag contradictions, and surface follow-up areas from recorded SME sessions, reducing hours of synthesis to minutes ([Instructional Design Central](https://www.instructionaldesigncentral.com/post/working-smarter-with-smes-how-ai-is-transforming-the-content-gathering-process)). Also documented: AI expanding question banks with probing follow-ups and reframing questions around performance outcomes rather than knowledge recall — which is Action Mapping discipline applied at the elicitation stage.

### 6.2 What it takes to conduct or draft an interview

**Draft (achievable, and the right v1 target):**

```
corpus + task inventory
  → GapDetection pass                → ExpertGapFlag[] (each: type, source anchor, quoted span)
  → question generation              → SMEInterviewGuide
       grouped by task, ordered, each question carrying the span that provoked it
  → human/ID reviews and edits       ← THE GATE
  → human conducts the interview
  → transcript ingested as a new source, anchored to the flags it answers
  → flags resolve; unanswered flags persist to the next round
```

The load-bearing property is that **each generated question carries the quoted span that provoked it.** That is what makes the guide reviewable — the ID can see "you're asking this because the SME said *'then you decide whether to escalate'* and never said how" and judge whether that's a real gap in one glance. Without the anchor it is a list of plausible questions and the reviewer has no basis to cut any.

Two design details from the practitioner literature worth honoring: the standard interview protocol is **structure first, prose second** — ask the SME to walk the process step by step, captured live, then ask per step what the learner must know and must be able to do ([The eLearning Coach](https://theelearningcoach.com/elearning_design/subject-matter-experts/)). A generated guide should follow that shape rather than being a flat question list. And second-round interviews are qualitatively different from first-round: round one elicits structure, round two closes gaps. A gap-driven guide is inherently a round-two instrument, which means the system should expect at least one human-run round one before it can contribute.

**Conduct (defer, and be careful about it):**

Technically the loop is small — ask, ingest the answer, re-detect, ask the follow-up. **[unverified]** But three things argue against it for v1: SME time is the scarcest resource in any ID project and spending it on an agent that asks a bad follow-up is expensive and reputationally costly; rapport and the ability to notice a hesitation are load-bearing in elicitation and are exactly what an async text interface removes; and an ID conducting the interview *with* a generated guide gets most of the value at a fraction of the risk.

**The middle option worth considering [unverified]:** an async written questionnaire, generated from gap flags, that the SME fills in at their own pace, with answers ingested as sources and follow-ups generated for a subsequent round. This suits SMEs who won't schedule an hour but will answer six specific questions — which is most of them. It also produces a written, attributable, span-anchorable artifact, where a live interview produces a recording someone has to transcribe.

---

## 7. Recommendation: Intake for v1

**Principle: add one layer, change nothing that works.** The graph path is well-built, well-documented, and correctly bounded. The gap is beneath it, not in it.

### 7.1 Build: the corpus layer

The single necessary addition. `SourceDocumentStored` on a research-team-owned stream, per project, carrying `source_id`, `text`, `sha256`, `uri`, `title`, `published_at`, `media_type`, `note`, and ingest attribution. This uses the event-store pattern already established, adds no new storage system, and preserves the "store is derived, log is truth" property that `rebuild.py` depends on.

Ingest ordering follows the existing knowledge-first rule (spec `:129-134`) with one addition: **corpus first, then graph, then session result.** A crash then leaves a stored source with no extraction — repairable by re-extracting, since the text is there. The reverse (extraction with no source) is what we have today and it is unrepairable.

Everything else in §3.2's proposed schema (`SourceChunked`, `ClaimExtracted`) is **deferred until a real course build proves the shape.** Store the text and its hash in v1; spans can be computed later against retained text, which is precisely the property retaining text buys.

### 7.2 Fix cheaply, now

- **Populate `uri`, `title`, `published_at`** on `SourceDocument` (`redstring_adapter.py:117-121`) — three unset fields that are exactly the citation fields. Add them to `SourceRef` (`application/knowledge.py:28`). Smallest provenance win available.
- **sha256 dedup guard in `ingest`** — reject or no-op an identical document. Note redstring already no-ops identical content at the same `model_version` (`:131-140`), so this is about the corpus layer, not the graph.
- **Record `source_id` parentage** for split documents, so a book in five parts is recomposable rather than five unrelated documents.

### 7.3 Build next, in this order

1. **A `fetch` tool.** Already identified as the top follow-on in the spec (`:369-370`) and correctly so. Today `web_search` returns 5 snippets and the agent cannot read a page — web research is effectively unavailable for corpus construction. **This is the highest-value single addition to intake.**
2. **PDF text extraction.** The most common real source format. Text-layer first; OCR later.
3. **Bulk ingest with progress.** Requires the redstring progress callback (spec `:353-359`) *and* threading an `ActivityReporter` into `build_knowledge_tools`, which today takes none. Forty documents behind one opaque `await` is not shippable.
4. **`ExpertGapFlags` detection + `SMEInterviewGuide` drafting.** Highest differentiation, and buildable on retained text alone — no embeddings, no vector store, no upstream changes. §6.1's taxonomy is the spec, and it deserves a prototype against a real transcript before it hardens.
5. **`ContradictionLog` as a first-class reviewable artifact**, with the "both true in different contexts" resolution state.

### 7.4 Defer

- **Vector search / embeddings.** R1 is closed upstream but nothing is built here. It is a feature to spec, not a workaround to remove (spec `:343`). Substring name matching (`redstring_adapter.py:239-276`) is weak but adequate at current scale, and the adapter already flags it as the first thing to revisit.
- **Agent-conducted live SME interviews** (§6.2).
- **Office/audio/video/ticket connectors.**
- **Threading spans into redstring's schema.** Keep spans in the corpus layer where we own them.

### 7.5 The two risks I would flag to the user

**R4 gets worse as the corpus grows.** `rebuild.py:51` refuses to serve a partial graph on any replay failure and — because redstring discards the exception (`rebuild.py:19-21`) — cannot say which event failed. With five documents that is an inconvenience. With a 200-document course corpus, one poison event makes the project unopenable with an unactionable error. **[unverified]** Two mitigations worth considering before that happens: a diagnostic path that replays events one at a time to bisect the failure, or upstream pressure on R4, which the spec already characterizes as the worst of the open gaps.

**R3 makes project open O(entire log).** Every open folds the global feed and filters in Python (`rebuild.py:47`). Course-scale corpora will make startup latency noticeable. The spec notes this is cheaper to close upstream than it first appeared — `GlobalEventFeed.read_all` already accepts `FeedReadOptions(tenant_id=...)` and `project()` simply never passes it (spec `:345`). That is plausibly a small upstream patch with a large payoff, and worth raising before working around it here.

---

## Sources

**Repository files read (all paths relative to `/home/ty/workspace/research-team/`)**
- `research_team/infrastructure/knowledge/redstring_adapter.py`
- `research_team/infrastructure/knowledge/stores.py`
- `research_team/infrastructure/knowledge/rebuild.py`
- `research_team/infrastructure/agent/knowledge_tools.py`
- `research_team/infrastructure/agent/search.py`
- `research_team/application/knowledge.py`
- `research_team/application/knowledge_attachment.py`
- `docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`

**redstring 0.2.0** — field lists verified by introspecting `SourceDocument`, `Entity`, `Relationship`, `Chunk`, and `DocumentExtracted` in `.venv/lib/python3.13/site-packages/redstring`.

**External**
- [RankStudio — LLM Citations Explained: RAG & Source Attribution Methods](https://rankstudio.net/articles/en/ai-citation-frameworks)
- [Tensorlake — Citation-Aware RAG: Fine Grained Citations in Retrieval and Response Synthesis](https://www.tensorlake.ai/blog/rag-citations)
- [When RAG Citations Still Lie](https://medium.com/@bhagyarana80/when-rag-citations-still-lie-7d289b5ba7cd)
- [MDPI — A Systematic Literature Review of Retrieval-Augmented Generation](https://www.mdpi.com/2504-2289/9/12/320)
- [arXiv — Even Small Reasoners Should Quote Their Sources (Pleias-RAG)](https://arxiv.org/pdf/2504.18225)
- [Instructional Design Central — Working Smarter with SMEs: How AI Is Transforming Content Gathering](https://www.instructionaldesigncentral.com/post/working-smarter-with-smes-how-ai-is-transforming-the-content-gathering-process)
- [The eLearning Coach — Your Guide to Doing a SME Interview](https://theelearningcoach.com/elearning_design/subject-matter-experts/)
- [ShiftELearning — How to Pick Your SME's Brain in an Interview](https://www.shiftelearning.com/blog/how-to-pick-your-smes-brain-in-an-interview)
- [Foundations of Instructional Design — Task analysis](https://id.rjhogue.name/foundations/chapter/task-analysis-skills-and-knowledge-analysis/)
