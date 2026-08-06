# The Tyler Model (The "Tyler Rationale")

Ralph W. Tyler, *Basic Principles of Curriculum and Instruction* (University of Chicago Press, 1949). A ~128-page syllabus for Tyler's course Education 360, not a treatise. Its brevity matters: the book states a procedure and declines to fill in the answers, which is both why it survived and why it is so often misread.

---

## 1. Origin and status

The four questions were formulated during the late 1930s in the course of the **Eight-Year Study** (1933–1941), the Progressive Education Association's experiment in which ~30 secondary schools were freed from college-entrance subject requirements in exchange for demonstrating outcomes by other means. Tyler ran its evaluation staff. The rationale is, in its origin, an *evaluation* problem solved backwards: if schools may teach whatever they like, on what basis do we say what they achieved? ([Understanding the Tyler rationale, Prospects](https://www.redalyc.org/pdf/4774/477455340011.pdf))

It is the single most-cited procedural framework in curriculum studies and the direct ancestor of nearly every instructional-design process in use today. It is also the field's most-attacked text. Both facts should be held simultaneously.

---

## 2. The four fundamental questions

Tyler's Introduction poses four questions that "must be answered in developing any curriculum and plan of instruction" ([ASCD](https://www.ascd.org/blogs/curriculum-development-what-would-tyler-do)):

| # | Tyler's question | Chapter | Modern name |
|---|---|---|---|
| 1 | What educational purposes should the school seek to attain? | 1 | Objectives |
| 2 | What educational experiences can be provided that are likely to attain these purposes? | 2 | Selection of learning experiences |
| 3 | How can these educational experiences be effectively organized? | 3 | Organization / scope & sequence |
| 4 | How can we determine whether these purposes are being attained? | 4 | Evaluation |

The cycle is not strictly linear in Tyler's own presentation — Chapter 4 ends by feeding evaluation results back into the restatement of objectives, making the rationale a loop with a designated re-entry point. Most secondary summaries flatten this into a four-box waterfall; that flattening is the source of a large share of the criticism aimed at Tyler.

**Note on question 1's scope.** Tyler is emphatic that the number of objectives must be bounded by available instructional time: "It is essential therefore to select the number of objectives that can actually be attained in a significant degree in the time available" ([ASCD](https://www.ascd.org/blogs/curriculum-development-what-would-tyler-do)). Objective inflation is a Tyler-recognized failure mode, not a later discovery.

---

## 3. The distinctive machinery: three sources, two screens

This is the part of the model that is genuinely Tyler's and the part most often dropped in practice. Steps 2–4 are recognizable in dozens of frameworks; the sources-and-screens funnel is not.

### 3.1 The funnel

```
  SOURCE A: Studies of the learners themselves
  SOURCE B: Studies of contemporary life outside the school
  SOURCE C: Suggestions from subject-matter specialists
              |
              v
      [ large pool of TENTATIVE GENERAL OBJECTIVES ]
              |
              v
  SCREEN 1: The educational and social philosophy of the school
              |
              v
  SCREEN 2: The psychology of learning
              |
              v
      [ small set of PRECISE INSTRUCTIONAL OBJECTIVES ]
```

Tyler's structural claim is that **no single source is sufficient and each is biased in a known direction**, so the three must be run in parallel and pooled before filtering. This is a deliberate answer to the single-source models that preceded him: Bobbitt and Charters derived objectives from activity/job analysis of adult life alone (Source B only); the classical humanist tradition derived them from the disciplines alone (Source C only); the child-study wing of progressivism derived them from learner interest alone (Source A only). Tyler's move is to refuse to arbitrate among the three and instead make the arbitration explicit and downstream, in the screens.

### 3.2 Source A — Studies of the learners

**What it asks:** What is the gap between the learner's present state and an acceptable norm? Tyler frames a need as a *discrepancy* — needs are differences between current condition and desired condition, which means Source A cannot produce objectives without importing a norm from somewhere.

**Sub-categories Tyler enumerates:** health needs; social-familial relationships; socio-civic; consumer; vocational; recreational; religious/existential. Plus *interests*, which he treats separately from needs — interest data tells you where engagement is cheap, need data tells you where it is required.

**Methods:** observation, interviews with learners, interviews with parents, questionnaires, tests, records of existing performance.

**Known bias:** conservatism toward the learner's current situation. Source A alone will never propose something the learner cannot currently imagine wanting.

**Artifact:** `LearnerAnalysisDossier` — entry-state description, prerequisite inventory, gap list, interest map, misconception catalogue.

### 3.3 Source B — Studies of contemporary life outside the school

**What it asks:** What is actually being done, demanded, or failed at in the world the learner is entering?

**Method:** analysis of contemporary life broken into fields (health, family, recreation, vocation, religion, consumption, civic life), each analysed for the activities and competencies it actually requires. This is Bobbitt's activity analysis, retained but demoted from sole source to one of three.

**Tyler's own stated cautions** — he anticipates the objection before Kliebard makes it:
- The is/ought problem: that something is prevalent in contemporary life does not make it desirable. Resolving this is explicitly deferred to Screen 1.
- Transfer is not automatic: training for a specific adult activity does not guarantee the learner performs it in the adult setting.
- Contemporary life is a moving target, so the analysis dates.

**Known bias:** status-quo reproduction; over-weighting the currently employable.

