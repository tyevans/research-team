# Extraction review: the workflow-and-checks subsystem

Scope: `domain/workflow.py` (662), `application/checks.py` (2013),
`application/coverage.py` (493), `application/findings.py` (74),
`application/stage_exit.py` (505), `workflows/{addie,ubd,hybrid}.py` (1982).
About 5.7k lines.

**Verdict: balanced as-is.** One library is arguable and two are not. The
reasoning is below, and the most useful part of it is that the seam is not
where the brief assumed.

## 1. Where the seam actually is

The brief framed the tension as *generic engine (checks) vs. instructional-design
vocabulary (ArtifactType)*. Reading the code, that is close to backwards.

### checks.py is almost fully parameterized already

`ArtifactType` appears **five times in 2013 lines**, and three of those are
inside error strings (`checks.py:609`, `:635`, `:769`, `:815`). The only
genuine coupling is one line: `checks.py:1862`, where
`tyler.criterion_doc_authored` selects `ArtifactType.CRITERION_DOCUMENT`.

Everything else routes through `TypeFilter` (`checks.py:200`), which is
`(artifact_type, subtype, stage)` ANDed, with a string shorthand
(`"EvidenceSpec.performance_task"`). The check functions never name a course
concept — they read `context.artifacts`, `context.links`,
`artifact.fields` (an untyped `Mapping`) and `artifact.provenance`. The
seventeen shared checks are: coverage, orphan, provenance, budget,
format_conformance, taxonomy_distribution, vocabulary_coverage,
exclusion_ledger, verdict_citation, self_review_separation, prune_ratio,
required_field_nondegenerate, recurrence, ordering, prerequisite_satisfied,
source_starvation, contradiction_escalation, matrix_density. Read cold, with
the docstrings stripped, that list is a **lint suite over a typed document
graph** and nothing about it is educational. `source_starvation`,
`prune_ratio`, `verdict_citation` and `self_review_separation` in particular
are checks about *any* generate-then-screen pipeline, LLM-driven or not.

The three namespaced checks (`tyler.*`, `addie.*`, `ubd.*`) are the honest
boundary and are already fenced: `addie.change_scope` queries the preset's own
`MaturityGate` rungs and is domain-shaped only in name; `ubd.uncoverage` and
`addie.expert_gap_flag` have `run=None` and are pure declarations.

`coverage.py` has two `ArtifactType` references, both in axis model fields
(`:59`, `:70`). `findings.py` (74 lines) has zero domain content.

### workflow.py is the domain-coupled module

The vocabulary is not only `ArtifactType` (lines 71–129, ~55 lines). It is
also, woven into the *engine* classes rather than into a data table:

- `SPINE_NAMES` / `SpinePosition` — an eleven-position ladder from "Corpus
  intake" to "Outcome evidence", with `PRODUCTION = 8` as a named constant
  that `problems()` branches on (`:603`).
- `ScopeLevel = Literal["program","course","unit","module","asset"]` on every
  stage.
- `ReviewerRole = Literal["sme","instructor","sponsor","peer_reviewer",
  "learner","lms_admin"]` on every gate.
- `produces: Literal["design","materials"]`.
- `AUTHORED_ARTIFACTS`, a closed set of six.
- Stage kinds `screen` / `matrix` / `produce` / `field` and gate kinds
  `rubric` / `ledger` / `maturity` — the discriminated union that the module
  docstring correctly identifies as its best idea — are named for
  instructional-design roles even where the shape is general.

So the split is: **checks.py is a general library with a five-line tether;
workflow.py is a domain model with a general graph validator inside it.**
`problems()` (`:530–613`) is the general part — duplicate ids, topological
order, input-source chain validation, upstream-only amendments, "some stage can
halt" — roughly 80 genuinely reusable lines.

### Cost to parameterize the vocabulary

Small, and smaller than it looks:

- `ArtifactType` → a generic type parameter or plain `str` validated against a
  caller-supplied vocabulary set: touches ~8 sites (`StageInput`,
  `StageOutput`, `TypeFilter`, two axis models, one check, `AUTHORED_ARTIFACTS`,
  `stage_exit.load_course`). Half a day to a day.
