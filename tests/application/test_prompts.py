"""The prompt loader, the resolver, and the rules that make a missing one loud.

Every prompt in this file is a fixture written into `tmp_path`. Nothing here
reads `prompts/` in the repository: the real prompts are instructional-design
content on their own schedule, and a loader test that depended on them would
fail for reasons that have nothing to do with the loader.

The exceptions are the three tests at the bottom, which are *about* the shipped
presets rather than about the loader, and read `PRESETS` deliberately.
"""

from pathlib import Path

import pytest

from research_team.application.prompts import (
    ALLOWED_CROSS_STAGE_REFS,
    DirectoryPromptLibrary,
    PromptError,
    intended_for_disagreements,
    load_prompts,
    orphaned_refs,
    prompt_digest,
    referenced_prompts,
    role_line,
    shared_ref_problems,
    stage_prompt,
    unresolved,
)
from research_team.domain.workflow import Generator
from research_team.workflows import PRESETS, ubd_pure


def write_prompt(
    root: Path,
    ref: str,
    *,
    kind: str = "generator",
    body: str = "Teach the methodology.",
    declared_ref: str | None = None,
    intended_for: tuple[str, ...] = (),
    version: int = 1,
) -> Path:
    """A prompt file at `root/<ref minus the root's name>.md`.

    `declared_ref` defaults to `ref`, and is separate so a test can write the
    one file the integrity check exists for: a prompt moved without its
    frontmatter following it.
    """
    relative = ref.split("/", 1)[1]
    path = root / f"{relative}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"prompt_ref: {declared_ref if declared_ref is not None else ref}",
        f"version: {version}",
        f"kind: {kind}",
        "methodology: ubd",
        "intended_for:",
        *(f"  - {entry}" for entry in intended_for),
        "summary: A fixture.",
        "---",
        "",
        body,
        "",
    ]
    path.write_text("\n".join(lines))
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "prompts"
    directory.mkdir()
    return directory


# --- loading ----------------------------------------------------------------


def test_a_prompt_loads_with_its_frontmatter_and_body(root: Path) -> None:
    write_prompt(root, "prompts/ubd/stage1_generate", body="A transfer goal is...")
    loaded = load_prompts(root)
    prompt = loaded["prompts/ubd/stage1_generate"]
    assert prompt.kind == "generator"
    assert prompt.methodology == "ubd"
    assert prompt.body.strip() == "A transfer goal is..."


def test_the_ref_is_the_path_so_nesting_is_free(root: Path) -> None:
    """A prompt three directories deep gets the ref its path spells.

    The ref includes the root directory's own name -- `prompts/ubd/...`, not
    `ubd/...` -- because that is what the presets already say, and the loader
    has no business being the second opinion on it.
    """
    write_prompt(root, "prompts/addie/deep/nested/thing")
    assert "prompts/addie/deep/nested/thing" in load_prompts(root)


def test_a_prompt_whose_frontmatter_disagrees_with_its_path_is_refused(root: Path) -> None:
    """The integrity check §2.2 exists for: a file moved, its frontmatter not.

    Without this the file loads under its new path, the old ref stops
    resolving, and the failure surfaces as a stage running the wrong prompt
    rather than as a load error.
    """
    write_prompt(
        root,
        "prompts/ubd/stage1_generate",
        declared_ref="prompts/ubd/stage_one_generate",
    )
    with pytest.raises(PromptError, match="stage1_generate"):
        load_prompts(root)


def test_a_prompt_with_no_frontmatter_is_refused(root: Path) -> None:
    (root / "bare.md").write_text("Just prose, no block.")
    with pytest.raises(PromptError, match="frontmatter"):
        load_prompts(root)


def test_a_prompt_missing_a_required_field_is_refused(root: Path) -> None:
    (root / "partial.md").write_text("---\nprompt_ref: prompts/partial\n---\n\nBody.\n")
    with pytest.raises(PromptError, match="kind"):
        load_prompts(root)


def test_a_prompt_with_an_unknown_kind_is_refused(root: Path) -> None:
    """`kind` is a closed set because the resolver dispatches on it.

    A typo'd `critique` would resolve as neither and the mismatch check below
    would pass it, which is the failure that check exists to prevent.
    """
    write_prompt(root, "prompts/ubd/x", kind="critique")
    with pytest.raises(PromptError, match="kind"):
        load_prompts(root)


def test_an_empty_prompt_body_is_refused(root: Path) -> None:
    """A prompt that resolves to nothing is the failure §2.3 rules out.

    An empty resolution is indistinguishable from today's unprompted stage, so
    it has to fail at load rather than produce a run nobody can tell was
    unprompted.
    """
    write_prompt(root, "prompts/ubd/x", body="   ")
    with pytest.raises(PromptError, match="empty"):
        load_prompts(root)


