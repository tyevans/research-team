"""`ubd.pure` — Understanding by Design, ending at a unit plan.

Exists for one legitimate reason: in some contexts the process trail is itself
the deliverable. A district that has adopted UbD wants Template 2.0 and the
three-stage shape, and a hybrid that produces a better course with the wrong
paperwork fails that user.

It occupies [0,1,4,5,6,7] and **terminates at a unit plan, not materials**. UbD
has no production or delivery half at all, and that is a scope boundary rather
than an oversight -- it assumes a teacher who will do the producing. Inventing
an alpha/beta/gold ladder for a UbD unit would be fabricating machinery the
methodology does not have, so the preset says what it produces instead.

**Two deliberate departures from textbook UbD**, both of which the research
argued for rather than merely permitted:

- A halt-capable gate at context framing. UbD presupposes that a unit is
  happening; the research called that a defect rather than a property worth
  preserving faithfully, and an automated pipeline is biased toward producing
  its own output.
- A discipline charter as an optional criterion document. UbD's real authority
  is whether an understanding is genuinely central and in need of uncoverage,
  and that lives uncodified in an expert's head (L6) -- so `verdict_citation`,
  the mechanism that hardens Tyler's screens, has nothing to bite on. Accepting
  an authored charter is effectively grafting Tyler's Screen 1 on. It is not
  standard UbD, which is itself an argument for the hybrid.

What it does not have is the front end: no candidate pool at [2], no filtering
at [3]. A standards document is usually UbD's only input, and that thinness is
visible here in the data rather than papered over.
"""

from research_team.domain.workflow import (
    Amendments,
    Check,
    Critic,
    DecideStage,
    DecisionGate,
    GenerateStage,
    Generator,
    MatrixStage,
    Preset,
    RubricGate,
    SpecifyStage,
)
from research_team.domain.workflow import (
    ArtifactType as A,
)
from research_team.domain.workflow import (
    StageInput as In,
)
from research_team.domain.workflow import (
    StageOutput as Out,
)

_INTAKE = GenerateStage(
    id="ubd.step0.intake",
    name="Corpus ingestion and domain concept mapping",
    spine=0,
    scope_level="unit",
    inputs=(In(artifact_type=A.SOURCE_DOCUMENT, cardinality="1..n"),),
    outputs=(
        Out(artifact_type=A.SOURCE_CLAIM, cardinality="1..n"),
        Out(artifact_type=A.SOURCE_DOSSIER, subtype="domain_concept_map", cardinality="1"),
    ),
    tools=("list_sources", "read_source", "graph_search"),
    generator=Generator(role="domain mapper", prompt_ref="prompts/ubd/intake"),
    checks=(
        Check(
            check="provenance", params={"type": "SourceClaim", "must_cite": "SourceDocument"}
        ),
    ),
)

_CONTEXT = DecideStage(
    id="ubd.step1.context",
    name="Context framing — is this unit worth building?",
    spine=1,
    scope_level="unit",
    inputs=(
        In(artifact_type=A.ESTABLISHED_GOAL, cardinality="1..n"),
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="ubd.step0.intake",
            required=False,
        ),
        # The optional discipline charter. Absent, Stage 1's gate is the only
        # authority there is; present, the critic has something to cite.
        In(
            artifact_type=A.CRITERION_DOCUMENT,
            subtype="discipline_charter",
            cardinality="1",
            required=False,
        ),
    ),
    outputs=(
        Out(artifact_type=A.CONTEXT_PROFILE, cardinality="1"),
        Out(artifact_type=A.CONSTRAINT_REGISTER, cardinality="1"),
    ),
    generator=Generator(role="curriculum lead", prompt_ref="prompts/ubd/context"),
    critic=Critic(
        role="scope skeptic",
        prompt_ref="prompts/ubd/context_critique",
        criterion_doc="ubd.design_standards.overall",
        adversarial_second_pass=True,
    ),
    gate=DecisionGate(
        reviewer_role="instructor",
        presents=("ContextProfile", "EstablishedGoal.*", "critic.adversarial_case"),
    ),
)

