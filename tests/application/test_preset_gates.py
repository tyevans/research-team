"""The oracle for gate contents, which until now had none.

`test_checks.py`'s preset guards cover check bindings: every name resolves, and
every parameter set is one its check accepts. Nothing covered the *other* half
of a stage's declaration. A `presents` tuple naming an artifact type that does
not exist, or a rung no ladder declares, passed every test in the suite -- and
a gate that presents the wrong thing is a rubber stamp with an audit trail,
which is `workflow.py`'s own description of the failure.

This was written after `hybrid.default`'s formative tryout was found presenting
`Build.beta` where it should present `Build.alpha`. **None of the structural
guards here would have caught that**, and saying so precisely matters more than
the guards themselves: `beta` is a real rung of a real ladder, so every
property below holds for it. That instance is pinned by value in
`test_the_formative_tryout_gates_promotion_out_of_alpha`, and the gap is
asserted in `test_no_structural_guard_here_would_catch_the_wrong_rung`. Do not
widen the claim without widening the code.

What a `presents` entry looks like, from the shipped presets:

    Build.*                        an artifact type, every instance
    Build.alpha                    an artifact type at a named maturity rung
    EvidenceSpec.assessment_item.* a subtype, then a view facet
    VerdictLedger.philosophy.reject   a subtype, then a facet
    checks.source_starvation       the findings of a check bound on this stage
    critic.adversarial_case        the critic's counter-case
    answer_keys                    a literal, not an artifact

so the head of an entry is either an `ArtifactType` or a member of a small
closed set. Keeping that set closed is deliberate: a new namespace has to be
added here, which makes adding one an edit somebody reviews rather than a typo
that silently becomes a category.
"""

import pytest

from research_team.domain.workflow import (
    ArtifactType,
    FieldGate,
    LedgerGate,
    MaturityGate,
    Preset,
    StageBase,
)
from research_team.workflows import PRESETS

ALL_PRESETS = pytest.mark.parametrize(
    "preset", list(PRESETS.values()), ids=list(PRESETS.keys())
)

ARTIFACT_TYPES = {member.value for member in ArtifactType}

NON_ARTIFACT_HEADS = frozenset({"checks", "critic", "answer_keys"})
"""`presents` heads that are not artifact types.

Closed on purpose. `checks.*` and `critic.*` are resolved against the stage
below; `answer_keys` is a literal with nothing to resolve it against, and is
listed rather than pattern-matched so that the next literal is a deliberate
addition instead of an unnoticed one.
"""

#: Gate kinds whose whole purpose is to put an artifact in front of a human.
#: A gate of one of these kinds presenting nothing an available stage produces
#: is unsatisfiable in principle, not merely empty on a given run.
MUST_BE_SATISFIABLE = (FieldGate, MaturityGate, LedgerGate)


def gates(preset: Preset) -> list[tuple[StageBase, object]]:
    return [(stage, stage.gate) for stage in preset.stages if getattr(stage, "gate", None)]


def produced_types(preset: Preset) -> set[str]:
    return {output.artifact_type.value for stage in preset.stages for output in stage.outputs}


def declared_subtypes(preset: Preset, artifact_type: str) -> set[str]:
    return {
        output.subtype
        for stage in preset.stages
        for output in stage.outputs
        if output.artifact_type.value == artifact_type and output.subtype
    }


def rungs_for(preset: Preset, artifact_type: str) -> set[str]:
    """Rung names of any ladder gating a stage that produces `artifact_type`.

    `Build.alpha` is not a subtype -- the build stage's `Build` output has no
    subtype at all. `alpha` is a rung of the `MaturityGate` on the stage that
    produces it, referenced from a *different* stage's gate. Resolving it means
    going to the producer, which is why this is a preset-level lookup rather
    than a stage-level one.
    """
    found: set[str] = set()
    for stage in preset.stages:
        if not any(output.artifact_type.value == artifact_type for output in stage.outputs):
            continue
        gate = getattr(stage, "gate", None)
        found |= {rung.name for rung in getattr(gate, "rungs", ()) or ()}
    return found


