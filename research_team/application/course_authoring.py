"""Turning one learning area into a unit and its lessons, by Understanding by Design.

`workflows/ubd.py` encodes UbD's three-stage shape and **terminates at a unit
plan**, deliberately: "UbD has no production or delivery half at all… it
assumes a teacher who will do the producing." This module is that teacher, and
going past Stage 3 into materials is a departure from the preset recorded here
rather than smuggled into it. The preset is untouched; nothing below reads it.

**Backward design is enforced by sequencing, not by asking for it.** Three
turns run in order, and each is given only what the stages before it produced:
desired results, then evidence *given the results*, then the learning plan
*given both*. A model asked for all three at once writes the lessons first and
reverse-engineers understandings to match them -- fluently, and with every
section present, so the output is indistinguishable from the real thing by
inspection. That is the precise failure UbD exists to prevent, and three calls
rather than one is what it costs to actually prevent it rather than to request
it politely.

**Every turn runs against a project the agent has joined**, so its graph and
corpus tools are bound and a lesson can quote the material it is teaching.
That is the payoff of clustering the graph rather than a vector space: the
area carries entity ids, the prompts hand those ids to the model, and the
components it writes resolve against the same project.
"""

import textwrap
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from research_team.application.authoring_checkpoints import (
    AREAS_DIR,
    lesson_paths,
    review_path,
    unit_path,
)
from research_team.application.components import REGISTRY
from research_team.application.session_service import SessionService
from research_team.domain import SessionPurpose
from research_team.domain.learning_area import LearningArea, LearningPath
from research_team.infrastructure.agent.authoring_subagents import (
    AUTHORING_DISPATCH_PROMPT,
)

#: How many of an area's anchors are named in a prompt.
#:
#: A ceiling on prompt size, and also on ambition: an area with sixty members
#: does not become a better unit by having all sixty listed, it becomes a unit
#: with no focus. The anchors are ranked by centrality *within the area*, so
#: the twelve named are the twelve the graph says the area is actually about.
PROMPT_ANCHORS = 12

#: `AREAS_DIR` is imported above, not defined here: `authored_files.py` and
#: anything else already resolving it from this module still can, but the
#: definition and its docstring now live in `authoring_checkpoints.py`,
#: because that module's checkpoints need the constant and cannot import it
#: from here -- a later task makes this module import `authoring_checkpoints`
#: for those checkpoints, and a mutual import is a circular one. Moving the
#: constant rather than duplicating it matters because CLAUDE.md already
#: records `AREAS_DIR` on its third independent copy (`course_authoring.py`,
#: `export.py`, `frontend/src/presentation/curriculum/course-paths.ts`) -- a
#: fourth definition here would be exactly that failure again, so this name
#: is an alias, not a value.

PATHS_DIR = "/course/paths"


class TurnRunner(Protocol):
    """The slice of `TurnSupervisor` an authoring turn needs."""

    async def run(self, session_id: UUID, user_input: str) -> object: ...


@dataclass(frozen=True)
class AuthoredCourse:
    """What one area's authoring run produced, and where.

    No file *contents* here, and no list of what was actually written. Both
    are reads of the session workspace, which the file routes already answer,
    and a second account of them assembled here would be the one a UI used and
    the one that went stale. What this carries is the session id, which is the
    only thing a caller cannot derive.
    """

    area_slug: str
    project_id: UUID
    session_id: UUID
    run_id: UUID
    replies: tuple[str, ...]


def _anchor_lines(area: LearningArea) -> str:
    """The area's anchors, with the entity ids the components need.

    Ids are given to the model rather than withheld because six of the ten
    component types resolve against this project's graph, and a `definition`
    or `graph` block without an entity id is a widget that renders
    `unavailable` forever. The alternative -- letting the model write names and
    resolving them here -- reintroduces exactly the name-matching problem
    consolidation exists to solve, at a layer with none of its evidence.
    """
    return "\n".join(
        f"- {m.name} ({m.entity_type}, id `{m.entity_id}`"
        + (f", {m.temporal}" if m.temporal else "")
        + ")"
        for m in area.anchors[:PROMPT_ANCHORS]
    )


