"""Workflow presets: the shapes, and the rules that make a preset trustworthy.

A workflow here is **data, not code**. Tyler (1949), ADDIE (1975) and UbD (1998)
turn out to be the same graph over a small artifact vocabulary, differing in
which nodes exist, which edge carries authority, and where the humans stand --
so three hand-written pipelines would reimplement one core three times and
drift. `docs/research/course-design/synthesis-generic-workflow.md` is the source
of truth for these shapes; this module is that document made executable.

Because a preset is data, validation is the whole safety story. A typo in a
`from_stage` is not a crash, it is a run that proceeds confidently and fails an
hour in when a stage asks for an artifact nobody produced. Every rule in
`problems()` exists because its absence has a specific expensive failure, and
each is named in the function.

**`kind` is modelled as a discriminated union rather than a field.** §2.4 of the
synthesis observes that `kind` is doing real work: screens have no generator,
`produce` stages have a rung ladder instead of a flat gate, `decide` stages are
the only ones that may halt, and `field` stages cannot be executed by an agent
at all. One flat `Stage` with all of those fields would leave half of them
unused in every instance, and would turn "a screen must not generate" into a
validation rule that fires after someone has already written the preset. Here it
is unrepresentable instead. The cost is eight classes where one would do; the
benefit is that the most dangerous mistake in the system -- a screen that
generates the candidates it then screens, and therefore passes nearly all of
them -- cannot be typed.

**`halt` is available in every preset, deliberately unfaithfully.** Only ADDIE
has "this should not be a course" as a legitimate output. The research was
explicit that its absence from Tyler and UbD is a defect in those traditions
rather than a property worth preserving, and an automated pipeline's strongest
bias is toward producing its own output. So `problems()` requires a halt-capable
gate of every preset, including the pure ones, and the shipped `ubd.pure` grafts
one on at context framing. Anyone reading `ubd.pure` and expecting textbook UbD
should know that is the one place it departs.
"""

from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

SPINE_NAMES: dict[int, str] = {
    0: "Corpus intake",
    1: "Context framing",
    2: "Candidate generation",
    3: "Filtering",
    4: "Intent specification",
    5: "Evidence design",
    6: "Experience design",
    7: "Organization",
    8: "Production",
    9: "Delivery",
    10: "Outcome evidence",
}
"""The eleven-position spine all three methodologies reduce to.

Not every methodology occupies every position, and that is the finding rather
than a defect in the mapping: each is strong exactly where the others are weak.
Tyler owns [0]-[4] and has nothing at [8]-[9]; UbD owns [5]-[7]; ADDIE owns
[8]-[10] and has no value filter at [3] at all.
"""

SpinePosition = Annotated[int, Field(ge=0, le=10)]

PRODUCTION = 8
"""The position below which a preset produces a design, not materials."""


class ArtifactType(StrEnum):
    """The artifact vocabulary, canonical types first.

    The twenty-two in `CANONICAL_ARTIFACTS` are the collapse the research
    found: Tyler's objective grid, UbD's Code columns and ADDIE's assessment
    blueprint really are one `CoverageMatrix` with different axes, and every
    density and coverage check becomes one implementation because of it.

    The rest are ADDIE's production and delivery types. §3.2 says explicitly
    *not* to canonicalize them -- Tyler and UbD have no delivery half, and
    giving a UbD unit a tracking package would be inventing machinery the
    methodology does not have. They are named here only so an ADDIE preset can
    reference them; no shared check is written against them.
    """

    SOURCE_DOCUMENT = "SourceDocument"
    SOURCE_CLAIM = "SourceClaim"
    SOURCE_DOSSIER = "SourceDossier"
    CONTEXT_PROFILE = "ContextProfile"
    CONSTRAINT_REGISTER = "ConstraintRegister"
    CRITERION_DOCUMENT = "CriterionDocument"
    INTENT = "Intent"
    VERDICT_LEDGER = "VerdictLedger"
    EXCLUSION = "Exclusion"
    EVIDENCE_SPEC = "EvidenceSpec"
    CRITERIA = "Criteria"
    RUBRIC = "Rubric"
    EXPERIENCE = "Experience"
    SEQUENCE = "Sequence"
    COVERAGE_MATRIX = "CoverageMatrix"
    RESOURCE_SELECTION = "ResourceSelection"
    RISK_REGISTER = "RiskRegister"
    MONITORING_PLAN = "MonitoringPlan"
    EVALUATION_PLAN = "EvaluationPlan"
    OUTCOME_EVIDENCE = "OutcomeEvidence"
    REVISION_PROPOSAL = "RevisionProposal"
    OPEN_QUESTION = "OpenQuestion"

    # Not canonical. See the class docstring.
    REQUEST_BRIEF = "RequestBrief"
    SCOPE_STATEMENT = "ScopeStatement"
    ESTABLISHED_GOAL = "EstablishedGoal"
    GAP_STATEMENT = "GapStatement"
    INTERVENTION_RECOMMENDATION = "InterventionRecommendation"
    TAXONOMY_SELECTION = "TaxonomySelection"
    CONTESTED_QUEUE = "ContestedQueue"
    PRODUCTION_SPEC = "ProductionSpec"
    STYLE_GUIDE = "StyleGuide"
    BUILD = "Build"
    DEFECT_LOG = "DefectLog"
    REVIEW_COMMENT_LOG = "ReviewCommentLog"
    CONFORMANCE_REPORT = "ConformanceReport"
    TRACKING_PACKAGE = "TrackingPackage"
    LMS_CONFIGURATION = "LMSConfigurationRecord"