def test_a_directory_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="no prompt directory"):
        load_prompts(tmp_path / "absent")


# --- resolving --------------------------------------------------------------


def test_resolving_returns_the_body_not_the_frontmatter(root: Path) -> None:
    write_prompt(root, "prompts/ubd/stage1_generate", body="A transfer goal is...")
    library = DirectoryPromptLibrary.load(root)
    resolved = library.resolve("prompts/ubd/stage1_generate", kind="generator")
    assert "A transfer goal is..." in resolved
    assert "prompt_ref:" not in resolved


def test_a_missing_ref_raises_naming_the_ref(root: Path) -> None:
    """The common case for the next 32 refs, and it must be unmistakable.

    There is no fallback and no empty string: §2.3's argument is that an empty
    prompt is indistinguishable from the behaviour the system has today, which
    is precisely the failure that would go unnoticed.
    """
    library = DirectoryPromptLibrary.load(root)
    with pytest.raises(PromptError, match="prompts/ubd/stage1_generate"):
        library.resolve("prompts/ubd/stage1_generate", kind="generator")


def test_a_generator_ref_pointing_at_a_critic_file_raises(root: Path) -> None:
    """The self-review failure arriving through the filesystem.

    `checks.py:1110` compares the two `prompt_ref` *strings*, so two distinct
    refs whose files hold the same critic prompt sail past it. `kind` is the
    only thing standing between that and a critic reviewing its own argument.
    """
    write_prompt(root, "prompts/ubd/stage1_generate", kind="critic")
    library = DirectoryPromptLibrary.load(root)
    with pytest.raises(PromptError, match="kind"):
        library.resolve("prompts/ubd/stage1_generate", kind="generator")


@pytest.mark.parametrize(
    "ref",
    ["prompts/../../secrets", "/etc/passwd", "elsewhere/ubd/stage1_generate", "bare"],
)
def test_a_ref_that_leaves_the_library_does_not_resolve(root: Path, ref: str) -> None:
    """A ref names a file inside the library or it names nothing.

    Refs come from preset modules rather than from users, so this is not a
    privilege boundary. It is here because the round trip that catches
    traversal is the same one that makes a ref and its path agree, and losing
    it to a "simplification" would cost both.
    """
    (root.parent / "secrets.md").write_text("---\nprompt_ref: x\n---\n\nBody.\n")
    library = DirectoryPromptLibrary.load(root)
    with pytest.raises(PromptError):
        library.resolve(ref, kind="generator")


def test_a_versioned_pin_does_not_resolve(root: Path) -> None:
    """`ref@3` is not a ref. §2.4 rejects per-prompt pins; this keeps it true.

    Left unchecked, a pin would fail as an ordinary missing prompt and read as
    "somebody forgot to write it" rather than "somebody invented a pinning
    scheme the loader does not implement".
    """
    write_prompt(root, "prompts/ubd/stage1_generate")
    library = DirectoryPromptLibrary.load(root)
    with pytest.raises(PromptError, match="version pin"):
        library.resolve("prompts/ubd/stage1_generate@1", kind="generator")


# --- §2.4: what happens when a prompt changes mid-run ------------------------


def test_an_edited_prompt_lands_on_the_next_resolution(root: Path) -> None:
    """A stage in flight picks up the new text, exactly as a preset edit does.

    This is the whole of §2.4's mid-run answer, and the reason the library
    re-reads rather than serving the mapping it validated at load: the run in
    front of you is how you discovered the prompt was wrong, and a prompt
    frozen for the duration of a stage would not apply to it.
    """
    write_prompt(root, "prompts/ubd/stage1_generate", body="First wording.")
    library = DirectoryPromptLibrary.load(root)
    assert "First wording." in library.resolve("prompts/ubd/stage1_generate", kind="generator")

    write_prompt(root, "prompts/ubd/stage1_generate", body="Corrected wording.")
    reread = library.resolve("prompts/ubd/stage1_generate", kind="generator")
    assert "Corrected wording." in reread


def test_a_prompt_deleted_after_load_raises_rather_than_serving_stale_text(root: Path) -> None:
    """Re-reading has to fail the same way a cold start would.

    The cost of re-reading is that a prompt can vanish under a live run. Held
    text would paper over it and the run would look fine until the next
    restart, which is the strand-later failure §2.4 is trying to avoid.
    """
    path = write_prompt(root, "prompts/ubd/stage1_generate")
    library = DirectoryPromptLibrary.load(root)
    path.unlink()
    with pytest.raises(PromptError, match="prompts/ubd/stage1_generate"):
        library.resolve("prompts/ubd/stage1_generate", kind="generator")


