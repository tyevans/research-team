"""The five reads the explorer needs, over the interaction log's SQLite table.

Query metrics helpers, summary and page models, and `InteractionLogReader`.
Extracted from `interaction_log.py`.
"""

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import aiosqlite
from pydantic import BaseModel

from research_team.domain.interaction import INTERACTION_EVENTS

if TYPE_CHECKING:
    from research_team.infrastructure.persistence.interaction_log import InteractionEventRow

REPEAT_SEARCH_MAX_DISTANCE_RATIO = 0.3
"""How different two consecutive searches may be and still count as a repeat.

Levenshtein distance over the normalised text, divided by the longer of the
two lengths -- so 0.3 means "up to a third of the characters changed". A
reformulation like `roman senate` -> `the roman senate` scores 0.25 and counts;
`roman senate` -> `carthage` scores 1.0 and does not.

**A heuristic, and never a measurement.** There is no corpus of real searches
to tune this against -- the log is what would produce one -- so the number it
produces is a pointer to a stream worth reading by eye, not a friction rate.
Reasoned, not measured. Revisit once the log holds real searches: if a
plausible reformulation scores above this, the count is missing the signal it
exists for.
"""

VIEW_DWELL_PERCENTILE = 0.9
"""The `p90` in `by_view`, by nearest-rank rather than by interpolation.

Nearest-rank returns a dwell that some view exit actually had, which is what
makes the number checkable against the feed below it; an interpolated
percentile returns a duration nobody experienced.
"""


def _normalised_query(text: str) -> str:
    """Lowercased, whitespace collapsed. The spec's definition, in one place."""
    return " ".join(text.lower().split())


def _edit_distance(left: str, right: str) -> int:
    """Levenshtein, two rows rather than a full matrix.

    Written out rather than taken from a dependency: it is used on one pair of
    bounded strings (`QUERY_TEXT_MAX_LENGTH`) per search, and a library for it
    would be a dependency added for eleven lines.
    """
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _is_repeat_search(previous: str, current: str) -> bool:
    """Whether `current` is a near-repeat of `previous`, both already
    normalised."""
    longest = max(len(previous), len(current))
    if longest == 0:
        return True
    return _edit_distance(previous, current) / longest <= REPEAT_SEARCH_MAX_DISTANCE_RATIO


def _median(values: Sequence[int]) -> int | None:
    """The middle value, or None over nothing.

    None rather than 0: a view nobody exited and a view exited instantly are
    different facts, and 0 makes them one.
    """
    if not values:
        return None
    return int(statistics.median(values))


def _percentile(values: Sequence[int], fraction: float) -> int | None:
    """Nearest-rank percentile -- see `VIEW_DWELL_PERCENTILE`."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


class InteractionLogHealth(BaseModel):
    """Whether the instrument is working, and how much it has seen.

    Carries neither `collecting` nor `failures`: the first is a fact about the
    recorder's environment variable and belongs to the route, the second comes
    from the runner's DLQ. A reader that reported either would be guessing at
    something it cannot see.
    """

    total: int
    first_at: datetime | None
    last_at: datetime | None
    kinds: dict[str, int]
    """Every kind in `INTERACTION_EVENTS`, zeros included, plus any kind found
    in the table that the vocabulary no longer names. A dict built from what
    the table happens to hold makes "never emitted" and "does not exist" look
    identical, which is the defect this shape exists to prevent."""
    install_count: int
    session_count: int


class BrowserSessionRow(BaseModel):
    """One browser session, summarised."""

    browser_session_id: UUID
    install_id: UUID
    started_at: datetime | None
    ended_at: datetime | None
    event_count: int
    """What arrived. Beside `max_seq` on purpose: `seq` is the browser's own
    counter, so the two disagree exactly when delivery lost something."""
    max_seq: int
    views: list[str]
    project_ids: list[UUID]
    kinds: dict[str, int]


class BrowserSessionPage(BaseModel):
    sessions: list[BrowserSessionRow]
    total: int


class InteractionEventPage(BaseModel):
    events: list["InteractionEventRow"]
    total: int
    """The count under the same filters, never the page length. A reader who
    cannot tell 200-of-200 from 200-of-9000 cannot tell a filter that found
    everything from one that hit the cap."""
    limit: int
    offset: int


class ViewDwell(BaseModel):
    """One view's traffic and how long people stayed."""

    view: str
    entries: int
    """`ViewEntered` for this view."""
    exits: int
    """`ViewExited` for this view. Reported apart from `entries` because the
    difference is the count of views left by a route the page-hide flush did
    not catch."""
    dwell_ms_median: int | None
    dwell_ms_p90: int | None
    hidden_ms_median: int | None
    """Reported beside dwell and never subtracted from it -- `ViewExited`'s own
    docstring gives the reason, and it holds here: the consumer chooses."""


