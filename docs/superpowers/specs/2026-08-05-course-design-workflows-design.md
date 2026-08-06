# Course-design workflows

## The problem

The agent researches well and produces prose. Someone turning that research into
a course has to do the instructional design themselves, in their head, with no
structure and no record of what was decided or discarded.

Instructional design has been a discipline for seventy-five years and has three
canonical process models — Ralph Tyler's rationale (1949), ADDIE (1975), and
Wiggins & McTighe's Understanding by Design (1998). Each is a sequence of stages
with named artifacts, quality criteria, and human review points. That shape is
close enough to what this codebase already does — staged agent work, files as
events, gated tool calls, a human watching a stream — that the integration is
mostly a question of choosing boundaries carefully.

This spec covers a **workflow engine**: selectable, data-driven course-design
processes a user picks per project, that run against a research corpus and emit
reviewable course materials as files.

Five research reports back this design and are cited throughout. They live in
[`docs/research/course-design/`](../../research/course-design/). Where this spec
disagrees with them, it says so.

## What the research changed about the plan

Three findings reshaped the design before it was written. Recording them because
each one closed off an approach that looked obviously right beforehand.

**There is no corpus.** `DocumentExtracted` carries entities and relationships
and no text; `redstring_adapter.py:117` builds a `SourceDocument`, passes it to
`build_graph`, and drops the text. After `remember`, the system holds a graph
*about* a document and no copy of the document. Every methodology's provenance
machinery — Tyler's quoted spans, ADDIE's storyboard citation gate, UbD's
`inferred_not_in_source` flag — needs the source text to still exist and be
addressable. A corpus layer is therefore a **prerequisite**, not a feature of
this work. See [Prerequisites](#prerequisites).

**The three methodologies are not alternatives.** They are strong in
complementary places and each has a structural hole where another has machinery.
Tyler owns corpus-to-objectives and has no production phase at all. UbD owns
evidence-and-experience design and its front end accepts one input (a standards
document). ADDIE owns production, delivery, and outcome measurement and has **no
value filter whatsoever**. A user who picks one methodology inherits its defect,
and choosing which defect to tolerate is exactly the expertise they are using
the tool to avoid needing. So the default is a hybrid, and pure modes exist for
users with a conformance requirement rather than a preference.

**Stage state cannot live in the graph.** `DeepAgentTurnExecutor._invoke`
constructs `MemorySaver()` inline per turn and embeds `turn_index` in the
`thread_id`, so nothing in LangGraph state survives a turn. Stage must be
reconstructed from the event log at agent-build time. This is the right answer
rather than a workaround: it keeps the event log as the single source of truth
instead of introducing a durable checkpointer alongside it.

## Scope

In scope:

- **The spine** — an eleven-position model of course design that all three
  methodologies map onto, and the vocabulary the engine is built in.
- **Presets** — workflow definitions as data: which stages, in what order, with
  which checks, gates, and criterion documents.
- **`StageMiddleware`** — stage enforcement by tool visibility, in a
  `deepagents` middleware.
- **Workflow events on `Project`** — `WorkflowSelected`, `StageAdvanced`, and
  the fold that reconstructs stage at agent-build time.
- **The check library** — automated checks as graph and schema queries, no
  model call.
- **Gates** — five kinds, carried on the existing approval machinery.
- **Course artifacts** — canonical artifact types written as markdown files with
  typed frontmatter, plus the per-block `audience` primitive.
- **Markdown components** — `component:<type>` fenced blocks with YAML bodies,
  and the author/learner projection.

Out of scope, each for a stated reason:

- **The corpus layer itself.** A prerequisite with its own spec — see below.
- **A `fetch` tool.** Also a prerequisite; `web_search` returns five snippets
  and the agent cannot read a page, so web research is effectively unavailable
  for corpus construction today.
- **Authentication, users, RBAC, and any real author/learner boundary.** There
  is no user system. Recorded in `BACKLOG.md` rather than designed here.
- **Item banks and pointer components.** Deferred with a migration path, not
  rejected — see [Components](#markdown-components-are-inline-and-server-projected).
- **LMS packaging** — SCORM, cmi5, xAPI, QTI, Common Cartridge, LTI. Every one
  is a lossy compile target for a source format that has to exist anyway.
  Nobody authors in SCORM, so the source question is settled independent of
  export.
- **Learner state, grading, and spaced repetition.** Needs a learner principal.
- **Field gates as a workflow that waits.** The engine marks them unsatisfied;
  it does not schedule or collect real-learner evidence.

## Decisions

### The engine is built on a spine, not on three pipelines

All three methodologies reduce to the same eleven positions. Not every
methodology occupies every position, and that is the point rather than a defect
in the mapping.

```
 [0] CORPUS INTAKE        raw material → routed, provenance-tagged claims
 [1] CONTEXT FRAMING      audience, constraints, time budget, purpose
 [2] CANDIDATE GENERATION deliberately over-large pool of learning intents
 [3] FILTERING            candidate pool → surviving set + exclusion ledger
 [4] INTENT SPECIFICATION survivors → typed, formatted, provenanced objectives
 [5] EVIDENCE DESIGN      intents → assessments, tasks, instruments, criteria
 [6] EXPERIENCE DESIGN    intents + evidence → learner-facing activities
 [7] ORGANIZATION         experiences → sequence, threads, chunks, calendar
 [8] PRODUCTION           specs → built materials at rising fidelity
 [9] DELIVERY             built materials → deployed, supported, staffed
[10] OUTCOME EVIDENCE     real results → localized revision proposals
```

A preset declares which positions it occupies. `ubd.pure` occupies [0,1,4,5,6,7]
and terminates at a unit plan; `hybrid.default` occupies all eleven.

The alternative — three hand-written pipelines sharing utilities — was rejected
because the reports found the overlap is not incidental. Fourteen of the
nineteen automated checks are shared, the artifact vocabulary collapses to
twenty-two canonical types, and the apparently methodology-specific checks
mostly turn out to be generics with different parameters: ADDIE's
unobservable-verb rejection is `format_conformance` with a denylist, Tyler's
grid diagnostics are `matrix_density`, UbD's transfer-needs-a-performance-task
rule is `coverage` with a subtype filter. Three pipelines would reimplement that
core three times and drift.

### False friends are recorded in the preset definitions, not left to inference

Several stage pairs look aligned by name and are not. These are written into the
mapping tables explicitly because getting one wrong produces a pipeline that
fails in a way that looks like a model quality problem.

| Looks like a match | Actually |
|---|---|
| ADDIE "Design" ≈ UbD "Stage 1" | ADDIE Design spans [4]–[8-prep] and contains all three UbD stages plus storyboarding. UbD Stage 1 is [4] alone. |
| ADDIE "Evaluation" ≈ Tyler Q4 "Evaluation" | **The worst one.** Tyler's Q4 is instrument design at [5]. ADDIE's E is Kirkpatrick program evaluation at [10]. Mapping them moves assessment design to the end of the pipeline — precisely the failure UbD exists to prevent. |
| UbD "Stage 2" ≈ ADDIE "Evaluation" | Same error from the other side. Stage 2 is design-time [5]; ADDIE E is run-time [10]. |
| ADDIE "formative evaluation" ≈ UbD's **E** in WHERETO | Opposite directions. One is feedback on the design; the other is feedback to the learner, designed into the course. |
| Tyler "Screen 2" ≈ ADDIE "learner analysis" | Screen 2 is a filter over candidates producing per-item verdicts. Learner analysis is an input document. One is a stage kind, the other an artifact. |

### The default preset is a hybrid, and the UI names its composition

`hybrid.default` is the default and is described to the user as what it is —
"Tyler's sourcing, UbD's evidence-first design, ADDIE's production" — rather
than presented as a neutral house process.

```
[0-1]  Tyler corpus intake + three-source routing         ← best provenance discipline
[2-3]  Tyler candidate pool → Screen 1 → Screen 2         ← the only real value filter
[4]    Tyler behavior+content spec, UbD intent subtypes   ← both, per subtype
[5]    UbD Stage 2: GRASPS, evidence before activities    ← the key inversion
[6-7]  UbD Stage 3 with A/M/T, Tyler continuity/sequence escalation
[8-9]  ADDIE storyboard → Alpha/Beta/Gold → deployment    ← the only production half
[10]   Tyler ≥2-time-point + defect localization, ADDIE Kirkpatrick
```

Every graft closes a documented hole in the methodology it lands on. None is
speculative — each is a mechanism one tradition has and another lacks.

Pure presets exist for one specific and legitimate reason: **in some contexts the
process trail is itself the deliverable.** A regulated team must show ADDIE phase
sign-offs; an accreditation review expects Tyler-shaped outcome maps; a district
adopting UbD wants Template 2.0. That is a conformance requirement, not an
aesthetic preference, and a hybrid that produces better courses with the wrong
paperwork fails those users.

Per-phase override is exposed but is not the default. Choosing Tyler for
analysis and UbD for design is exactly right and requires the user to hold the
synthesis in their head.

**No methodology-picker as the first screen.** The choice is only meaningful to
someone who has read all three research reports. Selection is driven by asking
what the user is producing and under what constraints — a unit plan or finished
materials, whether there is a conformance requirement, and **whether a written
statement of what this program is for already exists**. That last question
decides whether Tyler's Screen 1 is usable at all: a `PhilosophyStatement` that
does not exist cannot be faked, and a vague one yields a screen that passes
everything while appearing to work. That is the worst failure mode in the system
precisely because it is invisible.

A preset that terminates before [8] says so on the artifact. Silently producing
less than the user expected is worse than an up-front scope statement.

### Workflow binds to the `Project`, by an explicit event

Not to a session, and not at project creation.

A project already has exactly the right lifetime: sequential, one holder at a
time, a filesystem lineage via tip-forking, spanning many sessions. But
`POST /api/projects` is the wrong moment, because it would commit to a
methodology before any research exists — and the corpus is what the choice
should be made against.

Two new `Project` events:

```python
@register_event
class WorkflowSelected(DomainEvent):
    aggregate_type: str = "Project"
    preset_id: str
    preset_version: str

@register_event
class StageAdvanced(DomainEvent):
    aggregate_type: str = "Project"
    from_stage: str | None
    to_stage: str
    decided_by: Literal["agent", "human"]
    gate_decision: dict | None
```

`ProjectState` gains `preset_id`, `preset_version`, `current_stage`, and
`stage_history`. Changing methodology mid-run is rejected by `decide`, naming
the current preset — fork or a new project is the escape hatch, consistent with
how `JoinProject` already refuses a held project by naming its holder.

This also happens to be the reconstruction source the middleware needs, which is
what makes the whole design cheap: `start_in_project` forks the filesystem from
the tip but deliberately does not carry the conversation, so a per-session
record of stage would be lost exactly when a workflow spans sessions.

### Stage enforcement is structural, by tool visibility

A stage instruction in a prompt is a request. A tool the model cannot see is one
it cannot call.

`StageMiddleware` is an `AgentMiddleware` (from `langchain.agents.middleware`,
not deepagents) that on each model call appends the stage prompt to the existing
system message and filters `request.tools` down to the stage's allowed set.

Four API facts constrain the implementation, all verified against langchain
1.3.14 rather than assumed:

- **It must implement `awrap_model_call`, not `wrap_model_call`.** The default
  async body raises `NotImplementedError` (`types.py:625`) with a message naming
  exactly this case — a sync-only hook under `astream()`. `_invoke` streams, so
  a sync-only implementation fails on the first turn.
- **Use `request.override(**kwargs)`**, which is immutable and returns a new
  request that must be passed to `handler()`. Direct assignment works but emits
  a `DeprecationWarning` per field.
- **Filtering down is safe; adding is not.** Overriding `tools` genuinely
  changes the bind (`factory.py:1349` → `1367`), but a tool not registered at
  agent creation raises. So the executor registers the **union of all stage
  tools** once and the middleware hides per stage.
- **`request.tools` already contains the deepagents built-ins** by the time
  middleware sees it. A naive allowlist would strip `read_file`, `write_file`,
  and `task`. The filter is a denylist over stage-specific tools plus an
  always-allowed core.

Composition with the existing approval path is clean and needs no changes:
deepagents installs `HumanInTheLoopMiddleware` in the tail, so stage filtering
runs first and HITL gates whatever survives. Hidden tools never reach the
interrupt config; gated visible tools interrupt exactly as they do today. And
middleware graph nodes are named `f"{name}.before_model"`, never `"model"`, so
`to_activity_delta`'s `MAIN_AGENT_NODE` discriminator is unaffected.

Stage is passed into the middleware constructor from the folded `ProjectState`
at agent-build time, since `_invoke` rebuilds the agent every turn anyway.

The rejected alternative was a LangGraph state machine around or instead of the
deep agent. It is the right shape for a pipeline product and the wrong one here:
it breaks the `TurnExecutor` contract and forces a durable checkpointer
alongside the event log, which is two sources of truth for the same run.

### Artifacts are files; the canonical vocabulary is typed frontmatter

Stage artifacts are markdown files in the event-sourced virtual filesystem, at
`/course/NN-<artifact>.md`. The `NN-` prefix makes lexical order match stage
order, which is the whole of what the existing alphabetical file list needs to
become useful.

This means persistence, audit, history, scrubbing, and diffing are the existing
event-sourced path with no new machinery. It also means an artifact is readable
by `cat`, by a diff, by a reviewer, and by the agent's own next turn.

Twenty-two canonical types carry the shared vocabulary — `SourceClaim`,
`ContextProfile`, `CriterionDocument`, `Intent`, `VerdictLedger`, `Exclusion`,
`EvidenceSpec`, `Rubric`, `Experience`, `Sequence`, `CoverageMatrix`,
`RiskRegister`, `EvaluationPlan`, `RevisionProposal`, and others. Methodology
idiosyncrasy lives in an `extensions` map with a `schema_ref` into `ext/`:
GRASPS, A/M/T coding, WHERETO annotations, Tyler's escalation descriptors,
ADDIE's task-analysis trees.

Three canonicalizations carry most of the value:

1. **`CoverageMatrix`** with *typed axes*. Tyler's behavior×content grid, UbD's
   Code columns, and ADDIE's assessment blueprint are the same artifact with
   different axes. Typed axes let one implementation serve both intrinsic
   matrices (two attributes of one type) and relational ones (two types joined
   by an edge), and every coverage, orphan, and density check becomes one
   implementation.
2. **`Exclusion`.** All three traditions independently produce a cut list, and
   all three research reports independently concluded that **reviewing what was
   excluded is more informative than reviewing what was kept**. Convergence from
   three unrelated traditions is strong evidence this belongs in the canonical
   set. Exclusions carry a mandatory reason, a citation, and a reversal path.
3. **`CriterionDocument`.** Tyler's philosophy and learning-theory statements
   and UbD's Design Standards are the same kind of thing — an authored,
   versioned, human-signed document a critic must cite. Unifying the container
   gives one harness rule, *uncited verdicts are invalid*, which hardens all
   three methodologies at once.

Renderers are decoupled from artifacts. UbD Template 2.0, the ADDIE Course
Design Document, and Tyler's grid are **views** over canonical artifacts, not
storage formats. This is what lets a hybrid run emit conformant paperwork, and
it is why conformance of output and conformance of process are separable.

### Checks are queries; the registry is namespaced

Every automated check is a graph or schema query over artifacts. None requires a
model call, which is what makes them cheap enough to run on every stage exit and
trustworthy enough to gate on.

Shared: `coverage`, `orphan`, `matrix_density`, `provenance`, `budget`,
`format_conformance`, `taxonomy_distribution`, `vocabulary_coverage`,
`exclusion_ledger`, `verdict_citation`, `self_review_separation`,
`contradiction_escalation`, `prune_ratio`, `required_field_nondegenerate`,
`recurrence`, `ordering`, `prerequisite_satisfied`, `source_starvation`.

Namespaced `shared.*`, `ubd.*`, `tyler.*`, `addie.*`. Presets bind checks; the
engine does not know which are which.

Two invariants are enforced by the harness rather than requested in prompts,
because both fail silently and neither is visible in the output:

- **`self_review_separation`** — the critic for a stage must not be the
  generator. Self-screening yields near-100% pass rates.
- **`verdict_citation`** — a screen or review verdict must cite a clause of a
  `CriterionDocument`. Uncited verdicts are rejected by the harness. Run the
  screen with criterion clauses as retrieval targets so a verdict that cannot
  retrieve a relevant clause is forced to `contested` rather than inventing a
  justification.

One check is deliberately **not** automatable and is recorded as such:
`uncoverage`, UbD's discriminator for whether an understanding is genuinely
worth uncovering. A model will generate fluent platitudes and rate them highly.
It is a human gate with no automated substitute.

`expert_gap_flag` is the one high-value check that requires a model call —
detecting where an expert stopped explaining, via unstated decision criteria,
abstraction jumps, undefined jargon, unquantified qualifiers, unenumerated
exceptions. It is the one place automation plausibly beats human practice, since
the expert blind spot is well-attested and humans miss it by construction. Each
generated question carries the quoted span that provoked it, which is what makes
the output reviewable at a glance rather than a list of plausible questions with
no basis to cut any.

### Five gate kinds, on the existing approval machinery

Gates are genuinely different in what the human sees and what they can return.
This is not one gate with a flag.

| Kind | Shown | Decisions |
|---|---|---|
| `rubric` | An artifact set plus critic findings against a `CriterionDocument` | approve, approve_with_edits, amend_upstream, send_back |
| `ledger` | Per-item verdicts, **rejections first and in full**, retains sampled | approve, approve_with_edits, send_back |
| `maturity` | The same artifact at a higher rung, permitted change scope declared and narrowing | approve, approve_with_edits (alpha only), send_back |
| `decision` | A recommendation plus its adversarial counter-case | approve, send_back, **halt** |
| `field` | Evidence from real humans outside the pipeline | approve, send_back |

The existing park-announce-resolve machinery (`WebApprovals.decide`,
`approvals.py:66`) is reused. It is the expensive correct part, and a parallel
blocking path would double the ways a turn can hang. Three narrow extensions:

- an optional `context: dict` on `ApprovalRequest`, `None` for ordinary tool
  gates, carrying artifact paths, findings, and the exclusion ledger;
- `halt` added to the decision vocabulary;
- a gate-shaped branch in `renderApprovals`.

**`approve_with_edits` does not go through `edited_args`.** A reviewer editing a
markdown artifact edits the file — producing `FileEdited` with recorded intent —
and then approves. Routing it through the approval payload would make the edit
invisible to file history, which is the one place edits are supposed to be
auditable. The recorded delta between machine output and human-corrected output
is also the best available signal for which stages need better prompts.

Three review cultures are preserved rather than flattened:

- **UbD's peer review produces commentary, never a score.** The Design Standards
  are consider-questions. No numeric aggregate — adding one would change the
  artifact into something practitioners do not use.
- **Tyler's screens produce a per-candidate verdict with a citation**, and the
  UI shows **rejections first and in full, retains sampled**. Inverting this
  destroys the gate's value.
- **ADDIE's ladder is about declining permitted change scope.** Its value is
  that it *forbids* substantive change late. This is the discipline automation
  will otherwise erode by making change look cheap, so `change_scope` is
  enforced rather than advisory. The naive implementation — "re-run the
  generator, it's fast" — destroys the mechanism.

**Field gates are marked unsatisfied, never skipped.** Every methodology
independently identified the same irreplaceable input: evidence from real
humans who are not part of the pipeline. The engine emits a complete course with
its field gates explicitly unsatisfied rather than blocking forever or
pretending they passed. An artifact that has never met a learner says so on its
face.

One thing genuinely does not fit and is specified separately: **a gate a human
wants to answer tomorrow.** Today's approval is an in-memory future inside a
running turn holding an open model session. Minutes-scale review is fine;
days-scale requires the turn to *end* at the stage boundary with pending-gate
state on the log, and a new turn to resume after approval. Build the in-turn
gate first.

### Markdown components are inline and server-projected

An interactive component is a fenced code block with a `component:` prefix and a
YAML body:

````markdown
```component:mcq
id: severity-classification-1
prompt: A customer reports the checkout page returning 500s for all users.
options:
  - text: SEV-1
    correct: true
  - text: SEV-2
rationale: Total loss of a revenue-critical path is SEV-1 regardless of duration.
```
````

The governing constraint, ranked above expressiveness and elegance: **an LLM
must author it correctly on the first try.** Models emit fenced YAML constantly.
The runner-up, generic directives (`:::mcq{...}`), loses on colon-count nesting
being a real reliability tax. MDX loses outright because it would break the
current invariant that model output never becomes markup. And the existing
renderer already stores the info string in `pre.dataset.lang` (`app.js:306`), so
the dispatch hook exists.

Unknown component types degrade to a labeled code block rather than breaking the
document — in `cat`, in a git diff, in GitHub, and in the source view.

**Content stays inline; the server projects.** The file is the source of truth;
the server parses it and serves `view=author` (everything) or `view=learner`
(`correct`, `rationale`, and feedback fields dropped before the bytes leave the
process).

The rejected alternative was reducing components to `{type, id}` with content
server-side. The argument against is specific to this codebase rather than
general taste: a bare-id pointer **does not fork** (editing an item in a forked
session would mutate the parent's lesson) and **does not scrub** (renders
today's item inside last Tuesday's lesson). Both breakages have one cause —
mutability, not location — and the fix, a version-pinned immutable pointer,
gives up the strongest reason to want pointers at all. *You can have referential
integrity or central revision; in an event-sourced system you cannot have both,
and this system has already chosen.*

Pointer components remain genuinely necessary for randomized item pools, timed
exams, and adaptive sequencing — where the point is that the document does not
determine the experience. Deferred, not rejected: inline-full, inline-with-
grading, and server-projected differ only in *server behavior, not file format*,
so moving among them is configuration. Moving to pointers is a format change and
a data migration. That asymmetry is the argument for starting where we start.

**Answer-withholding in v1 is a rendering affordance, not a boundary, and the UI
says so.** The file endpoint serves source verbatim, the UI has a source toggle,
and `presenters.py`'s edit-intent display leaks answer text through a route that
never returns a whole file. There is no user system, so there is no learner
principal to withhold from. The real fix — a publication boundary where a
finished lesson is snapshotted into a form whose stored bytes have never
contained an answer — is recorded in `BACKLOG.md` and blocked on authentication.
Never claim v1 is security.

### Deliverables carry a per-block `audience`

The learner/facilitator split recurs across assessments, exercises, case
studies, rubrics, slide decks, workbooks, schedules, and objectives — and
rubrics are *both* at different depths, with criteria disclosed to learners and
calibration anchors withheld. That proves the granularity: **per-block, not
per-document**, and an enum rather than a boolean, since manager reinforcement
guides are a real third audience.

The ILT tooling category already works this way — the participant workbook is
*extracted* from the facilitator guide. One source, two projections.

This is the same primitive as component answer-withholding. Two research threads
reached it independently from opposite ends, which is good evidence it is the
right abstraction.

**Authoring decisions are stored as artifacts; exports are mechanical.**
Mechanical: static site, PDF, EPUB, audience projections. Authoring decisions:
slide content and pacing, assessment items, activity design, timing. The
pipeline generates `slides.md` as a deliverable rather than transforming prose
into slides — auto-slicing prose at `##` produces dense-text decks, the
most-mocked artifact in corporate training.

v1 emits a markdown tree plus a course manifest. Quarto is the render target
when one is added, being the only generator that treats site, PDF, slides, and
book as outputs of one source — which is exactly the course-deliverable shape.

## Where unification fails

Recorded because each is a real limit rather than an unfinished part, and
because the escape hatches are load-bearing.

**Scope-level mismatch is the deepest leak.** Tyler's unit of work is a program,
UbD's is a 2–6 week unit, ADDIE's storyboard operates at *screen* level. One
`Experience` type cannot span "a semester-long organizing thread" and "slide
14's wrong-answer feedback branch." The evidence this is real: when the three
methodologies were expressed in the generic schema, canonical `Experience` came
out nearly contentless with everything useful pushed into `ext/`. Escape hatch:
`scope_level` as a first-class field on stages and artifacts, and a **nested
rather than flat execution graph** — analysis once at course scope, then
design-develop per module, which is ADDIE's own agile reconciliation. Coverage
checks become scope-aware. Do not attempt a single flat DAG.

**Observability is a theoretical disagreement, not vocabulary.** ADDIE
hard-rejects "understand" as an objective verb. UbD's central artifact is
stemmed *"Students will understand that…"* and its authors argue that demanding
observability at that grain size *is* the design error. No single `Intent`
schema satisfies both. Escape hatch: observability is a **methodology-bound
validator**, not a schema constraint — attached in ADDIE and Tyler presets,
absent in UbD's, and decided per intent subtype in the hybrid.

**The three taxonomies are not interchangeable.** Bloom's is a hierarchy; the
Six Facets are explicitly not one; Tyler's behavior axis includes affective
entries neither accommodates. `taxonomy_binding` names a registered taxonomy and
each registers its own valid checks. Do not build a union enum.

**UbD's authority is a person, not a document.** Tyler's authority is an
authored philosophy statement — citable, versionable. ADDIE's is a business
metric — measurable. UbD's is whether an understanding is genuinely central to
the discipline, and it lives uncodified in an expert's head. So
`verdict_citation`, the mechanism that hardens Tyler's screens, has nothing to
bite on at UbD's most important gate. There is no satisfying escape hatch. The
honest answer is a mandatory human `rubric` gate at Stage 1. A partial
mitigation: let a UbD preset optionally accept a discipline charter as a
`CriterionDocument`, effectively grafting Tyler's Screen 1 onto UbD. That is not
standard UbD and is a real improvement, which is itself an argument for the
hybrid.

**Convergence criteria do not unify.** UbD exits when its coherence standard
passes, ADDIE when Gold is signed, Tyler when the achievement profile stops
indicting the objectives. `loop_policy.convergence_check` names a check per
preset, with `max_iterations` as a universal backstop. Do not define a global
"done."

## Prerequisites

This spec cannot ship without the first of these and is substantially weakened
without the second. Both need their own specs.

**A corpus layer.** A `SourceDocumentStored` event on a research-team stream
holding the retained text, with span-addressable claims. One event on an
existing pattern, versus three redstring schema changes — and it strengthens the
property `rebuild.py` is built on, since today the log is the only copy of
anything and the text is not in it. The graph stays what it is good at:
cross-course recall and adjudicated entity consolidation, not citation storage.

Note that redstring *computes* chunk offsets (`start_char`/`end_char`) and then
discards them — `Entity` carries only `source_id` and `source_text`, and
`DocumentExtracted` carries entities rather than chunks. `Relationship` has no
provenance fields at all, which means the part of the graph carrying the most
instructional content has the least provenance.

Also live today and worth fixing alongside: consolidation will **silently merge
contradictory claims**. Two SMEs giving different escalation thresholds are
likely to be unified into one node, with `unmerge` available only if the agent
notices. `ContradictionLog` must be first-class with a "both true in different
contexts" resolution state — in procedural domains an apparent contradiction is
usually an unstated conditional, which is exactly an `expert_gap_flag`.

**A `fetch` tool.** `web_search` returns five snippets and the agent cannot read
a page, so web research is effectively unavailable for corpus construction.

Bulk ingest is additionally not shippable today: `build_graph` has no progress
callback and `build_knowledge_tools` takes no `ActivityReporter`. Forty
documents behind one opaque `await` is not acceptable in a UI that otherwise
streams everything.

**Intake is necessarily two-pass**, and the spec should not pretend otherwise.
Corpus sufficiency is only assessable against a task inventory — "is this corpus
good enough?" is unanswerable in the abstract. Ingest enough to scope, scope,
then assess sufficiency against scope and ingest again. The human sees a
coverage matrix marking tasks with no source and tasks with a single source, a
contradiction log, expert-gap flags, and roughly twenty sampled claims with
their quoted spans. Not the corpus, and not the graph — a node-link diagram is a
demo, not a review artifact.

## Build order

**Step 1 — a usable workflow with no new UI components.** `GET /api/workflows`,
`POST/GET /api/projects/{id}/workflow`, the two `Project` events and their fold,
`StageMiddleware` with `awrap_model_call`, one preset, artifacts written to
`/course/NN-*.md` that the existing file viewer already renders, a `<select>`
beside the existing project-name input, a chip in the project row, and one
`isinstance` branch in `event_summary` so transitions appear in the timeline.

**Step 2 — the check library and the coverage matrix.** Generated as markdown
tables first; the renderer already handles tables. This is where most of the
value is and it needs no model calls.

**Step 3 — the stage rail.** Stage progress folds off `Project` and rides the
existing SSE channel with a position and replay safety. Explicitly **not** the
summaries projection — that is per-session and is already what `/api/health`
warns about going stale.

**Step 4 — the gate review UI.** Last, deliberately. The field list for
`context` is a guess until the earlier steps show what a reviewer actually
needs, and getting it wrong is expensive because it crosses the port boundary.

**Step 5 — markdown components**, starting with the four that fall directly out
of the methodologies: `rubric` and `scenario` from UbD Stage 2, `mcq` and
`cloze` from Tyler's evaluation step.

Note on the client: vanilla JS, no build step, no `package.json`. A new pane
costs roughly 150–250 lines across four files. The no-build property is
load-bearing for a local single-user tool; if `app.js` becomes unwieldy, split
into several `<script>` tags sharing globals before reaching for a bundler.

## Deferred

Recorded in `BACKLOG.md` with reasons: the author/learner boundary and the
publication mechanism (blocked on there being a user system at all), redaction
and erasure in an append-only log, item banks and pointer components, LMS
packaging, learner state and grading, durable cross-session gates.

One deferral worth a spike rather than a flat no: **Common Cartridge 1.1**. For
a page-shaped course it is close to a directory listing plus a typed manifest,
it is the standard Canvas/Moodle interchange path, and its documented lossiness
costs us almost nothing. Plausibly the cheapest real LMS-import win available.
The Canvas REST API may beat any file format for programmatic construction.

## Open questions

- **Is the project the right tenancy boundary for a course?** A project may hold
  several courses over its life, and `project_id` is already redstring's
  `tenant_id`. Binding workflow to project means one workflow run per project at
  a time, which is consistent with projects being sequential but may prove too
  coarse.
- **What does the reviewer actually need in `context`?** Deliberately unresolved
  until Step 1 is in use. It crosses the port boundary, so it is the one field
  set worth being slow about.
- **Does `hybrid.default`'s per-subtype observability rule hold in practice?**
  UbD-style for `understanding`, ADDIE-style for `skill` is coherent on paper.
  It has to be authored deliberately and has not been tried.
- **How much does the local model degrade the screen stages?** Value arbitration
  under Screen 1 is the least trustworthy output in the system by design. Worth
  measuring before trusting the preset that leads with it.
