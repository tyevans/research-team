"""Preset validation, and the three shipped presets held to it.

A preset is data, so validation is the only thing standing between a typo and a
workflow that fails an hour into a run. Most of this file is therefore about
malformed presets rather than well-formed ones: each rule gets a preset that
breaks it and nothing else, so a failure names the rule.

The three shipped presets are then run through the same rules. That is not a
formality -- they are the first real evidence the schema can express the three
methodologies without a special case.
"""

import pytest

from research_team.domain.workflow import (
    ArtifactType,
    Check,
    DecideStage,
    DecisionGate,
    FieldGate,
    FieldStage,
    GenerateStage,
    Generator,
    LedgerGate,
    Preset,
    PresetError,
    ScreeningCritic,
    ScreenStage,
    SpecifyStage,
    StageInput,
    StageOutput,
    problems,
)
from research_team.workflows import PRESETS, addie_pure, hybrid_default, ubd_pure


def _generator(role: str = "author") -> Generator:
    return Generator(role=role, prompt_ref="prompts/test/generate")


def _intake(stage_id: str = "s0", spine: int = 0) -> GenerateStage:
    return GenerateStage(
        id=stage_id,
        name="Intake",
        spine=spine,
        scope_level="course",
        inputs=(StageInput(artifact_type=ArtifactType.SOURCE_DOCUMENT, cardinality="1..n"),),
        outputs=(StageOutput(artifact_type=ArtifactType.SOURCE_CLAIM, cardinality="1..n"),),
        generator=_generator(),
    )


def _halt_stage(stage_id: str = "decide", spine: int = 1) -> DecideStage:
    """Every preset needs one of these; most tests do not care about it."""
    return DecideStage(
        id=stage_id,
        name="Is this a course at all?",
        spine=spine,
        scope_level="course",
        inputs=(
            StageInput(
                artifact_type=ArtifactType.SOURCE_CLAIM,
                cardinality="0..n",
                from_stage="s0",
                required=False,
            ),
        ),
        outputs=(StageOutput(artifact_type=ArtifactType.CONTEXT_PROFILE, cardinality="1"),),
        generator=_generator("performance consultant"),
        gate=DecisionGate(reviewer_role="sponsor", presents=("GapStatement",)),
    )


def _preset(*stages, **overrides) -> Preset:
    """A minimally valid preset, so each test can break exactly one thing."""
    stages = stages or (_intake(), _halt_stage())
    fields = {
        "id": "test.preset",
        "name": "Test",
        "version": "1",
        "description": "A preset for testing.",
        "spine_positions": tuple(sorted({stage.spine for stage in stages})),
        "stages": stages,
        "produces": "design",
    }
    fields.update(overrides)
    return Preset(**fields)


# --- the spine --------------------------------------------------------------


def test_a_spine_position_above_ten_is_rejected() -> None:
    with pytest.raises(ValueError, match="spine"):
        _intake(spine=11)


def test_a_negative_spine_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="spine"):
        _intake(spine=-1)


def test_every_spine_position_is_named() -> None:
    """The names are what the UI shows. A gap would render a bare integer."""
    from research_team.domain.workflow import SPINE_NAMES

    assert sorted(SPINE_NAMES) == list(range(11))


# --- kind is load-bearing, and modelled as such -----------------------------


def test_a_screen_stage_has_no_generator_field_at_all() -> None:
    """Not "must be None" -- absent. A screen that generates its own candidates
    is self-screening, which the research found yields near-100% pass rates.
    Making it unrepresentable is stronger than validating it away."""
    assert "generator" not in ScreenStage.model_fields


def test_a_screen_stage_requires_a_criterion_document() -> None:
    with pytest.raises(ValueError):
        ScreeningCritic(role="screener", prompt_ref="p")


def test_a_field_stage_has_neither_generator_nor_critic() -> None:
    """A field gate is evidence from real humans outside the pipeline. There is
    nothing for an agent to execute, so there is nothing to prompt."""
    assert "generator" not in FieldStage.model_fields
    assert "critic" not in FieldStage.model_fields


