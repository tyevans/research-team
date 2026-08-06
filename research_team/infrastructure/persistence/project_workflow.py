"""`WorkflowPort` over the `Project` aggregate, fixed to one project.

The sibling of `ProjectCorpusReader`, and bound the same way and for the same
reason: the port takes no project argument, so a tool holding one of these can
only ever move the run it was built for. A tool that could be passed an id
could advance somebody else's workflow, and `advance_stage` is the one tool in
the system where that would rewrite an audit trail rather than merely read the
wrong thing.

Every call reloads the aggregate rather than caching it. That is not caution
about staleness in the abstract -- it is that one turn can legitimately advance
twice, an approval per boundary, and an adapter answering from state it loaded
at construction would compute the same `to_stage` the second time and be
refused for skipping. The reload is a replay of one small stream, which is what
the event log is for.
"""

from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.domain.project import AdvanceStage, Project, ProjectState


class ProjectWorkflow:
    """One project's stage position, read and moved."""

    def __init__(self, projects: AggregateRepository[Project], project_id: UUID) -> None:
        self._projects = projects
        self._project_id = project_id

    async def project_state(self) -> ProjectState:
        return (await self._projects.load(self._project_id)).state

    async def advance(self, command: AdvanceStage) -> ProjectState:
        """Run the command and persist it, or let the refusal through.

        `execute` raises `CommandRejectedError` for an out-of-order or unknown
        stage and nothing is saved on that path, so a refused advance leaves
        the log untouched -- which is what lets the tool above turn the
        exception into prose without having to undo anything.
        """
        project = await self._projects.load(self._project_id)
        project.execute(command)
        await self._projects.save(project)
        return project.state
