"""Running a stage's checks at the moment somebody is asked to let it go.

A check library nothing calls is documentation. This is the call site: when
`advance_stage` is proposed, the stage being left has its declared checks run
over the course directory, the findings are written as an artifact, and the
same findings are attached to the approval so the reviewer reads them *before*
deciding rather than discovering them afterwards.

**Findings inform; they do not block.** A blocking-severity finding is a strong
statement to a human, not a veto over one. The reason is behavioural rather
than architectural: a pipeline that refuses to advance on an advisory finding
teaches people to switch checks off, and a switched-off check reports nothing
at all. The human is the gate. Severity is how loudly a finding argues at it.

**The two invariants are the exception, and they refuse outright.**
`self_review_separation` and `verdict_citation` are the two failures that are
invisible in the output -- a self-screening critic passes nearly everything and
looks like a working filter, and an uncited verdict reads exactly like a cited
one. Handing either to a human as something to weigh converts an invariant back
into advice, and hands them a judgement with nothing to look at. So they are
refused before the human is consulted. That is a real cost: the run stops until
someone fixes the preset or supplies the citation. It is the intended cost --
both are repairs, both are named in the refusal, and neither is a judgement
call the reviewer was equipped to make.

**A check that raises never costs a transition.** It becomes a finding naming
the exception and the run carries on -- including when the check that raised
was an invariant. That is deliberate and it is the one place the invariant rule
bends: an invariant that *failed* is a refusal, an invariant that *crashed* is
our bug, and charging the run for our bug is how a gate acquires a reputation
for being in the way.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_team.application.artifacts import COURSE_DIR, parse_frontmatter, stage_number
from research_team.application.checks import (
    Artifact,
    CheckContext,
    Link,
    MalformedCheck,
    UnknownCheck,
    run_check,
)
from research_team.application.findings import Finding
from research_team.domain.workflow import ArtifactType, Preset, StageBase

__all__ = [
    "FINDINGS_ARTIFACT",
    "StageReview",
    "findings_path",
    "gate_context",
    "load_course",
    "refusal",
    "render_review",
    "review_stage",
]

FINDINGS_ARTIFACT = "check-findings"
"""The findings file's name within the stage's `NN-` prefix.

