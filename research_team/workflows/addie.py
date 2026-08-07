"""`addie.pure` — Analysis, Design, Development, Implementation, Evaluation.

Exists for the same reason `ubd.pure` does: a regulated team must be able to
show ADDIE phase sign-offs, and that is a conformance requirement rather than an
aesthetic preference.

**It has no value filter, and that is the point rather than an omission.** ADDIE
assumes the value question was settled before the designer was engaged --
appropriate to its procurement origins, and the reason it reproduces Tyler's
known criticisms in stronger form when imported into general education without
restoring Screen 1. `Preset.has_value_filter` is `False` here, deliberately and
visibly, so a user choosing it can be told what they are choosing. Restoring the
missing filter is one of the grafts `hybrid.default` exists to make.

Two false friends are avoided by construction, and both would be easy to get
wrong from the phase names alone. ADDIE's **Evaluation** phase is program
evaluation at spine [10], *not* Tyler's Q4 instrument design at [5]; conflating
them moves assessment design to the end of the pipeline, which is precisely the
failure UbD exists to prevent. And ADDIE's **Design** phase spans [4] through
[8-prep] -- it contains all three UbD stages plus storyboarding -- so it appears
here as four separate stages rather than one.
"""

from research_team.domain.workflow import (
    Amendments,
    Check,
    Critic,
    DecideStage,
    DecisionGate,
    FieldGate,
    FieldStage,
    GenerateStage,
    Generator,
    MatrixStage,
    MaturityGate,
    Preset,
    ProduceStage,
    RubricGate,
    Rung,
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

_GAP = DecideStage(
    id="addie.a1.intake_gap_framing",
    name="Analysis — intake and gap framing",
    spine=0,
    scope_level="course",
    inputs=(
        In(artifact_type=A.REQUEST_BRIEF, cardinality="1"),
        In(artifact_type=A.SOURCE_DOCUMENT, cardinality="0..n", required=False),
    ),
    outputs=(
        Out(artifact_type=A.SOURCE_CLAIM, cardinality="0..n"),
        Out(artifact_type=A.GAP_STATEMENT, cardinality="1"),
        Out(artifact_type=A.INTERVENTION_RECOMMENDATION, cardinality="1"),
        # B15's home. Consolidation merges disagreeing claims quietly -- two
        # SMEs giving different escalation thresholds become one node -- so the
        # contradiction has to have somewhere to be recorded before anything
        # downstream can be asked to adjudicate it. `0..n` because a corpus
        # with no disagreements is a real outcome; the file is still written,
        # empty and explicit, which is what makes "none found" a claim rather
        # than a silence.
        Out(artifact_type=A.CONTESTED_QUEUE, cardinality="0..n"),
        Out(artifact_type=A.OPEN_QUESTION, cardinality="0..n"),
        # Planned backward from Level 4 and authored here, because an
        # evaluation plan written after the course is a plan written to be
        # passed by it.
        Out(artifact_type=A.EVALUATION_PLAN, subtype="skeleton", cardinality="1"),
    ),
    tools=("list_sources", "read_source"),
    generator=Generator(role="performance consultant", prompt_ref="prompts/addie/gap_framing"),
    critic=Critic(
        role="intervention skeptic",
        prompt_ref="prompts/addie/gap_critique",
        criterion_doc="addie.intervention_criteria",
        # Must argue "no course" for every "course". This gate is the one
        # place any of the three traditions can conclude not to build.
        adversarial_second_pass=True,
    ),
    checks=(
        Check(
            check="shared.required_field_nondegenerate",
            params={
                "field": "GapStatement.business_metric",
                "reject_if": ["empty", "unmeasurable"],
            },
        ),
        Check(
            # Was a `must_enumerate` on format_conformance, which is what
            # vocabulary_coverage already is: every option considered at
            # least once, so a recommendation cannot quietly skip the
            # possibility that training is the wrong intervention.
            check="shared.vocabulary_coverage",
            params={
                "type": "InterventionRecommendation",
                "dimension": "options_considered",
                "vocab": ["training", "non_training", "hybrid"],
            },
        ),
        Check(
            check="shared.contradiction_escalation",
            params={"type": "ContestedQueue", "no_auto_resolve": True},
        ),
    ),
    gate=DecisionGate(
        reviewer_role="sponsor",
        presents=("GapStatement", "InterventionRecommendation", "critic.adversarial_case"),
    ),
)

_AUDIENCE = GenerateStage(
    id="addie.a3.audience_constraints",
    name="Analysis — audience and constraints",
    spine=1,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="addie.a1.intake_gap_framing",
            required=False,
        ),
        In(
            artifact_type=A.GAP_STATEMENT,
            cardinality="1",
            from_stage="addie.a1.intake_gap_framing",
        ),
    ),
    outputs=(
        Out(artifact_type=A.CONTEXT_PROFILE, cardinality="1"),
        Out(artifact_type=A.CONSTRAINT_REGISTER, cardinality="1"),
    ),
    generator=Generator(role="needs analyst", prompt_ref="prompts/addie/audience"),
    checks=(
        Check(
            check="shared.source_starvation",
            params={"routes": ["sme", "performance_data"], "min_claims_each": 1},
            severity="advisory",
        ),
    ),
    gate=RubricGate(
        reviewer_role="sponsor", presents=("ContextProfile", "ConstraintRegister")
    ),
)