class EmptyResultPlace(BaseModel):
    where: str
    count: int


class FrictionSummary(BaseModel):
    """The signals the vocabulary was built to carry."""

    undone: int
    retried: int
    empty_results: int
    empty_by_where: list[EmptyResultPlace]
    repeat_searches: int
    """Searches within `REPEAT_SEARCH_MAX_DISTANCE_RATIO` of the immediately
    previous search in the same browser session. A heuristic pointer to a
    stream worth reading, never a measurement -- see the constant."""


class ApprovalSummary(BaseModel):
    """The deliberation split `docs/direction.md` §3 turns on."""

    total: int
    expanded: int
    """`expanded_details == true`. **The name overstates it**, exactly as that
    field's own docstring says: it counts readers who opened Edit or Respond,
    so a careful reader who deliberates and then presses plain Approve records
    `false`. Read it as a floor on deliberation, never as a count of who read
    carefully. The caveat is repeated here rather than renamed away, because
    every plausible rename carries the same ambiguity one word further out."""
    median_latency_ms: int | None
    median_latency_ms_expanded: int | None
    median_latency_ms_plain: int | None
    by_decision: dict[str, int]


class InteractionSummary(BaseModel):
    by_kind: dict[str, int]
    by_view: list[ViewDwell]
    friction: FrictionSummary
    approvals: ApprovalSummary


def _timestamp_sql(column: str) -> str:
    """`column`, normalised to a comparable UTC string.

    Both sides of every time comparison go through this, because the stored
    text is not one format: pydantic writes `occurred_at` with a `Z` and the
    envelope columns with `+00:00`, and a raw `>=` between the two orders
    `...39.9Z` before `...39Z` -- `.` sorts below `Z`, so a bound on a whole
    second silently drops the rows within it.

    The cost is that `idx_interaction_events_kind`'s `occurred_at` half cannot
    serve a range scan. Accepted: the spec's own retention note puts this table
    years away from a million rows, and every read here already scans for a
    filter no index covers.
    """
    return f"strftime('%Y-%m-%dT%H:%M:%f', {column})"


