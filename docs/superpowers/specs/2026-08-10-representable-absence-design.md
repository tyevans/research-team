# Recording what was looked for and not found

## The gap

A research run that searches five ways and finds nothing leaves almost no
trace of having looked. `TopicInvestigated` fires on every round, *"Recorded
even when the look found nothing"* (`domain/topic.py:131-150`), and carries
three fields: `at_position`, `by_run_id`, and a free-text `summary`. When the
round produced nothing, `_summarize` writes the literal string `"nothing
recorded"` (`application/auto_research.py:299-310`). When the round *raised*,
`_record_look` writes `"failed"` (`:239`).

**So "we searched and the answer does not appear to exist" and "the model
endpoint was down" are the same event with different English in one field.**
Neither is queryable, and neither says what was searched.

The consequence recurs. `_rework_thrash` (`application/topic_attention.py:347-369`)
already notices the pattern — two or more looks since the last finding — and
reports `"{n} look(s) with nothing recorded since the last one"`. It is
advisory, so it only deprioritises within the queue
(`infrastructure/persistence/topics.py:509`); the topic stays live and gets
looked at again, forever, by every later run. Each of those runs re-derives
the same absence from nothing, because the previous run's attempt was never
written down.

There is a second reason this is worth fixing beyond wasted effort. The
project's check library already treats absence as a finding rather than a
silence, and says why: `_contradiction_escalation` reports a missing log
because *"'No contradictions were found' and 'nobody looked' are the same
empty page"* (`application/checks.py:1685-1697`), and `_source_starvation`
reports a starved route *"with no affected artifact, deliberately: the finding
is about what is not there"* (`:1604-1615`). The topic layer has the same
problem and none of that machinery.

## What this is not

**It is not a new open-question node.** A `Topic` already is one:
`TopicState` (`domain/topic.py:333-390`) carries a `question`, a `rationale`,
`sub_questions`, linked sources, and the lifecycle
`open → investigating → answered | not_pursuing | superseded`
(`topic.py:42-51`). Anything shaped like "a question we have not answered yet"
belongs on a topic, and building a second one — in the knowledge graph or
anywhere else — would produce two representations of one idea that immediately
disagree about which is authoritative.

**It is not a way for a run to stop pursuing something.** `TopicPort` has no
`close_topic`, deliberately (`application/topics.py:94-102`):

> an autonomous run that could close its own topics could empty its queue
> without answering anything -- which is the confabulated ending this whole
> design exists to prevent. Closing stays a human action.

A tool that let an agent declare a question unanswerable is that same failure
in different clothing. **Everything below is evidence for a human's decision,
never a substitute for it.**

## 1. A gap is the twin of a finding, and is recorded the same way

`TopicFindingRecorded` (`topic.py:151-161`) is *"the unit of progress"*. The
symmetric event is `TopicGapRecorded`: the unit of *searched and did not
find*.

```
@register_event
class TopicGapRecorded(DomainEvent):
    aggregate_type: str = "Topic"
    looking_for: str     # what an answer would have been
    tried: list[str]     # the queries and sources actually attempted
```

`looking_for` and a non-empty `tried` are both required, and `decide` refuses
without them — for `TopicOpened`'s reason, which requires both question and
rationale (`topic.py:64`), and `TopicSourceUnlinked`'s, which requires a
reason (`:117`). **A gap with nothing in `tried` is indistinguishable from
never having looked**, which is the exact confusion this exists to remove.

`tried` is a list of strings rather than structured search results because
there is nothing structured to reference: `format_results` flattens the
payload to text at the point of receipt (`infrastructure/agent/search.py:34-60`),
and nothing downstream can map a snippet back to its URL. Recording the
queries the agent believes it ran is a claim by the agent, not a fact about
the search instance, and the field's docstring must say so. Making it a fact
would mean retaining structured results, which is a larger change and is not
required to stop the recurrence.

The tool is `record_gap(looking_for, tried)`, added beside the four existing
topic tools (`infrastructure/agent/topic_tools.py:209`) and ungated like
them — a record of failure is not a hazard, and gating it would discourage
exactly the honesty it exists to collect.

**Rejected — inferring the gap from `RoundOutcome.produced_nothing`.** The
driver already computes it (`application/auto_research.py:84-86`) from state
deltas, with no agent cooperation needed, which makes it tempting. But the
driver cannot see what was searched — only that nothing arrived — so an
inferred gap records the fact already recorded and none of the part that is
missing. It would also fire on a round that produced nothing because it
crashed.