CANONICAL_ARTIFACTS: frozenset[ArtifactType] = frozenset(
    list(ArtifactType)[: list(ArtifactType).index(ArtifactType.REQUEST_BRIEF)]
)

AUTHORED_ARTIFACTS: frozenset[ArtifactType] = frozenset(
    {
        ArtifactType.SOURCE_DOCUMENT,
        ArtifactType.CRITERION_DOCUMENT,
        ArtifactType.REQUEST_BRIEF,
        ArtifactType.SCOPE_STATEMENT,
        ArtifactType.ESTABLISHED_GOAL,
        ArtifactType.CONTEXT_PROFILE,
    }
)
"""Types a human or the pipeline boundary can supply, so an input of one of
these needs no producing stage.

The list is closed rather than "anything with no `from_stage`", because
otherwise a forgotten `from_stage` would silently opt an input out of chain
validation -- the exact typo the chain rule exists to catch. A
`PhilosophyStatement` in particular *must* be authorable: the tautology guard
depends on it not being derived from the corpus that produced the candidates.
"""

ScopeLevel = Literal["program", "course", "unit", "module", "asset"]
"""L1, the deepest leak: Tyler's unit of work is a program, UbD's is a 2-6 week
unit, ADDIE's storyboard operates at screen level. Carried on every stage so a
later coverage check can be scope-aware rather than comparing a semester-long
thread with a wrong-answer feedback branch."""

ReviewerRole = Literal["sme", "instructor", "sponsor", "peer_reviewer", "learner", "lms_admin"]

Decision = Literal["approve", "approve_with_edits", "amend_upstream", "send_back", "halt"]

Severity = Literal["blocking", "advisory"]

Cardinality = Literal["1", "0..n", "1..n"]


class PresetError(Exception):
    """A preset is malformed. Carries every problem found, not just the first.

    Not a `ValueError`: pydantic would fold that into a `ValidationError` and
    bury the list of problems inside its own formatting, which is the opposite
    of what someone editing preset data needs to see.
    """


class Check(BaseModel, frozen=True):
    """One entry from the shared check registry, bound with its parameters.

    Every check in the registry is a graph or schema query -- none requires a
    model call. `severity` is what separates a preset that stops from one that
    warns, and it is per binding rather than per check because the same
    `coverage` check is blocking in UbD Stage 2 and advisory elsewhere.
    """

    check: str
    params: dict[str, object] = Field(default_factory=dict)
    severity: Severity = "blocking"


class Generator(BaseModel, frozen=True):
    """Who writes the artifact, and under which taxonomy."""

    role: str
    prompt_ref: str
    taxonomy_binding: str | None = None
    """`six_facets`, `blooms_revised`, `tyler_behavior_axis` -- named, never
    unioned. Bloom's is a hierarchy and the Six Facets are explicitly not one
    (L4), so a check written against one is meaningless against the other."""
    over_generate_factor: int | None = None
    """Pool size multiplier where generation is deliberately over-large. `None`
    where it is not; a `prune_ratio` check has nothing to measure without it."""


class Critic(BaseModel, frozen=True):
    """Who reviews the artifact, and whether their verdict must be cited."""

    role: str
    prompt_ref: str
    criterion_doc: str | None = None
    require_citation: bool = True
    separate_context: bool = True
    """MUST stay true wherever a critic gates a generator. A critic that has
    seen the generating rationale is reviewing the argument, not the artifact."""
    adversarial_second_pass: bool = False


