# Widget Horizons: What Else the Component Catalog Should Carry

A companion to [`markdown-components.md`](./markdown-components.md). That document
settled the *mechanism* — fenced `component:<type>` blocks with YAML bodies, a
server-side registry, a learner projection, no nesting — and shipped a catalog of
seventeen types in §3.4. This document asks the next question: **which types are
missing, and which of the obvious candidates should be refused.**

The bar is not novelty. It is **orthogonality**: a proposed type earns its place
only if it does a pedagogical job that no already-catalogued type does. "H5P has
one" is not an argument. H5P has fifty-four, and most of them are the same three
jobs wearing different costumes.

Everything here inherits the settled constraints of §3.1-§3.2 without restating
them: fenced block plus YAML, no nesting, explicit `id`, prose in `|` block
scalars, unknown types degrade to a labeled code block, and nothing the model
writes ever becomes markup. Where a proposal strains one of those constraints I
say so rather than quietly assuming an exception.

Anything I could not confirm from a real source is marked **UNVERIFIED**.

---

## 1. What the survey actually showed

I went through H5P's full catalog, Moodle's question types, QTI 3.0's interaction
taxonomy, Anki's note types, the ADL xAPI verb vocabulary, and Articulate Rise's
block list. The useful finding is not a list of missing widgets. It is a shape.

