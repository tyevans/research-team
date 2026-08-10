"""The shared check library: everything a stage exit can verify without asking a model.

`docs/research/course-design/synthesis-generic-workflow.md` §4 is the
specification. Its finding is that the three methodologies' apparently
idiosyncratic quality rules collapse into about seventeen parameterized
queries -- ADDIE's unobservable-verb rejection is `format_conformance` with a
denylist, UbD's transfer-needs-a-task rule is `coverage` with a subtype filter,
Tyler's continuity criterion is `recurrence`. That collapse is why this is one
module rather than three.

**Every check is a graph or schema query. None calls a model, ever.** That single
constraint is what buys both properties this library needs. Cheap: a check runs
on every stage exit, dozens of times in a run, and a model call there would cost
more than the stage it guards. Trustworthy: a model asked to judge its own
pipeline's output produces fluent agreement, which is indistinguishable from a
passing check and is the worst failure mode in the system. Anything that
genuinely needs semantic judgement belongs in a critic prompt behind a gate,
where a human sees the reasoning -- not here, where the output is a boolean
nobody re-reads. `test_no_check_reaches_for_a_model` asserts this rather than
trusting it.

**Findings, never a score.** A check returns a list of
`{check, severity, message, cites, suggested_edit}` and an empty
list is a pass. No aggregate, no percentage. This is not stylistic restraint:
UbD's Design Standards are deliberately written as consider-questions producing
commentary, and rolling them into a number would turn the artifact into
something practitioners do not use -- the same reasoning that keeps `RubricGate`
scoreless.

**Severity is the binding's to choose, except where it isn't.** A preset says
whether its `coverage` is blocking or advisory, because the same check really is
load-bearing in one stage and informational in another. Two checks override
that: `self_review_separation` and `verdict_citation` are harness invariants,
they report at severity `invariant`, and no binding can downgrade them. Both
failures are silent and invisible in the output -- a self-screening critic
passes nearly everything while looking exactly like a filter, and an uncited
verdict reads the same as a cited one -- which is precisely why they have to be
mechanical and non-negotiable rather than requested in a prompt.

**One check is deliberately absent, and says so.** UbD's `uncoverage` -- is this
understanding actually in need of uncovering -- has no automatable proxy, and a
model asked the question will generate fluent platitudes and rate them highly.
It is registered with `run=None` and a `human_gate` reason, and running it emits
a standing `human_gate` finding rather than passing. A human gate that satisfies
itself silently is worse than no check at all, so it refuses to.

**Every check is registered here, explicitly, and nothing registers itself.**
This module is the assembly point: `REGISTRY` is complete the moment it is
imported, and the whole set is readable in one file. A check implemented
elsewhere -- `matrix_density` lives in `coverage.py`, where the matrix it
queries is defined -- is imported and registered here like any other, so the
arrow runs `checks -> coverage -> findings` and never back.

That is a deliberate reversal of the obvious design, in which an
implementation module adds its own `CheckSpec` on import. The obvious design
works and had to be abandoned, because it makes a check's existence depend on
an import nobody can see from either end: the registry does not name it, the
implementation does not know who pulls it in, and a check that was never
registered fails by being absent -- which looks exactly like a check that
passed. `matrix_density` spent a day in precisely that state, fully
implemented, exported, agreed by everyone to be wired, and in no registry.

The `_register` decorator below is still a decorator, and that is not the same
thing: every one of its call sites is in this file, so the set it builds is
something a reader can enumerate by scrolling. The magic was never the
decorator, it was the action at a distance.

`tests/application/test_stage_exit.py` asserts the other half -- that every
name any shipped preset binds resolves here. Explicit registration stops a
check from going unregistered; that test stops a preset from naming one that
does not exist.

**The registry is namespaced and the engine does not know the namespaces.**
Names are opaque strings; `shared.*` holds the generics, and `ubd.*`, `tyler.*`
and `addie.*` exist for rules that genuinely do not generalize. Adding a
methodology means registering names, never editing anything that runs them.

Checks read a `CheckContext`: artifacts with their frontmatter fields and
provenance, the links between them, and -- for the two checks that are graph
properties of the workflow rather than of its output -- the preset's stages.
Nothing here reaches for a file or a store; assembling the context is the
caller's job, which is what keeps this layer testable with dataclasses.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from research_team.application.coverage import CoverageMatrix, matrix_density
from research_team.application.findings import Finding, FindingSeverity
from research_team.domain.workflow import ArtifactType, Check, StageBase

__all__ = [
    "REGISTRY",
    "Artifact",
    "CheckContext",
    "CheckSpec",
    "Finding",
    "FindingSeverity",
    "Link",
    "MalformedCheck",
    "MatrixDensityParams",
    "TypeFilter",
    "UnknownCheck",
    "critic_gates",
    "human_gates",
    "run_check",
    "run_checks",
    "unknown_checks",
]


class UnknownCheck(KeyError):
    """A binding names a check that is not registered.

    Raised rather than reported as a finding, and this is the important choice:
    a typo'd check name that returned an empty list would read as a check that
    ran and found nothing, which is a gate silently disappearing from a preset.
    `unknown_checks` exists so preset authors meet this at edit time instead.
    """


class MalformedCheck(ValueError):
    """A binding's parameters do not fit the check it names.

    Carries the check name because pydantic's message alone does not, and a
    preset binding twenty checks gives no other clue which one is wrong.
    """


# --- what a check reads -----------------------------------------------------


@dataclass(frozen=True)
class Artifact:
    """One artifact instance, as a check sees it.

    Deliberately not the file: `fields` is whatever the frontmatter and any
    structured body parsed to, and `provenance` is the raw list of entries in
    exactly the shape `artifacts.py` documents -- `{source_id, start, end}` or
    `{inferred_not_in_source: true}`. Keeping them as plain mappings rather than
    a second typed model means a check reads what the file actually said, and a
    new methodology-specific field needs no change here to be checkable.

    `stage` and `subtype` are on the node rather than derived, because filters
    routinely need to distinguish the same type produced at two fidelities --
    candidate objectives and screened ones are both `Intent`.
    """

    id: str
    artifact_type: ArtifactType
    subtype: str | None = None
    stage: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class Link:
    """An edge between two artifacts, by id.

    `kind` is carried but no shipped check filters on it. Direction is recorded
    and mostly not consulted: see `_adjacent`.
    """

    source: str
    target: str
    kind: str = "references"


@dataclass(frozen=True)
class CheckContext:
    """Everything the check library is allowed to look at.

    `preset_stages` and `stage` are here for the two checks that are properties
    of the workflow graph rather than of its output. Passing the stage list
    rather than the `Preset` keeps this constructible in a test from two stages,
    which matters because a `Preset` cannot be built malformed and the
    interesting separation cases are exactly the malformed ones.
    """

    artifacts: tuple[Artifact, ...] = ()
    links: tuple[Link, ...] = ()
    matrices: tuple[CoverageMatrix, ...] = ()
    """Built matrices, carried alongside the artifacts they were built from.

    A matrix is derived rather than authored -- `coverage.py` builds it from
    links or attributes -- so rebuilding it inside every `matrix_density`
    binding would do the same join two or three times per stage exit and give
    the check no way to be run against a matrix a human had corrected.
    """
    preset_stages: tuple[StageBase, ...] = ()
    stage: StageBase | None = None


class TypeFilter(BaseModel, frozen=True):
    """Which artifacts a parameter refers to.

    Three optional predicates, ANDed, all absent meaning "any artifact". The
    subtype axis is what lets one `coverage` express UbD's rule that a transfer
    goal needs a *performance task* specifically, which was the single strongest
    piece of evidence in the research that the generic abstraction is real.

    **A bare string is the same thing, spelled the way preset authors write it.**
    `"Intent"` is `{artifact_type: Intent}` and `"EvidenceSpec.performance_task"`
    is that plus the subtype. Every shipped preset reached for the string form
    independently, before this module existed, which is decent evidence that it
    is the natural spelling; and a filter carrying only a type carries no
    information the string does not. The dotted form is unambiguous because
    `ArtifactType` values never contain a dot. An unrecognised type still raises,
    so the shorthand costs no validation -- `"SourceClam"` fails exactly as
    `{"artifact_type": "SourceClam"}` does.
    """

    artifact_type: ArtifactType | None = None
    subtype: str | None = None
    stage: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_a_bare_type_name(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        artifact_type, _, subtype = value.partition(".")
        return {"artifact_type": artifact_type, "subtype": subtype or None}

    def matches(self, artifact: Artifact) -> bool:
        if self.artifact_type is not None and artifact.artifact_type != self.artifact_type:
            return False
        if self.subtype is not None and artifact.subtype != self.subtype:
            return False
        return not (self.stage is not None and artifact.stage != self.stage)

    def describe(self) -> str:
        parts = [str(self.artifact_type) if self.artifact_type else "artifact"]
        if self.subtype:
            parts.append(f"({self.subtype})")
        if self.stage:
            parts.append(f"from {self.stage}")
        return " ".join(parts)


# --- the registry -----------------------------------------------------------


class Params(BaseModel, frozen=True):
    """Base for every check's parameter model.

    `extra="forbid"` is the point of having these at all: a misspelled parameter
    that pydantic silently dropped would leave a check running with its defaults,
    which is a weaker check than the author wrote and no way to notice.
    `populate_by_name` lets the preset data spell parameters the way §4 does --
    `from`, `to`, `min`, `type`, `for` -- none of which are usable as Python
    identifiers.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)