# --- what every gate must satisfy --------------------------------------------


@ALL_PRESETS
def test_every_presents_entry_has_a_head_this_project_recognises(preset: Preset) -> None:
    """A typo'd artifact type in `presents` is invisible without this.

    `SourceDosier.*` names nothing, resolves to nothing, and shows the reviewer
    nothing -- while reading, in the preset source, exactly like a line that
    works.
    """
    unknown = sorted(
        f"{stage.id} -> {entry}"
        for stage, gate in gates(preset)
        for entry in gate.presents
        if entry.split(".")[0] not in ARTIFACT_TYPES
        and entry.split(".")[0] not in NON_ARTIFACT_HEADS
    )
    assert unknown == [], f"{preset.id} presents unrecognised things: {unknown}"


@ALL_PRESETS
def test_every_presented_qualifier_resolves_to_a_subtype_or_a_rung(preset: Preset) -> None:
    """`Build.gamma` and `VerdictLedger.philosphy` are caught here.

    The qualifier after an artifact type is one of three things: `*` for every
    instance, a subtype some stage declares, or a rung of the ladder gating the
    stage that produces it. Anything else is a reference to something that does
    not exist, and the gate will show the reviewer an empty panel.

    Trailing segments beyond the qualifier -- the `.reject` of
    `VerdictLedger.philosophy.reject` -- are view facets and are not resolved:
    they name how the viewer should slice what it was given, and no artifact
    declaration carries them.
    """
    dangling: list[str] = []
    for stage, gate in gates(preset):
        for entry in gate.presents:
            parts = entry.split(".")
            head = parts[0]
            if head not in ARTIFACT_TYPES or len(parts) == 1:
                continue
            qualifier = parts[1]
            if qualifier == "*":
                continue
            known = declared_subtypes(preset, head) | rungs_for(preset, head)
            if qualifier not in known:
                dangling.append(f"{stage.id} -> {entry} (known: {sorted(known) or 'none'})")
    assert dangling == [], f"{preset.id} presents unresolvable qualifiers: {sorted(dangling)}"


@ALL_PRESETS
def test_a_presented_check_is_one_the_stage_actually_binds(preset: Preset) -> None:
    """`checks.source_starvation` is a promise that the stage runs that check.

    Presenting the findings of a check the stage does not bind shows the
    reviewer an empty panel where they were told to expect the evidence, which
    is worse than not offering it -- an empty findings panel reads as "nothing
    was wrong".

    Matched on the last segment because a preset writes `checks.coverage` while
    the binding is `shared.coverage`; the namespace is the registry's business
    and the gate has no reason to name it.
    """
    missing: list[str] = []
    for stage, gate in gates(preset):
        bound = {binding.check.rsplit(".", 1)[-1] for binding in stage.checks}
        missing += [
            f"{stage.id} -> {entry}"
            for entry in gate.presents
            if entry.startswith("checks.") and entry.split(".", 1)[1] not in bound
        ]
    assert missing == [], f"{preset.id} presents unbound checks: {sorted(missing)}"


@ALL_PRESETS
def test_a_presented_critic_output_means_the_stage_has_a_critic(preset: Preset) -> None:
    offenders = sorted(
        f"{stage.id} -> {entry}"
        for stage, gate in gates(preset)
        for entry in gate.presents
        if entry.startswith("critic.") and getattr(stage, "critic", None) is None
    )
    assert offenders == [], f"{preset.id} presents critic output with no critic: {offenders}"