_DESIRED_RESULTS = GenerateStage(
    id="ubd.stage1.desired_results",
    name="Stage 1 — desired results",
    spine=4,
    scope_level="unit",
    inputs=(
        In(artifact_type=A.ESTABLISHED_GOAL, cardinality="1..n"),
        In(artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="ubd.step1.context"),
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="ubd.step0.intake",
            required=False,
        ),
    ),
    outputs=(
        Out(artifact_type=A.INTENT, subtype="transfer_goal", cardinality="1..n"),
        Out(artifact_type=A.INTENT, subtype="understanding", cardinality="1..n"),
        Out(artifact_type=A.INTENT, subtype="essential_question", cardinality="1..n"),
        Out(artifact_type=A.EXCLUSION, cardinality="0..n"),
        Out(
            artifact_type=A.RISK_REGISTER,
            subtype="predicted_misconception",
            cardinality="0..n",
        ),
    ),
    generator=Generator(
        role="curriculum designer, discipline-facing",
        prompt_ref="prompts/ubd/stage1_generate",
        # Generate fifteen, keep three. The note-7 prune, made explicit and
        # given an `Exclusion` output so it is reviewable rather than prose.
        over_generate_factor=5,
    ),
    critic=Critic(
        role="UbD design-standards reviewer",
        prompt_ref="prompts/ubd/stage1_critique",
        criterion_doc="ubd.design_standards.stage1",
    ),
    checks=(
        Check(
            check="format_conformance",
            params={"subtype": "understanding", "stem": "Students will understand that"},
        ),
        Check(
            check="format_conformance",
            params={"subtype": "essential_question", "reject_if": "single_fact_answerable"},
        ),
        Check(
            check="coverage",
            params={
                "from": {"subtype": "understanding"},
                "to": {"subtype": "essential_question"},
                "min": 1,
            },
        ),
        Check(
            check="prune_ratio", params={"expected_range": [0.15, 0.40]}, severity="advisory"
        ),
    ),
    # Mandatory and human, with no automated substitute. "In need of
    # uncoverage" has no proxy: a model will generate fluent platitudes and
    # rate them highly, so this is the one gate that cannot be softened.
    gate=RubricGate(
        reviewer_role="sme",
        presents=("Intent.*", "Exclusion.*", "critic.findings"),
    ),
)

_EVIDENCE = SpecifyStage(
    id="ubd.stage2.evidence",
    name="Stage 2 — evidence",
    spine=5,
    scope_level="unit",
    inputs=(
        In(
            artifact_type=A.INTENT, cardinality="1..n", from_stage="ubd.stage1.desired_results"
        ),
        In(artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="ubd.step1.context"),
    ),
    outputs=(
        Out(
            artifact_type=A.EVIDENCE_SPEC,
            subtype="performance_task",
            cardinality="1..n",
            schema_ref="ext/ubd/grasps",
        ),
        Out(artifact_type=A.EVIDENCE_SPEC, subtype="other_evidence", cardinality="0..n"),
        Out(artifact_type=A.CRITERIA, cardinality="1..n"),
        Out(artifact_type=A.RUBRIC, cardinality="0..n"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="intent_x_evidence", cardinality="1"),
        Out(artifact_type=A.TAXONOMY_SELECTION, subtype="six_facets", cardinality="1"),
    ),
    generator=Generator(
        role="assessor",
        prompt_ref="prompts/ubd/stage2_generate",
        taxonomy_binding="six_facets",
    ),
    critic=Critic(
        role="UbD design-standards reviewer",
        prompt_ref="prompts/ubd/stage2_critique",
        criterion_doc="ubd.design_standards.stage2",
    ),
    checks=(
        Check(
            check="matrix_density",
            params={
                "matrix": "intent_x_evidence",
                "no_empty_rows": True,
                "no_empty_columns": True,
            },
        ),
        Check(
            check="coverage",
            params={
                "from": {"subtype": "transfer_goal"},
                "to": {"subtype": "performance_task"},
                "min": 1,
            },
        ),
        Check(
            check="vocabulary_coverage",
            params={
                "type": "Criteria",
                "vocab": ["impact", "content", "quality", "process"],
                "min_required": ["impact"],
            },
            severity="advisory",
        ),
    ),
    gate=RubricGate(
        reviewer_role="sme",
        presents=("EvidenceSpec.*", "CoverageMatrix.intent_x_evidence", "Rubric.*"),
    ),
    amendments=Amendments(emits_to=("ubd.stage1.desired_results",)),
)

