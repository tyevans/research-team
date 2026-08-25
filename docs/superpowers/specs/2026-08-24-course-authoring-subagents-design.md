# Course authoring by subagent fan-out

## Why

The lessons this project generates are well grounded and inert. Read
`/course/areas/agent-interaction-log/lesson-01.md` and
`/course/areas/knowledge-graph/lesson-02.md`: the sourcing is correct, the UbD
sequencing is correct, and nothing pulls the reader through a paragraph. Six
causes, all structural rather than a matter of writing quality:

1. **Every lesson opens with a thesis, never a problem.** "A system that
   records what happens has a choice about *where* to record it." Nothing is
   at risk, so there is no reason to read the second sentence.
2. **Nothing is withheld.** Each essential question is answered in the
   paragraph that raises it. The reader never holds an open question.
3. **No time.** Everything sits in documentation's present tense. "Measured on
   a five-article corpus, 105 -> 7 -> 1" is a story about somebody finding
   something out, rendered as a static property.
4. **Uniform rhythm.** Claim, block quote, "that sentence has two halves",
   gloss -- in every section. After two sections the reader can predict the
   rest.
5. **Citation density reads as a literature review.** The lesson teaches what
   the README claims rather than how the system behaves.
6. **Assessments are furniture.** The same two blocks at the end of every
   lesson, written in Stage 2 before any lesson existed.

Grounding was never the missing ingredient. The corpus is full of incidents
and the current pipeline renders them as properties.

The current pipeline is `application/course_authoring.py`: three turns per
area -- desired results, evidence, learning plan -- with one turn writing every
lesson in one context. There is no critique, no revision, nothing that hunts
for the concrete, and the assessment items are written before the prose they
assess.

## What this changes

Four Python-sequenced phases per learning area. Inside each phase the primary
agent fans out to subagents. Python owns the order and the checkpoints; the
model owns the granularity.

### Why not one agent running the whole pipeline

A model-driven run has no observable end state. `CourseAuthor` returns after
three turns today, so `CourseAuthoringRunSettled` means something. An agent
that owns the whole pipeline ends when it stops talking, and a run that
dispatched two drafters instead of five, or skipped the prose critic,
produces a complete-looking set of files and the same settled event. That is
the failure this repository has already met twice -- an event no projection
handles counts as applied, and a no-op default makes "never wired" identical
to "working."

"One revise round, never a loop" is also a rule a prompt can only request.
Python can enforce it.

### Why not Python all the way down

Hard-coding the fan-out throws away the thing subagents are for. Context
isolation per drafter is real, and the right number of anecdote hunters
depends on how rich the area turns out to be -- which is not knowable when the
loop is written.

## The reconciliation problem, and the lesson plan

`infrastructure/agent/delegation.py` already warns against exactly this design:

> Cognition argues the opposite case for *constructive* work: subagents that
> each produce part of an artifact make conflicting implicit decisions the
> parent must then reconcile.

One drafter per lesson is that case. Three drafters will each choose a voice,
a depth, and an idea of what the reader already knows, and the unit will read
like three people wrote it, because three did.

**The lesson plan is the reconciliation, made before the fan-out rather than
after.** Every decision that must be shared across lessons is fixed in the
plan: voice, what each lesson may assume from the ones before it, which
anecdote belongs to which lesson, and the exact claim each lesson owns. A
drafter fills a slot; it does not choose. Anything the plan leaves open, three
drafters will answer three ways.

## The roster

Six subagent types. Available tools are `list_sources`, `read_source`,
`graph_search`, `graph_describe`, plus the file tools.

| Subagent | Phase | Tools | Writes | Returns |
|---|---|---|---|---|
| `unit-critic` | 1 | corpus + graph, read-only files | nothing | Findings against the Stage 1 rubric, each naming the rule it fails |
| `anecdote-hunter` | 3 | corpus + graph, read-only files | nothing | Concrete incidents, numbers or contradictions, each cited and tagged with the understanding it serves |
| `lesson-drafter` | 3 | corpus + graph, read + write | one `lesson-NN.md` | The path it wrote |
| `prose-critic` | 3 | read-only files | nothing | Rubric findings on one lesson |
| `quiz-writer` | 4 | read + write | appends to one lesson | The path it changed |
| `unit-reviewer` | 4 | read + write | `review.md` | The path it wrote |

