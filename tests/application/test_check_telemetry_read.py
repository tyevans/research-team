"""The aggregation that turns recorded outcomes into per-check rates.

Tested directly against `summarise` rather than through a database, because
every one of the spec's four honesty constraints is a rule *in this function*
and a database in the way would only make each test slower and less specific
about what it pins.

Three of the four live here. The fourth -- that viewing a course records no
telemetry -- is about a call site rather than about arithmetic, and Task 3 put
it in `tests/application/test_stage_runner.py`, where a real gate has recorded
something for a course view to fail to add to.
"""

from datetime import UTC, datetime, timedelta

from research_team.application.check_telemetry_read import CheckOutcome, summarise

T = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
"""One fixed instant, so a duration in a test is the difference the test states."""


def _outcome(
    check: str = "shared.coverage",
    *,
    status: str = "ran",
    findings: int = 0,
    posed_by: str = "runner",
    evaluated_at: datetime = T,
    decision: str | None = None,
    decided_by: str | None = None,
    decided_at: datetime | None = None,
) -> CheckOutcome:
    """One row's worth of outcome, with everything irrelevant defaulted.

    Defaults describe the dullest case -- a check that ran, found nothing, and
    was never decided -- so that each test's arguments are exactly the facts it
    is about.
    """
    return CheckOutcome(
        check=check,
        status=status,
        findings=findings,
        posed_by=posed_by,
        evaluated_at=evaluated_at,
        decision=decision,
        decided_by=decided_by,
        decided_at=decided_at,
    )


def _only(outcomes: list[CheckOutcome]):
    """The single `CheckStat` these outcomes fold into.

    Unpacking asserts there is exactly one, which is what fails first if
    `summarise` ever groups by something other than the check name.
    """
    [stat] = summarise(outcomes)
    return stat


def test_fire_rate_counts_the_runs_a_check_passed() -> None:
    """Three runs, one finding: fired 1, evaluated 3. Not fired 1 of 1.

    The denominator, arriving where it is finally used. Fails against any
    implementation that counts only the rows carrying findings -- which is
    every implementation written from the findings file.
    """
    stat = _only(
        [
            _outcome(findings=2),
            _outcome(findings=0),
            _outcome(findings=0),
        ]
    )

    assert stat.evaluated == 3
    assert stat.fired == 1
    assert stat.findings == 2


def test_an_unimplemented_binding_is_not_a_run() -> None:
    """It appears in `unimplemented` and in neither `evaluated` nor `fired`.

    Counting it as a run would report a check with a 0% fire rate that has
    never executed a line -- a check nobody would then think to fix, because
    the table says it is quietly passing.
    """
    stat = _only(
        [
            _outcome(status="unimplemented"),
            _outcome(status="unimplemented"),
            _outcome(findings=1),
        ]
    )

    assert stat.unimplemented == 2
    assert stat.evaluated == 1
    assert stat.fired == 1


def test_a_policy_approval_is_not_an_override() -> None:
    """`decided_by == "policy"` means nobody was asked.

    Counted in `auto_approved` and excluded from `overridden`. Reporting it as
    an override would describe a system that ignores its checks, when what
    happened is that `advance_stage` was set to `auto`.
    """
    stat = _only(
        [
            _outcome(findings=1, decision="approve", decided_by="policy", decided_at=T),
            _outcome(findings=1, decision="approve", decided_by="human", decided_at=T),
        ]
    )

    assert stat.auto_approved == 1
    assert stat.overridden == 1
    assert stat.decided == 2


def test_an_override_is_only_counted_when_the_check_actually_fired() -> None:
    """A check that found nothing was not overridden when the gate opened.

    Every gate a passing check sat in was approved by somebody, so an
    implementation that counted approvals rather than approvals-despite-a-
    finding would report an override rate of nearly 100% for the checks that
    never complain -- the exact inverse of the truth.
    """
    stat = _only(
        [
            _outcome(findings=0, decision="approve", decided_by="human", decided_at=T),
            _outcome(findings=0, decision="reject", decided_by="human", decided_at=T),
        ]
    )

    assert stat.overridden == 0
    assert stat.refused == 0
    assert stat.decided == 2


