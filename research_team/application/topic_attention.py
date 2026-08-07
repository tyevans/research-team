"""Which topics need looking at, and why.

A registry of triggers, deliberately shaped like `checks.py`: each is named,
namespaced `topic.*`, parameterized, and returns a list of `Finding` rather than
a score. Attention is *computed on read* from a topic's folded state plus what
the corpus currently holds -- nothing here is stored, and no topic carries a
needs-attention flag.

**One `Finding`, shared with the check library.** This module briefly declared
its own, written while the check library was unmerged; `findings.py` exists
precisely to stop that, and the two are now one type. The join cost one field
name -- `affected_artifact_ids` became `cites`, because a trigger cites source
ids and sub-question keys and neither is an artifact.

The *registries* stay separate, and that is not a deferral. A check reads a
`CheckContext` of artifacts, links and matrices; a trigger reads folded topic
state and a corpus snapshot. They share a contract and an output type, not an
input, and forcing one signature would hand every check arguments it does not
use in order to make a table look tidy.

**Why computed rather than stored.** A stored flag is written by one code path
and read by another, and it goes stale the moment an event arrives that nobody
thought to re-evaluate. The failure is silent: the queue looks right and is
wrong. A computed one cannot drift, because there is nothing to keep in sync.
The cost is that the answer has to be cheap, which is why every trigger here is
Tier 1 -- arithmetic and set membership over state that is already in hand, no
model call, no I/O.

**No scores.** A per-topic priority float would be a number nobody could
re-derive and everyone would threshold on. Findings carry a severity, the
queue orders by the worst severity a topic has and then by how long it has been
waiting, and that is the whole ranking. `blocking` means the topic cannot be
usefully worked until it is addressed; `advisory` means it is worth a look.

**The instrument rule.** A trigger reports when the instrument it was handed is
missing, and passes when only its domain is empty. A topic with no linked
sources produces a `topic.low_coverage` finding, because "we have looked at
nothing" is the thing worth saying. A topic whose linked sources contain no
contradiction passes silently, because an absent contradiction is an answer.

**If the only possible response to a finding is to dismiss it, the trigger
should not exist.** Alert fatigue is the defining failure of every monitoring
system, and it comes from firing on conditions nobody would act on. Each trigger
below has an action attached to it in the docstring; one that cannot name an
action does not belong here.

Two things are deliberately *not* here:

- **Confidence decay.** A float that falls with elapsed time is the most
  tempting mechanism in this design and the least defensible: its rate is
  unfalsifiable, nobody can re-derive it, and thresholding on it invents
  precision. Staleness here is evidence-based -- `topic.new_material` fires
  because a specific document arrived, and says which one.
- **Contradiction *detection*.** Deciding that two sources disagree on substance
  is semantic, so it is registered as a human gate (`run=None`) rather than
  faked. `topic.contested` tracks contradictions someone has already recorded,
  which is a different and computable question.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

from research_team.application.findings import Finding, FindingSeverity
from research_team.domain.topic import TopicState

DEFAULT_MIN_SOURCES = 2
"""How many live sources a topic wants before its coverage stops being a finding.

Two rather than one because the failure this catches is the single-source
conclusion. It is a binding parameter, not a law: a preset that wants three says
so when it binds the trigger.
"""

DEFAULT_THRASH_LOOKS = 2
"""Consecutive fruitless looks before rework is worth reporting.

One fruitless look is ordinary -- plenty of real investigations come back empty.
Two in a row with nothing recorded between them is a loop that has stopped
learning, which is the thing an autonomous run needs told.
"""


BLOCKING_SEVERITIES: frozenset[str] = frozenset({"invariant", "blocking", "human_gate"})
"""Severities that stop a topic being worked, out of `FindingSeverity`'s five.