Four of the six write nothing, which is the investigative shape
`delegation.py` endorses. The three that construct each own one file no other
subagent touches.

**One writer per path, per phase.** Two subagents editing one file is the
reconciliation problem in its worst form and there is no reason to accept it.

**No subagent gets the `task` tool.** This costs nothing to arrange:
`_compile_spec` builds each subagent with plain `create_agent(model,
tools=spec["tools"], ...)` and no `SubAgentMiddleware`, so nesting is
impossible by construction in deepagents 0.7.6. Their system prompts follow
`WORKER`'s shape -- objective, boundaries, tools, output -- with no
orchestration content beyond one line saying they are a subagent, cannot see
the conversation, and what to return.

Two roster decisions and their rejected alternatives:

- **`prose-critic` writes nothing; the drafter revises its own file.** Letting
  the critic edit directly is one fewer round trip. Rejected because the
  drafter holds the plan slot and the anecdote it chose, and a critic editing
  blind will "fix" an opening by turning it back into a thesis statement.
- **`anecdote-hunter` returns to the parent rather than writing a pool file.**
  A shared `anecdotes.md` is a file several drafters read and quietly compete
  over. The parent collects the returns, assigns each anecdote to exactly one
  slot, and hands each drafter only its own.

## The phases

Each phase is one turn on one session. Python runs them in order and asserts
on what each left behind.

**Phase 1 -- Desired results.** The parent writes Stage 1, dispatches
`unit-critic`, revises once. Exactly one critique round, enforced by the phase
ending rather than by asking politely.
*Checkpoint:* `unit.md` exists, holds a Stage 1 section, 2-4 enduring
understandings and 3-5 essential questions.

**Phase 2 -- Evidence.** Unchanged from today: Stage 2 given Stage 1
verbatim. No subagents; there is nothing to fan out.
*Checkpoint:* a `## Stage 2 - Evidence` section exists with at least one
performance task per understanding.

**Phase 3 -- Plan, then draft.** Two acts in one turn, deliberately.

The parent writes the lesson plan: one slot per lesson carrying its title,
`builds_toward`, the single claim it owns, its opening move, and what it may
assume from the lessons before it. Then it dispatches `anecdote-hunter`s,
assigns each returned anecdote to exactly one slot, and fans out one
`lesson-drafter` per slot -- handing each its slot and its anecdotes and
nothing else. Then one `prose-critic` per lesson, and each drafter revises its
own file.

Plan and draft share a turn because the plan is the parent's working state.
Spilling it to a file and re-reading it in a new turn is how the
reconciliation gets lost.

*Checkpoint:* the plan names N lessons; N lesson files exist; every
`builds_toward` resolves to a real Stage 2 item; every understanding is
claimed by at least one lesson.

**Phase 4 -- Assessment.** One `quiz-writer` per lesson, given the lesson as
written rather than as planned -- so items test what was taught. Then one
`unit-reviewer` over all of them.
*Checkpoint:* every lesson carries a retrieval block, `review.md` exists,
every understanding is assessed somewhere.

### Checkpoint failures fail the run

Not a warning, not a log line. The whole reason for four phases rather than
one agent is that "it stopped" and "it finished" become different observable
states, and that only holds if a missing file raises.
`CourseAuthoringFailed` already exists in the event log.

### The plan is not persisted, and that is a cost

If phase 3 dies halfway the plan dies with it, and a retry re-plans from
scratch -- possibly differently. Writing the plan to a file buys resumability
and reintroduces the shared-pool problem for anything later that reads it.
Taking the loss for the first version, since a phase 3 that dies has usually
left a half-written unit worth discarding anyway.

## The prose rubric

Lives at `prompts/course/prose_rubric.md`, resolved by the existing
`prompt_ref` mechanism in `application/prompts.py` -- where the ref restating
its own path is the integrity check. Not a string literal inside a
prompt-building function.

`checks.py:1111` already refuses a critic and generator that share a
`prompt_ref`, which is the right instinct: a critic reading the same
instructions it is judging against finds nothing.