class CheckFn(Protocol):
    def __call__(
        self, context: CheckContext, params: Any
    ) -> list[tuple[str, tuple[str, ...], str | None]]: ...


@dataclass(frozen=True)
class CheckSpec:
    """One registered check: how to parse its parameters and how to run it.

    `fixed_severity` is how the two harness invariants refuse to be downgraded.
    `human_gate` and `critic_gate` are the two ways a check admits it has no
    implementation here, and they are separate because the honest answer differs:
    `uncoverage` has no automated substitute at all, while `expert_gap_flag`
    has one that a model can perform and this library must not. Collapsing them
    would tell a reader that UbD's discriminator and ADDIE's gap detector are
    blocked on the same thing, and they are not. All three are properties of the
    check rather than of the binding, which is exactly the distinction a preset
    author must not be able to override.
    """

    name: str
    params_model: type[Params]
    run: CheckFn | None = None
    fixed_severity: FindingSeverity | None = None
    human_gate: str | None = None
    critic_gate: str | None = None


REGISTRY: dict[str, CheckSpec] = {}


def _register(
    name: str,
    params_model: type[Params],
    *,
    fixed_severity: FindingSeverity | None = None,
) -> Any:
    def decorate(function: CheckFn) -> CheckFn:
        REGISTRY[name] = CheckSpec(
            name=name,
            params_model=params_model,
            run=function,
            fixed_severity=fixed_severity,
        )
        return function

    return decorate


def human_gates() -> tuple[str, ...]:
    """Registered checks that have no automated implementation, by name.

    Exposed so a UI can show a preset's human gates alongside its automated
    ones instead of leaving them indistinguishable from checks that passed.
    """
    return tuple(sorted(name for name, spec in REGISTRY.items() if spec.human_gate))


def critic_gates() -> tuple[str, ...]:
    """Registered checks a model can answer but this library will not, by name.

    The distinction from `human_gates` is worth the second function. A human
    gate is a limit of automation; a critic gate is a limit of *this* module,
    which is restricted to graph and schema queries on purpose. Something has to
    carry that difference, or the only visible category becomes "checks that
    always report", and the two get triaged as one.
    """
    return tuple(sorted(name for name, spec in REGISTRY.items() if spec.critic_gate))


def unknown_checks(bindings: Iterable[Check]) -> list[str]:
    """Every bound name that is not registered, in binding order.

    All of them at once and returned rather than raised, for the same reason
    `problems()` collects preset faults: this is read by someone editing preset
    data, and one typo per run is a bad loop.
    """
    return [binding.check for binding in bindings if binding.check not in REGISTRY]


def run_check(binding: Check, context: CheckContext) -> list[Finding]:
    """Run one bound check, yielding a finding per problem and `[]` for a pass."""
    spec = REGISTRY.get(binding.check)
    if spec is None:
        raise UnknownCheck(f"no check named {binding.check!r} is registered")
    severity: FindingSeverity = spec.fixed_severity or binding.severity
    try:
        params = spec.params_model.model_validate(dict(binding.params))
    except ValidationError as error:
        raise MalformedCheck(f"{binding.check}: {error}") from error
    if spec.run is None:
        # Parameters are validated first even here. A gate's parameters are read
        # by whoever answers it -- `quote_span_required` tells the critic what
        # to produce -- so a typo in them is as real as a typo anywhere else,
        # and skipping validation would make the un-runnable checks the only
        # ones where a misspelled parameter is silently ignored.
        return [
            Finding(
                check=spec.name,
                severity=severity,
                message=spec.human_gate
                or spec.critic_gate
                or "this check has no automated implementation",
            )
        ]
    return [
        Finding(
            check=spec.name,
            severity=severity,
            message=message,
            cites=affected,
            suggested_edit=suggestion,
        )
        for message, affected, suggestion in spec.run(context, params)
    ]


def run_checks(bindings: Iterable[Check], context: CheckContext) -> list[Finding]:
    """Every finding from every binding, in binding order.

    Order is preserved rather than grouped by severity so the list reads in the
    order the preset author wrote, which is the order they will look for it in.
    """
    return [finding for binding in bindings for finding in run_check(binding, context)]


# --- shared helpers ---------------------------------------------------------

_INSTRUMENT_RULE = """When emptiness is a pass and when it is a finding.

Every check here can be handed nothing to look at, and the two honest answers
are not interchangeable. The rule, which every check in this module follows:

**A check reports when the instrument it was handed is missing. A check passes
when only its domain is empty.**

The instrument is what the *binding* supplies or points at -- a ceiling to
measure against, a candidate pool to compute a ratio over, a vocabulary, a
ledger, a criterion document. If it is absent the check has no opinion, and
saying so is the only truthful result: a budget nobody could evaluate must not
be indistinguishable from a budget that was met. `budget`, `prune_ratio`,
`source_starvation`, `taxonomy_distribution`, `vocabulary_coverage`,
`ordering`, `matrix_density`, `exclusion_ledger` and `contradiction_escalation`
all report in this case.

The domain is the set of artifacts a universal quantifies over. "Every intent
has an experience" is *true* of zero intents, and that is not a weasel -- it is
what the sentence means. `coverage`, `orphan`, `recurrence` and `provenance`
therefore pass on an empty domain. The question those checks are not being
asked is whether the stage should have produced artifacts at all; that is the
stage's declared outputs, and answering it here would put the same
finding in four places and still miss the types nothing is bound to.

The two ledger checks moved from the second category to the first, because for
them the distinction collapses: `exclusion_ledger` and
`contradiction_escalation` exist specifically to detect *disappearance*, and an
absent ledger is the disappearance rather than an empty domain over which
something is vacuously true. An empty page saying "nothing was cut" and no page
at all look identical downstream, and only one of them is a claim anybody made.
"""

#: What a check hands back before `run_check` dresses it as a `Finding`:
#: message, affected ids, suggested edit. Checks are spared repeating the name
#: and severity they cannot choose anyway.
Result = tuple[str, tuple[str, ...], str | None]


def _select(context: CheckContext, filter_: TypeFilter) -> list[Artifact]:
    return [artifact for artifact in context.artifacts if filter_.matches(artifact)]


def _adjacent(context: CheckContext, artifact_id: str) -> set[str]:
    """Neighbours of an artifact, ignoring edge direction.

    Direction is an authoring accident here: whether an experience cites the
    objective it serves or the objective lists its experiences is a choice made
    per methodology, and a `coverage` check that only counted one of them would
    silently pass or silently fail depending on that choice. Semantics that
    depend on which way a preset author happened to point an arrow are worse
    than no semantics.
    """
    neighbours = {link.target for link in context.links if link.source == artifact_id}
    neighbours |= {link.source for link in context.links if link.target == artifact_id}
    return neighbours


def _mentions(value: Any, term: str) -> bool:
    """Whether a field claims `term`.

    A list is membership and a string is containment, because both spellings
    occur in real frontmatter -- `code: [A, M]` and `whereto: WHERETO` are the
    same claim written by two authors -- and rejecting one of them would make
    the check a formatting rule wearing a taxonomy's name.
    """
    if isinstance(value, str):
        return term in value
    if isinstance(value, list | tuple | set):
        return any(str(item) == term for item in value)
    return False


def _entries(artifact: Artifact, field_name: str) -> list[Mapping[str, Any]]:
    """A list-of-mappings field, tolerating absence and the wrong shape.

    A ledger whose entries are not mappings is itself a finding, but it is the
    *caller's* finding to report; returning `[]` here keeps a malformed one
    artifact from taking down the check over the other twenty.
    """
    raw = artifact.fields.get(field_name)
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, Mapping)]


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# --- coverage and orphan ----------------------------------------------------


class CoverageParams(Params):
    from_: TypeFilter = Field(default_factory=TypeFilter, alias="from")
    to: TypeFilter = Field(default_factory=TypeFilter)
    min: int = 1