_TASKS = GenerateStage(
    id="addie.a4.task_analysis",
    name="Analysis — hierarchical and cognitive task analysis",
    spine=1,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="addie.a1.intake_gap_framing",
            required=False,
        ),
        In(
            artifact_type=A.GAP_STATEMENT,
            cardinality="1",
            from_stage="addie.a1.intake_gap_framing",
        ),
    ),
    outputs=(
        Out(artifact_type=A.SOURCE_DOSSIER, subtype="task_analysis", cardinality="1"),
        Out(artifact_type=A.RISK_REGISTER, subtype="expert_gap_flag", cardinality="0..n"),
    ),
    generator=Generator(role="task analyst", prompt_ref="prompts/addie/task_analysis"),
    critic=Critic(
        role="expert-gap auditor",
        prompt_ref="prompts/addie/expert_gap",
        criterion_doc="addie.task_analysis_criteria",
    ),
    checks=(
        # The one high-value check that genuinely needs a model call: where did
        # the expert stop explaining? Each flag carries the quoted span that
        # provoked it, which is what makes the output reviewable at a glance.
        Check(
            check="addie.expert_gap_flag",
            params={"quote_span_required": True},
            severity="advisory",
        ),
    ),
    gate=RubricGate(
        reviewer_role="sme", presents=("SourceDossier.task_analysis", "RiskRegister.*")
    ),
)

_OBJECTIVES = SpecifyStage(
    id="addie.d1.objective_formulation",
    name="Design — objective formulation",
    spine=4,
    scope_level="module",
    inputs=(
        In(
            artifact_type=A.SOURCE_DOSSIER,
            cardinality="1..n",
            from_stage="addie.a4.task_analysis",
        ),
        In(
            artifact_type=A.CONTEXT_PROFILE,
            cardinality="1",
            from_stage="addie.a3.audience_constraints",
        ),
    ),
    outputs=(
        Out(artifact_type=A.INTENT, subtype="terminal_objective", cardinality="1..n"),
        Out(artifact_type=A.INTENT, subtype="enabling_objective", cardinality="0..n"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="objective_x_module", cardinality="1"),
    ),
    generator=Generator(
        role="objective author",
        prompt_ref="prompts/addie/objectives",
        taxonomy_binding="blooms_revised",
    ),
    critic=Critic(
        role="objective reviewer",
        prompt_ref="prompts/addie/objective_critique",
        criterion_doc="addie.objective_criteria",
    ),
    checks=(
        # ADDIE's observability rule, as `format_conformance` with a denylist.
        # Attached here and absent from `ubd.pure`, because L3 is a real
        # theoretical disagreement and not vocabulary drift.
        Check(
            check="shared.format_conformance",
            params={"verb_denylist": ["understand", "be aware of", "appreciate", "know"]},
        ),
        Check(
            check="shared.matrix_density",
            params={"matrix": "objective_x_module", "no_empty_rows": True},
        ),
    ),
    gate=RubricGate(reviewer_role="sme", presents=("Intent.*",)),
)