class ScreeningCritic(Critic):
    """A critic whose `criterion_doc` is mandatory.

    Tyler's screens are the only place in the system where a verdict has legal
    force over a candidate, and `verdict_citation` -- the rule that makes that
    bearable -- has nothing to bite on without an authored document to cite.
    A screen with an optional criterion document degrades into fluent generic
    plausibility, which the spec calls the worst failure in the system
    precisely because it looks like it is working.
    """

    criterion_doc: str
    adversarial_second_pass: bool = True


class StageInput(BaseModel, frozen=True):
    """One artifact a stage consumes, and where it comes from.

    `from_stage=None` means authored or supplied at the pipeline boundary, and
    is legal only for `AUTHORED_ARTIFACTS`.
    """

    artifact_type: ArtifactType
    cardinality: Cardinality
    from_stage: str | None = None
    subtype: str | None = None
    required: bool = True


class StageOutput(BaseModel, frozen=True):
    artifact_type: ArtifactType
    cardinality: Cardinality
    subtype: str | None = None
    schema_ref: str | None = None
    """Points into `ext/` where a methodology's idiosyncrasy lives -- GRASPS,
    the A/M/T-coded learning event, Tyler's escalation descriptor. This escape
    hatch absorbed nearly all the pressure that would otherwise have bloated
    the canonical types, at the cost that canonical `Experience` is nearly
    contentless on its own (L1)."""


class Amendments(BaseModel, frozen=True):
    """Which earlier stages this one may route a revision back to.

    UbD's Stage 2 → Stage 1 edge and Tyler's evaluation → objectives loop, made
    explicit. A gate may only return `amend_upstream` to a stage named here.
    """

    emits_to: tuple[str, ...] = ()
    accepts_from: tuple[str, ...] = ()


class LoopPolicy(BaseModel, frozen=True):
    """When to stop going round.

    `convergence_check` is per preset because the traditions genuinely disagree
    about done: UbD exits when the coherence standard passes, ADDIE when Gold
    is signed, Tyler when the achievement profile stops indicting the
    objectives (L7). `max_iterations` is the universal backstop.
    """

    max_iterations: int = 3
    convergence_check: str | None = None


# --- gates ------------------------------------------------------------------
#
# Five kinds, genuinely different in what the human sees and what they may
# return. Modelled as separate classes for the same reason stages are: `halt`
# belongs to exactly one of them, and `rungs` to exactly one other.


class GateBase(BaseModel, frozen=True):
    decisions: tuple[Decision, ...]
    blocking: bool = True
    reviewer_role: ReviewerRole
    presents: tuple[str, ...] = ()
    """What the human actually sees. Not decoration -- a gate that presents the
    wrong thing is a rubber stamp with an audit trail."""
    sla: str | None = None

    @model_validator(mode="after")
    def _halt_is_a_decision_gate_privilege(self) -> Self:
        if "halt" in self.decisions and not isinstance(self, DecisionGate):
            raise ValueError("halt is only available on a decision gate")
        return self


class RubricGate(GateBase, frozen=True):
    """An artifact set plus critic findings against a criterion document.

    UbD's peer review produces commentary and never a score; the Design
    Standards are written as consider-questions. No numeric aggregate is
    modelled, deliberately -- adding one would turn the artifact into something
    practitioners do not use.
    """

    kind: Literal["rubric"] = "rubric"
    decisions: tuple[Decision, ...] = (
        "approve",
        "approve_with_edits",
        "amend_upstream",
        "send_back",
    )


class LedgerGate(GateBase, frozen=True):
    """Per-item verdicts, rejections first and in full, retains sampled.

    The ordering is the gate's whole value: the interesting failure is what got
    cut, and all three traditions independently concluded that reviewing the
    exclusions is more informative than reviewing what survived. A UI that
    inverts it leaves the reviewer approving a list they cannot learn from.
    """

    kind: Literal["ledger"] = "ledger"
    decisions: tuple[Decision, ...] = ("approve", "approve_with_edits", "send_back")


class Rung(BaseModel, frozen=True):
    name: str
    reviewer_role: ReviewerRole
    permitted_change: tuple[str, ...]
    forbidden_change: tuple[str, ...] = ()
    decisions: tuple[Decision, ...] = ("approve", "send_back")


class MaturityGate(GateBase, frozen=True):
    """The same artifact at a rising rung, with permitted change narrowing.

    Unique to ADDIE, and its value is precisely that it *forbids* substantive
    change late. This is the discipline automation erodes by making change look
    cheap -- "re-run the generator, it's fast" destroys the mechanism -- so
    `change_scope` is enforced rather than advisory.
    """

    kind: Literal["maturity"] = "maturity"
    rungs: tuple[Rung, ...]
    decisions: tuple[Decision, ...] = ("approve", "approve_with_edits", "send_back")


