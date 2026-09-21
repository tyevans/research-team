"""Course authoring run read models, projections, stores, and runners.

Houses read-side state and projections for authoring runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import aiosqlite
from eventsource import DeclarativeProjection, ReadModel, handles
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository
from pydantic import Field, field_validator

from research_team.domain.curriculum.authoring_run import (
    COURSE_AUTHORING_RUN_AGGREGATE_TYPE,
    CourseAuthored,
    CourseAuthoringFailed,
    CourseAuthoringRunSettled,
    CourseAuthoringRunStarted,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "AuthoringRunProjection",
    "AuthoringRunRow",
    "AuthoringRunRunner",
    "AuthoringRunStore",
]


class AuthoringRunRow(ReadModel):
    """One course-authoring run. `id` is the run id.

    The aggregate id itself with no `uuid5` over it, for `AskConversationRow`'s
    reason: the run id is minted by the server and handed straight back on the
    202, so deriving a second one would give the catch-up route a key nothing
    ever returned.

    **One table, not two, and `authored` holds pairs.** The neighbouring
    two-table stores exist because something queries the child rows on their
    own -- a conversation's turns, a class's members. Nothing queries one
    authoring target: every read here is "the whole run", because the frame the
    browser renders is the whole run. So a target table would buy an index for
    a query nobody issues and cost a second write per target.

    Pairs rather than parallel `completed`/`sessions` lists, even though the
    wire frame carries them parallel: `courseLinks` in the browser has to
    defend against a length mismatch between those two, and a store that cannot
    produce one is better than a store that documents what to do about it. The
    frame is built by unzipping this, which makes the two arrays equal in
    length by construction rather than by care.

    **No `current` column, deliberately.** Which area is in hand right now is
    process state -- see `course_authoring_run.py` -- and a stored one would
    outlive the process driving it and assert that work is in progress when
    nothing is doing it.

    **No `settled_at` column either.** `last()` orders by `started_at`, and a
    nullable datetime that only three of five statuses ever fill would be a
    column read by nothing. The settling *time* is on the log if it is ever
    wanted; what a reader needs here is the settling *status*.
    """

    __table_name__ = "authoring_runs"

    project_id: UUID
    kind: str = ""
    status: str = "running"
    started_at: datetime
    targets: list[str] = Field(default_factory=list)
    authored: list[dict] = Field(default_factory=list)
    """`[{"target": ..., "session_id": ...}]`, in the order the run wrote them.

    `session_id` is the load-bearing half and the reason this table exists: the
    course markdown lives in that session's event-sourced workspace, and
    nothing else on the log records which session holds which area."""
    failures: list[dict] = Field(default_factory=list)
    """`[{"target": ..., "detail": ...}]`. Per target, because a run that wrote
    seven of eight is `done` with one failure listed."""

    @field_validator("targets", "authored", "failures", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        """Accept the JSON text SQLite hands back for a list column -- see
        `SessionSummaryRow._decode_json_list` on the asymmetry this hides."""
        if isinstance(value, str):
            return json.loads(value)
        return value


class AuthoringRunStore(BaseReadModelStore):
    """The `authoring_runs` table and the connection it owns.

    Every column is written from an event payload, so `rebuild()` may truncate
    -- unlike `EntityDefinitionStore`, nothing else writes here.
    """

    def __init__(
        self, connection: aiosqlite.Connection, rows: ReadModelRepository[AuthoringRunRow]
    ) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> AuthoringRunStore:
        connection = await open_readmodel_connection(db_path, AuthoringRunRow)
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. The only read that is not by id is
        # `latest_for_project`, which runs on every open of the curriculum
        # pane; unindexed it would scan every run every project has ever made.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_authoring_runs_project "
            f"ON {AuthoringRunRow.table_name()}(project_id, started_at)"
        )
        await connection.commit()
        return cls(connection, SQLiteReadModelRepository(connection, AuthoringRunRow, tracer))

    async def start(
        self,
        run_id: UUID,
        project_id: UUID,
        *,
        kind: str,
        targets: list[str],
        started_at: datetime,
    ) -> None:
        await self._rows.save(
            AuthoringRunRow(
                id=run_id,
                project_id=project_id,
                kind=kind,
                started_at=started_at,
                targets=targets,
            )
        )

    async def record_authored(self, run_id: UUID, target: str, session_id: UUID) -> None:
        """Append one target's session, unless this target is already recorded.

        The existence check is what makes redelivery safe. A subscription that
        is restarted from a checkpoint written before its last handler returned
        replays that event, and an unconditional append would put the same
        course in the list twice -- which reads, on every surface, as a run that
        authored more targets than it had.
        """
        row = await self._rows.get(run_id)
        if row is None:
            return
        if any(entry.get("target") == target for entry in row.authored):
            return
        row.authored = [*row.authored, {"target": target, "session_id": str(session_id)}]
        await self._rows.save(row)

    async def record_failure(self, run_id: UUID, target: str, detail: str) -> None:
        """Append one target's failure, unless this target already has one.

        Deduplicated on `target` for `record_authored`'s reason. A target can
        only fail once per run -- the driving loop moves on after it -- so the
        target alone is the identity, and the detail of a redelivered event is
        by construction the same string.
        """
        row = await self._rows.get(run_id)
        if row is None:
            return
        if any(entry.get("target") == target for entry in row.failures):
            return
        row.failures = [*row.failures, {"target": target, "detail": detail}]
        await self._rows.save(row)

    async def settle(self, run_id: UUID, status: str) -> None:
        row = await self._rows.get(run_id)
        if row is None:
            return
        row.status = status
        await self._rows.save(row)

    async def get(self, run_id: UUID) -> AuthoringRunRow | None:
        return await self._rows.get(run_id)

    async def recent_for_project(
        self, project_id: UUID, limit: int = 2
    ) -> list[AuthoringRunRow]:
        """This project's runs, most recently started first.

        Ordered by `started_at` and not by insertion order, for
        `AskTurnRow.position`'s reason: a `rebuild()` truncates and replays and
        is free to insert rows in a different physical order, so a read that
        leaned on the table's order would answer correctly until the first
        rebuild and differently after it.

        The default limit is 2 because that is what the one caller needs:
        `AuthoringActivity.last` wants the newest run that is *not* the one it
        is currently driving, and at most one run per project is ever in
        flight -- so the second row is the deepest it can have to look.
        """
        return await self._rows.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="started_at",
                order_direction="desc",
                limit=limit,
            )
        )

    async def latest_for_project(self, project_id: UUID) -> AuthoringRunRow | None:
        """This project's most recently started run, or None if it has had none."""
        found = await self.recent_for_project(project_id, limit=1)
        return found[0] if found else None

    async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None:
        """Which session holds `target`'s course markdown, or None if no run
        has ever authored it.

        Scans newest `started_at` first and returns the first match, so a
        target authored twice resolves to the session its *current* course
        actually lives in. `recent_for_project`'s own default `limit=2` is
        wrong here and is not reused: that default is tuned for
        `AuthoringActivity.last`, which only ever needs the run before the one
        in flight, but a course's session can have been written many runs
        ago -- inheriting 2 would make the link vanish the moment a third
        later run happens, indistinguishable from the course never having
        been authored. 200 is arbitrary but generous against any project's
        real run count.

        Filtered in Python, not SQL: `authored` is a JSON column, and a
        `json_each` query would tie this read to SQLite in a file whose other
        reads (`Query`/`Filter`) are backend-agnostic.
        """
        for row in await self.recent_for_project(project_id, limit=200):
            for entry in row.authored:
                if entry.get("target") == target:
                    return UUID(entry["session_id"])
        return None

    async def truncate(self) -> None:
        await self._truncate_tables(AuthoringRunRow)


