---
prompt_ref: prompts/ubd/stage3_generate
version: 1
kind: generator
methodology: ubd
intended_for:
  - ubd.pure/ubd.stage3.learning_plan
  - hybrid.default/ubd.stage3.learning_plan
summary: >
  UbD Stage 3 — the learning plan: A/M/T-coded events, WHERETO, pre-assessment
  against predicted misconceptions, and resources chosen last.
---

This is Stage 3 of Understanding by Design: **the learning plan**. It comes
last, and it is constrained from both sides. The intents were settled two stages
ago and the evidence was specified one stage ago; your job is to design the
means by which learners reach the first and succeed at the second.

Two things follow immediately, and they are the two rules most often broken.

**You do not revisit the earlier decisions.** If the plan will not fit, or an
intent has no plausible route, or the performance task turns out to need more
than the calendar holds — say so, in your prose, as a finding. Do not resolve it
by quietly narrowing an intent or by simplifying the assessment. Those stages
are settled and their files are their record; the route back is an amendment
raised against them, which a human decides.

**Resources are chosen last, and here.** Not before the events, and not as the
thing the events are built around. A plan built to match a textbook's chapters
is coverage-oriented design, which is the failure this whole methodology is
arranged to prevent. Every resource you select has to be justified against a
specific event serving a specific intent — and if a resource cannot be, the
honest move is to drop it, however good it is.

## Acquisition, meaning-making, transfer

Every learning event is coded **A**, **M** or **T**, and this coding is the
load-bearing mechanism of the stage.

- **A — acquisition.** Learners take on facts, vocabulary, procedures,
  discrete skills. Direct instruction, worked examples, practice with feedback.
- **M — meaning-making.** Learners construct the understanding for themselves:
  comparing cases, resolving a contradiction, arguing a position, building and
  testing a model, being wrong in a way they can see.
- **T — transfer.** Learners apply the learning in a new situation, with
  decreasing support, and judge for themselves what applies.

**The all-A plan is the commonest real design failure in this framework**, and
it is nearly invisible in prose: every event looks purposeful, the coverage is
complete, and the unit never asks a learner to make meaning of anything. It
happens because acquisition is the easiest thing to plan and the easiest to
recognise as teaching. Read your own draft for it before anything else.

The associated trap is subtler: an event that *says* it is meaning-making but is
delivered by telling. Understandings cannot be transmitted; a lecture explaining
the understanding is an acquisition event with an M written on it. If the
learner's part of an event is to receive it, it is A, and coding it otherwise
makes the balance check pass while the plan stays broken.

Transfer events need diminishing scaffolding across the unit. A single transfer
event at the end, which is the assessment, means the unit never practised
transfer — it only tested it.

## WHERETO

WHERETO is a checklist over the whole plan and a self-audit, **not an order of
instruction**. The letters do not sequence anything.

- **W — where, why, what.** Learners know where the unit is going, why it
  matters, and what will be required of them, including the criteria they will
  be judged by. This must be **early** — in the first quarter of the sequence.
  A unit that reveals its performance task and rubric the week they are due has
  had a rubric and not a design. The reciprocal is also W: find out where
  learners are coming from.
- **H — hook and hold.** Immerse learners in the ideas immediately, through
  something thought-provoking at the heart of the unit — not a decorative
  attention-getter unrelated to what follows.
- **E — equip and experience.** The tools, skills, information and experience
  needed to reach the understandings and succeed at the performance. Every skill
  the performance task presupposes is equipped here, and equipped *before* the
  task needs it.
- **R — rethink, rehearse, revise, refine.** Learners revisit ideas with new
  evidence or a different perspective, and get the chance to improve their work.
  A plan with no R is a single pass, which makes the performance task a one-shot
  exam in disguise however it was designed.
- **E2 — evaluate.** Diagnostic and formative feedback, and opportunities for
  learners to self-assess and self-adjust before the work counts.
- **T — tailor.** Differentiate route, support and pacing to readiness and
  interest, **without sacrificing validity or rigour**. That clause is the whole
  test: an adaptation that changes the route is differentiation, and one that
  changes what is being measured has quietly assessed a different thing for some
  learners.
- **O — organise.** Sequence to build understanding, which is not the order a
  textbook uses; textbooks are organised by topic, and understanding is not
  built topic by topic.

Every letter needs at least one event. R and E2 are the two most often absent,
and their absence is what turns a unit back into a course of lectures with a
test.

## Pre-assessment and progress monitoring

Pre-assessment checks prior knowledge and skill, and — specifically — the
misconceptions the earlier stages predicted. Design against those by name. A
generic diagnostic quiz tells you a score; a pre-assessment aimed at a predicted
misconception tells you whether the thing you designed the unit to fix is
actually there.

The monitoring plan carries three things, per phase or per event: how progress
toward acquisition, meaning and transfer will be watched *during* the events;
where the rough spots and likely misunderstandings are; and how learners get
feedback in time to use it. Feedback that arrives after the work is graded is a
result, not feedback.

## The budget is real

Give every event a duration and make the total fit the time budget the context
profile recorded. It is a stated ceiling and the plan will be reported against
it.

When the plan does not fit — and first drafts routinely do not — cut scope
deliberately and say what you cut, or raise the finding that the unit needs more
time than it has. What must not happen is both quietly: shaving durations until
the arithmetic works produces a plan that fits on paper and fails in a room,
and it is the reviewer, not you, who is entitled to make that trade.

Revision cycles are the first thing cut under pressure and the thing least
worth cutting. A unit with no R does not save time; it spends the same time
producing work nobody improved.

## What the opening blocks carry

On the learning events artifact:

- `amt` — the list of codes the plan's events actually use. Each event carries
  its own code in the body; this field is the union across them, and all three
  of A, M and T must be genuinely present.
- `whereto` — the list of WHERETO letters covered across the plan, spelling the
  evaluate letter `E2` to distinguish it from equip. Quote the letters.
- `code` — the WHERETO letters carried by the plan's opening events. `W` must be
  among them, for the reason above.
- `position` — the artifact's place in the unit's timeline, as a number, and
  a number on each event in the body.
- `minutes` — the total instructional minutes the plan consumes.
- `links` — the intents each part of the plan serves. Every learning event must
  serve at least one; an event that serves none is an activity, and an activity
  with no purpose behind it is the first of the two sins this methodology names.

Resource selections carry `links` to the events that use them, so that a
resource which turns out to serve nothing is visible as such.
