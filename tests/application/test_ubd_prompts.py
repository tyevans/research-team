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

**`KNOWN_GAPS` used to pin four defects in `ubd.pure` as expected findings**,
because no prompt could fix any of them. All four are now fixed and the
expectation is silence; the pins are corrected here rather than deleted, because
what they were and what happened to them is the part worth keeping:

- `ubd.step0.intake` bound `must_cite: SourceDocument`. No stage in any preset
  declares a `SourceDocument` output and source documents live in the corpus
  rather than in `/course`, so the requirement was unsatisfiable by
  construction. The binding is gone; the base provenance requirement, which is
  what it was reaching for, stays.
- `ubd.stage1.desired_results` bound `prune_ratio` with neither
  `candidate_pool` nor `survivors`, so both defaulted to "any artifact" and the
  ratio was 1.0 on every run. It is now bound to the understandings and the
  exclusion ledger, counted by item rather than by file.
- `ubd.stage2.evidence` bound `matrix_density` and `review_stage` built its
  `CheckContext` with no matrices, so the binding reported a missing matrix
  always. `stage_exit.course_matrices` now builds it from the binding's axes.
- `ubd.stage3.organization` required prerequisites from `Intent.skill` and
  `ubd.pure` had no acquisition tier. Template 2.0 has one, so the preset was
  wrong rather than the check: Stage 1 now produces knowledge and skill.