_ASSESSMENT = SpecifyStage(
    id="addie.d2.assessment_design",
    name="Design — assessment, before instruction and deliberately so",
    spine=5,
    scope_level="module",
    inputs=(
        In(
            artifact_type=A.INTENT,
            cardinality="1..n",
            from_stage="addie.d1.objective_formulation",
        ),
        In(
            artifact_type=A.CONSTRAINT_REGISTER,
            cardinality="1",
            from_stage="addie.a3.audience_constraints",
        ),
        In(
            artifact_type=A.RISK_REGISTER,
            subtype="expert_gap_flag",
            cardinality="0..n",
            from_stage="addie.a4.task_analysis",
            required=False,
        ),
    ),
    outputs=(
        Out(artifact_type=A.EVIDENCE_SPEC, subtype="assessment_item", cardinality="1..n"),
        Out(artifact_type=A.CRITERIA, subtype="mastery_rules", cardinality="1"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="intent_x_evidence", cardinality="1"),
    ),
    generator=Generator(
        role="assessment author",
        prompt_ref="prompts/addie/assessment_design",
        taxonomy_binding="blooms_revised",
        over_generate_factor=2,
    ),
    critic=Critic(
        role="item reviewer",
        prompt_ref="prompts/addie/item_critique",
        criterion_doc="addie.item_quality_criteria",
    ),
    checks=(
        Check(
            check="shared.matrix_density",
            params={"matrix": "intent_x_evidence", "no_empty_rows": True},
        ),
        # An item's cognitive level must match its parent objective's rather
        # than drifting down to recall, which is what an unchecked generator
        # writes because recall items are the easiest to produce.
        Check(
            check="shared.taxonomy_distribution",
            params={"dimension": "blooms_revised", "must_match_parent": "Intent.bloom_level"},
        ),
        Check(
            check="shared.provenance",
            params={
                "type": "EvidenceSpec.distractor",
                # `prefer_source: RiskRegister.expert_gap_flag` was here. A
                # preference is not a check -- there is no artifact state
                # that violates it -- so it belongs in the generator prompt,
                # and asserting it here would have made a nudge look like a
                # guarantee. What remains is the real constraint: a
                # distractor cites something.
            },
            severity="advisory",
        ),
    ),
    # A wrong answer key teaches the wrong thing and is then defended by the
    # system, so this gate shows the keys and not just the items.
    gate=RubricGate(
        reviewer_role="sme",
        presents=(
            "EvidenceSpec.assessment_item.*",
            "CoverageMatrix.intent_x_evidence",
            "answer_keys",
        ),
    ),
    amendments=Amendments(emits_to=("addie.d1.objective_formulation",)),
)

_TREATMENT = SpecifyStage(
    id="addie.d4.treatment",
    name="Design — instructional strategy and treatment",
    spine=6,
    scope_level="module",
    inputs=(
        In(
            artifact_type=A.INTENT,
            cardinality="1..n",
            from_stage="addie.d1.objective_formulation",
        ),
        In(
            artifact_type=A.EVIDENCE_SPEC,
            cardinality="1..n",
            from_stage="addie.d2.assessment_design",
        ),
        In(
            artifact_type=A.CONSTRAINT_REGISTER,
            cardinality="1",
            from_stage="addie.a3.audience_constraints",
        ),
    ),
    outputs=(
        Out(artifact_type=A.EXPERIENCE, subtype="treatment", cardinality="1..n"),
        Out(artifact_type=A.STYLE_GUIDE, cardinality="1"),
        Out(artifact_type=A.RESOURCE_SELECTION, cardinality="0..n"),
    ),
    generator=Generator(role="instructional strategist", prompt_ref="prompts/addie/treatment"),
    checks=(
        Check(check="shared.orphan", params={"type": "Experience", "must_link_to": "Intent"}),
    ),
    gate=RubricGate(reviewer_role="sme", presents=("Experience.*", "StyleGuide")),
    amendments=Amendments(emits_to=("addie.d2.assessment_design",)),
)