@_register("shared.coverage", CoverageParams)
def _coverage(context: CheckContext, params: CoverageParams) -> list[Result]:
    """Every artifact on the `from` side links to at least `min` on the `to` side.

    One implementation for Tyler's "every objective has an experience and an
    instrument", UbD's "every transfer goal has a performance task" and ADDIE's
    "every terminal objective has an assessment item". The parameterization is
    the whole finding of §4.
    """
    targets = {artifact.id for artifact in _select(context, params.to)}
    results: list[Result] = []
    for artifact in _select(context, params.from_):
        found = len(_adjacent(context, artifact.id) & targets)
        if found < params.min:
            results.append(
                (
                    f"{artifact.id} links to {found} {params.to.describe()}, "
                    f"needs at least {params.min}",
                    (artifact.id,),
                    f"add a link from {artifact.id} to a {params.to.describe()}, "
                    "or drop it if nothing should serve it",
                )
            )
    return results


class OrphanParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    must_link_to: TypeFilter = Field(default_factory=TypeFilter)


@_register("shared.orphan", OrphanParams)
def _orphan(context: CheckContext, params: OrphanParams) -> list[Result]:
    """Artifacts of a type that link to nothing they are supposed to serve.

    Formally `coverage` with `min=1` and the ends swapped, and kept as a separate
    name anyway: to a reader, an uncovered objective and an experience serving
    nothing are different problems with different fixes, and a shared message
    would be wrong for one of them. `test_orphan_is_coverage_with_the_ends_swapped`
    pins the two to the same answer.
    """
    targets = {artifact.id for artifact in _select(context, params.must_link_to)}
    return [
        (
            f"{artifact.id} is an orphan: it links to no {params.must_link_to.describe()}",
            (artifact.id,),
            f"link {artifact.id} to what it serves, or remove it",
        )
        for artifact in _select(context, params.type)
        if not _adjacent(context, artifact.id) & targets
    ]


# --- provenance -------------------------------------------------------------


class ProvenanceParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    must_cite: TypeFilter | None = None
    allow_flag: str = "inferred_not_in_source"


@_register("shared.provenance", ProvenanceParams)
def _provenance(context: CheckContext, params: ProvenanceParams) -> list[Result]:
    """Every artifact says where it came from, or says that it came from nowhere.

    The universal invariant across all three methodologies. An empty list is the
    one shape that is never right: it makes an unsourced claim and a sourced one
    indistinguishable on the page, which is the failure the corpus layer exists
    to prevent. The `allow_flag` entry is a pass, deliberately -- marked
    inference is honest work a reviewer can weigh.
    """
    results: list[Result] = []
    for artifact in _select(context, params.type):
        if not artifact.provenance:
            results.append(
                (
                    f"{artifact.id} has no provenance at all",
                    (artifact.id,),
                    f"cite the source spans it drew on, or record "
                    f"{params.allow_flag}: true if the thinking is yours",
                )
            )
            continue
        for index, entry in enumerate(artifact.provenance):
            cited = bool(entry.get("source_id"))
            flagged = entry.get(params.allow_flag) is True
            if not cited and not flagged:
                results.append(
                    (
                        f"{artifact.id} provenance entry {index} is neither a "
                        f"citation nor a {params.allow_flag} flag",
                        (artifact.id,),
                        "give the entry a source_id with start and end offsets",
                    )
                )
        if params.must_cite is not None:
            required = {item.id for item in _select(context, params.must_cite)}
            if not _adjacent(context, artifact.id) & required:
                results.append(
                    (
                        f"{artifact.id} cites no {params.must_cite.describe()}",
                        (artifact.id,),
                        f"link {artifact.id} to the {params.must_cite.describe()} it rests on",
                    )
                )
    return results


# --- budget -----------------------------------------------------------------


class BudgetParams(Params):
    dimension: Literal["duration", "count"] = "count"
    type: TypeFilter = Field(default_factory=TypeFilter)
    value_field: str | None = None
    source: str = "ContextProfile.budget"
    """Where the ceiling is read from, as `ArtifactType.field`.

    §4's spelling, and one parameter rather than the two this originally had.
    The dotted path is what a preset author writes anyway -- every shipped
    preset guessed `ContextProfile.time_budget` before this module existed --
    and splitting it into a filter plus a field name made the binding longer
    without making it more expressive.
    """


@_register("shared.budget", BudgetParams)
def _budget(context: CheckContext, params: BudgetParams) -> list[Result]:
    """What the design costs against what the context said was available.

    The ceiling is read from another artifact rather than written into the
    binding, because it is a fact about *this* course -- ADDIE's seat-time
    ceiling, UbD's `ContextProfile` -- and a number baked into a preset would be
    wrong for the second course that ran it.

    An unreadable ceiling is reported, not skipped. A budget nobody could
    evaluate must not be indistinguishable from a budget that was met; that is
    the class of silent pass this library exists to remove.
    """
    holder, _, ceiling_field = params.source.partition(".")
    if not ceiling_field:
        raise MalformedCheck(
            f"shared.budget: source {params.source!r} is not ArtifactType.field"
        )
    ceiling_source = TypeFilter.model_validate(holder)
    ceilings = [
        artifact.fields[ceiling_field]
        for artifact in _select(context, ceiling_source)
        if isinstance(artifact.fields.get(ceiling_field), int | float)
    ]
    if not ceilings:
        return [
            (
                f"no {ceiling_source.describe()} carries {ceiling_field}, so the "
                "budget cannot be evaluated",
                (),
                f"record {ceiling_field} on the {ceiling_source.describe()}",
            )
        ]
    ceiling = min(ceilings)
    items = _select(context, params.type)
    if params.dimension == "count":
        total: float = len(items)
        unit = params.type.describe()
    else:
        name = params.value_field or "minutes"
        total = sum(
            value for item in items if isinstance(value := item.fields.get(name), int | float)
        )
        unit = name
    if total <= ceiling:
        return []
    return [
        (
            f"{total:g} {unit} against a ceiling of {ceiling:g}",
            tuple(item.id for item in items),
            "cut scope or raise the ceiling deliberately; do not do both quietly",
        )
    ]


# --- format conformance -----------------------------------------------------


class FormatParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    field: str = "text"
    stem: str | None = None
    verb_denylist: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    reject_if: tuple[str, ...] = ()


def _denied(text: str, phrase: str) -> bool:
    """Whether `phrase` appears as a whole word (or word sequence) in `text`.

    Whole-word matching is load-bearing: ADDIE denies the *verb* "understand",
    and a substring match would also reject "an understanding graph", which is
    a noun and fine. A denylist that fires on correct artifacts gets switched
    off, and a check nobody runs enforces nothing.
    """
    pattern = r"\b" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


@_register("shared.format_conformance", FormatParams)
def _format_conformance(context: CheckContext, params: FormatParams) -> list[Result]:
    """Schema, stem, denied verbs and rejection patterns, in one check.

    Four predicates rather than four checks because §4 found them to be one
    parameter set with different arguments per methodology: UbD's understanding
    stem, ADDIE's unobservable-verb denylist, Tyler's required behavior+content
    pair. Each is optional, and a binding supplying none of them passes
    everything -- which is the honest behaviour for "no format was specified".
    """
    results: list[Result] = []
    for artifact in _select(context, params.type):
        for name in params.required_fields:
            if _blank(artifact.fields.get(name)):
                results.append(
                    (
                        f"{artifact.id} is missing required field {name}",
                        (artifact.id,),
                        f"add {name} to {artifact.id}",
                    )
                )
        value = artifact.fields.get(params.field)
        if not isinstance(value, str):
            continue
        if params.stem is not None and not value.startswith(params.stem):
            results.append(
                (
                    f"{artifact.id} does not open with {params.stem!r}",
                    (artifact.id,),
                    f"rewrite {artifact.id} to begin {params.stem!r}",
                )
            )
        for phrase in params.verb_denylist:
            if _denied(value, phrase):
                results.append(
                    (
                        f"{artifact.id} uses the unobservable verb {phrase!r}",
                        (artifact.id,),
                        f"replace {phrase!r} with something a learner can be seen doing",
                    )
                )
        for pattern in params.reject_if:
            if re.search(pattern, value):
                results.append(
                    (
                        f"{artifact.id} matches the rejection pattern {pattern!r}",
                        (artifact.id,),
                        None,
                    )
                )
    return results


# --- taxonomy and vocabulary ------------------------------------------------


class TaxonomyParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    dimension: str = "code"
    classes: tuple[str, ...] = ()
    min_per_class: int | Mapping[str, int] = 1
    """One floor for every class, or a floor per class.

    The mapping form supplies the vocabulary as well as the minimum, which is
    what a preset author writing `{"A": 1, "M": 1, "T": 1}` clearly intends and
    is strictly more expressive: UbD's A/M/T balance really does want different
    floors once a unit is long enough for one transfer task and six acquisition
    events. `classes` remains for the uniform case.
    """
    max_per_item: int | None = None
    must_match_parent: str | None = None
    """`ArtifactType.field` an item's class must agree with on its parent.

    ADDIE's rule that an assessment item sits at the Bloom level of the
    objective it serves. A graph query rather than a judgement: follow the link,
    compare two strings. The failure it catches is the common one -- a recall
    item under an "evaluate" objective -- which reads as fine item by item and
    is only visible against the parent.
    """


@_register("shared.taxonomy_distribution", TaxonomyParams)
def _taxonomy_distribution(context: CheckContext, params: TaxonomyParams) -> list[Result]:
    """Balance across a named taxonomy, and no item claiming to be everything.

    UbD's A/M/T balance is the highest-value member of the whole set: a unit
    with no transfer-coded event is the single commonest real design failure,
    and it is invisible in prose. The classes are a parameter rather than
    inferred from the data because a class with zero members is exactly what the
    check is looking for, and nothing in the artifacts can tell you it was
    supposed to exist. Taxonomies are named, never unioned -- Bloom's is a
    hierarchy, the Six Facets are explicitly not one.
    """
    items = _select(context, params.type)
    if isinstance(params.min_per_class, Mapping):
        floors = dict(params.min_per_class)
    else:
        floors = dict.fromkeys(params.classes, params.min_per_class)
    results: list[Result] = []
    for name, floor in floors.items():
        holders = [
            item.id for item in items if _mentions(item.fields.get(params.dimension), name)
        ]
        if len(holders) < floor:
            results.append(
                (
                    f"class {name!r} on {params.dimension} has {len(holders)} of "
                    f"{floor} required",
                    (),
                    f"design something coded {name}, or say why this course has none",
                )
            )
    if params.must_match_parent is not None:
        holder, _, parent_field = params.must_match_parent.partition(".")
        if not parent_field:
            raise MalformedCheck(
                f"shared.taxonomy_distribution: must_match_parent "
                f"{params.must_match_parent!r} is not ArtifactType.field"
            )
        parents = {
            parent.id: parent for parent in _select(context, TypeFilter.model_validate(holder))
        }
        for item in items:
            own = item.fields.get(params.dimension)
            for parent_id in sorted(_adjacent(context, item.id) & set(parents)):
                expected = parents[parent_id].fields.get(parent_field)
                if expected is not None and not _mentions(own, str(expected)):
                    results.append(
                        (
                            f"{item.id} is coded {own!r} but serves {parent_id}, "
                            f"which is {expected!r}",
                            (item.id, parent_id),
                            f"match {item.id} to the demand {parent_id} states, or "
                            "change the objective",
                        )
                    )
    if params.max_per_item is not None:
        for item in items:
            claimed = [
                name for name in floors if _mentions(item.fields.get(params.dimension), name)
            ]
            if len(claimed) > params.max_per_item:
                results.append(
                    (
                        f"{item.id} claims {len(claimed)} classes on "
                        f"{params.dimension}, at most {params.max_per_item} allowed",
                        (item.id,),
                        f"pick the one class {item.id} is really for",
                    )
                )
    return results


class VocabularyParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    dimension: str = "code"
    vocab: tuple[str, ...] = ()
    min_each: int = 1
    min_required: tuple[str, ...] = ()
    """The subset of `vocab` that is mandatory; empty means all of it.

    UbD's rubric rule is the motivating case: a rubric may draw on content,
    quality and process criteria as it likes, but an `impact` criterion is not
    optional, because a performance assessed only on its process has stopped
    assessing transfer. Requiring every term instead would be wrong in the other
    direction -- it would force a rubric to use criterion types it has no use
    for, which is how checklists become paperwork.
    """


@_register("shared.vocabulary_coverage", VocabularyParams)
def _vocabulary_coverage(context: CheckContext, params: VocabularyParams) -> list[Result]:
    """Every term in a required checklist appears somewhere in the set.

    Distinct from `taxonomy_distribution` despite the family resemblance: a
    taxonomy classifies each item and the interesting failure is an item in two
    classes at once, while a checklist vocabulary -- WHERETO's letters, a
    rubric's mandatory criterion types -- has nothing to say about any single
    item. Collapsing them would give one check two meanings for `max_per_item`.
    """
    items = _select(context, params.type)
    return [
        (
            f"{term!r} appears on {count} {params.type.describe()}, needs {params.min_each}",
            (),
            f"cover {term!r} somewhere in the design, or drop it from the vocabulary",
        )
        for term in (params.min_required or params.vocab)
        if (
            count := sum(
                1 for item in items if _mentions(item.fields.get(params.dimension), term)
            )
        )
        < params.min_each
    ]


# --- the exclusion ledger ---------------------------------------------------


class ExclusionParams(Params):
    candidates: TypeFilter = Field(default_factory=TypeFilter)
    survivors: TypeFilter = Field(default_factory=TypeFilter)
    ledger: TypeFilter = Field(default_factory=TypeFilter)
    entries_field: str = "entries"
    id_field: str = "candidate_id"
    reason_field: str = "reason"
    no_silent_drops: bool = True


@_register("shared.exclusion_ledger", ExclusionParams)
def _exclusion_ledger(context: CheckContext, params: ExclusionParams) -> list[Result]:
    """Nothing leaves the pipeline without a reason on the record.

    All three traditions arrive at this independently -- Tyler's
    reject-with-reason, ADDIE's `OutOfScopeRegister` with dispositions, UbD's
    reviewable prune -- and all three arrive at it because the interesting
    content of a screen is what it cut. A candidate that is simply absent
    downstream is the silent-drop failure, and it is undetectable by reading the
    output, since the output looks like a clean shorter list.

    A survivor counts as accounting for a candidate if it *is* that candidate or
    links to it, so a screen may either retain the artifact or produce a
    refined one that cites its origin.

    A missing ledger is reported rather than passed -- see `_INSTRUMENT_RULE`.
    The ledger is this check's instrument, and without one nothing records what
    was cut, which from the output alone is indistinguishable from a screen
    that cut nothing. Returning clean there is the reassuring-direction failure
    the check exists to catch.
    """
    if not params.no_silent_drops:
        return []
    ledgers = _select(context, params.ledger)
    if not ledgers:
        return [
            (
                f"no {params.ledger.describe()} is present, so nothing records "
                "what this stage cut",
                (),
                "write the exclusion ledger, empty and explicit if nothing was cut",
            )
        ]
    survivors = _select(context, params.survivors)
    accounted = {artifact.id for artifact in survivors}
    for artifact in survivors:
        accounted |= _adjacent(context, artifact.id)
    listed: dict[str, Any] = {}
    for ledger in ledgers:
        for entry in _entries(ledger, params.entries_field):
            candidate = entry.get(params.id_field)
            if isinstance(candidate, str):
                listed[candidate] = entry.get(params.reason_field)
    results: list[Result] = []
    for candidate in _select(context, params.candidates):
        if candidate.id in accounted:
            continue
        if candidate.id not in listed:
            results.append(
                (
                    f"{candidate.id} was dropped silently: no survivor accounts "
                    "for it and no ledger entry names it",
                    (candidate.id,),
                    f"add a ledger entry for {candidate.id} with the reason it went",
                )
            )
        elif _blank(listed[candidate.id]):
            results.append(
                (
                    f"{candidate.id} is excluded with no reason given",
                    (candidate.id,),
                    "a reason a reviewer can disagree with, not a blank",
                )
            )
    return results


# --- the two harness invariants ---------------------------------------------


class VerdictCitationParams(Params):
    ledger: TypeFilter = Field(default_factory=TypeFilter)
    criterion_doc: TypeFilter = Field(default_factory=TypeFilter)
    entries_field: str = "verdicts"
    clause_field: str = "clause"
    clauses_field: str = "clauses"
    on_retrieval_failure: Literal["fail", "flag", "force_verdict_contested"] = "fail"