def test_halt_is_not_available_on_a_non_decision_gate() -> None:
    with pytest.raises(ValueError, match="halt"):
        LedgerGate(reviewer_role="sponsor", decisions=("approve", "halt"))


def test_a_decision_gate_offers_halt_by_default() -> None:
    assert "halt" in DecisionGate(reviewer_role="sponsor").decisions


def test_a_field_gate_offers_only_approve_and_send_back() -> None:
    assert set(FieldGate(reviewer_role="learner").decisions) == {"approve", "send_back"}


# --- input chaining ---------------------------------------------------------


def test_an_input_nothing_produces_is_rejected() -> None:
    """The rule that catches the expensive failure: a stage consuming an
    artifact type no earlier stage emits fails halfway through a run."""
    consumer = SpecifyStage(
        id="s1",
        name="Consumer",
        spine=5,
        scope_level="course",
        inputs=(
            StageInput(
                artifact_type=ArtifactType.EVIDENCE_SPEC, cardinality="1..n", from_stage="s0"
            ),
        ),
        outputs=(StageOutput(artifact_type=ArtifactType.RUBRIC, cardinality="1"),),
        generator=_generator(),
    )
    with pytest.raises(PresetError, match="EvidenceSpec"):
        _preset(_intake(), _halt_stage(), consumer)


def test_an_input_from_a_later_stage_is_rejected() -> None:
    """Ordering, not just existence. A backward edge is an amendment and has
    its own field; smuggling one in as an input would deadlock the run."""
    early = SpecifyStage(
        id="early",
        name="Early",
        spine=4,
        scope_level="course",
        inputs=(
            StageInput(
                artifact_type=ArtifactType.EXPERIENCE, cardinality="1..n", from_stage="late"
            ),
        ),
        outputs=(StageOutput(artifact_type=ArtifactType.INTENT, cardinality="1..n"),),
        generator=_generator(),
    )
    late = SpecifyStage(
        id="late",
        name="Late",
        spine=6,
        scope_level="course",
        inputs=(
            StageInput(
                artifact_type=ArtifactType.INTENT, cardinality="1..n", from_stage="early"
            ),
        ),
        outputs=(StageOutput(artifact_type=ArtifactType.EXPERIENCE, cardinality="1..n"),),
        generator=_generator(),
    )
    with pytest.raises(PresetError, match="earlier"):
        _preset(_intake(), _halt_stage(), early, late)


def test_an_input_from_an_unknown_stage_is_rejected() -> None:
    consumer = SpecifyStage(
        id="s1",
        name="Consumer",
        spine=5,
        scope_level="course",
        inputs=(
            StageInput(
                artifact_type=ArtifactType.SOURCE_CLAIM,
                cardinality="1..n",
                from_stage="typo",
            ),
        ),
        outputs=(StageOutput(artifact_type=ArtifactType.RUBRIC, cardinality="1"),),
        generator=_generator(),
    )
    with pytest.raises(PresetError, match="typo"):
        _preset(_intake(), _halt_stage(), consumer)


def test_an_authored_input_needs_no_producing_stage() -> None:
    """A philosophy statement is signed by a human, not emitted by a stage.
    Requiring a producer for it would make the tautology guard impossible --
    the whole point is that it does not come from the corpus."""
    assert problems(_preset()) == []


def test_an_authored_input_of_a_derived_type_is_rejected() -> None:
    """The hole in "from_stage=None is exempt": a forgotten `from_stage` would
    otherwise silently skip chain validation. Only types a human can actually
    supply may be left unsourced."""
    consumer = SpecifyStage(
        id="s1",
        name="Consumer",
        spine=5,
        scope_level="course",
        inputs=(StageInput(artifact_type=ArtifactType.EXPERIENCE, cardinality="1..n"),),
        outputs=(StageOutput(artifact_type=ArtifactType.RUBRIC, cardinality="1"),),
        generator=_generator(),
    )
    with pytest.raises(PresetError, match="authored"):
        _preset(_intake(), _halt_stage(), consumer)


