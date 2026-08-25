"""A run seen whole: every stage of the preset, and every artifact it owes.

The pieces this joins all existed already. `domain/workflow.py` knows what a
preset's stages are and what each declares it produces; `domain/project.py`
knows which stage a project stands in; `application/artifacts.py` knows the
path an output is written to and how to read the frontmatter back. What was
missing was the join -- and without it the only thing any surface could say
about a fifteen-stage run was "4/15", which tells a person their position and
nothing about the road.

**Expected first, present second.** The stage list comes from the preset, so a
stage that has produced nothing still appears, and an artifact that was never
written is a named gap rather than an absence nobody can see. Listing the
`/course` directory instead would invert that: it would show what happened and
leave what was supposed to happen underivable, which is precisely backwards for
a surface whose job is to show a run against its plan.

**This module reports; it does not judge.** It says whether a file is there,
what its frontmatter contains, and what provenance it claims. It does not say
whether an empty `provenance` is acceptable, whether a missing artifact is a
failure, or whether a run is behind. Those are checks, and checks are a library
with severities and preset bindings behind them that Phase 3 builds. A verdict
invented here would be a second, weaker copy of that with nowhere to report to
-- and worse, it would be the copy the UI actually used.

The one place that distinction gets subtle is `ProvenanceSummary.inferred`. It
is a fact about what the file claims, not an assessment of whether claiming it
was right. A stage whose thinking is genuinely the model's own and says so is
working as designed; the flag is carried so a reviewer can weigh it, not so
anything here can dock points for it.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from research_team.application.artifacts import (
    artifact_path,
    parse_frontmatter,
    stage_number,
)
from research_team.application.findings import Finding
from research_team.application.stage_exit import findings_path, review_stage
from research_team.domain.project import ProjectState, current_stage_of
from research_team.domain.workflow import Preset, StageBase

FRONTMATTER_FIELDS = ("artifact_type", "stage", "preset", "preset_version", "provenance")
"""What `stage_artifact_instructions` tells every artifact to carry.

