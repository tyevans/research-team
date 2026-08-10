"""The six `ubd.pure` generator prompts, against the checks they have to survive.

Two quite different things are asserted here, and only the first is about files.

**The frontmatter contract**, from `docs/design/workflow-engine.md` §2.2: a
prompt states its own `prompt_ref`, which must equal its path minus `.md`, so a
file moved without its frontmatter updated is caught rather than silently
resolving to the wrong text. `intended_for` is the redundant declaration whose
only job is to disagree with the presets, and it is checked in both directions.

**The conventions the prompts teach, against the checks the stages bind.** This
is the part worth having. A prompt is a piece of instructional-design writing
and no test can say whether it is any good -- but the prompts do tell a model
what to put in an artifact's frontmatter, and every check in `ubd.pure` reads
frontmatter and nothing else (`stage_exit.load_course`: the body is for the
human). So the conventions are mechanically checkable even though the prose is
not. `_course()` below is a course written exactly as the six prompts instruct,
and `test_a_course_written_as_the_prompts_instruct_leaves_only_the_known_gaps`
runs every stage's real checks over it.

That test is also where three defects in `ubd.pure` are pinned, deliberately as
expected findings rather than as passes, because no prompt can fix any of them:

- `ubd.step0.intake` binds `must_cite: SourceDocument`, and no stage in the
  preset declares a `SourceDocument` output, so there is nothing in the course
  directory for a claim to cite.
- `ubd.stage1.desired_results` binds `prune_ratio` with neither
  `candidate_pool` nor `survivors`, so both default to "any artifact" and the
  ratio is 1.0 by construction on every run.
- `ubd.stage2.evidence` binds `matrix_density`, and `review_stage` builds its
  `CheckContext` with no matrices, so the binding always reports.
- `ubd.stage3.organization` requires prerequisites from `Intent.skill`, and
  `ubd.pure` has no skill tier at all -- textbook UbD Stage 1 does.

If one of those is fixed, this test fails and says so, which is the point of
writing them down as expectations rather than as a comment.
"""

from pathlib import Path

import pytest
import yaml

from research_team.application.artifacts import parse_frontmatter, stage_artifact_paths
from research_team.application.stage_exit import review_stage
from research_team.workflows import PRESETS, ubd_pure

PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"

GENERATOR_REFS = tuple(
    stage.generator.prompt_ref
    for stage in ubd_pure.stages
    if getattr(stage, "generator", None) is not None
)


def _prompt(ref: str) -> tuple[dict, str]:
    front, body = parse_frontmatter((PROMPT_ROOT.parent / f"{ref}.md").read_text())
    assert front is not None, f"{ref} has no readable frontmatter"
    return front, body


@pytest.mark.parametrize("ref", GENERATOR_REFS)
def test_every_ubd_pure_generator_has_a_prompt_that_names_its_own_path(ref: str):
    """The integrity check §2.2 asks for, and the one that catches a moved file."""
    front, body = _prompt(ref)
    assert front["prompt_ref"] == ref
    assert front["kind"] == "generator"
    assert front["methodology"] == "ubd"
    assert body.strip(), f"{ref} resolves to no instructions at all"


def test_no_prompt_file_is_orphaned():
    """Every file under `prompts/` is referenced by some preset.

    An unreferenced prompt is either a preset edit that lost its stage or a
    prompt written against a stage that was renamed, and both look like nothing.
    Critics are out of scope for this increment, so the referenced set is taken
    from every preset's generators and critics alike -- a critic prompt landing
    here later should not have to edit this test to be legal.
    """
    referenced = {
        author.prompt_ref
        for preset in PRESETS.values()
        for stage in preset.stages
        for author in (getattr(stage, "generator", None), getattr(stage, "critic", None))
        if author is not None
    }
    on_disk = {
        str(path.relative_to(PROMPT_ROOT.parent)).removesuffix(".md")
        for path in PROMPT_ROOT.rglob("*.md")
    }
    assert on_disk - referenced == set()


@pytest.mark.parametrize("ref", GENERATOR_REFS)
def test_intended_for_agrees_with_the_presets_in_both_directions(ref: str):
    """The redundant declaration whose only job is to disagree.

    A prompt written for UbD Stage 1 and quietly referenced by an ADDIE stage
    is §4.4's trap -- a methodology producing another's output while every
    structural check still passes -- and this is where it is caught.
    """
    front, _ = _prompt(ref)
    declared = set(front["intended_for"])
    actual = {
        f"{preset.id}/{stage.id}"
        for preset in PRESETS.values()
        for stage in preset.stages
        if getattr(getattr(stage, "generator", None), "prompt_ref", None) == ref
    }
    assert declared == actual