def _area_header(area: LearningArea) -> str:
    return (
        f"Learning area: {area.display_name()}\n"
        f"Slug: `{area.slug}`  ({area.size} entities in this area)\n\n"
        f"Its central entities, most connected first:\n{_anchor_lines(area)}\n"
    )


_COMPONENT_GUIDE_TEMPLATE = """\
Lessons may carry interactive components. A component is a fenced block whose
info string names its type, and its body is YAML:

    ```component:mcq
    id: actium-1
    prompt: What did the battle of Actium decide?
    options:
      - text: "The succession to Julius Caesar"
        correct: true
        feedback: "Yes -- it ended the last rival claim."
      - text: "The boundary of the Rhine frontier"
        correct: false
    rationale: |
      Actium removed Antony, leaving one claimant.
    ```

Available types: `mcq`, `cloze`, `flashcards`, `checklist` (authored outright),
and `definition`, `evidence`, `graph`, `timeline`, `explorer`, `compare`
(which resolve against this project -- give them entity ids from the list
above and they fetch the real material).

Two rules, and the first is the one that gets broken:

- **`id` must be unique within the file** and stable. It is the key an
  attempt is recorded against, so changing it discards a learner's history on
  that item.
- A resolved component takes **entity ids copied exactly** from the list you
  were given. An id you invented renders as unavailable, and nothing warns you.

Where the id goes, and it is not the same field everywhere:

{id_fields}

An id in a field that expects a name is drawn to the reader as a raw
`9f2c1a44-...`, because the lookup is a name search and nothing is named by
its own id.
"""


def _id_field_lines() -> str:
    """Which types take an `entity_id`, derived from the registry rather than typed.

    This paragraph is the whole of defect 1: the guide named neither `entity:`
    nor `entity_id:`, so a model told to copy ids exactly put them wherever an
    entity-ish field was -- into `compare.entities`, which has no id field at
    all and renders straight to the reader.

    Generated for the reason `component_reference()` is generated: a
    hand-written sentence about the schema stops being true two edits later and
    nothing says so. `test_the_guide_names_the_id_field_of_every_type_that_has_one`
    is the second half of that guarantee, and would fail if this were a literal
    that someone stopped maintaining.

    `component_reference()` itself is deliberately *not* used here. It is the
    full field schema for every type, it runs to hundreds of lines, and this
    turn is already carrying two prior stages verbatim -- what is missing is
    two field names, not a second copy of the reference.
    """
    named = sorted(name for name, spec in REGISTRY.items() if "entity_id" in spec.fields)
    # `evidence` is in neither list and that is not an oversight: it resolves
    # against *source* ids, which the prompt hands over separately, so telling
    # this turn it takes no entity id would be true and useless.
    nameless = sorted(
        name
        for name, spec in REGISTRY.items()
        if spec.resolved and not {"entity_id", "sources"} & set(spec.fields)
    )
    types = ", ".join(f"`{name}`" for name in named)
    others = ", ".join(f"`{name}`" for name in nameless)
    return "\n".join(
        textwrap.fill(text, width=76, initial_indent="- ", subsequent_indent="  ")
        for text in (
            f"{types} take **two** fields: `entity:` is the name, spelled as "
            f"the sources spell it, and `entity_id:` is the id, copied "
            f"exactly. Write both.",
            f"{others} take **no id at all**. There is no field for one. "
            f"Where they name entities -- `compare`'s `entities:` -- write "
            f"the names.",
        )
    )


COMPONENT_GUIDE = _COMPONENT_GUIDE_TEMPLATE.format(id_fields=_id_field_lines())