def test_the_digest_is_over_the_resolved_text(root: Path) -> None:
    """`prompt_digest` is what makes the preset's version honest, per §2.4.

    A digest over the whole file would move when `summary` was reworded; a
    digest over the resolved text moves when, and only when, what the model
    read changed.
    """
    write_prompt(root, "prompts/ubd/stage1_generate", body="Wording.")
    library = DirectoryPromptLibrary.load(root)
    before = prompt_digest(library.resolve("prompts/ubd/stage1_generate", kind="generator"))

    write_prompt(root, "prompts/ubd/stage1_generate", body="Wording.", version=9)
    unchanged = prompt_digest(library.resolve("prompts/ubd/stage1_generate", kind="generator"))
    assert unchanged == before

    write_prompt(root, "prompts/ubd/stage1_generate", body="Different wording.")
    after = prompt_digest(library.resolve("prompts/ubd/stage1_generate", kind="generator"))
    assert after != before


# --- preset-level validation ------------------------------------------------


def test_unresolved_names_the_ref_the_stage_and_the_field(root: Path) -> None:
    """What the composition root would print when it refuses to build.

    "A prompt is missing" is not actionable across 38 refs; the stage and the
    field are what turn it into an edit.
    """
    problems = unresolved(ubd_pure, DirectoryPromptLibrary.load(root))
    assert problems
    joined = "\n".join(problems)
    assert "ubd.stage1.desired_results" in joined
    assert "prompts/ubd/stage1_generate" in joined
    assert "generator" in joined


def test_unresolved_is_empty_when_every_ref_has_a_file_of_the_right_kind(root: Path) -> None:
    for stage_id, field, ref in referenced_prompts(ubd_pure):
        write_prompt(root, ref, kind=field, intended_for=(f"{ubd_pure.id}/{stage_id}",))
    assert unresolved(ubd_pure, DirectoryPromptLibrary.load(root)) == []


def test_unresolved_reports_a_kind_mismatch_as_well_as_an_absence(root: Path) -> None:
    for stage_id, field, ref in referenced_prompts(ubd_pure):
        wrong = "critic" if field == "generator" else "generator"
        write_prompt(root, ref, kind=wrong, intended_for=(f"{ubd_pure.id}/{stage_id}",))
    problems = unresolved(ubd_pure, DirectoryPromptLibrary.load(root))
    assert len(problems) == len(referenced_prompts(ubd_pure))
    assert all("kind" in problem for problem in problems)


def test_a_field_stage_references_no_prompt(root: Path) -> None:
    """A `FieldStage` has neither a generator nor a critic and must resolve nothing.

    Its evidence comes from people outside the pipeline, so an agent cannot
    execute it at all -- and a loader that demanded a prompt for one would make
    that unrepresentable.
    """
    field_stages = [
        (preset, stage)
        for preset in PRESETS.values()
        for stage in preset.stages
        if getattr(stage, "generator", None) is None and getattr(stage, "critic", None) is None
    ]
    assert field_stages, "no field stage in the shipped presets; this test proves nothing"
    library = DirectoryPromptLibrary.load(root)
    for preset, stage in field_stages:
        assert stage.id not in {stage_id for stage_id, _, _ in referenced_prompts(preset)}
        # An empty library: a stage that resolved anything would raise here.
        assert stage_prompt(stage, library) == ""


def test_a_screen_stage_resolves_its_critic_because_it_has_no_generator(root: Path) -> None:
    screens = [
        (preset, stage)
        for preset in PRESETS.values()
        for stage in preset.stages
        if getattr(stage, "generator", None) is None
        and getattr(stage, "critic", None) is not None
    ]
    assert screens, "no screen stage in the shipped presets; this test proves nothing"
    _, stage = screens[0]
    write_prompt(root, stage.critic.prompt_ref, kind="critic", body="Screen against the doc.")
    library = DirectoryPromptLibrary.load(root)
    assert "Screen against the doc." in stage_prompt(stage, library)


def test_orphaned_refs_finds_a_file_no_preset_names(root: Path) -> None:
    """An unreferenced prompt is a stage that was renamed, and it looks like nothing."""
    write_prompt(root, "prompts/ubd/stage1_generate")
    write_prompt(root, "prompts/ubd/abandoned")
    assert orphaned_refs(PRESETS.values(), DirectoryPromptLibrary.load(root)) == (
        "prompts/ubd/abandoned",
    )


