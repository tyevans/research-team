"""Sending one agent at one topic, for one turn, to do one thing to it.

Three actions: `understanding` writes what the project knows about the
question, `research` gathers sources for it, `refine` judges the question
itself. They differ in a prompt and a path and in nothing else, which is why
`TopicDispatcher.dispatch` takes the action rather than there being three of
it.

`topic_seeding.py` already made the argument this module rests on, and it
applies here unchanged: a bounded burst of work whose failure costs seconds is
a *turn*, not a run, because "the atomicity that makes a long run worthless
makes a short one clean". Writing our understanding of a topic is exactly that
shape -- read what the project already holds about one question, write one
file, stop. There is no partial progress worth preserving across a crash and
no queue to resume, so this holds no state the log does not have and drives no
loop.

**This adds no domain event.** The file lands as `FileWritten` on the
dispatching session's stream, which is already on the live feed, already
scrubbable, already diffable. Findings the agent records land as
`TopicFindingRecorded` on the topic. There is nothing new to write down, and
that is the strongest property this shape has: a feature that adds no
vocabulary to the log cannot break anyone's stored history.

**Why `/topics/<nn>-<slug>/` and not `/course/`.** `/course` is where authoring
writes, and a topic synthesis is not authoring -- it answers a question somebody
asked rather than building a lesson. Two directories, two provenances. The
`<nn>` prefix is there because alphabetical file listing is the only ordering a
file viewer has, so without a numeric prefix the directory sorts by whatever the
questions happen to start with.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from research_team.application.session_service import SessionService
from research_team.application.text import slugify
from research_team.application.topic_read import TopicDetail, TopicReadPort
from research_team.domain import SessionPurpose

TOPICS_DIR = "/topics"
"""Where a dispatch writes, kept apart from `/course` -- see the module
docstring. One directory per topic rather than one file per topic, because
action 3 will add `lesson.md` beside `understanding.md` and a flat
`/topics/00-slug-understanding.md` would have to be renamed to accommodate it.
"""

SLUG_LIMIT = 60
"""How much of a question survives into its directory name.

A question is free text and some of them are a paragraph. The cost of a cap is
that two questions sharing their first sixty characters collide on one
directory; the cost of no cap is a path long enough to be unreadable in a file
list and, on some filesystems, unwritable. The `<nn>` prefix makes the
collision case impossible anyway -- two topics never share a position.
"""

DispatchAction = Literal["understanding", "research", "refine"]
"""What a dispatch was asked to do.

Three values. `lesson` is designed and still not built: it is blocked on
whether "course" means a lesson or the staged gated thing, which is a question
about authoring rather than about dispatch.

`research` was blocked on `BACKLOG.md` B24 -- `fetch` floors at `ask`, and an
unattended loop reaching an approval "either deadlocks on a future nobody will
resolve or is auto-rejected outright". **That blocker is about being
unattended, not about fetching.** A dispatch is attended by construction: a
person pressed a button on a row seconds ago and the approvals surface is on
that page. So this asks, under a default policy, and the person who pressed
answers. Nothing here lowers `TOOL_FLOORS`, and nothing may -- B24's "a loop
that can edit its own permissions makes the floors advisory for everything
else too" is the rule this stays inside.
"""

DISPATCH_ACTIONS: frozenset[str] = frozenset({"understanding", "research", "refine"})
"""The actions this build will actually run, for a route to check against.

A runtime set beside the `Literal` rather than derived from it, because the
route validates a string off the wire and `typing.get_args` is a clever way to
write the same set less readably. Adding an action means adding it in both
places, and `test_an_unsupported_action_is_refused_by_name` -- which posts
`lesson`, the one designed action still absent, and asserts the refusal names
all three of these -- is what notices if only one is updated.
"""


class UnknownTopic(LookupError):
    """This project has no such topic, so there is nothing to dispatch at."""

    def __init__(self, project_id: UUID, topic_id: UUID) -> None:
        super().__init__(f"project {project_id} has no topic {topic_id}")
        self.project_id = project_id
        self.topic_id = topic_id


class TurnRunner(Protocol):
    """The slice of `TurnSupervisor` a dispatch turn needs. As `TopicSeeder`'s."""

    async def run(self, session_id: UUID, user_input: str) -> object: ...


TopicReaderFor = Callable[[UUID], TopicReadPort]
"""A project's topic reader, by project id.

Declared here rather than imported from the web layer's `TopicReaders` alias
for the reason `workers.py` gives about its own protocols: `application` may
not import `interfaces`, and `test_imports_point_inward` enforces it.
"""