class AuthoringRunProjection(DeclarativeProjection):
    """Writes course-authoring runs into the table above.

    Nothing else writes it, which is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        runs: AuthoringRunStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._runs = runs
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseAuthoringRunStarted)
    async def _on_started(self, event: CourseAuthoringRunStarted) -> None:
        await self._runs.start(
            event.aggregate_id,
            event.project_id,
            kind=event.kind,
            targets=list(event.targets),
            started_at=event.started_at,
        )

    @handles(CourseAuthored)
    async def _on_authored(self, event: CourseAuthored) -> None:
        await self._runs.record_authored(event.aggregate_id, event.target, event.session_id)

    @handles(CourseAuthoringFailed)
    async def _on_failed(self, event: CourseAuthoringFailed) -> None:
        await self._runs.record_failure(event.aggregate_id, event.target, event.detail)

    @handles(CourseAuthoringRunSettled)
    async def _on_settled(self, event: CourseAuthoringRunSettled) -> None:
        await self._runs.settle(event.aggregate_id, event.status)


class AuthoringRunRunner(BaseProjectionRunner[AuthoringRunStore]):
    """Keeps the authoring-run table following the log, and answers from it.

    A tenth runner, for the reasons `CorpusRunner`'s docstring gives for being
    a second: a `rebuild()`/`failures()`-shaped surface for this table alone,
    and a `rebuild()` that cannot truncate a table it does not own.

    Its failure mode if never constructed is `AskConversationRunner`'s and
    worse: an authoring run appends whether or not anything is following, so a
    build missing it answers every catch-up read with "no run has ever
    happened" while the courses sit on the log unfindable -- which is the exact
    bug this whole aggregate was added to fix, restored by an unwired line.
    `test_an_authoring_run_survives_a_restart.py` is what fails.
    """

    _label = "authoring"
    _store_class = AuthoringRunStore
    _projection_class = AuthoringRunProjection
    _caught_up_aggregate_types = (COURSE_AUTHORING_RUN_AGGREGATE_TYPE,)

    @property
    def _runs(self) -> AuthoringRunStore | None:
        return self._store_instance

    async def get(self, run_id: UUID) -> AuthoringRunRow | None:
        return await self._started().get(run_id)

    async def latest_for_project(self, project_id: UUID) -> AuthoringRunRow | None:
        return await self._started().latest_for_project(project_id)

    async def recent_for_project(
        self, project_id: UUID, limit: int = 2
    ) -> list[AuthoringRunRow]:
        return await self._started().recent_for_project(project_id, limit)

    async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None:
        return await self._started().authored_session_for(project_id, target)