**Artifact:** `ContemporaryDemandAnalysis` — domain decomposition, task/competency inventory per domain, evidence of demand, recency stamp.

### 3.4 Source C — Suggestions from subject specialists

**What it asks:** What can this discipline contribute to the education of the *non-specialist*?

This is the source most often misapplied. Tyler's complaint is that specialists asked "what should be taught?" answer as if training successors — producing a miniature graduate curriculum. The correct question, which he says the Eight-Year Study committees were forced to answer, is: *what can your subject do for a young person who will never specialize in it?* Answering it well tends to yield **modes of inquiry, characteristic concepts, and forms of evidence** rather than topic coverage lists.

Tyler also distinguishes the *specific functions* of a subject (what only it can do) from its *general functions* (habits of mind it shares with others) — a distinction worth preserving as separate fields, because the two behave differently downstream in organization.

**Known bias:** coverage inflation; specialist-succession framing; topic lists masquerading as objectives.

**Artifact:** `DisciplinaryContributionBrief` — big ideas, modes of inquiry, canonical methods, specific vs. general functions, deliberately excluded content with reasons.

### 3.5 Screen 1 — The educational and social philosophy of the school

**Function:** value selection. Which of the pooled tentative objectives are *worth* pursuing given what this institution believes education is for?

Tyler's requirement is that the institution write its philosophy down as a small set of committing propositions and then use them as a decision rule. His own worked examples of the kind of question a philosophy must settle:

- Should education transmit the existing social order or seek to improve it?
- Should there be a common education for all, or differentiated education by destination (the tracking question)?
- Are democratic values — participation, individual worth, free intelligence over authority — to be treated as goals of instruction or as background assumptions?
- Where is the boundary between the school's responsibility and the family's/community's?

**Operationally the screen produces four verdicts per candidate objective:** *retain*, *reject as inconsistent with stated values*, *reformulate to conform*, or *retain but flag as contested* (surface the disagreement rather than resolve it silently).

This screen is where Source B's is/ought gap is closed. An objective that survives only because "employers want it" must be re-justified in value terms or dropped.

**Artifact:** `PhilosophyStatement` (input, versioned, institution-level) and `PhilosophyScreenLedger` (output: candidate ID, verdict, cited philosophy clause, rationale).

### 3.6 Screen 2 — The psychology of learning

**Function:** feasibility selection. Which of the value-approved objectives can actually be learned, by these learners, in this time, in this order?

Tyler lists the discriminations this screen must make:

1. **Learnable vs. not learnable at all** — separates real learning outcomes from things that are not outcomes of instruction (maturation, fixed traits).
2. **Developmentally appropriate vs. mistimed** — "attainable at this age level," the wrong-grade-level filter. An objective may be perfectly good and simply be scheduled five years early.
3. **Realistic vs. utopian time cost** — objectives requiring years of practice cannot be assigned to one unit. This is the screen that enforces the bounded-objective-count rule.
4. **Coherent vs. mutually interfering** — some objectives are hard to pursue simultaneously; some cluster and can be pursued as one.
5. **Consistent with a defensible theory of learning** — which entails that the institution's learning theory also be stated, since the screen's verdicts depend on it.

Tyler notes the screen has a positive as well as a negative function: it identifies which objectives are *cheap in combination*, letting a set of objectives be attained by a shared body of experience.

**Artifact:** `LearningTheoryStatement` (input, versioned) and `PsychologyScreenLedger` (output: candidate ID, verdict, failure mode, suggested reformulation/regrade/decomposition).

### 3.7 Why the order matters

Philosophy before psychology. If feasibility runs first, the objective set is silently reduced to whatever is easy to teach and easy to test, and the value question never gets asked about anything hard. Running philosophy first means everything cut on feasibility grounds was at least *wanted*, and its removal is a recorded loss rather than an invisible one. Reversing the screens is a real and common defect.

---

## 4. Concrete artifacts

### 4.1 The behavioral objective statement (two-dimensional)

Tyler's format rule: **an objective must name both a behavior and a content area to which the behavior applies.** "To develop critical thinking" fails (no content); "to cover the Reconstruction era" fails (no behavior); "to interpret conflicting primary-source accounts of Reconstruction" passes.

The paired specification generates Tyler's **two-dimensional chart** — behaviors on one axis, content on the other, cells marked where an objective exists ([overview](https://www.studocu.com/row/document/bahauddin-zakariya-university/curriculum-development/rational-models-tyler-taba-model/10087898)):

|                          | Content A | Content B | Content C | Content D |
|--------------------------|-----------|-----------|-----------|-----------|
| Understands concepts     | ✔ | ✔ |   | ✔ |
| Interprets data          | ✔ |   | ✔ |   |
| Applies principles       |   | ✔ | ✔ |   |
| Has broad interests      | ✔ |   |   | ✔ |

The chart is a *diagnostic*, and this is its real value: an empty row means a behavior is claimed but never practised anywhere; an empty column means content is taught with no behavior attached (coverage); a fully dense grid means objective inflation; clustering in one row means the course does one cognitive thing repeatedly. Note that Tyler's behavior axis, in his own examples, includes affective and dispositional entries ("has broad interests") — he was not restricting objectives to the narrowly observable, which the later ISD tradition often did.

