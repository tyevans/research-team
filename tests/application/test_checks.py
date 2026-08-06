"""The check library, held to the property that makes it worth running.

Every check here is a graph or schema query, so every test here is an example
or a property over data structures -- there is no transport to stub and no
model to fake, which is the point. A check that needed a model would need a
recorded fixture, and a recorded fixture would go stale silently.

The properties carry more weight than the examples for the four generic checks
that have them. `coverage` and `orphan` are duals and a divergence between them
would be invisible in any single example; `prune_ratio` and `recurrence` are
counting arguments where the interesting cases are the boundaries.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.application.checks import (
    REGISTRY,
    Artifact,
    CheckContext,
    Link,
    MalformedCheck,
    UnknownCheck,
    critic_gates,
    human_gates,
    run_check,
    run_checks,
    unknown_checks,
)
from research_team.domain.workflow import (
    ArtifactType,
    Check,
    Critic,
    DecisionGate,
    Generator,
    LedgerGate,
    MaturityGate,
    ProduceStage,
    Rung,
    ScreeningCritic,
    ScreenStage,
    SpecifyStage,
)
from research_team.workflows import PRESETS

INTENT = ArtifactType.INTENT
EXPERIENCE = ArtifactType.EXPERIENCE
EVIDENCE = ArtifactType.EVIDENCE_SPEC


def artifact(
    artifact_id: str,
    artifact_type: ArtifactType = INTENT,
    **kwargs: object,
) -> Artifact:
    return Artifact(id=artifact_id, artifact_type=artifact_type, **kwargs)  # type: ignore[arg-type]


def context(*artifacts: Artifact, links: tuple[Link, ...] = ()) -> CheckContext:
    return CheckContext(artifacts=artifacts, links=links)


def bind(name: str, **params: object) -> Check:
    return Check(check=name, params=params)


# --- the registry itself ----------------------------------------------------


def test_every_registered_name_is_namespaced() -> None:
    """The engine binds by name and must never learn which namespace is which.

    A bare name would work today and collide the moment a methodology wants its
    own `coverage`, which is the exact edit this design exists to make cheap.
    """
    for name in REGISTRY:
        namespace, _, rest = name.partition(".")
        assert namespace in {"shared", "ubd", "tyler", "addie"}, name
        assert rest, name


def test_an_unregistered_check_raises_rather_than_passing() -> None:
    """A typo in a preset must not read as a check that found nothing."""
    with pytest.raises(UnknownCheck):
        run_check(bind("shared.covrage"), context())


def test_unknown_checks_reports_every_bad_binding_at_once() -> None:
    bindings = (bind("shared.coverage"), bind("nope.nope"), bind("shared.orphan"))
    assert unknown_checks(bindings) == ["nope.nope"]


def test_malformed_parameters_name_the_check() -> None:
    with pytest.raises(MalformedCheck) as caught:
        run_check(bind("shared.coverage", min="lots"), context())
    assert "shared.coverage" in str(caught.value)


# --- coverage and orphan, the dual pair -------------------------------------


def test_coverage_reports_the_uncovered_artifact_not_a_count() -> None:
    graph = context(
        artifact("i1", INTENT),
        artifact("i2", INTENT),
        artifact("e1", EXPERIENCE),
        links=(Link("e1", "i1"),),
    )
    findings = run_check(
        bind(
            "shared.coverage",
            **{"from": {"artifact_type": "Intent"}, "to": {"artifact_type": "Experience"}},
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("i2",)]
    assert findings[0].suggested_edit


def test_coverage_counts_links_in_either_direction() -> None:
    """Which way an edge points is an authoring accident, not a semantic one."""
    forward = context(artifact("i1"), artifact("e1", EXPERIENCE), links=(Link("i1", "e1"),))
    backward = context(artifact("i1"), artifact("e1", EXPERIENCE), links=(Link("e1", "i1"),))
    binding = bind(
        "shared.coverage",
        **{"from": {"artifact_type": "Intent"}, "to": {"artifact_type": "Experience"}},
    )
    assert run_check(binding, forward) == run_check(binding, backward) == []


def test_coverage_respects_a_subtype_filter() -> None:
    """UbD's transfer-goal rule is this check with a subtype filter, nothing more."""
    graph = context(
        artifact("i1"),
        artifact("e1", EVIDENCE, subtype="performance_task"),
        artifact("e2", EVIDENCE, subtype="quiz"),
        links=(Link("i1", "e2"),),
    )
    findings = run_check(
        bind(
            "shared.coverage",
            **{
                "from": {"artifact_type": "Intent"},
                "to": {"artifact_type": "EvidenceSpec", "subtype": "performance_task"},
            },
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("i1",)]


def test_orphan_reports_the_artifact_serving_nothing() -> None:
    graph = context(artifact("i1"), artifact("e1", EXPERIENCE))
    findings = run_check(
        bind(
            "shared.orphan",
            type={"artifact_type": "Experience"},
            must_link_to={"artifact_type": "Intent"},
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("e1",)]


ID = st.text(alphabet="abcde", min_size=1, max_size=3)


@st.composite
def graphs(draw: st.DrawFn) -> CheckContext:
    intents = sorted(draw(st.sets(ID, max_size=5)))
    experiences = sorted("x" + name for name in draw(st.sets(ID, max_size=5)))
    pairs = draw(
        st.lists(
            st.tuples(st.sampled_from(intents or [""]), st.sampled_from(experiences or [""])),
            max_size=8,
        )
    )
    links = tuple(
        Link(experience, intent) for intent, experience in pairs if intent and experience
    )
    return CheckContext(
        artifacts=tuple(artifact(name, INTENT) for name in intents)
        + tuple(artifact(name, EXPERIENCE) for name in experiences),
        links=links,
    )


@given(graphs())
def test_orphan_is_coverage_with_the_ends_swapped(graph: CheckContext) -> None:
    """The load-bearing property: these two are one query read from either end.

    They are kept as separate names because the *message* differs -- an
    uncovered intent and an orphaned experience are different problems to a
    reader -- but if the sets they report ever diverge, one of them is wrong.
    """
    covered = run_check(
        bind(
            "shared.coverage",
            **{
                "from": {"artifact_type": "Experience"},
                "to": {"artifact_type": "Intent"},
            },
        ),
        graph,
    )
    orphans = run_check(
        bind(
            "shared.orphan",
            type={"artifact_type": "Experience"},
            must_link_to={"artifact_type": "Intent"},
        ),
        graph,
    )
    assert {finding.affected_artifact_ids for finding in covered} == {
        finding.affected_artifact_ids for finding in orphans
    }


@given(graphs(), st.integers(min_value=0, max_value=4))
def test_coverage_at_min_zero_can_never_fail(graph: CheckContext, minimum: int) -> None:
    findings = run_check(
        bind(
            "shared.coverage",
            **{
                "from": {"artifact_type": "Intent"},
                "to": {"artifact_type": "Experience"},
                "min": minimum,
            },
        ),
        graph,
    )
    assert findings == [] or minimum > 0


@given(graphs())
def test_coverage_only_ever_names_artifacts_that_exist(graph: CheckContext) -> None:
    known = {item.id for item in graph.artifacts}
    for finding in run_check(
        bind(
            "shared.coverage",
            **{
                "from": {"artifact_type": "Intent"},
                "to": {"artifact_type": "Experience"},
                "min": 2,
            },
        ),
        graph,
    ):
        assert set(finding.affected_artifact_ids) <= known


# --- provenance -------------------------------------------------------------


def test_provenance_rejects_an_empty_list_and_accepts_the_flag() -> None:
    """An empty list is the one shape that is never right; the flag is honest."""
    graph = context(
        artifact("a", INTENT, provenance=()),
        artifact("b", INTENT, provenance=({"source_id": "s1", "start": 0, "end": 9},)),
        artifact("c", INTENT, provenance=({"inferred_not_in_source": True},)),
    )
    findings = run_check(bind("shared.provenance", type={"artifact_type": "Intent"}), graph)
    assert [finding.affected_artifact_ids for finding in findings] == [("a",)]


def test_provenance_rejects_an_entry_that_is_neither_a_citation_nor_a_flag() -> None:
    graph = context(artifact("a", INTENT, provenance=({"note": "from memory"},)))
    findings = run_check(bind("shared.provenance", type={"artifact_type": "Intent"}), graph)
    assert len(findings) == 1


def test_provenance_can_require_a_link_to_a_criterion_document() -> None:
    graph = context(
        artifact("a", INTENT, provenance=({"inferred_not_in_source": True},)),
        artifact("d", ArtifactType.SOURCE_CLAIM),
    )
    findings = run_check(
        bind(
            "shared.provenance",
            type={"artifact_type": "Intent"},
            must_cite={"artifact_type": "SourceClaim"},
        ),
        graph,
    )
    assert findings[0].check == "shared.provenance"


# --- budget -----------------------------------------------------------------


def test_budget_sums_a_duration_against_a_ceiling_read_from_another_artifact() -> None:
    graph = context(
        artifact("p", ArtifactType.CONTEXT_PROFILE, fields={"minutes_available": 60}),
        artifact("e1", EXPERIENCE, fields={"minutes": 40}),
        artifact("e2", EXPERIENCE, fields={"minutes": 40}),
    )
    findings = run_check(
        bind(
            "shared.budget",
            dimension="duration",
            type={"artifact_type": "Experience"},
            value_field="minutes",
            source="ContextProfile.minutes_available",
        ),
        graph,
    )
    assert "80" in findings[0].message


def test_budget_counts_artifacts_when_the_dimension_is_count() -> None:
    graph = context(
        artifact("p", ArtifactType.CONTEXT_PROFILE, fields={"max_objectives": 1}),
        artifact("i1"),
        artifact("i2"),
    )
    findings = run_check(
        bind(
            "shared.budget",
            dimension="count",
            type={"artifact_type": "Intent"},
            source="ContextProfile.max_objectives",
        ),
        graph,
    )
    assert len(findings) == 1


def test_an_unreadable_ceiling_is_a_finding_not_a_silence() -> None:
    """A budget nobody can evaluate must not look like a budget that was met."""
    graph = context(artifact("i1"))
    findings = run_check(
        bind(
            "shared.budget",
            dimension="count",
            type={"artifact_type": "Intent"},
            source="ContextProfile.max_objectives",
        ),
        graph,
    )
    assert len(findings) == 1
    assert findings[0].affected_artifact_ids == ()


# --- format conformance -----------------------------------------------------


def test_format_conformance_enforces_a_stem() -> None:
    graph = context(
        artifact("a", INTENT, fields={"text": "Students will understand that x"}),
        artifact("b", INTENT, fields={"text": "Know the dates"}),
    )
    findings = run_check(
        bind(
            "shared.format_conformance",
            type={"artifact_type": "Intent"},
            field="text",
            stem="Students will understand that",
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("b",)]


def test_format_conformance_rejects_denied_verbs_whole_word() -> None:
    """`understand` is denied; `understanding` in a noun phrase is not the verb."""
    graph = context(
        artifact("a", INTENT, fields={"text": "Learners understand recursion"}),
        artifact("b", INTENT, fields={"text": "Learners trace an understanding graph"}),
    )
    findings = run_check(
        bind(
            "shared.format_conformance",
            type={"artifact_type": "Intent"},
            field="text",
            verb_denylist=["understand", "be aware of", "appreciate"],
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("a",)]


def test_format_conformance_requires_declared_fields() -> None:
    """Tyler's behavior+content pair is exactly this: two fields, both present."""
    graph = context(artifact("a", INTENT, fields={"behavior": "analyse"}))
    findings = run_check(
        bind(
            "shared.format_conformance",
            type={"artifact_type": "Intent"},
            required_fields=["behavior", "content"],
        ),
        graph,
    )
    assert "content" in findings[0].message


def test_format_conformance_reject_if_is_a_regex_over_the_field() -> None:
    graph = context(artifact("a", INTENT, fields={"text": "What year was it?"}))
    findings = run_check(
        bind(
            "shared.format_conformance",
            type={"artifact_type": "Intent"},
            field="text",
            reject_if=[r"^What (year|date)\b"],
        ),
        graph,
    )
    assert len(findings) == 1


# --- taxonomy and vocabulary ------------------------------------------------


def test_taxonomy_distribution_names_the_missing_class() -> None:
    """UbD's A/M/T balance: the empty class is the finding, and it has no artifact."""
    graph = context(
        artifact("a", EXPERIENCE, fields={"code": ["A"]}),
        artifact("b", EXPERIENCE, fields={"code": ["M"]}),
    )
    findings = run_check(
        bind(
            "shared.taxonomy_distribution",
            type={"artifact_type": "Experience"},
            dimension="code",
            classes=["A", "M", "T"],
        ),
        graph,
    )
    assert len(findings) == 1
    assert "T" in findings[0].message
    assert findings[0].affected_artifact_ids == ()


def test_taxonomy_distribution_flags_an_item_claiming_too_many_classes() -> None:
    graph = context(artifact("a", EXPERIENCE, fields={"code": ["A", "M", "T"]}))
    findings = run_check(
        bind(
            "shared.taxonomy_distribution",
            type={"artifact_type": "Experience"},
            dimension="code",
            classes=["A", "M", "T"],
            min_per_class=1,
            max_per_item=1,
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("a",)]


def test_vocabulary_coverage_requires_every_letter_somewhere() -> None:
    graph = context(
        artifact("a", EXPERIENCE, fields={"whereto": "WH"}),
        artifact("b", EXPERIENCE, fields={"whereto": ["E", "R"]}),
    )
    findings = run_check(
        bind(
            "shared.vocabulary_coverage",
            type={"artifact_type": "Experience"},
            dimension="whereto",
            vocab=["W", "H", "E", "R", "E2", "T", "O"],
        ),
        graph,
    )
    missing = {
        word for finding in findings for word in ("E2", "T", "O") if word in finding.message
    }
    assert missing == {"E2", "T", "O"}


# --- the exclusion ledger ---------------------------------------------------


def test_exclusion_ledger_catches_a_candidate_that_simply_vanished() -> None:
    graph = context(
        artifact("c1", INTENT, stage="generate"),
        artifact("c2", INTENT, stage="generate"),
        artifact("s1", INTENT, stage="screen"),
        artifact(
            "led",
            ArtifactType.EXCLUSION,
            fields={"entries": [{"candidate_id": "c1", "reason": "off charter"}]},
        ),
        links=(Link("s1", "c2"),),
    )
    findings = run_check(
        bind(
            "shared.exclusion_ledger",
            candidates={"artifact_type": "Intent", "stage": "generate"},
            survivors={"artifact_type": "Intent", "stage": "screen"},
            ledger={"artifact_type": "Exclusion"},
        ),
        graph,
    )
    assert findings == []

    graph = context(
        artifact("c1", INTENT, stage="generate"),
        artifact("led", ArtifactType.EXCLUSION, fields={"entries": []}),
    )
    findings = run_check(
        bind(
            "shared.exclusion_ledger",
            candidates={"artifact_type": "Intent", "stage": "generate"},
            survivors={"artifact_type": "Intent", "stage": "screen"},
            ledger={"artifact_type": "Exclusion"},
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("c1",)]


def test_exclusion_ledger_rejects_a_blank_reason() -> None:
    graph = context(
        artifact("c1", INTENT, stage="generate"),
        artifact(
            "led",
            ArtifactType.EXCLUSION,
            fields={"entries": [{"candidate_id": "c1", "reason": "  "}]},
        ),
    )
    findings = run_check(
        bind(
            "shared.exclusion_ledger",
            candidates={"artifact_type": "Intent", "stage": "generate"},
            survivors={"artifact_type": "Intent", "stage": "screen"},
            ledger={"artifact_type": "Exclusion"},
        ),
        graph,
    )
    assert len(findings) == 1


# --- the two harness invariants ---------------------------------------------


def test_an_uncited_verdict_is_an_invariant_violation() -> None:
    graph = context(
        artifact(
            "doc",
            ArtifactType.CRITERION_DOCUMENT,
            fields={"clauses": ["p1", "p2"]},
        ),
        artifact(
            "led",
            ArtifactType.VERDICT_LEDGER,
            fields={
                "verdicts": [
                    {"candidate_id": "c1", "verdict": "reject", "clause": "p1"},
                    {"candidate_id": "c2", "verdict": "reject"},
                ]
            },
        ),
    )
    findings = run_check(
        bind(
            "shared.verdict_citation",
            ledger={"artifact_type": "VerdictLedger"},
            criterion_doc={"artifact_type": "CriterionDocument"},
        ),
        graph,
    )
    assert len(findings) == 1
    assert findings[0].severity == "invariant"


def test_a_verdict_citing_a_clause_that_does_not_exist_is_a_violation() -> None:
    graph = context(
        artifact("doc", ArtifactType.CRITERION_DOCUMENT, fields={"clauses": ["p1"]}),
        artifact(
            "led",
            ArtifactType.VERDICT_LEDGER,
            fields={"verdicts": [{"candidate_id": "c", "clause": "p9"}]},
        ),
    )
    findings = run_check(
        bind(
            "shared.verdict_citation",
            ledger={"artifact_type": "VerdictLedger"},
            criterion_doc={"artifact_type": "CriterionDocument"},
        ),
        graph,
    )
    assert len(findings) == 1


def test_a_binding_cannot_downgrade_an_invariant_to_advisory() -> None:
    """The severity of an invariant is not the preset author's to choose."""
    graph = context(
        artifact("doc", ArtifactType.CRITERION_DOCUMENT, fields={"clauses": []}),
        artifact("led", ArtifactType.VERDICT_LEDGER, fields={"verdicts": [{"id": "c"}]}),
    )
    binding = Check(
        check="shared.verdict_citation",
        params={
            "ledger": {"artifact_type": "VerdictLedger"},
            "criterion_doc": {"artifact_type": "CriterionDocument"},
        },
        severity="advisory",
    )
    assert run_check(binding, graph)[0].severity == "invariant"


def _screen(critic: ScreeningCritic) -> ScreenStage:
    return ScreenStage(
        id="tyler.screen.philosophy",
        name="Philosophy screen",
        spine=3,
        scope_level="course",
        critic=critic,
        gate=LedgerGate(reviewer_role="instructor"),
    )


def _generator_stage() -> SpecifyStage:
    return SpecifyStage(
        id="tyler.generate",
        name="Candidate objectives",
        spine=2,
        scope_level="course",
        generator=Generator(role="designer", prompt_ref="prompts/generate.md"),
    )


def test_a_critic_sharing_the_generators_role_fails_the_separation_invariant() -> None:
    stage = _screen(
        ScreeningCritic(
            role="designer",
            prompt_ref="prompts/screen.md",
            criterion_doc="philosophy",
        )
    )
    findings = run_check(
        bind("shared.self_review_separation", generator_stage="tyler.generate"),
        CheckContext(preset_stages=(_generator_stage(), stage), stage=stage),
    )
    assert len(findings) == 1
    assert findings[0].severity == "invariant"


def test_a_critic_that_has_seen_the_generation_trajectory_fails_too() -> None:
    stage = _screen(
        ScreeningCritic(
            role="reviewer",
            prompt_ref="prompts/screen.md",
            criterion_doc="philosophy",
            separate_context=False,
        )
    )
    findings = run_check(
        bind("shared.self_review_separation", generator_stage="tyler.generate"),
        CheckContext(preset_stages=(_generator_stage(), stage), stage=stage),
    )
    assert len(findings) == 1


def test_a_separate_critic_passes_the_separation_invariant() -> None:
    stage = _screen(
        ScreeningCritic(
            role="reviewer",
            prompt_ref="prompts/screen.md",
            criterion_doc="philosophy",
        )
    )
    findings = run_check(
        bind("shared.self_review_separation", generator_stage="tyler.generate"),
        CheckContext(preset_stages=(_generator_stage(), stage), stage=stage),
    )
    assert findings == []


def test_separation_reports_rather_than_raises_when_the_stage_is_unknown() -> None:
    stage = _screen(ScreeningCritic(role="r", prompt_ref="p", criterion_doc="philosophy"))
    findings = run_check(
        bind("shared.self_review_separation", generator_stage="nope"),
        CheckContext(preset_stages=(stage,), stage=stage),
    )
    assert len(findings) == 1


def test_a_stage_reviewing_itself_fails() -> None:
    stage = SpecifyStage(
        id="s",
        name="s",
        spine=2,
        scope_level="course",
        generator=Generator(role="designer", prompt_ref="p"),
        critic=Critic(role="reviewer", prompt_ref="p2"),
    )
    findings = run_check(
        bind("shared.self_review_separation", generator_stage="s"),
        CheckContext(preset_stages=(stage,), stage=stage),
    )
    assert len(findings) == 1


# --- prune ratio ------------------------------------------------------------


def _pool(candidates: int, survivors: int) -> CheckContext:
    return CheckContext(
        artifacts=tuple(
            artifact(f"c{index}", INTENT, stage="generate") for index in range(candidates)
        )
        + tuple(artifact(f"s{index}", INTENT, stage="screen") for index in range(survivors))
    )


PRUNE = bind(
    "shared.prune_ratio",
    candidate_pool={"artifact_type": "Intent", "stage": "generate"},
    survivors={"artifact_type": "Intent", "stage": "screen"},
    expected_range=[0.1, 0.5],
)


def test_a_critic_that_kept_everything_is_a_finding() -> None:
    """The rubber-stamp detector: a screen that rejects nothing screened nothing."""
    assert run_check(PRUNE, _pool(10, 10))


def test_a_prune_inside_the_expected_range_passes() -> None:
    assert run_check(PRUNE, _pool(10, 3)) == []


def test_an_empty_candidate_pool_is_a_finding_not_a_division_by_zero() -> None:
    findings = run_check(PRUNE, _pool(0, 0))
    assert len(findings) == 1


@given(st.integers(min_value=1, max_value=30), st.integers(min_value=0, max_value=30))
def test_prune_ratio_fires_exactly_outside_the_range(candidates: int, survivors: int) -> None:
    ratio = survivors / candidates
    findings = run_check(PRUNE, _pool(candidates, survivors))
    assert bool(findings) == (not 0.1 <= ratio <= 0.5)


# --- non-degenerate required fields -----------------------------------------


def test_required_field_rejects_empty_duplicate_and_generic() -> None:
    graph = context(
        artifact("a", INTENT, fields={"escalation": ""}),
        artifact("b", INTENT, fields={"escalation": "call the on-call engineer"}),
        artifact("c", INTENT, fields={"escalation": "call the on-call engineer"}),
        artifact("d", INTENT, fields={"escalation": "as appropriate"}),
    )
    findings = run_check(
        bind(
            "shared.required_field_nondegenerate",
            type={"artifact_type": "Intent"},
            field="escalation",
            reject_if=["empty", "duplicate", "generic"],
            generic_phrases=["as appropriate"],
        ),
        graph,
    )
    flagged = {item for finding in findings for item in finding.affected_artifact_ids}
    assert flagged == {"a", "b", "c", "d"}


def test_required_field_only_applies_the_rejections_it_was_given() -> None:
    graph = context(
        artifact("b", INTENT, fields={"escalation": "x"}),
        artifact("c", INTENT, fields={"escalation": "x"}),
    )
    findings = run_check(
        bind(
            "shared.required_field_nondegenerate",
            type={"artifact_type": "Intent"},
            field="escalation",
            reject_if=["empty"],
        ),
        graph,
    )
    assert findings == []


# --- recurrence -------------------------------------------------------------


def _recurring(counts: dict[str, int]) -> CheckContext:
    artifacts = [artifact(name, INTENT) for name in counts]
    links = []
    for name, count in counts.items():
        for index in range(count):
            experience = f"{name}-e{index}"
            artifacts.append(artifact(experience, EXPERIENCE))
            links.append(Link(experience, name))
    return CheckContext(artifacts=tuple(artifacts), links=tuple(links))


def test_recurrence_catches_the_intent_taught_once() -> None:
    findings = run_check(
        bind(
            "shared.recurrence",
            type={"artifact_type": "Intent"},
            min_occurrences=2,
        ),
        _recurring({"i1": 1, "i2": 3}),
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("i1",)]


def test_recurrence_can_count_by_a_field_instead_of_by_link() -> None:
    graph = context(
        artifact("a", EXPERIENCE, fields={"thread": "safety"}),
        artifact("b", EXPERIENCE, fields={"thread": "safety"}),
        artifact("c", EXPERIENCE, fields={"thread": "ethics"}),
    )
    findings = run_check(
        bind(
            "shared.recurrence",
            type={"artifact_type": "Experience"},
            key_field="thread",
            min_occurrences=2,
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("c",)]


@given(
    st.dictionaries(ID, st.integers(min_value=0, max_value=4), max_size=5),
    st.integers(min_value=1, max_value=4),
)
def test_recurrence_fires_for_exactly_the_under_counted(
    counts: dict[str, int], minimum: int
) -> None:
    findings = run_check(
        bind(
            "shared.recurrence",
            type={"artifact_type": "Intent"},
            min_occurrences=minimum,
        ),
        _recurring(counts),
    )
    flagged = {item for finding in findings for item in finding.affected_artifact_ids}
    assert flagged == {name for name, count in counts.items() if count < minimum}


@given(st.dictionaries(ID, st.integers(min_value=0, max_value=4), max_size=5))
def test_recurrence_at_one_agrees_with_orphan(counts: dict[str, int]) -> None:
    """At `min_occurrences=1` continuity degenerates into "linked at all"."""
    graph = _recurring(counts)
    recurring = run_check(
        bind("shared.recurrence", type={"artifact_type": "Intent"}, min_occurrences=1),
        graph,
    )
    orphans = run_check(
        bind(
            "shared.orphan",
            type={"artifact_type": "Intent"},
            must_link_to={"artifact_type": "Experience"},
        ),
        graph,
    )
    assert {finding.affected_artifact_ids for finding in recurring} == {
        finding.affected_artifact_ids for finding in orphans
    }


# --- ordering and prerequisites ---------------------------------------------


def test_ordering_requires_the_element_early_in_the_sequence() -> None:
    graph = context(
        *(
            artifact(f"e{index}", EXPERIENCE, fields={"position": index, "code": "E"})
            for index in range(9)
        ),
        artifact("late", EXPERIENCE, fields={"position": 9, "code": "W"}),
    )
    findings = run_check(
        bind(
            "shared.ordering",
            type={"artifact_type": "Experience"},
            element="W",
            element_field="code",
            position_percentile=0.34,
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("late",)]


def test_ordering_reports_an_element_that_never_appears() -> None:
    graph = context(artifact("e", EXPERIENCE, fields={"position": 0, "code": "E"}))
    findings = run_check(
        bind(
            "shared.ordering",
            type={"artifact_type": "Experience"},
            element="W",
            element_field="code",
            position_percentile=0.34,
        ),
        graph,
    )
    assert findings[0].affected_artifact_ids == ()


def test_prerequisite_must_exist_and_come_first() -> None:
    graph = context(
        artifact("skill", EXPERIENCE, fields={"position": 5, "key": "regex"}),
        artifact(
            "task",
            EVIDENCE,
            fields={"position": 2, "requires": ["regex", "parsing"]},
        ),
    )
    findings = run_check(
        bind(
            "shared.prerequisite_satisfied",
            **{
                "for": {"artifact_type": "EvidenceSpec"},
                "required_from": {"artifact_type": "Experience"},
                "via": "requires",
                "key_field": "key",
            },
        ),
        graph,
    )
    messages = " ".join(finding.message for finding in findings)
    assert "parsing" in messages and "regex" in messages


# --- source starvation and contradiction escalation -------------------------


def test_source_starvation_reports_the_source_nothing_drew_on() -> None:
    graph = context(
        artifact("d1", ArtifactType.SOURCE_DOCUMENT, fields={"source_id": "s1"}),
        artifact("d2", ArtifactType.SOURCE_DOCUMENT, fields={"source_id": "s2"}),
        artifact(
            "c1",
            ArtifactType.SOURCE_CLAIM,
            provenance=({"source_id": "s1", "start": 0, "end": 3},),
        ),
    )
    findings = run_check(
        bind(
            "shared.source_starvation",
            sources={"artifact_type": "SourceDocument"},
            claims={"artifact_type": "SourceClaim"},
            min_claims_each=1,
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("d2",)]


def test_a_contradiction_resolved_without_a_named_human_is_a_finding() -> None:
    graph = context(
        artifact(
            "log",
            ArtifactType.CONTESTED_QUEUE,
            fields={
                "entries": [
                    {"id": "x", "resolution": "took the newer one"},
                    {"id": "y", "resolution": "sme said 4h", "escalated_to": "dana"},
                    {"id": "z"},
                ]
            },
        )
    )
    findings = run_check(
        bind("shared.contradiction_escalation", type={"artifact_type": "ContestedQueue"}),
        graph,
    )
    messages = " ".join(finding.message for finding in findings)
    assert "x" in messages and "z" in messages and "y" not in messages


# --- the check that is deliberately not implemented -------------------------


def test_uncoverage_is_registered_as_a_human_gate_with_no_automated_run() -> None:
    """Honesty beats coverage here: a fake `uncoverage` would be worse than none.

    The registry carries it so a preset can bind it and a reviewer can see it,
    and running it yields a standing finding rather than a pass -- a human gate
    that silently satisfies itself is the failure this whole module exists to
    prevent.
    """
    assert "ubd.uncoverage" in human_gates()
    assert REGISTRY["ubd.uncoverage"].human_gate
    findings = run_check(bind("ubd.uncoverage"), context(artifact("a")))
    assert len(findings) == 1
    assert findings[0].severity == "human_gate"
    assert findings[0].suggested_edit is None


def test_no_check_reaches_for_a_model() -> None:
    """The governing property, asserted where it can be seen rather than trusted.

    Cheap enough to run on every stage exit and trustworthy enough to gate on
    are both consequences of this one line: nothing in here calls out.
    """
    source = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("research_team/application/checks.py")
        .read_text()
    )
    for forbidden in ("langchain", "deepagents", "openai", "httpx", "requests"):
        assert forbidden not in source


# --- running a set of bindings ----------------------------------------------


def test_run_checks_returns_the_findings_of_every_binding_in_order() -> None:
    graph = context(artifact("i1"), artifact("i2"))
    findings = run_checks(
        (
            bind(
                "shared.coverage",
                **{
                    "from": {"artifact_type": "Intent"},
                    "to": {"artifact_type": "Experience"},
                },
            ),
            bind("shared.provenance", type={"artifact_type": "Intent"}),
        ),
        graph,
    )
    assert [finding.check for finding in findings] == [
        "shared.coverage",
        "shared.coverage",
        "shared.provenance",
        "shared.provenance",
    ]


def test_an_advisory_binding_yields_advisory_findings() -> None:
    graph = context(artifact("i1"))
    binding = Check(
        check="shared.provenance",
        params={"type": {"artifact_type": "Intent"}},
        severity="advisory",
    )
    assert run_check(binding, graph)[0].severity == "advisory"


def test_a_gate_is_not_needed_to_run_checks() -> None:
    """Checks read artifacts; they never need to know what the gate decided."""
    assert DecisionGate(reviewer_role="sponsor").decisions
    assert run_checks((), context()) == []


# ---- the shipped presets, against the registry ----
#
# The two tests below guard opposite halves of the same seam, which is why
# neither replaces the other. `test_a_binding_naming_no_registered_check_is_
# reported_not_ignored` in `test_stage_exit.py` covers the runtime half: a
# binding that cannot resolve is reported rather than skipped. These cover the
# static half -- that no preset we actually ship names a check that does not
# exist.
#
# Written after `shared.matrix_density` was defined, exported, agreed by two
# people to be registered, and registered nowhere. Every unit test passed
# throughout, because each side of the seam was tested and the seam was not.
# Without this, such a preset fails only when someone reaches that stage, which
# may be an hour into a turn and days into a run.


@pytest.mark.parametrize("preset", list(PRESETS.values()), ids=list(PRESETS.keys()))
def test_every_check_a_shipped_preset_declares_is_registered(preset) -> None:
    """A preset naming an unregistered check is a typo that ships."""
    declared = {(stage.id, check.check) for stage in preset.stages for check in stage.checks}
    missing = sorted(
        f"{stage_id} -> {name}" for stage_id, name in declared if name not in REGISTRY
    )
    assert missing == [], f"{preset.id} names checks that do not exist: {missing}"


@pytest.mark.parametrize("preset", list(PRESETS.values()), ids=list(PRESETS.keys()))
def test_every_check_a_shipped_preset_declares_accepts_its_parameters(preset) -> None:
    """Registration is not enough: the parameters have to be ones it takes.

    A check that resolves and then raises `MalformedCheck` at stage exit is no
    better off than one that never resolved -- the failure has just moved later
    and become harder to attribute. `run_check` is the thing that validates
    parameters, so asking it is the only honest way to test this.
    """
    context = CheckContext(artifacts=(), links=())
    for stage in preset.stages:
        for check in stage.checks:
            if check.check in human_gates():
                continue
            try:
                run_check(check, context)
            except MalformedCheck as error:
                raise AssertionError(
                    f"{preset.id}/{stage.id} binds {check.check} with parameters "
                    f"it does not accept: {error}"
                ) from error


# --- the shorthand, and the methodology-specific checks ----------------------


def test_a_bare_string_is_a_whole_type_filter() -> None:
    """`"Intent"` and `{"artifact_type": "Intent"}` must not be able to diverge."""
    graph = context(artifact("i1"), artifact("e1", EXPERIENCE))
    assert run_check(
        bind("shared.orphan", type="Intent", must_link_to="Experience"), graph
    ) == run_check(
        bind(
            "shared.orphan",
            type={"artifact_type": "Intent"},
            must_link_to={"artifact_type": "Experience"},
        ),
        graph,
    )


def test_a_dotted_string_carries_the_subtype() -> None:
    graph = context(
        artifact("t1", EVIDENCE, subtype="performance_task"),
        artifact("q1", EVIDENCE, subtype="quiz"),
    )
    findings = run_check(
        bind("shared.orphan", type="EvidenceSpec.performance_task", must_link_to="Intent"),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("t1",)]


def test_the_shorthand_still_rejects_a_type_that_does_not_exist() -> None:
    """Shorthand must cost no validation, or it buys convenience with typos."""
    with pytest.raises(MalformedCheck):
        run_check(bind("shared.orphan", type="SourceClam"), context())


def test_an_unsigned_criterion_document_fails_the_tautology_guard() -> None:
    graph = context(
        artifact("phil", ArtifactType.CRITERION_DOCUMENT, fields={"name": "tyler.philosophy"})
    )
    findings = run_check(
        bind("tyler.criterion_doc_authored", doc="tyler.philosophy"),
        graph,
    )
    assert len(findings) == 1
    assert "authored_by" in findings[0].message


def test_a_criterion_document_derived_from_the_screened_corpus_is_a_tautology() -> None:
    """The failure this exists for: a philosophy that agrees with the corpus.

    It approves nearly everything and the ledger looks like a working screen,
    which is why it cannot be left to a reviewer to notice.
    """
    graph = context(
        artifact(
            "phil",
            ArtifactType.CRITERION_DOCUMENT,
            fields={"name": "tyler.philosophy", "authored_by": "dana"},
            provenance=({"source_id": "s1", "start": 0, "end": 10},),
        ),
        artifact("c1", ArtifactType.SOURCE_CLAIM, fields={"source_id": "s1"}),
    )
    findings = run_check(
        bind(
            "tyler.criterion_doc_authored",
            doc="tyler.philosophy",
            forbid_derivation_from="SourceClaim",
        ),
        graph,
    )
    assert findings == []

    graph = context(
        artifact(
            "phil",
            ArtifactType.CRITERION_DOCUMENT,
            fields={"name": "tyler.philosophy", "authored_by": "dana"},
        ),
        artifact("c1", ArtifactType.SOURCE_CLAIM),
        links=(Link("phil", "c1"),),
    )
    findings = run_check(
        bind(
            "tyler.criterion_doc_authored",
            doc="tyler.philosophy",
            forbid_derivation_from="SourceClaim",
        ),
        graph,
    )
    assert len(findings) == 1
    assert "tautology" in (findings[0].suggested_edit or "")


def test_a_missing_criterion_document_is_reported_not_skipped() -> None:
    findings = run_check(bind("tyler.criterion_doc_authored", doc="nope"), context())
    assert len(findings) == 1


def _ladder_stage() -> ProduceStage:
    return ProduceStage(
        id="addie.v1.build",
        name="Build",
        spine=8,
        scope_level="asset",
        generator=Generator(role="developer", prompt_ref="p"),
        gate=MaturityGate(
            reviewer_role="sponsor",
            rungs=(
                Rung(
                    name="beta",
                    reviewer_role="sponsor",
                    permitted_change=("cosmetic", "verification"),
                    forbidden_change=("substantive",),
                ),
            ),
        ),
    )


def test_change_scope_reads_the_ladder_the_stage_actually_has() -> None:
    stage = _ladder_stage()
    passing = run_check(
        bind(
            "addie.change_scope",
            maturity="beta",
            permitted=["cosmetic"],
            forbidden=["substantive"],
        ),
        CheckContext(stage=stage),
    )
    assert passing == []

    findings = run_check(
        bind("addie.change_scope", maturity="beta", forbidden=["cosmetic"]),
        CheckContext(stage=stage),
    )
    assert len(findings) == 1
    assert "not actually constrained" in findings[0].message


def test_change_scope_on_a_stage_with_no_ladder_says_so() -> None:
    """§4: the check is only meaningful against a maturity ladder.

    Passing would tell a reader a stage everyone believes is scope-limited is
    limited, when nothing is limiting it.
    """
    stage = SpecifyStage(
        id="s",
        name="s",
        spine=4,
        scope_level="course",
        generator=Generator(role="d", prompt_ref="p"),
    )
    findings = run_check(
        bind("addie.change_scope", maturity="gold"), CheckContext(stage=stage)
    )
    assert len(findings) == 1
    assert "constrains nothing" in findings[0].message


def test_expert_gap_flag_is_owed_to_a_critic_not_faked_here() -> None:
    """A model can answer this; a graph query cannot. The registry says which.

    Distinct from `ubd.uncoverage`, which no model should be trusted with
    either -- collapsing the two would triage them as one problem.
    """
    assert "addie.expert_gap_flag" in critic_gates()
    assert "addie.expert_gap_flag" not in human_gates()
    findings = run_check(bind("addie.expert_gap_flag", quote_span_required=True), context())
    assert len(findings) == 1
    assert findings[0].severity == "critic_gate"


def test_a_gate_still_validates_its_parameters() -> None:
    """The parameters are read by whoever answers the gate, so a typo is real."""
    with pytest.raises(MalformedCheck):
        run_check(bind("addie.expert_gap_flag", quote_spans_required=True), context())


# --- the parameters the shipped presets needed -------------------------------


def test_taxonomy_takes_a_floor_per_class() -> None:
    graph = context(
        artifact("a", EXPERIENCE, fields={"code": ["A"]}),
        artifact("b", EXPERIENCE, fields={"code": ["A"]}),
    )
    findings = run_check(
        bind(
            "shared.taxonomy_distribution",
            type="Experience",
            dimension="code",
            min_per_class={"A": 2, "M": 1, "T": 1},
        ),
        graph,
    )
    assert {finding.message.split("'")[1] for finding in findings} == {"M", "T"}


def test_an_item_must_match_the_taxonomy_of_the_objective_it_serves() -> None:
    graph = context(
        artifact("obj", INTENT, fields={"bloom_level": "evaluate"}),
        artifact("item", EVIDENCE, fields={"blooms_revised": "remember"}),
        links=(Link("item", "obj"),),
    )
    findings = run_check(
        bind(
            "shared.taxonomy_distribution",
            type="EvidenceSpec",
            dimension="blooms_revised",
            must_match_parent="Intent.bloom_level",
        ),
        graph,
    )
    assert findings[0].affected_artifact_ids == ("item", "obj")


def test_vocabulary_can_require_a_mandatory_subset_only() -> None:
    """A rubric may pick its criterion types, but `impact` is not optional."""
    graph = context(artifact("r", ArtifactType.CRITERIA, fields={"kind": "process"}))
    findings = run_check(
        bind(
            "shared.vocabulary_coverage",
            type="Criteria",
            dimension="kind",
            vocab=["impact", "content", "quality", "process"],
            min_required=["impact"],
        ),
        graph,
    )
    assert len(findings) == 1
    assert "impact" in findings[0].message


def test_a_flat_spiral_is_caught_within_its_thread_and_not_across_threads() -> None:
    """Two threads sharing wording is coincidence; one repeating itself is flat."""
    graph = context(
        artifact("a1", EXPERIENCE, fields={"thread": "x", "position": 1, "esc": "same"}),
        artifact("a2", EXPERIENCE, fields={"thread": "x", "position": 2, "esc": "same"}),
        artifact("b1", EXPERIENCE, fields={"thread": "y", "position": 1, "esc": "same"}),
    )
    findings = run_check(
        bind(
            "shared.required_field_nondegenerate",
            type="Experience",
            field="esc",
            per="thread",
            reject_if=["duplicate_of_previous"],
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("a1", "a2")]


def test_an_unmeasurable_business_metric_is_one_with_no_number_in_it() -> None:
    graph = context(
        artifact("g1", ArtifactType.GAP_STATEMENT, fields={"metric": "reduce escalations"}),
        artifact(
            "g2", ArtifactType.GAP_STATEMENT, fields={"metric": "cut escalations 15% by Q3"}
        ),
    )
    findings = run_check(
        bind(
            "shared.required_field_nondegenerate",
            type="GapStatement",
            field="metric",
            reject_if=["unmeasurable"],
        ),
        graph,
    )
    assert [finding.affected_artifact_ids for finding in findings] == [("g1",)]


def test_starvation_counts_named_routes_not_only_documents() -> None:
    """Tyler's three sources are routes; a design claiming three and using one."""
    graph = context(
        artifact("c1", ArtifactType.SOURCE_CLAIM, fields={"route": "learner"}),
        artifact("c2", ArtifactType.SOURCE_CLAIM, fields={"route": "learner"}),
    )
    findings = run_check(
        bind(
            "shared.source_starvation",
            routes=["learner", "contemporary_life", "discipline"],
            claims="SourceClaim",
        ),
        graph,
    )
    assert {finding.message.split("'")[1] for finding in findings} == {
        "contemporary_life",
        "discipline",
    }


def test_a_starvation_binding_that_names_nothing_is_malformed() -> None:
    with pytest.raises(MalformedCheck):
        run_check(bind("shared.source_starvation"), context())


def test_an_unresolvable_citation_can_contest_the_verdict_instead_of_failing_it() -> None:
    """Tyler's screens need a third answer: not upheld, not discarded, owed."""
    graph = context(
        artifact("led", ArtifactType.VERDICT_LEDGER, fields={"verdicts": [{"clause": "p1"}]})
    )
    findings = run_check(
        bind(
            "shared.verdict_citation",
            ledger="VerdictLedger",
            criterion_doc="CriterionDocument",
            on_retrieval_failure="force_verdict_contested",
        ),
        graph,
    )
    assert len(findings) == 1
    assert "contested" in findings[0].message


def test_budget_reads_its_ceiling_from_a_dotted_path() -> None:
    graph = context(
        artifact("p", ArtifactType.CONTEXT_PROFILE, fields={"max_intents": 1}),
        artifact("i1"),
        artifact("i2"),
    )
    findings = run_check(
        bind(
            "shared.budget",
            dimension="count",
            type="Intent",
            source="ContextProfile.max_intents",
        ),
        graph,
    )
    assert len(findings) == 1


def test_a_matrix_that_was_never_built_is_a_finding_not_a_malformed_binding() -> None:
    """The binding is well formed; the wiring is missing. Different fix, different reader."""
    findings = run_check(bind("shared.matrix_density", matrix="intent_x_evidence"), context())
    assert len(findings) == 1
    assert "never checked" in findings[0].message
