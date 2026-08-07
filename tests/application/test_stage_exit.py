"""What the harness knows about a stage before it lets anyone leave it.

Two things are being pinned here and they pull in opposite directions. Findings
must reach the reviewer without stopping the run, because a pipeline that
refuses to advance on an advisory finding is a pipeline whose checks get turned
off. And the two invariants must stop the run outright, because they are the
two failures a reviewer cannot see by looking. Most of these tests exist to
keep that line in the same place.
"""

import subprocess
import sys
from dataclasses import replace
from typing import Any

import pytest

from research_team.application.checks import REGISTRY
from research_team.application.findings import Finding
from research_team.application.stage_exit import (
    FINDINGS_ARTIFACT,
    findings_path,
    gate_context,
    load_course,
    refusal,
    render_review,
    review_stage,
)
from research_team.domain.workflow import (
    ArtifactType,
    Check,
    DecideStage,
    DecisionGate,
    Generator,
    LedgerGate,
    Preset,
    ScreeningCritic,
    ScreenStage,
    SpecifyStage,
    StageOutput,
)
from research_team.workflows import PRESETS

ALL_PRESETS = pytest.mark.parametrize(
    "preset", list(PRESETS.values()), ids=list(PRESETS.keys())
)


def file(content: str) -> dict[str, Any]:
    return {"content": content}


def artifact_file(**frontmatter: Any) -> dict[str, Any]:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value!r}" if isinstance(value, str) else f"{key}: {value}")
    lines += ["---", "", "body text"]
    return file("\n".join(lines))


def specify(stage_id: str, *checks: Check) -> SpecifyStage:
    return SpecifyStage(
        id=stage_id,
        name=stage_id,
        spine=4,
        scope_level="unit",
        outputs=(StageOutput(artifact_type=ArtifactType.INTENT, cardinality="1..n"),),
        generator=Generator(role="author", prompt_ref="p/gen"),
        checks=checks,
    )


def halting() -> DecideStage:
    """Every preset must be able to answer "no course"; this is that stage."""
    return DecideStage(
        id="s.decide",
        name="Decide",
        spine=1,
        scope_level="unit",
        generator=Generator(role="analyst", prompt_ref="p/decide"),
        gate=DecisionGate(reviewer_role="sponsor", presents=("RequestBrief",)),
    )


def preset_of(*stages: Any) -> Preset:
    stages = (halting(), *stages)
    return Preset(
        id="test.preset",
        name="Test",
        version="1",
        description="A preset built for these tests only.",
        spine_positions=tuple(sorted({stage.spine for stage in stages})),
        stages=tuple(stages),
        produces="design",
    )


# --- reading the course directory --------------------------------------------


def test_a_course_file_becomes_an_artifact_keyed_by_its_path():
    artifacts, links, unreadable = load_course(
        {"/course/03-intent.md": artifact_file(artifact_type="Intent", subtype="skill")}
    )
    (intent,) = artifacts
    assert intent.id == "/course/03-intent.md"
    assert intent.artifact_type is ArtifactType.INTENT
    assert intent.subtype == "skill"
    assert links == () and unreadable == ()


def test_files_outside_the_course_directory_are_not_artifacts():
    artifacts, _, unreadable = load_course(
        {"/notes.md": artifact_file(artifact_type="Intent")}
    )
    assert artifacts == () and unreadable == ()


def test_the_findings_artifact_is_never_an_input_to_its_own_checks():
    # Otherwise every run's provenance check reports the previous run's report.
    artifacts, _, unreadable = load_course(
        {f"/course/02-{FINDINGS_ARTIFACT}.md": file("# findings")}
    )
    assert artifacts == () and unreadable == ()


def test_a_file_with_no_frontmatter_is_reported_rather_than_skipped():
    _, _, unreadable = load_course({"/course/03-intent.md": file("just prose")})
    assert unreadable == ("/course/03-intent.md",)


def test_an_unknown_artifact_type_is_reported_rather_than_guessed():
    _, _, unreadable = load_course(
        {"/course/03-intent.md": artifact_file(artifact_type="Nonsense")}
    )
    assert unreadable == ("/course/03-intent.md",)


