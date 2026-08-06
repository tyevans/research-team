"""Where a stage writes what it produced, and what the file has to say for itself.

Stage outputs are markdown files in the event-sourced filesystem, which is the
whole reason this module is as small as it is: audit, history, scrubbing and
diffing already exist for files, and the viewer already renders markdown and
tables. Anything invented here would be a second mechanism for a job the
aggregate already does.

Two conventions carry all of it.

**`/course/NN-<artifact>.md`, where `NN` is the stage's position in the
preset.** The file list is sorted alphabetically, so the prefix is the entire
difference between a directory a person can read top to bottom and a pile in
which `context-profile` sorts before `source-claim` for no reason anybody
cares about. The number is the stage *index*, deliberately not the spine
position: two stages routinely share a spine position -- the hybrid has two at
position 1 -- and numbering by spine would collapse them onto one prefix and
lose the ordering the prefix exists to provide.

**Frontmatter that names its own provenance.** `artifact_type`, `stage`,
`preset` and `preset_version` are what a later reader needs to know what they
are holding and which revision of the workflow produced it. `provenance` is the
one that matters: a list of `{source_id, start, end}` entries, or an entry of
`{inferred_not_in_source: true}`. Both are legitimate and the flag is not
optional, because the alternative is that an unsourced claim and a sourced one
are indistinguishable on the page -- which is precisely the failure the corpus
layer was built to prevent. An empty list is the one shape that is never right.

Document-level provenance is an index, not a substitute for the inline
`source_id@start-end` citations `CORPUS_PROMPT` asks for. It answers "what did
this draw on", which is a question a check can ask cheaply over a whole course;
the inline offsets answer "where did *this sentence* come from", which is the
question a reviewer asks about one claim.

**This module parses and derives. It does not judge.** `parse_frontmatter`
reports what a file contains and returns `None` where a validator would raise.
Whether a missing block, an empty `provenance` or an unknown `artifact_type` is
acceptable is a check, and checks are a library Phase 3 builds with severities,
findings and preset bindings behind them. A validator here would be a second,
weaker copy of that with no way to report anything.
"""

import re
from typing import Any

import yaml

from research_team.domain.workflow import Preset, StageBase, StageOutput

COURSE_DIR = "/course"
"""Everything a workflow produces, in one directory.

Separate from the rest of the filesystem so that "what did this run make" is a
listing rather than a search, and so a session that also wrote scratch files
does not interleave them with the course.
"""

FRONTMATTER_FENCE = "---"

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """`SourceClaim` and `source claim` and `source_claim` all become one name.

    Artifact types are CamelCase and subtypes are free text written by whoever
    edited the preset, so both shapes reach this and both have to land on a
    filename that is stable across those spellings.
    """
    spaced = _CAMEL_BOUNDARY.sub("-", text)
    return _NON_SLUG.sub("-", spaced.lower()).strip("-")


def stage_number(preset: Preset, stage: StageBase) -> int:
    """This stage's position in the preset, which is what `NN` encodes.

    Matched by id rather than by identity so a caller holding a stage read back
    out of a preset -- or a copy of one -- gets the same answer.
    """
    for index, candidate in enumerate(preset.stages):
        if candidate.id == stage.id:
            return index
    raise KeyError(f"preset {preset.id} has no stage {stage.id}")


def artifact_path(preset: Preset, stage: StageBase, output: StageOutput) -> str:
    """The one path this stage writes that output to.

    The subtype is part of the name because a type can legitimately appear
    twice in a preset at different fidelities -- the hybrid produces an
    `EvaluationPlan` skeleton at framing and a full one much later -- and
    without it the second would overwrite the first, silently, at the point in
    a long run where nobody is watching closely.
    """
    name = slugify(output.artifact_type.value)
    if output.subtype:
        name = f"{name}-{slugify(output.subtype)}"
    return f"{COURSE_DIR}/{stage_number(preset, stage):02d}-{name}.md"