def desired_results_prompt(area: LearningArea, subject: str) -> str:
    """UbD Stage 1, and the only turn with no prior stage to be faithful to.

    It is given the anchors and told to work from the project's own material
    rather than from what it knows about the subject generally. The
    distinction is not pedantic: a model asked for enduring understandings
    about Rome writes excellent ones about Rome, none of which the corpus
    supports, and the resulting unit assesses things the project cannot teach.
    """
    return (
        f"You are designing a unit by Understanding by Design, Stage 1 only.\n\n"
        f"Project subject: {subject}\n\n"
        f"{_area_header(area)}\n"
        f"These entities were clustered together by this project's own knowledge "
        f"graph, so they are what the corpus actually connects -- not a topic "
        f"chosen for you. Read the material with your graph and corpus tools "
        f"before writing.\n\n"
        f"Write `{AREAS_DIR}/{area.slug}/unit.md` containing **Stage 1 only**:\n"
        f"- A title for the area, and two or three sentences on what it is.\n"
        f"- 2-4 **enduring understandings**: full sentences stating what a "
        f"learner should still understand in a year. Not topics.\n"
        f"- 3-5 **essential questions**: open, arguable, not answerable by "
        f"recall.\n"
        f"- **Knowledge** and **Skills** as two separate lists.\n\n"
        f"Do not write assessments and do not write lessons. A later turn does "
        f"each, and it will be given what you write here. Anything you add now "
        f"is work that turn will contradict.\n\n"
        f"Ground every understanding in the corpus. Where a claim rests on a "
        f"source, cite it.\n\n"
        f"Then dispatch `unit-critic` **once**, giving it "
        f"`{unit_path(area.slug)}` by path and naming the corpus the unit was "
        f"built from. It judges each enduring understanding on three counts: "
        f"arguable, central, corpus-supported. Revise `unit.md` yourself from "
        f"what it returns -- it writes nothing.\n\n"
        f"Revise once and stop. A second round makes the understandings "
        f"blander, not truer: the first pass removes the ones the corpus "
        f"cannot carry, which is the whole win, and every pass after it is "
        f"answering objections by hedging. An understanding nobody can "
        f"disagree with survives any number of critics and teaches nothing."
        + AUTHORING_DISPATCH_PROMPT
    )


def evidence_prompt(area: LearningArea, stage_one: str) -> str:
    """UbD Stage 2, given Stage 1 and nothing later.

    The turn that makes backward design real. It is handed the understandings
    verbatim rather than told to re-read the file, because the whole point is
    that the assessments are designed *from* them -- and a turn that has to go
    and find them will sometimes not, and will then write assessments from the
    area's entity list instead, which is forward design with the file names of
    backward design.
    """
    return (
        f"Understanding by Design, Stage 2, for the area `{area.slug}`.\n\n"
        f"Stage 1 produced this:\n\n---\n{stage_one}\n---\n\n"
        f"Design the evidence that would show a learner has reached those "
        f"understandings. **Work from the understandings, not from the topic.** "
        f"For each enduring understanding, say what a learner who had it could "
        f"do that one who had merely memorised the material could not.\n\n"
        f"Append to `{AREAS_DIR}/{area.slug}/unit.md` a `## Stage 2 — Evidence` "
        f"section holding:\n"
        f"- One **performance task** per enduring understanding: a paragraph "
        f"describing what the learner produces and what would make it good.\n"
        f"- A set of **check-for-understanding items** as components: at least "
        f"one `mcq` and one `cloze` per understanding, and a `flashcards` deck "
        f"over the vocabulary a learner needs.\n\n"
        f"{COMPONENT_GUIDE}\n"
        f"Every item must be answerable from this project's corpus. An item "
        f"whose answer is general knowledge is testing the model, not the "
        f"course."
    )


