"""What makes a topic need attention.

Every trigger here is model-free and computed from folded state plus a corpus
snapshot, so these tests are arithmetic: build a state, build the facts, assert
the findings. No fixtures, no event loop, no store.

The properties worth defending, and the reason each has its own test:

- A trigger that fires on a condition nobody would act on is alert fatigue, so
  each one has to *stop* firing once the thing is addressed.
- Two findings for one action is the same failure, so overlapping triggers
  (`never_investigated` and `new_material`) must not both fire.
- Attention is computed, never stored, so a topic taken out of the queue by its
  status produces nothing at all.
"""

from uuid import uuid4

import pytest

from research_team.application.topic_attention import (
    BY_NAME,
    REGISTRY,
    CorpusFacts,
    Finding,
    Trigger,
    attention_for,
)
from research_team.domain.topic import (
    AcknowledgeTrigger,
    AddSubQuestion,
    LinkSource,
    OpenTopic,
    RecordContest,
    RecordFinding,
    RecordInvestigation,
    ResolveContest,
    ResolveSubQuestion,
    SetTopicStatus,
    decide,
    evolve,
    initial_state,
)


def run(state, *commands):
    for command in commands:
        for event in decide(command, state):
            state = evolve(state, event)
    return state


def opened(**kwargs):
    return run(
        initial_state(),
        OpenTopic(
            topic_id=kwargs.get("topic_id", uuid4()),
            project_id=uuid4(),
            question="q?",
            rationale="r",
        ),
    )


def facts(live=(), dropped=(), stored_at=None) -> CorpusFacts:
    return CorpusFacts(
        live_source_ids=frozenset(live),
        dropped_source_ids=frozenset(dropped),
        stored_at=dict(stored_at or {}),
    )


def triggers_of(state, corpus, **kwargs) -> set[str]:
    return set(attention_for(state, corpus, **kwargs).triggers)


# ---------------- never investigated ----------------


def test_a_fresh_topic_is_flagged_as_never_investigated():
    assert "topic.never_investigated" in triggers_of(opened(), facts())


def test_investigating_clears_it():
    state = run(opened(), RecordInvestigation(at_position="p1"))
    assert "topic.never_investigated" not in triggers_of(state, facts())


def test_a_never_investigated_topic_does_not_also_report_new_material():
    """Two findings for one action is the alert-fatigue failure in miniature.

    Everything in the corpus is unseen by a topic nobody has looked at, so
    `new_material` would fire on every fresh topic and say nothing that
    `never_investigated` has not already said.
    """
    corpus = facts(live={"s1", "s2"}, stored_at={"s1": "p1", "s2": "p2"})

    found = triggers_of(opened(), corpus)

    assert "topic.never_investigated" in found
    assert "topic.new_material" not in found


# ---------------- unanswered ----------------


def test_open_sub_questions_are_blocking_and_clear_when_resolved():
    state = run(opened(), AddSubQuestion(key="a", question="q?"))
    attention = attention_for(state, facts())

    [finding] = [f for f in attention.findings if f.trigger == "topic.unanswered"]
    assert finding.is_blocking
    assert finding.evidence == ("a",)

    state = run(state, ResolveSubQuestion(key="a", answer="yes"))
    assert "topic.unanswered" not in triggers_of(state, facts())


# ---------------- coverage ----------------


def test_coverage_counts_live_sources_only():
    """A conclusion must not outlive its evidence.

    Three links, two of them dropped, is coverage of one -- and reporting three
    is how a topic goes on looking supported after the support is gone.
    """
    state = run(
        opened(),
        LinkSource(source_id="s1"),
        LinkSource(source_id="s2"),
        LinkSource(source_id="s3"),
    )
    corpus = facts(live={"s1"}, dropped={"s2", "s3"})

    [finding] = [
        f for f in attention_for(state, corpus).findings if f.trigger == "topic.low_coverage"
    ]

    assert "1 live source" in finding.summary


def test_coverage_is_satisfied_at_the_bound_and_the_bound_is_a_parameter():
    state = run(opened(), LinkSource(source_id="s1"), LinkSource(source_id="s2"))
    corpus = facts(live={"s1", "s2"})

    assert "topic.low_coverage" not in triggers_of(state, corpus)

    stricter = [BY_NAME["topic.low_coverage"].bind(minimum=3)]
    assert attention_for(state, corpus, triggers=stricter).findings