def test_the_tool_path_contributes_no_duration() -> None:
    """`posed_by == "tool"` gives null, never zero.

    Both events commit at `_save_turn` there, so their timestamps are
    milliseconds apart and measure serialization rather than deliberation. Zero
    would look like an instant approval; the truth is an absent measurement.
    Fails if someone computes the delta unconditionally -- which reads as
    correct and produces a median near zero for any tool-heavy project.
    """
    stat = _only(
        [
            _outcome(
                posed_by="tool",
                findings=1,
                decision="approve",
                decided_by="human",
                decided_at=T + timedelta(milliseconds=3),
            )
        ]
    )

    assert stat.median_seconds_to_decision is None
    assert stat.decided == 1, "the decision is still a decision; only its clock is unusable"


def test_a_median_is_taken_over_the_runner_rows_that_remain() -> None:
    """A mix of paths reports the runner ones and drops the rest.

    The tool row is three milliseconds wide. Including it would pull the median
    of {10s, 30s} down to 10s, so this fails loudly rather than approximately
    against an implementation that times every path.
    """
    stat = _only(
        [
            _outcome(decision="approve", decided_at=T + timedelta(seconds=10)),
            _outcome(decision="approve", decided_at=T + timedelta(seconds=30)),
            _outcome(
                posed_by="tool",
                decision="approve",
                decided_at=T + timedelta(milliseconds=3),
            ),
        ]
    )

    assert stat.median_seconds_to_decision == 20.0


def test_an_undecided_review_is_counted_but_not_timed() -> None:
    """A gate posed and never answered -- the process died, or it is open now.

    `decided` excludes it; `evaluated` includes it. The check ran, and dropping
    the row for want of an answer would make a crashed run look like a run that
    never happened.
    """
    stat = _only([_outcome(findings=1)])

    assert stat.evaluated == 1
    assert stat.fired == 1
    assert stat.decided == 0
    assert stat.median_seconds_to_decision is None


def test_a_standing_gate_is_marked_as_one() -> None:
    """`ubd.uncoverage` and `addie.expert_gap_flag` fire on every run by design.

    Registered with `run=None`, they emit a standing finding and can never
    pass, so a 100% fire rate is their specification. Reported in a column of
    their own so they are not read beside a check that chose to fire.

    Recognised from the registry -- `human_gate` or `critic_gate` non-null --
    and not from a list here, so a third one added later needs no edit.
    """
    stats = {
        stat.check: stat
        for stat in summarise(
            [
                _outcome("ubd.uncoverage", findings=1),
                _outcome("addie.expert_gap_flag", findings=1),
                _outcome("shared.coverage", findings=1),
            ]
        )
    }

    assert stats["ubd.uncoverage"].standing_gate is True
    assert stats["addie.expert_gap_flag"].standing_gate is True
    assert stats["shared.coverage"].standing_gate is False


def test_the_table_leads_with_the_check_that_fires_most() -> None:
    """Ordered by fire rate descending, because that is the question asked.

    A table sorted by name buries the check that fires every time among twenty
    others, and that check is the entire reason this feature exists (B38's four
    `matrix_density` bindings are exactly it).
    """
    stats = summarise(
        [
            _outcome("shared.orphan", findings=0),
            _outcome("shared.orphan", findings=0),
            _outcome("shared.coverage", findings=1),
            _outcome("shared.coverage", findings=1),
            _outcome("shared.provenance", findings=1),
            _outcome("shared.provenance", findings=0),
        ]
    )

    assert [stat.check for stat in stats] == [
        "shared.coverage",
        "shared.provenance",
        "shared.orphan",
    ]


def test_a_check_that_only_ever_failed_to_exist_does_not_divide_by_zero() -> None:
    """`evaluated == 0` still has to sort, and a rate over no runs is not 0/0.

    B38's bindings are one bad rename away from being this, and a crash in the
    read surface would be a strange way to find out.
    """
    stats = summarise([_outcome("shared.no_such_check", status="unimplemented")])

    assert [stat.check for stat in stats] == ["shared.no_such_check"]
    assert stats[0].evaluated == 0
    assert stats[0].fired == 0