@_register("shared.verdict_citation", VerdictCitationParams, fixed_severity="invariant")
def _verdict_citation(context: CheckContext, params: VerdictCitationParams) -> list[Result]:
    """A verdict with legal force over a candidate must cite the clause it rests on.

    A harness invariant, not advice, and no binding can downgrade it. Tyler's
    screens are the only place a verdict can kill a candidate outright, and an
    uncited verdict is textually indistinguishable from a cited one -- it reads
    as confident and specific while being fluent generic plausibility, which the
    spec calls the worst failure in the system precisely because it looks like it
    is working. The citation is what makes the verdict arguable at the gate.

    `on_retrieval_failure` covers the case where the criterion document is
    missing or does not enumerate its clauses, so the citation cannot be
    resolved. It defaults to `fail`: an unverifiable citation is not evidence.
    `force_verdict_contested` is the better answer where a screen has legal
    force -- it says the verdict is neither upheld nor discarded but owed to a
    human, which is what Tyler's screens need and what `flag` is too weak to
    express. `flag` is for the advisory case, where the run should note the gap
    and continue.
    """
    clauses: set[str] = set()
    documents = _select(context, params.criterion_doc)
    for document in documents:
        raw = document.fields.get(params.clauses_field)
        if isinstance(raw, list):
            clauses |= {str(item) for item in raw}
    results: list[Result] = []
    for ledger in _select(context, params.ledger):
        for index, entry in enumerate(_entries(ledger, params.entries_field)):
            cited = entry.get(params.clause_field)
            where = entry.get("candidate_id", index)
            if _blank(cited):
                results.append(
                    (
                        f"verdict on {where} in {ledger.id} cites no clause of a "
                        f"{params.criterion_doc.describe()}",
                        (ledger.id,),
                        "cite the clause the verdict rests on, or withdraw the verdict",
                    )
                )
                continue
            if not clauses:
                if params.on_retrieval_failure == "force_verdict_contested":
                    results.append(
                        (
                            f"verdict on {where} in {ledger.id} cites {cited!r}, which "
                            "cannot be resolved: the verdict is contested",
                            (ledger.id,),
                            f"route {where} to the reviewer as contested; it is "
                            "neither upheld nor discarded until someone reads the clause",
                        )
                    )
                elif params.on_retrieval_failure == "fail":
                    results.append(
                        (
                            f"verdict on {where} in {ledger.id} cites {cited!r}, but "
                            "no criterion document enumerates its clauses",
                            (ledger.id,),
                            "supply the criterion document the screen ran against",
                        )
                    )
                continue
            if str(cited) not in clauses:
                results.append(
                    (
                        f"verdict on {where} in {ledger.id} cites {cited!r}, which "
                        "is not a clause of any criterion document present",
                        (ledger.id,),
                        "cite a clause that exists",
                    )
                )
    return results


class SeparationParams(Params):
    generator_stage: str


@_register("shared.self_review_separation", SeparationParams, fixed_severity="invariant")
def _self_review_separation(context: CheckContext, params: SeparationParams) -> list[Result]:
    """The critic for a stage must not be its generator, by any route.

    The other harness invariant, and the more dangerous of the two because it
    fails *upward*: a self-screening critic passes nearly everything, so the run
    looks fast and clean and the ledger looks like a filter that found little to
    object to. `ScreenStage` makes the crudest version untypeable by having no
    generator field; this catches the three versions that are still typeable --
    the same role, the same prompt, and a critic sharing the generator's context
    and therefore reviewing the argument rather than the artifact.

    Reported as one finding per stage listing every reason, rather than one per
    reason: they are all the same defect, and three findings would read as three
    problems to fix separately.
    """
    stage = context.stage
    if stage is None:
        return [("no stage in context, so separation cannot be checked", (), None)]
    generator_stage = next(
        (
            candidate
            for candidate in context.preset_stages
            if candidate.id == params.generator_stage
        ),
        None,
    )
    if generator_stage is None:
        return [
            (
                f"{stage.id} declares separation from unknown stage {params.generator_stage}",
                (),
                "name the stage that generates the candidates this one reviews",
            )
        ]
    critic = getattr(stage, "critic", None)
    generator = getattr(generator_stage, "generator", None)
    if critic is None:
        return [(f"{stage.id} has no critic, so there is nothing to separate", (), None)]
    if generator is None:
        return [(f"{params.generator_stage} has no generator to separate from", (), None)]
    reasons: list[str] = []
    if stage.id == generator_stage.id:
        reasons.append("it reviews its own stage")
    if critic.role == generator.role:
        reasons.append(f"critic and generator share the role {critic.role!r}")
    if critic.prompt_ref == generator.prompt_ref:
        reasons.append(f"critic and generator share the prompt {critic.prompt_ref!r}")
    if not critic.separate_context:
        reasons.append("the critic sees the generation trajectory")
    if not reasons:
        return []
    return [
        (
            f"{stage.id} is self-reviewing {generator_stage.id}: " + "; ".join(reasons),
            (),
            "give the critic a distinct role, prompt and context; a critic that "
            "has seen the reasoning reviews the argument, not the artifact",
        )
    ]


# --- prune ratio ------------------------------------------------------------


class PruneParams(Params):
    survivors: TypeFilter | None = None
    candidate_pool: TypeFilter | None = None
    excluded: TypeFilter | None = None
    items_field: str | None = None
    """Count the items *inside* each selected artifact rather than the artifacts.

    `load_course` builds one `Artifact` per file and a stage writes one file per
    declared output, so counting artifacts counts files: an understandings file
    and a candidates file are one apiece however many lines each holds, and the
    ratio is 1.0 whatever the screen did. Naming the field that holds the items
    -- a list, or a block scalar written one per line -- is the only way the
    numerator can be a number of understandings rather than a number of files.
    """
    entries_field: str = "entries"
    """Where an `excluded` ledger keeps what it cut, one entry each."""
    expected_range: tuple[float, float] = (0.1, 0.6)

    @model_validator(mode="after")
    def _the_denominator_is_named(self) -> "PruneParams":
        """Rejected at validation, not at run time, so a defective binding is a
        preset error the whole-preset parameter test sees rather than a finding
        one run of one stage produces."""
        if self.survivors is None:
            raise ValueError(
                "prune_ratio needs `survivors`: without it the numerator is "
                "every artifact in the course"
            )
        if self.candidate_pool is None and self.excluded is None:
            raise ValueError(
                "prune_ratio needs `candidate_pool` (where the candidates survive "
                "as artifacts of their own) or `excluded` (the ledger of what was "
                "cut); with neither, the ratio is 1.0 by construction"
            )
        return self


def _count(artifacts: Sequence[Artifact], items_field: str | None) -> int:
    """How many things these artifacts amount to: files, or items within them.

    A string is counted by non-blank lines because that is how every shipped
    prompt writes a multi-item `text` field. A field of any other shape counts
    zero rather than one -- an item field nobody wrote is not one item, and
    counting it as one is how a denominator quietly becomes a floor.
    """
    if items_field is None:
        return len(artifacts)
    total = 0
    for artifact in artifacts:
        value = artifact.fields.get(items_field)
        if isinstance(value, list | tuple):
            total += len(value)
        elif isinstance(value, str):
            total += len([line for line in value.splitlines() if line.strip()])
    return total


@_register("shared.prune_ratio", PruneParams)
def _prune_ratio(context: CheckContext, params: PruneParams) -> list[Result]:
    """How much the screen actually cut, against how much it was meant to.

    The rubber-stamp detector. Over-generate-then-screen is the shared shape of
    Tyler's candidate objectives and UbD's fifteen understandings pruned to
    three, and its failure mode is a critic that approves everything -- which
    produces a perfect-looking ledger. A ratio near 1.0 means the screen did no
    work; a ratio near 0 means the generator did none, or the criterion document
    is wrong.

    **The denominator has to be named, and there are two honest ways to name
    it.** Either the candidates survive as artifacts of their own and
    `candidate_pool` selects them, or they do not -- UbD generates fifteen
    understandings in one turn and writes three down -- and then the only record
    of the pool is the survivors plus the ledger of what was cut, which is what
    `excluded` is for. A binding supplying neither is `MalformedCheck` rather
    than a finding: both filters defaulting to "any artifact" made pool and
    survivors the same set and pinned the ratio at 1.0, so the check reported a
    rubber stamp on every run of two shipped presets and taught its readers to
    skip it. A check that always fires is worse than no check, and the cost of
    refusing the binding is that a preset author must say what was screened.

    An empty pool is a finding rather than a division by zero: a screen with
    nothing to screen ran, reported success, and means nothing.
    """
    assert params.survivors is not None  # held by `_the_denominator_is_named`
    kept_items = _select(context, params.survivors)
    kept = _count(kept_items, params.items_field)
    if params.candidate_pool is not None:
        described = params.candidate_pool.describe()
        pool = _count(_select(context, params.candidate_pool), params.items_field)
    else:
        assert params.excluded is not None
        described = f"{params.excluded.describe()} entry"
        pool = kept + _count(_select(context, params.excluded), params.entries_field)
    low, high = params.expected_range
    if not pool:
        return [
            (
                f"no {described} to prune, so the prune ratio means nothing",
                (),
                "check the generating stage actually produced a pool",
            )
        ]
    ratio = kept / pool
    if low <= ratio <= high:
        return []
    verdict = (
        "the screen kept almost everything, which is what a rubber stamp looks like"
        if ratio > high
        else "the screen kept almost nothing; check the criterion document"
    )
    return [
        (
            f"{kept} of {pool} survived ({ratio:.0%}), expected "
            f"{low:.0%}-{high:.0%}: {verdict}",
            (),
            "review the rejections at the gate before accepting this",
        )
    ]