_LEARNING_PLAN = SpecifyStage(
    id="ubd.stage3.learning_plan",
    name="Stage 3 — learning plan",
    spine=6,
    scope_level="unit",
    inputs=(
        In(
            artifact_type=A.INTENT, cardinality="1..n", from_stage="ubd.stage1.desired_results"
        ),
        In(
            artifact_type=A.EVIDENCE_SPEC, cardinality="1..n", from_stage="ubd.stage2.evidence"
        ),
        In(
            artifact_type=A.RISK_REGISTER,
            cardinality="0..n",
            from_stage="ubd.stage1.desired_results",
            required=False,
        ),
        In(artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="ubd.step1.context"),
    ),
    outputs=(
        Out(artifact_type=A.EVIDENCE_SPEC, subtype="pre_assessment", cardinality="1..n"),
        Out(
            artifact_type=A.EXPERIENCE, cardinality="1..n", schema_ref="ext/ubd/learning_event"
        ),
        Out(artifact_type=A.SEQUENCE, cardinality="1"),
        Out(artifact_type=A.RESOURCE_SELECTION, cardinality="0..n"),
        Out(artifact_type=A.MONITORING_PLAN, cardinality="1"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="intent_x_experience", cardinality="1"),
    ),
    generator=Generator(
        role="instructional planner",
        prompt_ref="prompts/ubd/stage3_generate",
        taxonomy_binding="amt",
    ),
    critic=Critic(
        role="UbD design-standards reviewer",
        prompt_ref="prompts/ubd/stage3_critique",
        criterion_doc="ubd.design_standards.stage3",
    ),
    checks=(
        Check(
            check="taxonomy_distribution",
            params={
                "type": "Experience",
                "dimension": "amt",
                "min_per_class": {"A": 1, "M": 1, "T": 1},
            },
        ),
        Check(
            check="vocabulary_coverage",
            params={
                "dimension": "whereto",
                "vocab": ["W", "H", "E", "R", "E2", "T", "O"],
                "min_each": 1,
            },
        ),
        Check(check="orphan", params={"type": "Experience", "must_link_to": "Intent"}),
        # W must come early: a plan that never tells the learner where it is
        # going has a hook and no destination.
        Check(
            check="ordering",
            params={"element": "W", "position_percentile_max": 0.25},
            severity="advisory",
        ),
        Check(
            check="budget",
            params={"dimension": "duration", "source": "ContextProfile.time_budget"},
        ),
    ),
    gate=RubricGate(
        reviewer_role="instructor",
        presents=("Experience.*", "CoverageMatrix.intent_x_experience", "MonitoringPlan"),
    ),
    amendments=Amendments(emits_to=("ubd.stage2.evidence", "ubd.stage1.desired_results")),
)

_ORGANIZATION = MatrixStage(
    id="ubd.stage3.organization",
    name="Stage 3 — sequencing (the O of WHERETO)",
    spine=7,
    scope_level="unit",
    inputs=(
        In(
            artifact_type=A.EXPERIENCE,
            cardinality="1..n",
            from_stage="ubd.stage3.learning_plan",
        ),
        In(
            artifact_type=A.INTENT, cardinality="1..n", from_stage="ubd.stage1.desired_results"
        ),
    ),
    outputs=(
        Out(artifact_type=A.SEQUENCE, subtype="event_order", cardinality="1"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="intent_x_experience", cardinality="1"),
    ),
    generator=Generator(role="instructional planner", prompt_ref="prompts/ubd/sequence"),
    checks=(
        Check(
            check="prerequisite_satisfied",
            params={"for": "performance_task", "required_from": "Intent.subtype.skill"},
        ),
    ),
    gate=RubricGate(reviewer_role="instructor", presents=("Sequence.event_order",)),
    amendments=Amendments(emits_to=("ubd.stage3.learning_plan",)),
)

ubd_pure = Preset(
    id="ubd.pure",
    name="Understanding by Design (unit plan)",
    version="1",
    description=(
        "The three UbD stages, ending at a unit plan rather than at materials "
        "-- UbD has no production half and assumes a teacher who will build. "
        "Choose this when the UbD process trail is itself the deliverable."
    ),
    spine_positions=(0, 1, 4, 5, 6, 7),
    stages=(_INTAKE, _CONTEXT, _DESIRED_RESULTS, _EVIDENCE, _LEARNING_PLAN, _ORGANIZATION),
    produces="design",
    renderer="ubd_template_2_0",
)
