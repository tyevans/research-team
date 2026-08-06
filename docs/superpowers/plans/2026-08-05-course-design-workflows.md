# Course-design workflows implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn unstructured research into real course materials through selectable instructional-design workflows, staged and gated, with every artifact traceable to a source.

**Architecture:** A `Corpus` aggregate retains the source text the graph currently discards, so provenance can be enforced rather than claimed. A workflow is a **preset** — data, not code — naming stages on an eleven-position spine. Stage enforcement is structural: a `StageMiddleware` filters the tools the model can see, and stage folds off the `Project` aggregate at agent-build time because the LangGraph checkpointer is per-turn. Artifacts are markdown files in the event-sourced filesystem, so audit, history, scrubbing and diffing are the existing path.

**Tech Stack:** Python 3.13, `deepagents>=0.7.1`, `langchain` 1.3.x, `eventsource-py[sqlite]>=0.10.0`, `redstring[llm,neo4j]>=0.2.0`, `trafilatura`, pytest, SQLite.

**Spec:** `docs/superpowers/specs/2026-08-05-course-design-workflows-design.md`

**Research:** `docs/research/course-design/` — ten reports. `synthesis-generic-workflow.md` is the backbone; `research-intake.md` governs Phase 1; `deepagents-integration.md` §5 governs Phase 2.

---

## Global constraints

- **Test command:** `uv run pytest`. Lint: `uv run ruff check research_team/ tests/` and `uv run ruff format --check`.
- **No test may touch the network.** Stub transports, as `tests/infrastructure/test_fetch.py` and `test_search.py` do.
- **Adding a field to an existing event requires a default** meaning what its absence meant, plus a case in `tests/infrastructure/test_schema_evolution.py`. This is the documented rule in `research_team/domain/events.py` and it is not optional.
- **`project_id` is a `UUID`**, because it is also redstring's `tenant_id`.
- **`StreamId(aggregate_id, aggregate_type)`** — a `Corpus` may share a UUID with its `Project` and still be a distinct stream. Verify this against `event_store.py:233` before relying on it.
- **No model call at fold time.** Anything a model produced is recorded as an event and replayed, never recomputed.
- **The application layer names no redstring type.** `tests/test_architecture.py` enforces layering; run it.
- **Middleware hooks must be the `a`-prefixed variants.** The default `awrap_model_call` raises `NotImplementedError` under `astream()`, which is what `DeepAgentTurnExecutor._invoke` uses. A sync-only hook fails on the first turn.
- **Docstrings explain *why*, not *what*.** Match the surrounding prose density; this codebase's docstrings carry reasoning and trade-offs, and a summary line restating the signature is a regression.

---

## Phase 1 — The corpus layer

Closes B12, B13, B14. **This phase blocks everything else**: without retained source text, every provenance guarantee in every methodology is unenforceable.

The shape, decided in the spec: the log holds the text, the aggregate holds only an index of it, and a read model serves retrieval. Splitting it that way keeps snapshots small — `SessionSummaryRunner` snapshots every 50 events, and folding whole documents into aggregate state would put entire corpora in every snapshot.

### Task 1.1: The `Corpus` aggregate

**Files:**
- Create: `research_team/domain/corpus.py`
- Modify: `research_team/domain/__init__.py`
- Test: `tests/domain/test_corpus.py`

**Interfaces:**

```python
@register_event
class SourceDocumentStored(DomainEvent):
    aggregate_type: str = "Corpus"
    source_id: str
    text: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None   # ISO date as text; sources lie about formats
    note: str | None = None
    fetched_at: str | None = None

@register_event
class SourceDocumentDropped(DomainEvent):
    aggregate_type: str = "Corpus"
    source_id: str
    reason: str          # required; a drop with no reason is B15's silent-drop failure

class DocumentRecord(BaseModel):
    source_id: str
    sha256: str
    char_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    dropped_reason: str | None = None

class CorpusState(BaseModel):
    corpus_id: UUID
    status: Literal["new", "created"] = "new"
    documents: dict[str, DocumentRecord] = Field(default_factory=dict)
    #: sha256 -> source_id, so a re-ingest of identical bytes is detectable
    by_digest: dict[str, str] = Field(default_factory=dict)
```