class DecisionGate(GateBase, frozen=True):
    """A recommendation plus its adversarial counter-case. The only gate that
    may halt the run, and the reason every preset is required to have one."""

    kind: Literal["decision"] = "decision"
    decisions: tuple[Decision, ...] = ("approve", "send_back", "halt")


class FieldGate(GateBase, frozen=True):
    """Evidence from real humans who are not part of the pipeline.

    Schedulable but pending: the engine emits a complete course with its field
    gates explicitly unsatisfied rather than blocking forever or pretending
    they passed. An artifact that has never met a learner says so on its face.
    """

    kind: Literal["field"] = "field"
    decisions: tuple[Decision, ...] = ("approve", "send_back")


Gate = Annotated[
    RubricGate | LedgerGate | MaturityGate | DecisionGate | FieldGate,
    Field(discriminator="kind"),
]


# --- stages -----------------------------------------------------------------


class StageBase(BaseModel, frozen=True):
    id: str
    """Namespaced `<methodology>.<phase>.<step>`, so a hybrid preset's
    composition is readable from the stage list alone."""
    name: str
    spine: SpinePosition
    scope_level: ScopeLevel
    inputs: tuple[StageInput, ...] = ()
    outputs: tuple[StageOutput, ...] = ()
    tools: tuple[str, ...] = ()
    """Which tools the model may see in this stage. `StageMiddleware` filters
    the registered set down to this; it can never add one."""
    checks: tuple[Check, ...] = ()
    amendments: Amendments = Amendments()
    loop_policy: LoopPolicy = LoopPolicy()


class _Authored(StageBase, frozen=True):
    """A stage an agent executes: it has someone writing and someone reviewing."""

    generator: Generator
    critic: Critic | None = None


class GenerateStage(_Authored, frozen=True):
    """Pools candidates, usually deliberately over-large."""

    kind: Literal["generate"] = "generate"
    gate: Gate | None = None


class SpecifyStage(_Authored, frozen=True):
    """Elaborates artifacts that already exist rather than pooling new ones.

    Distinct from `generate` because a `prune_ratio` check is meaningful for
    one and meaningless for the other: there is no candidate pool to prune.
    """

    kind: Literal["specify"] = "specify"
    gate: Gate | None = None


class MatrixStage(_Authored, frozen=True):
    """Produces a coverage matrix as its primary artifact.

    Kept apart from `specify` because the matrix checks are intrinsic to it --
    an empty row is an uncovered intent and an empty column is an orphan, and a
    fully dense grid is objective inflation.
    """

    kind: Literal["matrix"] = "matrix"
    gate: Gate | None = None


class ScreenStage(StageBase, frozen=True):
    """A filter over candidates, producing a cited verdict per candidate.

    **No generator field.** A screen that generates the candidates it screens
    is self-screening, and the research found that yields near-100% pass rates
    while looking exactly like a working filter. `self_review_separation`
    checks the graph property; this makes the mistake untypeable.
    """

    kind: Literal["screen"] = "screen"
    critic: ScreeningCritic
    gate: LedgerGate


class DecideStage(_Authored, frozen=True):
    """A go/no-go. The only stage kind whose gate may halt the run."""

    kind: Literal["decide"] = "decide"
    gate: DecisionGate


class ProduceStage(_Authored, frozen=True):
    """Builds materials at rising fidelity, behind a maturity ladder."""

    kind: Literal["produce"] = "produce"
    gate: MaturityGate


class FieldStage(StageBase, frozen=True):
    """Evidence from real learners. **Not executable by an agent at all.**

    No generator and no critic, because there is nothing here to prompt: the
    input is people outside the pipeline, and the only honest states are
    satisfied and unsatisfied.
    """

    kind: Literal["field"] = "field"
    gate: FieldGate


class CustomStage(_Authored, frozen=True):
    """The escape hatch, for methodologies outside the three and house process.

    Only universal checks apply. It exists so that not being one of the three
    is a supported case rather than a reason to fork the engine.
    """

    kind: Literal["custom"] = "custom"
    critic: Critic | None = None
    gate: Gate | None = None


Stage = Annotated[
    GenerateStage
    | SpecifyStage
    | MatrixStage
    | ScreenStage
    | DecideStage
    | ProduceStage
    | FieldStage
    | CustomStage,
    Field(discriminator="kind"),
]


# --- presets ----------------------------------------------------------------