**Every one of these catalogs collapses onto a small number of response
primitives.** QTI 3.0 — the only one of the group that was designed rather than
accreted — names twenty-two interactions
([QTI 3.0 implementation guide](https://www.imsglobal.org/spec/qti/v3p0/impl)),
and eleven of them are the *same six response primitives applied to an image
instead of text*: `graphic-order` is `order` on hotspots, `graphic-associate` is
`associate` on hotspots, `graphic-gap-match` is `gap-match` on hotspots,
`select-point` and `position-object` are choice-with-continuous-coordinates.
H5P's catalog compresses even harder: Memory Game, Image Pairing, and Find the
Words are all recognition-matching; Drag the Words, Fill in the Blanks, and
Complex Fill the Blanks are all cloze; Image Sequencing and Sort the Paragraphs
are both ordering
([H5P content types](https://h5p.org/content-types-and-applications)).

So the honest summary of the prior art is this table:

| Response primitive | QTI 3.0 | H5P | Moodle | Already in §3.4? |
|---|---|---|---|---|
| Select from a fixed set | `choice`, `inline-choice`, `hotspot`, `select-point`, `graphic-associate` | Multiple Choice, Single Choice Set, True/False, Multimedia Choice, Find the Hotspot, Personality Quiz | Multiple Choice, True/False, Calculated Multi-choice | **Yes** — `mcq`, `poll` |
| Produce text from memory | `text-entry`, `extended-text` | Fill in the Blanks, Dictation, Essay, Guess the Answer | Short Answer, Numerical, Essay, Calculated | **Partly** — `cloze` only inside an authored frame; **§3.1 gap** |
| Associate across two sets | `match`, `associate`, `gap-match`, `graphic-gap-match` | Drag and Drop, Image Pairing, Memory Game, Drag the Words | Matching, Random Short-answer Matching, Drag and drop into text | **Yes** — `matching`; **but not many-to-one, §3.2 gap** |
| Impose an order | `order`, `graphic-order` | Image Sequencing, Sort the Paragraphs | Ordering | **Yes** — `ordering` |
| Mark a region of a given artifact | `hot-text`, `hotspot`, `drawing` | Mark the Words, Find Multiple Hotspots, Image Hotspots | Drag and drop markers | **No** — **§3.3 gap** |
| Set a continuous value | `slider` | Arithmetic Quiz (indirectly) | Numerical | **No**, and mostly not worth having (§4) |
| Submit an artifact | `upload` | Audio Recorder, Documentation Tool | Essay (file) | **No**, and blocked on asset storage (§5.1) |
| Navigate a branching structure | (none — QTI is item-scoped) | Branching Scenario, Interactive Book, Game Map | (none) | **Yes** — `scenario` |
| Explain / study a given artifact | (none — QTI has no expository model) | Interactive Video, Course Presentation, Agamotto, Image Juxtaposition, Accordion | Description | **Weakly** — `diagram` hotspots only; **§3.5 gap** |
| Report about oneself | (none) | Questionnaire, Summary, Cornell Notes, Documentation Tool | (none) | **Partly** — `poll`, `reflection`; **§3.6 gap** |

The three genuine holes are the rows marked as gaps, and they are the first three
proposals below. Everything else in the prior art is either already covered, or a
media re-skin of something covered, or — a category worth naming explicitly —
*not a widget at all*.

**The register of Rise 360 is the odd one out and instructive for it.** Rise's
interactive blocks are Accordion, Tabs, Labeled Graphic, Process, Scenario,
Sorting, Timeline, Flashcard grid/stack, and Button
([Articulate Rise block types](https://www.articulate.com/360/rise/); see also
[Rise sorting activity blocks](https://www.articulatesupport.com/article/Rise-How-to-Use-Sorting-Activity-Blocks)).
Four of those nine — Accordion, Tabs, Process, Button — are **layout**, not
pedagogy. They exist because Rise is an authoring tool for people who cannot
write HTML. We are an authoring surface for a language model that writes markdown
natively, and §3.2's no-nesting rule makes layout containers structurally
impossible anyway. That is not a limitation to work around; it is the single
largest source of correct *cuts* in this document (§4.1). The one Rise block that
is genuinely a pedagogical primitive we lack is **Sorting**, and it is proposal
§3.2 below.

One more framing note before the proposals. The xAPI verb vocabulary — ADL's
list runs to `attempted`, `answered`, `completed`, `passed`, `failed`,
`mastered`, `experienced`, `interacted`, `progressed`, `responded`, `commented`,
`shared`, `voided`, among others
([ADL xAPI verbs](https://github.com/adlnet-archive/xAPIVerbs);
[xAPI statements 101](https://xapi.com/statements-101/)) — is a useful audit
instrument in the other direction. §3.6 of the design doc names events for
`attempted`, `answered`, `completed`, `passed`/`failed`, and the SRS and
checklist cases. It has **nothing that emits `commented` or `shared`**, because
there is no multi-learner surface at all. That is a real absence and §5.5 argues
it is the right absence for now, but it should be a decision rather than an
oversight.

---

## 2. The proposals, ranked

Eleven new types and three refinements to existing ones. Ranked by leverage —
that is, by how much a course improves per unit of implementation — not by how
interesting they are to build. The ranking is the opinion; the individual
descriptions are the evidence for it.

| # | Type | Job no existing type does | Spectrum (§4.3) | Phase (§3.10) |
|---|---|---|---|---|
| 1 | `alignment_map` | Shows the author what the course does *not* assess | L3 format, computed content | **v1.5** |
| 2 | `short_answer` | Recall without recognition cues | L3 | **v1.5** |
| 3 | `categorize` | Many-to-one classification with unequal bins | L3 | **v1.5** |
| 4 | `mark_the_text` | Discrimination *inside* an authentic artifact | L3 | **v1.5** |
| 5 | `annotated_artifact` | The worked example — study an expert product | L1 | **v1.5** |
| 6 | `survey` | A multi-item instrument, not one question | L2 | **v1.5** |
| 7 | `glossary` | Vocabulary as a referenceable shipped artifact | L1 | **v1.5** |
| 8 | `open_response` | Extended writing graded against a rubric | L3, non-deterministic grading | **v2** |
| 9 | `pool` / `exam` | Server-owned form selection and gating | **L5** | **v2** |
| 10 | `explorer` | Intuition for a quantitative relationship | L2, needs an expression evaluator | **v2** |
| 11 | `hotspot` | Everything above, on an image | L3, **blocked on asset storage** | **v2 at the earliest** |

### 2.1 `alignment_map` — the author's coverage report

**Purpose.** Declare the objective-to-evidence matrix for a module or course, and
render the coverage and gap analysis the server computes from the parsed AST.

**The job nothing else does.** §3.8 of the design doc ends with the claim that the
`objective:` field on assessment components "is probably the highest-leverage
thing in this whole design," because it makes an alignment report a trivial query.
It then never proposes the report. Every other component in the catalog serves a
learner. This one serves the author, and it is the only component whose value is
*negative space* — its output is the list of objectives with no assessment
evidence, the assessments tagged to no objective, and the objectives assessed
only by recognition-level items. UbD Stage 2 and Tyler's evaluation step both
demand exactly this artifact, and both are currently unserved by anything but the
author's memory.

**It is also structurally novel in a way worth flagging.** Its `data` is *derived*,
not authored. The YAML declares a scope and a policy; the server computes the
body by walking every parsed document in scope. That is the first component in the
catalog whose content is not in the file, which sounds like §4's pointer debate
but is not — nothing about the learner's experience depends on it, and it is
reproducible from the documents at any event index, so `state_at()` and `fork()`
both behave. It is a *view over the corpus*, which is a category the design has
not needed until now.

````markdown
```component:alignment_map
id: module-03-alignment
title: "Module 3 — Objective Coverage"
audience: instructor
scope: modules/03-*.md
objectives_from: course.md            # where the canonical objective list lives
require:
  - objective: "Classify an incident by severity using the org's matrix"
    evidence_min: 2
    depth_min: application            # recall | application | analysis | creation
  - objective: "Draft a stakeholder comms update within 15 minutes of declaration"
    evidence_min: 1
    depth_min: creation
  - objective: "Run the first five minutes of a SEV-2 as Incident Commander"
    evidence_min: 1
    depth_min: application
report:
  - coverage                          # objective -> components tagged to it
  - orphans                           # components with no objective:
  - depth_gaps                        # objectives met only below depth_min
  - unassessed                        # objectives with zero evidence
notes: |
  The comms objective is the one this module keeps failing. It is easy to write
  four MCQs about severity and none about writing the update, because severity
  has crisp right answers and comms does not. If `depth_gaps` flags this
  objective at `recall`, the fix is a `rubric` plus an `open_response`, not
  another MCQ.
```
````

**`secret_fields`:** none, and that is the wrong question for this type. The whole
component is `audience: instructor` (see [course-deliverables.md §2.1](./course-deliverables.md),
which argues audience is an enum, not a boolean). The learner projection should
omit the block **entirely** rather than emptying it — a learner who sees an empty
"Objective Coverage" panel has learned that one exists. This is the first
component that needs *block-level suppression* rather than *field-level
withholding*, and the projection code should grow that capability here.

**Spectrum position.** L3 in format. Content is server-computed, which resembles
L5, but without L5's irreproducibility: the report is a pure function of the
documents at a given event index.

**Why it ranks first.** It is the cheapest item on this list to implement — a walk
over an AST the parser already produces — and it is the only one that improves
courses the author has *already written*.

### 2.2 `short_answer` — recall without cues

**Purpose.** A free-text or numeric response graded server-side against an
accept/reject spec.

**The job nothing else does.** `mcq` tests recognition. `cloze` tests recall, but
only inside a sentence the author wrote, which supplies most of the retrieval cue
for free. Neither asks the learner to **produce** a term, a number, or a short
phrase from nothing. The recognition/recall distinction is the oldest one in
assessment, and the catalog currently has no clean instance of the second half of
it. Every surveyed system has this and treats it as foundational: QTI's
`text-entry-interaction` and `extended-text-interaction`, Moodle's Short Answer /
Numerical / Calculated, Anki's `{{type:}}` template
([Anki manual](https://docs.ankiweb.net/editing.html)).

It also unlocks something structural: it is the **first type whose grading key is
genuinely useful to withhold**. §2.7 of the design doc correctly notes that
cryptographic commitment is useless for MCQ because four options is four hashes.
For a free-text answer over an open space it is not useless — though I still
would not build it, because the server-side projection (§4.3 L3) already solves
the problem and does so for every type at once.

````markdown
```component:short_answer
id: comms-cadence-recall
prompt: |
  A SEV-1 has just been declared. How often must the Comms Lead publish a
  stakeholder update? Answer with a number and a unit.
mode: text                    # text | numeric
normalize: [trim, lowercase, collapse_whitespace]
accept:
  - pattern: "^15 ?(min|mins|minutes)$"
    kind: regex
  - pattern: "every 15 minutes"
    kind: contains
reject:
  - pattern: "^30 ?(min|mins|minutes)$"
    kind: regex
    feedback: |
      Thirty minutes is the SEV-2 cadence. The distinction is the point: SEV-1
      cadence is set so that a stakeholder who joins late has never been more
      than fifteen minutes behind.
  - pattern: "hour"
    kind: contains
    feedback: |
      Hourly is the cadence for a stable, long-running SEV-2 after the IC has
      explicitly downgraded the comms tempo -- and the IC has to say so.
attempts: 2
case_sensitive: false
rationale: |
  Cadence is a promise, not a target. The reason it is written down is that
  under load the IC will not choose it well, and stakeholders who cannot
  predict the next update start asking for it out of band.
objective: "Classify an incident by severity using the org's matrix"
```
````

A numeric variant carries `mode: numeric` with `accept: [{value: 15, tolerance: 0}]`
and an optional `unit:`. Do **not** grow this into an expression grader — see
§4.2.

**`secret_fields`:** `accept`, `reject[].pattern`, `rationale`. Note that
`reject[].feedback` is *not* secret in the useful sense: it is only returned when
that pattern matched, so the grading endpoint returns it naturally. The patterns
themselves must be withheld, because a regex is a nearly-complete answer key.

**Spectrum position.** L3, and it is the type that makes L3 pay for itself. With
answers stripped, the client genuinely cannot grade this — unlike MCQ, where a
determined client could brute-force four options against the endpoint.

**The honest analysis.** Short-answer grading is where every assessment system
accumulates its worst tech debt. Moodle's Short Answer type is a list of wildcard
patterns with per-pattern grades, and in practice authors maintain it forever as
learners find new spellings. The mitigation is not a better matcher; it is
*telling the author to only use this type where the answer space is genuinely
small*. That belongs in the prompt guidance of §3.7, phrased as: if you cannot
enumerate the acceptable answers in three patterns, you wanted `open_response`.

### 2.3 `categorize` — sort into bins

**Purpose.** Assign each of N items to one of M categories, where the mapping is
many-to-one and the bins are unequal.

**The job nothing else does.** `matching` is a bijection between two equal-sized
sets — it is `associate` in QTI terms. `ordering` is a single total sequence.
Neither expresses **classification**, which is many items into few bins with no
constraint on bin size, and classification is the single most common cognitive
task in operational training. Triage *is* classification. This is Rise's Sorting
Activity block and H5P's Drag and Drop; QTI expresses it as
`match-interaction` with `matchMax` unbounded on the target side, which is the
tell that it is a distinct interaction wearing the same element name.

The difference matters pedagogically, not just structurally: in `matching`, having
placed four of five pairs tells you the fifth for free, so the last item is not
assessed. In `categorize` there is no such elimination, which is why it is the
better instrument for the same content.

````markdown
```component:categorize
id: severity-triage-drill
prompt: |
  Each row below is a real page from the last quarter, stripped of its
  eventual outcome. Sort them by the severity the IC should have declared at
  the moment of the page -- not by what it turned out to be.
categories:
  - id: sev1
    label: "SEV-1"
  - id: sev2
    label: "SEV-2"
  - id: sev3
    label: "SEV-3"
  - id: not-incident
    label: "Not an incident"
items:
  - text: "Checkout API 500s at 4%, retries succeed, no data loss"
    category: sev2
    feedback: "Degradation with a working customer-side workaround."
  - text: "Nightly export job failed; no customer-visible surface"
    category: sev3
    feedback: "Real, but business hours. Escalating this is how SEV-3 stops meaning anything."
  - text: "Two rows in the audit log confirmed unrecoverable after a bad migration"
    category: sev1
    feedback: "Confirmed data loss is SEV-1 regardless of blast radius. Two rows and two million rows are the same call."
  - text: "A staging environment is completely down"
    category: not-incident
    feedback: "No customer surface and no production dependency. File a ticket."
  - text: "Login is unavailable for one enterprise tenant, no workaround"
    category: sev1
    feedback: "Single-tenant, but total loss with no workaround. The SEV-2 rule requires a workaround to exist -- this is the case people get wrong most often."
  - text: "p99 latency up 40% on search, still within SLO"
    category: not-incident
    feedback: "Inside SLO is by definition the budget being spent as designed. Watch it; do not declare it."
allow_partial_credit: true
shuffle: true
rationale: |
  Three of these six are deliberately near the boundary. Getting them right
  from a rule is the skill; getting them right from intuition is a coincidence
  that stops working at 3am.
objective: "Classify an incident by severity using the org's matrix"
```
````

**`secret_fields`:** `items[].category`, `items[].feedback`, `rationale`.

**Spectrum position.** L3, with the useful property that `allow_partial_credit`
makes per-item scoring a server concern rather than a renderer concern.

**Accessibility, non-negotiably.** Drag-and-drop must not be the only affordance
(§3.9, WCAG 2.1.1). The right primitive is a per-item `<select>` of category
labels, with drag as a progressive enhancement layered on top — which is also
the simpler thing to build. Rise's own accessibility documentation flags sorting
blocks as one of the components needing care here
([Rise 360 accessible components](https://www.articulatesupport.com/article/Rise-360-Choosing-Accessible-Components-to-Create-Online-Learning)).
**UNVERIFIED** in specifics; the page was not fetched directly.

### 2.4 `mark_the_text` — find it in the artifact

**Purpose.** The learner selects spans within a passage the author supplies.

**The job nothing else does.** Every assessment type in the catalog presents an
*abstracted* stimulus — a prompt the author wrote about the material. This one
presents the material and asks the learner to locate something in it. That is a
different skill and a strictly harder one: recognizing a blameful sentence in a
postmortem you are reading is not the same as answering "what makes a postmortem
blameful." H5P calls it Mark the Words, QTI calls it `hot-text-interaction`, and
it has no analogue anywhere in §3.4 — `diagram` hotspots are the closest, but
those are author-placed annotations on a mermaid graph, not learner selections in
prose.

For an incident-response course this is the highest-fidelity text-only item type
available, because the authentic performance really is *reading an artifact and
noticing what is wrong with it*.

````markdown
```component:mark_the_text
id: blameful-postmortem-marking
prompt: |
  Below is an excerpt from a submitted postmortem. Select every sentence that
  violates the blameless standard.
mode: sentence                  # sentence | word | span
text: |
  At 02:14 the checkout error-rate alert fired. Priya had pushed a config
  change at 01:58 without running the staged rollout, which caused the
  outage. The on-call engineer investigated for eleven minutes before
  declaring. Rollback completed at 02:22 with no effect, because the actual
  cause was an upstream provider timeout. The team should be more careful
  with config pushes going forward. Error rate returned to baseline at 02:41.
targets:
  - match: "Priya had pushed a config change at 01:58 without running the staged rollout, which caused the outage."
    feedback: |
      Two violations in one sentence: it names an individual, and it asserts a
      single cause that the next sentence contradicts. Rewrite as "a config
      change was pushed without a staged rollout" and move the causal claim to
      the contributing-factors section where it can be qualified.
  - match: "The team should be more careful with config pushes going forward."
    feedback: |
      "Be more careful" is the canonical non-action-item. It has no owner, no
      date, and no way to tell whether it worked -- and it relocates the fix
      into people's attention rather than into the system.
distractors:
  - match: "The on-call engineer investigated for eleven minutes before declaring."
    feedback: |
      This one is fine, and it is the trap. It is an unflattering fact stated
      without judgment, which is exactly what a timeline is for. Blameless does
      not mean omitting what people did.
min_selections: 2
max_selections: 4
rationale: |
  The discriminating skill is not spotting the word "Priya." It is noticing
  that the aspirational action item is also a blame statement -- it locates
  the defect in the team's diligence rather than in the deploy tooling.
objective: "Write a blameless postmortem"
```
````

**`secret_fields`:** `targets`, `distractors`, `rationale`. `text` is emphatically
*not* secret — the learner needs it.

**Spectrum position.** L3. Note the projection is slightly subtler than for other
types: stripping `targets` must not disturb the offsets or normalization of
`text`, so the parser should resolve `match:` strings to character spans at parse
time and withhold the *spans*, not re-match on the client.

**One honest constraint.** `mode: span` (arbitrary character ranges) is harder to
author correctly and harder to grade forgivingly than `mode: sentence`. Ship
`sentence` and `word` first; `span` can wait for a demand that may never arrive.

### 2.5 `annotated_artifact` — the worked example

**Purpose.** Present a real artifact — a log excerpt, a diff, a status page post,
a Slack transcript — with expert annotations revealed progressively.

**The job nothing else does.** The catalog is overwhelmingly weighted toward
*eliciting* learner responses. It has almost nothing for the expository half of
instruction, and specifically nothing for the **worked example**, which is among
the better-evidenced techniques in instructional design: novices learn a
procedure faster from studying expert solutions than from attempting problems,
and the advantage inverts as expertise grows (the expertise-reversal effect).
**UNVERIFIED** — I am asserting the worked-example and expertise-reversal
literature from background knowledge; I did not fetch a primary source for it in
this pass, and the claim should be checked before it is used to justify build
priority.

`diagram` with `hotspots` is the nearest existing type and covers exactly one
case: annotations on a mermaid graph. This generalizes it to *any* textual
artifact and adds the thing that makes worked examples work — **fading**, where
successive instances of the same artifact type reveal fewer annotations until the
learner is doing it unaided.

````markdown
```component:annotated_artifact
id: good-status-update-worked
title: "Worked Example: A SEV-2 Status Page Update"
kind: text                      # text | code | diff | transcript
language: markdown              # syntax hint when kind: code | diff
reveal: progressive             # all | progressive | on_request
artifact: |
  **Investigating — 02:24 UTC.** Some customers are seeing errors at checkout.
  Retrying the purchase usually succeeds. We have identified a likely cause and
  are testing a fix. Next update by 02:54 UTC.
annotations:
  - anchor: "Some customers"
    note: |
      Vague on purpose, and correctly so. At 02:24 the IC does not know it is
      4%, and a number published now is a number that has to be corrected
      later. "Some" is honest; "a small number" is a claim.
  - anchor: "Retrying the purchase usually succeeds"
    note: |
      This is the whole update. It is the only sentence that changes what a
      reader does in the next ten minutes. Put the workaround above the
      diagnosis, always.
  - anchor: "We have identified a likely cause"
    note: |
      "Likely" is doing real work. It commits to nothing and still tells the
      reader that someone is on it. Compare "we have identified the cause,"
      which the 02:31 finding would have made false.
  - anchor: "Next update by 02:54 UTC"
    note: |
      Absolute time, not "in 30 minutes," because readers arrive at different
      times. And "by," not "at" -- you are promising a ceiling you can beat.
fade_from: good-status-update-worked
counterexample: bad-status-update-worked
objective: "Draft a stakeholder comms update within 15 minutes of declaration"
```
````

`fade_from:` is the cross-reference mechanism from §3.10's no-nesting mitigation
applied to instructional sequencing: a later `annotated_artifact` naming an
earlier one as its `fade_from` renders with annotations collapsed by default and
lets the renderer report which annotations the learner asked to see. That is a
cheap, genuinely diagnostic signal — *which* explanations a learner still needs
is more informative than whether they got an MCQ right.

**`secret_fields`:** none. This type is expository; withholding the annotations
would defeat it. `reveal: progressive` is a UI affordance and §2.7 of the design
doc is right that we must never call that a boundary.

**Spectrum position.** L1 — inline-full, no server behavior beyond parsing.
Cheap, which combined with its rank makes it the best effort-to-value ratio on
this list after `alignment_map`.

### 2.6 `survey` — an instrument, not a question

**Purpose.** A multi-item scaled instrument with a defined scale, optional
pre/post pairing, and aggregation.

**The job nothing else does.** `poll` (§3.4.13) is one question with options and
`show_results`. `reflection` (§3.4.14) is one open prompt. Neither is an
*instrument*: a fixed item set on a shared scale, administered twice, whose
signal is the shift. ADDIE's Evaluation phase and Kirkpatrick Level 1 both want
exactly this artifact, and [course-deliverables.md](./course-deliverables.md)
lists "Evaluation plan & instruments" as a shipped deliverable with no component
behind it. The design doc's §3.8 table maps ADDIE-Evaluation to "`poll`,
`reflection`, and the `LearnerProgress` event log," which is the row where that
table is weakest.

H5P's Questionnaire and Summary types are the prior art, and Moodle keeps this
out of the question-type system entirely (it is a separate Feedback activity) —
which is itself a signal that it is a distinct thing rather than a quiz variant.

````markdown
```component:survey
id: m3-self-efficacy
title: "Incident Command Self-Efficacy"
instrument: likert-5
scale:
  - {value: 1, label: "Not at all confident"}
  - {value: 2, label: "Slightly confident"}
  - {value: 3, label: "Moderately confident"}
  - {value: 4, label: "Very confident"}
  - {value: 5, label: "Completely confident"}
pair_with: m3-self-efficacy-pre    # same instrument administered before the module
anonymous: true
items:
  - id: declare
    text: "I could decide whether to declare an incident within three minutes of a page."
  - id: severity
    text: "I could assign a severity I would be willing to defend in the postmortem."
  - id: delegate
    text: "I could assign Comms Lead and Scribe without being asked to."
  - id: comms
    text: "I could write a stakeholder update that a non-engineer would find useful."
  - id: close
    text: "I could decide when an incident is over."
report:
  - per_item_mean
  - shift_from_pair
  - lowest_two
notes: |
  Self-efficacy is not competence, and this instrument does not claim to
  measure competence. It measures whether the learner would take the role --
  which is the thing that actually determines whether the training changes
  anything at 3am. Expect `comms` to be the lowest item and expect the shift
  on `close` to be negative, because the module makes people realise closing
  is a judgment call rather than an event.
```
````

**`secret_fields`:** none for the learner. The *aggregate* is the sensitive
object: with `anonymous: true`, the projection must refuse to return per-learner
responses to any audience, and should suppress aggregates below a small-N
threshold. That is a projection rule the design does not currently have, and it is
the only place in this document where a component needs privacy machinery rather
than answer-hiding machinery.

**Spectrum position.** L2 — everything inline, server records the responses.

### 2.7 `glossary` — vocabulary as a shipped artifact

**Purpose.** A term bank, rendered as a definition list and referenceable from
elsewhere in the course.

**The job nothing else does.** `flashcards` and `srs_deck` are *study aids* —
they are about repetition and scheduling, and their front/back framing forces
every term into a question. A glossary is a **reference**: alphabetized,
scannable, exportable, and linked to from the prose that uses the term.
[course-deliverables.md §2.2](./course-deliverables.md) lists Glossary as a
learner-facing shipped artifact in its own right. It is also the natural source
for a generated `flashcards` deck, which is the argument for authoring it once
here rather than twice.

````markdown
```component:glossary
id: ir-glossary
title: "Incident Response Glossary"
sort: alphabetical              # alphabetical | authored
terms:
  - term: "Blameless"
    definition: |
      A postmortem norm holding that the analysis describes what the system
      made easy to do wrong, never who did it. Not a politeness convention --
      it is the only condition under which people report what they actually
      did.
    see_also: [Postmortem, Contributing factor]
  - term: "Comms cadence"
    definition: |
      The maximum interval between stakeholder updates for a given severity.
      Fifteen minutes at SEV-1, thirty at SEV-2, none at SEV-3. A ceiling, not
      a target.
    see_also: [Comms Lead]
  - term: "Contributing factor"
    definition: |
      One of several conditions that combined to produce an incident. Deliberately
      plural: the phrase "root cause" is avoided because it implies the search
      terminates at one.
  - term: "Declaration"
    definition: |
      The moment an engineer states in the incident channel that an incident
      exists, at a stated severity. Cheap, reversible, and the event that
      starts every clock in the process.
  - term: "Workaround"
    definition: |
      Something the *customer* can do to complete their task despite the fault.
      An internal failover is not a workaround. This distinction is the sole
      difference between SEV-1 and SEV-2 in most real calls.
    see_also: [SEV-1, SEV-2]
generate_deck: ir-glossary-deck    # optional: emit a flashcards component id
```
````

**`secret_fields`:** none.

**Spectrum position.** L1.

**Why it ranks seventh rather than higher.** It is nearly free and clearly
correct, but it does not change what a course can *teach* — it changes what a
course can *ship*. That is real value and lower leverage than the six above it.

### 2.8 `open_response` — extended writing against a rubric

**Purpose.** A long-form written response, graded against a referenced `rubric`
by a human, the learner (self-assessment), or a model — never by string matching.

**The job nothing else does.** `reflection` is private and ungraded by design.
`code_exercise` is graded but only for code. `rubric` (§3.4.8) declares criteria
and has `self_assess: true` but no task submission attached to it. So the single
most common summative assessment in professional training — *write the thing, and
be assessed on it* — has no component. QTI has `extended-text-interaction`,
Moodle has Essay, H5P has Essay; all three punt on automatic grading, and so
should we.

````markdown
```component:open_response
id: sev2-comms-draft
prompt: |
  It is 02:19. You have just declared a SEV-2 for checkout errors affecting
  roughly 4% of purchase attempts. Retries succeed. You believe but have not
  confirmed that a config push at 01:58 is responsible.

  Write the first status page update. You have three minutes.
rubric: postmortem-rubric          # id reference; components never nest (§3.10)
min_words: 60
max_words: 200
time_limit: 3m                     # advisory; rendered as a visible timer, not enforced
grading: rubric_manual             # rubric_manual | rubric_self | rubric_model
model_grading:
  enabled: false
  disclose: true                   # if ever enabled, the learner must be told
exemplar: |
  **Investigating — 02:19 UTC.** Some customers are seeing errors when
  completing a purchase. Retrying usually succeeds. We are investigating a
  recent configuration change as a possible cause. Next update by 02:49 UTC.
exemplar_notes: |
  Note what the exemplar does not do: it does not give a percentage, does not
  name the config change, and does not promise a fix time. Under time pressure
  the failure mode is over-committing, not under-communicating.
objective: "Draft a stakeholder comms update within 15 minutes of declaration"
```
````

**`secret_fields`:** `exemplar`, `exemplar_notes` — withheld until the learner has
submitted, which is a *sequencing* rule rather than an audience rule and is the
first time the projection needs to depend on `LearnerProgress` state. That is a
real complication and the reason this sits in v2 rather than v1.5.

**Spectrum position.** L3, with the uncomfortable footnote that **its grading
cannot be server-side in the sense the rest of the catalog means**. There is no
key. The three honest options are human grading (needs an instructor surface that
does not exist), self-assessment against the rubric (works today, weak signal), or
model grading (works today, and introduces a scoring authority whose reliability
nobody has measured). `grading: rubric_self` is the only one shippable now, and
the schema should carry the other two so that enabling them is configuration
rather than redesign. If model grading is ever switched on, `disclose: true`
should not be optional.

### 2.9 `pool` / `exam` — the level-5 pair, made concrete

**Purpose.** Declare a server-owned assessment form: an item pool, a selection
policy, and gating.

**Status: not new, and I am flagging that explicitly.** §4.7 of the design doc
already names `exam`, `pool`, and `gate` as the legitimate level-5 types. What is
missing is a concrete shape, and the shape matters because it is the one place
where the file genuinely stops determining the experience. Writing it down is how
the "bright line" §4.7 asks for actually stays bright.

````markdown
```component:pool
id: sev-classification-pool
title: "Severity Classification Item Pool"
audience: instructor
draw_from:
  - modules/03-severity.md
  - modules/04-boundaries.md
filter:
  objective: "Classify an incident by severity using the org's matrix"
  types: [mcq, short_answer, categorize]
  min_items: 12
```
````

````markdown
```component:exam
id: ir-certification-exam
title: "Incident Response Certification"
form:
  - pool: sev-classification-pool
    n: 5
  - pool: comms-pool
    n: 3
  - component: postmortem-rubric-task     # a fixed, non-drawn item
sequence: linear_no_back
time_limit: 30m
attempts: 2
pass_threshold: 0.8
feedback: on_completion                   # never | on_completion | immediate
gate:
  blocks: modules/06-oncall-shadow.md
  requires: pass
```
````

**`secret_fields`:** effectively the entire body of `pool`, plus `exam.form` — a
learner who can read which pools an exam draws from and how many items each
contributes has learned a great deal about what to study. This is the first
component whose *structure* rather than its answers is the secret, and it is the
cleanest argument in the whole design for the **publication boundary** that
§4.2 puts ahead of the item bank on the roadmap. Without that boundary, `exam` is
theatre.

**Spectrum position.** L5, by construction and by intent.

### 2.10 `explorer` — a parameter you can move

**Purpose.** A small set of named inputs, a whitelisted arithmetic expression, and
a readout — so the learner can develop intuition for how a quantity responds.

**The job nothing else does.** Nothing in the catalog is *manipulable*. Every
component either asks a question or displays something fixed. The
Jupyter/Observable idiom — a slider bound to a computed cell — is the
best-established interactive-notebook pattern there is, and its pedagogical job
(intuition for a relationship, as distinct from knowledge of a fact or execution
of a procedure) is genuinely unserved.

For this course the obvious instance is an error-budget calculator: move the
error rate and the duration, watch how much of the month's budget the incident
consumed, and discover that a 4% error rate for 27 minutes is nearly free while
0.5% sustained for a week is not.

````markdown
```component:explorer
id: error-budget-burn
title: "How much budget did that incident cost?"
inputs:
  - id: slo
    label: "Monthly availability SLO"
    kind: choice
    options: [0.99, 0.995, 0.999, 0.9999]
    default: 0.999
  - id: error_rate
    label: "Fraction of requests failing"
    kind: range
    min: 0.001
    max: 0.25
    step: 0.001
    default: 0.04
  - id: minutes
    label: "Duration (minutes)"
    kind: range
    min: 1
    max: 480
    step: 1
    default: 27
outputs:
  - id: budget_minutes
    label: "Monthly error budget (minutes)"
    expr: "(1 - slo) * 43200"
    format: "{:.1f} min"
  - id: burned
    label: "Budget consumed by this incident"
    expr: "error_rate * minutes"
    format: "{:.2f} min"
  - id: fraction
    label: "Share of the month's budget"
    expr: "(error_rate * minutes) / ((1 - slo) * 43200)"
    format: "{:.1%}"
    warn_above: 0.25
prompts:
  - "Set the SLO to three nines and the duration to 27 minutes. How high does the error rate have to go before this incident costs a quarter of the month?"
  - "Now hold the error rate at 0.5% and find the duration that costs the same. Which of those two incidents would page more people?"
takeaway: |
  Severity tracks how loud an incident is; the error budget tracks how
  expensive it is. They disagree constantly, and the disagreement is where
  "we had a good quarter with three SEV-2s" comes from.
```
````

**`secret_fields`:** none.

**Spectrum position.** L2 at most — nothing to grade, though recording which
parameter regions a learner explored would be a genuinely interesting
`ComponentInteracted` event.

**The cost, stated plainly.** `expr` is author-authored code, and §3.1 constraint
3 says we do not execute model-authored code. The reconciliation is that this must
be a **whitelisted arithmetic grammar** — numeric literals, the declared input
identifiers, `+ - * / %`, parentheses, and a fixed function list (`min`, `max`,
`abs`, `round`, `log`, `sqrt`) — parsed to an AST and evaluated by an
interpreter that has no property access, no calls to anything not on the list, and
no loops. That is a genuinely small piece of code and it is a genuinely real piece
of attack surface, and it is why this sits at rank ten rather than rank four. If
it is built, the evaluator must be server-side and pure, so `explorer` outputs are
computed by the same code path that would compute them for a PDF export.

### 2.11 `hotspot` — everything above, on an image

**Purpose.** Image-anchored selection, labeling, and annotation.

**The job nothing else does.** It is the whole graphical half of QTI —
`hotspot`, `graphic-order`, `graphic-associate`, `graphic-gap-match`,
`select-point`, `position-object` — and roughly a dozen H5P types, and Rise's
Labeled Graphic. For a great many subjects (anatomy, geography, UI walkthroughs,
architecture diagrams, dashboard reading) it is not a nice-to-have; it is the
primary modality.

**And it is blocked, completely, on something the repo does not have.** Files in
this system are `{content: str}` (`domain/session.py:70`). There is no binary
asset store, no upload path, no content-addressed blob table, and no media route.
A `hotspot` component would have to reference an image by URL — which makes the
document non-self-contained, breaks `fork()` and `state_at()` in exactly the way
§4.4 objects to for item pointers, and introduces an external fetch into a
renderer that currently makes none.

So the recommendation is: **do not build this until asset storage is a decided
feature with its own design**, and when that happens, treat this as one component
family designed at once rather than as six types dribbled in. I include it here
rather than in the cut list because unlike the cuts, it is genuinely valuable and
genuinely blocked, and those are different states that deserve different labels.

I am deliberately not giving a full YAML example, because writing one would imply
a `src:` field whose semantics are the unresolved question.

---

## 3. Refinements to already-proposed types

Three changes to existing types that do more good than most of the new types
above, and are labeled as refinements rather than proposals as requested.

### 3.1 A `confidence:` field on any graded component, not a `confidence` type

Confidence-weighted assessment — asking "how sure are you?" alongside the answer
— produces the calibration signal that separates *knows it* from *guessed it*,
and misplaced confidence is the diagnostically valuable case: a learner who is
certain and wrong will not self-correct. It is tempting to make this a component
type. It should not be. It is one optional boolean on `mcq`, `short_answer`,
`categorize`, `matching`, and `ordering`:

```yaml
confidence: true        # renders a 3-point sure/unsure scale alongside the response
```

with a corresponding `confidence` value on the `ComponentAnswered` event. A
separate type would force authors to pair every item with a companion widget,
which is exactly the two-things-to-keep-in-sync failure mode §3.2 rejects sidecar
files for.

### 3.2 `matching` should gain `left_to_many: true` rather than spawning a variant

Once `categorize` exists (§2.3), the temptation is to add `matching` variants for
one-to-many and many-to-many. Resist it: `matching` stays a bijection,
`categorize` covers many-to-one, and the many-to-many case is rare enough in
practice that it should be authored as `categorize` with `multi: true` if it ever
comes up. Three types is one too many; two is correct.

### 3.3 `scenario` needs an `assess:` hook, and it is the answer to no-nesting

§3.10 identifies the inability to put an `mcq` inside a `scenario` node as the
principal cost of the fenced-block choice, and proposes cross-references as the
mitigation without specifying them. Specify them:

```yaml
nodes:
  - id: alert
    text: |
      ...
    assess: sev-classification-1        # component id elsewhere in the document
    on_correct: declared
    on_incorrect: delayed
```

The renderer inlines the referenced component at that node and routes on its
grading result. This is strictly better than nesting: the item is independently
addressable for `alignment_map`, independently attemptable, independently
exportable to QTI, and has its own `LearnerProgress` history. The no-nesting
constraint turns out to have been the right call for a reason the original
document does not quite claim — **references produce a flat, queryable item space,
and containment produces a tree that only the renderer understands.**

---

## 4. What I am cutting, and why

A shorter catalog that gets implemented beats a longer one that does not. These
are the candidates the survey surfaced that I am explicitly refusing, grouped by
the reason.

### 4.1 Layout blocks — structurally impossible and pedagogically empty

**Cut: `accordion`, `tabs`, `columns`, `card_grid`, `process` (Rise), `button`,
`page`, `interactive_book`.**

These are roughly a third of both the H5P and Rise catalogs, and every one of them
is a container: its content is other content. §3.2 forbids nesting, so
implementing them would require either the `:::` escape hatch §3.10 holds in
reserve or a reference-list-of-ids indirection that produces worse markdown than
just writing headings. And the pedagogical claim is thin — an accordion is a
heading with the text hidden, which is a *reading-comfort* intervention, not a
learning one. Markdown already has headings, lists, and tables, and our renderer
already renders all three.

This is the single highest-value cut in the document, because it is where a naive
"port the H5P catalog" effort would spend most of its time.

### 4.2 Recognition games — high build cost, low yield, frequently inaccessible

**Cut: `crossword`, `word_search`, `memory_game`, `hangman`, `image_pairing`,
`arithmetic_quiz`, `personality_quiz`.**

H5P ships all of these. Crossword and Find the Words are grid-layout problems with
genuinely difficult keyboard-navigation and screen-reader stories; Memory Game
tests short-term visual recall of card positions, which is not the recall anyone
is trying to teach; Personality Quiz has no correct answer and is entertainment.
`jeopardy` (§3.4.6) already covers the "make review feel like a game" job, and one
of those is enough.

`arithmetic_quiz` is a different kind of cut: it is a *generator*, not a content
type. Generated item variants belong to the `pool` concern (§2.9), not to a
bespoke type — Moodle's Calculated question type is the same insight arrived at
from the other direction ([Moodle question types](https://docs.moodle.org/500/en/Question_types)).

### 4.3 Media-dependent types — blocked, not rejected, but out of scope

**Cut for now: `interactive_video`, `audio_recorder`, `dictation`,
`speak_the_words`, `image_occlusion`, `image_juxtaposition`, `agamotto`,
`virtual_tour`, `ar_scavenger`, `collage`, `image_slider`.**

Same blocker as `hotspot` (§2.11) plus, for the audio types, a media-capture
permission story, a storage-of-learner-voice privacy story, and an ASR
dependency. The 360/AR types are cut permanently rather than deferred: they need a
3D asset pipeline this project will never plausibly have, and their instructional
yield outside a small number of physical-space domains is poor.

Note the pattern — **eleven of H5P's fifty-four types are unavailable to us for
one shared reason: `files: dict[str, dict[str, Any]]` holds strings.** That is
worth stating as a single architectural fact rather than eleven separate
disappointments.

### 4.4 Types subsumed by something already proposed

**Cut: `true_false`** — an `mcq` with two options; a separate type buys a slightly
tidier render and costs a registry entry, a schema, a renderer, and an export
mapping. **Cut: `essay`** — that is `open_response` (§2.8). **Cut: `numeric` /
`estimate`** — that is `short_answer` with `mode: numeric`. **Cut: `slider`
(QTI)** — a slider *as a response mechanism* is a numeric entry with a worse
keyboard story and coarser resolution; `explorer` (§2.10) uses sliders as inputs,
which is the use they are actually good for. **Cut: `chart`** — a bar or pie chart
of author-supplied numbers is a `diagram`, and mermaid renders both.

### 4.5 Types whose grading cannot be honest

**Cut: `math_expression`** — grading "is `2(x+1)` equivalent to `2x+2`?" requires a
computer algebra system. Moodle's answer is STACK, which embeds Maxima; that is a
large dependency for a project whose current client has zero third-party JS and
whose subject matter is not mathematics. **UNVERIFIED** in detail — I did not fetch
the STACK documentation.

**Cut: `peer_review`** — genuinely valuable, genuinely blocked, and see §5.5.

### 4.6 The near-miss I keep and the near-miss I cut

Two candidates sat on the line, and it is worth showing the reasoning rather than
just the verdict.

**Kept, barely: `survey` (§2.6).** The argument against is that it is `poll` in a
loop. The argument for, which wins, is that the *instrument* — fixed items, shared
scale, pre/post pairing, aggregate-only projection — is the unit of analysis, and
five `poll`s cannot be paired, aggregated, or shifted. The privacy rule in §2.6 is
the tell: it is a property of the instrument, not of any item.

**Cut: `decision_table` / `matrix_exercise`.** Filling a two-axis grid (severity
by impact-and-workaround) is a real and distinct task — it is `categorize` with
two independent classification axes rather than one. But the cases where the grid
is genuinely two-dimensional are rare, the accessible rendering of an editable
grid is fiddly, and every instance I could construct decomposed into either a
`categorize` or a small set of `mcq`s without loss. If a course appears where the
matrix *is* the content, revisit. Not before.

---

## 5. Cross-cutting gaps the catalog does not see

Six observations that are not about any individual widget.

### 5.1 The asset problem is one fact, not eleven

Restating §4.3 because it deserves to be a decision rather than a background
constraint: `files` holds strings, so **the entire image-anchored half of the
assessment universe is unavailable**, and that half is not a fringe. Whoever
scopes asset storage should know that it unblocks `hotspot`, `image_occlusion`,
`interactive_video`, and diagram formats richer than mermaid, all at once — which
makes it a larger single lever than any three widgets on my list.

### 5.2 There are no inline components, and `cloze` is the only workaround

Every component in the catalog is block-level, because a fenced code block is
block-level. QTI's taxonomy has three inline interactions —
`inline-choice-interaction`, `text-entry-interaction`, and `hot-text-interaction`
— specifically so an item can embed a response *inside a sentence*. We can
approximate the first two with `cloze` and the third with `mark_the_text` (§2.4),
both of which move the interaction into a dedicated block. That is a real
expressive loss and I do not think it is worth fixing: the fix is inline
directives (`:name[content]{attrs}`), which reintroduces the second grammar §3.2
rejected. Name it as a known, accepted limitation so nobody rediscovers it as a
bug.

### 5.3 Learner state is keyed per-occurrence, so nothing spans documents

§4.5 keys `component_ref` on `(session_id | publication_id, path, component_id)`,
deliberately, so that the same id in two lessons is two occurrences. Correct for
grading and psychometrics. **But it means there is no home for state that is
inherently course-scoped**, and there are at least four such things:

- A spaced-repetition **due queue** spanning every `srs_deck` in the course. A
  learner does not want to visit six lesson files to find today's cards.
- **Mastery per objective**, which is the aggregate `alignment_map` (§2.1) would
  want to render for a learner rather than an author.
- **Streaks and session pacing** — the Duolingo mechanic, whatever one thinks of
  it, is course-scoped by construction.
- **Gate satisfaction** (§2.9) — "has this learner passed the thing that unblocks
  module 6" is a question about the course, not about a file.

The design doc gestures at this ("read models — mastery per objective, SR
due-queue, gradebook — are folded from it") and the folding is indeed the answer.
The gap is that no *component* surfaces those read models. `alignment_map` in a
learner-facing variant, and a `due_queue` widget, would be the obvious two. I have
not proposed `due_queue` as a numbered type because it is a *page*, not a widget —
it belongs in the web UI's navigation surface (see
[web-ui-surface.md](./web-ui-surface.md) §4), not in a lesson document. But
something must own it.

### 5.4 One component now needs block-level suppression, not field-level withholding

§3.3's projection model is `secret_fields` — a list of field paths dropped from
the learner view. `alignment_map` (§2.1) and `pool` (§2.9) both need the whole
block gone, and an emptied shell is an information leak of its own. The projection
needs `audience: [learner | instructor | manager | admin]` at block level, per
[course-deliverables.md §2.1](./course-deliverables.md)'s argument that audience is
an enum. This is a small change made much cheaper by making it before three types
depend on the field-level model.

### 5.5 There is no second person anywhere in this design

No peer review, no discussion, no group activity, no facilitator-in-the-room
component, no cohort. The xAPI verbs `commented` and `shared` have no
counterpart in §3.6's event list. This is currently correct — there is no user
system at all (see [exposure-and-redaction.md](./exposure-and-redaction.md) Part 1,
which is unambiguous that the web app has no notion of who anyone is) — but it
should be recorded as a *consequence of missing identity* rather than a
pedagogical position. Cohort-based and blended modalities, both of which
[course-deliverables.md §1](./course-deliverables.md) treats as first-class, are
substantially about what learners do to each other's work. When auth lands, this
is the next catalog conversation, and `peer_review` is its first item.

### 5.6 The author-facing widget class is real and currently has one member

The task asked whether there is a widget class serving the author rather than the
learner. There is, and `alignment_map` is its first and most valuable member, but
it is not the only one worth naming:

| Candidate | What it does | Verdict |
|---|---|---|
| `alignment_map` | Objective coverage, orphans, depth gaps | **Build it** (§2.1) |
| `item_analysis` | Difficulty and discrimination per item, distractor selection rates | **Later, and it is a page not a widget** — needs attempt volume that does not exist yet, and it renders over a whole course |
| `readability` | Reading level, sentence length, jargon density per lesson | **No.** A linter, not a component. Belongs in the write-path validation of §3.7 item 2 |
| `time_estimate` | Estimated seat time from word counts and component types | **Maybe, folded into `alignment_map`** — it is the one number every stakeholder asks for and no design artifact currently produces |
| `change_log` | What changed in this lesson since the last review, computed from the event log | **Interesting, and it is a UI view** — `presenters.py` already has the edit-intent data |
| `facilitator_notes` | Instructor-only prose beside a learner-facing activity | **This is not a new type** — it is `audience: instructor` (§5.4) applied to an ordinary markdown region, which is precisely what [course-deliverables.md §2.1](./course-deliverables.md) recommends |

The pattern in that table is the useful output: **most author-facing needs are
either a linter, a page, or an audience tag — not a widget.** `alignment_map` is
the exception because it must be *anchored to a place in a document* (this module,
these objectives) and authored with intent (`require:`, `depth_min:`), which is
what makes it a component rather than a report.

---

## 6. Phasing, against §3.10

Slotting the eleven proposals and three refinements into the existing phase plan.

**v1 — unchanged.** `flashcards`, `mcq`, `cloze`, `checklist`. Nothing here
belongs in v1; the point of v1 is to prove the authoring loop, and four types is
the right number for that.

**v1.5 — add six, in this order.**

1. `alignment_map`, because it makes v1.5's `objective:` alignment report a thing
   an author can see rather than a query someone might run.
2. `short_answer`, because it is the type that proves the L3 projection is real.
3. `annotated_artifact`, because it is L1, costs almost nothing, and fills the
   expository half of the catalog.
4. `categorize`, alongside §3.10's already-planned `matching` and `ordering` —
   these three share a renderer skeleton and should be built together.
5. `glossary`, essentially free.
6. `survey`, which needs the small-N aggregate rule (§2.6) and so should come last
   in the phase.

Also in v1.5: the `confidence:` field (§3.1), block-level `audience`
suppression (§5.4), and `scenario.assess:` (§3.3) once `scenario` itself lands.

**v2 — add three.** `mark_the_text` (its span-resolution work is real),
`open_response` (needs the submit-then-reveal projection dependency),
`pool`/`exam` (needs the publication boundary first — do not build these before
it, or they are theatre).

**v2+, gated on decisions outside this catalog.** `explorer`, gated on someone
wanting the expression evaluator badly enough to review it. `hotspot` and family,
gated on asset storage. `peer_review` and the discussion family, gated on auth.

**Probably never.** Everything in §4.1 and §4.2, plus the 360/AR family, plus
`math_expression`. These are refusals rather than deferrals, and the value of
writing them down is that the next person to read the H5P catalog does not have to
re-derive the reasoning.

---

## 7. The uncomfortable summary

Three claims I would defend and one I am uneasy about.

**The catalog is already close to complete for text.** Seventeen types cover
recognition, cued recall, association, sequencing, branching, procedure,
scheduling, and reflection. My eleven additions cover exactly three real response
gaps (production, classification, in-artifact marking), one expository gap (worked
examples), one instrument gap (surveys), one reference gap (glossary), and three
things that are really infrastructure wearing a component costume (`alignment_map`,
`pool`/`exam`, `explorer`). That is a healthy ratio and it means **the marginal
value of catalog expansion is falling fast.** The next unit of effort is better
spent on the publication boundary and asset storage than on type sixteen through
twenty-eight.

**The best new component serves the author, not the learner.** `alignment_map` is
ranked first because a course with twelve well-built widgets and no evidence for
two of its objectives is worse than a course with six widgets and full coverage,
and today nothing tells the author which one they have written.

**Half of the prior-art catalogs are layout, and layout is not pedagogy.** The
no-nesting constraint that §3.10 treats as the design's principal cost turns out
to be its most effective filter.

**The claim I am uneasy about:** that `short_answer` is worth its maintenance
cost. Free-text matching decays — every deployment of it accumulates patterns
forever, and the failure mode is a learner who was right being told they were
wrong, which is the worst thing an assessment system can do. I rank it second
because the recognition/recall gap is real and because `cloze` alone is not an
honest substitute. But if I am wrong about one thing on this list, it is that, and
the measurable check is the same one §3.10 proposes for YAML validity: author
twenty short-answer items, have five people answer them, and count how often a
correct answer is rejected. If it is above a few percent, the type wants
`grading: rubric_self` semantics rather than pattern matching, and it drops to v2.

---

## Sources

- [H5P content types and applications](https://h5p.org/content-types-and-applications)
- [Moodle question types](https://docs.moodle.org/500/en/Question_types)
- [1EdTech QTI 3.0 Best Practices and Implementation Guide](https://www.imsglobal.org/spec/qti/v3p0/impl)
- [1EdTech QTI 3.0 Overview](https://www.imsglobal.org/spec/qti/v3p0/oview)
- [ADL xAPI Verbs (adlnet-archive/xAPIVerbs)](https://github.com/adlnet-archive/xAPIVerbs)
- [xAPI Statements 101](https://xapi.com/statements-101/)
- [xAPI Deep Dive: Verbs](https://xapi.com/blog/deep-dive-verb/)
- [adlnet/xAPI-Spec: xAPI-Data.md](https://github.com/adlnet/xAPI-Spec/blob/master/xAPI-Data.md)
- [Anki Manual: Adding and Editing (note types, cloze, image occlusion, type-in)](https://docs.ankiweb.net/editing.html)
- [Anki Manual: Getting Started](https://docs.ankiweb.net/getting-started.html)
- [Articulate Rise 360 product page (block types)](https://www.articulate.com/360/rise/)
- [Rise 360: Using Sorting Activity Blocks](https://www.articulatesupport.com/article/Rise-How-to-Use-Sorting-Activity-Blocks)
- [Rise 360: Choosing Accessible Components](https://www.articulatesupport.com/article/Rise-360-Choosing-Accessible-Components-to-Create-Online-Learning)
- [Brilliant: guided interactive problem solving](https://brilliant.org/help/why-brilliant/)
- Sibling docs: [`markdown-components.md`](./markdown-components.md),
  [`course-deliverables.md`](./course-deliverables.md),
  [`exposure-and-redaction.md`](./exposure-and-redaction.md),
  [`web-ui-surface.md`](./web-ui-surface.md)
