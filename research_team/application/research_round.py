"""One round, as a turn: what the agent is told, and how its work is counted.

The driver in `research_run.py` names no executor -- it takes a `RunRound`
callable and asks it for counts. This is the implementation of that callable,
and it is the only place where "a round" and "a turn" meet.

**Counts come from the topic's stream, never from the reply.** The turn is run,
and then the topic is folded again and compared with the fold taken before it.
What the agent *said* it did is not read at all. That is the whole defence the
driver's novelty-decay stop rests on: a round that describes a breakthrough and
appends nothing is an empty round, and it has to be counted as one by something
the agent cannot influence with prose.

Only three counts are taken, matching `RoundOutcome`, and each is chosen for
being monotone under the events a round can append:

- `findings` is a counter on `TopicState`, so the difference is exactly the
  number of `TopicFindingRecorded` events the round appended.
- `sources_linked` is the number of source ids that were not linked before,
  rather than the change in length -- a round that unlinks one and links
  another has done work, and a length difference of zero would hide it.
- `sub_questions_opened` is the growth of the sub-question map. Keys are never
  removed; resolving one fills in its answer, which is not what this counts.

**The prompt says why the topic was raised, in the trigger's own words.** The
findings that put it at the head of the queue are computed from the log, and
handing the agent a paraphrase of them would put a second, softer account of the
same reasons in front of the model. `topic.low_coverage` fired because the topic
links one source; the message says so, and that is what the round is for.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from research_team.application.research_run import RoundOutcome
from research_team.application.topic_attention import TopicAttention

ROUND_INSTRUCTIONS = (
    "You are working one topic in an autonomous research round. Do the work "
    "and record it with the topic tools -- `record_finding` for something "
    "learned, `link_source` for a corpus document that bears on this topic, "
    "`open_topic` for a genuinely new question you cannot answer here.\n\n"
    "Two things this round is measured on, and neither is what you write "
    "here. Progress is counted from what reaches the topic's record, so a "
    "round that reads a great deal and records nothing has produced nothing. "
    "And a round that records a finding it did not learn is worse than an "
    "empty one: several consecutive empty rounds end the run, which is the "
    "correct outcome when there is nothing left to find, and a padded finding "
    "is what stops that from working.\n\n"
    "If the reasons below are already addressed, say so plainly and record "
    "nothing.\n\n"
    "A page you fetch in this round is kept in the corpus for you -- you do "
    "not have to call `remember_page` to stop it being lost, and "
    "`link_source` can cite it as soon as you have read it. What that does "
    "not do is extract it into the graph; `remember_page` is still how a page "
    "whose contents should be searchable as entities and relationships gets "
    "there. Use it for the pages that turn out to matter, not for everything "
    "you opened.\n\n"
    "Gathering is part of the work, not preparation for it. A round that "
    "finds and links a source this topic did not have has produced "
    "something, and `sources_linked` is counted exactly as findings are. "
    "Reading widely and linking nothing is the empty round described above."
)
"""What every round's turn is told, before the topic itself.

The counting rule is stated to the model on purpose. It is measured on
artifacts either way, so telling it is not what makes the measurement honest --
but a model that does not know how it is scored optimises for the reply, and
the reply is the one thing here nobody reads.

The last paragraph exists because of what else changed on this branch, not
because the counting rule above needed restating on its own. Before the
workflow was detached from research rounds, a round's system message carried
the stage's methodology, and that methodology gave gathering sources a reason
to matter -- a round doing document review, say, was told document review was
its job. Detaching the workflow removed that message and left this constant as
the only thing a round is told. Without a sentence naming `sources_linked` as
first-class, a round would be told less than it used to be -- `link_source`
would appear only in the tool list two paragraphs up, indistinguishable from
`open_topic` -- which reads as a regression in the very isolation Task 3 was
for.
"""


def round_prompt(attention: TopicAttention, question: str, scope: str = "") -> str:
    """The turn text for one round: the topic, and why it was raised.

    Takes the question and scope rather than the whole `TopicState`, because
    that is all of it a prompt may say. Handing this the aggregate's state
    would invite the prompt to grow a summary of the topic's own history, which
    the agent can read for itself with the tools it has.
    """
    lines = [
        ROUND_INSTRUCTIONS,
        "",
        f"Topic: {question}",
    ]
    if scope:
        lines.append(f"Scope: {scope}")
    lines.append("")
    lines.append("Raised because:")
    for finding in attention.findings:
        cites = f" (see: {', '.join(finding.cites)})" if finding.cites else ""
        lines.append(f"- [{finding.check}] {finding.message}{cites}")
        if finding.suggested_edit:
            lines.append(f"  suggested: {finding.suggested_edit}")
    return "\n".join(lines)


class TopicRoundRunner:
    """Runs one round as one turn, and counts what it appended.

    Takes `run_turn` already bound to a session rather than a session id and a
    supervisor, so a run's rounds cannot be spread across sessions by accident
    and so a test can drive this with a callable that never touches a model.

    The turn's return value is discarded, deliberately. It carries the event
    span the turn wrote, which is a fact about the *session's* stream; what a
    round produced is a fact about the *topic's*, and the two are not the same
    slice of the log.
    """

    def __init__(
        self,
        topics,
        run_turn: Callable[[str], Awaitable[object]],
    ) -> None:
        self._topics = topics
        self._run_turn = run_turn

    async def __call__(self, topic_id: UUID, attention: TopicAttention) -> RoundOutcome:
        before = (await self._topics.load(topic_id)).state
        await self._run_turn(round_prompt(attention, before.question, before.scope))
        after = (await self._topics.load(topic_id)).state
        return RoundOutcome(
            findings=max(after.findings - before.findings, 0),
            sources_linked=len(set(after.source_ids) - set(before.source_ids)),
            sub_questions_opened=max(len(after.sub_questions) - len(before.sub_questions), 0),
        )
