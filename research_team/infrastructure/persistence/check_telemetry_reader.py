"""The check telemetry read model, behind its port, scoped to one project.

`CheckTelemetryRunner` answers for every project -- it is one table following
one log -- and `CheckTelemetryReadPort` deliberately takes no project argument.
The project is bound once, here, following `ProjectCorpusReader`.

The mapping in `_outcome` is the one place `check_name` becomes `check`. The
column is spelled differently from the field it holds because `CHECK` is a
SQLite keyword and the schema generator does not quote identifiers -- see
`CheckOutcomeRow`'s docstring for what that cost. Everything above this line
says `check`, and this function is the seam that keeps it that way.
"""

from uuid import UUID

from research_team.application.check_telemetry_read import (
    CheckOutcome,
    CheckStat,
    CheckTelemetryReadError,
    summarise,
)
from research_team.infrastructure.persistence.check_telemetry import (
    CheckOutcomeRow,
    CheckTelemetryRunner,
)


def _outcome(row: CheckOutcomeRow) -> CheckOutcome:
    """One stored row, in the terms the aggregation speaks.

    A translation rather than a pass-through, because `summarise` lives in
    `application/` and cannot name a `ReadModel`. Only the columns the
    arithmetic reads cross over: `severity`, `stage` and the preset fields stay
    in storage until something asks for them.
    """
    return CheckOutcome(
        check=row.check_name,
        status=row.status,
        findings=row.findings,
        posed_by=row.posed_by,
        evaluated_at=row.evaluated_at,
        decision=row.decision,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


class ProjectCheckTelemetryReader:
    """`CheckTelemetryReadPort` over `CheckTelemetryRunner`, fixed to one project."""

    def __init__(self, runner: CheckTelemetryRunner, project_id: UUID) -> None:
        self._runner = runner
        self._project_id = project_id

    async def stats(self) -> list[CheckStat]:
        try:
            rows = await self._runner.outcomes(self._project_id)
        except RuntimeError as error:
            # The runner raises this when its projection was never started,
            # which is a wiring fault rather than an absence of measurements --
            # and the two must not render alike, because one of them is "no
            # gate has run yet" and the other is "this instrument is off".
            raise CheckTelemetryReadError(str(error)) from error
        return summarise(_outcome(row) for row in rows)
