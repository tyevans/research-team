"""What a round tells the agent, and how it counts what came back.

The counting tests are the load-bearing half. A round is scored on what
reached the topic's stream, and every one of these drives the runner with a
turn that *says* something and appends nothing, or appends something and says
nothing, so that a runner reading the reply instead of the fold would fail.
"""

from uuid import uuid4

from research_team.application.findings import Finding
from research_team.application.research_round import (
    ROUND_INSTRUCTIONS,
    TopicRoundRunner,
    round_prompt,
)
from research_team.application.topic_attention import TopicAttention
from research_team.domain.topic import SubQuestion, TopicState


def attention(*findings):
    return TopicAttention(topic_id=uuid4(), findings=tuple(findings))


def finding(check="topic.low_coverage", message="only one source", **kwargs):
    return Finding(check=check, severity="blocking", message=message, **kwargs)


class FakeTopic:
    def __init__(self, state):
        self.state = state


class ScriptedTopics:
    """Hands out a different fold on each load, so a turn can appear to work."""

    def __init__(self, *states):
        self.states = list(states)

    async def load(self, topic_id):
        return FakeTopic(self.states.pop(0) if len(self.states) > 1 else self.states[0])


def state(**kwargs):
    kwargs.setdefault("question", "does it?")
    return TopicState(topic_id=uuid4(), status="open", **kwargs)


# ---------------- the prompt ----------------


def test_the_prompt_carries_the_triggers_own_words():
    """Not a paraphrase: the finding is computed from the log, so it is the reason."""
    raised = attention(
        finding(check="topic.new_material", message="3 sources arrived", cites=("s1", "s2"))
    )

    text = round_prompt(raised, "what changed?", scope="since March")

    assert "what changed?" in text
    assert "since March" in text
    assert "topic.new_material" in text
    assert "3 sources arrived" in text
    assert "s1, s2" in text


def test_the_prompt_says_how_the_round_is_scored():
    """A model that does not know it is measured on artifacts optimises the reply."""
    assert "record" in ROUND_INSTRUCTIONS
    assert ROUND_INSTRUCTIONS in round_prompt(attention(finding()), "q")


def test_a_prompt_with_no_scope_does_not_invent_one():
    assert "Scope:" not in round_prompt(attention(finding()), "q")


# ---------------- the counting ----------------


async def test_a_round_that_records_nothing_counts_as_nothing():
    """However well it described itself. This is what novelty decay reads."""
    before = state(findings=0)
    runner = TopicRoundRunner(ScriptedTopics(before, before), _reply("I found a great deal"))

    outcome = await runner(before.topic_id, attention(finding()))

    assert outcome.produced_nothing


async def test_findings_are_counted_from_the_topics_own_counter():
    runner = TopicRoundRunner(ScriptedTopics(state(findings=2), state(findings=5)), _reply(""))

    outcome = await runner(uuid4(), attention(finding()))

    assert outcome.findings == 3


async def test_a_round_that_swaps_one_source_for_another_has_still_linked_one():
    """A length difference would report zero, which is the wrong answer."""
    runner = TopicRoundRunner(
        ScriptedTopics(state(source_ids=["a"]), state(source_ids=["b"])), _reply("")
    )

    outcome = await runner(uuid4(), attention(finding()))

    assert outcome.sources_linked == 1
    assert not outcome.produced_nothing


async def test_resolving_a_sub_question_is_not_opening_one():
    """Keys are never removed, so growth is the only thing that counts as opening."""
    open_one = state(sub_questions={"k": SubQuestion(question="?")})
    answered = state(sub_questions={"k": SubQuestion(question="?", answer="yes")})
    runner = TopicRoundRunner(ScriptedTopics(open_one, answered), _reply(""))

    outcome = await runner(uuid4(), attention(finding()))

    assert outcome.sub_questions_opened == 0


async def test_the_turn_is_given_the_round_prompt():
    seen = []

    async def capture(prompt):
        seen.append(prompt)

    before = state(question="why?")
    await TopicRoundRunner(ScriptedTopics(before, before), capture)(
        before.topic_id, attention(finding(message="only one source"))
    )

    assert "why?" in seen[0]
    assert "only one source" in seen[0]


def _reply(text):
    async def run_turn(prompt):
        return text

    return run_turn