def test_intended_for_disagrees_in_both_directions(root: Path) -> None:
    """The redundant declaration whose only job is to disagree.

    Both directions matter and they catch different mistakes: a claim nothing
    references is a prompt written against a renamed stage, and a reference
    nothing claims is a prompt quietly reused by a stage it was not written
    for -- which is the expensive one, because a UbD prompt bound to an ADDIE
    stage produces a well-formed artifact of the wrong methodology.
    """
    write_prompt(
        root,
        "prompts/ubd/stage1_generate",
        intended_for=("ubd.pure/ubd.stage1.desired_results", "addie.pure/invented.stage"),
    )
    write_prompt(root, "prompts/ubd/stage1_critique", kind="critic")
    problems = intended_for_disagreements(PRESETS.values(), DirectoryPromptLibrary.load(root))
    assert any("claims addie.pure/invented.stage" in problem for problem in problems)
    assert any(
        "prompts/ubd/stage1_critique is referenced by" in problem for problem in problems
    )


def test_intended_for_agreeing_reports_nothing(root: Path) -> None:
    for stage_id, field, ref in referenced_prompts(ubd_pure):
        write_prompt(root, ref, kind=field, intended_for=(f"{ubd_pure.id}/{stage_id}",))
    assert intended_for_disagreements([ubd_pure], DirectoryPromptLibrary.load(root)) == ()


def test_role_line_carries_the_three_fields_nothing_else_reads(root: Path) -> None:
    """`role`, `taxonomy_binding` and `over_generate_factor` are inert until here.

    `taxonomy_binding` is the one that matters: Bloom's and the Six Facets are
    named-never-unioned because they are incompatible, and a stage that does
    not say which it is under gets whichever the model prefers.
    """
    line = role_line(
        Generator(
            role="assessor",
            prompt_ref="prompts/ubd/stage2_generate",
            taxonomy_binding="blooms_revised",
            over_generate_factor=5,
        )
    )
    assert "assessor" in line
    assert "blooms_revised" in line
    assert "5" in line


def test_role_line_omits_what_the_generator_did_not_declare() -> None:
    line = role_line(Generator(role="domain mapper", prompt_ref="prompts/ubd/intake"))
    assert "domain mapper" in line
    assert "taxonomy" not in line.lower()


# --- about the shipped presets, not about the loader ------------------------


def test_a_prompt_shared_across_differing_stage_ids_is_allowlisted() -> None:
    """§4.5: share a prompt when two presets reference the same stage id.

    The rule is mechanical and it reproduces the shipped data exactly. What it
    guards is §4.4: four stages produce `Intent` under four prompts and look
    like one stage, and collapsing them would make each methodology emit
    another's output while every structural check still passed -- because the
    checks are graph queries and the collapse does not change the graph.
    """
    assert shared_ref_problems(PRESETS.values()) == ()


def test_the_allowlist_is_exactly_the_deliberate_rename() -> None:
    """`addie.a1.intake_gap_framing` and `hybrid.step1.framing` are one stage renamed.

    Pinned by value rather than by count so that adding an entry is a visible
    edit to this test. §4.3 is the standing hazard: the two stages emit
    different artifact sets, so the shared prompt must teach the method and
    never name a deliverable.
    """
    assert set(ALLOWED_CROSS_STAGE_REFS) == {
        "prompts/addie/gap_framing",
        "prompts/addie/gap_critique",
    }


def test_removing_the_allowlist_would_make_the_shared_ref_rule_fire() -> None:
    """Proves the rule above is not vacuous.

    Without this, `test_a_prompt_shared_across_differing_stage_ids_is_allowlisted`
    passes just as well against an implementation that returns `()` always.
    """
    assert shared_ref_problems(PRESETS.values(), allowlist=frozenset()) != ()


def test_no_generator_and_critic_in_one_stage_share_a_ref() -> None:
    """What `checks.py:1110` forbids at invariant severity, asserted engine-wide.

    The check is bound at exactly one stage across all three presets
    (`hybrid.default/tyler.step2.philosophy_screen`), which is BACKLOG B22's
    complaint. It becomes urgent once prompts exist, because a critic reviewing
    under the generator's prompt produces a course that claims a review and
    evidences agreement with itself.
    """
    for preset in PRESETS.values():
        for stage in preset.stages:
            generator = getattr(stage, "generator", None)
            critic = getattr(stage, "critic", None)
            if generator is None or critic is None:
                continue
            assert generator.prompt_ref != critic.prompt_ref, (
                f"{preset.id}/{stage.id} has one prompt for both roles"
            )