**Steps:**
- [ ] Write `tests/domain/test_corpus.py` first. Cover: storing a document records it; state carries metadata but **not** text (assert `"text" not in DocumentRecord.model_fields` — this is the snapshot-size invariant and it must be pinned, not merely intended); re-storing identical bytes under a new `source_id` is detectable via `by_digest`; re-storing the *same* `source_id` with different bytes is legal and supersedes; dropping requires a reason; dropping an unknown `source_id` is rejected; `evolve` is total against an unknown event.
- [ ] Implement `initial_state` / `decide` / `evolve` as three pure functions plus a `Corpus(DeciderAggregate)` shell, mirroring `domain/project.py` exactly.
- [ ] Export from `domain/__init__.py`.
- [ ] `uv run pytest tests/domain/test_corpus.py`

**Note for the implementer:** the creation-event pattern in this codebase is `status: "new" | "created"` with a `case _, State(status="new"): raise` guard near the top of `decide`. Do not invent a different one. Decide deliberately whether a `Corpus` needs an explicit creation event at all, or whether the first `SourceDocumentStored` creates it — and say which in the module docstring, with the reason.

### Task 1.2: The corpus read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_corpus_read_model.py`

The aggregate deliberately does not hold text, so retrieval needs a projection. Follow `SessionSummaryProjection` / `SessionSummaryStore` / `SessionSummaryRunner` — the same three-part shape, for the same reasons.

**Steps:**
- [ ] Tests first: a stored document is retrievable by `(project_id, source_id)`; text round-trips exactly, including newlines and non-ASCII; a dropped document is no longer returned; rebuild from an empty table reproduces the same rows.
- [ ] `CorpusDocumentRow(ReadModel)` with the text column, `CorpusProjection(DeclarativeProjection)`, and a store exposing `get(project_id, source_id)` and `list(project_id)`.
- [ ] Wire into the existing runner rather than adding a second background task if the existing one can carry another projection — check before duplicating. If it cannot, say why in the docstring.
- [ ] `uv run pytest tests/infrastructure/test_corpus_read_model.py`

### Task 1.3: `SourceRef` gains citation fields (B14)

**Files:**
- Modify: `research_team/application/knowledge.py`
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Test: `tests/infrastructure/test_knowledge_adapter.py` (extend)

`redstring_adapter.py:117-121` builds a `SourceDocument` leaving `uri`, `title` and `published_at` unset — exactly the fields a citation needs. They exist on redstring's model and are simply never populated.

**Steps:**
- [ ] Test first: a `SourceRef` carrying `uri`/`title`/`published_at` produces a `SourceDocument` carrying them. Assert against the constructed document, not the report.
- [ ] Add the three optional fields to `SourceRef` and populate them in `ingest`.
- [ ] Verify against the installed redstring that the field names are right — introspect `SourceDocument.model_fields`, do not trust this plan.
- [ ] `uv run pytest tests/infrastructure/`

### Task 1.4: `remember` stores the document before extracting (B12)

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Modify: `research_team/application/knowledge.py` (port, if the signature changes)
- Test: `tests/infrastructure/test_knowledge_adapter.py`

**The load-bearing task in this phase.** Today the text reaches `build_graph` and goes no further.

**Steps:**
- [ ] Test first: after `ingest`, the source text is retrievable from the corpus; a failed extraction does **not** leave a stored document without a graph, or vice versa — decide the ordering and pin it. Recommended: store first, extract second, because a document stored without a graph is repairable by re-extracting and a graph without its document is not.
- [ ] Test: re-ingesting identical bytes does not duplicate the document.
- [ ] Implement. Keep `RedstringKnowledge` the only module importing redstring; the corpus write goes through a port or a collaborator passed in, not through a new redstring call.
- [ ] `uv run pytest tests/`

### Task 1.5: Deterministic chunking and span quoting (B13)

**Files:**
- Create: `research_team/application/corpus_spans.py`
- Test: `tests/application/test_corpus_spans.py`

