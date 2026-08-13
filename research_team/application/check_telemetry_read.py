"""Per-check fire rate, override rate and time-to-decision, from the outcomes.

The read side of check telemetry: a port, the shapes it speaks in, and the
arithmetic that turns one row per bound check per gate into one line per check.

**The arithmetic is here, in `application/`, and not in the adapter.** Every
one of the spec's honesty constraints -- a policy approval is not an override,
the tool path has no measurable duration, an unimplemented binding is not a run
-- is a rule about what the numbers mean, and a rule about meaning belongs
beside the vocabulary rather than beside the SQL. Written as a pure function
over a plain dataclass, each rule is a line a test can aim at directly; written
as a `GROUP BY`, each would be a clause nobody can test without a database and
which the next person to write a second query would have to remember to repeat.

Nothing here imports infrastructure, `aiosqlite` or `sqlalchemy`.
`tests/test_architecture.py` enforces the first; the other two are house style
and would be a layering violation in spirit if not in the letter of that test.

`CheckOutcome` deliberately mirrors only the part of `CheckOutcomeRow` the
arithmetic reads. It is not a copy of the row: a port that named a `ReadModel`
would drag the projection's shape into the application layer, and a mirror that
carried the row's every column would grow a field each time storage did.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Protocol

from research_team.application.checks import critic_gates, human_gates

__all__ = [
    "CheckOutcome",
    "CheckStat",
    "CheckTelemetryReadError",
    "CheckTelemetryReadPort",
    "summarise",
]

RAN = "ran"
"""`status` for a binding that resolved to a registered check and executed."""

UNIMPLEMENTED = "unimplemented"
"""`status` for a binding naming no registered check. It neither ran nor passed."""

_OPENED_THE_GATE = frozenset({"approve", "edit"})
"""Decisions that let the advance through.

An edit belongs here with an approve: the gate opened, and the findings were
not what stopped it. What was edited was the call's arguments, not the review.
"""

_NOBODY_WAS_ASKED = "policy"
"""`decided_by` when `advance_stage` was set to `auto` or `deny`.