# --- non-degenerate required fields -----------------------------------------


class NondegenerateParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    field: str = "text"
    reject_if: tuple[
        Literal["empty", "duplicate", "duplicate_of_previous", "generic", "unmeasurable"],
        ...,
    ] = ("empty",)
    generic_phrases: tuple[str, ...] = ()
    min_chars: int = 0
    per: str | None = None
    """A field to group by before comparing, so duplicates are judged in scope.

    Tyler's escalation descriptor recurs per thread, and two different threads
    landing on the same wording is a coincidence while one thread repeating
    itself is a flat spiral. Without the grouping the check reports the first as
    if it were the second, and a check that cries wolf gets unbound.
    """
    position_field: str = "position"


@_register("shared.required_field_nondegenerate", NondegenerateParams)
def _required_field_nondegenerate(
    context: CheckContext, params: NondegenerateParams
) -> list[Result]:
    """A field that exists but says nothing is worse than one that is missing.

    Tyler's escalation descriptor per recurrence is the motivating case: a
    spiral whose every turn carries the same sentence is flat, and reads as
    complete. `duplicate` catches any two that match; `duplicate_of_previous`
    catches only a turn identical to the one before it, which is the flat spiral
    exactly and does not fire on a descriptor that legitimately returns to an
    earlier form later.

    Two of the five rejections are proxies and are worth naming as such.
    `generic` is a denylist of stock phrases plus a length floor, because
    judging genericness in the general case needs a model, and that judgement
    belongs in a critic prompt where a human sees the reasoning rather than here
    where the result is a boolean. `unmeasurable` asks only whether the value
    contains a number: "reduce escalations" fails and "reduce escalations by
    15%" passes. Neither proxy is the concept, both catch the specific failure
    that keeps recurring, and a check that catches the common case honestly is
    worth more than one that claims the general case falsely.
    """
    items = _select(context, params.type)
    seen: dict[tuple[str, str], list[str]] = {}
    results: list[Result] = []
    for item in items:
        value = item.fields.get(params.field)
        if "empty" in params.reject_if and (
            _blank(value) or (isinstance(value, str) and len(value.strip()) < params.min_chars)
        ):
            results.append(
                (
                    f"{item.id} has an empty {params.field}",
                    (item.id,),
                    f"write a {params.field} specific to {item.id}",
                )
            )
            continue
        if not isinstance(value, str):
            continue
        group = str(item.fields.get(params.per)) if params.per else ""
        seen.setdefault((group, value.strip().casefold()), []).append(item.id)
        if "generic" in params.reject_if and any(
            phrase.casefold() in value.casefold() for phrase in params.generic_phrases
        ):
            results.append(
                (
                    f"{item.id} has a generic {params.field}: {value!r}",
                    (item.id,),
                    "say the thing that is true of this one and not of the others",
                )
            )
        if "unmeasurable" in params.reject_if and not any(
            character.isdigit() for character in value
        ):
            results.append(
                (
                    f"{item.id} states no measurable quantity in {params.field}: {value!r}",
                    (item.id,),
                    "name the number and the period it is measured over",
                )
            )
    if "duplicate" in params.reject_if:
        results.extend(
            (
                f"{len(ids)} artifacts share the same {params.field}: {', '.join(ids)}",
                tuple(ids),
                f"differentiate the {params.field}s, or say why they are identical",
            )
            for ids in seen.values()
            if len(ids) > 1
        )
    if "duplicate_of_previous" in params.reject_if:
        results.extend(_flat_spiral(items, params))
    return results


def _flat_spiral(items: Sequence[Artifact], params: NondegenerateParams) -> list[Result]:
    """Consecutive occurrences within a group carrying an identical value.

    Ordered by `position_field` rather than by list order, because "the turn
    before this one" is a claim about the sequence a learner meets and not about
    the order a generator happened to emit.
    """
    grouped: dict[str, list[Artifact]] = {}
    for item in items:
        grouped.setdefault(str(item.fields.get(params.per)) if params.per else "", []).append(
            item
        )
    results: list[Result] = []
    for group, members in grouped.items():
        ordered = _sequenced(members, params.position_field)
        for earlier, later in pairwise(ordered):
            before = earlier.fields.get(params.field)
            after = later.fields.get(params.field)
            if (
                isinstance(before, str)
                and isinstance(after, str)
                and before.strip().casefold() == after.strip().casefold()
            ):
                where = f" in {group}" if group else ""
                results.append(
                    (
                        f"{later.id} repeats the {params.field} of {earlier.id}"
                        f"{where}: the spiral is flat here",
                        (earlier.id, later.id),
                        "each turn must ask more than the one before it; say what "
                        "is harder this time",
                    )
                )
    return results


# --- recurrence -------------------------------------------------------------


class RecurrenceParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    min_occurrences: int = 2
    key_field: str | None = None


@_register("shared.recurrence", RecurrenceParams)
def _recurrence(context: CheckContext, params: RecurrenceParams) -> list[Result]:
    """Tyler's continuity criterion: an intent met once was not really taught.

    Two counting modes, because recurrence is expressed both ways in real
    artifacts. By default an artifact recurs as often as other artifacts link to
    it. With `key_field`, artifacts sharing a field value are occurrences of one
    thread -- which is how a preset that does not model links between events and
    threads still gets the check.

    At `min_occurrences=1` this degenerates into `orphan`, and the property test
    pins that: if the two ever disagree, the adjacency helper is broken.
    """
    items = _select(context, params.type)
    if params.key_field is None:
        counts = {item.id: len(_adjacent(context, item.id)) for item in items}
        return [
            (
                f"{item_id} occurs {count} times, continuity needs {params.min_occurrences}",
                (item_id,),
                f"revisit {item_id} later in the sequence, at a higher demand",
            )
            for item_id, count in counts.items()
            if count < params.min_occurrences
        ]
    grouped: dict[str, list[str]] = {}
    for item in items:
        grouped.setdefault(str(item.fields.get(params.key_field)), []).append(item.id)
    return [
        (
            f"{params.key_field}={key!r} occurs {len(ids)} times, continuity "
            f"needs {params.min_occurrences}",
            tuple(ids),
            f"revisit {key!r} later in the sequence, at a higher demand",
        )
        for key, ids in grouped.items()
        if len(ids) < params.min_occurrences
    ]


# --- ordering and prerequisites ---------------------------------------------


def _sequenced(items: Sequence[Artifact], position_field: str) -> list[Artifact]:
    """Artifacts in sequence order, falling back to the order they arrived.

    A missing position sorts last rather than raising: an unpositioned event is
    itself a finding for another check, and losing the ordering check entirely
    because one event lacked a number would be the wrong trade.
    """
    return sorted(
        items,
        key=lambda item: (
            not isinstance(item.fields.get(position_field), int | float),
            item.fields.get(position_field)
            if isinstance(item.fields.get(position_field), int | float)
            else 0,
        ),
    )


class OrderingParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    element: str
    element_field: str = "code"
    position_percentile: float = 0.33
    position_field: str = "position"


@_register("shared.ordering", OrderingParams)
def _ordering(context: CheckContext, params: OrderingParams) -> list[Result]:
    """An element that must appear early in a sequence, and does not.

    UbD's **W** -- where the unit is going and why -- is the case: it is not
    merely required, it is required *first*, and a unit that explains itself in
    week three has lost most of the value of explaining itself at all. A
    percentile rather than an index because sequences differ in length and "in
    the first third" is the claim the methodology actually makes.

    An element that never appears is reported with no affected artifact, because
    there is no artifact to point at -- which is exactly the finding.
    """
    ordered = _sequenced(_select(context, params.type), params.position_field)
    if not ordered:
        return [
            (
                f"no {params.type.describe()} to order",
                (),
                None,
            )
        ]
    for index, item in enumerate(ordered):
        if _mentions(item.fields.get(params.element_field), params.element):
            percentile = index / len(ordered)
            if percentile <= params.position_percentile:
                return []
            return [
                (
                    f"{params.element!r} first appears {percentile:.0%} through "
                    f"the sequence, needs to be within the first "
                    f"{params.position_percentile:.0%}",
                    (item.id,),
                    f"move {item.id} earlier, or introduce {params.element!r} sooner",
                )
            ]
    return [
        (
            f"{params.element!r} never appears on {params.element_field}",
            (),
            f"add something carrying {params.element!r}",
        )
    ]


class PrerequisiteParams(Params):
    for_: TypeFilter = Field(default_factory=TypeFilter, alias="for")
    required_from: TypeFilter = Field(default_factory=TypeFilter)
    via: str = "requires"
    key_field: str = "key"
    position_field: str = "position"


