"""Naming a project's first topics in one turn, not a run.

`auto_research.py` argues at length for round-per-turn scheduling, because
investigation is long, failure-prone and unbounded: "A turn is atomic: a
failure discards the aggregate and appends a lone marker. All-or-nothing over
an hour of work is worthless." Seeding shares none of those properties. It is
one bounded burst of naming -- the agent reads a subject, calls `open_topic`
a handful of times, and stops -- and a failure loses seconds, not an hour of
findings, sources and sub-questions. **The atomicity that makes a long run
worthless makes a short one clean**: there is no partial progress worth
preserving across a crash, no queue to resume, and no reason to trade the
simplicity of "one turn, one outcome" for machinery that exists to survive a
failure mode seeding does not have.

So this holds no state the log does not have and drives no loop.
`TopicSeeder.seed` joins the project the same way `start_auto_research` does
-- `start_in_project` then `attach_project`, so `open_topic` is bound -- runs
exactly one `TurnSupervisor` turn, and releases. There is no driver here
because there is nothing to drive: a turn either names topics or it does not,
and the caller finds out which by reading the queue afterwards, not by
folding a run's stream.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from research_team.application.session_service import SessionService
from research_team.application.topics import SELF_CONTAINED_QUESTION

SEEDING_PROMPT = (
    "Open a set of broad, orthogonal topics covering this subject. Work from "
    "your own knowledge. Call `web_search` only if you cannot confidently "
    "name a varied set for this subject -- if the subject is unfamiliar, or "
    "if the topics you can name all cluster in one corner of it."
)
"""The rule, stated as a decision procedure: "if you cannot", not "if search
is available". Those read identically to a person but not to a build --
checking tool availability would make this prompt describe two different
deployments, and it must describe one. With no `AGENT_SEARXNG_URL` configured
`web_search` is never bound in the first place, so an agent that follows this
rule to the letter behaves exactly the same whether the tool exists or not:
it works from what it knows, which is the path the rule prefers regardless.
Do not "fix" this to say "if `web_search` is available" -- that would make
search-less deployments a degraded case instead of the normal one."""


class TurnRunner(Protocol):
    """The slice of `TurnSupervisor` a seeding turn needs."""

    async def run(self, session_id: UUID, user_input: str) -> object: ...


@dataclass(frozen=True)
class SeedingRun:
    """What one seeding turn did, in the shape a caller wants to report.

    No topic count here: counting is a read of the queue, and a seeder that
    also carried the count would be a second, possibly stale, account of the
    same fact `TopicReadPort.list_topics` already answers.
    """

    run_id: UUID
    project_id: UUID
    session_id: UUID
    subject: str
    reply: str


def seeding_prompt(subject: str, max_topics: int) -> str:
    """The turn's user input: the rule, then the specifics it needs applied to.

    `SELF_CONTAINED_QUESTION` is already in this turn's *system* prompt --
    `TOPICS_PROMPT` carries it wherever `open_topic` is bound. It is repeated
    here, and the repetition is deliberate rather than an oversight.

    Seeding is the one path that hands the model a subject **once, as a
    heading, above a list it is about to write**, and that shape is what
    produces the elision: a list written under a heading does not repeat the
    heading. The system prompt's copy states the rule; this states the rule
    *instantiated on this run's subject*, with the subject spelled out inside
    the instruction, so following it is a matter of copying a string that is
    already on the page rather than of remembering a principle from a thousand
    tokens earlier.

    The cost is the subject appearing three times in one turn's input, which
    is a few dozen tokens and reads repetitively to a human. Judged worth it:
    the alternative -- stating the rule once, abstractly, far from the
    subject -- is precisely the arrangement that shipped this bug.
    """
    return (
        f"{SEEDING_PROMPT}\n\n"
        f"Subject: {subject}\n"
        f"Open at most {max_topics} topics.\n\n"
        f"{SELF_CONTAINED_QUESTION}\n\n"
        f"For this run that means every question you open names "
        f"{subject!r} (or an unambiguous full form of it) in the question "
        f"itself. A question that reads correctly only because "
        f"{subject!r} appears above it in this message is not finished."
    )


class TopicSeeder:
    """Runs one seeding turn per call, joining and releasing the project around it."""

    def __init__(self, session: SessionService, turns: TurnRunner) -> None:
        self._session = session
        self._turns = turns

    async def seed(
        self, project_id: UUID, subject: str, max_topics: int, run_id: UUID | None = None
    ) -> SeedingRun:
        """Open a broad set of topics for `subject`, in a single turn.

        `release_project` runs in `finally` rather than after a successful
        `run`, because the failure this exists to prevent is a run that dies
        holding the project: locked out of every later seed or turn over a
        crash that cost seconds and produced nothing. Joining itself
        (`start_in_project`) is not guarded the same way -- a project that
        was never joined has nothing to release, and `release_project` on an
        id that was never attached is the ordinary case `start_auto_research`
        already relies on.

        `run_id` is accepted rather than always minted here so a caller that
        has to hand back an id *before* this coroutine runs -- the web
        route's 202, minted the moment a background task starts -- can hand
        back the same id `SeedingRun.run_id` reports once the turn finishes,
        the way `ResearchSupervisor.start` mints `ActiveRun.run_id` up front
        for the same reason. Defaults to a fresh one for every caller that
        has no such id to thread through, `TopicSeeder`'s own tests among
        them.
        """
        run_id = run_id or uuid4()
        session_id = await self._session.start_in_project(project_id)
        try:
            await self._session.attach_project(project_id)
            outcome = await self._turns.run(session_id, seeding_prompt(subject, max_topics))
        finally:
            await self._session.release_project(session_id)

        return SeedingRun(
            run_id=run_id,
            project_id=project_id,
            session_id=session_id,
            subject=subject,
            reply=outcome.reply,
        )