**Chosen — the agent records it, as it records a finding.** What was looked
for is a judgement only the agent holds. The cost is that an agent may fail to
call it; §4 is what makes that cost visible rather than silent.

## 2. A gap never closes a topic and never silences a trigger

`TopicGapRecorded` does not change `status`. `evolve` increments a `gaps`
counter on `TopicState` and records `last_gap_at`; nothing else.

It specifically does not emit or imply `TopicTriggerAcknowledged`. That event
already exists as the silencing mechanism, requires a reason and an expiry,
and refuses without either (`topic.py:198-210`, `:538-545`) — and **nothing
emits it from an agent tool today**. Wiring gaps to it would hand an
autonomous run the ability to mute its own alarms, which is `close_topic`'s
prohibition arriving through a side door. Acknowledging stays a human action,
and a recorded gap is the evidence a human would acknowledge *from*.

## 3. The thrash trigger reports what was tried

`_rework_thrash` currently says `"{n} look(s) with nothing recorded since the
last one"` and suggests *"Change what you are asking; re-reading the same
material is not working."* With gaps recorded it can say what was already
attempted, which turns an unactionable nudge into one a reader can act on:
the suggestion becomes worth following because it names what not to repeat.

Its firing condition is untouched — see §5. What changes is only what it says
once it has fired. Its severity stays `advisory` and its registration is unchanged
(`topic_attention.py:416-420`). A topic with recorded gaps is deprioritised,
never removed. This follows `topic_attention.py:41-45` — *"If the only
possible response to a finding is to dismiss it, the trigger should not
exist"* — in the direction that keeps the finding: the response to a gap is a
human deciding to close, rescope, or acknowledge, and all three remain
available.

**No new trigger.** A `topic.has_gaps` trigger would report a fact already
carried by `topic.rework_thrash`, and two triggers firing on one condition is
how a queue starts double-counting the thing it is trying to rank.

## 4. Search bounds itself in band, and says what to do instead

The behaviour asked for is: after some number of fruitless searches, stop
searching this turn. The mechanism has to be chosen carefully, because the
obvious ones are all rejected elsewhere in this codebase.

**Rejected — a counter on `AutonomyPolicy`.** The policy is per-tool and
three-valued and has no counter by design. B24 rejects counting as a
permission mechanism by name: *"Not a blanket 'N auto-approvals', which is
`auto` with a counter: the count is not what makes an approval meaningful, the
scope is."* A search bound is not a permission question — the agent is
allowed to search; it is being told that searching again will not help.

**Rejected — extending `Budget`.** `Budget` bounds a *run*
(`domain/auto_research.py:74-86`) and its counters live on `AutoRunState`.
A turn-scoped bound there would make the bound invisible to any turn outside
an auto-research run, which is most turns.

**Chosen — the tool counts its own consecutive empty results, per turn, and
degrades in band.** A small `SearchAttempts` object is held by the
`web_search` closure and reset at the turn boundary by an `AgentMiddleware`
(the mechanism `StageMiddleware` already uses,
`infrastructure/agent/stage_middleware.py:117`). It counts *consecutive*
results equal to `"No results."` and resets on any non-empty result.

Past the threshold, `web_search` returns, instead of searching:

> That is N searches in this turn with no results. Searching again with a
> similar query will not help. Record what you were looking for with
> `record_gap`, or ask a different question.