def topic_slug(question: str) -> str:
    """The readable half of a topic's directory name.

    Falls back to `topic` rather than the empty string: a question of `???`
    slugifies to nothing, and `/topics/00-/understanding.md` is a directory
    with no name -- which reads as a bug in the path builder rather than as a
    badly worded question.
    """
    slug = slugify(question)
    if len(slug) > SLUG_LIMIT:
        # Cut on a hyphen so the last word is whole. `rsplit` on the cut
        # prefix rather than a word-count loop, because slugify has already
        # collapsed every separator to one hyphen.
        slug = slug[:SLUG_LIMIT].rsplit("-", 1)[0]
    return slug.strip("-") or "topic"


def topic_directory(position: int, question: str) -> str:
    """Where everything written about one topic goes.

    `position` is the topic's index in the project's topic list, and it is in
    the directory name so that a reader listing `/topics` sees them in the
    order the project has them rather than alphabetically.
    It is read at dispatch time rather than stored, so a topic that moves in
    the list after its directory was written will next be written to a
    different one. That is a real cost and the alternative is worse: storing
    the number means a new field on an event, and this design adds none.
    """
    return f"{TOPICS_DIR}/{position:02d}-{topic_slug(question)}"


def understanding_path(position: int, question: str) -> str:
    """The one file action 2 writes. Overwritten by a later dispatch, deliberately.

    The filesystem is event-sourced, so every prior version is already
    recoverable by scrubbing the session's timeline. A second file would be a
    second mechanism for history the aggregate already provides -- and one the
    file viewer would have to learn to collapse.
    """
    return f"{topic_directory(position, question)}/understanding.md"


def refinement_path(position: int, question: str) -> str:
    """Where `refine` records what it concluded about the question itself.

    Beside `understanding.md` in the same directory, which is the case
    `TOPICS_DIR`'s docstring anticipated when it chose one directory per topic
    over one file per topic. Overwritten by a later refinement for
    `understanding_path`'s reason exactly.

    **This file is `refine`'s only durable output, and that is a smaller claim
    than the design makes.** §3.2 says refine "writes through the topic's
    existing events (the question and its sub-questions are already editable
    through `TopicManagePane`'s routes)". Half of that is wrong: sub-questions
    are editable (`AddSubQuestion`, and a route for it), but **the question is
    not** -- there is no command, no event and no route that rewrites a
    `TopicOpened.question`, and `build_topic_tools` gives the agent five tools
    of which none touches either. So a refine turn cannot rewrite the question
    it was asked to rewrite. Rather than inventing an event to close the gap
    -- which this design explicitly forbids itself -- the turn writes its
    diagnosis and its proposed wording here, where a person applies it from
    `TopicManagePane`. See the report on this branch; the missing tool is the
    next thing to build, not something to fake.
    """
    return f"{topic_directory(position, question)}/refinement.md"


def dispatch_path(action: DispatchAction, position: int, question: str) -> str:
    """The file this action is asked to write, or `""` when it writes none.

    `research` is the empty case and it is not an oversight: what a research
    turn produces is links and findings on the topic aggregate --
    `TopicSourceLinked`, `TopicFindingRecorded`, real events on the permanent
    log -- and a summary file beside them would be a second, weaker account of
    the same work that nothing keeps in step with the first.

    The cost lands on the caller: `DispatchRun.path` and the queue's `done`
    frame carry `""` for a research dispatch, so a client rendering "open the
    file it wrote" must treat empty as "no file" rather than as a path. Stated
    here because the alternative -- `None` -- would make every other reader
    branch on a case only one action produces.
    """
    match action:
        case "understanding":
            return understanding_path(position, question)
        case "refine":
            return refinement_path(position, question)
        case "research":
            return ""


UNDERSTANDING_PROMPT = (
    "Write down what this project understands about one topic, as a single "
    "markdown document. Work from what the project already holds -- the "
    "topic's linked sources, its findings, its sub-questions, and the "
    "knowledge graph. Read the sources rather than recalling them: "
    "`read_source` gives you the text and the offsets to cite.\n\n"
    "Do not fetch anything, and do not search. If the material does not "
    "answer part of the question, say so in the document and record it as a "
    "sub-question rather than filling the gap from your own knowledge. A "
    "synthesis that quietly substitutes what you already knew for what this "
    "project gathered is indistinguishable, on the page, from one that did "
    "the work -- and that is the failure this instruction exists to prevent.\n\n"
    "Prose, not exercises. This document explains; it is not something to "
    "practise against."
)
"""The rule, stated before the specifics it applies to, matching `SEEDING_PROMPT`.

Two things it deliberately does *not* say. It does not mention `web_search`
availability -- a prompt that branched on a tool's presence would describe two
deployments instead of one, which is the mistake `SEEDING_PROMPT`'s docstring
warns against at length. And it asks for no widgets, because a synthesis is
explanation and a component earns its place when the learner should *do*
something. A dossier padded with flashcards is a worse dossier.
"""