def problems(preset: "Preset") -> list[str]:
    """Every way this preset is malformed, in one pass.

    All of them at once rather than the first: preset data is authored by hand,
    and fixing one typo per run is a bad loop. Each rule below is here because
    its absence has a specific failure, named inline.
    """
    found: list[str] = []
    stages = preset.stages
    ids = [stage.id for stage in stages]

    duplicates = sorted({stage_id for stage_id in ids if ids.count(stage_id) > 1})
    for stage_id in duplicates:
        found.append(f"duplicate stage id: {stage_id}")

    # Execution order is list order, so a preset whose spine positions go
    # backwards would run organization before objectives. This is also what
    # enforces Tyler's philosophy-before-psychology screen order, without any
    # rule that knows Tyler exists.
    for earlier, later in pairwise(stages):
        if later.spine < earlier.spine:
            found.append(
                f"stages are out of spine order: {later.id} at [{later.spine}] "
                f"follows {earlier.id} at [{earlier.spine}]"
            )

    position = {stage.id: index for index, stage in enumerate(stages)}
    for index, stage in enumerate(stages):
        for item in stage.inputs:
            if item.from_stage is None:
                if item.artifact_type not in AUTHORED_ARTIFACTS:
                    # Otherwise a forgotten `from_stage` opts an input out of
                    # chain validation entirely -- the very typo it catches.
                    found.append(
                        f"{stage.id} takes {item.artifact_type} with no source, but "
                        f"{item.artifact_type} is not an authored artifact"
                    )
                continue
            source_index = position.get(item.from_stage)
            if source_index is None:
                found.append(f"{stage.id} reads from unknown stage {item.from_stage}")
            elif source_index >= index:
                found.append(
                    f"{stage.id} reads {item.artifact_type} from {item.from_stage}, "
                    f"which is not an earlier stage"
                )
            elif not any(
                out.artifact_type == item.artifact_type for out in stages[source_index].outputs
            ):
                # The expensive one: nothing fails until the run reaches here.
                found.append(
                    f"{stage.id} reads {item.artifact_type} from {item.from_stage}, "
                    f"which does not produce it"
                )

        for target in stage.amendments.emits_to:
            target_index = position.get(target)
            if target_index is None:
                found.append(f"{stage.id} amends unknown stage {target}")
            elif target_index >= index:
                # An amendment routes a revision upstream. Pointing it forward
                # is a cycle wearing the wrong name, and would never converge.
                found.append(f"{stage.id} amends {target}, which is not an earlier stage")

    declared = tuple(preset.spine_positions)
    actual = tuple(sorted({stage.spine for stage in stages}))
    if declared != actual:
        # Two sources of truth that can disagree. The declaration is what the
        # UI shows and what "terminates before production" is judged against.
        found.append(
            f"spine_positions {list(declared)} do not match the stages {list(actual)}"
        )

    if actual and max(actual) < PRODUCTION and preset.produces != "design":
        found.append("a preset terminating before production produces a design, not materials")

    if not any(
        isinstance(stage, DecideStage) and "halt" in stage.gate.decisions for stage in stages
    ):
        found.append(
            "no stage can halt the run; every preset needs one, including the pure ones"
        )

    return found


class Preset(BaseModel, frozen=True):
    """A workflow, as data. Cannot be constructed malformed.

    Validation runs at construction rather than at selection time because a
    preset is loaded once and run for hours: the useful moment to learn it is
    broken is when someone edits it, not when a user picks it.
    """

    id: str
    name: str
    version: str
    description: str
    """What this preset is, in the words the UI shows. The hybrid names its own
    composition -- "Tyler's sourcing, UbD's evidence-first design, ADDIE's
    production" -- rather than presenting itself as a neutral house process."""
    spine_positions: tuple[SpinePosition, ...]
    stages: tuple[Stage, ...]
    produces: Literal["design", "materials"]
    renderer: str = "canonical"
    """Renderers are views over canonical artifacts, not storage formats. This
    is what lets a hybrid run emit UbD Template 2.0 -- process conformance and
    output conformance are separable, and separating them is what lets most
    users take the better process while the constrained minority takes the
    required paperwork."""
    overridable_spine_positions: tuple[SpinePosition, ...] = ()

    @model_validator(mode="after")
    def _is_well_formed(self) -> Self:
        found = problems(self)
        if found:
            raise PresetError(f"preset {self.id} is malformed:\n" + "\n".join(found))
        return self

    @property
    def has_value_filter(self) -> bool:
        """Whether anything here asks *should* this be taught, not just *can* it.

        ADDIE has no such stage, and that is load-bearing rather than
        incidental: it assumes the value question was settled before the
        designer was engaged. Surfaced as a property so the gap can be shown to
        a user choosing a preset instead of being discovered later.
        """
        return any(isinstance(stage, ScreenStage) for stage in self.stages)

    @property
    def terminal_spine(self) -> int:
        return max(stage.spine for stage in self.stages)