The value the runner and the executor both record when no `ApprovalRequest` was
ever posed. It is the whole reason `auto_approved` is a separate column.
"""

_MEASURABLE_PATH = "runner"
"""The only `posed_by` whose two timestamps bracket a human deliberating."""


class CheckTelemetryReadError(Exception):
    """The outcomes could not be read. Storage or wiring, not an empty table.

    A project with no recorded gates answers with an empty list; this is
    reserved for the case where the question could not be asked at all, so that
    "nothing has been measured yet" and "the instrument is broken" stay apart.
    """


@dataclass(frozen=True)
class CheckOutcome:
    """One bound check at one gate, in the terms the arithmetic needs.

    `status` and `findings` are separate facts and both are load-bearing:
    `findings == 0` means "ran and passed" only when `status` is `ran`, and
    means "never executed" when it is `unimplemented`. Collapsing them would
    make B38's unbound matrices indistinguishable from checks that are quietly
    doing their job.
    """

    check: str
    status: str
    findings: int
    posed_by: str
    evaluated_at: datetime
    decision: str | None
    decided_by: str | None
    decided_at: datetime | None


@dataclass(frozen=True)
class CheckStat:
    """What one check has done across every gate it was bound at.

    Counts rather than rates, with one exception (`median_seconds_to_decision`,
    which cannot be recovered from counts). A renderer can divide; a reader
    given only a percentage cannot tell 1-of-1 from 200-of-200, and those two
    warrant opposite conclusions about whether a check earns its place.
    """

    check: str
    evaluated: int
    """Gates at which this check ran, whether or not it found anything."""
    fired: int
    """Of `evaluated`, how many produced at least one finding."""
    findings: int
    """Total findings produced. A check that fires with twenty is not the same
    nuisance as one that fires with one, and the fire rate cannot say so."""
    unimplemented: int
    """Gates where it was bound and no such check is registered. Not a run."""
    decided: int
    """Rows whose gate was answered. Excludes a gate posed and never closed."""
    overridden: int
    """Fired, and a person opened the gate anyway. Excludes policy decisions."""
    refused: int
    """Fired, and the gate was rejected."""
    auto_approved: int
    """Fired, and the gate opened without anyone being asked."""
    standing_gate: bool
    """This check cannot pass by construction, so its fire rate is its spec."""
    median_seconds_to_decision: float | None
    """None when nothing here was measurable -- never zero. See `summarise`."""


class CheckTelemetryReadPort(Protocol):
    """This project's check statistics, already folded.

    No project argument, for `CorpusReadPort`'s reason: an instance belongs to
    one project and supplies it, so no caller is in a position to read another
    project's measurements by passing a different id.

    One method, returning finished statistics rather than rows. The caller is a
    renderer, and a port that handed out outcomes would put the fold -- and
    therefore every honesty constraint -- in whichever interface asked next.
    """

    async def stats(self) -> list[CheckStat]:
        """Every check this project has recorded, most-firing first.

        Empty when nothing has been measured. Raises `CheckTelemetryReadError`
        when the question could not be asked.
        """
        ...


def _fire_rate(fired: int, evaluated: int) -> float:
    """Fired per run, or 0.0 for a check that has never run.

    A check that is only ever unimplemented has `evaluated == 0` and no rate at
    all; it sorts last rather than crashing the table it appears in.
    """
    return fired / evaluated if evaluated else 0.0


def summarise(outcomes: Iterable[CheckOutcome]) -> list[CheckStat]:
    """Fold raw outcomes into one statistic per check, ordered by fire rate.

    Ordered by fire rate descending because the check that always fires is the
    one this whole feature exists to surface, and a table sorted by name buries
    it among twenty-one others. Ties break on the check name so that two runs
    over unchanged data render identically.
    """
    grouped: dict[str, list[CheckOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault(outcome.check, []).append(outcome)
    stats = [_summarise_one(check, rows) for check, rows in grouped.items()]
    return sorted(
        stats, key=lambda stat: (-_fire_rate(stat.fired, stat.evaluated), stat.check)
    )


def _summarise_one(check: str, rows: Sequence[CheckOutcome]) -> CheckStat:
    """One check's line. Every honesty constraint is a filter in here."""
    # An unimplemented binding is excluded from `ran` entirely rather than
    # counted as a run with no findings: it neither ran nor passed, and a 0%
    # fire rate on a check that has never executed a line is the most
    # confidently wrong number this table could print.
    ran = [row for row in rows if row.status == RAN]
    fired = [row for row in ran if row.findings > 0]

    # Overrides are counted only against gates where the check had something to
    # say. Every gate a passing check sat in was approved by someone, so
    # counting approvals rather than approvals-despite-a-finding would report
    # the quietest checks as the most ignored.
    #
    # A policy approval is not an override: `decided_by == "policy"` means
    # `advance_stage` was set to `auto` and nobody saw the finding. Counting it
    # would describe a system ignoring its checks when what happened is that
    # nobody was asked. It is reported beside the rate, in `auto_approved`.
    opened = [row for row in fired if row.decision in _OPENED_THE_GATE]
    overridden = [row for row in opened if row.decided_by != _NOBODY_WAS_ASKED]
    auto_approved = [row for row in opened if row.decided_by == _NOBODY_WAS_ASKED]
    # Refusals are not split the same way. A policy `deny` really did refuse
    # the advance, and separating it would suggest the gate might have opened;
    # the asymmetry with `overridden` is that an unasked *approval* overstates
    # what a human ignored, while an unasked refusal overstates nothing.
    refused = [row for row in fired if row.decision == "reject"]

    # A tool-path review and its decision both reach the store at `_save_turn`,
    # so their timestamps differ by however long serialization took. Excluded
    # rather than counted as fast: zero would be a number that looks like an
    # instant approval and is an absent measurement. Reporting None for a
    # tool-only project is the honest answer and the one this refuses to
    # improve on.
    durations = [
        (row.decided_at - row.evaluated_at).total_seconds()
        for row in rows
        if row.posed_by == _MEASURABLE_PATH and row.decided_at is not None
    ]

    return CheckStat(
        check=check,
        evaluated=len(ran),
        fired=len(fired),
        findings=sum(row.findings for row in ran),
        unimplemented=sum(1 for row in rows if row.status == UNIMPLEMENTED),
        decided=sum(1 for row in rows if row.decision is not None),
        overridden=len(overridden),
        refused=len(refused),
        auto_approved=len(auto_approved),
        standing_gate=_is_standing_gate(check),
        median_seconds_to_decision=median(durations) if durations else None,
    )


def _is_standing_gate(check: str) -> bool:
    """Whether this check emits a standing finding and can never pass.

    Read from the registry rather than from a list here. `ubd.uncoverage` and
    `addie.expert_gap_flag` are the two today, and a hardcoded pair would go
    quietly stale the day a third is registered -- reporting it beside checks
    that chose to fire, which is the confusion the column exists to prevent.
    """
    return check in human_gates() or check in critic_gates()