@_register("shared.prerequisite_satisfied", PrerequisiteParams)
def _prerequisite_satisfied(context: CheckContext, params: PrerequisiteParams) -> list[Result]:
    """What a task needs must exist, and must come before the task needs it.

    Two failures, and the second is the one that survives review: UbD's
    performance task whose required skills are never equipped is obvious once
    named, while the task that requires a skill taught two weeks later reads
    perfectly well in the document and fails only in a classroom. Gagne's
    prerequisite ordering is the same constraint under a different name.

    A provider may equip **several** keys, because `load_course` gives one
    artifact per file and a stage writes one file per declared output: the
    skills a unit teaches are lines in one artifact, not one artifact each. A
    list-valued `key_field` is therefore every key that artifact equips. Reading
    only a scalar there was not a smaller feature, it was a wrong answer --
    `str(["a", "b"])` is a key nothing ever requires, so every requirement
    reported as unprovided.
    """
    providers = _select(context, params.required_from)
    supplied: dict[str, Artifact] = {}
    for provider in providers:
        raw_keys = provider.fields.get(params.key_field)
        if raw_keys is None:
            continue
        keys = raw_keys if isinstance(raw_keys, list | tuple) else [raw_keys]
        for key in keys:
            supplied.setdefault(str(key), provider)
    results: list[Result] = []
    for consumer in _select(context, params.for_):
        raw = consumer.fields.get(params.via)
        needed = raw if isinstance(raw, list | tuple) else ([raw] if raw else [])
        for requirement in (str(item) for item in needed):
            provider = supplied.get(requirement)
            if provider is None:
                results.append(
                    (
                        f"{consumer.id} requires {requirement!r}, which no "
                        f"{params.required_from.describe()} provides",
                        (consumer.id,),
                        f"design something that equips {requirement!r}, or drop "
                        "the requirement",
                    )
                )
                continue
            here = consumer.fields.get(params.position_field)
            there = provider.fields.get(params.position_field)
            if (
                isinstance(here, int | float)
                and isinstance(there, int | float)
                and there >= here
            ):
                results.append(
                    (
                        f"{consumer.id} requires {requirement!r}, which "
                        f"{provider.id} does not equip until later",
                        (consumer.id, provider.id),
                        f"move {provider.id} before {consumer.id}",
                    )
                )
    return results


# --- source starvation and contradiction escalation -------------------------


class StarvationParams(Params):
    routes: tuple[str, ...] = ()
    """Named intake routes that must each yield claims, §4's spelling.

    Tyler's three sources of objectives -- learner, contemporary life,
    discipline -- are *routes*, not documents, and the failure they guard
    against is a design that claims three inputs and drew on one. That is a
    different question from "which document did nothing draw on", so both modes
    are here: `routes` counts by a field on the claim, and `sources` counts by
    the documents themselves. Naming neither checks nothing, which is why an
    empty binding is a finding rather than a pass.
    """
    route_field: str = "route"
    sources: TypeFilter | None = None
    claims: TypeFilter = Field(default_factory=TypeFilter)
    id_field: str = "source_id"
    min_claims_each: int = 1


@_register("shared.source_starvation", StarvationParams)
def _source_starvation(context: CheckContext, params: StarvationParams) -> list[Result]:
    """A source nothing drew on is a finding, not a silence.

    Tyler's version is the sharpest: a route named as an input and then
    effectively unused means either it was wrong for this course or the
    extraction missed it, and both are worth knowing before the objectives are
    written. Generalizes to ADDIE's single-SME dependency and UbD's
    standards-only input, where the same count says the design rests on one
    voice while appearing to rest on several.

    The starved route is reported with no affected artifact, deliberately: the
    finding is about what is *not* there, and there is no artifact to point at.
    """
    claims = _select(context, params.claims)
    results: list[Result] = []
    if params.routes:
        by_route: dict[str, int] = dict.fromkeys(params.routes, 0)
        for claim in claims:
            route = claim.fields.get(params.route_field)
            if isinstance(route, str) and route in by_route:
                by_route[route] += 1
        results += [
            (
                f"route {route!r} yielded {count} claims, expected at least "
                f"{params.min_claims_each}",
                (),
                f"draw on {route!r} or record why this course has nothing from it",
            )
            for route, count in by_route.items()
            if count < params.min_claims_each
        ]
    if params.sources is not None:
        counts: dict[str, int] = {}
        for claim in claims:
            for entry in claim.provenance:
                source_id = entry.get("source_id")
                if isinstance(source_id, str):
                    counts[source_id] = counts.get(source_id, 0) + 1
        results += [
            (
                f"{name} has {counts.get(name, 0)} claims, expected at least "
                f"{params.min_claims_each}",
                (source.id,),
                "extract from it, or drop it from the corpus with a reason",
            )
            for source in _select(context, params.sources)
            if counts.get(name := str(source.fields.get(params.id_field)), 0)
            < params.min_claims_each
        ]
    if not params.routes and params.sources is None:
        raise MalformedCheck(
            "shared.source_starvation: name routes, sources, or both; a binding "
            "with neither checks nothing"
        )
    return results


class ContradictionParams(Params):
    type: TypeFilter = Field(default_factory=TypeFilter)
    entries_field: str = "entries"
    resolution_field: str = "resolution"
    escalation_field: str = "escalated_to"
    no_auto_resolve: bool = True


@_register("shared.contradiction_escalation", ContradictionParams)
def _contradiction_escalation(
    context: CheckContext, params: ContradictionParams
) -> list[Result]:
    """Two sources disagreeing is information; the pipeline picking one is not.

    Consolidation will silently merge contradictory claims if nothing stops it,
    and two SMEs giving different escalation thresholds unified into one node is
    a course that teaches something neither of them said. The rule is that a
    contradiction leaves the pipeline only through a named human. So a resolution
    with no escalation target is a finding, and so is an entry with neither --
    that one is a contradiction logged and then forgotten, which is the same
    outcome as never having noticed.

    A missing log is reported rather than passed -- see `_INSTRUMENT_RULE`. "No
    contradictions were found" and "nobody looked" are the same empty page, and
    the second is the common one: consolidation merges disagreeing claims
    quietly, so the absence of a log is weak evidence of agreement and strong
    evidence of nothing having checked.
    """
    if not params.no_auto_resolve:
        return []
    logs = _select(context, params.type)
    if not logs:
        return [
            (
                f"no {params.type.describe()} is present, so a contradiction "
                "found here and one never looked for read the same",
                (),
                "write the contradiction log, empty and explicit if none were found",
            )
        ]
    results: list[Result] = []
    for log in logs:
        for index, entry in enumerate(_entries(log, params.entries_field)):
            where = entry.get("id", index)
            escalated = not _blank(entry.get(params.escalation_field))
            if escalated:
                continue
            if not _blank(entry.get(params.resolution_field)):
                results.append(
                    (
                        f"contradiction {where} in {log.id} was resolved without a "
                        "named human",
                        (log.id,),
                        f"route {where} to the SME who owns it and record who decided",
                    )
                )
            else:
                results.append(
                    (
                        f"contradiction {where} in {log.id} is neither escalated nor resolved",
                        (log.id,),
                        f"name who adjudicates {where}",
                    )
                )
    return results


# --- the check with no implementation ---------------------------------------


class NoParams(Params):
    pass


REGISTRY["ubd.uncoverage"] = CheckSpec(
    name="ubd.uncoverage",
    params_model=NoParams,
    run=None,
    fixed_severity="human_gate",
    human_gate=(
        "Whether an understanding is genuinely in need of uncovering -- "
        "counter-intuitive, easily mis-taken, central to the discipline -- has "
        "no automatable proxy and no honest model substitute: asked the "
        "question, a model produces fluent platitudes and rates them highly. "
        "A human who knows the discipline must answer it at the gate."
    ),
)
"""UbD's discriminator, registered precisely so that it cannot be quietly skipped.

The alternative designs were both worse. Leaving it out of the registry means a
preset cannot name it and nothing in the run says the judgement is owed. Writing
a model-backed approximation means the standard reports a pass, which is the one
outcome guaranteed to be wrong -- an unfounded pass on the most important
question in UbD Stage 1. So it is here, it has no `run`, and it emits a standing
`human_gate` finding every time it is bound. `human_gates()` lets a UI show it as
what it is rather than as a check that keeps failing.
"""


# --- matrix density ---------------------------------------------------------


class MatrixDensityParams(Params):
    matrix: str
    rows: TypeFilter | None = None
    columns: TypeFilter | None = None
    """The two axes of a relational matrix, as filters over the course.

    Read by `stage_exit.course_matrices`, not by this check: naming the axes in
    the binding is what lets the harness *build* the matrix a binding is about
    before running it. They are optional because an intrinsic matrix (Tyler's
    behaviour x content) is not two artifact types and cannot be built this way;
    such a binding still needs a matrix supplied some other way, and reports
    that it had none if nothing supplies one.
    """
    no_empty_rows: bool = False
    no_empty_columns: bool = False
    max_cell_density: float | None = None