def _parse_timestamp(value: str | None) -> datetime | None:
    """Back from `_timestamp_sql`'s form, which carries no offset of its own."""
    if value is None:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class InteractionLogReader:
    """The five reads the explorer needs, over the store's own connection.

    **Not the runner.** The runner owns a subscription, a checkpoint
    repository and a lifecycle; none of that is needed to answer a GET, and
    holding it would make every route test start a projection.

    Filtering, grouping and counting are SQL, because SQLite does them over the
    whole table without moving rows into Python. Every median is Python over
    the filtered rows, because SQLite has no median and a percentile written in
    SQL here would be an approximation nobody could check. The split is per
    read and stated at each one.
    """

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _row_type() -> type["InteractionEventRow"]:
        from research_team.infrastructure.persistence.interaction_log import (
            InteractionEventRow,
        )

        return InteractionEventRow

    async def health(self) -> InteractionLogHealth:
        """Totals, the window the log covers, and every kind's count."""
        table = self._row_type().table_name()
        async with self._connection.execute(
            f"SELECT COUNT(*), MIN({_timestamp_sql('occurred_at')}),"
            f" MAX({_timestamp_sql('occurred_at')}),"
            " COUNT(DISTINCT install_id), COUNT(DISTINCT browser_session_id)"
            f" FROM {table}"
        ) as cursor:
            total, first_at, last_at, installs, sessions = await cursor.fetchone()

        # Zeros first, from the vocabulary, then whatever the table holds. A
        # kind the table carries and the tuple no longer names survives the
        # merge rather than being dropped: an orphaned kind is a projection or
        # a vocabulary change worth seeing, and silently filtering it would
        # make it invisible in exactly the way this dict exists to prevent.
        kinds = {event_type.__name__: 0 for event_type in INTERACTION_EVENTS}
        async with self._connection.execute(
            f"SELECT kind, COUNT(*) FROM {table} GROUP BY kind"
        ) as cursor:
            for kind, count in await cursor.fetchall():
                kinds[kind] = count

        return InteractionLogHealth(
            total=total,
            first_at=_parse_timestamp(first_at),
            last_at=_parse_timestamp(last_at),
            kinds=kinds,
            install_count=installs,
            session_count=sessions,
        )

    async def sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        install_id: UUID | None = None,
        project_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> BrowserSessionPage:
        """One row per browser session, newest first, plus the count under the
        same filters.

        `project_id` selects sessions that touched that project and then
        summarises the *whole* session, not the part of it in that project.
        Deliberate: a session is a visit, and a visit cut at a project boundary
        stops being readable as one story -- which is the row's whole purpose.
        """
        table = self._row_type().table_name()
        where, params = self._scope(
            install_id=install_id, project_id=project_id, since=since, until=until
        )
        sessions_matching = f"SELECT DISTINCT browser_session_id FROM {table} WHERE {where}"

        async with self._connection.execute(
            f"SELECT COUNT(*) FROM ({sessions_matching})", params
        ) as cursor:
            (total,) = await cursor.fetchone()

        # Ordered by the session's last event rather than its first: "newest
        # first" is about what happened most recently, and a long session that
        # opened yesterday and is still going belongs above one that opened and
        # closed this morning.
        page_params = dict(params, page_limit=limit, page_offset=offset)
        async with self._connection.execute(
            "SELECT browser_session_id, MIN(install_id),"
            f" MIN({_timestamp_sql('occurred_at')}), MAX({_timestamp_sql('occurred_at')}),"
            " COUNT(*), MAX(seq)"
            f" FROM {table} WHERE browser_session_id IN ({sessions_matching})"
            " GROUP BY browser_session_id"
            f" ORDER BY MAX({_timestamp_sql('occurred_at')}) DESC, browser_session_id DESC"
            " LIMIT :page_limit OFFSET :page_offset",
            page_params,
        ) as cursor:
            grouped = await cursor.fetchall()

        rows: list[BrowserSessionRow] = []
        for browser_session_id, install, started, ended, count, max_seq in grouped:
            # Views, projects and kinds per session in a second pass rather
            # than as SQL aggregates: SQLite's `group_concat` would hand back a
            # comma-joined string that has to be split in Python anyway, and a
            # view name containing a comma would silently split into two.
            async with self._connection.execute(
                f"SELECT view, project_id, kind FROM {table}"
                " WHERE browser_session_id = :browser_session_id",
                {"browser_session_id": browser_session_id},
            ) as cursor:
                detail = await cursor.fetchall()
            views: list[str] = []
            projects: list[str] = []
            kinds: Counter[str] = Counter()
            for view, project, kind in detail:
                if view not in views:
                    views.append(view)
                if project is not None and project not in projects:
                    projects.append(project)
                kinds[kind] += 1
            rows.append(
                BrowserSessionRow(
                    browser_session_id=browser_session_id,
                    install_id=install,
                    started_at=_parse_timestamp(started),
                    ended_at=_parse_timestamp(ended),
                    event_count=count,
                    max_seq=max_seq,
                    views=views,
                    project_ids=projects,
                    kinds=dict(kinds),
                )
            )
        return BrowserSessionPage(sessions=rows, total=total)

    async def session(self, browser_session_id: UUID) -> list["InteractionEventRow"] | None:
        """One session's whole stream, `seq` ascending, or None when no row
        carries that id.

        None rather than an empty list, so the route can answer 404 for an
        unknown session and 200 for a real one -- which are different answers
        and a bare `[]` cannot tell apart. Unpaged: a browser session is
        bounded by a tab's life.
        """
        row_cls = self._row_type()
        table = row_cls.table_name()
        async with self._connection.execute(
            f"SELECT * FROM {table} WHERE browser_session_id = :browser_session_id"
            " ORDER BY seq ASC",
            {"browser_session_id": str(browser_session_id)},
        ) as cursor:
            columns = [column[0] for column in cursor.description]
            found = await cursor.fetchall()
        if not found:
            return None
        return [row_cls(**dict(zip(columns, row, strict=True))) for row in found]

    async def events(
        self,
        kinds: Sequence[str] | None = None,
        views: Sequence[str] | None = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
        order: str = "newest",
    ) -> InteractionEventPage:
        """A page of events, plus the count under the same filters."""
        row_cls = self._row_type()
        table = row_cls.table_name()
        where, params = self._scope(
            kinds=kinds,
            views=views,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=since,
            until=until,
        )
        async with self._connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ) as cursor:
            (total,) = await cursor.fetchone()

        # `seq` breaks the tie rather than `id`, so two events one batch
        # delivered in the same millisecond still read in the order the browser
        # put them in.
        direction = "ASC" if order == "oldest" else "DESC"
        async with self._connection.execute(
            f"SELECT * FROM {table} WHERE {where}"
            f" ORDER BY {_timestamp_sql('occurred_at')} {direction}, seq {direction}"
            " LIMIT :page_limit OFFSET :page_offset",
            dict(params, page_limit=limit, page_offset=offset),
        ) as cursor:
            columns = [column[0] for column in cursor.description]
            found = await cursor.fetchall()

        return InteractionEventPage(
            events=[row_cls(**dict(zip(columns, row, strict=True))) for row in found],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def summary(
        self,
        kinds: Sequence[str] | None = None,
        views: Sequence[str] | None = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> InteractionSummary:
        """Aggregates over the same window `events` pages.

        Counts and groupings are SQL; the four numbers that are medians pull
        their inputs into Python, because those are the values a median needs
        all of and SQLite cannot take one.
        """
        where, params = self._scope(
            kinds=kinds,
            views=views,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=since,
            until=until,
        )
        return InteractionSummary(
            by_kind=await self._by_kind(where, params),
            by_view=await self._by_view(where, params),
            friction=await self._friction(where, params),
            approvals=await self._approvals(where, params),
        )

    async def _by_kind(self, where: str, params: dict[str, object]) -> dict[str, int]:
        table = self._row_type().table_name()
        counts = {event_type.__name__: 0 for event_type in INTERACTION_EVENTS}
        async with self._connection.execute(
            f"SELECT kind, COUNT(*) FROM {table} WHERE {where} GROUP BY kind", params
        ) as cursor:
            for kind, count in await cursor.fetchall():
                counts[kind] = count
        return counts

    async def _by_view(self, where: str, params: dict[str, object]) -> list[ViewDwell]:
        table = self._row_type().table_name()
        async with self._connection.execute(
            f"SELECT view, COUNT(*) FROM {table} WHERE {where} AND kind = 'ViewEntered'"
            " GROUP BY view",
            params,
        ) as cursor:
            entries = dict(await cursor.fetchall())

        # Decoded in Python rather than grouped in SQL, because the medians
        # need every value and not a count -- one pass over the exits is
        # cheaper than a group-by plus a second query for the same rows.
        async with self._connection.execute(
            "SELECT view, json_extract(payload, '$.dwell_ms'),"
            " json_extract(payload, '$.hidden_ms')"
            f" FROM {table} WHERE {where} AND kind = 'ViewExited'",
            params,
        ) as cursor:
            exits = await cursor.fetchall()

        dwells: dict[str, list[int]] = defaultdict(list)
        hidden: dict[str, list[int]] = defaultdict(list)
        exit_counts: Counter[str] = Counter()
        for view, dwell_ms, hidden_ms in exits:
            exit_counts[view] += 1
            if dwell_ms is not None:
                dwells[view].append(int(dwell_ms))
            if hidden_ms is not None:
                hidden[view].append(int(hidden_ms))

        # Busiest first, name as the tiebreak, so the order is stable across
        # two calls with the same data.
        views = sorted(
            set(entries) | set(exit_counts),
            key=lambda view: (-entries.get(view, 0), -exit_counts[view], view),
        )
        return [
            ViewDwell(
                view=view,
                entries=entries.get(view, 0),
                exits=exit_counts[view],
                dwell_ms_median=_median(dwells[view]),
                dwell_ms_p90=_percentile(dwells[view], VIEW_DWELL_PERCENTILE),
                hidden_ms_median=_median(hidden[view]),
            )
            for view in views
        ]

    async def _friction(self, where: str, params: dict[str, object]) -> FrictionSummary:
        table = self._row_type().table_name()
        async with self._connection.execute(
            f"SELECT kind, COUNT(*) FROM {table} WHERE {where}"
            " AND kind IN ('ActionUndone', 'ActionRetried', 'EmptyResultEncountered')"
            " GROUP BY kind",
            params,
        ) as cursor:
            counts = dict(await cursor.fetchall())

        # `where` is JSON, and grouping it in SQL rather than in Python keeps
        # the count and the group in one pass over the same rows.
        async with self._connection.execute(
            "SELECT json_extract(payload, '$.where'), COUNT(*)"
            f" FROM {table} WHERE {where} AND kind = 'EmptyResultEncountered'"
            " GROUP BY json_extract(payload, '$.where')"
            " ORDER BY COUNT(*) DESC, json_extract(payload, '$.where') ASC",
            params,
        ) as cursor:
            places = await cursor.fetchall()

        return FrictionSummary(
            undone=counts.get("ActionUndone", 0),
            retried=counts.get("ActionRetried", 0),
            empty_results=counts.get("EmptyResultEncountered", 0),
            empty_by_where=[
                EmptyResultPlace(where=place or "", count=count) for place, count in places
            ],
            repeat_searches=await self._repeat_searches(where, params),
        )

    async def _repeat_searches(self, where: str, params: dict[str, object]) -> int:
        """Searches that near-repeat the one before them in the same session.

        Ordered by `seq` rather than by `occurred_at`: `seq` is the browser's
        own counter and the ordering authority the vocabulary names, and two
        searches typed inside one clock tick have no order at all under a
        timestamp.
        """
        table = self._row_type().table_name()
        async with self._connection.execute(
            "SELECT browser_session_id, json_extract(payload, '$.query_text')"
            f" FROM {table} WHERE {where} AND kind = 'SearchPerformed'"
            " ORDER BY browser_session_id, seq ASC",
            params,
        ) as cursor:
            searches = await cursor.fetchall()

        repeats = 0
        previous_session: str | None = None
        previous_text = ""
        for browser_session_id, query_text in searches:
            current = _normalised_query(query_text or "")
            if browser_session_id == previous_session and _is_repeat_search(
                previous_text, current
            ):
                repeats += 1
            previous_session = browser_session_id
            previous_text = current
        return repeats

    async def _approvals(self, where: str, params: dict[str, object]) -> ApprovalSummary:
        table = self._row_type().table_name()
        # Every column here feeds either a median or a split of one, so the
        # rows come back whole rather than as three separate aggregates.
        async with self._connection.execute(
            "SELECT json_extract(payload, '$.decision'),"
            " json_extract(payload, '$.latency_ms'),"
            " json_extract(payload, '$.expanded_details')"
            f" FROM {table} WHERE {where} AND kind = 'ApprovalDecided'",
            params,
        ) as cursor:
            decided = await cursor.fetchall()

        by_decision: Counter[str] = Counter()
        latencies: list[int] = []
        expanded_latencies: list[int] = []
        plain_latencies: list[int] = []
        expanded = 0
        for decision, latency_ms, expanded_details in decided:
            by_decision[decision or ""] += 1
            # SQLite hands a JSON boolean back as 1 or 0.
            was_expanded = bool(expanded_details)
            if was_expanded:
                expanded += 1
            if latency_ms is None:
                continue
            latencies.append(int(latency_ms))
            (expanded_latencies if was_expanded else plain_latencies).append(int(latency_ms))

        return ApprovalSummary(
            total=len(decided),
            expanded=expanded,
            median_latency_ms=_median(latencies),
            median_latency_ms_expanded=_median(expanded_latencies),
            median_latency_ms_plain=_median(plain_latencies),
            by_decision=dict(by_decision),
        )

    def _scope(
        self,
        kinds: Sequence[str] | None = None,
        views: Sequence[str] | None = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[str, dict[str, object]]:
        """The WHERE every read shares, and its parameters.

        Every value is bound, never interpolated. The only text this builds
        into SQL is placeholder *names* it generates itself (`:kind_0`), which
        no caller can influence.

        Returns `1 = 1` for no filters rather than an empty string, so each
        call site can write `WHERE {where} AND ...` without a branch -- and a
        forgotten branch there is a filter silently dropped.
        """
        clauses = ["1 = 1"]
        params: dict[str, object] = {}
        for name, values in (("kind", kinds), ("view", views)):
            if not values:
                continue
            placeholders = []
            for index, value in enumerate(values):
                key = f"{name}_{index}"
                params[key] = value
                placeholders.append(f":{key}")
            clauses.append(f"{name} IN ({', '.join(placeholders)})")
        for column, value in (
            ("project_id", project_id),
            ("session_id", session_id),
            ("install_id", install_id),
            ("browser_session_id", browser_session_id),
        ):
            if value is None:
                continue
            params[column] = str(value)
            clauses.append(f"{column} = :{column}")
        for column, bound, comparison in (
            ("since", since, ">="),
            ("until", until, "<="),
        ):
            if bound is None:
                continue
            params[column] = bound.astimezone(UTC).isoformat()
            clauses.append(
                f"{_timestamp_sql('occurred_at')} {comparison} {_timestamp_sql(':' + column)}"
            )
        return " AND ".join(clauses), params