`advisory` is worth a look and does not block. `critic_gate` is deliberately
absent: it names a model call this library will not make, and no trigger here
produces one -- listing it would imply a path that does not exist.
"""

POSITION_WIDTH = 12


def corpus_position(version: int) -> str:
    """One project's corpus version, as sortable text. The only position space here.

    Every position in this feature -- a topic's last look, an acknowledgement's
    expiry, a source's arrival -- is *this project's corpus version*, and they
    are only ever compared with each other. Mixing scales is the obvious way to
    get this wrong: a global feed position and a per-stream version are both
    "positions", they are both text, and comparing one to the other silently
    produces nonsense rather than an error.

    Corpus version rather than global feed position because it is the scale the
    questions are actually asked at -- "did anything arrive in *this corpus*
    since I last looked at this topic" -- and because a projection handler is
    given an event, not its envelope, so the global position is not in reach
    where these are written.

    Zero-padded so lexicographic order matches numeric order. Nothing parses
    these; they are compared and nothing else.
    """
    return f"{max(version, 0):0{POSITION_WIDTH}d}"


@dataclass(frozen=True)
class CorpusFacts:
    """What the registry needs to know about the corpus, and nothing more.

    A value rather than a port so the triggers stay pure functions of their
    inputs: the caller reads the corpus once and every trigger sees the same
    snapshot, which is what makes a whole queue evaluation consistent rather
    than a sequence of slightly different worlds.

    Deliberately not the `Corpus` aggregate itself. The registry has no business
    knowing how a corpus is stored, and taking the aggregate would make these
    functions untestable without building one.
    """

    live_source_ids: frozenset[str] = frozenset()
    dropped_source_ids: frozenset[str] = frozenset()
    #: source_id -> the position at which it was most recently stored. Used to
    #: tell "arrived since the last look" from "was already here".
    stored_at: dict[str, str] = field(default_factory=dict)

    def arrived_after(self, position: str | None) -> frozenset[str]:
        """Live sources stored strictly after `position`.

        Positions compare as text. `eventsource` encodes them so that
        lexicographic order matches append order within one store, which is the
        only ordering this needs -- and `None` (never looked) means everything
        counts as new.
        """
        if position is None:
            return self.live_source_ids
        return frozenset(
            source_id
            for source_id in self.live_source_ids
            if self.stored_at.get(source_id, "") > position
        )


RawFinding = tuple[str, tuple[str, ...], str | None]
"""`(message, cites, suggested_edit)`, before the registry stamps a severity."""

TriggerFn = Callable[[TopicState, CorpusFacts, dict], list[RawFinding]]
"""What a trigger returns: `(message, cites, suggested_edit)` per finding.

Tuples rather than assembled `Finding`s, matching `CheckFn`, and for the reason
that shape exists: severity belongs to the *registration*, not to the run. A
trigger that built its own findings could quietly disagree with the severity it
was registered under, and `fixed_severity`-style guarantees would be
unenforceable. Here a trigger says what is wrong and the registry says how much
it matters.
"""


@dataclass(frozen=True)
class Trigger:
    """One registered attention rule.

    `run=None` marks a trigger that cannot be honestly automated. It is
    registered anyway, and reports a standing `human_gate` finding, because the
    alternative -- leaving it out -- makes a gap look like a pass. That is the
    same argument the check library makes for registering `uncoverage` with no
    implementation rather than pretending a model call settles it.
    """

    name: str
    severity: FindingSeverity
    describes: str
    run: TriggerFn | None = None
    params: dict = field(default_factory=dict)

    def bind(self, **params) -> "Trigger":
        """This trigger with different parameters. Used by presets."""
        return replace(self, params={**self.params, **params})

    def evaluate(self, state: TopicState, corpus: CorpusFacts) -> list[Finding]:
        """Run this trigger and stamp its findings with the registered severity."""
        if self.run is None:
            # `human_gate` rather than this trigger's own severity: the
            # vocabulary from `findings.py` has a value for exactly this, and
            # it says the useful thing -- no run can clear it, because no
            # automated substitute exists at all.
            return [
                Finding(
                    check=self.name,
                    severity="human_gate",
                    message=f"{self.describes} -- needs a human; nothing here decides it",
                )
            ]
        return [
            Finding(
                check=self.name,
                severity=self.severity,
                message=message,
                cites=cites,
                suggested_edit=suggested_edit,
            )
            for message, cites, suggested_edit in self.run(state, corpus, self.params)
        ]


# ---------------- the triggers ----------------


def _never_investigated(
    state: TopicState, corpus: CorpusFacts, params: dict
) -> list[RawFinding]:
    """Action: look at it. A topic nobody has opened is the cheapest win there is.

    Distinct from `low_coverage` on purpose: a topic can have sources attached
    at creation and still never have been thought about.
    """
    if state.investigations > 0:
        return []
    return [("never investigated", (), None)]


def _unanswered(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: answer one of the open sub-questions, or close it as out of scope."""
    open_keys = state.open_sub_questions
    if not open_keys:
        return []
    return [(f"{len(open_keys)} open sub-question(s)", tuple(sorted(open_keys)), None)]


