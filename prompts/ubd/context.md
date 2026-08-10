---
prompt_ref: prompts/ubd/context
version: 1
kind: generator
methodology: ubd
intended_for:
  - ubd.pure/ubd.step1.context
summary: >
  Context framing before UbD Stage 1 — who this is for, what is fixed, and
  whether the unit is worth building at all.
---

Understanding by Design assumes a unit is happening. This step does not.

That is a deliberate departure from textbook UbD and the reason it exists is
worth stating plainly: an automated design pipeline is biased toward producing
its own output. It will design a unit for a problem that is not an instructional
problem, or a unit that duplicates one already taught, because designing is what
it does. The only defence is a step whose honest answer is sometimes "do not
build this", and this is that step.

So do the framing work, and then answer the question the framing was for.

## The profile

Write down what the design is being made *for*, in enough detail that a later
stage can be held to it:

- **The learners.** Who they are, what they already have, and — the part
  usually skipped — what they can already do that this unit is about. Prior
  knowledge stated as a level ("intermediate") is not usable. Prior knowledge
  stated as accomplishments ("can read a balance sheet, has never built one")
  is.
- **Prior experience with the ideas, including the wrong kind.** Where the
  corpus recorded misconceptions learners arrive with, carry them forward here.
  They will be designed against twice, later.
- **Modality and setting.** Where the learning happens, what is available in the
  room, what the learners can be asked to do outside it.
- **The time budget.** See below; it is the field with teeth.
- **Institutional constraints** — assessment regulations, timetable shape,
  accreditation obligations, anything that limits the design rather than
  informing it.

**The time budget is a commitment, not an estimate.** Record it as a whole
number of instructional minutes, in a field named `time_budget`, and mean it. A
later stage's plan is measured against this number and will be reported as over
budget if it exceeds it. A generous guess made here does not create time; it
produces a plan that cannot be taught and a stage gate that passes when it
should not have. If the real budget is uncertain, record the smaller credible
figure and say in the prose why.

## The constraint register

Separate from the profile, because they are read at different moments and by
different people. The register is the list of things the design may not change,
each with two things attached: **who fixed it**, and **whether it is genuinely
fixed or merely inherited**.

That second distinction is most of the value. "Assessment must be a two-hour
written exam" is a constraint if the regulations say so and an assumption if it
is what last year's version did. Designs are routinely crippled by inherited
constraints nobody has ever tested, and the register is where the difference
gets written down while somebody still has the standing to challenge it.

Where a constraint would prevent the unit from assessing understanding at all —
a format that can only test recall, a schedule with no room for revision — say
so here rather than discovering it two stages later. That is a finding, not a
complaint.

## The decision

Having written both, answer: **is this unit worth building?**

Argue for the answer you did not reach. Specifically, make the strongest case
you can that this should *not* be built, and then say why it fails, or concede
it. The cases worth testing:

- **The problem is not an instructional problem.** People know what to do and do
  not do it; the tooling is broken; the incentives are wrong. Teaching is a
  slow and expensive answer to those and usually the wrong one.
- **The goals cannot support a unit.** UbD's Stage 1 needs ideas worth
  uncovering. If the established goals decompose into a list of procedures with
  nothing contestable behind them, the honest output is training material, not
  a unit built around enduring understandings, and this methodology will
  produce an elaborate wrapper for a checklist.
- **The corpus cannot support the design.** If what was read is thin, or is one
  source's opinion, later stages will fabricate fluently to fill the gap.
- **It already exists.** Duplication is the cheapest failure to catch and the
  one an automated pipeline is least equipped to notice.
- **The time budget cannot hold a unit.** Understanding takes rehearsal,
  revision and a transfer performance. A budget that fits a lecture and a quiz
  fits acquisition and nothing above it.

State the recommendation and the reasoning, both. The person reading this is
deciding whether to spend the rest of the design, and a recommendation with no
argument gives them nothing to disagree with.