@ALL_PRESETS
def test_every_blocking_gate_kind_is_satisfiable_in_principle(preset: Preset) -> None:
    """A gate that can never be shown its subject cannot ever be answered.

    Distinct from "presents nothing on this run", which is a runtime fact about
    one course. This is a property of the preset: no stage anywhere in it
    produces the artifact the gate exists to put in front of somebody, so the
    gate is unanswerable for every course the preset will ever run.
    """
    available = produced_types(preset)
    unsatisfiable: list[str] = []
    for stage, gate in gates(preset):
        if not isinstance(gate, MUST_BE_SATISFIABLE):
            continue
        named = {
            entry.split(".")[0]
            for entry in gate.presents
            if entry.split(".")[0] in ARTIFACT_TYPES
        }
        if named and not named & available:
            unsatisfiable.append(f"{stage.id} -> {sorted(named)}")
    assert unsatisfiable == [], (
        f"{preset.id} has gates nothing can satisfy: {sorted(unsatisfiable)}"
    )


@ALL_PRESETS
def test_every_gate_presents_something(preset: Preset) -> None:
    """`presents` defaults to empty, so this is one deletion away at all times.

    "A gate that presents the wrong thing is a rubber stamp with an audit
    trail" -- and one that presents nothing is the same stamp without even the
    wrong thing to look at.
    """
    silent = sorted(stage.id for stage, gate in gates(preset) if not gate.presents)
    assert silent == [], f"{preset.id} has gates that show the reviewer nothing: {silent}"


@ALL_PRESETS
def test_the_run_can_still_be_stopped(preset: Preset) -> None:
    """The counterweight, asserted where deleting it is visible.

    `problems()` enforces this at construction, so this test is belt and
    braces -- but the two failures are different. Relaxing `problems()` is a
    domain edit somebody reviews; this asserts the *property* survives that
    edit, and states in one place that every preset can answer "no course",
    including the two methodologies whose own traditions cannot.
    """
    haltable = [
        stage.id for stage, gate in gates(preset) if "halt" in getattr(gate, "decisions", ())
    ]
    assert haltable, f"{preset.id} cannot be stopped: no gate offers halt"


# --- the boundary of this file's claim ---------------------------------------


@pytest.mark.parametrize("preset_id", ["hybrid.default", "addie.pure"])
def test_the_formative_tryout_gates_promotion_out_of_alpha(preset_id: str) -> None:
    """A regression pin for one instance, and honestly nothing more than that.

    The research puts ADDIE's formative tryout "between Alpha and Beta": it
    gates promotion *out of alpha*, so alpha is what it must put in front of
    the learners. `hybrid.default` presented `Build.beta`, which lets
    substantive change arrive after the rung where the ladder is supposed to
    have stopped accepting it -- the entire discipline the maturity gate
    encodes.

    Pinned by value because no structural property reaches it; see the test
    below. A pin catches this stage regressing and catches nothing else, which
    is the correct claim to make for it.
    """
    preset = PRESETS[preset_id]
    tryout = next(stage for stage in preset.stages if stage.id == "addie.v2.tryout")
    assert tryout.gate.presents == ("Build.alpha",)


def test_no_structural_guard_here_would_catch_the_wrong_rung() -> None:
    """The acceptance criterion, stated as an assertion so it cannot rot.

    `Build.beta` on the formative tryout satisfies **every** structural
    property this file checks: `Build` is a real `ArtifactType`, `beta` is a
    real rung of the real ladder on `addie.v1.build`, that stage really
    produces `Build`, and the gate really shows something. The error is *which*
    correct-looking rung was named, and nothing in the preset encodes which
    rung a field stage sits below -- so there is nothing here to contradict.

    This test asserts the gap rather than the fix, so that if someone later
    makes the class reachable, this fails and forces the docstrings above to be
    rewritten instead of quietly overclaiming.

    Closing it needs a schema change, not a cleverer test: a `FieldGate` would
    have to declare the rung it gates promotion out of --
    `gates_promotion_from: "alpha"` -- at which point "the rung you present is
    the rung you gate" becomes a structural property. That is a domain
    decision and is deliberately not taken here.
    """
    preset = PRESETS["hybrid.default"]
    head, qualifier = "Build", "beta"

    assert head in ARTIFACT_TYPES
    assert qualifier in rungs_for(preset, head)
    assert head in produced_types(preset)