RESEARCH_PROMPT = (
    "Gather sources for one topic. Search for material that bears on the "
    "question, fetch the pages worth keeping, and attach each one to the "
    "topic with `link_source`. Record what a source establishes with "
    "`record_finding`, citing the id you linked; record what you looked for "
    "and could not find with `record_gap`.\n\n"
    "This is one turn, not a campaign. Stop when the turn is spent rather "
    "than when the question is closed -- a person is watching this and can "
    "press the button again. Do not open new topics, do not write files, and "
    "do not answer the question from your own knowledge: a turn that reports "
    "findings it did not fetch is indistinguishable, on the topic, from one "
    "that did the work, and it is the reason this instruction is here.\n\n"
    "You may be asked to approve each fetch. That is the tool working as "
    "configured, not a fault: wait for the answer and carry on."
)
"""The rule, then the specifics, matching `UNDERSTANDING_PROMPT`'s register.

The last paragraph is the one that earns its place. `fetch` floors at `ask`
(`autonomy.py`'s `TOOL_FLOORS`), so on a default install every fetch in this
turn interrupts -- and a model that reads an approval prompt as a refusal
gives up and writes from memory, which is exactly the failure the paragraph
above forbids. Telling it the interruption is expected costs two lines.

It does **not** branch on whether `web_search` is registered, for
`UNDERSTANDING_PROMPT`'s reason: a prompt that described two deployments would
be a prompt nobody could read against the one they are running.
"""

REFINE_PROMPT = (
    "Judge whether this topic's question is answerable by what the project "
    "has gathered, and write down what should happen to it. Read the "
    "material first -- the linked sources, the findings, the gaps -- and let "
    "it decide the verdict rather than deciding from the wording alone.\n\n"
    "There are four verdicts and you must pick exactly one: the question is "
    "fine as it stands; it is too broad and should be narrowed to a stated "
    "narrower question; it is really several questions and should be split "
    "into stated sub-questions; or the material shows it was the wrong "
    "question, and you say what the right one is.\n\n"
    "Do not fetch, do not search, and do not open new topics. Do not record "
    "findings -- a finding is something learned about the subject, and this "
    "turn learns something about the question. Propose the new wording in "
    "the file; a person applies it."
)
"""What a refine turn is for, and the four endings it may reach.

**It proposes rather than applies, and that is a limitation rather than a
design choice.** See `refinement_path`: nothing in this system can rewrite a
topic's question, so "rewrites the question" -- which is what §3.2 asks for --
is not available to any tool this turn holds. The enumeration of four verdicts
is what makes the proposal usable anyway: a person reading the file gets a
decision to accept or reject, not an essay to interpret.

Forbidding `record_finding` is deliberate and costs something: a turn that
genuinely learns about the subject while reading has nowhere to put it. The
alternative is worse -- findings recorded by a turn that never fetched are the
`UNDERSTANDING_PROMPT` failure with a different verb.
"""


@dataclass(frozen=True)
class DispatchRun:
    """What one dispatch did, in the shape a caller wants to report.

    `path` is the file the agent was *asked* to write, not one read back off
    the filesystem. The two differ exactly when the agent disobeyed, and
    reporting the request is the more useful of the two: a caller comparing it
    against `project_files` can tell that case apart, which it could not if
    this field simply went missing.

    `path` is `""` for a `research` dispatch, which asks for no file at all --
    see `dispatch_path`. A reader must treat empty as "no file" rather than as
    a path, and that is the cost of not making this field optional.
    """

    dispatch_id: UUID
    project_id: UUID
    topic_id: UUID
    session_id: UUID
    action: DispatchAction
    question: str
    path: str
    reply: str


