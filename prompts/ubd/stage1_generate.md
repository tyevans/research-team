---
prompt_ref: prompts/ubd/stage1_generate
version: 1
kind: generator
methodology: ubd
intended_for:
  - ubd.pure/ubd.stage1.desired_results
summary: >
  UbD Stage 1 — transfer goals, enduring understandings, essential questions
  and the acquisition tier, over-generated and then pruned on the record.
---

This is Stage 1 of Understanding by Design: **desired results**. It is a
prioritisation, not a listing, and that sentence is the whole discipline of the
stage. There is always more content than the time allows, so the work is
choosing — and choosing means most of what you generate must die on the page
where somebody can see it die.

Work in that order: generate a genuinely over-large pool, then cut it hard, then
record what you cut and why.

## The tiers, and what distinguishes them

**Established goals** arrive from outside and are not yours to write. They are
the standards, outcomes and requirements the unit answers to. Your obligation to
them is **unpacking**: a standard copied into the design unchanged has not been
unpacked, and unpacking is a required transformation, not a formality. What
does this standard commit the unit to that its wording does not say?

**Transfer goals** state what learners should eventually be able to do *on their
own*, with this learning, in situations nobody has set up for them. They are
long-horizon and discipline-level, not unit-level. Write them with the stem
"Students will be able to independently use their learning to …".

The test that catches the common failure: if the goal names this unit's content,
it is not a transfer goal. "Use their learning to analyse the causes of the
French Revolution" is the unit wearing a transfer goal's clothes. "Apply lessons
of the past to current events, and critically appraise historical claims" is a
transfer goal — it outlives the unit, and a graduate could still be judged
against it in ten years.

The methodology expects you to author transfer goals **even when the established
goals do not state them**. That is inference and it should be marked as
inference in the provenance, not attached to a standard that does not say it.

**Understandings** are the specific, transferable generalisations a learner has
to construct for themselves. Write them with the stem "Students will understand
that …", and then check three things:

1. **It is a proposition, not a topic.** "The water cycle" is a topic.
   "Students will understand that water moves between reservoirs at rates that
   determine how quickly pollution disperses" is a proposition. If it cannot be
   agreed or disagreed with, it is not an understanding.
2. **It is specific.** "Students will understand that context matters" is a
   truism wearing the stem. A generalisation that would be true of any subject
   is not a generalisation about this one.
3. **It is in need of uncoverage.** This is the standard the whole stage is
   judged by, and it is the one thing here you cannot verify for yourself. An
   understanding worth its place is *not obvious* — it is counter-intuitive, or
   it is what novices reliably get wrong, or it is the point the discipline had
   to argue its way to. If it could be told to a learner in a sentence and
   believed, it is knowledge, not an understanding.

You will produce fluent platitudes and you will find them convincing. Everyone
does; it is the specific weakness of this task. The defence is not to try
harder, it is to write down, for each understanding you keep, **what a
competent person plausibly believes instead**. An understanding with no
plausible rival is a truism, and that test is one you can actually apply.

**Essential questions** are what the understandings look like as inquiry. They
are open — arguable, returned to, generative of further questions — and they
arise naturally both in life and in the doing of the subject. Each understanding
needs at least one, and the pairing is the point: the question is the route by
which a learner constructs the understanding rather than receives it.

A question with a right answer is a comprehension question, however it is
phrased. "When was the treaty signed" is obviously one. "What were the three
causes of the war" is one too — it has an answer, in the textbook, and the
learner's job is to find it. "Whose account of this war should we believe, and
how would we know?" is essential.

The opposite failure is a question so broad it attaches to no content — "What is
truth?" — which cannot be investigated with this unit's material and so becomes
decoration.

**Knowledge and skill** are the acquisition tier, and they are the tier this
stage is most often written without. Knowledge is what learners must be able to
recall — facts, vocabulary, conventions — written with the stem "Students will
know …". Skill is the discrete processes they must be able to carry out,
written with the stem "Students will be skilled at …".

They are not the point of the unit and they are not optional either. Every
understanding and every transfer goal presumes some acquisition, and the
presumption is exactly what goes unexamined: a performance task set before
anyone has been equipped to attempt it is the single most common way a
well-designed unit fails in a classroom, and it is invisible in the document
unless what the task presumes is written down as something the unit teaches.

Two failures to avoid, in opposite directions. An acquisition tier padded out
with everything the topic touches turns Stage 1 back into a coverage list, which
is what the prune exists to prevent. An acquisition tier left empty makes the
unit's presumptions unfalsifiable. Write what the understandings and the
performance evidence will actually need, and nothing beyond it.

Each skill carries a short `key` — a stable hyphenated handle, `weigh-two-accounts`
rather than a sentence. Stage 2's tasks name the keys they presuppose, and the
sequencing stage checks that whatever a task presupposes is equipped before the
task needs it. A skill without a key can satisfy nothing.

## Predicted misunderstandings

Write down what you expect learners to get wrong, and the *shape* of the error
rather than just its name. "Students confuse correlation and causation" is a
label; "students read any strong association as evidence of a mechanism, and
will accept a plausible mechanism as confirmation" is something a later stage
can pre-assess for and monitor against.

Where the corpus recorded misconceptions, use them. They are better evidence
than your expectations.

## The prune, and the ledger

Generate the over-large pool your brief asks for. Then apply the rule that makes
Stage 1 a prioritisation:

> Identify **only** those goals you intend to directly assess in the evidence
> stage and explicitly address in the learning plan.

This is a forward commitment. Every understanding you keep is a promise that
something later will assess it and something later will teach toward it. If you
cannot say what that would look like, cut it now — it is cheap here and
expensive two stages on.

Then write the exclusion record, and write it as an argument rather than a list.
Each entry names what was cut and **why it lost** — a truism, a duplicate of a
stronger one, no plausible rival belief, no room in the budget, better placed in
a different unit. A reviewer's most useful question at this gate is "why did
that one not make it", and an exclusion record that cannot answer it has wasted
the over-generation entirely.

Carry those entries in the opening block as `entries`, one mapping per cut with
a `candidate_id` and a `reason`, with the argument for each in the prose beneath.
The record is the only trace the pool ever leaves — the candidates you did not
keep are never written anywhere else — so how hard the screen worked can only be
read off this list. An exclusion record kept as prose alone is a screen nobody
downstream can tell happened.

A pool that was cut lightly is a sign the generation was timid, not that the
candidates were strong.

## What the opening blocks carry

For the understandings: `text` is a block scalar holding the understandings, one
per line, **each line beginning with "Students will understand that"**. The
prose beneath carries, per understanding, its rival belief, what it rests on and
which essential questions it pairs with.

For the essential questions: `text` is a block scalar holding the questions
themselves, one per line, written as questions. Do not put a framing stem in
front of them — the questions are what a reader and a check both need to see, and
a stem in front of a closed question conceals exactly the failure that matters
here.

For the transfer goals: `text` is a block scalar, one goal per line, each
beginning with the stem above.

For the knowledge and the skills: `text` is a block scalar, one per line, each
beginning with its stem. The skills artifact additionally carries `key` as a
list of the handles above, in the same order as the lines, and `position` — where
in the unit the skills are equipped, as a number.

`links` on the understandings names the essential questions artifact and the
transfer goals it serves. Every understanding must have at least one essential
question; the record of that is the link.

Where an element is your inference rather than something the sources state — and
for transfer goals it usually is — mark it as inference. This stage is expected
to author what the input documents do not contain. It is not expected to pretend
they contained it.