- `SpinePosition`/`SPINE_NAMES`/`PRODUCTION` → a caller-supplied ordered spine:
  another half-day, and it removes the only place `problems()` knows what
  "production" means.
- `ScopeLevel` and `ReviewerRole` → `str`: trivial, and a real loss. Today a
  typo in a reviewer role is a type error at preset-authoring time. Generalized
  to `str`, it is not.

That last point generalizes. The mechanical cost is maybe two days; the design
cost is that **StrEnum-ness is doing quiet work**. Every one of these closed
vocabularies exists because presets are hand-authored data and the module
docstring's whole thesis is that a typo in preset data fails an hour into a run.
Parameterizing them trades compile-time refusal for runtime validation against a
registry the library cannot itself see. That is the right trade for a published
library and a bad one for this repo.

### Test coverage

Strong, and it is a genuine asset for any extraction:

| file | tests |
| --- | --- |
| `tests/application/test_checks.py` (1579 lines) | 83 |
| `tests/domain/test_workflow.py` (447) | 40 |
| `tests/application/test_coverage.py` + `test_stage_exit.py` (978) | 74 |
| `tests/application/test_preset_gates.py` (342) | — |

Plus `tests/test_architecture.py`, which enforces that `research_team/workflows/`
imports nothing but `domain.workflow` — an import-direction rule that already
proves the presets are pure data over the engine. `test_no_check_reaches_for_a_model`
enforces the no-LLM property. This is the shape of a codebase that *could* be
extracted cheaply; the question is whether anyone wants it.

## 2. Competitors

### (a) Generic: workflow-as-data and deterministic checks

**Workflow-as-data with human gates — crowded, and the incumbents are bigger.**

