"""Turning one learning area into a unit and its lessons, by Understanding by Design.

UbD's own three stages **terminate at a unit plan**: it has no production or
delivery half at all, because it assumes a teacher who will do the producing.
This module is that teacher. Phase 4 goes past Stage 3 into materials, which is
a departure from UbD as written rather than part of it, and it is recorded here
so that nobody later reads the four phases as three stages plus a rounding
error.

**Backward design is enforced by sequencing, not by asking for it.** Four
phases run in order, and each of the first three is given only what the stages
before it produced: desired results, then evidence *given the results*, then
the learning plan *given Stage 1's reply and Stage 2 off the file*. Phase 4 is
given neither reply -- it is written against the lessons as they ended up, and
that is the whole reason it is separate. A model asked for all of it at once
writes the lessons first and reverse-engineers understandings to match them --
fluently, and with every section present, so the output is indistinguishable
from the real thing by inspection. That is the precise failure UbD exists to
prevent, and four calls rather than one is what it costs to actually prevent it
rather than to request it politely.

**Every turn runs against a project the agent has joined**, so its graph and
corpus tools are bound and a lesson can quote the material it is teaching.
That is the payoff of clustering the graph rather than a vector space: the
area carries entity ids, the prompts hand those ids to the model, and the
components it writes resolve against the same project.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from research_team.curriculum.application.authoring_checkpoints import (
    AREAS_DIR,
    CheckpointEvaluation,
    CheckpointFailed,
    check_assessment,
    check_lessons,
    check_stage_one,
    check_stage_two,
    component_counts,
    stage_one_text,
)
from research_team.curriculum.application.authoring_prompts import (
    COMPONENT_GUIDE,
    PATHS_DIR,
    PROMPT_ANCHORS,
    RETRY_PREFACE,
    assessment_prompt,
    desired_results_prompt,
    evidence_prompt,
    learning_plan_prompt,
    path_overview_prompt,
    retry_prompt,
)
from research_team.curriculum.domain.learning_area import LearningArea, LearningPath
from research_team.session.application.session_service import SessionService
from research_team.session.domain import SessionPurpose


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

    `checkpoints` carries the evaluations of the four authoring checkpoints (B154),
    providing the denominator so telemetry can measure pass and retry rates.
    """

    area_slug: str
    project_id: UUID
    session_id: UUID
    run_id: UUID
    replies: tuple[str, ...]
    checkpoints: tuple[CheckpointEvaluation, ...] = ()


_retry_prompt = retry_prompt

__all__ = [
    "AREAS_DIR",
    "COMPONENT_GUIDE",
    "PATHS_DIR",
    "PROMPT_ANCHORS",
    "RETRY_PREFACE",
    "AuthoredCourse",
    "CourseAuthor",
    "TurnRunner",
    "assessment_prompt",
    "desired_results_prompt",
    "evidence_prompt",
    "learning_plan_prompt",
    "path_overview_prompt",
    "retry_prompt",
]