**Artifact:** `ObjectiveSpecification` (id, behavior, content, source provenance A/B/C, screen verdicts, evidence type) and `ObjectiveGrid` (the chart plus its density diagnostics).

### 4.2 Learning experience selection criteria

Tyler's key definitional move: a *learning experience* is "the interaction between the learner and the external conditions in the environment to which he can react." Learning happens through the **active behavior of the learner** — it is what the student does, not what the teacher does. Two students in one classroom are having two learning experiences. This is why Tyler says "experiences" and not "content" or "activities."

His five general principles for selecting an experience for a given objective:

1. **Practice** — the student must have opportunity to practise the very behavior the objective names.
2. **Satisfaction** — the student must obtain satisfaction from performing it, or the behavior will not be maintained.
3. **Within range** — the required reactions must be within the student's present capability (a Screen-2 constraint reappearing at the experience level).
4. **Many experiences, one objective** — different experiences can serve the same objective, so the designer has real latitude and can vary for interest and access.
5. **One experience, many outcomes** — the same experience produces multiple outcomes, so experiences must be checked for *unintended* effects as well as intended ones.

Principles 4 and 5 together are the economic core of the model: they are what makes a bounded set of experiences able to carry a larger set of objectives, and they are the reason the mapping between objectives and experiences is many-to-many, never a table of one row each.

**Artifact:** `LearningExperienceSpecification` (id, learner action, conditions provided, objectives served [many], predicted side-effects, satisfaction mechanism, prerequisite check) and `ObjectiveExperienceMatrix` (the many-to-many coverage map; gaps = unserved objectives, orphans = experiences serving nothing).

### 4.3 Organizational principles

Tyler distinguishes **vertical** relationships (same subject, across time) from **horizontal** (across subjects, same time), then names three criteria:

- **Continuity** (vertical) — reiteration of major curriculum elements. If reading complex prose is an objective, complex prose must recur, repeatedly, throughout.
- **Sequence** (vertical) — each successive experience builds on the preceding one and goes *broader and deeper*, not merely again. Tyler's distinction between continuity and sequence is precisely repetition-at-level versus repetition-with-escalation; conflating them yields spiral curricula that spiral flat.
- **Integration** (horizontal) — the learner can relate the element across the subjects and situations in which it appears, producing unified rather than compartmented behavior.

He then specifies the *structural elements* the organization is built from, at three levels:
- **Largest:** specific subjects / broad fields / core / completely undifferentiated structure
- **Middle:** courses, sequences, units
- **Smallest:** lessons, topics, individual learning experiences

And the **organizing threads** ("organizing elements") that run through them — concepts, values, and skills that recur — arranged by **organizing principles** (chronological, increasing breadth of application, increasing range of activities, part-to-whole, concrete-to-abstract). The recurring thread is what makes continuity checkable: without a named thread, "continuity" cannot be verified.

**Artifact:** `OrganizingThreadRegistry` (named threads with the objectives they carry), `SequenceMap` (thread × time, with an escalation descriptor at each recurrence — the escalation descriptor is what distinguishes sequence from mere continuity), `IntegrationMap` (cross-thread contact points).

### 4.4 Evaluation instruments

Tyler's definition of evaluation: the process of determining the degree to which the *behavior changes* named in the objectives have actually occurred. Consequences:

- **Two time points minimum.** Tyler requires an appraisal early and a later one, because evaluation measures *change*, not state. A single post-test cannot satisfy the model. A third, delayed appraisal tests permanence, which he explicitly wants.
- **Any behavior evidence counts.** Paper-and-pencil tests are one instrument among many; observation records, interviews, questionnaires, work samples, and products of student activity are all legitimate. The instrument must fit the behavior, not the other way around.
- **Objectives dictate instruments, one per behavior kind.** Each behavior type in the grid needs an evidence-gathering method capable of detecting it.
- **Results are reported as a profile, not a score.** Tyler wants a picture of the pattern of achievement across objectives, because a single aggregate destroys the diagnostic information.
- **Findings feed back into all four steps.** Failure at evaluation may indict the objective, the experiences, or the organization — the model requires locating which.

Tyler is also explicit that objectives which the institution cares about but cannot yet measure should not be silently dropped; the response is to build a better instrument. Practice mostly ignores this, and the ignoring is the most damaging thing done in his name.

**Artifact:** `EvaluationPlan` (objective ID → instrument → administration schedule with ≥2 points), `EvidenceInstrumentSpecification`, `AchievementProfile`, `RevisionFindings` (defect located at objective / experience / organization level).

---

## 5. Mapping unstructured source material onto the machinery

Given a heap of raw material — transcripts, docs, standards, job postings, forum threads, textbooks, tickets — the routing rule is by *what claim the material licenses*, not by document type:

| Raw material | Source | What it licenses |
|---|---|---|
| Learner interviews, intake surveys, diagnostic results, support tickets, "I don't understand X" threads, prior-course grade distributions | **A** | Entry state, gaps, misconceptions, interest |
| Job postings, incident postmortems, task observations, regulatory requirements, practitioner interviews, tool telemetry, RFPs | **B** | External demand, real task structure, frequency/criticality |
| Textbooks, standards documents, canonical papers, expert interviews, framework docs, conference talks | **C** | Big ideas, modes of inquiry, structure of the field |
| Mission statements, values docs, program charters, DEI/access policy, employer-vs-citizen framing debates | **Screen 1 input** | The philosophy the screen applies |
| Cognitive-load research, prerequisite chains, time-on-task data, known difficulty data, spacing/retrieval evidence | **Screen 2 input** | The learning theory the screen applies |