# --- amendments -------------------------------------------------------------


def test_an_amendment_to_an_unknown_stage_is_rejected() -> None:
    stage = _halt_stage()
    stage = stage.model_copy(
        update={"amendments": stage.amendments.model_copy(update={"emits_to": ("nowhere",)})}
    )
    with pytest.raises(PresetError, match="nowhere"):
        _preset(_intake(), stage)


def test_an_amendment_to_a_later_stage_is_rejected() -> None:
    """An amendment routes a revision *upstream*. Pointing it downstream is a
    forward edge wearing the wrong name, and the run would never converge."""
    intake = _intake()
    intake = intake.model_copy(
        update={"amendments": intake.amendments.model_copy(update={"emits_to": ("decide",)})}
    )
    with pytest.raises(PresetError, match="earlier"):
        _preset(intake, _halt_stage())


def test_an_amendment_to_itself_is_rejected() -> None:
    stage = _halt_stage()
    stage = stage.model_copy(
        update={"amendments": stage.amendments.model_copy(update={"emits_to": ("decide",)})}
    )
    with pytest.raises(PresetError, match="earlier"):
        _preset(_intake(), stage)


# --- preset-level shape -----------------------------------------------------


def test_duplicate_stage_ids_are_rejected() -> None:
    with pytest.raises(PresetError, match="s0"):
        _preset(_intake(), _intake(), _halt_stage())


def test_declared_spine_positions_must_match_the_stages() -> None:
    """Two sources of truth that can disagree. The declaration is what the UI
    shows and what "terminates before [8]" is judged against, so a drift here
    misdescribes the preset to the person choosing it."""
    with pytest.raises(PresetError, match="spine_positions"):
        _preset(spine_positions=(0, 1, 2))


def test_stages_must_be_listed_in_non_decreasing_spine_order() -> None:
    """Execution order is list order. This is also what enforces Tyler's
    screen ordering -- philosophy before psychology -- without a check that
    knows anything about Tyler."""
    with pytest.raises(PresetError, match="order"):
        _preset(_halt_stage("a", spine=4), _intake("s0", spine=0))


def test_a_preset_terminating_before_production_must_say_it_produces_a_design() -> None:
    """`ubd.pure` genuinely stops at a unit plan. Silently producing less than
    the user expected is worse than saying so up front."""
    with pytest.raises(PresetError, match="design"):
        _preset(produces="materials")


def test_a_preset_reaching_production_may_claim_materials() -> None:
    produce = _halt_stage("build", spine=8)
    assert problems(_preset(_intake(), produce, produces="materials")) == []


def test_every_preset_must_offer_halt_somewhere() -> None:
    """Neither UbD nor Tyler has "do not build a course" as an output, and the
    research called that a defect rather than a property worth preserving. An
    automated pipeline is structurally biased toward producing its own output,
    so this is the counterweight -- and it is required of every preset, not
    just ADDIE's."""
    with pytest.raises(PresetError, match="halt"):
        _preset(_intake(), _intake("s1", spine=1))


def test_an_unknown_artifact_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        StageInput(artifact_type="Vibes", cardinality="1")


def test_problems_reports_every_failure_not_just_the_first() -> None:
    """A preset is authored data. Fixing one typo per run is a bad loop."""
    with pytest.raises(PresetError) as caught:
        _preset(_intake(), _intake(), spine_positions=(3,))
    message = str(caught.value)
    assert "s0" in message  # the duplicate id
    assert "spine_positions" in message  # and the mismatched declaration


# --- the canonical vocabulary -----------------------------------------------


def test_the_canonical_vocabulary_is_the_twenty_two_the_research_found() -> None:
    """Pinned because the number is load-bearing in the spec's argument that
    one engine beats three pipelines. Growth is fine; unnoticed growth is not."""
    from research_team.domain.workflow import CANONICAL_ARTIFACTS

    assert len(CANONICAL_ARTIFACTS) == 22