- [LangGraph](https://machinelearningmastery.com/building-a-human-in-the-loop-approval-gate-for-autonomous-agents/) — state graphs with interrupts for human approval; now the default answer for agent HITL.
- [Prefect / Dagster / Airflow](https://getbruin.com/blog/best-data-pipeline-tools-2026/) — orchestration with pause/approve, but code-first rather than data-first.
- [python-statemachine](https://python-statemachine.readthedocs.io/) and [pytransitions](https://github.com/pytransitions/transitions) — declarative statecharts, compound states, parallel regions. Closest to the *validated graph* half, with no gate or check concept.
- [Atomic](https://bastani.ai/) — the nearest single competitor found: "workflows with checks, evidence, gates, and approvals... an inspectable DAG of stages". Same four nouns as this subsystem. Worth a closer look before publishing anything.
- [Cerri Project](https://cerri.com/stage-and-gate-software) and the wider stage-gate SaaS market — proprietary, business-process framing.

What none of them offer is `problems()`: **validating the graph as authored
data before it runs** — that a stage reads an artifact type an earlier stage
actually produces, that amendments point upstream, that some stage can halt.
Orchestrators validate at execution. That is a real gap, but it is a feature
gap, not a library-sized one.

**Deterministic checks over a document graph — thinner, and the closest fit
is not Python.**

- [OPA / Rego](https://www.openpolicyagent.org/docs/policy-language) is the serious incumbent: Datalog-derived, built for structured JSON documents, with `graph.reachable` built in and termination guarantees a Python check function does not have. [Styra's own Python comparison](https://docs.styra.com/opa/rego-language-comparisons) argues exactly the case against a general-purpose language here.
- [GoRules Zen](https://github.com/gorules/zen) — JSON Decision Model, decision graphs as data, multi-language bindings.
- [Arta](https://maif.github.io/arta/) — YAML-configured Python rules engine, deterministic by design.
- [rule-engine](https://pypi.org/project/rule-engine/) — typed expression language over arbitrary Python objects.

Against these, the distinctive bits here are: **findings with severity and a
suggested edit, never a score**; the `human_gate` / `critic_gate` distinction
(a check that declares it *cannot* be automated and refuses to pass); and the
`fixed_severity` invariants a binding cannot downgrade. Those three are
genuinely good and I did not find them elsewhere. They are also about 150 lines.

### (b) Domain: instructional-design software

Searched broadly. **No open-source Python (or JS) library implementing ADDIE,
UbD or Tyler as a programmable model exists.** That is not a market signal in
the direction it first appears.

What exists instead:
- [nsip/curriculum-mapper](https://github.com/nsip/curriculum-mapper) — an ML document-classification tool for mapping between curricula. Different problem.
- [icarnaghan/CurriculumStart](https://github.com/icarnaghan/CurriculumStart) — a curriculum-mapping *framework* (templates/process), low activity.
- [Academic CLO→PLO mapping via NLP](https://link.springer.com/article/10.1007/s10639-023-11877-4) — research artifacts and one-off web tools, not libraries.
- The commercial layer is [AI tool suites and SaaS](https://www.disco.co/blog/ai-for-instructional-design-using-the-addie-model): Articulate 360 AI, Synthesia, MagicSchool, [x-pilot](https://www.x-pilot.ai/blog/addie-model-ai-instructional-design-complete-guide-2026), [addiearchitect](https://addiearchitect.com/). All end-user products. None expose a model an engineer would import.

The empty niche is empty for a structural reason: **instructional designers are
not Python developers, and the developers building ID products build products,
not libraries.** The addressable audience for `pip install
instructional-design-workflow` is roughly "people building a second
research-team", which is a number in the low tens optimistically and plausibly
one. Publishing it would produce a repo with a good README, a handful of stars
from the ID-adjacent Twitter audience, zero issues, and a maintenance
obligation on the most opinionated 5.7k lines in the codebase.

## 3. Verdict

**Balanced as-is. Do not extract. Certainly not two libraries.**

Reasoning, in order of weight:

1. **The domain library has no audience.** The niche is genuinely unoccupied
   and that is the finding — occupancy would at least prove demand. Nothing
   found suggests developers want to compose instructional-design methodology
   in code.

2. **The generic library has an audience but a crowded one, and the extractable
   novelty is small.** The parts that are genuinely distinctive —
   authored-graph validation before execution, findings-not-scores,
   `human_gate`/`critic_gate`, undowngradeable invariants — total a few hundred
   lines spread across three modules. Extracted, they would be a thin library
   competing for attention with LangGraph and OPA on their home ground.
   [Atomic](https://bastani.ai/) already ships the same four nouns.

3. **Extraction would cost the thing that makes the code good.** The value here
   is not the abstraction; it is that the abstraction is *pinned to a specific
   methodology by closed vocabularies and by comments recording why each rule
   exists*. `ScreeningCritic` requires a `criterion_doc` because Tyler's screens
   are the one place a verdict has legal force. Generalize that and you get
   `Critic` with an optional field and a docstring nobody can act on. The
   comments in these files are unusually load-bearing — they name the specific
   expensive failure each rule prevents — and most of them stop making sense
   once the domain is a type parameter.

4. **The two-library split would be worse than either.** It puts the
   `ArtifactType`/`TypeFilter` boundary on a package edge, meaning every
   vocabulary change becomes a cross-repo version bump — for a vocabulary that
   is still being edited.

### The one thing worth doing

Not extraction, but a cheap internal hedge that also improves the code:

- Move the one hardcoded `ArtifactType.CRITERION_DOCUMENT` in
  `tyler.criterion_doc_authored` (`checks.py:1862`) into a `TypeFilter`
  parameter on the binding. That makes `checks.py` **zero-coupled** to the
  artifact vocabulary except in error strings, which is worth having as a
  stated property regardless of whether anything is ever extracted — it means
  the no-domain-knowledge rule for shared checks is enforceable rather than
  merely observed.

Revisit if either becomes true: a second non-course workflow gets built on this
engine in-repo (proving generality with a user rather than by inspection), or
the artifact vocabulary stops changing for a few months (removing the main cost
of a package boundary).

### Not recommended: "lean further in"

Worth naming why. Leaning in would mean more `tyler.*`/`ubd.*`/`addie.*`
checks and richer methodology-specific types. The registry's second table is
short — three checks — and the module docstring calls that shortness the
finding. It is right. The generalization here was earned by comparing three
traditions and observing the collapse; adding domain-specific machinery back
would undo the one piece of research this subsystem encodes.