_COURSE_MAP = MatrixStage(
    id="addie.d3.course_map",
    name="Design — course map",
    spine=7,
    scope_level="course",
    inputs=(
        In(artifact_type=A.EXPERIENCE, cardinality="1..n", from_stage="addie.d4.treatment"),
        In(
            artifact_type=A.INTENT,
            cardinality="1..n",
            from_stage="addie.d1.objective_formulation",
        ),
    ),
    outputs=(
        Out(artifact_type=A.SEQUENCE, subtype="course_map", cardinality="1"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="objective_x_module", cardinality="1"),
    ),
    generator=Generator(role="course architect", prompt_ref="prompts/addie/course_map"),
    checks=(
        Check(
            check="shared.prerequisite_satisfied",
            params={"for": "Experience", "required_from": "Intent"},
        ),
        Check(
            check="shared.budget",
            params={"dimension": "duration", "source": "ConstraintRegister.seat_time"},
        ),
    ),
    gate=RubricGate(reviewer_role="sponsor", presents=("Sequence.course_map",)),
)

_STORYBOARD = SpecifyStage(
    id="addie.d5.storyboarding",
    name="Design — storyboarding",
    spine=8,
    scope_level="asset",
    inputs=(
        In(artifact_type=A.EXPERIENCE, cardinality="1..n", from_stage="addie.d4.treatment"),
        In(artifact_type=A.SEQUENCE, cardinality="1", from_stage="addie.d3.course_map"),
        In(artifact_type=A.STYLE_GUIDE, cardinality="1", from_stage="addie.d4.treatment"),
    ),
    outputs=(Out(artifact_type=A.PRODUCTION_SPEC, cardinality="1..n"),),
    generator=Generator(role="storyboard author", prompt_ref="prompts/addie/storyboard"),
    critic=Critic(
        role="content accuracy reviewer",
        prompt_ref="prompts/addie/storyboard_critique",
        criterion_doc="addie.style_guide",
    ),
    checks=(
        Check(
            check="shared.provenance",
            params={"type": "ProductionSpec", "must_cite": "SourceClaim"},
        ),
    ),
    gate=RubricGate(reviewer_role="sme", presents=("ProductionSpec.*",)),
)

_BUILD = ProduceStage(
    id="addie.v1.build",
    name="Development — alpha, beta, gold",
    spine=8,
    scope_level="module",
    inputs=(
        In(
            artifact_type=A.PRODUCTION_SPEC,
            cardinality="1..n",
            from_stage="addie.d5.storyboarding",
        ),
        In(artifact_type=A.STYLE_GUIDE, cardinality="1", from_stage="addie.d4.treatment"),
        In(
            artifact_type=A.CONSTRAINT_REGISTER,
            cardinality="1",
            from_stage="addie.a3.audience_constraints",
        ),
    ),
    outputs=(
        Out(artifact_type=A.BUILD, cardinality="1..n"),
        Out(artifact_type=A.DEFECT_LOG, cardinality="1"),
        Out(artifact_type=A.REVIEW_COMMENT_LOG, cardinality="1"),
        Out(artifact_type=A.CONFORMANCE_REPORT, subtype="accessibility", cardinality="1"),
    ),
    generator=Generator(role="developer", prompt_ref="prompts/addie/build"),
    critic=Critic(role="QA", prompt_ref="prompts/addie/qa", criterion_doc="addie.qa_criteria"),
    checks=(
        Check(
            check="shared.provenance",
            params={"type": "Build.content_claim", "must_cite": "SourceClaim"},
        ),
        Check(
            check="addie.change_scope",
            params={
                "maturity": "beta",
                "permitted": ["cosmetic", "verification"],
                "forbidden": ["substantive"],
            },
        ),
        Check(
            check="addie.change_scope",
            params={
                "maturity": "gold",
                "permitted": ["packaging"],
                "forbidden": ["substantive", "cosmetic"],
            },
        ),
    ),
    gate=MaturityGate(
        reviewer_role="sponsor",
        presents=("Build.*", "DefectLog", "ConformanceReport.accessibility"),
        rungs=(
            Rung(
                name="alpha",
                reviewer_role="sme",
                permitted_change=("substantive",),
                decisions=("approve", "approve_with_edits", "send_back"),
            ),
            Rung(
                name="beta",
                reviewer_role="sme",
                permitted_change=("cosmetic", "verification"),
                forbidden_change=("substantive",),
            ),
            Rung(
                name="gold",
                reviewer_role="lms_admin",
                permitted_change=("packaging",),
                forbidden_change=("substantive", "cosmetic"),
            ),
        ),
    ),
    amendments=Amendments(emits_to=("addie.d5.storyboarding",)),
)