# --- the three shipped presets ----------------------------------------------


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_every_shipped_preset_validates(preset: Preset) -> None:
    assert problems(preset) == []


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_every_shipped_preset_can_halt(preset: Preset) -> None:
    assert any(
        isinstance(stage, DecideStage) and "halt" in stage.gate.decisions
        for stage in preset.stages
    )


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_every_shipped_preset_names_itself_and_its_version(preset: Preset) -> None:
    assert preset.name and preset.version and preset.description


def test_the_presets_are_registered_under_their_own_ids() -> None:
    assert all(key == preset.id for key, preset in PRESETS.items())


def test_hybrid_default_occupies_the_whole_spine() -> None:
    assert hybrid_default.spine_positions == tuple(range(11))
    assert hybrid_default.produces == "materials"


def test_ubd_pure_terminates_at_a_unit_plan() -> None:
    assert hybrid_default.spine_positions[-1] == 10
    assert ubd_pure.spine_positions == (0, 1, 4, 5, 6, 7)
    assert ubd_pure.produces == "design"


def test_addie_pure_reaches_production_and_delivery() -> None:
    assert 8 in addie_pure.spine_positions
    assert 9 in addie_pure.spine_positions
    assert addie_pure.produces == "materials"


def test_ubd_pure_skips_candidate_generation_and_filtering() -> None:
    """UbD is thin at [2]-[3] -- a standards document is usually its only
    input. That is the documented weakness the hybrid exists to fix, and it
    should be visible in the data rather than papered over."""
    assert 2 not in ubd_pure.spine_positions
    assert 3 not in ubd_pure.spine_positions


def test_only_the_hybrid_has_a_value_filter() -> None:
    """ADDIE has no value filter and this is load-bearing, not incidental --
    it assumes the value question was settled before the designer was engaged.
    Pinning it makes the gap a fact about the preset a user can be shown."""
    assert hybrid_default.has_value_filter
    assert not addie_pure.has_value_filter
    assert not ubd_pure.has_value_filter


def test_the_hybrid_screens_philosophy_before_psychology() -> None:
    """Tyler's `screen_order`: value first, feasibility second. Reversed, a
    candidate is discarded as impractical before anyone asks whether it was
    worth doing, and the value question is never put."""
    ids = [stage.id for stage in hybrid_default.stages if isinstance(stage, ScreenStage)]
    assert ids == ["tyler.step2.philosophy_screen", "tyler.step3.psychology_screen"]


def test_the_hybrid_designs_evidence_before_experiences() -> None:
    """UbD's contribution, and a DAG edge rather than a philosophy: the
    experience stage takes EvidenceSpec as an input."""
    plan = next(
        stage for stage in hybrid_default.stages if stage.id == "ubd.stage3.learning_plan"
    )
    assert any(
        item.artifact_type == ArtifactType.EVIDENCE_SPEC
        and item.from_stage == "ubd.stage2.evidence"
        for item in plan.inputs
    )


def test_every_preset_marks_its_field_gate_rather_than_skipping_it() -> None:
    """A course that has never met a learner should carry that on its face.
    Presets that reach production carry a field stage; ones that stop at a
    design have nothing to try out yet."""
    for preset in (hybrid_default, addie_pure):
        assert any(isinstance(stage, FieldStage) for stage in preset.stages)


def test_the_hybrid_carries_checks_on_its_screens() -> None:
    """A screen with no checks is a critic with no harness, which is the
    "fluent generic plausibility" failure the spec calls the worst one
    precisely because it is invisible."""
    screens = [stage for stage in hybrid_default.stages if isinstance(stage, ScreenStage)]
    assert screens
    assert all(stage.checks for stage in screens)


def test_checks_name_a_severity() -> None:
    with pytest.raises(ValueError):
        Check(check="coverage", severity="whenever")
