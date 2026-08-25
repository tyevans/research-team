"""Where a stage's artifacts land, and what a reader can tell from the file.

Two properties carry most of the weight here. Lexical order matching stage
order is the whole reason the numeric prefix exists -- the file list is sorted
alphabetically and nothing else makes it readable -- and it is a property of a
whole preset rather than of one path, so it is asserted over every shipped
preset rather than over an example. And a path has to be derivable twice: once
into the prompt that tells the model where to write, and once by anything later
that goes looking. A test that only checked one of those would let them drift.
"""

import re

import pytest

from research_team.application.artifacts import (
    COURSE_DIR,
    artifact_path,
    parse_frontmatter,
    stage_artifact_instructions,
    stage_artifact_paths,
)
from research_team.domain.workflow import (
    ArtifactType,
    GenerateStage,
    Generator,
    StageOutput,
)
from research_team.workflows import PRESETS, hybrid_default

ALL_PRESETS = pytest.mark.parametrize(
    "preset", list(PRESETS.values()), ids=list(PRESETS.keys())
)

FRAMING = "hybrid.step1.framing"


def _stage(preset, stage_id: str):
    return next(stage for stage in preset.stages if stage.id == stage_id)


def test_a_path_is_the_course_directory_a_number_and_a_slug():
    output = StageOutput(artifact_type=ArtifactType.CONTEXT_PROFILE, cardinality="1")
    path = artifact_path(hybrid_default, _stage(hybrid_default, FRAMING), output)
    assert path == f"{COURSE_DIR}/01-context-profile.md"


def test_the_number_is_the_stages_position_not_its_spine_position():
    """Two stages can share a spine position; two cannot share an index.

    Numbering by spine would collapse them onto one prefix and lose the
    ordering the prefix exists to provide.
    """
    framing = _stage(hybrid_default, FRAMING)
    sources = _stage(hybrid_default, "tyler.step1a.source_analysis")
    assert framing.spine == 1
    assert sources.spine == 1
    prefixes = {
        stage_artifact_paths(hybrid_default, stage)[0].split("/")[-1][:2]
        for stage in (framing, sources)
    }
    assert len(prefixes) == 2


def test_a_subtype_is_part_of_the_name():
    """`EvaluationPlan` appears twice in the hybrid, at different fidelities.

    Without the subtype the second one would overwrite the first, silently and
    at the point where a run is least likely to be watched closely.
    """
    output = StageOutput(
        artifact_type=ArtifactType.EVALUATION_PLAN, subtype="skeleton", cardinality="1"
    )
    path = artifact_path(hybrid_default, _stage(hybrid_default, FRAMING), output)
    assert path == f"{COURSE_DIR}/01-evaluation-plan-skeleton.md"


@ALL_PRESETS
def test_lexical_order_matches_stage_order(preset):
    """The finding this convention exists to exploit, asserted per preset."""
    paths = [path for stage in preset.stages for path in stage_artifact_paths(preset, stage)]

    def prefix(path: str) -> int:
        return int(path.split("/")[-1][:2])

    # Within a stage the outputs keep their declaration order, which is not
    # alphabetical and is not meant to be. The claim is about stages: sorting
    # the whole directory never moves a file across a stage boundary.
    assert [prefix(path) for path in sorted(paths)] == sorted(prefix(path) for path in paths)


@ALL_PRESETS
def test_every_path_in_a_preset_is_unique(preset):
    """Two artifacts sharing a path is one artifact, and nobody would notice."""
    paths = [path for stage in preset.stages for path in stage_artifact_paths(preset, stage)]
    assert len(paths) == len(set(paths))


@ALL_PRESETS
def test_a_stage_has_one_path_per_declared_output(preset):
    for stage in preset.stages:
        assert len(stage_artifact_paths(preset, stage)) == len(stage.outputs)


@ALL_PRESETS
def test_every_path_is_a_markdown_file_under_the_course_directory(preset):
    for stage in preset.stages:
        for path in stage_artifact_paths(preset, stage):
            assert re.fullmatch(rf"{COURSE_DIR}/\d\d-[a-z0-9-]+\.md", path), path


def test_frontmatter_parses_into_a_mapping_and_the_body_that_followed():
    text = (
        "---\n"
        "artifact_type: ContextProfile\n"
        "stage: hybrid.step1.framing\n"
        "preset: hybrid.default\n"
        "preset_version: '1'\n"
        "provenance:\n"
        "  - source_id: doc-1\n"
        "    start: 0\n"
        "    end: 40\n"
        "---\n"
        "\n# Context\n\nThe body.\n"
    )
    front, body = parse_frontmatter(text)
    assert front["artifact_type"] == "ContextProfile"
    assert front["provenance"] == [{"source_id": "doc-1", "start": 0, "end": 40}]
    assert body.strip().startswith("# Context")