def _low_coverage(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: find more sources, or record that the topic is answerable from these.

    Counts *live* links only. A topic resting on three sources, two of which
    have since been dropped, has coverage of one -- and saying otherwise is how
    a conclusion outlives its evidence.
    """
    minimum = params.get("minimum", DEFAULT_MIN_SOURCES)
    live = [s for s in state.source_ids if s in corpus.live_source_ids]
    if len(live) >= minimum:
        return []
    return [(f"{len(live)} live source(s), wants {minimum}", tuple(sorted(live)), None)]


def _source_dropped(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: unlink it and reassess whatever rested on it.

    The corpus records a drop with a reason rather than deleting the row, which
    is what makes this computable at all. A topic still linked to a dropped
    source is the silent-drop failure one level up: the topic looks supported
    and is not.
    """
    dropped = sorted(set(state.source_ids) & corpus.dropped_source_ids)
    if not dropped:
        return []
    return [
        (
            f"{len(dropped)} linked source(s) dropped from the corpus",
            tuple(dropped),
            "Unlink them and reassess whatever rested on them.",
        )
    ]


def _new_material(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: read the new documents and link or dismiss them.

    The highest-value trigger, and pure bookkeeping: a document arrived after
    this topic was last looked at, and the topic does not link it. It says
    nothing about whether the document is *relevant* -- that is the look's job.

    Bounded by `sample` in the evidence so a bulk ingest does not produce a
    finding carrying ten thousand ids; the count is exact regardless.
    """
    if state.last_investigated_at is None:
        # `never_investigated` already covers this, and firing both would be
        # two findings for one action.
        return []
    unseen = sorted(corpus.arrived_after(state.last_investigated_at) - set(state.source_ids))
    if not unseen:
        return []
    sample = params.get("sample", 10)
    return [
        (
            f"{len(unseen)} source(s) arrived since the last look",
            tuple(unseen[:sample]),
            None,
        )
    ]


def _source_superseded(
    state: TopicState, corpus: CorpusFacts, params: dict
) -> list[RawFinding]:
    """Action: re-read the source; whatever rested on the old bytes may not hold.

    Supersession is a first-class corpus behaviour -- re-storing a `source_id`
    replaces its record -- so this is "the bytes under a linked source changed
    after we last looked at this topic".
    """
    last = state.last_investigated_at
    if last is None:
        return []
    changed = sorted(
        source_id
        for source_id in state.source_ids
        if corpus.stored_at.get(source_id, "") > last
    )
    if not changed:
        return []
    return [
        (
            f"{len(changed)} linked source(s) changed since the last look",
            tuple(changed),
            "Re-read them; whatever rested on the old bytes may not hold.",
        )
    ]


def _contested(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: adjudicate, or record the conditional under which both hold.

    Tracks contradictions someone already recorded. Detecting them is semantic
    and is registered separately as a human gate.
    """
    unresolved = state.unresolved_contests
    if not unresolved:
        return []
    return [
        (
            f"{len(unresolved)} unresolved contradiction(s)",
            tuple(sorted(unresolved)),
            None,
        )
    ]


def _rework_thrash(state: TopicState, corpus: CorpusFacts, params: dict) -> list[RawFinding]:
    """Action: stop looking at this and change what you are asking.

    The counter-measure to an autonomous run re-reading the same material every
    round. It fires on looks that produced nothing, which is measured from the
    finding count snapshotted at each look -- not from the run's own account of
    itself, which is exactly the thing that cannot be trusted.

    Advisory rather than blocking: thrash is a reason to *deprioritise* a topic,
    not a defect in it, and the queue does that by ranking.
    """
    looks = params.get("looks", DEFAULT_THRASH_LOOKS)
    if state.investigations < looks:
        return []
    if state.findings > state.findings_at_last_investigation:
        return []
    return [
        (
            f"{state.investigations} look(s) with nothing recorded since the last one",
            (),
            "Change what you are asking; re-reading the same material is not working.",
        )
    ]


REGISTRY: tuple[Trigger, ...] = (
    Trigger(
        name="topic.never_investigated",
        severity="blocking",
        describes="the topic has never been looked at",
        run=_never_investigated,
    ),
    Trigger(
        name="topic.unanswered",
        severity="blocking",
        describes="sub-questions remain open",
        run=_unanswered,
    ),
    Trigger(
        name="topic.source_dropped",
        severity="blocking",
        describes="a linked source was dropped from the corpus",
        run=_source_dropped,
    ),
    Trigger(
        name="topic.source_superseded",
        severity="blocking",
        describes="a linked source changed after the last look",
        run=_source_superseded,
    ),
    Trigger(
        name="topic.contested",
        severity="blocking",
        describes="recorded contradictions are unresolved",
        run=_contested,
    ),
    Trigger(
        name="topic.low_coverage",
        severity="advisory",
        describes="the topic rests on too few live sources",
        run=_low_coverage,
    ),
    Trigger(
        name="topic.new_material",
        severity="advisory",
        describes="sources arrived that this topic has not considered",
        run=_new_material,
    ),
    Trigger(
        name="topic.rework_thrash",
        severity="advisory",
        describes="repeated looks are producing nothing",
        run=_rework_thrash,
    ),
)
"""Every trigger that ships, in the order a reader should meet them.

Blocking first, then advisory, so the list reads as a severity ladder. Order
does not affect evaluation -- `attention_for` sorts what it collects.
"""

BY_NAME: dict[str, Trigger] = {trigger.name: trigger for trigger in REGISTRY}


@dataclass(frozen=True)
class TopicAttention:
    """What one topic's evaluation produced.

    Carries the findings rather than a verdict: "needs attention" is just
    "findings is non-empty", and a caller ranking a queue wants to see what it
    is ranking on.
    """

    topic_id: UUID
    findings: tuple[Finding, ...]

    @property
    def needs_attention(self) -> bool:
        return bool(self.findings)

    @property
    def is_blocked(self) -> bool:
        """Whether anything here stops the topic being usefully worked.

        `human_gate` counts. A trigger that has no implementation is not a
        trigger that passed, and treating it as advisory would let the queue
        rank a topic as nearly-clean on the strength of a check nobody ran.
        """
        return any(finding.severity in BLOCKING_SEVERITIES for finding in self.findings)

    @property
    def triggers(self) -> tuple[str, ...]:
        return tuple(finding.check for finding in self.findings)

    @property
    def evidence(self) -> tuple[str, ...]:
        """Every id cited by any finding, deduplicated and ordered.

        This is what a round record carries to justify its choice. A reason
        string would be a claim; these are checkable.
        """
        seen: list[str] = []
        for finding in self.findings:
            for item in finding.cites:
                if item not in seen:
                    seen.append(item)
        return tuple(seen)


def attention_for(
    state: TopicState,
    corpus: CorpusFacts,
    *,
    at_position: str | None = None,
    triggers: Sequence[Trigger] = REGISTRY,
) -> TopicAttention:
    """Evaluate every trigger against one topic.

    A topic that is not live produces nothing at all. A topic that has been
    answered or set aside is not a queue item, and running the triggers over it
    would fill the queue with work somebody has already decided not to do.

    `at_position` is where the log stands now, and is what expires
    acknowledgements: an acknowledgement silences its trigger only while the log
    has not yet passed the position it named. Omitting it means no
    acknowledgement has expired yet, which is the right reading for a caller
    that does not know where the log is.
    """
    if not state.is_live:
        return TopicAttention(topic_id=state.topic_id, findings=())

    collected: list[Finding] = []
    for trigger in triggers:
        if _acknowledged(state, trigger.name, at_position):
            continue
        collected.extend(trigger.evaluate(state, corpus))

    # Blocking before advisory, then by trigger name so the order is stable
    # across runs -- an unstable order makes two identical evaluations look
    # like a change.
    collected.sort(
        key=lambda finding: (
            0 if finding.severity in BLOCKING_SEVERITIES else 1,
            finding.check,
        )
    )
    return TopicAttention(topic_id=state.topic_id, findings=tuple(collected))


def _acknowledged(state: TopicState, trigger: str, at_position: str | None) -> bool:
    """Whether `trigger` is currently silenced on this topic.

    An acknowledgement expires by log position rather than by clock, so a
    project that sat idle for a month has not silently un-silenced everything
    it muted.
    """
    ack = state.acknowledgements.get(trigger)
    if ack is None:
        return False
    if at_position is None:
        return True
    return at_position <= ack.until_position
