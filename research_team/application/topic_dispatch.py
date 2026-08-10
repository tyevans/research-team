"""Sending one agent at one topic, to write down what we understand of it.

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

**Why `/topics/<nn>-<slug>/` and not `/course/`.** `COURSE_DIR`'s docstring
says it is "everything a workflow produces", and a topic synthesis is not
produced by a workflow -- it has no preset, no stage and no stage number.
Two directories, two provenances. The `<nn>` prefix is borrowed from
`artifacts.py` for the reason that module gives: alphabetical file listing is
the only ordering a file viewer has, so without a numeric prefix the directory
sorts by whatever the questions happen to start with.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from research_team.application.artifacts import slugify
from research_team.application.session_service import SessionService
from research_team.application.topic_read import TopicDetail, TopicReadPort

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

DispatchAction = Literal["understanding"]
"""What a dispatch was asked to do.

One value today. `research` and `lesson` are designed and deliberately not
built: one is blocked on whether a dispatch may fetch unattended, the other on
whether "course" means a lesson or the staged gated thing. A `Literal` with one
member reads oddly and is correct -- it is the type that will gain members,
and widening it later is additive.
"""

DISPATCH_ACTIONS: frozenset[str] = frozenset({"understanding"})
"""The actions this build will actually run, for a route to check against.

A runtime set beside the `Literal` rather than derived from it, because the
route validates a string off the wire and `typing.get_args` on a one-member
`Literal` is a clever way to write the same set less readably. Adding an
action means adding it in both places, and a test asserting the route refuses
`lesson` by name is what notices if only one is updated.
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

    `position` is the topic's index in the project's topic list, which is the
    same thing `stage_number` is to a preset and is used for the same reason.
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
warns against at length. And it asks for no widgets: `SourceDossier` is absent
from `COMPONENTS_FOR` and should stay absent, because a synthesis is
explanation and "a component earns its place when the learner should *do*
something". A dossier padded with flashcards is a worse dossier.
"""


@dataclass(frozen=True)
class DispatchRun:
    """What one dispatch did, in the shape a caller wants to report.

    `path` is the file the agent was *asked* to write, not one read back off
    the filesystem. The two differ exactly when the agent disobeyed, and
    reporting the request is the more useful of the two: a caller comparing it
    against `project_files` can tell that case apart, which it could not if
    this field simply went missing.
    """

    dispatch_id: UUID
    project_id: UUID
    topic_id: UUID
    session_id: UUID
    action: DispatchAction
    question: str
    path: str
    reply: str


def _briefing(detail: TopicDetail, path: str, at: datetime) -> str:
    """The specifics: which topic, what we already hold, and where to write it.

    Everything here is also reachable through the agent's own tools. It is
    stated up front anyway because a turn that has to discover its own subject
    spends its first tool calls doing so, and a dispatch is one turn -- those
    calls come out of the budget for the work itself.
    """
    summary = detail.view.summary
    lines = [
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

    lines.append(
        f"\nWrite exactly one file, at `{path}`, with `write_file`. Overwrite "
        "it if it is already there. Open it with a frontmatter block fenced "
        "by `---` carrying `topic_id`, `question`, "
        f"`dispatched_at: '{at.isoformat()}'`, and `source_ids` -- the ids you "
        "actually drew on, which is not necessarily every id listed above."
    )
    return "\n".join(lines)


def understanding_input(detail: TopicDetail, path: str, at: datetime) -> str:
    """The turn's user input: the rule, then the specifics it needs applied to."""
    return f"{UNDERSTANDING_PROMPT}\n\n{_briefing(detail, path, at)}"


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
        """Write our understanding of one topic, in a single turn.

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
        path = understanding_path(position, question)
        at = datetime.now(UTC)

        session_id = await self._session.start_in_project(project_id)
        try:
            await self._session.attach_project(project_id)
            outcome = await self._turns.run(session_id, understanding_input(detail, path, at))
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