def learning_plan_prompt(area: LearningArea, stage_one: str, lesson_count: int) -> str:
    """UbD Stage 3: plan the unit, then fan out to draft it.

    Lessons are separate files rather than sections of `unit.md` because a
    lesson is the thing a person reads *one of*, and because the file routes
    and `LessonDocument` already render a markdown file with components in it.
    One long unit file would render identically and be unnavigable.

    **Four acts in a fixed order, and each act says why it is where it is.**
    An order given without a reason is an order a model reorders: told to plan,
    hunt, draft and critique, it starts drafting, because drafting is the thing
    it is confident about and the plan looks like preamble. The reasons are
    therefore in the prompt text rather than in this docstring, which the model
    never sees. `test_the_learning_plan_prompt_says_why_the_plan_comes_first`
    fails if the reason is trimmed while the sequence is left standing -- which
    is the edit that looks harmless.

    What this cannot do: nothing here forces the acts to actually run in order,
    and `authoring_checkpoints` only sees the files at the end. A turn that
    drafted first and wrote a plan afterwards leaves output this module cannot
    distinguish from the real thing.
    """
    paths = lesson_paths(area.slug, lesson_count)
    return (
        f"Understanding by Design, Stage 3, for the area `{area.slug}`.\n\n"
        f"Stage 1 produced this:\n\n---\n{stage_one}\n---\n\n"
        f"Read the `## Stage 2 — Evidence` section of "
        f"`{unit_path(area.slug)}` before you begin. **Every lesson must build "
        f"toward a specific assessment there.**\n\n"
        f"You are writing {lesson_count} lessons:\n"
        + "\n".join(f"- `{path}`" for path in paths)
        + f"\n\nDo this in four acts, in this order. The order is the whole "
        f"design of this phase; read the reason under each act before you "
        f"decide it does not apply to you.\n\n"
        f"**Act 1 — write the plan, in your reply, before you dispatch "
        f"anything.** One slot per lesson, in teaching order, each carrying:\n"
        f"- its title;\n"
        f"- its `builds_toward`: the Stage 2 assessment it serves, named;\n"
        f"- the single **claim** it owns -- one sentence, and no other lesson "
        f"owns it;\n"
        f"- its **opening move**: what the first paragraph does;\n"
        f"- what it may **assume** the reader already has from earlier lessons.\n"
        f"Fix the **voice** of the unit here too, in one sentence, and give it "
        f"to every drafter.\n\n"
        f"Why first: in Act 3 you dispatch {lesson_count} drafters at once, and "
        f"they cannot see each other or this conversation. Every decision this "
        f"plan leaves open gets answered {lesson_count} times, differently, and "
        f"the unit then reads like {lesson_count} people wrote it -- because "
        f"{lesson_count} did. Three drafters given an open question answer it "
        f"three ways. The plan is the only place a shared decision can be made "
        f"once.\n\n"
        f"**Act 2 — dispatch `anecdote-hunter`, then assign what it returns.** "
        f"Give it the enduring understandings and name the corpus. Each find it "
        f"returns goes to **exactly one** slot; two lessons opening on the same "
        f"incident is the reader meeting it twice as if new.\n\n"
        f"It **may return nothing**, and nothing is a complete answer -- do not "
        f"send it back to look harder. A slot with no anecdote opens on a "
        f"surprising number or on two sources that disagree, both of which are "
        f"in the corpus if the incident is not. **Never invent drama.** An "
        f"invented stake reads as false to a reader who knows the material and "
        f"discredits the lesson around it, which is a worse outcome than a flat "
        f"opening.\n\n"
        f"Why before drafting: an anecdote found after a lesson is written can "
        f"only be pasted on top of it, where it is decoration. Found first, it "
        f"is what the lesson opens on and the claim is argued from.\n\n"
        f"**Act 3 — dispatch one `lesson-drafter` per slot, in parallel.** Give "
        f"each one its own path, its slot verbatim, the anecdotes you assigned "
        f"it, the unit's voice, and the enduring understandings. Give it "
        f"**nothing else** -- not the other slots, not the other lessons. A "
        f"drafter handed the whole plan writes toward the whole plan and "
        f"restates its neighbours' claims.\n\n"
        f"**Act 4 — one `prose-critic` per lesson, then the same lesson's own "
        f"drafter to revise.** The critic returns failed rule numbers and the "
        f"passages; hand those to a `lesson-drafter` for that same path. Do not "
        f"edit a lesson yourself and do not send one lesson's findings to "
        f"another lesson's drafter.\n\n"
        f"**Exactly one round.** Critique, revise, stop. A second round trades "
        f"a rule failure for blandness: the passages a critic can name are the "
        f"specific ones, so each pass sands off what was concrete and the "
        f"lesson gets cleaner and emptier.\n\n"
        f"Each lesson, whoever writes it:\n"
        f"- opens with frontmatter carrying `title`, `area`, and "
        f"`builds_toward` (the assessment it serves);\n"
        f"- teaches in prose, with real explanation rather than a summary of "
        f"what the learner will learn;\n"
        f"- quotes the corpus where the corpus says it better, with a citation;\n"
        f"- carries at least two components, of which at least one resolves "
        f"against the project (`definition`, `evidence`, `graph`, `timeline`, "
        f"`explorer` or `compare`) so the learner meets the actual material.\n\n"
        f"Do not write the check-for-understanding items here. A later phase "
        f"writes them from the lessons as they end up, and anything you add now "
        f"is written from a plan.\n\n"
        f"{COMPONENT_GUIDE}\n"
        f"Write the files. Do not summarise them back to me." + AUTHORING_DISPATCH_PROMPT
    )