redstring computes `start_char`/`end_char` during chunking and discards them. Rather than chase that upstream, derive spans ourselves from retained text — deterministic chunking needs no event, because the same text always yields the same spans.

**Interfaces:**

```python
@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str

def chunk(text: str, *, target_chars: int = 1200, overlap: int = 0) -> list[Span]: ...
def quote(text: str, start: int, end: int, *, context: int = 0) -> Span: ...
```

**Steps:**
- [ ] Tests first, and make them properties where they are properties — use `hypothesis`, which is already a dev dependency: for any text and any chunking, concatenating chunk texts in order reproduces the original exactly (with `overlap=0`); every chunk's `text` equals `text[start:end]`; spans are non-overlapping and ordered; `quote` out of range is clamped rather than raising.
- [ ] Chunk on paragraph then sentence boundaries, falling back to a hard split — never mid-word if avoidable.
- [ ] `uv run pytest tests/application/test_corpus_spans.py`

### Task 1.6: The `read_source` tool

**Files:**
- Create: `research_team/infrastructure/agent/corpus_tools.py`
- Modify: `research_team/application/autonomy.py` (tool name constant)
- Test: `tests/infrastructure/test_corpus_tools.py`

A retained corpus nothing can read is not worth retaining. Two read-only tools: `list_sources()` and `read_source(source_id, start=None, end=None)`.

**Steps:**
- [ ] Tests first, including: reading a range returns exactly that span with its offsets, so the agent can cite `source_id@start-end`; an unknown `source_id` returns prose naming what is available rather than raising.
- [ ] Read-only, so **not** in `GATED_TOOLS` — the existing rule is that read tools are ungated because gating them trains people to click through approvals without reading them.
- [ ] Write a `CORPUS_PROMPT` in the house style: what the tool is for, and the one rule that matters — a claim written into a course artifact carries `source_id` and offsets, or it is marked as inferred.
- [ ] `uv run pytest tests/infrastructure/test_corpus_tools.py`

### Task 1.7: Composition wiring and a corpus listing endpoint

**Files:**
- Modify: `research_team/composition.py`
- Modify: `research_team/interfaces/web/app.py`
- Test: `tests/interfaces/test_web.py`, `tests/integration/`

**Steps:**
- [ ] Corpus tools are registered when a project is attached, alongside the knowledge tools — same lifetime, same reason. Extend `KnowledgeAttachment` rather than adding a parallel attachment.
- [ ] `GET /api/projects/{project_id}/sources` listing stored documents (metadata only, never text in the list).
- [ ] `GET /api/projects/{project_id}/sources/{source_id}` returning text.
- [ ] Tests over ASGI, following `tests/interfaces/test_web.py`'s existing shape.
- [ ] Full suite green, ruff clean.

**→ CHECKPOINT: open a PR.** Title: `feat: a corpus layer, so a claim can name its source`. Body must state plainly that this closes B12/B13/B14 and delete those entries from `BACKLOG.md` (the file says closed entries are deleted, not ticked).

---

## Phase 2 — Workflow engine, step 1

Makes workflows usable with **no new UI components**. Everything here renders through surfaces that already exist.

### Task 2.1: Presets as data

**Files:**
- Create: `research_team/domain/workflow.py` (spine positions, stage and preset shapes)
- Create: `research_team/workflows/` (the preset definitions themselves)
- Test: `tests/domain/test_workflow.py`

**Steps:**
- [ ] Define `SpinePosition` (0–10), `StageKind` (`generate`, `screen`, `produce`, `decide`, `field`, `custom`), `Stage`, `Preset`.
- [ ] A `Stage` declares: `id`, `name`, `spine`, `kind`, `inputs`, `outputs`, `tools`, `generator_prompt`, `critic_prompt`, `checks`, `gate`, `amendments.emits_to`.
- [ ] Ship three presets to start: `hybrid.default`, `ubd.pure`, `addie.pure`. Tyler and per-phase override come later.
- [ ] Validation, tested: every `inputs` artifact type is some earlier stage's `outputs`; `amendments.emits_to` names a real earlier stage; `screen` stages have a `criterion_doc` and no generator; a preset declares its `spine_positions` and they match its stages; a preset terminating before position 8 is marked as producing a design rather than materials.
- [ ] `uv run pytest tests/domain/test_workflow.py`

