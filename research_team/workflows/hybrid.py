"""`hybrid.default` — Tyler's sourcing, UbD's design, ADDIE's production.

The default, and not a compromise. Each methodology is strong exactly where the
others are weak: Tyler owns the front end and has no production half at all; UbD
owns evidence-before-experiences and takes a standards document as its only
input; ADDIE owns production, delivery and outcome measurement and has no value
filter whatsoever. Every graft below closes a hole one tradition documented in
another, and none of them is speculative.

Locking a user into one pure methodology asks them to already know which
structural defect they can live with, which is exactly the expertise they are
using the tool to avoid needing.
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
    LedgerGate,
    MatrixStage,
    MaturityGate,
    Preset,
    ProduceStage,
    RubricGate,
    Rung,
    ScreeningCritic,
    ScreenStage,
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
    id="tyler.step0.intake",
    name="Corpus intake and three-source routing",
    spine=0,
    scope_level="course",
    inputs=(
        In(artifact_type=A.SOURCE_DOCUMENT, cardinality="1..n"),
        In(artifact_type=A.SCOPE_STATEMENT, cardinality="1"),
    ),
    outputs=(
        Out(artifact_type=A.SOURCE_CLAIM, cardinality="1..n"),
        Out(artifact_type=A.OPEN_QUESTION, cardinality="0..n"),
    ),
    tools=("list_sources", "read_source", "graph_search"),
    generator=Generator(role="corpus router", prompt_ref="prompts/tyler/intake"),
    checks=(
        Check(
            check="provenance", params={"type": "SourceClaim", "must_cite": "SourceDocument"}
        ),
        Check(check="contradiction_escalation", params={"no_auto_resolve": True}),
    ),
)

_FRAMING = DecideStage(
    id="hybrid.step1.framing",
    name="Context framing — is this a course at all?",
    spine=1,
    scope_level="course",
    inputs=(
        In(artifact_type=A.REQUEST_BRIEF, cardinality="1"),
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="tyler.step0.intake",
            required=False,
        ),
    ),
    outputs=(
        Out(artifact_type=A.CONTEXT_PROFILE, cardinality="1"),
        Out(artifact_type=A.CONSTRAINT_REGISTER, cardinality="1"),
        Out(artifact_type=A.GAP_STATEMENT, cardinality="1"),
        Out(artifact_type=A.INTERVENTION_RECOMMENDATION, cardinality="1"),
        Out(artifact_type=A.EVALUATION_PLAN, subtype="skeleton", cardinality="1"),
    ),
    tools=("list_sources", "read_source"),
    generator=Generator(role="performance consultant", prompt_ref="prompts/addie/gap_framing"),
    critic=Critic(
        role="intervention skeptic",
        prompt_ref="prompts/addie/gap_critique",
        criterion_doc="addie.intervention_criteria",
        adversarial_second_pass=True,
    ),
    checks=(
        Check(
            check="required_field_nondegenerate",
            params={
                "field": "GapStatement.business_metric",
                "reject_if": ["empty", "unmeasurable"],
            },
        ),
    ),
    # ADDIE's A1 grafted onto Tyler's front end. This is the halt point, and
    # the only cheap one: everything after it has sunk cost behind it.
    gate=DecisionGate(
        reviewer_role="sponsor",
        presents=("GapStatement", "InterventionRecommendation", "critic.adversarial_case"),
    ),
)

_SOURCES = GenerateStage(
    id="tyler.step1a.source_analysis",
    name="Three-source analysis",
    spine=1,
    scope_level="course",
    inputs=(
        In(artifact_type=A.SOURCE_CLAIM, cardinality="1..n", from_stage="tyler.step0.intake"),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
    ),
    outputs=(Out(artifact_type=A.SOURCE_DOSSIER, cardinality="1..n"),),
    tools=("list_sources", "read_source", "graph_search"),
    generator=Generator(
        role="three disjoint analysts (learner / world / discipline)",
        prompt_ref="prompts/tyler/source_analysis",
    ),
    critic=Critic(
        role="bias auditor",
        prompt_ref="prompts/tyler/source_critique",
        criterion_doc="tyler.source_bias_profiles",
    ),
    checks=(
        # A source with near-zero claims is a finding, not a silence. This is
        # what makes single-source design detectable rather than invisible.
        Check(
            check="source_starvation",
            params={
                "routes": ["learner", "contemporary_life", "discipline"],
                "min_claims_each": 1,
            },
        ),
        Check(check="required_field_nondegenerate", params={"field": "known_bias_statement"}),
    ),
    gate=RubricGate(
        reviewer_role="sme", presents=("SourceDossier.*", "checks.source_starvation")
    ),
)

_CANDIDATES = GenerateStage(
    id="tyler.step1b.candidates",
    name="Candidate objective pool",
    spine=2,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.SOURCE_DOSSIER,
            cardinality="1..n",
            from_stage="tyler.step1a.source_analysis",
        ),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
    ),
    outputs=(
        Out(artifact_type=A.INTENT, subtype="candidate", cardinality="1..n"),
        Out(artifact_type=A.EXCLUSION, cardinality="0..n"),
        Out(artifact_type=A.RISK_REGISTER, subtype="misconception", cardinality="0..n"),
    ),
    generator=Generator(
        role="curriculum designer",
        prompt_ref="prompts/tyler/candidates",
        # Over-generated by doctrine, so the screens have something to cut. A
        # pool the size of the answer makes the screens rubber stamps.
        over_generate_factor=5,
    ),
    checks=(
        Check(check="provenance", params={"type": "Intent", "must_cite": "SourceDossier"}),
    ),
)

_PHILOSOPHY = ScreenStage(
    id="tyler.step2.philosophy_screen",
    name="Screen 1 — educational and social philosophy",
    spine=3,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.INTENT,
            subtype="candidate",
            cardinality="1..n",
            from_stage="tyler.step1b.candidates",
        ),
        # Authored, versioned, human-signed. Deliberately not derived from the
        # corpus that produced the candidates -- that is the tautology guard.
        In(artifact_type=A.CRITERION_DOCUMENT, subtype="philosophy", cardinality="1"),
    ),
    outputs=(
        Out(artifact_type=A.VERDICT_LEDGER, subtype="philosophy", cardinality="1"),
        Out(artifact_type=A.INTENT, subtype="candidate", cardinality="0..n"),
        Out(artifact_type=A.EXCLUSION, cardinality="0..n"),
        Out(artifact_type=A.CONTESTED_QUEUE, cardinality="0..n"),
    ),
    critic=ScreeningCritic(
        role="philosophy screener",
        prompt_ref="prompts/tyler/screen1",
        criterion_doc="tyler.philosophy_statement",
    ),
    checks=(
        Check(
            check="verdict_citation",
            params={"ledger": "philosophy", "on_retrieval_failure": "force_verdict_contested"},
        ),
        Check(
            check="criterion_doc_authored",
            params={
                "doc": "tyler.philosophy_statement",
                "require_human_signature": True,
                "forbid_derivation_from": "SourceClaim",
            },
        ),
        Check(check="exclusion_ledger", params={"no_silent_drops": True}),
        Check(
            check="self_review_separation",
            params={"generator_stage": "tyler.step1b.candidates"},
        ),
        Check(
            check="prune_ratio", params={"expected_range": [0.15, 0.40]}, severity="advisory"
        ),
    ),
    gate=LedgerGate(
        reviewer_role="sponsor",
        presents=("VerdictLedger.philosophy.reject", "VerdictLedger.philosophy.contested"),
    ),
    amendments=Amendments(emits_to=("tyler.step1b.candidates",)),
)

_PSYCHOLOGY = ScreenStage(
    id="tyler.step3.psychology_screen",
    name="Screen 2 — learning psychology and feasibility",
    spine=3,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.INTENT,
            subtype="candidate",
            cardinality="1..n",
            from_stage="tyler.step2.philosophy_screen",
        ),
        In(artifact_type=A.CRITERION_DOCUMENT, subtype="learning_theory", cardinality="1"),
        In(
            artifact_type=A.SOURCE_DOSSIER,
            cardinality="1..n",
            from_stage="tyler.step1a.source_analysis",
        ),
    ),
    outputs=(
        Out(artifact_type=A.VERDICT_LEDGER, subtype="psychology", cardinality="1"),
        Out(artifact_type=A.INTENT, subtype="candidate", cardinality="0..n"),
        Out(artifact_type=A.EXCLUSION, cardinality="0..n"),
        Out(artifact_type=A.CONTESTED_QUEUE, cardinality="0..n"),
    ),
    critic=ScreeningCritic(
        role="feasibility screener",
        prompt_ref="prompts/tyler/screen2",
        criterion_doc="tyler.learning_theory_statement",
    ),
    checks=(
        Check(check="verdict_citation", params={"ledger": "psychology"}),
        Check(check="exclusion_ledger", params={"no_silent_drops": True}),
        Check(
            check="prerequisite_satisfied",
            params={"for": "Intent", "required_from": "ContextProfile.entry_state"},
        ),
    ),
    gate=LedgerGate(
        reviewer_role="sme",
        presents=("VerdictLedger.psychology.reject", "VerdictLedger.psychology.contested"),
    ),
    amendments=Amendments(emits_to=("tyler.step1b.candidates",)),
)

_INTENT_SPEC = SpecifyStage(
    id="hybrid.step4.intent_spec",
    name="Intent specification — behaviour and content, UbD subtypes",
    spine=4,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.INTENT,
            cardinality="1..n",
            from_stage="tyler.step3.psychology_screen",
        ),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
    ),
    outputs=(
        Out(artifact_type=A.INTENT, cardinality="1..n"),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="behaviour_x_content", cardinality="1"),
    ),
    generator=Generator(
        role="objective author",
        prompt_ref="prompts/hybrid/intent_spec",
        taxonomy_binding="hybrid_per_subtype",
    ),
    critic=Critic(role="format reviewer", prompt_ref="prompts/hybrid/intent_critique"),
    checks=(
        # L3, authored deliberately rather than defaulted: the observability
        # rule is applied per subtype. `understanding` keeps UbD's "students
        # will understand that" stem; `skill` takes ADDIE's verb denylist.
        # One `Intent` schema cannot satisfy both without picking a side.
        Check(
            check="format_conformance",
            params={"subtype": "understanding", "stem": "Students will understand that"},
        ),
        Check(
            check="format_conformance",
            params={
                "subtype": "skill",
                "verb_denylist": ["understand", "be aware of", "appreciate"],
            },
        ),
        Check(
            check="matrix_density",
            params={"matrix": "behaviour_x_content", "no_empty_rows": True},
        ),
        Check(check="budget", params={"dimension": "intent_count"}, severity="advisory"),
    ),
    gate=RubricGate(
        reviewer_role="sme", presents=("Intent.*", "CoverageMatrix.behaviour_x_content")
    ),
)

_EVIDENCE = SpecifyStage(
    id="ubd.stage2.evidence",
    name="Evidence design — GRASPS tasks before any activity exists",
    spine=5,
    scope_level="unit",
    inputs=(
        In(artifact_type=A.INTENT, cardinality="1..n", from_stage="hybrid.step4.intent_spec"),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
        In(
            artifact_type=A.SOURCE_CLAIM,
            cardinality="0..n",
            from_stage="tyler.step0.intake",
            required=False,
        ),
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
        role="assessor — think like an assessor before designing lessons",
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
        # A transfer goal needs a task, not a quiz.
        Check(
            check="coverage",
            params={
                "from": {"subtype": "transfer_goal"},
                "to": {"subtype": "performance_task"},
                "min": 1,
            },
        ),
        Check(
            check="format_conformance",
            params={
                "schema": "ext/ubd/grasps",
                "all_fields_nonempty": True,
                "reject_generic": True,
            },
        ),
    ),
    gate=RubricGate(
        reviewer_role="sme",
        presents=("EvidenceSpec.*", "CoverageMatrix.intent_x_evidence", "Rubric.*"),
    ),
    amendments=Amendments(emits_to=("hybrid.step4.intent_spec",)),
)

_LEARNING_PLAN = SpecifyStage(
    id="ubd.stage3.learning_plan",
    name="Experience design — A/M/T coded learning events",
    spine=6,
    scope_level="unit",
    inputs=(
        In(artifact_type=A.INTENT, cardinality="1..n", from_stage="hybrid.step4.intent_spec"),
        # The UbD inversion, as a DAG edge rather than a philosophy: evidence
        # is an input to experience design, so it cannot be designed after.
        In(
            artifact_type=A.EVIDENCE_SPEC, cardinality="1..n", from_stage="ubd.stage2.evidence"
        ),
        In(
            artifact_type=A.RISK_REGISTER,
            cardinality="0..n",
            from_stage="tyler.step1b.candidates",
            required=False,
        ),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
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
        # The single highest-value check in the whole comparison: it catches
        # an all-acquisition plan, which is what an unchecked generator writes.
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
        Check(
            check="budget",
            params={"dimension": "duration", "source": "ContextProfile.time_budget"},
        ),
    ),
    gate=RubricGate(
        reviewer_role="instructor",
        presents=("Sequence", "CoverageMatrix.intent_x_experience", "MonitoringPlan"),
    ),
    amendments=Amendments(emits_to=("ubd.stage2.evidence", "hybrid.step4.intent_spec")),
)

_ORGANIZATION = MatrixStage(
    id="tyler.step6.organization",
    name="Organization — continuity, sequence, integration",
    spine=7,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.EXPERIENCE,
            cardinality="1..n",
            from_stage="ubd.stage3.learning_plan",
        ),
        In(artifact_type=A.INTENT, cardinality="1..n", from_stage="hybrid.step4.intent_spec"),
        In(
            artifact_type=A.CONTEXT_PROFILE, cardinality="1", from_stage="hybrid.step1.framing"
        ),
    ),
    outputs=(
        Out(artifact_type=A.SEQUENCE, subtype="thread_registry", cardinality="1"),
        Out(
            artifact_type=A.SEQUENCE,
            subtype="sequence_map",
            cardinality="1",
            schema_ref="ext/tyler/sequence_map",
        ),
        Out(artifact_type=A.COVERAGE_MATRIX, subtype="thread_x_thread", cardinality="1"),
    ),
    generator=Generator(role="curriculum organizer", prompt_ref="prompts/tyler/organize"),
    critic=Critic(
        role="organization auditor",
        prompt_ref="prompts/tyler/organize_critique",
        criterion_doc="tyler.organization_criteria",
    ),
    checks=(
        Check(check="recurrence", params={"type": "Sequence.thread", "min_recurrences": 3}),
        # Sequence, not mere continuity. Without the escalation descriptor a
        # topic that recurs three times at the same level looks like a spiral.
        Check(
            check="required_field_nondegenerate",
            params={
                "field": "escalation_descriptor",
                "per": "thread_recurrence",
                "reject_if": ["empty", "duplicate_of_previous"],
            },
        ),
        Check(
            check="matrix_density",
            params={"matrix": "thread_x_thread", "min_contact_points": 1},
            severity="advisory",
        ),
    ),
    gate=RubricGate(
        blocking=False,
        reviewer_role="instructor",
        presents=("Sequence.sequence_map", "checks.required_field_nondegenerate"),
    ),
    amendments=Amendments(emits_to=("ubd.stage3.learning_plan",)),
)

_STORYBOARD = SpecifyStage(
    id="addie.d5.storyboarding",
    name="Storyboarding",
    spine=8,
    scope_level="module",
    inputs=(
        In(
            artifact_type=A.EXPERIENCE,
            cardinality="1..n",
            from_stage="ubd.stage3.learning_plan",
        ),
        In(
            artifact_type=A.SEQUENCE, cardinality="1..n", from_stage="tyler.step6.organization"
        ),
        In(
            artifact_type=A.CONSTRAINT_REGISTER,
            cardinality="1",
            from_stage="hybrid.step1.framing",
        ),
    ),
    outputs=(
        Out(artifact_type=A.PRODUCTION_SPEC, cardinality="1..n"),
        Out(artifact_type=A.STYLE_GUIDE, cardinality="1"),
    ),
    generator=Generator(role="storyboard author", prompt_ref="prompts/addie/storyboard"),
    critic=Critic(
        role="content accuracy reviewer",
        prompt_ref="prompts/addie/storyboard_critique",
        criterion_doc="addie.style_guide",
    ),
    checks=(
        Check(
            check="provenance", params={"type": "ProductionSpec", "must_cite": "SourceClaim"}
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
        In(artifact_type=A.STYLE_GUIDE, cardinality="1", from_stage="addie.d5.storyboarding"),
        In(
            artifact_type=A.CONSTRAINT_REGISTER,
            cardinality="1",
            from_stage="hybrid.step1.framing",
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
            check="provenance",
            params={"type": "Build.content_claim", "must_cite": "SourceClaim"},
        ),
        Check(
            check="change_scope",
            params={
                "maturity": "beta",
                "permitted": ["cosmetic", "verification"],
                "forbidden": ["substantive"],
            },
        ),
        Check(
            check="change_scope",
            params={
                "maturity": "gold",
                "permitted": ["packaging"],
                "forbidden": ["substantive", "cosmetic"],
            },
        ),
    ),
    gate=MaturityGate(
        reviewer_role="sponsor",
        presents=("Build.*", "DefectLog"),
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
    name="Formative tryout with real learners",
    spine=8,
    scope_level="module",
    inputs=(In(artifact_type=A.BUILD, cardinality="1..n", from_stage="addie.v1.build"),),
    outputs=(
        Out(artifact_type=A.OUTCOME_EVIDENCE, subtype="tryout", cardinality="1"),
        Out(artifact_type=A.DEFECT_LOG, cardinality="1"),
    ),
    # Its own stage rather than a rung of the build ladder, because nothing
    # here is executable: the input is two or three people who are not in the
    # pipeline. Marked unsatisfied rather than skipped, so a course that has
    # never met a learner carries that on its face.
    gate=FieldGate(reviewer_role="learner", presents=("Build.beta",)),
    amendments=Amendments(emits_to=("addie.v1.build",)),
)

_IMPLEMENTATION = ProduceStage(
    id="addie.i1.implementation",
    name="Delivery",
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

_OUTCOMES = GenerateStage(
    id="hybrid.step10.outcomes",
    name="Outcome evidence and defect localization",
    spine=10,
    scope_level="course",
    inputs=(
        In(
            artifact_type=A.OUTCOME_EVIDENCE,
            cardinality="1..n",
            from_stage="addie.v2.tryout",
        ),
        In(
            artifact_type=A.EVALUATION_PLAN, cardinality="1", from_stage="hybrid.step1.framing"
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
    generator=Generator(role="evaluation analyst", prompt_ref="prompts/hybrid/outcomes"),
    checks=(
        # Tyler's contribution here is localization: a defect is attributed to
        # an objective, an experience or the organization, not to "the course".
        Check(check="provenance", params={"type": "RevisionProposal", "must_cite": "Intent"}),
        Check(check="recurrence", params={"type": "OutcomeEvidence", "min_occurrences": 2}),
    ),
    gate=RubricGate(
        reviewer_role="sponsor", presents=("OutcomeEvidence.*", "RevisionProposal.*")
    ),
    amendments=Amendments(
        emits_to=(
            "hybrid.step4.intent_spec",
            "ubd.stage3.learning_plan",
            "tyler.step6.organization",
        )
    ),
)

hybrid_default = Preset(
    id="hybrid.default",
    name="Research to course (recommended)",
    version="1",
    description=(
        "Tyler's sourcing and value screens, UbD's evidence-first design, "
        "ADDIE's production and outcome measurement. Named rather than "
        "presented as a neutral house process, so anyone who knows the field "
        "can see what it is and anyone who does not gets the vocabulary."
    ),
    spine_positions=tuple(range(11)),
    stages=(
        _INTAKE,
        _FRAMING,
        _SOURCES,
        _CANDIDATES,
        _PHILOSOPHY,
        _PSYCHOLOGY,
        _INTENT_SPEC,
        _EVIDENCE,
        _LEARNING_PLAN,
        _ORGANIZATION,
        _STORYBOARD,
        _BUILD,
        _TRYOUT,
        _IMPLEMENTATION,
        _OUTCOMES,
    ),
    produces="materials",
    # Where methodology choice genuinely changes the work rather than the
    # vocabulary: filtering, evidence, experience, production.
    overridable_spine_positions=(3, 5, 6, 8),
)