def _briefing(detail: TopicDetail, closing: str, project_name: str = "") -> str:
    """The specifics: which topic, what we already hold, and how to finish.

    `closing` is the last thing said, and it differs per action -- two of the
    three end in a file and one ends on the topic aggregate. Passed in rather
    than selected here, so this function has no opinion about actions at all
    and a fourth one adds nothing to it.

    Everything here is also reachable through the agent's own tools. It is
    stated up front anyway because a turn that has to discover its own subject
    spends its first tool calls doing so, and a dispatch is one turn -- those
    calls come out of the budget for the work itself.

    `project_name` is the repair for topics *already stored* with an implicit
    subject -- "typical physical traits" rather than "typical physical traits
    of a Nova Scotia Duck Tolling Retriever". Those questions are in the log
    and the log is not rewritten, so nothing can fix the stored text; what can
    be fixed is what the agent reading it is told. Naming the project here
    costs a line and makes a fragment actionable.

    It does *not* make the fragment correct. The reading rule below is a
    guess, and it is a wrong guess exactly when a topic legitimately concerns
    something other than the project's headline subject -- a comparison
    topic, say. Stated as "if the question does not name its own subject"
    rather than unconditionally, so a question that already names one is left
    alone.
    """
    summary = detail.view.summary
    lines: list[str] = []
    if project_name.strip():
        lines.append(f"Project: {project_name}")
    lines += [
        f"Topic: {summary.question}",
        f"Topic id: {summary.topic_id}",
        f"Status: {summary.status}",
        f"Why it was opened: {detail.rationale}",
    ]
    if detail.scope:
        lines.append(f"Scope: {detail.scope}")
    if detail.source_ids:
        lines.append("Linked sources: " + ", ".join(detail.source_ids))
    else:
        lines.append(
            "Linked sources: none. Say so in the document rather than "
            "writing from your own knowledge."
        )
    if detail.findings:
        lines.append("Findings already recorded:")
        lines += [f"- {finding}" for finding in detail.findings]
    open_questions = [sub.question for sub in detail.sub_questions if not sub.resolved]
    if open_questions:
        lines.append("Open sub-questions:")
        lines += [f"- {question}" for question in open_questions]
    if detail.contested:
        lines.append(
            "Some of this is contested. Report the disagreement rather than "
            "resolving it -- the document should leave a reader knowing that "
            "the question is open."
        )
    if project_name.strip():
        # Last of the context, immediately before the write instruction, so
        # the rule for reading a bare question is the thing most recently
        # said when the model starts writing.
        lines.append(
            f"\nIf the topic question does not name its own subject, read it as "
            f"a question about {project_name!r} -- topics opened before that was "
            f"required were written down when the subject was obvious from "
            f"context. Either way, write the document so a reader who has not "
            f"seen this project can follow it: name the subject in the prose "
            f"rather than leaving the question to carry it."
        )

    lines.append(f"\n{closing}")
    return "\n".join(lines)


def _file_closing(path: str, at: datetime, source_ids_note: str) -> str:
    """The write instruction the two file-writing actions share.

    One builder rather than two literals, because the frontmatter block is the
    part a reader of the file depends on and two copies would drift by a key.
    `source_ids_note` is the only thing that differs: what "the ids you drew
    on" means is not the same question for a synthesis and for a verdict about
    a question's wording.
    """
    return (
        f"Write exactly one file, at `{path}`, with `write_file`. Overwrite "
        "it if it is already there. Open it with a frontmatter block fenced "
        "by `---` carrying `topic_id`, `question`, "
        f"`dispatched_at: '{at.isoformat()}'`, and `source_ids` -- {source_ids_note}"
    )


def understanding_input(
    detail: TopicDetail, path: str, at: datetime, project_name: str = ""
) -> str:
    """The turn's user input: the rule, then the specifics it needs applied to.

    `project_name` defaults to empty so a caller that has no project state in
    hand still builds a valid input -- the briefing then reads exactly as it
    did before, which is the pre-existing behaviour rather than a degraded
    one.
    """
    closing = _file_closing(
        path,
        at,
        "the ids you actually drew on, which is not necessarily every id listed above.",
    )
    return f"{UNDERSTANDING_PROMPT}\n\n{_briefing(detail, closing, project_name)}"


def research_input(detail: TopicDetail, at: datetime, project_name: str = "") -> str:
    """A research turn's input. No path, because it writes no file.

    `at` is accepted and unused, so every `*_input` here has one signature the
    dispatcher can call. The alternative -- a special case at the call site for
    the one action with no timestamp to state -- puts the knowledge that
    research writes nothing in two places instead of one.
    """
    del at
    closing = (
        "Attach what you find with `link_source` and say what it establishes "
        "with `record_finding`. Write no file: the links and findings on this "
        "topic are the record of this turn, and a file beside them would be a "
        "second account of the same work."
    )
    return f"{RESEARCH_PROMPT}\n\n{_briefing(detail, closing, project_name)}"