### Task 2.2: Workflow events on `Project`

**Files:**
- Modify: `research_team/domain/project.py`
- Test: `tests/domain/test_project.py` (extend)

**Steps:**
- [ ] `WorkflowSelected(preset_id, preset_version)` and `StageAdvanced(from_stage, to_stage, decided_by, gate_decision)`.
- [ ] `ProjectState` gains `preset_id`, `preset_version`, `current_stage`, `stage_history`.
- [ ] Rules, tested: selecting a workflow twice is rejected naming the current preset; advancing to a stage not in the preset is rejected; advancing out of order is rejected; a deleted project rejects both (the `status="deleted"` guard already sits above everything else — keep it there).
- [ ] Schema-evolution case for the new `ProjectState` fields.
- [ ] `uv run pytest tests/domain/`

### Task 2.3: `StageMiddleware`

**Files:**
- Create: `research_team/infrastructure/agent/stage_middleware.py`
- Test: `tests/infrastructure/test_stage_middleware.py`

**The one with real API hazards.** `docs/research/course-design/deepagents-integration.md` §5 is verified against langchain 1.3.14 — read it before writing this.

**Steps:**
- [ ] Implement `awrap_model_call`, **not** `wrap_model_call`.
- [ ] Use `request.override(...)` and pass the result to `handler()` — it is immutable and returns a new request.
- [ ] **Append** the stage prompt to `request.system_message`; do not replace it. A future Anthropic model resolves a harness profile whose content wholesale replacement would discard.
- [ ] Filter `request.tools` **down only**. The executor registers the union of all stage tools once; adding a tool not registered at creation raises. `request.tools` already contains the deepagents built-ins, so the filter is a denylist over stage-specific tools plus an always-allowed core (`read_file`, `write_file`, `edit_file`, `ls`, `task`).
- [ ] Tests: a tool outside the stage is not in what reaches the model; built-ins survive; the stage prompt is appended not substituted; a sync-only implementation would fail (assert the async hook is the one defined).
- [ ] `uv run pytest tests/infrastructure/test_stage_middleware.py`

### Task 2.4: `advance_stage`, gated

**Files:**
- Create/modify: `research_team/infrastructure/agent/workflow_tools.py`
- Modify: `research_team/application/autonomy.py`
- Test: `tests/infrastructure/test_workflow_tools.py`

**Steps:**
- [ ] `advance_stage(rationale)` executes the domain command and returns prose.
- [ ] Add to `GATED_TOOLS` with a floor of `ask` via `TOOL_FLOORS` — advancing a stage is exactly the human gate, and this reuses the whole existing approval and SSE path for free.
- [ ] Test that it is gated and that a rejected advance leaves `current_stage` unchanged.

### Task 2.5: Executor and composition wiring

**Files:**
- Modify: `research_team/infrastructure/agent/deep_agent.py`, `research_team/composition.py`
- Test: `tests/infrastructure/test_deep_agent.py`, `tests/integration/`

**Steps:**
- [ ] `DeepAgentTurnExecutor` accepts `middleware: Sequence[AgentMiddleware] = ()` and passes it to `create_deep_agent`. It rebuilds the agent every turn already, so stage is read fresh each time.
- [ ] Stage is folded from `ProjectState` at agent-build time and handed to the middleware constructor. **It cannot come from graph state** — `MemorySaver()` is constructed inline per `_invoke` and `thread_id` embeds `turn_index`.
- [ ] Test that `to_activity_delta` still filters correctly: middleware nodes are named `f"{name}.before_model"`, never `"model"`, so streaming should be unaffected — pin it rather than assume it.
- [ ] `uv run pytest tests/`

### Task 2.6: Web surface

**Files:**
- Modify: `research_team/interfaces/web/app.py`, `presenters.py`, `static/app.js`, `static/index.html`
- Test: `tests/interfaces/test_web.py`