This is a refusal the model can act on, in the shape this codebase uses
everywhere else — `fetch`'s unreadable-page sentence tells the model to treat
the empty answer as an answer rather than something to retry
(`infrastructure/agent/fetch.py:46-50`), and an unresolved `prompt_ref`
degrades to an in-band notice rather than a silent fallback (#91). It is not
a permission change: `TOOL_FLOORS` is untouched, and `application/auto_research.py:24-27`'s
rule that the driver never writes the policy is unaffected because nothing
here writes a policy at all.

The threshold is a module constant with a named default, not a parameter
threaded from configuration. There is exactly one caller and it takes the
default, which is `MAX_OPEN_TOPICS`'s reasoning (`application/topics.py:23`)
and B26's.

## 5. `"failed"` stops meaning the same as `"nothing recorded"`

`_record_look` writes `"failed"` when a round raised and `"nothing recorded"`
when it produced nothing (`auto_research.py:239`, `:299-310`). Both land in
the same free-text field, so nothing downstream can distinguish a fruitless
round from a broken one — and `_rework_thrash` counts them alike, so a topic
whose rounds keep crashing is reported as one that keeps finding nothing.

`TopicInvestigated` gains `outcome: Literal["produced", "nothing", "failed"] | None = None`.
`summary` stays as it is; it is for a person to read.

**The default is `None`, meaning "written before this was recorded", and not
one of the three values.** Defaulting to any real outcome would assert
something about rounds nobody observed: `"produced"` would quietly stop
`_rework_thrash` counting historic fruitless rounds, and `"nothing"` would
claim every past round found nothing. `None` is the only honest reading of a
payload that predates the field.

**`_rework_thrash`'s firing condition does not change.** It continues to
compare `state.investigations` against `findings_at_last_investigation`
(`topic_attention.py:347-369`), which works on payloads old and new alike. A
trigger whose condition depended on a field half its history lacks would
report differently about the same topic depending on when its rounds happened.

**`outcome` is recorded now and consumed later.** Reading it from
`_rework_thrash` — to keep the trigger from describing a crashed round as one
that found nothing — would need `TopicState` to carry the last look's
outcome, which is the same trade this project already refused for gap text:
see `TopicState.gaps`' docstring, "deliberately absent: any finding text, any
attention flag, any score." Widening the state for one more field it exists
only to report is not a decision to make twice in one change. The field is
written anyway, because the distinction it captures — a fruitless round
versus a crashed one — is only recordable at the moment the round ends. An
event log that did not capture it then can never be back-filled; not writing
it now makes the distinction permanently unrecoverable for every round
between today and whenever a consumer is built. `outcome` costs one nullable
field and keeps that consumer possible. Nothing reads it yet.

This is a schema change to an event already written, so
`tests/infrastructure/test_schema_evolution.py` gains the old-shaped payload
and asserts it still loads with `outcome` absent, per `CLAUDE.md`'s rule.

## What this does not do

**No structured search results.** `tried` is what the agent says it tried, not
what the search instance was asked. Retaining structured results would make it
checkable and is a larger change; the recurrence this fixes does not need it.

**No detection of gaps the agent did not notice.** This records absences an
agent recognised, exactly as `record_finding` records findings it recognised.
Detecting an unnoticed gap is the shape of B23's proposed contradiction
critic — a prompt behind a gate producing a *candidate* for a human — and
belongs with that work, not here.

**No closing, no acknowledging, no rescoping.** A topic with twenty recorded
gaps stays live and stays in the queue. Every response to that remains a
human's.

**No cross-run memory of queries.** Gaps are per topic. Two topics asking
overlapping questions each record their own attempts, and nothing notices the
overlap. Deduplicating across topics needs a notion of query similarity, and
`recall.py:16-25` argues at length against exactly that inference for search
queries.

**Nothing for B15.** A contradiction record is the sibling of a gap record —
both are the graph learning to say something other than a confident positive —
but a contest already has its own event and its own trigger, and merging the
two designs would produce one worse than either.

**No change to the run budget.** `Budget` already stops a run after
`quiet_rounds` rounds that produced nothing
(`domain/auto_research.py:274-291`). This makes those rounds legible; it does
not change when a run gives up.

## Testing

- A gap recorded against a topic appears in its state and does not change its
  status.
- `record_gap` with an empty `tried` is refused, naming what is missing.
- `record_gap` with an empty `looking_for` is refused.
- Recording a gap does not emit `TopicTriggerAcknowledged` and does not
  silence any trigger — asserted directly, because the whole hazard is that it
  would be convenient if it did.
- A topic with recorded gaps still appears in `TopicQueue.evaluate`.
- `topic.rework_thrash` names what was tried when gaps exist, and still fires
  with its existing message when none do.
- `topic.rework_thrash` fires on exactly the same condition as before this
  change — a test that would fail if the condition were made to depend on
  `outcome`, since a topic's history predates the field.
- A `TopicInvestigated` payload written before `outcome` existed still loads,
  with `outcome` absent rather than defaulted to a real value
  (schema-evolution test).
- `web_search` returns the in-band notice after the threshold, and the notice
  names `record_gap`.
- The counter resets on any non-empty result, so an intermittently productive
  search is never bounded.
- The counter resets at the turn boundary, so a turn does not inherit the
  previous turn's misses.
- `TOOL_FLOORS` and `AutonomyPolicy` are unchanged by all of the above — a
  test that fails if the bound is ever implemented as a permission.
