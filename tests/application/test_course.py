"""A run seen whole, and the distinctions the view is not allowed to flatten.

The tests that matter most here are the ones about absence. A missing artifact,
an artifact with no provenance, an artifact claiming inference, and an artifact
whose provenance is corrupt all look like "nothing to show" to a naive view,
and they are four different situations with four different responses. Most of
what follows exists to keep them four.
"""

from typing import Any
from uuid import uuid4

import pytest

from research_team.application.artifacts import artifact_path, stage_artifact_paths
from research_team.application.course import course_progress
from research_team.application.stage_exit import findings_path
from research_team.domain.project import ProjectState
from research_team.workflows import PRESETS, hybrid_default

ALL_PRESETS = pytest.mark.parametrize(
    "preset", list(PRESETS.values()), ids=list(PRESETS.keys())
)


def file(content: str) -> dict[str, Any]:
    return {"content": content}


def artifact_file(provenance: Any = "unset", **frontmatter: Any) -> dict[str, Any]:
    """A course file with the frontmatter the instructions ask for.

    `provenance` defaults to a single well-formed source rather than to nothing,
    so a test that is not about provenance does not accidentally assert on the
    empty case, which is the one shape the module treats specially.
    """
    front: dict[str, Any] = {
        "artifact_type": "Intent",
        "stage": "s",
        "preset": "p",
        "preset_version": "1",
        **frontmatter,
    }
    if provenance != "unset":
        front["provenance"] = provenance
    else:
        front["provenance"] = [{"source_id": "doc-1", "start": 0, "end": 40}]

    import yaml

    return file(f"---\n{yaml.safe_dump(front)}---\n\nthe artifact body\n")


def state(preset, stage_id: str | None = None) -> ProjectState:
    return ProjectState(
        project_id=uuid4(),
        status="created",
        name="a project",
        preset_id=preset.id,
        preset_version=preset.version,
        current_stage=stage_id,
    )


@ALL_PRESETS
def test_the_rail_lists_every_stage_of_the_preset(preset):
    """Not just the ones that have run. The plan is the thing being shown."""
    course = course_progress(preset, state(preset), {})

    assert len(course.stages) == len(preset.stages)
    assert [s.id for s in course.stages] == [s.id for s in preset.stages]
    assert course.stage_count == len(preset.stages)


@ALL_PRESETS
def test_a_fresh_project_stands_in_the_first_stage(preset):
    """`current_stage` is None until something advances, and that means stage one."""
    course = course_progress(preset, state(preset), {})

    assert course.position == 1
    assert course.stages[0].status == "current"
    assert {s.status for s in course.stages[1:]} <= {"upcoming"}


def test_status_is_positional_not_a_claim_about_completeness():
    """A stage advanced past with nothing written is still `done`.

    Its emptiness is visible in its slots. Letting status mean "finished
    properly" would hide exactly the run a reviewer needs to catch.
    """
    preset = hybrid_default
    third = preset.stages[2].id
    course = course_progress(preset, state(preset, third), {})

    assert course.position == 3
    assert [s.status for s in course.stages[:2]] == ["done", "done"]
    assert course.stages[2].status == "current"
    assert course.stages[3].status == "upcoming"

    left_behind = course.stages[0]
    assert all(slot.present is False for slot in left_behind.outputs)


def test_a_declared_artifact_that_was_never_written_is_a_named_gap():
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)

    course = course_progress(preset, state(preset), {})
    slots = next(s for s in course.stages if s.id == stage.id).outputs

    assert [slot.path for slot in slots] == list(stage_artifact_paths(preset, stage))
    assert all(not slot.present for slot in slots)
    assert all(slot.frontmatter is None and slot.provenance is None for slot in slots)


def test_a_written_artifact_reports_its_frontmatter_and_sources():
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    course = course_progress(preset, state(preset), {path: artifact_file()})
    slot = next(s for s in course.stages if s.id == stage.id).outputs[0]

    assert slot.present is True
    assert slot.frontmatter is not None
    assert slot.missing_fields == ()
    assert slot.provenance is not None
    assert [src.source_id for src in slot.provenance.sources] == ["doc-1"]
    assert slot.provenance.sources[0].start == 0
    assert slot.provenance.sources[0].end == 40
    assert slot.provenance.inferred is False
    assert slot.provenance.is_empty is False
    assert slot.body_chars > 0