Each of the four has a companion test below proving the check can still *fire*
against this course. A check that cannot fire and a check that always fires are
the same defect, and fixing one by producing the other would pass the test above
without improving anything.
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
    (
        goals,
        understandings,
        questions,
        knowledge,
        skills,
        exclusions,
        misconceptions,
    ) = _paths("ubd.stage1.desired_results")
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
        # Three understandings against twelve entries in the exclusion ledger:
        # the fifteen-to-three prune the stage's `over_generate_factor` asks for,
        # written the way the prompt asks for it -- one per line in `text`, and
        # the cut ones as ledger entries, which is the only record the pool
        # leaves behind.
        understandings: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="understanding",
            text=(
                "Students will understand that a source's proximity to an event "
                "raises its detail and its interest in the account equally.\n"
                "Students will understand that an absence in the record is "
                "evidence about who kept records, not about what happened.\n"
                "Students will understand that corroboration between two accounts "
                "is worth less when both descend from one origin.\n"
            ),
            links=[questions, goals],
        ),
        questions: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="essential_question",
            text=(
                "Whose account of this should we believe, and how would we know?\n"
                "What does this silence in the record tell us?\n"
            ),
        ),
        knowledge: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="knowledge",
            text=(
                "Students will know the difference between a primary and a "
                "secondary source.\n"
                "Students will know the conventions by which historians cite "
                "archival material.\n"
            ),
        ),
        skills: _file(
            "ubd.stage1.desired_results",
            artifact_type="Intent",
            subtype="skill",
            text=(
                "Students will be skilled at weighing two accounts of one event "
                "against each other.\n"
                "Students will be skilled at tracing an account back to the "
                "record it rests on.\n"
            ),
            key=["weigh-two-accounts", "trace-to-record"],
            position=2,
        ),
        exclusions: _file(
            "ubd.stage1.desired_results",
            artifact_type="Exclusion",
            entries=[
                {"candidate_id": f"u{index}", "reason": "a truism with no plausible rival"}
                for index in range(12)
            ],
        ),
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
        # Other evidence carries the acquisition tier and the essential
        # questions, which is what the stage 2 prompt asks of it: knowledge and
        # discrete skill "well served by other evidence", and every intent
        # needing evidence of some kind. Without these links they are empty rows
        # in the intent-by-evidence matrix, which is the finding that matrix
        # exists to produce.
        other: _file(
            "ubd.stage2.evidence",
            artifact_type="EvidenceSpec",
            subtype="other_evidence",
            links=[understandings, questions, knowledge, skills],
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


#: The findings that survive a correctly written course, per stage.
#: Four of these were non-empty and are not any more; see the module docstring
#: for what each was. Nothing here is expected to stay empty by luck -- the
#: `_is_caught` tests below fire each of the four deliberately.
KNOWN_GAPS: dict[str, tuple[str, ...]] = {
    "ubd.step0.intake": (),
    "ubd.step1.context": (),
    "ubd.stage1.desired_results": (),
    "ubd.stage2.evidence": (),
    "ubd.stage3.learning_plan": (),
    "ubd.stage3.organization": (),
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


def _checks(stage_id: str, course) -> list[str]:
    stage = next(stage for stage in ubd_pure.stages if stage.id == stage_id)
    return [finding.check for finding in review_stage(ubd_pure, stage, course).findings]


def _messages(stage_id: str, course, check: str) -> list[str]:
    stage = next(stage for stage in ubd_pure.stages if stage.id == stage_id)
    review = review_stage(ubd_pure, stage, course)
    return [finding.message for finding in review.findings if finding.check == check]


def _replace(course, path: str, old: str, new: str):
    course[path] = {"content": course[path]["content"].replace(old, new, 1)}
    return course


# --- the four, from the other direction --------------------------------------
#
# Each of these was silent before its defect was fixed, because each check was
# either unsatisfiable or already reporting on a clean course -- there was
# nothing a mutation could change. They are the half of the fix that the
# `KNOWN_GAPS` test cannot supply: it says the check is quiet, and quiet is also
# what a check that has been switched off sounds like.


def test_an_uncited_source_claim_is_caught():
    """Intake's provenance requirement still bites once `must_cite` is gone.

    `must_cite: SourceDocument` was the unsatisfiable half and this is what
    remains. Reverted -- with the provenance block restored -- this test fails.
    """
    course = _replace(
        _course(),
        _paths("ubd.step0.intake")[0],
        "provenance:\n- source_id: src-1\n  start: 40\n  end: 210\n",
        "provenance: []\n",
    )
    assert "shared.provenance" in _checks("ubd.step0.intake", course)


def test_a_prune_that_cut_nothing_is_caught():
    """The rubber stamp, now that the ratio is computed from something.

    An empty exclusion ledger is a screen with no record of having screened, and
    the pool collapses to the survivors -- 3 of 3.

    The counts are asserted, not just the check name. Before the binding was
    fixed this check fired on every course, so a test asserting only that it
    fired would pass against the defect it was written to prove gone.
    """
    course = _course()
    path = _paths("ubd.stage1.desired_results")[5]
    course[path] = {"content": course[path]["content"].split("entries:")[0] + "---\n\nbody\n"}
    assert _messages("ubd.stage1.desired_results", course, "shared.prune_ratio") == [
        "3 of 3 survived (100%), expected 15%-40%: the screen kept almost "
        "everything, which is what a rubber stamp looks like"
    ]


def test_an_unassessed_intent_is_caught():
    """An empty row in the intent-by-evidence matrix, which is now built.

    The essential questions are evidenced only by the other-evidence artifact, so
    dropping that one link leaves an intent nothing assesses -- the finding the
    stage 2 prompt describes as "a promise the unit does not keep".

    The message is asserted rather than the count, and that is the whole point:
    before `course_matrices` existed this binding produced exactly one finding
    too -- "no matrix was built for this stage" -- so a count assertion would
    have passed against the wiring fault it exists to prove fixed.
    """
    questions = _paths("ubd.stage1.desired_results")[2]
    course = _replace(_course(), _paths("ubd.stage2.evidence")[1], f"- {questions}\n", "")
    messages = _messages("ubd.stage2.evidence", course, "shared.matrix_density")
    assert len(messages) == 1
    assert f"{questions} is uncovered" in messages[0]


def test_a_task_needing_a_skill_the_unit_never_teaches_is_caught():
    """The prerequisite check, against an acquisition tier that now exists.

    Reverted -- that is, with `ubd.pure` carrying no skill tier -- this test
    passes for the wrong reason: the check fired on every task with any
    `requires` at all, including the correct ones. The `KNOWN_GAPS` case above
    is the load-bearing half of this pair, and this one exists so that a later
    edit cannot make that one pass by making the check unfireable.
    """
    course = _replace(
        _course(),
        _paths("ubd.stage2.evidence")[0],
        "weigh-two-accounts",
        "read-latin-charters",
    )
    assert "shared.prerequisite_satisfied" in _checks("ubd.stage3.organization", course)


def test_a_skill_equipped_after_the_task_that_needs_it_is_caught():
    """The ordering half, which is the one that survives review.

    A task at position 8 requiring a skill the unit equips at position 9 reads
    perfectly well in the document. Nothing but the position comparison sees it.

    Like the test above, this one would also pass against the unfixed preset --
    which is why the message is asserted: "does not equip until later" is only
    reachable once a provider exists at all.
    """
    course = _replace(
        _course(), _paths("ubd.stage1.desired_results")[4], "position: 2", "position: 9"
    )
    messages = _messages("ubd.stage3.organization", course, "shared.prerequisite_satisfied")
    assert len(messages) == 1
    assert "does not equip until later" in messages[0]


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