**Steps:**
- [ ] `GET /api/workflows` (static preset list: id, name, what it produces, where it terminates).
- [ ] `POST /api/projects/{id}/workflow` with a `WorkflowChoice` body; `GET` returns current preset and stage. Follow the existing `NewSession`/`JoinOptions` conventions.
- [ ] `project_view` gains `workflow` and `stage`.
- [ ] One `isinstance` branch in `event_summary` so stage transitions appear in the timeline.
- [ ] A `<select>` beside the existing project-name input, and a chip in the project row. **No new pane** — that is Phase 3's stage rail.
- [ ] Note: this file has in-flight changes from other work. Rebase rather than assume.

### Task 2.7: Artifacts on disk

**Files:**
- Modify: preset definitions; add prompt guidance
- Test: `tests/integration/`

**Steps:**
- [ ] Stage outputs are written to `/course/NN-<artifact>.md` with typed frontmatter, `NN` matching stage order so lexical order matches stage order.
- [ ] Frontmatter carries `artifact_type`, `stage`, `preset`, and `provenance` (source ids and spans, or `inferred_not_in_source: true`).
- [ ] An integration test driving a fake model through two stages, asserting the files land with valid frontmatter.

**→ CHECKPOINT: open a PR.** Title: `feat: selectable course-design workflows, staged and gated`.

---

## Phase 3 — The check library and coverage matrix

Where most of the value sits, and it needs no model calls.

### Task 3.1: Check primitives

**Files:** create `research_team/application/checks.py`; test `tests/application/test_checks.py`

- [ ] Implement as parameterized queries over artifacts: `coverage`, `orphan`, `matrix_density`, `provenance`, `budget`, `format_conformance`, `taxonomy_distribution`, `vocabulary_coverage`, `exclusion_ledger`, `verdict_citation`, `self_review_separation`, `prune_ratio`, `required_field_nondegenerate`, `recurrence`, `ordering`, `prerequisite_satisfied`, `source_starvation`, `contradiction_escalation`.
- [ ] Namespaced registry: `shared.*`, `ubd.*`, `tyler.*`, `addie.*`. Presets bind checks; the engine does not know which are which.
- [ ] Every check returns findings — `{check, severity, message, affected_artifact_ids, suggested_edit}` — never a score. UbD's peer review produces commentary, and a numeric aggregate would change the artifact into something practitioners do not use.
- [ ] Property-test the generic ones with hypothesis.

### Task 3.2: `CoverageMatrix` with typed axes

**Files:** `research_team/application/coverage.py`; test `tests/application/test_coverage.py`

- [ ] Typed axes (`{artifact_type, subtype}` or `{attribute_path}`), supporting both intrinsic matrices (two attributes of one artifact type, as Tyler's behavior × content) and relational ones (two types joined by an edge, as UbD's Code columns and ADDIE's blueprint).
- [ ] `matrix_density` subsumes `coverage` and `orphan` when the artifact is a matrix: empty row = uncovered intent, empty column = orphan.
- [ ] Render as a markdown table — the existing viewer already renders tables, which is why this needs no UI work.

### Task 3.3: Wire checks to stage exit

- [ ] A stage's declared checks run on exit; findings are written as an artifact and attached to the gate's `context`.
- [ ] `self_review_separation` and `verdict_citation` are **harness invariants**, enforced rather than requested in a prompt: both fail silently and neither is visible in the output.

**→ CHECKPOINT: open a PR.**

---

## Deliberately not in this plan

Recorded in `BACKLOG.md` (B17–B19) or the spec's deferred section: authentication and the author/learner boundary, the publication mechanism, redaction in an append-only log, item banks and pointer components, LMS packaging, learner state and grading, durable cross-session gates, and markdown components (which come after the engine works, starting with `rubric` and `scenario` from UbD Stage 2 and `mcq`/`cloze` from Tyler's evaluation step).

**One judgement to preserve throughout:** the pipeline is structurally biased toward producing its own output. A human must be able to answer *"no course"* at the intake gate, and `halt` must remain available on `decide` gates in every preset — including the two methodologies whose own traditions lack it.