# ---------------- dropped and superseded ----------------


def test_a_dropped_linked_source_is_blocking():
    state = run(opened(), LinkSource(source_id="s1"))
    corpus = facts(live=set(), dropped={"s1"})

    [finding] = [
        f for f in attention_for(state, corpus).findings if f.trigger == "topic.source_dropped"
    ]

    assert finding.is_blocking
    assert finding.evidence == ("s1",)


def test_a_source_that_changed_after_the_last_look_is_blocking():
    state = run(opened(), LinkSource(source_id="s1"), RecordInvestigation(at_position="p5"))
    corpus = facts(live={"s1"}, stored_at={"s1": "p9"})

    [finding] = [
        f
        for f in attention_for(state, corpus).findings
        if f.trigger == "topic.source_superseded"
    ]

    assert finding.evidence == ("s1",)


def test_a_source_unchanged_since_the_last_look_is_quiet():
    state = run(opened(), LinkSource(source_id="s1"), RecordInvestigation(at_position="p9"))
    corpus = facts(live={"s1"}, stored_at={"s1": "p5"})

    assert "topic.source_superseded" not in triggers_of(state, corpus)


# ---------------- new material ----------------


def test_material_arriving_after_the_last_look_is_reported_with_its_ids():
    state = run(opened(), RecordInvestigation(at_position="p2"))
    corpus = facts(live={"s1", "s2"}, stored_at={"s1": "p1", "s2": "p3"})

    [finding] = [
        f for f in attention_for(state, corpus).findings if f.trigger == "topic.new_material"
    ]

    # s1 predates the look; s2 arrived after it.
    assert finding.evidence == ("s2",)


def test_material_already_linked_is_not_new():
    state = run(opened(), LinkSource(source_id="s2"), RecordInvestigation(at_position="p2"))
    corpus = facts(live={"s2"}, stored_at={"s2": "p3"})

    assert "topic.new_material" not in triggers_of(state, corpus)


def test_the_evidence_sample_is_bounded_but_the_count_is_not():
    """A bulk ingest must not produce a finding carrying ten thousand ids."""
    state = run(opened(), RecordInvestigation(at_position="p0"))
    many = {f"s{n:04d}" for n in range(50)}
    corpus = facts(live=many, stored_at=dict.fromkeys(many, "p1"))

    [finding] = [
        f for f in attention_for(state, corpus).findings if f.trigger == "topic.new_material"
    ]

    assert "50 source(s)" in finding.summary
    assert len(finding.evidence) == 10


# ---------------- contests ----------------


def test_an_unresolved_contest_blocks_and_resolving_clears_it():
    state = run(opened(), RecordContest(key="k", nature="24h vs 48h"))
    assert "topic.contested" in triggers_of(state, facts())

    state = run(
        state,
        ResolveContest(key="k", resolution="both", justification="different tiers"),
    )
    assert "topic.contested" not in triggers_of(state, facts())


# ---------------- thrash ----------------


def test_repeated_looks_with_nothing_recorded_are_reported():
    state = run(
        opened(),
        RecordInvestigation(at_position="p1"),
        RecordInvestigation(at_position="p2"),
    )

    assert "topic.rework_thrash" in triggers_of(state, facts())


def test_a_look_that_produced_a_finding_is_not_thrash():
    state = run(
        opened(),
        RecordInvestigation(at_position="p1"),
        RecordInvestigation(at_position="p2"),
        RecordFinding(summary="learned something"),
    )

    assert "topic.rework_thrash" not in triggers_of(state, facts())


def test_thrash_is_advisory_rather_than_blocking():
    """Thrash is a reason to deprioritise a topic, not a defect in it."""
    state = run(
        opened(),
        RecordInvestigation(at_position="p1"),
        RecordInvestigation(at_position="p2"),
    )

    [finding] = [
        f for f in attention_for(state, facts()).findings if f.trigger == "topic.rework_thrash"
    ]
    assert not finding.is_blocking


# ---------------- status and acknowledgement ----------------


@pytest.mark.parametrize("status", ["answered", "not_pursuing", "superseded"])
def test_a_closed_topic_produces_no_findings_at_all(status):
    """Work somebody has decided not to do must not fill the queue."""
    state = run(opened(), SetTopicStatus(to_status=status, justification="decided"))

    attention = attention_for(state, facts())

    assert attention.findings == ()
    assert not attention.needs_attention