@pytest.mark.parametrize("ref", GENERATOR_REFS)
def test_a_prompt_does_not_name_the_paths_or_frontmatter_something_else_owns(ref: str):
    """§2.1's negative space, as far as a substring can police it.

    `stage_artifact_instructions` derives paths, artifact types and the
    provenance block from `stage.outputs`, so a prompt repeating them breaks
    silently the next time a stage is inserted. Only the mechanical half is
    testable: this catches a hardcoded `/course/...` path and the canonical
    type names, not a prompt that explains the gate in its own words.
    """
    _, body = _prompt(ref)
    assert "/course/" not in body
    for type_name in ("EvidenceSpec", "CoverageMatrix", "ContextProfile", "RiskRegister"):
        assert type_name not in body


# --- the course those prompts would produce ---------------------------------


def _paths(stage_id: str) -> tuple[str, ...]:
    stage = next(stage for stage in ubd_pure.stages if stage.id == stage_id)
    return stage_artifact_paths(ubd_pure, stage)


def _file(stage_id: str, **front) -> str:
    front.setdefault("provenance", [{"inferred_not_in_source": True}])
    front |= {"stage": stage_id, "preset": ubd_pure.id, "preset_version": ubd_pure.version}
    return f"---\n{yaml.safe_dump(front, sort_keys=False)}---\n\nbody\n"


def _course() -> dict[str, dict[str, str]]:
    """A course whose frontmatter follows the six prompts and nothing else.

    Written by hand rather than generated, because the thing under test is
    exactly the set of field names and shapes the prompt prose asks for: a
    helper that derived them from the checks would assert that the checks agree
    with themselves.
    """
    intake, dossier = _paths("ubd.step0.intake")
    profile, register = _paths("ubd.step1.context")
    goals, understandings, questions, exclusions, misconceptions = _paths(
        "ubd.stage1.desired_results"
    )
    task, other, criteria, rubric, matrix2, facets = _paths("ubd.stage2.evidence")
    pre, events, order, resources, monitoring, matrix3 = _paths("ubd.stage3.learning_plan")
    final_order, final_matrix = _paths("ubd.stage3.organization")

    files = {
        intake: _file(
            "ubd.step0.intake",
            artifact_type="SourceClaim",
            route="disciplinary",
            provenance=[{"source_id": "src-1", "start": 40, "end": 210}],
        ),
        dossier: _file(
            "ubd.step0.intake",
            artifact_type="SourceDossier",
            subtype="domain_concept_map",
            links=[intake],
        ),
        profile: _file(
            "ubd.step1.context",
            artifact_type="ContextProfile",
            time_budget=1200,
        ),
        register: _file("ubd.step1.context", artifact_type="ConstraintRegister"),
        goals: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="transfer_goal",
            text=(
                "Students will be able to independently use their learning to "
                "appraise historical claims they meet outside this course."
            ),
        ),
        understandings: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="understanding",
            text=(
                "Students will understand that a source's proximity to an event "
                "raises its detail and its interest in the account equally."
            ),
            links=[questions, goals],
        ),
        questions: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="essential_question",
            text="Whose account of this should we believe, and how would we know?",
        ),
        exclusions: _file("ubd.stage1.desired_results", artifact_type="Exclusion"),
        misconceptions: _file(
            "ubd.stage1.desired_results",
            artifact_type="RiskRegister",
            subtype="predicted_misconception",
        ),
        task: _file(
            "ubd.stage2.evidence",
            artifact_type="EvidenceSpec",
            subtype="performance_task",
            position=8,
            requires=["weigh-two-accounts"],
            links=[goals, understandings],
        ),
        other: _file(
            "ubd.stage2.evidence",
            artifact_type="EvidenceSpec",
            subtype="other_evidence",
            links=[understandings],
        ),
        criteria: _file(
            "ubd.stage2.evidence",
            artifact_type="Criteria",
            code=["impact", "content", "quality"],
            links=[task],
        ),
        rubric: _file("ubd.stage2.evidence", artifact_type="Rubric", links=[criteria]),
        matrix2: _file(
            "ubd.stage2.evidence",
            artifact_type="CoverageMatrix",
            subtype="intent_x_evidence",
            links=[goals, understandings, task],
        ),
        facets: _file(
            "ubd.stage2.evidence",
            artifact_type="TaxonomySelection",
            subtype="six_facets",
            links=[understandings],
        ),
        pre: _file(
            "ubd.stage3.learning_plan",
            artifact_type="EvidenceSpec",
            subtype="pre_assessment",
            links=[misconceptions, understandings],
        ),
        events: _file(
            "ubd.stage3.learning_plan",
            artifact_type="Experience",
            amt=["A", "M", "T"],
            whereto=["W", "H", "E", "R", "E2", "T", "O"],
            code=["W", "H"],
            position=1,
            minutes=900,
            links=[goals, understandings, task],
        ),
        order: _file("ubd.stage3.learning_plan", artifact_type="Sequence", links=[events]),
        resources: _file(
            "ubd.stage3.learning_plan", artifact_type="ResourceSelection", links=[events]
        ),
        monitoring: _file(
            "ubd.stage3.learning_plan",
            artifact_type="MonitoringPlan",
            links=[events, misconceptions],
        ),
        matrix3: _file(
            "ubd.stage3.learning_plan",
            artifact_type="CoverageMatrix",
            subtype="intent_x_experience",
            links=[events, understandings],
        ),
        final_order: _file(
            "ubd.stage3.organization",
            artifact_type="Sequence",
            subtype="event_order",
            position=1,
            links=[events, goals, understandings],
        ),
        final_matrix: _file(
            "ubd.stage3.organization",
            artifact_type="CoverageMatrix",
            subtype="intent_x_experience",
            links=[events, understandings],
        ),
    }
    return {path: {"content": content} for path, content in files.items()}