def test_claimed_inference_and_claimed_nothing_are_different_answers():
    """The distinction the provenance contract exists to preserve."""
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    def provenance_of(value):
        course = course_progress(
            preset, state(preset), {path: artifact_file(provenance=value)}
        )
        return next(s for s in course.stages if s.id == stage.id).outputs[0].provenance

    inferred = provenance_of([{"inferred_not_in_source": True}])
    assert inferred.inferred is True
    assert inferred.is_empty is False

    nothing = provenance_of([])
    assert nothing.inferred is False
    assert nothing.sources == ()
    assert nothing.is_empty is True


def test_corrupt_provenance_entries_are_counted_not_dropped():
    """Three good entries and two broken ones must not look like three."""
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    course = course_progress(
        preset,
        state(preset),
        {
            path: artifact_file(
                provenance=[
                    {"source_id": "doc-1", "start": 0, "end": 10},
                    {"nonsense": True},
                    "a bare string",
                ]
            )
        },
    )
    provenance = next(s for s in course.stages if s.id == stage.id).outputs[0].provenance

    assert [src.source_id for src in provenance.sources] == ["doc-1"]
    assert provenance.unreadable == 2
    assert provenance.is_empty is False


def test_provenance_that_is_not_a_list_is_unreadable_rather_than_absent():
    """`provenance: "the paper"` tried to make a claim. Say so."""
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    course = course_progress(
        preset, state(preset), {path: artifact_file(provenance="the paper")}
    )
    provenance = next(s for s in course.stages if s.id == stage.id).outputs[0].provenance

    assert provenance.unreadable == 1
    assert provenance.sources == ()


def test_a_present_file_with_no_frontmatter_is_present_with_none():
    """Present-but-unparseable and missing must not collapse into one state."""
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    course = course_progress(preset, state(preset), {path: file("just prose\n")})
    slot = next(s for s in course.stages if s.id == stage.id).outputs[0]

    assert slot.present is True
    assert slot.frontmatter is None
    assert slot.provenance is None
    assert slot.body_chars == len("just prose\n")


def test_missing_frontmatter_fields_are_named():
    preset = hybrid_default
    stage = next(s for s in preset.stages if s.outputs)
    path = artifact_path(preset, stage, stage.outputs[0])

    content = "---\nartifact_type: Intent\n---\n\nbody\n"
    course = course_progress(preset, state(preset), {path: file(content)})
    slot = next(s for s in course.stages if s.id == stage.id).outputs[0]

    assert set(slot.missing_fields) == {"stage", "preset", "preset_version", "provenance"}


def test_a_stage_whose_report_exists_links_to_it():
    preset = hybrid_default
    stage = preset.stages[0]
    path = findings_path(preset, stage)

    course = course_progress(preset, state(preset), {path: file("---\n---\n\nreport")})

    assert course.stages[0].findings_report == path
    assert course.stages[1].findings_report is None


def test_a_stage_the_preset_does_not_contain_leaves_the_rail_standing():
    """The disagreement `advance_stage` refuses to work around, seen rather than hidden."""
    preset = hybrid_default
    course = course_progress(preset, state(preset, "not-a-stage-of-this-preset"), {})

    assert course.position is None
    assert len(course.stages) == len(preset.stages)
    assert {s.status for s in course.stages} == {"unknown"}
    assert course.live_findings == ()


def test_artifacts_reads_the_course_in_stage_order():
    """Stage order, which the `NN-` prefix tracks -- but not filename order.

    Two outputs of one stage share a prefix and keep their declaration order,
    which is the order the stage's own instructions list them in. Sorting the
    whole list alphabetically would reorder those pairs against the preset for
    no reason a reader of the course would recognise.
    """
    preset = hybrid_default
    course = course_progress(preset, state(preset), {})

    ordered = [slot.path for slot in course.artifacts]
    assert len(ordered) == sum(len(stage.outputs) for stage in preset.stages)

    prefixes = [path.split("/")[-1][:2] for path in ordered]
    assert prefixes == sorted(prefixes)

    expected = [
        path for stage in preset.stages for path in stage_artifact_paths(preset, stage)
    ]
    assert ordered == expected


@ALL_PRESETS
def test_the_live_review_belongs_to_the_current_stage_only(preset):
    """Findings are computed for where the run stands, never re-derived for its past.

    A stage that has been left has its report on disk, recorded against the
    course as it was at the time; recomputing it now would show a different
    table and present it as the one the gate saw.
    """
    course = course_progress(preset, state(preset), {})

    # Whatever the first stage's checks find, nothing raises and the shape is
    # right -- an empty tuple is a legitimate answer and is not asserted away.
    assert isinstance(course.live_findings, tuple)
    assert isinstance(course.unimplemented_checks, tuple)