def test_an_acknowledgement_silences_its_trigger_until_the_log_passes_the_expiry():
    state = run(
        opened(),
        RecordInvestigation(at_position="p1"),
        AcknowledgeTrigger(
            trigger="topic.new_material", reason="bulk import, reviewed", until_position="p5"
        ),
    )
    corpus = facts(live={"s9"}, stored_at={"s9": "p2"})

    assert "topic.new_material" not in triggers_of(state, corpus, at_position="p3")

    # Past the expiry, it speaks again -- which is the whole point of requiring
    # one. A permanent acknowledgement is a muted alarm nobody remembers.
    assert "topic.new_material" in triggers_of(state, corpus, at_position="p6")


def test_an_acknowledgement_does_not_silence_other_triggers():
    state = run(
        opened(),
        AcknowledgeTrigger(
            trigger="topic.new_material", reason="reviewed", until_position="p9"
        ),
    )

    assert "topic.never_investigated" in triggers_of(state, facts(), at_position="p1")


# ---------------- ranking and shape ----------------


def test_blocking_findings_sort_ahead_of_advisory_ones():
    state = run(opened(), AddSubQuestion(key="a", question="q?"))

    findings = attention_for(state, facts()).findings

    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: 0 if s == "blocking" else 1)


def test_evidence_is_deduplicated_across_findings_in_order():
    state = run(
        opened(),
        LinkSource(source_id="s1"),
        RecordInvestigation(at_position="p1"),
    )
    # s1 is both dropped and (as far as coverage is concerned) not live, so two
    # findings cite it.
    corpus = facts(live=set(), dropped={"s1"})

    attention = attention_for(state, corpus)

    assert attention.evidence.count("s1") == 1


def test_is_blocked_reflects_the_worst_severity_present():
    quiet = run(
        opened(),
        LinkSource(source_id="s1"),
        LinkSource(source_id="s2"),
        RecordInvestigation(at_position="p1"),
        RecordFinding(summary="done"),
    )
    assert not attention_for(quiet, facts(live={"s1", "s2"})).is_blocked

    blocked = run(quiet, AddSubQuestion(key="a", question="q?"))
    assert attention_for(blocked, facts(live={"s1", "s2"})).is_blocked


def test_a_settled_topic_needs_no_attention():
    """The state the whole design is aiming at: quiet when there is nothing to do."""
    state = run(
        opened(),
        LinkSource(source_id="s1"),
        LinkSource(source_id="s2"),
        RecordInvestigation(at_position="p9"),
        RecordFinding(summary="answered"),
    )
    corpus = facts(live={"s1", "s2"}, stored_at={"s1": "p1", "s2": "p2"})

    assert not attention_for(state, corpus).needs_attention


# ---------------- the registry itself ----------------


def test_every_registered_trigger_has_a_unique_name_and_a_description():
    names = [trigger.name for trigger in REGISTRY]
    assert len(names) == len(set(names))
    assert all(trigger.describes for trigger in REGISTRY)
    assert all(name.startswith("topic.") for name in names)


def test_a_trigger_with_no_implementation_reports_a_human_gate_rather_than_passing():
    """Registering a gap is what stops it from looking like a pass.

    A trigger that cannot be honestly automated -- "is this answer actually
    responsive to the question" -- is registered with `run=None` and speaks up
    every time, rather than being left out and silently reading as clean.
    """
    gate = Trigger(
        name="topic.responsive",
        severity="advisory",
        describes="the answer may not address the question",
        run=None,
    )

    [finding] = gate.evaluate(opened(), facts())

    assert "human" in finding.summary
    assert finding.trigger == "topic.responsive"


def test_binding_a_trigger_does_not_mutate_the_registered_one():
    original = BY_NAME["topic.low_coverage"]
    bound = original.bind(minimum=99)

    assert bound is not original
    assert original.params.get("minimum") is None


def test_a_finding_carries_no_score():
    """No numbers nobody can re-derive. Severity is the whole ranking."""
    finding = Finding(trigger="t", severity="advisory", summary="s")

    assert not hasattr(finding, "score")
    assert not hasattr(finding, "priority")