def test_provenance_survives_into_the_artifact_in_the_shape_checks_expect():
    artifacts, _, _ = load_course(
        {
            "/course/03-intent.md": file(
                "---\nartifact_type: Intent\nprovenance:\n"
                "  - {source_id: s1, start: 0, end: 9}\n---\nbody"
            )
        }
    )
    assert artifacts[0].provenance == ({"source_id": "s1", "start": 0, "end": 9},)


def test_a_links_list_of_bare_ids_becomes_edges():
    artifacts, links, _ = load_course(
        {
            "/course/03-intent.md": file(
                "---\nartifact_type: Intent\nlinks: ['/course/04-evidence-spec.md']\n---\nb"
            ),
            "/course/04-evidence-spec.md": artifact_file(artifact_type="EvidenceSpec"),
        }
    )
    assert len(artifacts) == 2
    assert [(link.source, link.target) for link in links] == [
        ("/course/03-intent.md", "/course/04-evidence-spec.md")
    ]


def test_a_links_entry_may_name_its_kind():
    _, links, _ = load_course(
        {
            "/course/03-intent.md": file(
                "---\nartifact_type: Intent\nlinks:\n"
                "  - {target: '/course/04-e.md', kind: assesses}\n---\nb"
            )
        }
    )
    assert links[0].kind == "assesses"


def test_a_links_field_of_the_wrong_shape_is_ignored_not_raised():
    # Frontmatter is written by a model; a malformed field must not take the
    # gate down with it.
    _, links, _ = load_course(
        {"/course/03-intent.md": file("---\nartifact_type: Intent\nlinks: 7\n---\nb")}
    )
    assert links == ()


# --- running a stage's checks -------------------------------------------------


def test_a_stage_with_no_checks_reviews_clean():
    stage = specify("s.one")
    review = review_stage(preset_of(stage), stage, {})
    assert review.findings == () and not review.blocked


def test_a_declared_check_actually_runs_and_reports():
    stage = specify(
        "s.one",
        Check(check="shared.provenance", params={"type": {"artifact_type": "Intent"}}),
    )
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    assert [finding.check for finding in review.findings] == ["shared.provenance"]


def test_a_binding_naming_no_registered_check_is_reported_not_ignored():
    """A declared check that silently does not run is worse than none at all."""
    # A name that is not and will not be registered. This used to be
    # `addie.expert_gap_flag`, which made the test depend on that check staying
    # unimplemented -- so implementing it broke a test about something else.
    stage = specify("s.one", Check(check="addie.no_such_check"))
    review = review_stage(preset_of(stage), stage, {})
    assert review.unimplemented == ("addie.no_such_check",)
    assert review.findings == ()