Named here so the "what is missing from this block" answer is derived from the
same tuple the instructions are built from, rather than from a second list that
would go stale the first time the contract changed.
"""


@dataclass(frozen=True)
class SourceSpan:
    """One `{source_id, start, end}` entry, as the file claims it.

    The offsets are not resolved against the corpus. Doing so would need a
    corpus reader, would turn a listing into N document reads, and would answer
    a question -- does this span still say what it said -- that belongs to a
    check rather than to a view. The UI links to the existing source endpoint
    with these offsets and lets the reader see for themselves.
    """

    source_id: str
    start: int | None
    end: int | None


@dataclass(frozen=True)
class ProvenanceSummary:
    """What an artifact says it rests on.

    `unreadable` counts entries that are neither a source span nor the
    inference flag. They are kept as a count rather than dropped because an
    artifact with three good entries and two malformed ones is a different
    thing from one with three, and silently showing the same number for both
    would hide exactly the corruption a reader would want to know about.
    """

    sources: tuple[SourceSpan, ...] = ()
    inferred: bool = False
    unreadable: int = 0

    @property
    def is_empty(self) -> bool:
        """No claim of any kind -- neither a source nor an admission of inference.

        The one shape `artifacts.py` calls never right, reported as a fact
        about the file so a surface can show it plainly. What follows from it
        is a check's business.
        """
        return not self.sources and not self.inferred and not self.unreadable


@dataclass(frozen=True)
class ArtifactSlot:
    """One file a stage declared it would write, present or not.

    A slot exists because the preset declares the output, which is what makes
    `present=False` meaningful. `frontmatter` is `None` both for a file that
    is missing and for one whose block would not parse; `present` is what
    separates those two, and both are worth showing differently.
    """

    path: str
    artifact_type: str
    cardinality: str
    stage_id: str
    subtype: str | None = None
    present: bool = False
    frontmatter: dict[str, Any] | None = None
    provenance: ProvenanceSummary | None = None
    missing_fields: tuple[str, ...] = ()
    body_chars: int = 0


@dataclass(frozen=True)
class StageProgress:
    """One stage of the preset, placed against where the project actually is.

    `status` is positional, derived from the stage's index against the current
    one, and deliberately carries no notion of completeness: a stage the run
    has moved past is `done` whether or not it wrote what it owed. Its slots
    say what it produced. Conflating the two would let a rail claim a stage
    finished cleanly when it was advanced past with nothing written -- which
    is the case a reviewer most needs to be able to see.
    """

    index: int
    id: str
    name: str
    kind: str
    spine: int
    scope_level: str
    status: str
    outputs: tuple[ArtifactSlot, ...] = ()
    gate_decisions: tuple[str, ...] = ()
    reviewer_role: str | None = None
    findings_report: str | None = None
    """Path of the report `stage_exit` wrote when this stage was left, if it is
    there. A path rather than its contents: the file viewer already renders the
    table, and inlining it here would be a second rendering of the same record
    that could disagree with the one on disk.

    Absent on a stage nobody has left yet, and absent on one left before checks
    existed -- which are different facts that unfortunately look identical from
    here. The status says which."""


@dataclass(frozen=True)
class Course:
    """A whole run: its preset, its position, its stages and their artifacts.

    `position` is `None` when the project's recorded stage is not one the
    preset contains -- the disagreement `workflow_tools` refuses to work
    around. The rail still renders, because the stage list is knowable even
    when the position is not, and a rail that vanished at exactly the moment
    something went wrong would hide the problem it exists to surface.
    """

    preset_id: str
    preset_name: str
    preset_version: str
    position: int | None
    stage_count: int
    stages: tuple[StageProgress, ...] = field(default_factory=tuple)
    live_findings: tuple[Finding, ...] = ()
    """What this stage's own checks say about the course *right now*.

    Computed for the current stage only, and the restriction is the point. A
    stage that has been left has a findings artifact recorded at the moment it
    was left, and that record is what the gate decision was made against;
    recomputing it later against a course that has since grown would produce a
    different table and quietly present it as the one the reviewer saw. The
    live numbers belong to the stage still in progress, where the question is
    "what would stop me advancing" and the only useful answer is the current
    one.

    Empty when there is no resolvable position, when the stage binds no checks,
    or when every check it binds passes -- three different things that a
    surface showing this should not flatten into one silent gap.
    """
    unimplemented_checks: tuple[str, ...] = ()
    """Checks the current stage declares that nothing implements. Surfaced
    because a declared check that never runs is a guarantee the preset claims
    and nothing provides -- worse than declaring none, and invisible without
    this."""

    @property
    def artifacts(self) -> tuple[ArtifactSlot, ...]:
        """Every declared artifact in stage order -- the course, read top to bottom.

        Stage order rather than filename order, though the `NN-` prefix makes
        them agree: the prefix exists to make a directory listing readable by
        somebody who has only the files, and this module has the preset, so it
        can order by the thing the prefix is standing in for.
        """
        return tuple(slot for stage in self.stages for slot in stage.outputs)


def _summarize_provenance(raw: Any) -> ProvenanceSummary | None:
    """A frontmatter `provenance` value as a summary, or `None` if it has none.

    A value that is present but not a list is reported as one unreadable entry
    rather than as absence. `provenance: "the paper"` is a real thing models
    write, and reading it as "no provenance key" would lose the fact that the
    artifact tried to make a claim and made it in a shape nothing can follow.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        return ProvenanceSummary(unreadable=1)

    sources: list[SourceSpan] = []
    inferred = False
    unreadable = 0
    for entry in raw:
        if not isinstance(entry, dict):
            unreadable += 1
            continue
        if entry.get("inferred_not_in_source") is True:
            inferred = True
            continue
        source_id = entry.get("source_id")
        if isinstance(source_id, str) and source_id:
            start = entry.get("start")
            end = entry.get("end")
            sources.append(
                SourceSpan(
                    source_id=source_id,
                    start=start if isinstance(start, int) else None,
                    end=end if isinstance(end, int) else None,
                )
            )
            continue
        unreadable += 1
    return ProvenanceSummary(sources=tuple(sources), inferred=inferred, unreadable=unreadable)