def refine_input(detail: TopicDetail, path: str, at: datetime, project_name: str = "") -> str:
    """A refine turn's input: the verdict rules, then the question to judge."""
    closing = _file_closing(
        path,
        at,
        "the ids whose content decided the verdict, which may be none if the "
        "question fails on its own terms.",
    ) + (
        "\nAfter the frontmatter, state the verdict on its own line as "
        "`verdict: fine`, `verdict: narrow`, `verdict: split` or "
        "`verdict: wrong`, then the proposed wording, then why the material "
        "supports it. Nothing in this repository parses that line -- it is "
        "there so a person scanning several refinements can sort them, and "
        "asserting on it in Python would be the half-a-contract mistake "
        "CLAUDE.md records paying for four times."
    )
    return f"{REFINE_PROMPT}\n\n{_briefing(detail, closing, project_name)}"


def dispatch_input(
    action: DispatchAction,
    detail: TopicDetail,
    path: str,
    at: datetime,
    project_name: str = "",
) -> str:
    """The user input for one dispatch, by action.

    A `match` rather than a dict of callables, because the three builders do
    not share a signature -- `research_input` has no path to take -- and a dict
    would have to pretend they do.
    """
    match action:
        case "understanding":
            return understanding_input(detail, path, at, project_name)
        case "research":
            return research_input(detail, at, project_name)
        case "refine":
            return refine_input(detail, path, at, project_name)


class TopicDispatcher:
    """Runs one dispatch turn per call, joining and releasing the project around it."""

    def __init__(
        self, session: SessionService, turns: TurnRunner, topics: TopicReaderFor
    ) -> None:
        self._session = session
        self._turns = turns
        self._topics = topics

    async def dispatch(
        self,
        project_id: UUID,
        topic_id: UUID,
        action: DispatchAction = "understanding",
        dispatch_id: UUID | None = None,
    ) -> DispatchRun:
        """Do one thing to one topic, in a single turn.

        The action decides both the prompt and the path; everything else --
        resolving the topic, joining, releasing -- is identical across the
        three, which is the reason they are one method rather than three.

        The topic is resolved *before* the project is joined. A refusal that
        had already taken the project would hold it for the duration of a turn
        that was never going to run -- the mirror image of the failure the
        `finally` below prevents, and worse here than for seeding because
        dispatches queue behind each other and the whole queue stalls with it.

        `release_project` runs in `finally` for the reason `TopicSeeder.seed`
        gives verbatim: the failure this exists to prevent is a run that dies
        holding the project.

        `dispatch_id` is accepted rather than always minted here so a caller
        that must hand back an id *before* this coroutine runs -- the route's
        202 -- reports the same id `DispatchRun.dispatch_id` carries once the
        turn finishes. Same reasoning as `TopicSeeder.seed`'s `run_id`.
        """
        dispatch_id = dispatch_id or uuid4()
        views = await self._topics(project_id).list_topics()
        position = next(
            (index for index, view in enumerate(views) if view.summary.topic_id == topic_id),
            None,
        )
        if position is None:
            raise UnknownTopic(project_id, topic_id)
        detail = await self._topics(project_id).read_topic(topic_id)
        if detail is None:
            # Listed a moment ago and unreadable now. Reported as unknown
            # rather than crashing: the caller's recourse is the same either
            # way, and a dispatch is not the place to explain a race in a
            # read model.
            raise UnknownTopic(project_id, topic_id)

        question = detail.view.summary.question
        path = dispatch_path(action, position, question)
        at = datetime.now(UTC)
        # Read before joining, alongside the topic resolution above and for the
        # same reason: a read that failed after `start_in_project` would hold
        # the project across a turn that never runs.
        project_name = (await self._session.project_state(project_id)).name

        session_id = await self._session.start_in_project(
            project_id, SessionPurpose.TOPIC_DISPATCH
        )
        try:
            await self._session.attach_project(project_id)
            outcome = await self._turns.run(
                session_id, dispatch_input(action, detail, path, at, project_name)
            )
        finally:
            await self._session.release_project(session_id)

        return DispatchRun(
            dispatch_id=dispatch_id,
            project_id=project_id,
            topic_id=topic_id,
            session_id=session_id,
            action=action,
            question=question,
            path=path,
            reply=outcome.reply,
        )