def stage_artifact_paths(preset: Preset, stage: StageBase) -> tuple[str, ...]:
    """Every file this stage is expected to leave behind, in declaration order.

    One file per declared output rather than one per artifact *instance*: a
    stage producing `1..n` source claims writes them into the one file its
    declaration names. That keeps the set of files a stage owes derivable from
    the preset alone, which is what makes a missing artifact a detectable gap
    rather than something nobody can tell was supposed to exist.
    """
    return tuple(artifact_path(preset, stage, output) for output in stage.outputs)


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """The leading YAML block as a mapping, and the body after it.

    `None` for a file with no block, an unparseable one, or one whose YAML is
    valid but is not a mapping -- a bare list parses cleanly and is still not
    frontmatter. All three are things a check reports on, and none is a reason
    to raise here: a run that produced one malformed artifact should still hand
    back the other twenty.

    The body is returned unchanged in the `None` cases, so a caller that only
    wanted the prose does not have to know whether the parse succeeded.
    """
    if not text.startswith(FRONTMATTER_FENCE):
        return None, text
    parts = text.split(f"\n{FRONTMATTER_FENCE}", 2)
    if len(parts) < 2:
        return None, text
    block = parts[0][len(FRONTMATTER_FENCE) :]
    body = parts[1].lstrip("-").lstrip("\n")
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError:
        return None, text
    if not isinstance(loaded, dict):
        return None, text
    return loaded, body


_RULES = (
    "Write what a stage produces as a file, not as a reply. The reply is gone "
    "when the turn ends; the file is the artifact, and everything downstream "
    "-- the next stage, the checks, the person reviewing -- reads the file.\n\n"
    "Every one of them opens with a frontmatter block fenced by `---`, "
    "carrying `artifact_type`, `stage`, `preset`, `preset_version`, and "
    "`provenance`. `provenance` is a list, and each entry is either a source "
    "you drew on -- `source_id`, `start`, `end`, exactly the offsets "
    "`read_source` reported back to you -- or `inferred_not_in_source: true` "
    "for the reasoning that came from you rather than from the corpus.\n\n"
    "Mark the inference. An artifact whose thinking is yours and says so is "
    "honest work that a reviewer can weigh; the same artifact with an empty "
    "`provenance` is indistinguishable from one that was never checked against "
    "anything. That is the difference the flag exists to preserve, and it is "
    "the one thing here worth being pedantic about."
)


def stage_artifact_instructions(preset: Preset, stage: StageBase) -> str:
    """The block appended to the system prompt telling this stage where to write.

    Derived from the stage's own declaration rather than written out in the
    preset, so the paths in the prompt and the paths anything else computes
    cannot disagree -- and so adding an output to a stage updates its
    instructions with it, instead of leaving the two to drift until a run
    produces a file nothing goes looking for.

    A stage with no declared outputs gets an explicit "writes nothing" rather
    than an empty block. Silence reads as a missing instruction, and a model
    reading a stage that lists no files is likelier to invent one to write than
    to conclude there is nothing to write -- which is exactly what a field
    stage, whose evidence comes from people outside the pipeline, must not do.
    """
    if not stage.outputs:
        return (
            "This stage produces no artifact of its own. Do not write course "
            "files from it; its result is recorded elsewhere."
        )
    lines = [
        f"This stage writes {len(stage.outputs)} artifact"
        f"{'' if len(stage.outputs) == 1 else 's'}:"
    ]
    lines += [
        f"- `{artifact_path(preset, stage, output)}` — {output.artifact_type.value}"
        + (f" ({output.subtype})" if output.subtype else "")
        + f", {output.cardinality}"
        for output in stage.outputs
    ]
    lines.append(_RULES)
    lines.append(
        f"Use `stage: {stage.id}`, `preset: {preset.id}` and "
        f"`preset_version: '{preset.version}'` in the frontmatter of each."
    )
    return "\n".join(lines)
