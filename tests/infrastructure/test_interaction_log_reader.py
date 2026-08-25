"""The five reads the explorer is built on.

Every assertion is on a number the reader computed from rows written through
`store.record`, never on a call returning. A test that asserts a read did not
raise passes with the projection deleted and proves nothing -- see
`CLAUDE.md`, "Events".
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from research_team.domain.interaction import (
    INTERACTION_EVENTS,
    ActionRetried,
    ActionUndone,
    ApprovalDecided,
    EmptyResultEncountered,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)
from research_team.infrastructure.persistence.interaction_log import (
    InteractionLogRunner,
    InteractionLogStore,
)

BASE = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


class _Session:
    """A browser session, minting seq for its own events.

    The counter is the browser's job in production, and a test that spells it
    by hand gets the ordering assertions wrong by transcription rather than by
    logic.
    """

    def __init__(self, install_id=None, project_id=None):
        self.id = uuid4()
        self.install_id = install_id or uuid4()
        self.project_id = project_id
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def event(self, event_type, minutes: float = 0, view: str = "home", **fields):
        return event_type(
            aggregate_id=self.id,
            install_id=self.install_id,
            seq=self._next(),
            view=view,
            occurred_at=_at(minutes),
            project_id=fields.pop("project_id", self.project_id),
            **fields,
        )


@pytest.fixture
async def store(db_path):
    opened = await InteractionLogStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def _record(store, *events):
    for event in events:
        await store.record(event)


async def test_health_names_every_kind_in_the_vocabulary_including_the_unused(store):
    """The keys come from `INTERACTION_EVENTS` by introspection.

    Derived rather than written out: a hand-written list is the failure
    `CLAUDE.md` records under the checkpoint markers, and a kind added to the
    tuple and missing from `health` has to fail here rather than be noticed.
    """
    session = _Session()
    await _record(store, session.event(ViewEntered, minutes=0))

    health = await store.reader.health()

    assert set(health.kinds) == {event_type.__name__ for event_type in INTERACTION_EVENTS}
    assert health.kinds["ViewEntered"] == 1
    assert health.kinds["ApprovalDecided"] == 0


async def test_health_counts_installs_sessions_and_the_window_they_cover(store):
    first = _Session()
    second = _Session(install_id=first.install_id)
    third = _Session()
    await _record(
        store,
        first.event(ViewEntered, minutes=0),
        first.event(ViewExited, minutes=5, dwell_ms=300_000),
        second.event(ViewEntered, minutes=10),
        third.event(ViewEntered, minutes=20),
    )

    health = await store.reader.health()

    assert health.total == 4
    assert health.session_count == 3
    assert health.install_count == 2
    assert health.first_at == _at(0)
    assert health.last_at == _at(20)


async def test_health_over_an_empty_log_reports_no_window_rather_than_an_epoch(store):
    health = await store.reader.health()

    assert health.total == 0
    assert health.first_at is None
    assert health.last_at is None
    assert health.kinds["ViewEntered"] == 0


async def test_sessions_come_back_newest_first_with_their_views_and_kinds(store):
    older = _Session()
    newer = _Session()
    await _record(
        store,
        older.event(ViewEntered, minutes=0, view="home"),
        older.event(ViewEntered, minutes=1, view="project/catalog"),
        newer.event(ViewEntered, minutes=30, view="home"),
    )

    page = await store.reader.sessions()

    assert page.total == 2
    assert [row.browser_session_id for row in page.sessions] == [newer.id, older.id]
    assert page.sessions[1].views == ["home", "project/catalog"]
    assert page.sessions[1].kinds == {"ViewEntered": 2}
    assert page.sessions[1].started_at == _at(0)
    assert page.sessions[1].ended_at == _at(1)


async def test_a_session_reports_what_arrived_beside_what_the_browser_counted(store):
    """`event_count` and `max_seq` disagree exactly when delivery lost
    something, which is the cheapest integrity check on the transport."""
    session = _Session()
    first = session.event(ViewEntered, minutes=0)
    session._next()  # the seq of an event that never arrived
    third = session.event(ViewEntered, minutes=1)
    await _record(store, first, third)

    page = await store.reader.sessions()

    assert page.sessions[0].event_count == 2
    assert page.sessions[0].max_seq == 3


async def test_sessions_filter_by_install_and_by_window(store):
    mine = _Session()
    theirs = _Session()
    await _record(
        store,
        mine.event(ViewEntered, minutes=0),
        theirs.event(ViewEntered, minutes=0),
    )

    page = await store.reader.sessions(install_id=mine.install_id)
    assert [row.browser_session_id for row in page.sessions] == [mine.id]
    assert page.total == 1

    assert (await store.reader.sessions(since=_at(1))).total == 0
    assert (await store.reader.sessions(until=_at(-1))).total == 0
    assert (await store.reader.sessions(since=_at(0), until=_at(0))).total == 2


async def test_session_returns_none_for_an_id_no_row_carries(store):
    """None rather than `[]`, so the route can tell 404 from an empty
    session."""
    session = _Session()
    await _record(store, session.event(ViewEntered))

    assert await store.reader.session(uuid4()) is None


async def test_session_returns_the_stream_ascending_by_seq(store):
    session = _Session()
    third = session.event(ViewEntered, minutes=2, view="third")
    first = session.event(ViewEntered, minutes=0, view="first")
    second = session.event(ViewEntered, minutes=1, view="second")
    # Written out of order on purpose: the reader must sort, not preserve
    # insertion.
    await _record(store, third, first, second)

    stream = await store.reader.session(session.id)

    assert [row.view for row in stream] == ["third", "first", "second"]
    assert [row.seq for row in stream] == [1, 2, 3]


async def test_events_total_counts_the_filter_not_the_page(store):
    """A reader who cannot tell 2-of-2 from 2-of-5 cannot tell a filter that
    found everything from one that hit the cap."""
    session = _Session()
    await _record(store, *[session.event(ViewEntered, minutes=index) for index in range(5)])

    page = await store.reader.events(limit=2)

    assert len(page.events) == 2
    assert page.total == 5
    assert page.limit == 2


async def test_events_order_newest_first_by_default_and_oldest_on_request(store):
    session = _Session()
    await _record(
        store,
        session.event(ViewEntered, minutes=0, view="first"),
        session.event(ViewEntered, minutes=1, view="second"),
    )

    newest = await store.reader.events()
    oldest = await store.reader.events(order="oldest")

    assert [row.view for row in newest.events] == ["second", "first"]
    assert [row.view for row in oldest.events] == ["first", "second"]


async def test_events_filter_by_kind_view_and_scope(store):
    project = uuid4()
    session = _Session(project_id=project)
    other = _Session()
    await _record(
        store,
        session.event(ViewEntered, minutes=0, view="home"),
        session.event(ViewExited, minutes=1, view="home", dwell_ms=60_000),
        session.event(ViewEntered, minutes=2, view="project/catalog"),
        other.event(ViewEntered, minutes=3, view="home"),
    )
    reader = store.reader

    assert (await reader.events(kinds=["ViewExited"])).total == 1
    assert (await reader.events(views=["home"])).total == 3
    assert (await reader.events(kinds=["ViewEntered"], views=["home"])).total == 2
    assert (await reader.events(project_id=project)).total == 3
    assert (await reader.events(browser_session_id=other.id)).total == 1
    assert (await reader.events(install_id=other.install_id)).total == 1
    assert (await reader.events(since=_at(2))).total == 2
    assert (await reader.events(until=_at(1))).total == 2


async def test_events_paging_walks_the_whole_result(store):
    session = _Session()
    await _record(
        store,
        *[session.event(ViewEntered, minutes=index, view=f"v{index}") for index in range(4)],
    )

    second_page = await store.reader.events(limit=2, offset=2, order="oldest")

    assert [row.view for row in second_page.events] == ["v2", "v3"]
    assert second_page.offset == 2
    assert second_page.total == 4


async def test_dwell_is_a_median_and_an_outlier_does_not_move_it(store):
    """The distinguishing case, not a representative one.

    Four short dwells and one backgrounded tab: the mean is over 20 minutes
    and the median is a second. A mean would pass every other assertion in
    this file, so this is the test that separates the two.
    """
    session = _Session()
    dwells = [800, 1_000, 1_200, 1_400, 6_000_000]
    await _record(
        store,
        *[
            session.event(ViewExited, minutes=index, view="home", dwell_ms=dwell)
            for index, dwell in enumerate(dwells)
        ],
    )

    [home] = (await store.reader.summary()).by_view

    assert home.dwell_ms_median == 1_200
    assert home.dwell_ms_median != int(sum(dwells) / len(dwells))
    assert home.dwell_ms_p90 == 6_000_000


async def test_by_view_reports_entries_and_exits_apart(store):
    """Their difference counts the views left by a route the page-hide flush
    did not catch."""
    session = _Session()
    await _record(
        store,
        session.event(ViewEntered, minutes=0, view="home"),
        session.event(ViewExited, minutes=1, view="home", dwell_ms=1_000, hidden_ms=400),
        session.event(ViewEntered, minutes=2, view="home"),
    )

    [home] = (await store.reader.summary()).by_view

    assert home.entries == 2
    assert home.exits == 1
    assert home.hidden_ms_median == 400


async def test_a_view_nobody_exited_reports_no_dwell_rather_than_zero(store):
    session = _Session()
    await _record(store, session.event(ViewEntered, minutes=0, view="home"))

    [home] = (await store.reader.summary()).by_view

    assert home.exits == 0
    assert home.dwell_ms_median is None
    assert home.dwell_ms_p90 is None


async def test_by_kind_covers_the_vocabulary_under_the_filter(store):
    session = _Session()
    await _record(store, session.event(ViewEntered, minutes=0))

    summary = await store.reader.summary()

    assert set(summary.by_kind) == {event_type.__name__ for event_type in INTERACTION_EVENTS}
    assert summary.by_kind["ViewEntered"] == 1
    assert summary.by_kind["SearchPerformed"] == 0


async def test_friction_counts_undone_events(store):
    session = _Session()
    await _record(
        store,
        session.event(ActionUndone, minutes=0, action_kind="merge", target_id="e1"),
        session.event(ActionUndone, minutes=1, action_kind="merge"),
        session.event(ViewEntered, minutes=2),
    )

    assert (await store.reader.summary()).friction.undone == 2


async def test_friction_counts_retried_events(store):
    session = _Session()
    await _record(
        store,
        session.event(ActionRetried, minutes=0, action_kind="extract", attempt_number=2),
        session.event(ViewEntered, minutes=1),
    )

    assert (await store.reader.summary()).friction.retried == 1


async def test_friction_counts_empty_results_and_where_they_happened(store):
    session = _Session()
    await _record(
        store,
        session.event(EmptyResultEncountered, minutes=0, where="search", query_length=4),
        session.event(EmptyResultEncountered, minutes=1, where="search", query_length=6),
        session.event(EmptyResultEncountered, minutes=2, where="timeline"),
    )

    friction = (await store.reader.summary()).friction

    assert friction.empty_results == 3
    assert [(place.where, place.count) for place in friction.empty_by_where] == [
        ("search", 2),
        ("timeline", 1),
    ]


async def test_friction_counts_a_near_repeat_search_and_not_a_different_one(store):
    """Three searches in one session: the second is a reformulation of the
    first, the third is a different subject. One repeat, not two."""
    session = _Session()
    await _record(
        store,
        session.event(SearchPerformed, minutes=0, query_text="Roman Senate", result_count=3),
        session.event(
            SearchPerformed, minutes=1, query_text="the roman  senate", result_count=5
        ),
        session.event(SearchPerformed, minutes=2, query_text="carthage", result_count=1),
    )

    assert (await store.reader.summary()).friction.repeat_searches == 1


async def test_a_repeat_is_never_read_across_two_browser_sessions(store):
    """The same query in two tabs is two people looking, not a
    reformulation."""
    first = _Session()
    second = _Session()
    await _record(
        store,
        first.event(SearchPerformed, minutes=0, query_text="roman senate", result_count=3),
        second.event(SearchPerformed, minutes=1, query_text="roman senate", result_count=3),
    )

    assert (await store.reader.summary()).friction.repeat_searches == 0


async def test_approvals_count_the_total_and_the_decisions(store):
    session = _Session()
    await _record(
        store,
        session.event(
            ApprovalDecided,
            minutes=0,
            decision="approved",
            latency_ms=900,
            expanded_details=False,
        ),
        session.event(
            ApprovalDecided,
            minutes=1,
            decision="rejected",
            latency_ms=1_100,
            expanded_details=False,
        ),
    )

    approvals = (await store.reader.summary()).approvals

    assert approvals.total == 2
    assert approvals.by_decision == {"approved": 1, "rejected": 1}


async def test_approvals_split_latency_by_whether_the_details_were_opened(store):
    """The click-through / deliberation split. The two medians differ by an
    order of magnitude and the combined one sits between them."""
    session = _Session()
    plain = [400, 900, 1_000]
    expanded = [12_000, 14_200, 60_000]
    await _record(
        store,
        *[
            session.event(
                ApprovalDecided,
                minutes=index,
                decision="approved",
                latency_ms=latency,
                expanded_details=False,
            )
            for index, latency in enumerate(plain)
        ],
        *[
            session.event(
                ApprovalDecided,
                minutes=10 + index,
                decision="approved",
                latency_ms=latency,
                expanded_details=True,
            )
            for index, latency in enumerate(expanded)
        ],
    )

    approvals = (await store.reader.summary()).approvals

    assert approvals.expanded == 3
    assert approvals.median_latency_ms_plain == 900
    assert approvals.median_latency_ms_expanded == 14_200
    assert approvals.median_latency_ms == 6_500


async def test_approvals_over_nothing_report_no_median(store):
    session = _Session()
    await _record(store, session.event(ViewEntered, minutes=0))

    approvals = (await store.reader.summary()).approvals

    assert approvals.total == 0
    assert approvals.median_latency_ms is None
    assert approvals.by_decision == {}


async def test_summary_respects_the_same_scope_filters_events_does(store):
    project = uuid4()
    inside = _Session(project_id=project)
    outside = _Session()
    await _record(
        store,
        inside.event(ActionUndone, minutes=0, action_kind="merge"),
        outside.event(ActionUndone, minutes=1, action_kind="merge"),
    )

    assert (await store.reader.summary(project_id=project)).friction.undone == 1
    assert (await store.reader.summary()).friction.undone == 2


async def test_the_runner_refuses_to_hand_out_a_reader_before_it_is_started(store, db_path):
    """The same refusal `events()` and `count()` give -- a reader over a
    connection that does not exist yet would fail somewhere less obvious."""
    runner = InteractionLogRunner(store=None, db_path=db_path, bus=None)

    with pytest.raises(RuntimeError, match="has not been started"):
        _ = runner.reader