Six rules, each a pass/fail a critic can cite by number:

1. **Opens with a problem, not a thesis.** The first 80 words carry a specific
   moment: a failure, a measured number that surprised somebody, or two
   plausible answers that disagree. The concept is named after.
2. **Something is withheld.** At least one question is raised and left open
   for a paragraph or more before it is answered.
3. **One stated cost.** What breaks if the learner gets this wrong, with
   evidence from the corpus.
4. **No quote-then-gloss chains.** At most one block quote followed by
   restatement, per lesson.
5. **Second person with a task.** The reader is doing something, not being
   told about a system.
6. **Varied section shape.** No two consecutive sections built the same way;
   parallel bolded lists only where the parallelism is load-bearing.

Binary rules rather than a 1-5 scale, because a local model asked to score
gives everything a 4.

**One rubric, two readers.** The `lesson-drafter` gets the same file as its
brief. The rules are what to write, not a hoop to clear afterwards -- handing
the drafter something vaguer and the critic something sharp produces a
revision loop that could have been a first draft.

**What the rubric cannot do.** It can force a lesson to open with an incident;
it cannot make the incident interesting. A corpus with no incidents yields no
anecdotes, and rule 1 then produces manufactured drama, which is worse than a
flat opening. So `anecdote-hunter` is allowed to return nothing, and a slot
with no anecdote falls back to rule 1's other two forms: the surprising number
or the disagreement.

## Testing

**1. The spine, with a fake turn runner.** `CourseAuthor` already takes a
`TurnRunner` protocol, so the four phases are testable with no model.
Assertions: phases run in order and each is handed only what the phase before
produced; and one test per checkpoint, each proved red -- a fake that returns
a reply but writes no lesson files must raise, not settle. That last set is
what stops "it stopped" looking like "it finished", so it is written first.

The ordering assertion still matters for the reason the current module states:
a model given all three UbD stages at once writes the lessons first and
reverse-engineers understandings to match, fluently and with every section
present, so the output is indistinguishable from the real thing by inspection.

**2. The subagent specs, compiled for real.** This is the port-with-one-adapter
shape from CLAUDE.md, with a sharp edge: `_compile_spec` raises `ValueError`
when a spec lacks `model` or `tools`, and it raises at agent-construction time
inside a turn -- so a malformed roster entry surfaces as a failed authoring run
against a live endpoint, minutes in, naming nothing about the roster. A test
that pushes all six specs through deepagents' own compilation catches it in a
second. A test that asserts the dicts have the right keys does not, and would
look identical.

**3. A live run, which is not a gate.** The acceptance test is reading three
lessons and seeing whether they catch the reader. It runs against the real
endpoint on a real project, by hand, and belongs beside `npm run test:browser`
in CLAUDE.md's terms: outside CI, run deliberately, because it is the only
thing that judges the actual deliverable.

### What no test here can do

**Nothing asserts the prose is good.** A test that greps for "the first
sentence is not a definition" checks rule 1 with a regex, and a model that
learns to open with "Somebody wants to log that..." every time passes it
forever. The rubric is enforced by a critic at runtime, not by pytest. This is
a real gap, not one this design closes.

**A run where every subagent silently did nothing must not pass.** The defence
is that checkpoints assert on content -- N lesson files exist, each names a
real Stage 2 item, each carries a retrieval block -- and never that the turn
returned or that no exception escaped.

### Measure on the first live run

How many lesson slots received a real anecdote, versus falling back to a
number or a disagreement. If that count is near zero, this design's central
bet is wrong, and it is better to learn that from a count than from a vague
sense that the lessons still read flat. Same discipline as `105 -> 7 -> 1`.

## Out of scope

- The `workflows/ubd.py` preset engine. It terminates at a unit plan by
  design, and bending it to cover production would be a larger change than
  this pipeline. `course_authoring.py` stays hand-rolled, as it is today.
- Cost. This is roughly 4 sequential turns per area against today's 3, with
  fan-out inside them. Quality first; the spend is a later bridge.
- Whether the unit review is one document or one per learning path. One per
  area for now.