class CourseAuthor:
    """Runs an area's four authoring phases, joining and releasing around them.

    The join/release shape is `TopicSeeder.seed`'s exactly, including
    `release_project` in `finally` for its reason: a run that dies holding the
    project locks out every later turn over a crash that produced nothing.

    **One session for all four phases**, not one per stage. The turns are a
    single piece of work whose later steps read what the earlier ones wrote,
    and splitting them across sessions would put Stage 2's reading of Stage 1
    across a workspace boundary -- the file would not be there.
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
        """Four phases, in order, each asserted on before the next begins.

        The phase boundary is the whole point. A single agent holding the
        `task` tool would end when it stopped talking, and a run that
        dispatched two drafters instead of five, or skipped the prose critic,
        produces a complete-looking unit and the same settled event. Between
        phases there is somewhere for Python to look.

        **Every phase gets a second attempt in the same session**, which is
        where this method's recovery story now lives -- see `_phase`. The
        paragraph this replaces said a phase 3 that dies "has usually left a
        half-written unit worth discarding anyway", and the log disagrees: of
        22 authoring sessions in the owner's database on 2026-08-29, four
        reached all four phases and eighteen did not, and the ones that stopped
        at phase 2 or 3 were discarding two working phases apiece.

        The parent's lesson plan is still not persisted, and that is still a
        real cost: a phase 3 whose *second* attempt fails re-plans from scratch
        if anyone runs the area again. Writing it to a file would buy that back
        and reintroduce the shared-pool problem for anything later that reads
        it. The retry narrows how often it matters without settling it.
        """
        run_id = run_id or uuid4()
        session_id = await self._session.start_in_project(
            project_id, SessionPurpose.COURSE_AUTHORING
        )
        replies: list[str] = []
        evaluations: list[CheckpointEvaluation] = []
        try:
            await self._session.attach_project(project_id)

            replies.append(
                await self._phase(
                    session_id,
                    desired_results_prompt(area, subject),
                    lambda files: check_stage_one(files, area.slug),
                    evaluations=evaluations,
                    phase_name="stage_one",
                    target=area.slug,
                )
            )

            # Stage 1 comes off the file, not off the reply above. See
            # `stage_one_text`: the reply was empty on every run this change
            # was written from, and on the runs that worked it was a second,
            # unreconciled account of a document that already exists.
            stage_one = stage_one_text(await self._files(session_id), area.slug)

            replies.append(
                await self._phase(
                    session_id,
                    evidence_prompt(area, stage_one),
                    lambda files: check_stage_two(files, area.slug),
                    evaluations=evaluations,
                    phase_name="stage_two",
                    target=area.slug,
                )
            )

            replies.append(
                await self._phase(
                    session_id,
                    learning_plan_prompt(area, stage_one, lesson_count),
                    lambda files: check_lessons(files, area.slug, lesson_count, area=area),
                    evaluations=evaluations,
                    phase_name="lessons",
                    target=area.slug,
                )
            )
            # Read before phase 4 runs, because phase 4's checkpoint has no
            # other way to tell its own contribution from phase 3's: every
            # lesson already carries components by then, so an unconditional
            # "carries a component" check passes a run in which every
            # `quiz-writer` did nothing.
            before = component_counts(await self._files(session_id), area.slug, lesson_count)

            replies.append(
                await self._phase(
                    session_id,
                    assessment_prompt(area, lesson_count),
                    lambda files: check_assessment(
                        files, area.slug, lesson_count, before=before
                    ),
                    evaluations=evaluations,
                    phase_name="assessment",
                    target=area.slug,
                )
            )
        finally:
            await self._session.release_project(session_id)

        return AuthoredCourse(
            area_slug=area.slug,
            project_id=project_id,
            session_id=session_id,
            run_id=run_id,
            replies=tuple(replies),
            checkpoints=tuple(evaluations),
        )

    async def _phase(
        self,
        session_id: UUID,
        prompt: str,
        check: Callable[[dict[str, Any]], None],
        evaluations: list[CheckpointEvaluation] | None = None,
        phase_name: str = "",
        target: str = "",
    ) -> str:
        """One phase: run the turn, check the files, and on a refusal try once
        more from where it stopped rather than losing the area.

        **The retry is the resumption.** Restarting the area from phase 1 was
        the only recovery this had, and it is the expensive one: the phases
        share a session precisely because each reads what the earlier ones
        wrote, so a phase 3 that failed had two working phases behind it that a
        fresh run would pay for again. Re-issuing the same phase into the same
        session keeps the workspace, keeps the conversation, and costs one turn.

        **What makes the second attempt different from the first is not the
        prose.** The retry prompt adds the checkpoint's own complaint, which is
        the specific thing that was missing -- but the load-bearing difference
        is that the failing turn's tool results are now *in* the conversation
        and its research budget has reset (`ResearchBudget` is built per turn),
        so the attempt that spiralled through eighteen rounds of graph queries
        starts the second turn holding all of them. The failure this was
        written for is a parent that researched and never wrote; the second
        turn is one where the research is already done.

        **Once, not until it passes.** A phase that fails twice is failing for
        a reason another turn will not fix -- most often a corpus too thin to
        carry two enduring understandings -- and a loop there spends a local
        model's evening rediscovering that. What propagates is the *second*
        `CheckpointFailed`, chained from the first: both name the same phase,
        which is what `CourseAuthoringFailed` records, and the second one
        describes the state the files are actually in when the caller reads
        them. Chained rather than replaced so a traceback still shows that a
        retry happened; the run would otherwise report a single failure and
        two turns' worth of elapsed time with nothing joining them.
        """
        outcome = await self._turns.run(session_id, prompt)
        try:
            check(await self._files(session_id))
            if evaluations is not None:
                evaluations.append(
                    CheckpointEvaluation(phase=phase_name, target=target, passed=True)
                )
        except CheckpointFailed as first:
            first.session_id = session_id
            if evaluations is not None:
                evaluations.append(
                    CheckpointEvaluation(
                        phase=first.phase or phase_name,
                        target=target,
                        passed=False,
                        reason=first.reason,
                    )
                )
            retry = await self._turns.run(session_id, _retry_prompt(prompt, first))
            try:
                check(await self._files(session_id))
                if evaluations is not None:
                    evaluations.append(
                        CheckpointEvaluation(phase=phase_name, target=target, passed=True)
                    )
            except CheckpointFailed as second:
                second.session_id = session_id
                if evaluations is not None:
                    evaluations.append(
                        CheckpointEvaluation(
                            phase=second.phase or phase_name,
                            target=target,
                            passed=False,
                            reason=second.reason,
                        )
                    )
                    second.checkpoints = tuple(evaluations)
                raise second from first
            # The retry's reply, not the first turn's: it is the turn that
            # produced the files every later phase reads.
            return retry.reply
        return outcome.reply

    async def _files(self, session_id: UUID) -> dict[str, Any]:
        """This session's workspace, re-read after every phase.

        Re-read rather than accumulated, because the subagents wrote through
        the same backend and their writes are on the session, not in anything
        this object holds.
        """
        session = await self._session.load(session_id)
        return dict(session.state.files)

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