def _slot(
    preset: Preset, stage: StageBase, output: Any, files: dict[str, dict[str, Any]]
) -> ArtifactSlot:
    path = artifact_path(preset, stage, output)
    entry = files.get(path)
    base = ArtifactSlot(
        path=path,
        artifact_type=output.artifact_type.value,
        cardinality=str(output.cardinality),
        stage_id=stage.id,
        subtype=output.subtype,
    )
    if entry is None:
        return base

    content = entry.get("content", "") or ""
    frontmatter, body = parse_frontmatter(content)
    if frontmatter is None:
        # Present but unparseable. `body` still excludes the fenced block --
        # `parse_frontmatter` identifies the block structurally before it
        # tries to parse it, so a malformed block is not counted as prose
        # either. (It used to be: the block failing to parse meant `body` was
        # the whole file including the block, overcounting every check that
        # reads this field as "how much prose is here" by the size of the
        # block. Changed with the frontmatter-on-the-course-page fix; see
        # `parse_frontmatter`'s docstring.)
        return replace(base, present=True, body_chars=len(body))
    missing = tuple(name for name in FRONTMATTER_FIELDS if name not in frontmatter)
    return replace(
        base,
        present=True,
        frontmatter=frontmatter,
        provenance=_summarize_provenance(frontmatter.get("provenance")),
        missing_fields=missing,
        body_chars=len(body),
    )


def _status(index: int, position: int | None) -> str:
    """Where this stage sits relative to the run's position.

    `unknown` when there is no position at all, rather than defaulting every
    stage to `upcoming`: a rail that showed fifteen upcoming stages for a
    project whose stage cannot be resolved would look like a run that has not
    started, which is a different and much less alarming thing than a project
    and its workflow disagreeing.
    """
    if position is None:
        return "unknown"
    if index < position:
        return "done"
    if index == position:
        return "current"
    return "upcoming"


def course_progress(
    preset: Preset, state: ProjectState, files: dict[str, dict[str, Any]]
) -> Course:
    """Join a preset, a project's position and its filesystem into one view.

    `files` is passed in rather than fetched because resolving which stream a
    project's filesystem currently folds from is `SessionService.project_files`'
    job and wants a repository this module has no business holding. Fetching
    here would be a second answer to "which files are this project's", and the
    two would eventually disagree about which session was newer.
    """
    current = current_stage_of(state, preset)
    position = stage_number(preset, current) if current is not None else None

    def _report(stage: StageBase) -> str | None:
        path = findings_path(preset, stage)
        return path if path in files else None

    stages = tuple(
        StageProgress(
            findings_report=_report(stage),
            index=index + 1,
            id=stage.id,
            name=stage.name,
            kind=getattr(stage, "kind", "stage"),
            spine=int(stage.spine),
            scope_level=str(stage.scope_level),
            status=_status(index, position),
            outputs=tuple(_slot(preset, stage, output, files) for output in stage.outputs),
            gate_decisions=tuple(getattr(stage, "gate", None).decisions)
            if getattr(stage, "gate", None) is not None
            else (),
            reviewer_role=str(stage.gate.reviewer_role)
            if getattr(stage, "gate", None) is not None
            else None,
        )
        for index, stage in enumerate(preset.stages)
    )

    review = review_stage(preset, current, files) if current is not None else None

    return Course(
        preset_id=preset.id,
        preset_name=preset.name,
        preset_version=preset.version,
        position=position + 1 if position is not None else None,
        stage_count=len(preset.stages),
        stages=stages,
        live_findings=review.findings if review is not None else (),
        unimplemented_checks=review.unimplemented if review is not None else (),
    )