def assessment_prompt(area: LearningArea, lesson_count: int) -> str:
    """Phase 4: the items, written against lessons that now exist.

    This phase exists only because of *when* it runs. Stage 2 already asked for
    check-for-understanding items and got them -- before a single lesson was
    drafted, so they are written from the understandings and read as furniture:
    correct, unattached, and asking about points the drafts did not make. The
    items here are written from the prose a reader will actually meet.

    The cost is a fourth turn per area, and a real risk this phase does not
    remove: Stage 2's items are still in `unit.md` and nothing deletes them, so
    a unit carries two generations of items. That is left undone deliberately
    -- deleting another phase's output from a prompt is the reconciliation
    problem this design is arranged to avoid.

    Lesson paths come from `lesson_paths` rather than a format string built
    here. CLAUDE.md records `AREAS_DIR` reaching three independent copies; a
    fourth resolver for the `lesson-NN.md` pattern is the same failure, and its
    symptom is a `quiz-writer` dispatched at a path nothing wrote, which
    returns an empty page rather than an error.
    """
    paths = lesson_paths(area.slug, lesson_count)
    return (
        f"Phase 4 for the area `{area.slug}`: the check-for-understanding "
        f"items, and one review of the unit.\n\n"
        f"The {lesson_count} lessons are written:\n"
        + "\n".join(f"- `{path}`" for path in paths)
        + f"\n\nDispatch one `quiz-writer` per lesson, in parallel, naming "
        f"that lesson by path and saying how many items to add. **Give it the "
        f"path and nothing else -- not the plan, not the other lessons.** It "
        f"writes from the lessons **as they are written**, not as they were "
        f"planned.\n\n"
        f"That distinction is the reason this is a separate phase. What a "
        f"lesson intended to teach and what it teaches are different things, "
        f"and the reader only ever meets the second. An item written from a "
        f"plan asks about a point the draft dropped, which reads to the learner "
        f"as a question about something they were never shown -- and it looks "
        f"correct to everyone except the person taking it.\n\n"
        f"Then, once every `quiz-writer` has returned, dispatch "
        f"`unit-reviewer` **once**. Give it `{AREAS_DIR}/{area.slug}` as the "
        f"unit directory, the lesson paths above, and "
        f"`{unit_path(area.slug)}` for the Stage 2 tasks. It writes "
        f"`{review_path(area.slug)}` and nothing else.\n\n"
        f"Last, and not in parallel with the writers: it judges what happens "
        f"*between* the lessons -- a claim two of them both make as if new, a "
        f"lesson assuming something no earlier lesson taught, an understanding "
        f"the tasks assess that no lesson covers. Run it while a `quiz-writer` "
        f"is still appending and it reads a unit that is half one version.\n\n"
        f"Do not draft or revise lesson prose in this phase, and do not "
        f"dispatch a `lesson-drafter`. The lessons are final; this phase adds "
        f"items to the end of them and writes one file of its own.\n\n"
        f"{COMPONENT_GUIDE}"
    )


