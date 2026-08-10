---
prompt_ref: prompts/ubd/stage2_generate
version: 1
kind: generator
methodology: ubd
intended_for:
  - ubd.pure/ubd.stage2.evidence
  - hybrid.default/ubd.stage2.evidence
summary: >
  UbD Stage 2 — evidence before instruction: GRASPS performance tasks, other
  evidence, evaluative criteria and the alignment back to Stage 1.
---

This is Stage 2 of Understanding by Design: **evidence**. It runs before any
teaching is planned, and that ordering is the single most important thing about
it. Stage 2 is the stage people skip, and skipping it is what produces both of
the failures this methodology exists to prevent — activities with no evidence
behind them, and coverage with no evidence at all.

The instruction is to **think like an assessor before designing lessons**. An
assessor does not ask "what would be a good activity"; they ask "what would I
have to see a learner do before I would believe they understand this, and would
a sceptic accept it as evidence?"

## What you inherit, and what you may not touch

The intents this unit is built around have been settled and approved by a human
at a gate. They are your input, not your material. You do not add to them, you
do not reword them, and you do not quietly narrow one because it is awkward to
assess.

Every one of them needs evidence. If you reach an intent you cannot design valid
evidence for, that is a finding worth stating loudly in your prose — it usually
means the intent is untestable as written — but it is a finding to raise, not a
licence to drop it or to replace it with something easier and adjacent. An intent
that quietly loses its evidence has been deleted from the unit by an agent that
had no authority to delete it, and nothing downstream will show that it happened.

Read the subtypes the intents carry, because they demand different evidence:

- An intent that names **long-horizon autonomous transfer** requires a
  performance task. A quiz cannot evidence transfer, no matter how hard its
  questions are, because transfer is by definition performance in a situation
  nobody set up.
- An intent that names an **understanding** requires evidence of
  meaning-*making*: the learner constructing, explaining, defending. A correct
  answer is not evidence of understanding if it could have been produced by
  recall.
- An intent that names **knowledge or discrete skill** is well served by other
  evidence — quizzes, prompts, observations, work samples — and does not need a
  performance task of its own.

## The Six Facets, used as a selector

The facets — explain, interpret, apply, take perspective, empathise,
self-assess — are how you generate a task type from an understanding. They are
six equal indicators and explicitly **not** a hierarchy: nothing is "higher"
than explanation, and there is no progression through them.

Use **only** the facets that give appropriate evidence of the particular
understanding in front of you. Mathematics tends to apply, interpret and
explain; a unit on a contested history earns perspective and empathy honestly.
Forcing all six into one task is checklist-ism and is a named anti-pattern: it
produces a task with six half-hearted parts and no centre.

Record the selection, per understanding, **including the facets you excluded and
why**. An exclusion with a reason is a design decision; an exclusion with no
reason is indistinguishable from an oversight, and the reasons are the more
useful half of the record.

## GRASPS, and the field that gives it away

Performance tasks are authored to the GRASPS schema — goal, role, audience,
situation, performance, standards. Fill all six, and fill them with something.

**Situation is where these fail.** A situation reading "a real-world scenario"
or "an authentic context" is not a situation; it is the word for one. A
situation is a specific setting with specific constraints and specific
opportunities: what is missing, what is in the way, what the deadline is, who
disagrees. The methodology asks for real-world **messiness**, and messiness is
the property that distinguishes a task from a school exercise wearing a costume.

The same failure appears in role and audience. "Write a report for your teacher"
has a nominal role and a nominal audience, and it collapses GRASPS back into an
assignment. The role should be one someone actually occupies, and the audience
should be one with something at stake in the answer — a client who will act on
it, a committee that can say no, a public that will misread it if it is unclear.

The test that catches most of it: **would a practitioner recognise this
situation?** Not "is it plausible" — plausible is easy to fabricate — but would
someone who does this for a living say yes, that happens.

Performance tasks are **culminating performances for the unit**, not daily
lesson activities. If you have written one per lesson, you have written
activities.

## Other evidence, and the argument for it

Other evidence is not padding for coverage. It does two jobs the performance
task cannot: it evidences the knowledge and skill the task presumes but does not
isolate, and it disambiguates. A group performance task under-determines what any
individual attained, and other evidence is what makes an individual claim
defensible. That is a measurement argument, not a bookkeeping one, and it is the
reason to design overlap deliberately rather than avoid it.

Vary the format. A stage whose other evidence is four quizzes has one
instrument, not four.

## Evaluative criteria and rubrics

Criteria state what qualities matter, whatever the assessment's format.
Practitioner convention distinguishes four kinds, and the distinction is
load-bearing:

- **impact** — was the desired result actually achieved? Did the argument
  persuade, did the design work, did the explanation land?
- **content** — accuracy, thoroughness, proficiency.
- **quality** — craftsmanship, mechanics, presentation.
- **process** — how the work was carried out.

**A performance assessment without an impact criterion has stopped assessing
transfer.** It is the criterion most often missing and the one that does the
work: without it, a polished miss outscores a rough success, and the task
measures compliance again. Content, quality and process are drawn on as the
assessment needs them; impact is not optional.

Record the criterion kinds each criteria artifact covers in a `code` field, as a
list of those words. Rubrics turn the criteria into performance levels, and each
level must describe what the work *looks like*, not how much of it there is —
"three sources" is a count, and counts are how rubrics quietly become
checklists.

## The alignment record

Build the intent-by-evidence matrix: every intent on one axis, every piece of
evidence on the other. Two questions it answers, and both are ones designers
reliably get wrong by eye:

- **Is anything unassessed?** An intent with an empty row is a promise the unit
  does not keep.
- **Is anything assessed that nothing asked for?** Evidence with an empty column
  is either an assessment of something not in Stage 1, or a Stage 1 element that
  went missing.

The alignment audit behind it: are we assessing everything we are trying to
achieve, or only the things that are easy to test and grade?

## What the opening blocks carry

`links` on each evidence artifact names the intents it serves. The links run
upward, from the evidence you are writing now to the intents that already exist
— never the other way. Do not edit an artifact an earlier stage produced; that
stage is settled, and its files are its record.

On the performance tasks, additionally:

- `requires` — a list of short keys naming the skills and knowledge the task
  presupposes a learner will already have. This is what lets a later stage check
  that the learners were equipped before the task needed them, and it is the
  origin of the classic failure where a well-designed task is set before
  anything has prepared anyone for it.
- `position` — where the task falls in the unit's timeline, as a number. A
  culminating task sits late; a task that sits early is either formative or
  misplaced.
