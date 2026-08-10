"""Turning a `prompt_ref` into the text a stage runs under.

The presets carry 38 distinct `prompt_ref` strings and resolve none of them:
`composition.py` builds a stage's instructions out of artifact paths, the gate
explanation and widget syntax, all of which are mechanical. The
instructional-design intelligence of the system exists only as post-hoc
rejection in `checks.py`. This module is the half that puts the methodology in
front of the model instead of behind it.

**What is here and what is deliberately not.** The file format, the loader,
the resolver, and the validation that a preset's refs all resolve. Not the
prompts -- those are weeks of instructional-design writing, not a coding task
-- and not the composition wiring, which cannot be exercised until enough of
them exist that a preset resolves end to end. `unresolved()` is the function
the composition root will call; it is written and tested and has no caller
yet, which is stated here rather than left for someone to discover.

**A prompt is a markdown file with frontmatter**, for the reason artifacts are:
`artifacts.parse_frontmatter` already exists, the viewer already renders it,
and a second format would be a second thing to maintain.

    prompts/ubd/stage1_generate.md

    ---
    prompt_ref: prompts/ubd/stage1_generate
    version: 1
    kind: generator
    methodology: ubd
    intended_for:
      - ubd.pure/ubd.stage1.desired_results
    summary: >
      Desired results -- transfer goals, understandings, essential questions.
    ---

    You are a curriculum designer working the first stage of ...

`prompt_ref` restating its own path is the whole of the integrity check: a file
moved without its frontmatter following it is caught at load rather than by a
run that silently resolves the wrong text, or by a ref that silently resolves
nothing.

`kind` is enforced against the field that referenced it, and it is the only
defence against a particular way the self-review invariant is evaded.
`checks.py:1110` compares the two `prompt_ref` *strings*; two distinct refs
whose files hold the same critic prompt differ as strings and are the same
prompt in fact. That check would pass and the critic would be reviewing its own
argument.

`intended_for` is documentation for a human and an assertion for a test. It is
**not** consulted at resolution time: the preset that references a prompt is
the authority on what that prompt is for, and a second gate that could disagree
eventually would.

`role` is not in the frontmatter. It is on the `Generator`, and it belongs
there -- `prompts/ubd/stage2_generate` is used by two presets under different
role strings, a difference the hybrid makes deliberately and a prompt file has
no business overriding. `role_line` composes them; the file contains neither.

**A prompt must not name its output paths, its artifact types, its
frontmatter, the gate, the current stage, its tools, or widget syntax.** All
seven are already injected by something that derives them from the stage
declaration, and a prompt that repeats them is worse than one that omits them:
it is the copy that goes stale. This module cannot enforce that -- it is a
property of the prose -- and saying so here is the only place it gets said next
to the loader.

**Versions.** There is no per-prompt pin. The preset's version covers its
prompts: editing any prompt a preset references is editing that preset. A pin
would buy precision nothing consumes and cost a class of failure the system
does not have -- a pin pointing at a version no longer on disk is a run that
cannot start, which is exactly the strand-mid-flight failure
`composition.py`'s version-mismatch tolerance was written to avoid. `version`
in the frontmatter is for a human reading the file's history; nothing resolves
on it, and `resolve` refuses a `ref@n` outright so that inventing a pinning
scheme fails as itself rather than as a missing file.

`prompt_digest` is what makes that discipline honest: a short hash over the
exact resolved text, recordable on an artifact, so "which revision of the
workflow produced this file" is answerable even when somebody edited a prompt
and forgot to bump the preset. That is the case that will actually happen.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Literal, Protocol

from research_team.application.artifacts import parse_frontmatter
from research_team.domain.workflow import Generator, Preset, StageBase

Kind = Literal["generator", "critic"]

PROMPT_SUFFIX = ".md"

_REQUIRED_FIELDS = ("prompt_ref", "version", "kind", "methodology", "summary")

ALLOWED_CROSS_STAGE_REFS = frozenset(
    {
        # One stage under two names. ADDIE's analysis phase opens with gap
        # framing; the hybrid renamed the step and kept the work, so the two
        # ids differ and the prompt is legitimately one prompt.
        #
        # It is also the sharpest instance of the hazard the sharing rule
        # otherwise avoids: the two stages declare materially different
        # artifact sets -- `hybrid.step1.framing` emits `ContextProfile` and
        # `ConstraintRegister` because the hybrid has no separate audience
        # stage, while `addie.a1.intake_gap_framing` emits `SourceClaim`,
        # `ContestedQueue` and `OpenQuestion` and defers the profile. Nothing
        # here can catch a prompt that names a deliverable; only the discipline
        # of teaching the method can.
        "prompts/addie/gap_framing",
        "prompts/addie/gap_critique",
    }
)
"""Refs bound to stages whose ids differ, and which are nonetheless one prompt.