def path_overview_prompt(path: LearningPath, areas: dict[str, LearningArea]) -> str:
    """The path's own file: the order, and the reasoning that produced it.

    The reasoning is *given* to the model rather than asked for, and that is
    the point of the turn. The order came from the graph -- reference
    asymmetry, dates, corpus breadth -- and a model invited to explain an
    order it did not compute will invent a pedagogical rationale that sounds
    better than the real one and is unfalsifiable. Here it is writing up
    evidence it has been handed.
    """
    steps = "\n".join(
        f"{i}. **{areas[slug].display_name()}** (`{slug}`, {areas[slug].size} entities)"
        for i, slug in enumerate(path.area_slugs, start=1)
    )
    edges = (
        "\n".join(
            f"- `{e.before}` before `{e.after}` — {e.reason}"
            + (" **(contested: the reverse also had a claim)**" if e.contested else "")
            for e in path.edges
        )
        or "- No pair had enough evidence to be ordered."
    )
    return (
        f"Write `{PATHS_DIR}/{path.slug}.md`, the overview of a learning path "
        f"through this project.\n\n"
        f"The order below was **derived from the knowledge graph**, not chosen. "
        f"Write it up; do not re-order it and do not invent reasons for it. "
        f"Where an edge is marked contested, say plainly that the two areas "
        f"depend on each other and that the order is one defensible reading.\n\n"
        f"Title: {path.title}\n\n"
        f"Order:\n{steps}\n\n"
        f"Why, edge by edge:\n{edges}\n\n"
        f"For each step write a short paragraph: what the learner will be able "
        f"to do after it, and what it assumes from the steps before. Link each "
        f"to `{AREAS_DIR}/<slug>/unit.md`."
    )


class CourseAuthor:
    """Runs an area's three authoring turns, joining and releasing around them.

    The join/release shape is `TopicSeeder.seed`'s exactly, including
    `release_project` in `finally` for its reason: a run that dies holding the
    project locks out every later turn over a crash that produced nothing.

    **One session for all three turns**, not one per stage. The turns are a
    single piece of work whose second and third steps read what the first
    wrote, and splitting them across sessions would put Stage 2's reading of
    Stage 1 across a workspace boundary -- the file would not be there.
    """

    def __init__(self, session: SessionService, turns: TurnRunner) -> None:
        self._session = session
        self._turns = turns

    async def author_area(
        self,
        project_id: UUID,
        area: LearningArea,
        subject: str,
        *,
        lesson_count: int = 3,
        run_id: UUID | None = None,
    ) -> AuthoredCourse:
        """Stage 1, then 2, then 3, in one session, in that order."""
        run_id = run_id or uuid4()
        session_id = await self._session.start_in_project(
            project_id, SessionPurpose.COURSE_AUTHORING
        )
        replies: list[str] = []
        try:
            await self._session.attach_project(project_id)
            first = await self._turns.run(session_id, desired_results_prompt(area, subject))
            replies.append(first.reply)
            second = await self._turns.run(session_id, evidence_prompt(area, first.reply))
            replies.append(second.reply)
            third = await self._turns.run(
                session_id, learning_plan_prompt(area, first.reply, lesson_count)
            )
            replies.append(third.reply)
        finally:
            await self._session.release_project(session_id)

        return AuthoredCourse(
            area_slug=area.slug,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            replies=tuple(replies),
        )

    async def author_path(
        self,
        project_id: UUID,
        path: LearningPath,
        areas: dict[str, LearningArea],
        *,
        run_id: UUID | None = None,
    ) -> AuthoredCourse:
        """The path overview only. One turn, because there is one file."""
        run_id = run_id or uuid4()
        session_id = await self._session.start_in_project(
            project_id, SessionPurpose.COURSE_AUTHORING
        )
        try:
            await self._session.attach_project(project_id)
            outcome = await self._turns.run(session_id, path_overview_prompt(path, areas))
        finally:
            await self._session.release_project(session_id)

        return AuthoredCourse(
            area_slug=path.slug,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            replies=(outcome.reply,),
        )