**Rules that keep this honest:**
- A single document can feed multiple sources; split it into claims and route each claim. A practitioner interview yields Source B (what they do) *and* Source C (how they think about it) *and* often Screen-1 material (what they think it's for).
- Material must be routed *before* objectives are drafted. Post-hoc labeling of provenance is provenance theater.
- Absence of material in a source is a finding. A design with zero Source A evidence should say so on the face of the artifact, not silently proceed.
- Screen inputs must be authored, not inferred from the corpus. If the philosophy is derived from the same material as the objectives, the screen is a tautology and filters nothing. **This is the single most important structural constraint in the whole model.**

---

## 6. Lineage and comparison

**Tyler (1949) → Taba (1962).** Hilda Taba, Tyler's student and Eight-Year Study colleague, kept the logic and inverted the authorship: *Curriculum Development: Theory and Practice* proposes seven steps (diagnosis of needs; formulation of objectives; selection of content; organization of content; selection of learning experiences; organization of learning experiences; determination of what to evaluate and how) built **bottom-up by teachers** producing pilot units that are tested and then generalized, rather than top-down by administrators. Taba's contributions that Tyler lacks: content and experiences are separated into distinct decisions; needs diagnosis is a first-class step; the process is grassroots.

**→ Mastery learning (Bloom, Block, ~1968).** Bloom worked under Tyler at Chicago. The *Taxonomy of Educational Objectives* (1956) is a direct elaboration of Tyler's behavior axis into an ordered scale; mastery learning is Tyler's evaluation loop tightened to unit scale with formative testing and corrective cycles.

**→ ADDIE / ISD (1975).** ADDIE emerged from the Center for Educational Technology at Florida State University for the U.S. Army, formalized as the Interservice Procedures for Instructional Systems Development and adopted across the U.S. Armed Forces ([history](http://www.nwlink.com/~donclark/history_isd/addie.html), [Devlin Peck](https://www.devlinpeck.com/content/history-of-instructional-design)). Its goal was "to increase the effectiveness and efficiency of education and training by fitting instructions to jobs."

**→ UbD (Wiggins & McTighe, 1998).** Backward design: identify desired results → determine acceptable evidence → plan learning experiences. ([Wikipedia](https://en.wikipedia.org/wiki/Understanding_by_Design))

### Tyler vs. ADDIE

| | Tyler | ADDIE |
|---|---|---|
| Unit of work | Curriculum / course | Training intervention |
| Objective sourcing | Three sources, pooled | Needs analysis + **task analysis** — effectively Source B alone |
| Value filter | Screen 1, explicit and named | None. Business/mission requirement is assumed given |
| Feasibility filter | Screen 2, explicit | Distributed into Analysis and Design, rarely named |
| Development/production | Absent (Tyler assumes a teacher) | A named phase (D) — media, materials, build |
| Delivery | Absent | A named phase (I) |
| Evaluation | Pre/post change measurement against objectives | Formative + summative; typically extended by Kirkpatrick levels |
| Governing question | What is worth learning? | Does the intervention close the performance gap? |

ADDIE is Tyler with the philosophy screen removed, the production and delivery phases added, and the source pool narrowed to task analysis. That is exactly the trade you would expect from a military/corporate procurement context, where the value question is settled before the designer is engaged. It is also why ADDIE, imported into general education without restoring Screen 1, reproduces every criticism ever made of Tyler in stronger form.

### Tyler vs. UbD

| | Tyler | UbD |
|---|---|---|
| Order | Objectives → experiences → organization → evaluation | Results → **evidence** → experiences |
| Key inversion | — | Assessment precedes activity planning (Tyler's step 4 moved to position 2) |
| Objective form | Behavior + content pair | Enduring understandings, essential questions, transfer goals, knowledge/skill |
| Content triage | Implicit in the screens | Explicit: worth being familiar with / important to know and do / enduring understanding |
| Theory of the good outcome | Behavior change | **Understanding**, operationalized as six facets (explain, interpret, apply, have perspective, empathize, self-knowledge) |
| Attitude to objectives | Precision is the goal | Precision at the wrong grain size is the enemy; "twin sins" are activity-oriented and coverage-oriented design |
| Source discipline | Three named sources with known biases | Weak — standards are the usual sole input |
| Value filter | Named screen | Diffuse; carried inside "enduring understanding" judgments |

UbD's real innovation over Tyler is the **evidence-before-activities** reordering, which closes the gap where designers plan activities they like and retrofit assessment. Its regression from Tyler is the loss of the sources-and-screens discipline: UbD tells you to identify desired results but is comparatively silent on where results come from and what authorizes them. The two are complementary rather than rival — **Tyler's front end (sources + screens) grafted onto UbD's middle (evidence before experiences) is stronger than either alone**, and is the shape a modern pipeline should take.

### Where the model is used today

- **Outcomes-based education and programmatic accreditation.** OBE is directly rooted in Tyler's achievement-of-desired-outcomes logic ([EJ1180613](https://files.eric.ed.gov/fulltext/EJ1180613.pdf)). ABET, the Washington Accord signatories, and national accreditation bodies embed it; outcomes-based qualification frameworks are now a global phenomenon in vocational education across both the global North and South ([Taylor & Francis](https://think.taylorandfrancis.com/special_issues/debating-outcomes-based-qualifications/)).
- **Health-professions and nursing curriculum design**, where competency mapping to practice demands is the norm.
- **Higher-ed program review**: program learning outcomes → curriculum maps (Tyler's grid, renamed) → assurance-of-learning evidence (Tyler's step 4).
- **Corporate L&D and compliance training**, via ADDIE.
- **K–12 standards alignment**, where the standards document has largely replaced Source C and, in weaker implementations, all three sources.

---

## 7. Criticisms

### 7.1 Kliebard (1970)

Herbert Kliebard, "The Tyler Rationale," *The School Review* 78(2), 259–272 — the canonical attack, reprinted in Pinar's *Curriculum Theorizing* (1975) and Kliebard's *Forging the American Curriculum* (1992) ([citation record](https://stars.library.ucf.edu/cirs/1411/)). Its principal charges:

1. **It is a production model.** "In the final analysis," Tyler's rationale is a production model of curriculum and instruction — raw material in, specified product out, with the student as material.
2. **Bobbitt in disguise.** Kliebard associates the rationale with Bobbitt's job analysis on the grounds that both take society as a source of objectives. *This charge has been directly rebutted:* Antonelli (1972) notes that job analysis drew almost exclusively on society, whereas Tyler also draws on the learner and on subject matter — the three-source structure is precisely a rejection of Bobbitt's monopoly.
3. **The screens are empty.** Tyler names philosophy as a screen but supplies no way to choose or justify a philosophy; the rationale is procedurally complete and substantively vacant, so it will faithfully implement any values, good or bad. This is the most durable of the charges.
4. **Selecting from an infinite pool is not specified.** Tyler gives no principled account of how the source pool is bounded or how competing objectives are traded off once both pass the screens.
5. **Ahistoricism in the field it spawned.** Kliebard's broader lament was a "lack of historical perspective" in curriculum work, "in which new breakthroughs are solemnly proclaimed when in fact they represent minor modifications of early proposals."

The critique became near-orthodoxy among reconceptualist curriculum theorists through the 1970s–80s.

### 7.2 The technocratic/reductionist family

- **Measurability drives the curriculum.** Moral and affective objectives — increasing respect for others, developing intellectual humility — resist measurable statement and are therefore quietly dropped as too hard to assess ([EJ1180613](https://files.eric.ed.gov/fulltext/EJ1180613.pdf)). The tail wags the dog: the evaluation instrument selects the objective.
- **Managerial de-skilling.** The rationale has been read as "a management device designed to reduce teacher creativity and flexibility within the classroom" (ibid.), with excessive rigidity that does not accommodate unexpected turns in teaching.
- **Unintended outcomes are invisible.** Prespecified objectives make the model structurally blind to what it did not predict, which "could consequently limit inquiry and ingenuity" (ibid.). Eisner's *expressive outcomes* and *educational connoisseurship* are the standard counter-proposal.
- **Means–ends separation is false to practice.** Teachers do not fix ends and then choose means; ends emerge in the doing. Schwab's *practical* and *deliberative* mode is the alternative.
- **Consensus assumption.** The philosophy screen presumes an institution has a coherent, shared philosophy. Most do not; the screen then either rubber-stamps or masks a political fight.
- **Cost.** OBE implementations are resource-intensive, demanding substantial time and administrative effort ([Taylor & Francis](https://think.taylorandfrancis.com/special_issues/debating-outcomes-based-qualifications/)), and outcomes-based qualifications remain genuinely contested rather than settled.

### 7.3 What defenders say

Recent reappraisals argue much of the attack targets the flattened textbook Tyler rather than the 1949 text ([Prospects 2023, "The Tyler rationale: A reappraisal and rereading"](https://link.springer.com/article/10.1007/s11125-023-09643-y); ["In Defense of the Tyler Rationale"](https://wap.hillpublisher.com/ArticleDetails.aspx?cid=3386)). Specifically: Tyler's behavior axis includes dispositions and interests, not just observable acts; he insists objectives cannot be derived from society alone; he requires the feedback loop; he warns against objective inflation; and he explicitly refuses to prescribe a philosophy because prescribing one is not a curriculum theorist's job. The defense concedes charge 3 (the empty screen) and answers charges 1 and 2.

### 7.4 What practitioners actually do

| Problem | Mitigation in practice |
|---|---|
| Affective/moral objectives dropped | Carry them as *explicitly unassessed but stated* objectives; use portfolio, reflection, and observation instruments rather than tests |
| Blindness to unintended outcomes | Add a goal-free / emergent-outcomes evaluation pass (Scriven); Tyler's own experience-principle 5 already requires side-effect prediction |
| Teacher de-skilling | Taba's bottom-up authorship; specify objectives at course level and leave experience selection to instructors |
| Empty philosophy screen | Force a written, versioned, signed philosophy statement with named tensions; treat "contested" as a legal verdict, not a failure |
| Rigidity | Treat the four steps as a loop with explicit revision triggers; version objectives |
| Over-specification | Cap objective count per unit of instructional time; use UbD's three-tier triage before the screens |
| Objectives divorced from assessment | Adopt UbD's evidence-before-activities ordering inside Tyler's step 2/4 |

---

## 8. Common failure modes

1. **Sources collapse to one.** Usually a standards document or a job description. Provenance is then uniform and the pooling logic is dead.
2. **Screens are skipped entirely.** The most common defect by far. Candidate objectives become final objectives with no recorded filtering. Every downstream artifact then carries unfalsifiable authority.
3. **Screens are run in the wrong order.** Feasibility first silently deletes everything hard before anyone asks whether it mattered.
4. **The philosophy is derived from the corpus.** Screen 1 then agrees with everything and filters nothing.
5. **Topics dressed as objectives.** "Understand recursion" — no behavior, no evidence type. The grid catches this as an empty behavior cell.
6. **Objective inflation.** 40 objectives for a 6-hour course. Tyler names this explicitly; the time-budget check is a hard constraint, not advice.
7. **Coverage columns.** Content present in the grid with no behavior attached — the content got in because a specialist named it, and Source C's succession bias went unchecked.
8. **One-to-one objective→activity mapping.** Violates experience principles 4 and 5; produces bloated courses and forecloses variation for access.
9. **Continuity mistaken for sequence.** The same thread recurs at the same level. Every recurrence needs a stated escalation.
10. **Integration asserted, never mapped.** "Interdisciplinary" with no named contact points between threads.
11. **Single-point evaluation.** Post-test only; measures state, not change; cannot distinguish learning from prior knowledge.
12. **Instrument-driven objective selection.** Only what the available test can detect survives.
13. **Loop never closes.** Evaluation results are reported and filed; objectives are never revised; the defect is never localized to objective vs. experience vs. organization.
14. **Provenance theater.** Sources labeled after the fact to satisfy a template.

---

## 9. Mechanization Notes

Design target: a discrete-step pipeline where each step is an agent or agent group with typed inputs, named output artifacts, and a defined human review gate. The **screens are the highest-value automation target** and also the highest-risk, because they are the steps where the model's authority actually lives.

### Global invariants

- **Every objective carries provenance for its whole life.** `ObjectiveSpecification` includes source IDs, screen verdicts with cited clauses, and a revision history. An objective that cannot name its source or its screen verdicts is invalid and should fail validation, not warn.
- **`PhilosophyStatement` and `LearningTheoryStatement` are authored inputs, versioned independently of the corpus, and immutable during a run.** Deriving them from the corpus is the failure that silently disables both screens. If the pipeline generates a *draft* philosophy, it must be signed by a human before any objective is screened against it, and the signature must be recorded in the ledger.
- **Screen agents must not be the same agent that generated the candidate.** Self-screening yields near-100% pass rates. Generation and critique must be separate calls with separate context.
- **Reject-with-reason, never silent-drop.** Every rejected candidate is retained in the ledger. The set of rejections is a primary human review artifact — the interesting failure is usually what got cut, not what survived.

---

### Step 0 — Corpus intake and claim routing

- **Inputs:** raw material set (documents, transcripts, URLs, code, tickets); `DomainScopeStatement`.
- **Process:** split each document into atomic claims; route each claim to Source A / B / C / Screen-1 input / Screen-2 input / discard, with confidence and a quoted span.
- **Outputs:** `SourcedClaimIndex` (claim ID, text, span, document, route, confidence); `RoutingCoverageReport` (claim count per source, gaps flagged).
- **Judgment required:** distinguishing a claim about learners from a claim about the world from a claim about the discipline — a practitioner interview typically yields all three, and the sentence-level distinction is genuinely subtle. Also: recognizing normative claims that belong in Screen-1 input rather than in Source B, which is the is/ought split Tyler explicitly defers.
- **Human review before proceeding:** the `RoutingCoverageReport`. A source with near-zero claims means either the corpus is deficient or the router is miscalibrated, and the two look identical downstream. Spot-check 20–30 routed claims. **Confirm no normative material leaked into Source B.**

### Step 1a — Source analysis (three parallel agents)

- **Inputs:** `SourcedClaimIndex` filtered per source; `DomainScopeStatement`.
- **Process:** three independent agents, deliberately not sharing context, each synthesizing its source with its bias made explicit.
- **Outputs:** `LearnerAnalysisDossier`, `ContemporaryDemandAnalysis`, `DisciplinaryContributionBrief` — each with an explicit `KnownBiasStatement` and an evidence-thinness flag.
- **Judgment required:** for Source A, inferring a norm to define gaps against without importing an unstated philosophy. For Source B, separating what is *done* from what is *worth doing* and leaving the latter for Screen 1. For Source C, resisting the specialist-succession framing — the agent must be prompted with Tyler's actual question ("what can this subject do for someone who will never specialize in it?"), because the default answer to "what should be taught?" is a syllabus.
- **Human review:** Source C's brief specifically. Coverage inflation is the failure that most reliably survives to the end, and it looks reasonable at every intermediate step.

### Step 1b — Candidate objective generation

- **Inputs:** the three dossiers; `TimeBudget`.
- **Process:** generate a deliberately over-large pool of tentative general objectives, each tagged with contributing source IDs. Over-generation is correct here; the screens exist to cut.
- **Outputs:** `CandidateObjectivePool` (id, statement, contributing sources, supporting claim IDs).
- **Judgment required:** stating objectives at a consistent grain size, and generating genuinely source-distinct candidates rather than three paraphrases of the same thing.
- **Human review:** none required to proceed — this pool is provisional by construction. Cheap to inspect for grain-size drift.

### Step 2 — Screen 1: philosophy (automated critique pass)

- **Inputs:** `CandidateObjectivePool`; `PhilosophyStatement` (human-authored, versioned, signed).
- **Process:** per candidate, an agent with **no access to the generating rationale** returns one of `retain` / `reject` / `reformulate` / `contested`, **each with a cited clause of the philosophy statement**. Uncited verdicts are invalid and must be rejected by the harness — the citation requirement is what makes the screen auditable and what prevents it from degenerating into generic plausibility judgment.
- **Outputs:** `PhilosophyScreenLedger`; `ReformulatedObjectives`; `ContestedObjectivesQueue`.
- **Judgment required:** genuine value arbitration — Tyler's transmit-vs-improve, common-vs-differentiated, school-vs-family boundary questions. This is the least automatable step in the model and should be treated as the least trustworthy output of the pipeline. An agent will reliably produce fluent value reasoning; whether it produces *this institution's* value reasoning depends entirely on the specificity of `PhilosophyStatement`. A vague statement yields a screen that passes everything while appearing to work — the worst possible failure, because it is invisible.
- **Mitigations worth building in:** run the screen with the philosophy clauses as retrieval targets, so a verdict that cannot retrieve a relevant clause is forced to `contested` rather than inventing a justification. Run a second adversarial pass that argues the opposite verdict for every `retain`; disagreement between passes routes to human.
- **Human review — mandatory gate.** Review **every** `reject` and every `contested`. The rejections are where the institution's values were actually exercised, and a wrong rejection is permanent and unobservable downstream. Sample the `retain`s. Confirm the cited clauses genuinely support the verdicts rather than being decorative.

### Step 3 — Screen 2: psychology (automated filter pass)

- **Inputs:** philosophy-approved objectives; `LearningTheoryStatement`; `LearnerAnalysisDossier` (entry state, prerequisites); `TimeBudget`.
- **Process:** per objective, five checks, each returning a verdict plus a remedy — learnable / age-and-entry-appropriate / time-affordable / non-interfering / theory-consistent. Then a **positive** pass: cluster objectives attainable by shared experience, and a **budget** pass: total estimated time vs. `TimeBudget`, forcing prioritization if over.
- **Outputs:** `PsychologyScreenLedger`; `ObjectiveClusterMap`; `TimeBudgetReconciliation`; `DeferredObjectives` (right objective, wrong stage — retained with a target stage, not discarded).
- **Judgment required:** time-to-mastery estimation, which agents do poorly and confidently; prerequisite-chain reasoning against actual entry state rather than an idealized one; distinguishing "not learnable" from "not learnable *by this route*."
- **Human review — mandatory gate.** The `TimeBudgetReconciliation` and the cut list. This is the step where an over-ambitious design becomes an honest one, and the trade-offs are exactly the ones an instructor has calibration for and an agent does not. Verify that nothing was cut *only* because it is hard to assess — that is the reductionist failure entering the pipeline, and it enters here.

### Step 4 — Objective specification and grid construction

- **Inputs:** screened objectives.
- **Process:** rewrite each as a behavior+content pair; place on the two-dimensional grid; run density diagnostics (empty rows, empty columns, over-dense cells, single-row clustering).
- **Outputs:** `ObjectiveSpecification` set; `ObjectiveGrid`; `GridDiagnosticsReport`.
- **Judgment required:** deciding whether a behavior-less objective should be rewritten or dropped; keeping affective/dispositional behaviors on the axis rather than letting the rewrite silently narrow everything to the testable. Prompt explicitly against that narrowing — it is the default drift.
- **Human review:** the `GridDiagnosticsReport`. Cheap, high-signal, and legible to a non-specialist. A good gate for a lightweight approval.

### Step 5 — Learning experience selection

- **Inputs:** `ObjectiveSpecification` set; `ObjectiveClusterMap`; delivery constraints.
- **Process:** generate experiences against Tyler's five principles; build the many-to-many `ObjectiveExperienceMatrix`; predict side-effects per experience (principle 5).
- **Outputs:** `LearningExperienceSpecification` set; `ObjectiveExperienceMatrix`; `PredictedSideEffectRegister`; `CoverageGapReport` (unserved objectives, orphan experiences).
- **Judgment required:** the satisfaction criterion — whether a learner will actually find the experience rewarding — which is a claim about real people that an agent cannot verify. Also resisting the one-objective-one-activity default, which produces a plausible and badly bloated course.
- **Human review:** the `PredictedSideEffectRegister` and the satisfaction claims. Side-effect prediction is where a well-formed course quietly teaches the wrong lesson (e.g. that the subject is tedious, or that the answer is always in the last paragraph).

### Step 6 — Organization

- **Inputs:** experiences; objectives; calendar/structure constraints.
- **Process:** extract organizing threads; sequence them with a **required escalation descriptor at every recurrence**; map integration contact points; verify continuity (each thread recurs ≥ n times) and sequence (each recurrence escalates) as separate checks.
- **Outputs:** `OrganizingThreadRegistry`; `SequenceMap`; `IntegrationMap`; `ContinuitySequenceAudit`.
- **Judgment required:** choosing the organizing principle (chronological / part-to-whole / concrete-to-abstract / increasing breadth) — this is a real design decision with pedagogical consequences and should be a human choice presented with options, not an agent default.
- **Human review:** the `ContinuitySequenceAudit`, specifically the escalation descriptors. Flat spirals are mechanically detectable if escalation is a required field, which is the main reason to make it one.

### Step 7 — Evaluation design

- **Inputs:** `ObjectiveSpecification` set; `SequenceMap`.
- **Process:** per objective, select an instrument matched to the behavior type; schedule **at least two** administration points (early + late; optionally delayed for permanence); define the `AchievementProfile` reporting shape.
- **Outputs:** `EvaluationPlan`; `EvidenceInstrumentSpecification` set; `AchievementProfileSchema`; `UnmeasuredObjectiveRegister`.
- **Judgment required:** instrument validity — whether the evidence actually indicates the named behavior — and honest handling of objectives with no adequate instrument. The `UnmeasuredObjectiveRegister` is the pipeline's structural answer to the measurability critique: objectives without instruments are recorded and retained as unassessed, never deleted. **Deleting them is the single most damaging thing the pipeline could do, and it is also the path of least resistance, so it must be prevented structurally rather than by prompt.**
- **Human review — mandatory gate.** The `UnmeasuredObjectiveRegister` and instrument validity. Also confirm no single-point evaluation slipped in.

### Step 8 — Feedback loop

- **Inputs:** `AchievementProfile` from a real delivery; all prior artifacts.
- **Process:** localize each shortfall to objective / experience / organization / instrument; emit typed revision proposals against the specific artifact.
- **Outputs:** `RevisionFindings`; `ObjectiveRevisionProposals`; `NextCycleBacklog`.
- **Judgment required:** attribution. A missed objective may indict any of four artifacts, and the evidence rarely distinguishes them cleanly. Agents will confidently attribute; the confidence is not warranted.
- **Human review — mandatory gate.** All attributions before any artifact is revised. Wrong attribution compounds across cycles.

### Summary of gates

| Gate | Artifact reviewed | Why it cannot be skipped |
|---|---|---|
| After Step 0 | `RoutingCoverageReport` | Source starvation is invisible downstream |
| After Step 1a | `DisciplinaryContributionBrief` | Coverage inflation survives every later step |
| After Step 2 | Every `reject` + `contested` | Value judgments; wrong cuts are unrecoverable |
| After Step 3 | `TimeBudgetReconciliation` + cut list | Where reductionism enters; needs real calibration |
| After Step 4 | `GridDiagnosticsReport` | Cheap, legible, high-signal |
| After Step 5 | `PredictedSideEffectRegister` | Where courses teach the wrong lesson |
| After Step 6 | `ContinuitySequenceAudit` | Flat spirals |
| After Step 7 | `UnmeasuredObjectiveRegister` | The measurability critique, structurally answered |
| After Step 8 | `RevisionFindings` attributions | Wrong attribution compounds |

**The load-bearing insight for a mechanized pipeline:** the three sources are a *fan-out* problem (parallel, cheap, agent-suited, high tolerance for over-generation) and the two screens are a *fan-in* problem (serial, expensive, judgment-dense, where over-generation must be paid for). Automating the fan-out is nearly free and clearly valuable. Automating the fan-in is where the model's authority lives, and every screen verdict must be citable to a human-authored statement or the pipeline is producing well-formatted arbitrariness — which is precisely Kliebard's charge 3, reproduced at machine speed.

---

## Sources

- [Understanding the Tyler rationale: *Basic Principles of Curriculum and Instruction* in historical context — Prospects (PDF)](https://www.redalyc.org/pdf/4774/477455340011.pdf)
- [The Tyler rationale: A reappraisal and rereading — Prospects (2023)](https://link.springer.com/article/10.1007/s11125-023-09643-y)
- [Kliebard, "The Tyler Rationale," *The School Review* 78(2), 1970 — citation record](https://stars.library.ucf.edu/cirs/1411/)
- [ASCD — Curriculum Development: What Would Tyler Do?](https://www.ascd.org/blogs/curriculum-development-what-would-tyler-do)
- [Considering Tyler's Curriculum Model in Health and Social Care Education — ERIC EJ1180613 (PDF)](https://files.eric.ed.gov/fulltext/EJ1180613.pdf)
- [In Defense of the Tyler Rationale — Hill Publishing Group](https://wap.hillpublisher.com/ArticleDetails.aspx?cid=3386)
- [Rational Models: An Overview of Tyler & Taba Curriculum Theories](https://www.studocu.com/row/document/bahauddin-zakariya-university/curriculum-development/rational-models-tyler-taba-model/10087898)
- [History of the ADDIE Model — Don Clark](http://www.nwlink.com/~donclark/history_isd/addie.html)
- [The Full History of Instructional Design — Devlin Peck](https://www.devlinpeck.com/content/history-of-instructional-design)
- [Understanding by Design — Wikipedia](https://en.wikipedia.org/wiki/Understanding_by_Design)
- [Debating outcomes-based qualifications — Taylor & Francis](https://think.taylorandfrancis.com/special_issues/debating-outcomes-based-qualifications/)
- [Innovative Models of Curriculum Design: Tyler, Taba, and Beyond](https://teachers.institute/knowledge-curriculum/innovative-curriculum-design-models/)