@_register("shared.matrix_density", MatrixDensityParams)
def _matrix_density(context: CheckContext, params: MatrixDensityParams) -> list[Result]:
    """Tyler's grid diagnostics, and the same query read over UbD's and ADDIE's.

    The implementation lives in `coverage.py`, which owns the matrix and its
    two axis kinds; this is the three-line adapter that binds it to a name and
    lets `run_check` apply the binding's severity. Registered *here*, beside
    every other check, because this module is the one place a reader can see
    the whole set -- a registration that fired only because some other module
    remembered to import this one is a check whose existence depends on an
    import nobody can see from either end.

    `matrix` names which of the stage's matrices this binding is about, since a
    stage routinely produces two. Not finding it is a finding rather than a
    pass, on the same reasoning that makes `budget` report an unreadable
    ceiling: a binding pointed at a matrix that was never built has verified
    nothing, and returning `[]` is how a clean grid would look. It is not a
    `MalformedCheck`, because the binding is not malformed -- the parameters are
    well-formed and the matrix is missing at run time, which is a wiring fault
    with a different fix and a different audience.
    """
    matrix = next((m for m in context.matrices if m.matrix_id == params.matrix), None)
    if matrix is None:
        return [
            (
                f"no matrix {params.matrix!r} was built for this stage, so its "
                "density was never checked",
                (),
                f"build {params.matrix!r} at this stage, or drop the binding",
            )
        ]
    return [
        (finding.message, finding.cites, finding.suggested_edit)
        for finding in matrix_density(
            matrix,
            no_empty_rows=params.no_empty_rows,
            no_empty_columns=params.no_empty_columns,
            max_cell_density=params.max_cell_density,
        )
    ]


# --- the methodology-specific checks ----------------------------------------
#
# §4's second table, and its shortness is the finding: three of the five
# genuinely resist generalizing, and only one of those three resists automation
# as well. They live in their own namespaces so that a preset for a fourth
# methodology inherits none of them.


class CriterionDocAuthoredParams(Params):
    doc: str
    require_human_signature: bool = True
    forbid_derivation_from: TypeFilter | None = None
    signature_field: str = "authored_by"


@_register("tyler.criterion_doc_authored", CriterionDocAuthoredParams)
def _criterion_doc_authored(
    context: CheckContext, params: CriterionDocAuthoredParams
) -> list[Result]:
    """The tautology guard: a screen may not derive its criteria from what it screens.

    Tyler's philosophy statement is the only thing standing between a screen and
    fluent agreement with whatever the generator produced, and it only works if
    it comes from somewhere else. A philosophy inferred from the same corpus
    that produced the candidates will approve them at close to 100%, and --
    this is why it needs a mechanical check -- the resulting ledger is
    indistinguishable from a screen that genuinely found the candidates sound.

    Both halves are graph queries. The signature is a field. The derivation test
    is provenance: if the document cites the corpus it is meant to judge, it was
    written from it. That does not catch a human who read the corpus first and
    then wrote a philosophy agreeing with it, and nothing mechanical could; it
    catches the pipeline doing it to itself, which is the failure that scales.

    Scoped by `doc` rather than by type: a preset may carry several criterion
    documents, and only the one a screen actually cites is load-bearing for it.
    """
    documents = [
        artifact
        for artifact in _select(
            context, TypeFilter(artifact_type=ArtifactType.CRITERION_DOCUMENT)
        )
        if params.doc in {artifact.id, artifact.subtype, artifact.fields.get("name")}
    ]
    if not documents:
        return [
            (
                f"no CriterionDocument named {params.doc!r} is present, so the "
                "screen has nothing authored to cite",
                (),
                f"author {params.doc!r} before running the screen; a screen "
                "without one degrades into generic plausibility",
            )
        ]
    results: list[Result] = []
    for document in documents:
        if params.require_human_signature and _blank(
            document.fields.get(params.signature_field)
        ):
            results.append(
                (
                    f"{document.id} carries no {params.signature_field}: nobody "
                    "has put their name to the criteria this screen applies",
                    (document.id,),
                    f"record who authored {document.id}; an unsigned criterion "
                    "document is one nobody can be asked to defend",
                )
            )
        if params.forbid_derivation_from is not None:
            forbidden = {item.id for item in _select(context, params.forbid_derivation_from)}
            cited = {
                str(entry.get("source_id"))
                for entry in document.provenance
                if entry.get("source_id")
            }
            overlap = sorted(cited & forbidden) or sorted(
                _adjacent(context, document.id) & forbidden
            )
            if overlap:
                results.append(
                    (
                        f"{document.id} is derived from "
                        f"{params.forbid_derivation_from.describe()} "
                        f"({', '.join(overlap)}), which is what it exists to judge",
                        (document.id, *overlap),
                        "author the criteria independently of the corpus that "
                        "produced the candidates, or the screen is a tautology",
                    )
                )
    return results


class ChangeScopeParams(Params):
    maturity: str
    permitted: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@_register("addie.change_scope", ChangeScopeParams)
def _change_scope(context: CheckContext, params: ChangeScopeParams) -> list[Result]:
    """What may still be changed at this rung, checked against the ladder itself.

    ADDIE's maturity ladder earns its keep by *forbidding* substantive change
    late, and that discipline is exactly what automation erodes: re-running a
    generator is cheap, so "just regenerate it" is always available and always
    destroys the mechanism. The check is a query over the preset's own gate --
    the rung named by `maturity` must exist and must permit and forbid what the
    binding says it does.

    In a preset with no maturity ladder the honest answer is that the check is
    meaningless, and it says so rather than passing. §4 is explicit that
    `change_scope` only means anything against a ladder, so a binding on a stage
    without one is a preset error; reporting it as a pass would hide that a
    stage everyone believes is scope-limited is not limited at all.
    """
    gate = getattr(context.stage, "gate", None)
    rungs = getattr(gate, "rungs", None)
    if not rungs:
        return [
            (
                f"{getattr(context.stage, 'id', 'this stage')} has no maturity "
                f"ladder, so a change_scope binding for {params.maturity!r} "
                "constrains nothing",
                (),
                "bind change_scope only on a stage behind a MaturityGate",
            )
        ]
    rung = next((candidate for candidate in rungs if candidate.name == params.maturity), None)
    if rung is None:
        available = ", ".join(candidate.name for candidate in rungs)
        return [
            (
                f"no rung named {params.maturity!r} on this ladder ({available})",
                (),
                f"name a rung that exists, or add {params.maturity!r} to the gate",
            )
        ]
    results: list[Result] = []
    missing = [change for change in params.permitted if change not in rung.permitted_change]
    if missing:
        results.append(
            (
                f"rung {rung.name!r} does not permit {', '.join(missing)}, which "
                "this binding says it should",
                (),
                "reconcile the gate's permitted_change with the binding",
            )
        )
    allowed = [change for change in params.forbidden if change in rung.permitted_change]
    if allowed:
        results.append(
            (
                f"rung {rung.name!r} permits {', '.join(allowed)}, which this "
                "binding forbids: late change is not actually constrained here",
                (),
                f"remove {', '.join(allowed)} from the rung's permitted_change",
            )
        )
    return results


class ExpertGapParams(Params):
    quote_span_required: bool = True


REGISTRY["addie.expert_gap_flag"] = CheckSpec(
    name="addie.expert_gap_flag",
    params_model=ExpertGapParams,
    run=None,
    fixed_severity="critic_gate",
    critic_gate=(
        "Finding where an expert stopped explaining -- an unstated decision "
        "criterion, an abrupt jump to abstraction, a term used as though it "
        "were shared -- is a judgement about prose, not a property of the "
        "graph. It is the highest-value model-based check in the comparison "
        "and it must be a critic pass over the source with the quoted span "
        "attached, so a reviewer can see what provoked each flag."
    ),
)
"""ADDIE's expert-gap detector, registered as owed to a critic rather than faked here.

The tempting implementation is a keyword heuristic -- jargon lists, sentence
length, discourse markers -- and it would be worse than nothing. Expert gaps
are precisely the places where the prose reads smoothly, because the expert did
not notice the step they skipped; a proxy that fires on rough prose finds the
opposite of the target and reports a clean pass on the real thing.

So this is a `critic_gate` rather than a `human_gate`: unlike `uncoverage`, the
question is answerable by a model, just not by a graph query. Keeping the two
categories apart is what stops "the model must do it" and "no one can do it
automatically" from being triaged as the same problem.
"""