The rule is: share a prompt when two presets reference the same *stage id*,
never otherwise. That is mechanical, checkable, and reproduces the eleven
reuses already in the shipped data. What it guards is expensive: four stages
across the three presets produce `Intent` under four prompts and look like one
stage. Collapsing them would make each methodology emit another's output while
every structural check still passed -- the checks are graph queries over
`Intent` and the collapse does not change the graph.
"""


class PromptError(Exception):
    """A prompt library that cannot be trusted, at load or at resolution.

    Deliberately not a value a caller can carry on past. The tempting
    alternative -- resolve to empty and continue -- is the one failure mode
    nobody can see: an ungated run is visibly ungated, but a stage running with
    an empty prompt is indistinguishable from the system before prompts
    existed, and produces methodology-free output that passes every structural
    check.
    """


@dataclass(frozen=True)
class Prompt:
    """One prompt file, parsed and validated."""

    ref: str
    version: int
    kind: Kind
    methodology: str
    summary: str
    intended_for: tuple[str, ...]
    body: str


class PromptLibrary(Protocol):
    """What a stage needs: text, for a ref, of a stated kind."""

    def resolve(self, ref: str, *, kind: Kind) -> str: ...


def _ref_for(root: Path, path: Path) -> str:
    """The ref a file's location spells.

    Includes the root directory's own name, so a library rooted at `prompts/`
    yields `prompts/ubd/stage1_generate` -- which is what the presets already
    say. The loader is not the place to hold a second opinion about that.
    """
    return f"{root.name}/{path.relative_to(root).with_suffix('').as_posix()}"


def parse_prompt(ref: str, text: str) -> Prompt:
    """One file's frontmatter and body, or `PromptError` saying which file.

    Unlike `artifacts.parse_frontmatter`, which reports and never raises
    because a run that produced one malformed artifact should still hand back
    the other twenty, a malformed *prompt* is a broken installation. There is
    no useful partial answer: the stage either runs under its methodology or it
    does not.
    """
    front, body = parse_frontmatter(text)
    if front is None:
        raise PromptError(f"{ref}: no frontmatter block, or one that is not a mapping")
    missing = [field for field in _REQUIRED_FIELDS if field not in front]
    if missing:
        raise PromptError(f"{ref}: frontmatter is missing {', '.join(missing)}")
    declared = front["prompt_ref"]
    if declared != ref:
        raise PromptError(
            f"{ref}: frontmatter says prompt_ref {declared!r}. A prompt states its own "
            "path so that a file moved without its frontmatter is caught here rather "
            "than by a stage resolving the wrong text."
        )
    kind = front["kind"]
    if kind not in ("generator", "critic"):
        raise PromptError(f"{ref}: kind is {kind!r}, which is neither generator nor critic")
    if not body.strip():
        raise PromptError(
            f"{ref}: body is empty. An empty prompt resolves to the behaviour the "
            "system had before prompts existed, which is the one failure that is "
            "invisible in the output."
        )
    intended = front.get("intended_for") or ()
    if not isinstance(intended, list | tuple):
        raise PromptError(f"{ref}: intended_for is not a list")
    return Prompt(
        ref=ref,
        version=int(front["version"]),
        kind=kind,
        methodology=str(front["methodology"]),
        summary=str(front["summary"]),
        intended_for=tuple(str(entry) for entry in intended),
        body=body.strip(),
    )


def load_prompts(root: Path) -> Mapping[str, Prompt]:
    """Every prompt under `root`, keyed by ref, all of them validated.

    Raises on the first malformed file rather than collecting problems, which
    is the opposite of `problems()` for presets and is right for a different
    reason: a preset's problems are all visible in one module a person is
    editing, while a prompt library is a directory tree whose files were
    written at different times, and a list of forty errors from a tree is less
    useful than the first one with its path.
    """
    if not root.is_dir():
        raise PromptError(f"no prompt directory at {root}")
    loaded: dict[str, Prompt] = {}
    for path in sorted(root.rglob(f"*{PROMPT_SUFFIX}")):
        if not path.is_file():
            continue
        ref = _ref_for(root, path)
        loaded[ref] = parse_prompt(ref, path.read_text())
    return loaded


@dataclass(frozen=True)
class DirectoryPromptLibrary:
    """Prompts on disk, validated once at load and re-read at every resolution.

    The two halves answer different questions and the split is deliberate.

    **Validated at load** so that a missing or malformed prompt is a startup
    failure, the way `problems()` validates presets at import rather than at
    selection. A broken installation should be learned about before a run, not
    an hour into one.

    **Re-read at resolution** so that an edit lands on the next turn. This is a
    departure from a strictly frozen mapping and it is the mid-run behaviour
    that matters: the run in front of you is how you discover a prompt is
    wrong, and a prompt frozen for the duration of a stage would mean the fix
    you just made does not apply to the run you made it for. It is also the
    behaviour a preset edit already has, and the behaviour `AutonomyPolicy`
    already has.

    The cost is a file read per stage turn, which is nothing beside the model
    call it precedes, and one real hazard: a prompt can vanish under a live
    run. `resolve` raises in that case rather than serving the text it loaded
    with, because held text would hide the deletion until the next restart --
    the strand-later failure, arriving later and with less context.

    A stage already advanced is settled regardless: its artifact carries the
    digest of the prompt that wrote it, which is what `prompt_digest` is for.
    """

    root: Path
    at_load: Mapping[str, Prompt]

    @classmethod
    def load(cls, root: Path) -> "DirectoryPromptLibrary":
        return cls(root=root, at_load=load_prompts(root))

    def prompt(self, ref: str, *, kind: Kind) -> Prompt:
        if "@" in ref:
            raise PromptError(
                f"{ref!r} carries a version pin. Prompts are not independently "
                "versioned: the preset's version covers its prompts, and a pin at a "
                "version no longer on disk is a run that cannot start."
            )
        # Round-tripped through `_ref_for` rather than trusted: a ref carrying
        # `..`, an absolute path, or a first segment that is not this root's
        # name would otherwise reach outside the library, and the check that
        # catches it is the same one that makes a ref and its path agree.
        # `resolve()` on the join so that `..` is collapsed before comparing.
        path = (self.root / f"{ref.split('/', 1)[-1]}{PROMPT_SUFFIX}").resolve()
        try:
            spelled = _ref_for(self.root.resolve(), path)
        except ValueError:
            spelled = None
        if spelled != ref or not path.is_file():
            raise PromptError(
                f"no prompt file for {ref!r} under {self.root}. There is no fallback: "
                "a stage running without its methodology produces output that passes "
                "every structural check and is wrong in the one way nobody can see."
            )
        found = parse_prompt(ref, path.read_text())
        if found.kind != kind:
            raise PromptError(
                f"{ref!r} is referenced as a {kind} and its kind is {found.kind!r}"
            )
        return found

    def resolve(self, ref: str, *, kind: Kind) -> str:
        return self.prompt(ref, kind=kind).body


def prompt_digest(text: str) -> str:
    """A short hash over the exact text a stage ran under.

    Over the resolved body rather than the whole file, so it moves when what
    the model read changed and stays put when `summary` was reworded. Recorded
    on an artifact, it answers "which revision of the workflow produced this"
    even when a prompt was edited and the preset version was not -- which is
    the case that will actually happen, because the version bump is a
    discipline and a discipline nobody can check is a wish.

    Twelve hex characters: enough that a collision within one course is not a
    thing to think about, short enough to sit in frontmatter a person reads.
    Not cryptographic; nothing here defends against a forged digest.
    """
    return blake2b(text.encode(), digest_size=6).hexdigest()


def referenced_prompts(preset: Preset) -> tuple[tuple[str, Kind, str], ...]:
    """`(stage_id, kind, ref)` for every prompt this preset needs, in stage order.

    A `ScreenStage` has no generator by construction, so it contributes only
    its critic. A `FieldStage` has neither and contributes nothing -- its
    evidence comes from people outside the pipeline, so no agent executes it
    and demanding a prompt for one would make that unrepresentable.
    """
    found: list[tuple[str, Kind, str]] = []
    for stage in preset.stages:
        generator = getattr(stage, "generator", None)
        if generator is not None:
            found.append((stage.id, "generator", generator.prompt_ref))
        critic = getattr(stage, "critic", None)
        if critic is not None:
            found.append((stage.id, "critic", critic.prompt_ref))
    return tuple(found)


def unresolved(preset: Preset, library: PromptLibrary) -> list[str]:
    """Everything about this preset's prompts that would fail at run time, now.

    Written for a composition root that refuses to build rather than for a
    caller that inspects the result: the reason to collect rather than raise on
    the first is that "one prompt is missing" is not actionable across 38 refs,
    and the whole list is a work item. Each line names the stage, the field and
    the ref, which is what turns it into an edit.

    Has no caller yet. It becomes one line in `composition.py` once a preset's
    prompts exist to resolve; wiring it before that would refuse to build for
    every preset shipped today.
    """
    problems: list[str] = []
    for stage_id, kind, ref in referenced_prompts(preset):
        try:
            library.resolve(ref, kind=kind)
        except PromptError as error:
            problems.append(f"{preset.id}/{stage_id} {kind} {ref}: {error}")
    return problems


def orphaned_refs(
    presets: Iterable[Preset], library: DirectoryPromptLibrary
) -> tuple[str, ...]:
    """Prompt files no preset names.

    An unreferenced prompt is either a preset edit that lost its stage or a
    prompt written against a stage that was since renamed. Both look like
    nothing: the file is there, it is well formed, and no run will ever read
    it.
    """
    referenced = {ref for preset in presets for _, _, ref in referenced_prompts(preset)}
    return tuple(sorted(set(library.at_load) - referenced))


def shared_ref_problems(
    presets: Iterable[Preset], allowlist: frozenset[str] = ALLOWED_CROSS_STAGE_REFS
) -> tuple[str, ...]:
    """Refs bound to two stages with different ids and not allowlisted.

    The unit of sharing is a *stage*, not a piece of instructional work that
    resembles another piece. When the hybrid takes ADDIE's storyboarding stage
    it names `addie.d5.storyboarding` and reuses it, and one prompt is right
    because there is one stage. Nine of the eleven reuses in the shipped data
    are exactly that shape.

    The failure this refuses is not a crash. A shared "objectives" prompt
    across UbD, ADDIE and Tyler would produce a course that is internally
    consistent, passes its gates, and is not the methodology the user selected
    -- because the structural checks are graph queries over `Intent` and cannot
    see which tradition wrote it.
    """
    bound: dict[str, set[str]] = {}
    for preset in presets:
        for stage_id, _, ref in referenced_prompts(preset):
            bound.setdefault(ref, set()).add(stage_id)
    return tuple(
        f"{ref} is bound to {len(ids)} stages with different ids: {', '.join(sorted(ids))}"
        for ref, ids in sorted(bound.items())
        if len(ids) > 1 and ref not in allowlist
    )


def intended_for_disagreements(
    presets: Iterable[Preset], library: DirectoryPromptLibrary
) -> tuple[str, ...]:
    """Where a prompt's `intended_for` and the presets do not agree, both ways.

    A redundant declaration whose only job is to disagree, exactly like
    `FieldGate.gates_promotion_from` -- naming the binding in two places gives
    the two facts something to disagree about. A prompt written for UbD Stage 1
    and quietly referenced by an ADDIE stage is the expensive mistake, and this
    is where it surfaces.

    Not consulted at resolution time. This is a test, not a gate.
    """
    actual: dict[str, set[str]] = {}
    for preset in presets:
        for stage_id, _, ref in referenced_prompts(preset):
            actual.setdefault(ref, set()).add(f"{preset.id}/{stage_id}")
    problems: list[str] = []
    for ref, prompt in sorted(library.at_load.items()):
        declared = set(prompt.intended_for)
        bound = actual.get(ref, set())
        for entry in sorted(declared - bound):
            problems.append(f"{ref} claims {entry}, which does not reference it")
        for entry in sorted(bound - declared):
            problems.append(f"{ref} is referenced by {entry}, which it does not claim")
    return tuple(problems)


def role_line(generator: Generator) -> str:
    """The three `Generator` fields nothing has ever read, rendered for the model.

    `taxonomy_binding` is the one that matters. `blooms_revised` and
    `six_facets` are named-never-unioned because they are incompatible -- one
    is a hierarchy and the other is explicitly not -- so a stage that does not
    say which it is working under gets whichever the model prefers, and a check
    written against one is meaningless against the other.

    `over_generate_factor` is stated as a target because the stages that carry
    it are *meant* to produce several times what survives: a `prune_ratio`
    check expecting 0.15-0.4 survival has nothing to measure against a stage
    that generated exactly what it kept.

    Omits what the generator did not declare rather than saying "none". A model
    told its taxonomy binding is absent has been given a fact it cannot use and
    a sentence it must read.
    """
    lines = [f"You are working as: {generator.role}."]
    if generator.taxonomy_binding is not None:
        lines.append(
            f"Classify under the {generator.taxonomy_binding} taxonomy, and no other. "
            "The taxonomies in this system are named and never combined; work in a "
            "second one is not richer, it is unclassifiable."
        )
    if generator.over_generate_factor is not None:
        lines.append(
            f"Generate roughly {generator.over_generate_factor}x what you expect to "
            "survive. Most of these are meant to be discarded downstream, and a pool "
            "sized to what you would keep defeats the screen that follows."
        )
    return "\n\n".join(lines)


def stage_prompt(stage: StageBase, library: PromptLibrary) -> str:
    """The methodology text this stage runs under, with its role framing.

    The generator's prompt where there is a generator; a `ScreenStage` has none
    by construction and runs under its critic's. A `FieldStage` has neither and
    resolves nothing -- an agent cannot execute it at all -- and gets the empty
    string rather than a raise, because "this stage has no prompt" is a
    property of the stage rather than a fault in the library.

    Returned as the first term of the instruction block, before the artifact
    paths and the gate explanation, so that what the stage is *for* precedes
    the mechanics of where it writes.
    """
    generator = getattr(stage, "generator", None)
    if generator is not None:
        text = library.resolve(generator.prompt_ref, kind="generator")
        return f"{text}\n\n{role_line(generator)}"
    critic = getattr(stage, "critic", None)
    if critic is not None:
        return library.resolve(critic.prompt_ref, kind="critic")
    return ""
