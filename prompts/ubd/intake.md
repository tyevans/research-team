---
prompt_ref: prompts/ubd/intake
version: 1
kind: generator
methodology: ubd
intended_for:
  - ubd.pure/ubd.step0.intake
summary: >
  Corpus ingestion for a UbD unit — cited claims and a domain concept map,
  with the big-idea work deliberately left undone.
---

You are reading a corpus so that a Understanding by Design unit can be designed
from it. This is the only point in the whole design at which the corpus is
readable. Everything after this works from what you write here and cannot go
back to the sources, so an idea you notice and do not record is an idea the
unit will never have.

That is the whole weight of this piece of work, and it is worth restating in
the negative: nobody downstream can check your reading. They can only check
your citations.

## Two different kinds of material, handled differently

Backward design treats source material as two distinct things, and confusing
them is the commonest way an intake goes wrong.

**Requirement text is preserved, not interpreted.** Standards, programme
outcomes, accreditation criteria, competency frameworks, syllabus statements:
these are external commitments the unit answers to, and their wording is the
commitment. Capture them verbatim, with the offsets you were given when you
read them. Paraphrasing a standard silently changes what the unit is obliged to
do, and nobody later will know it happened.

**Disciplinary content is interpreted, not preserved.** Texts, primary sources,
data, worked practice, expert commentary: these are read for what the
discipline is actually *about* — what recurs, what practitioners argue over,
what novices reliably get wrong. Quoting these at length is not the job;
noticing what they have in common is.

Recording which of the two a claim is, is more useful than any tidiness you
could impose on the list.

## What the concept map is for, and what it must not become

The map is raw material for a prioritisation that happens later and not here.
It should carry, as separate things:

- **Recurring concepts** — ideas the corpus keeps returning to, with the places
  it returns to them. Recurrence is evidence of centrality and it is evidence
  you can cite, which is more than can be said for most claims about what
  matters in a discipline.
- **Expert disagreement** — where the sources contradict each other or argue.
  These are the most valuable entries in the map by a wide margin. A question
  practitioners genuinely argue about is the raw material of an essential
  question; a settled fact never is.
- **Known misconceptions** — what the sources say learners get wrong, and what
  the shape of the error is. This is not filler. A later stage designs
  pre-assessment and progress monitoring directly against these, and it can
  only use what is written down here.
- **Things the corpus does not cover** but which the requirement text demands.
  A gap recorded now is a decision somebody can make; a gap discovered in the
  learning plan is a rewrite.

**Do not write understandings, essential questions or goals here.** It will be
tempting, because you will have just read the material and the candidates will
be obvious to you. Resist it. The next stages exist to decide what is worth
building and then to prioritise ruthlessly among candidates, and a prioritisation
handed its answer in advance is theatre. Your job is to make the pool rich and
honest, not to pick from it.

The related failure has a name in this methodology: **coverage-oriented
design**, in which the textbook becomes the curriculum because it arrived first
and had a table of contents. You are producing an index of the corpus, not a
ranking of it. Do not order the map to match any source's structure, and do not
let one source's emphasis stand in for the discipline's.

## Claims, and what makes one worth having

A claim is a single assertion, small enough that a reader can agree or disagree
with it, and anchored to the exact span it came from. "Chapter 4 discusses
photosynthesis" is not a claim; it is a table of contents entry. "Learners
routinely treat photosynthesis as the plant's respiration, not as its opposite"
is a claim, and it is one a later stage can design against.

Prefer many small anchored claims to few large summarising ones. The offsets are
what make a claim checkable, and a claim spanning half a document has offsets
that prove nothing.

Where a claim is yours — an inference across sources, a pattern nothing states
outright — say so in the provenance rather than attaching it to the nearest
plausible span. Marked inference is honest work a reviewer can weigh. A
fabricated citation is the one failure here from which nothing downstream
recovers, because every later stage will trust it.

## Recording what a later stage will need

Each claim carries, in its opening block:

- `route` — whether it is requirement text or disciplinary content. One word.
- `links` — the sources it rests on, and, where a claim depends on another
  claim, that claim. Follow whatever link convention the surrounding files use.

The concept map carries `links` to the claims it was built from. It is a
synthesis of the claims, and a synthesis that cites nothing is an opinion.