#: The findings that survive a correctly written course, per stage, and why.
#: Every one is a defect in `ubd.pure` or in the harness wiring that no prompt
#: can reach. See the module docstring.
KNOWN_GAPS = {
    "ubd.step0.intake": ("shared.provenance",),
    "ubd.step1.context": (),
    "ubd.stage1.desired_results": ("shared.prune_ratio",),
    "ubd.stage2.evidence": ("shared.matrix_density",),
    "ubd.stage3.learning_plan": (),
    "ubd.stage3.organization": ("shared.prerequisite_satisfied",),
}


@pytest.mark.parametrize("stage_id", list(KNOWN_GAPS))
def test_a_course_written_as_the_prompts_instruct_leaves_only_the_known_gaps(stage_id: str):
    """The prompts' frontmatter conventions satisfy every check that can pass.

    This is the closest thing to §6's first signal that exists without a model
    in the loop: it does not say the prose is good, it says the conventions the
    prose teaches are the ones the checks read. It would pass with the prompt
    *text* replaced by anything, and that limit is the reason the PR body lists
    what remains unverified.
    """
    stage = next(stage for stage in ubd_pure.stages if stage.id == stage_id)
    review = review_stage(ubd_pure, stage, _course())
    assert review.unreadable == ()
    assert tuple(finding.check for finding in review.findings) == KNOWN_GAPS[stage_id]


def test_dropping_the_understanding_stem_is_caught():
    """Proves the stem check is live against this course rather than vacuous.

    Reverted -- that is, with the stem restored -- this test fails, which is
    what makes the passing case above evidence of anything. Without it, a `text`
    field of the wrong *type* would skip the check silently and the course
    would look conformant.
    """
    course = _course()
    path = _paths("ubd.stage1.desired_results")[1]
    course[path] = {"content": course[path]["content"].replace("Students will ", "They will ")}
    stage = next(s for s in ubd_pure.stages if s.id == "ubd.stage1.desired_results")
    checks = [finding.check for finding in review_stage(ubd_pure, stage, course).findings]
    assert "shared.format_conformance" in checks


def test_a_closed_essential_question_is_caught():
    """The interrogative-stem rejection, against the course above.

    The prompts deliberately put the questions themselves in `text` rather than
    a framing stem in front of them; a stem would make this check unfireable,
    and this test is what would notice if a later edit added one.
    """
    course = _course()
    path = _paths("ubd.stage1.desired_results")[2]
    course[path] = {
        "content": course[path]["content"].replace(
            "Whose account of this should we believe, and how would we know?",
            "What year was the treaty signed?",
        )
    }
    stage = next(s for s in ubd_pure.stages if s.id == "ubd.stage1.desired_results")
    checks = [finding.check for finding in review_stage(ubd_pure, stage, course).findings]
    assert checks.count("shared.format_conformance") == 1


def test_an_all_acquisition_plan_is_caught():
    """The single commonest real design failure, and the check that sees it.

    Named here because it is the one finding in the whole preset that would
    change a course rather than a file: a plan coded only `A` teaches nothing
    toward meaning or transfer, and reads perfectly well as prose.
    """
    course = _course()
    path = _paths("ubd.stage3.learning_plan")[1]
    course[path] = {"content": course[path]["content"].replace("- A\n- M\n- T\n", "- A\n")}
    stage = next(s for s in ubd_pure.stages if s.id == "ubd.stage3.learning_plan")
    findings = review_stage(ubd_pure, stage, course).findings
    assert [finding.check for finding in findings] == [
        "shared.taxonomy_distribution",
        "shared.taxonomy_distribution",
    ]