_TRYOUT = FieldStage(
    id="addie.v2.tryout",
    name="Formative tryout with two or three representative learners",
    spine=8,
    scope_level="module",
    inputs=(In(artifact_type=A.BUILD, cardinality="1..n", from_stage="addie.v1.build"),),
    outputs=(
        Out(artifact_type=A.OUTCOME_EVIDENCE, subtype="tryout", cardinality="1"),
        Out(artifact_type=A.DEFECT_LOG, cardinality="1"),
    ),
    gate=FieldGate(
        reviewer_role="learner",
        presents=("Build.alpha",),
        # Between Alpha and Beta: this is what promotes a build out of
        # alpha, so alpha is what the learners must be shown.
        gates_promotion_from="alpha",
    ),
    amendments=Amendments(emits_to=("addie.v1.build",)),
)

_IMPLEMENT = ProduceStage(
    id="addie.i1.implementation",
    name="Implementation — deployment, pilot, enablement",
    spine=9,
    scope_level="course",
    inputs=(In(artifact_type=A.BUILD, cardinality="1..n", from_stage="addie.v1.build"),),
    outputs=(
        Out(artifact_type=A.TRACKING_PACKAGE, cardinality="1"),
        Out(artifact_type=A.LMS_CONFIGURATION, cardinality="1"),
        Out(artifact_type=A.MONITORING_PLAN, cardinality="1"),
    ),
    generator=Generator(role="deployment lead", prompt_ref="prompts/addie/implement"),
    gate=MaturityGate(
        reviewer_role="lms_admin",
        presents=("TrackingPackage", "LMSConfigurationRecord"),
        rungs=(
            Rung(name="pilot", reviewer_role="learner", permitted_change=("configuration",)),
            Rung(name="release", reviewer_role="sponsor", permitted_change=()),
        ),
    ),
)

_EVALUATION = GenerateStage(
    id="addie.e1.evaluation",
    name="Evaluation — Kirkpatrick L1 to L4",
    spine=10,
    scope_level="program",
    inputs=(
        In(artifact_type=A.OUTCOME_EVIDENCE, cardinality="1..n", from_stage="addie.v2.tryout"),
        In(
            artifact_type=A.EVALUATION_PLAN,
            cardinality="1",
            from_stage="addie.a1.intake_gap_framing",
        ),
        In(
            artifact_type=A.MONITORING_PLAN,
            cardinality="1",
            from_stage="addie.i1.implementation",
        ),
    ),
    outputs=(
        Out(artifact_type=A.OUTCOME_EVIDENCE, cardinality="1..n"),
        Out(artifact_type=A.REVISION_PROPOSAL, cardinality="0..n"),
    ),
    generator=Generator(role="evaluation analyst", prompt_ref="prompts/addie/evaluate"),
    checks=(
        Check(
            check="shared.provenance",
            params={"type": "RevisionProposal", "must_cite": "Intent"},
        ),
    ),
    gate=RubricGate(
        reviewer_role="sponsor", presents=("OutcomeEvidence.*", "RevisionProposal.*")
    ),
    # An L3 failure indicts the gap statement, not the storyboard. Routing it
    # back to A1 is what makes "should this have been a course" answerable
    # with evidence the second time round.
    amendments=Amendments(
        emits_to=(
            "addie.a1.intake_gap_framing",
            "addie.d1.objective_formulation",
            "addie.d2.assessment_design",
        )
    ),
)

addie_pure = Preset(
    id="addie.pure",
    name="ADDIE (materials and delivery)",
    version="1",
    description=(
        "Analysis, Design, Development, Implementation, Evaluation, with the "
        "alpha/beta/gold ladder and Kirkpatrick outcomes. The only tradition "
        "with a production half -- and the only one with no value filter, so "
        "it takes the question of whether this should be taught as settled."
    ),
    spine_positions=(0, 1, 4, 5, 6, 7, 8, 9, 10),
    stages=(
        _GAP,
        _AUDIENCE,
        _TASKS,
        _OBJECTIVES,
        _ASSESSMENT,
        _TREATMENT,
        _COURSE_MAP,
        _STORYBOARD,
        _BUILD,
        _TRYOUT,
        _IMPLEMENT,
        _EVALUATION,
    ),
    produces="materials",
    renderer="addie_course_design_document",
)