def test_an_inference_flag_parses_as_a_provenance_entry():
    """Both shapes are legitimate; only an empty list is not."""
    text = "---\nprovenance:\n  - inferred_not_in_source: true\n---\nbody\n"
    front, _ = parse_frontmatter(text)
    assert front["provenance"] == [{"inferred_not_in_source": True}]


def test_a_file_with_no_frontmatter_parses_as_none_rather_than_raising():
    """A missing block is a finding for a check to report, not a crash here.

    Parsing is separated from judging deliberately: this module says what a
    file contains, and Phase 3's check library says whether that is acceptable.
    """
    front, body = parse_frontmatter("# Just a heading\n")
    assert front is None
    assert body == "# Just a heading\n"


def test_unparseable_frontmatter_is_none_rather_than_an_exception():
    front, body = parse_frontmatter("---\nartifact_type: [unclosed\n---\nbody\n")
    assert front is None
    # The block is still excluded even though it never parsed: a delimited
    # block is identified structurally (does the text open with `---` and
    # close it on its own line) before its contents are validated as YAML, so
    # a caller after the prose does not get the block back just because this
    # one failed to load.
    assert body == "body\n"


def test_frontmatter_that_is_not_a_mapping_is_none():
    """A YAML list parses fine and is still not frontmatter."""
    front, body = parse_frontmatter("---\n- one\n- two\n---\nbody\n")
    assert front is None
    assert body == "body\n"


def test_a_value_containing_a_colon_still_gets_its_block_stripped():
    """`builds_toward` names an assessment and states what it covers, and that
    is prose a model routinely punctuates with a colon -- the exact case
    `stage_artifact_instructions` asks for. `yaml.safe_load` reads a second
    `:` on a line as a second mapping key rather than as punctuation inside a
    string and raises `mapping values are not allowed here`, so `front` comes
    back `None` here same as any other malformed block.

    What must not happen is the block landing back in `body`: a course lesson
    on screen with this exact field content (`agent-interaction-log`,
    lesson-03 in a real authored course, quoted verbatim as the fixture,
    per CLAUDE.md's rule against a fixture simpler than what the real producer
    emits) rendered `---` then `title: ... builds_toward: ...` as a markdown
    setext `<h2>` above the real `# ` heading, because the strip built for
    that defect discarded the block only when `parse_frontmatter` returned a
    mapping -- and a block with a colon in a value never does.
    """
    text = (
        "---\n"
        "title: No reader, and a switch that does not delete\n"
        "area: agent-interaction-log\n"
        "builds_toward: Understanding 3 — a log with no reader: "
        "pre-consumer collection; Understanding 4 — disabling the switch "
        "vs. deleting the data\n"
        "---\n\n"
        "# No reader, and a switch that does not delete\n\nThe rest of the lesson.\n"
    )
    front, body = parse_frontmatter(text)
    assert front is None
    expected_body = (
        "# No reader, and a switch that does not delete\n\nThe rest of the lesson.\n"
    )
    assert body == expected_body
    assert "builds_toward" not in body
    assert "---" not in body


def test_the_instructions_name_every_path_the_stage_is_expected_to_write():
    stage = _stage(hybrid_default, FRAMING)
    text = stage_artifact_instructions(hybrid_default, stage)
    for path in stage_artifact_paths(hybrid_default, stage):
        assert path in text


def test_the_instructions_name_the_frontmatter_keys_and_the_inference_flag():
    stage = _stage(hybrid_default, FRAMING)
    text = stage_artifact_instructions(hybrid_default, stage)
    for key in ("artifact_type", "stage", "preset", "provenance"):
        assert key in text
    assert "inferred_not_in_source" in text


def test_a_stage_that_declares_no_outputs_says_so_rather_than_going_silent():
    """Silence would read as a missing instruction rather than as no work.

    A model given a stage block that lists no files is likelier to invent one
    to write than to conclude there is nothing to write -- which is exactly
    what a stage whose evidence comes from outside the pipeline must not do.

    Constructed rather than taken from a shipped preset, because every stage in
    all three declares at least one output today. That makes this branch a
    guard against a future preset edit rather than a description of one, and
    saying so is cheaper than a reader discovering it.
    """
    outputless = GenerateStage(
        id="custom.observe",
        name="Watch and record nothing",
        spine=9,
        scope_level="course",
        generator=Generator(role="observer", prompt_ref="prompts/none"),
    )
    text = stage_artifact_instructions(hybrid_default, outputless)
    assert COURSE_DIR not in text
    assert text