def break_check(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    def explode(context: Any, params: Any) -> Any:
        raise RuntimeError("bad query")

    monkeypatch.setitem(REGISTRY, name, replace(REGISTRY[name], run=explode))


def test_a_check_that_raises_becomes_a_finding_and_does_not_propagate(monkeypatch):
    break_check(monkeypatch, "shared.provenance")
    stage = specify("s.one", Check(check="shared.provenance"))
    review = review_stage(preset_of(stage), stage, {})
    (finding,) = review.findings
    assert "bad query" in finding.message
    assert not review.blocked


def test_a_malformed_binding_becomes_a_finding_rather_than_a_crash():
    stage = specify("s.one", Check(check="shared.coverage", params={"min": "lots"}))
    review = review_stage(preset_of(stage), stage, {})
    (finding,) = review.findings
    assert "shared.coverage" in finding.message
    assert not review.blocked


def test_the_review_counts_what_it_looked_at():
    stage = specify("s.one")
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    assert review.artifact_count == 1


# --- the two invariants -------------------------------------------------------


def screen(stage_id: str, *, generator_stage: str, separate_context: bool) -> ScreenStage:
    return ScreenStage(
        id=stage_id,
        name=stage_id,
        spine=4,
        scope_level="unit",
        critic=ScreeningCritic(
            role="screener",
            prompt_ref="p/screen",
            criterion_doc="doc",
            separate_context=separate_context,
        ),
        gate=LedgerGate(reviewer_role="sponsor", presents=("VerdictLedger.*",)),
        checks=(
            Check(
                check="shared.self_review_separation",
                params={"generator_stage": generator_stage},
            ),
        ),
    )


def test_a_separated_screen_does_not_block():
    generator = specify("s.gen")
    reviewer = screen("s.screen", generator_stage="s.gen", separate_context=True)
    review = review_stage(preset_of(generator, reviewer), reviewer, {})
    assert review.findings == () and not review.blocked


def test_a_self_reviewing_screen_blocks_the_advance():
    generator = specify("s.gen")
    reviewer = screen("s.screen", generator_stage="s.gen", separate_context=False)
    review = review_stage(preset_of(generator, reviewer), reviewer, {})
    assert [finding.severity for finding in review.invariant_failures] == ["invariant"]
    assert review.blocked


def test_an_uncited_verdict_blocks_the_advance():
    stage = specify(
        "s.one",
        Check(
            check="shared.verdict_citation",
            params={"ledger": {"artifact_type": "VerdictLedger"}},
        ),
    )
    review = review_stage(
        preset_of(stage),
        stage,
        {
            "/course/00-verdict-ledger.md": file(
                "---\nartifact_type: VerdictLedger\nverdicts:\n"
                "  - {candidate_id: c1, verdict: reject}\n---\nb"
            )
        },
    )
    assert review.blocked


def test_an_ordinary_blocking_finding_does_not_block():
    """The judgement this whole module turns on: severity informs, it does not gate."""
    stage = specify("s.one", Check(check="shared.provenance", severity="blocking"))
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    assert review.findings and not review.blocked


def test_a_crashing_invariant_does_not_block(monkeypatch):
    """A bug in a check must not cost a transition the model already earned."""
    break_check(monkeypatch, "shared.self_review_separation")
    generator = specify("s.gen")
    reviewer = screen("s.screen", generator_stage="s.gen", separate_context=False)
    review = review_stage(preset_of(generator, reviewer), reviewer, {})
    assert review.findings and not review.blocked


def test_refusal_names_the_invariant_and_what_to_do():
    generator = specify("s.gen")
    reviewer = screen("s.screen", generator_stage="s.gen", separate_context=False)
    review = review_stage(preset_of(generator, reviewer), reviewer, {})
    text = refusal(review)
    assert text is not None
    assert "shared.self_review_separation" in text


def test_a_clean_review_refuses_nothing():
    stage = specify("s.one")
    assert refusal(review_stage(preset_of(stage), stage, {})) is None


# --- the artifact and the gate context ----------------------------------------


def test_the_findings_artifact_lands_under_the_stage_number():
    first, second = specify("s.one"), specify("s.two")
    assert findings_path(preset_of(first, second), second) == (
        f"/course/02-{FINDINGS_ARTIFACT}.md"
    )


def test_the_rendered_report_carries_frontmatter_naming_its_stage():
    stage = specify("s.one", Check(check="shared.provenance"))
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    text = render_review(review, preset_of(stage))
    assert text.startswith("---\n")
    assert "stage: s.one" in text
    assert "s.one" in text


def test_a_clean_report_says_so_rather_than_rendering_an_empty_table():
    stage = specify("s.one")
    text = render_review(review_stage(preset_of(stage), stage, {}), preset_of(stage))
    assert "No findings" in text


def test_the_report_renders_findings_as_a_table_the_viewer_already_handles():
    stage = specify("s.one", Check(check="shared.provenance"))
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    text = render_review(review, preset_of(stage))
    assert "| Check | Severity | Message |" in text


def test_the_report_names_checks_that_could_not_run():
    stage = specify("s.one", Check(check="addie.expert_gap_flag"))
    text = render_review(review_stage(preset_of(stage), stage, {}), preset_of(stage))
    assert "addie.expert_gap_flag" in text


def test_the_gate_context_is_json_shaped_primitives_only():
    stage = specify("s.one", Check(check="shared.provenance"))
    review = review_stage(
        preset_of(stage),
        stage,
        {"/course/00-intent.md": artifact_file(artifact_type="Intent")},
    )
    context = gate_context(review, "/course/00-check-findings.md")
    assert context["stage"] == "s.one"
    assert context["findings_artifact"] == "/course/00-check-findings.md"
    assert isinstance(context["findings"], list)
    assert set(context["findings"][0]) == {
        "check",
        "severity",
        "message",
        "affected_artifact_ids",
        "suggested_edit",
    }
    assert isinstance(context["findings"][0]["affected_artifact_ids"], list)


def test_the_gate_context_says_when_the_harness_refused():
    generator = specify("s.gen")
    reviewer = screen("s.screen", generator_stage="s.gen", separate_context=False)
    review = review_stage(preset_of(generator, reviewer), reviewer, {})
    context = gate_context(review, "/course/01-check-findings.md")
    assert context["blocked"] is True


# --- the shipped presets ------------------------------------------------------


DELIBERATELY_UNIMPLEMENTED: frozenset[str] = frozenset()
"""Checks a shipped preset binds that the registry does not implement.

Empty, and worth keeping at zero. It held `addie.expert_gap_flag`,
`addie.change_scope` and `tyler.criterion_doc_authored` while those were
unregistered; all three are now in the registry, two as ordinary graph queries
and `expert_gap_flag` as a `critic_gate` -- registered, parameter-validated,
and reporting a standing finding rather than resolving to nothing. That is a
better answer than an exemption, because an exemption makes a bound check
invisible while a `critic_gate` makes it visible as something owed.

Kept as a name rather than deleted so the guard below stays an equality rather
than a subset: this list is the only place an exemption can be added, which
means adding one is an edit somebody reviews rather than a test that quietly
goes on passing. `test_no_exemption_outlives_the_check_it_exempts` is what
emptied it -- it failed the moment the three were implemented, which is exactly
what it is for.
"""


@ALL_PRESETS
def test_every_name_this_preset_binds_resolves_in_the_registry(preset):
    """The guard for the whole class, not for the instance that prompted it.

    `shared.matrix_density` was implemented, exported, agreed by everyone to be
    wired, and registered nowhere -- and every component test passed throughout,
    because an unregistered check fails by being *absent*, which is
    indistinguishable from a check that ran and found nothing. No test of the
    check itself can tell those apart. Only asserting the join can: every name a
    shipped preset binds must resolve, and every exception must be named.

    Per preset rather than over all of them at once so a failure says which
    workflow is broken without anyone having to go and find out.
    """
    unresolved = {
        (stage.id, check.check)
        for stage in preset.stages
        for check in stage.checks
        if check.check not in REGISTRY
    }
    unexpected = {
        (stage_id, name)
        for stage_id, name in unresolved
        if name not in DELIBERATELY_UNIMPLEMENTED
    }
    assert unexpected == set(), (
        f"{preset.id} binds checks that resolve to nothing: {sorted(unexpected)}"
    )


@ALL_PRESETS
def test_every_stage_of_this_preset_is_reachable_by_the_gate(preset):
    """The other half of the same join: the gate has to find the stage too.

    A check that resolves is worth nothing if `review_stage` never runs it,
    which is what a stage the preset numbers but the gate cannot place would
    mean.
    """
    for stage in preset.stages:
        assert findings_path(preset, stage).startswith("/course/")


def test_no_exemption_outlives_the_check_it_exempts():
    """A stale entry above would hide a check that had since been implemented,
    and the exemption list is only trustworthy if it cannot rot."""
    implemented = sorted(name for name in DELIBERATELY_UNIMPLEMENTED if name in REGISTRY)
    assert implemented == []


def test_the_registry_is_complete_on_importing_it_alone():
    """Explicit registration means no other module has to be pulled in first.

    Run in a fresh interpreter, because an implementation module imported
    earlier by something else in this session would mask exactly the failure
    this is looking for.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import research_team.application.checks as c;"
            "print('shared.matrix_density' in c.REGISTRY)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "True"


@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_every_shipped_stage_reviews_without_raising(preset_id: str):
    """The gate runs on every stage of every preset, so none may explode.

    An empty course directory is the worst case rather than a trivial one:
    it is what the first stage of every run actually sees.
    """
    preset = PRESETS[preset_id]
    for stage in preset.stages:
        review = review_stage(preset, stage, {})
        assert isinstance(review.findings, tuple)
        render_review(review, preset)


def test_no_shipped_preset_is_blocked_on_an_empty_course():
    """A run that cannot leave its first stage before doing any work is a
    misconfigured preset, and this is the cheapest place to notice."""
    for preset in PRESETS.values():
        first = preset.stages[0]
        assert not review_stage(preset, first, {}).blocked, preset.id


def test_a_finding_is_carried_verbatim_into_the_context():
    review = review_stage(preset_of(specify("s.one")), specify("s.one"), {})
    assert isinstance(review.findings, tuple)
    assert all(isinstance(finding, Finding) for finding in review.findings)