Not an `ArtifactType`, on purpose: it is a report *about* a stage's output
rather than one of the artifacts the stage owes, and adding it to the canonical
vocabulary would put it in `stage_artifact_paths` and make every stage look
like it owes one more file than the preset declares.
"""


@dataclass(frozen=True)
class StageReview:
    """Everything the harness learned about a stage as it was being left."""

    stage_id: str
    findings: tuple[Finding, ...] = ()
    unimplemented: tuple[str, ...] = ()
    """Bindings naming no registered check. Reported rather than raised: three
    of the shipped ones are deliberately unimplemented and one of them never
    can be, so this is a standing fact about the preset and not an error. It is
    reported at all because a declared check that silently does not run is
    worse than a stage that declared none -- the preset claims a guarantee
    nothing is providing."""
    unreadable: tuple[str, ...] = ()
    """Course files with no frontmatter, or naming an artifact type that does
    not exist. Neither is checkable, and both are invisible if dropped."""
    artifact_count: int = 0
    link_count: int = 0

    @property
    def invariant_failures(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "invariant")

    @property
    def blocked(self) -> bool:
        return bool(self.invariant_failures)


def load_course(
    files: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[Artifact, ...], tuple[Link, ...], tuple[str, ...]]:
    """The course directory as the graph a check reads, plus what would not parse.

    **One artifact per file, not per instance.** A stage writes one file per
    declared output, so an `Intent` file holds every intent the stage produced.
    Splitting the body into instances would need a body schema nothing has
    specified yet, and inventing one here would put the parser and the prompt
    that writes the file in two places with nothing keeping them honest. The
    consequence is real and worth stating: link-shaped checks -- `coverage`,
    `orphan` -- currently reason about files, so they answer "does the intent
    file point at the evidence file" and not "does intent 4 have a task". The
    file-level answer is the weaker one and it is still the one that catches a
    stage that produced evidence for nothing.

    **Links come from a `links:` frontmatter list**, of bare target paths or of
    `{target, kind}` mappings. A field of any other shape is ignored rather
    than raised on: frontmatter is written by a model, and a malformed field
    must not take the gate down with the run behind it.

    The findings artifact is excluded from its own inputs, or every run's
    provenance check would report the previous run's report.
    """
    artifacts: list[Artifact] = []
    links: list[Link] = []
    unreadable: list[str] = []
    for path in sorted(files):
        if not path.startswith(f"{COURSE_DIR}/") or not path.endswith(".md"):
            continue
        if path.endswith(f"-{FINDINGS_ARTIFACT}.md"):
            continue
        front = _frontmatter(str(files[path].get("content", "")))
        if front is None:
            unreadable.append(path)
            continue
        try:
            artifact_type = ArtifactType(str(front.get("artifact_type")))
        except ValueError:
            unreadable.append(path)
            continue
        artifacts.append(
            Artifact(
                id=path,
                artifact_type=artifact_type,
                subtype=_text(front.get("subtype")),
                stage=_text(front.get("stage")),
                fields=front,
                provenance=tuple(
                    entry
                    for entry in _sequence(front.get("provenance"))
                    if isinstance(entry, Mapping)
                ),
            )
        )
        links.extend(_links_from(path, front.get("links")))
    return tuple(artifacts), tuple(links), tuple(unreadable)


def _frontmatter(content: str) -> dict[str, Any] | None:
    """The file's frontmatter, or `None` if it has none we can use.

    A wrapper over `parse_frontmatter` only to drop the body, which nothing
    here reads: an artifact's checkable content is its frontmatter, and the
    prose beneath is for the human.
    """
    front, _ = parse_frontmatter(content)
    return front


def _text(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value.strip() else None


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _links_from(source: str, raw: Any) -> list[Link]:
    links: list[Link] = []
    for entry in _sequence(raw):
        if isinstance(entry, str):
            links.append(Link(source=source, target=entry))
        elif isinstance(entry, Mapping) and isinstance(entry.get("target"), str):
            links.append(
                Link(
                    source=source,
                    target=entry["target"],
                    kind=str(entry.get("kind", "references")),
                )
            )
    return links


def review_stage(
    preset: Preset, stage: StageBase, files: Mapping[str, Mapping[str, Any]]
) -> StageReview:
    """Run everything `stage` declares, over everything the course holds.

    Each binding is run on its own so that one bad binding costs one finding
    rather than the whole review -- `run_checks` would abandon the rest of the
    list at the first raise, and the checks after a typo are the ones nobody
    would know had not run.

    The context carries `preset.stages` and `stage` because the two invariants
    are properties of the workflow graph rather than of its output; without
    them `self_review_separation` has nothing to compare and reports that it
    could not check, which is the same as not being enforced.
    """
    artifacts, links, unreadable = load_course(files)
    context = CheckContext(
        artifacts=artifacts, links=links, preset_stages=preset.stages, stage=stage
    )
    findings: list[Finding] = []
    unimplemented: list[str] = []
    for binding in stage.checks:
        try:
            findings.extend(run_check(binding, context))
        except UnknownCheck:
            unimplemented.append(binding.check)
        except MalformedCheck as error:
            findings.append(
                Finding(
                    check=binding.check,
                    severity="blocking",
                    message=f"{error}",
                    suggested_edit="correct the parameters this check is bound with",
                )
            )
        except Exception as error:  # noqa: BLE001 -- see the module docstring
            findings.append(
                Finding(
                    check=binding.check,
                    severity="blocking",
                    message=(
                        f"{binding.check} raised {type(error).__name__}: {error}. "
                        f"It did not run, so nothing it would have found is known."
                    ),
                    suggested_edit="report this: the check itself is broken",
                )
            )
    return StageReview(
        stage_id=stage.id,
        findings=tuple(findings),
        unimplemented=tuple(unimplemented),
        unreadable=unreadable,
        artifact_count=len(artifacts),
        link_count=len(links),
    )


def refusal(review: StageReview) -> str | None:
    """Why the harness will not put this advance to a human, or `None`.

    Prose rather than a code, because it is read twice: by the model, which has
    to do something about it, and by whoever reads the tool result afterwards.
    Both need to know which invariant and what repairs it.
    """
    failures = review.invariant_failures
    if not failures:
        return None
    lines = [
        f"Stage not advanced: {len(failures)} harness invariant"
        f"{'' if len(failures) == 1 else 's'} failed on {review.stage_id}. "
        f"These are not findings for a reviewer to weigh -- both of them fail "
        f"invisibly, so there is nothing for a human to look at and no "
        f"judgement to make. Fix them and propose the advance again."
    ]
    lines += [
        f"- {finding.check}: {finding.message}"
        + (f" ({finding.suggested_edit})" if finding.suggested_edit else "")
        for finding in failures
    ]
    return "\n".join(lines)


def findings_path(preset: Preset, stage: StageBase) -> str:
    """Where this stage's report is written.

    Numbered with `stage_number` and named like every other course file, so it
    sorts into place beside the artifacts it is about instead of collecting at
    one end of the directory away from them.
    """
    return f"{COURSE_DIR}/{stage_number(preset, stage):02d}-{FINDINGS_ARTIFACT}.md"


def render_review(review: StageReview, preset: Preset) -> str:
    """The report as a markdown file, which is the record the gate decision is not.

    A gate decision is a moment: it is on the log as an approval and says
    nothing about what the machine had found at the time. The artifact is what
    a person reads six weeks later, so it carries the counts and the checks
    that could not run as well as the findings themselves -- an empty findings
    table means something quite different when four of the stage's checks were
    unimplemented.

    A table, because the file viewer already renders one. That was the finding
    that made this need no UI work.
    """
    lines = [
        "---",
        f"artifact_type: {FINDINGS_ARTIFACT}",
        f"stage: {review.stage_id}",
        f"preset: {preset.id}",
        f"preset_version: '{preset.version}'",
        "provenance:",
        "  - inferred_not_in_source: true",
        "---",
        "",
        f"# Checks on leaving {review.stage_id}",
        "",
        f"{review.artifact_count} artifact"
        f"{'' if review.artifact_count == 1 else 's'} and "
        f"{review.link_count} link{'' if review.link_count == 1 else 's'} were read.",
        "",
    ]
    if review.blocked:
        lines += [
            "**The advance was refused.** A harness invariant failed; see the "
            "`invariant` rows below.",
            "",
        ]
    if review.findings:
        lines += [
            "| Check | Severity | Message | Affected | Suggested edit |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [
            "| "
            + " | ".join(
                _cell(part)
                for part in (
                    finding.check,
                    finding.severity,
                    finding.message,
                    ", ".join(finding.cites),
                    finding.suggested_edit or "",
                )
            )
            + " |"
            for finding in review.findings
        ]
    else:
        lines.append("No findings.")
    if review.unimplemented:
        lines += [
            "",
            "## Declared but not implemented",
            "",
            "These checks are bound by the preset and have no implementation, so "
            "the guarantee they name was not tested.",
            "",
        ]
        lines += [f"- {name}" for name in review.unimplemented]
    if review.unreadable:
        lines += [
            "",
            "## Not readable as artifacts",
            "",
            "No frontmatter, or an `artifact_type` that is not one. Nothing in "
            "these files was checked.",
            "",
        ]
        lines += [f"- `{path}`" for path in review.unreadable]
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    """One table cell: pipes escaped, newlines flattened.

    A finding's message is prose a check author wrote, so both are reachable,
    and either one silently shifts every cell after it in the rendered table.
    """
    return " ".join(str(text).split()).replace("|", r"\|")


def gate_context(review: StageReview, artifact_path: str) -> dict[str, Any]:
    """The review as the `context` an `ApprovalRequest` carries.

    Primitives only, because this crosses to a browser as JSON. Findings are
    flattened into mappings rather than sent as dataclasses for the same
    reason, and the artifact path is included so a reviewer who wants the full
    report has somewhere to open rather than only the summary.

    Deliberately not a rendered string: what a UI shows and how it groups it is
    a decision nobody has enough use to make yet, and shipping the fields keeps
    that decision open. Shipping prose would close it.
    """
    return {
        "stage": review.stage_id,
        "findings_artifact": artifact_path,
        "blocked": review.blocked,
        "artifacts_reviewed": review.artifact_count,
        "links_reviewed": review.link_count,
        "unimplemented_checks": list(review.unimplemented),
        "unreadable_artifacts": list(review.unreadable),
        "findings": [
            {
                "check": finding.check,
                "severity": finding.severity,
                "message": finding.message,
                "cites": list(finding.cites),
                "suggested_edit": finding.suggested_edit,
            }
            for finding in review.findings
        ],
    }
